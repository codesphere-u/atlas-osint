"""Public records, registries, news archives and public documents."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.robotparser import RobotFileParser

from engine.normalization.identifiers import name_key, org_name_key
from integrations.sources.base import (
    AuthRequirement,
    CollectionContext,
    LegalInfo,
    RateLimit,
    SourceAdapter,
    SourceError,
    SourceMetadata,
    parse_datetime,
)
from shared.types import (
    AccessMethod,
    AdapterStatus,
    Evidence,
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    MatchType,
    Reliability,
    SourceCategory,
)

ORG_FIELDS = [
    "legal_name",
    "registry_id",
    "id_scheme",
    "jurisdiction",
    "legal_form",
    "status",
    "registered_country",
    "registered_city",
    "incorporation_date",
    "dissolution_date",
    "registry_url",
    "tickers",
    "exchanges",
    "sic_description",
    "fiscal_year_end",
    "recent_filings",
    "former_names",
    "parent_lei",
    "company_type",
    "relationship",
    "subsidiary_count",
]


def _org_match(query: str, candidate: str) -> MatchType:
    return MatchType.EXACT if org_name_key(query) == org_name_key(candidate) else MatchType.SIMILAR


class GleifAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="gleif",
        display_name="GLEIF Legal Entity Identifier (LEI) index",
        description="Global register of legal entities with LEIs, legal names, jurisdictions and parents.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.ORGANIZATION],
        access_method=AccessMethod.OFFICIAL_API,
        homepage="https://www.gleif.org/en/lei-data/gleif-api",
        rate_limit=RateLimit(requests=60, per_seconds=60),
        legal=LegalInfo(
            license="CC0-1.0",
            terms_url="https://www.gleif.org/en/meta/lei-data-terms-of-use",
            restrictions="Open data, free of charge, no restrictions on re-use.",
        ),
        fields=ORG_FIELDS,
        freshness="daily",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        records: list[dict[str, Any]] = []
        # Exact legal-name match first; fall back to GLEIF full-text search.
        for param in ("filter[entity.legalName]", "filter[fulltext]"):
            resp = await self.fetch(
                ctx,
                "https://api.gleif.org/api/v1/lei-records",
                params={param: identifier.value, "page[size]": 5},
                headers={"Accept": "application/vnd.api+json"},
            )
            if not resp.ok:
                raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
            records = resp.json().get("data") or []
            if records:
                break
        out = []
        for rec in records:
            lei = rec.get("id")
            a = rec.get("attributes") or {}
            ent = a.get("entity") or {}
            name = (ent.get("legalName") or {}).get("name") or lei
            addr = ent.get("legalAddress") or {}
            attrs = {
                "legal_name": name,
                "registry_id": lei,
                "id_scheme": "lei",
                "jurisdiction": ent.get("jurisdiction"),
                "legal_form": (ent.get("legalForm") or {}).get("id"),
                "status": ent.get("status"),
                "registered_country": addr.get("country"),
                "registered_city": addr.get("city"),
                "incorporation_date": ent.get("creationDate"),
                "registry_url": f"https://search.gleif.org/#/record/{lei}",
            }
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="legal_entity_record",
                    title=f"LEI {lei}: {name}",
                    description=f"Legal entity '{name}' ({attrs['jurisdiction']}), entity status {attrs['status']}.",
                    url=str(attrs["registry_url"]),
                    attributes=attrs,
                    match_type=_org_match(identifier.value, str(name)),
                    published_at=parse_datetime(ent.get("creationDate")),
                    entity_hint=f"organization:lei:{lei}",
                    entity_kind="organization",
                    claim_key=f"org.lei:{lei}",
                )
            )
        exact = [f for f in out if f.match_type == MatchType.EXACT][:2]
        for f in exact:
            out.extend(
                await self._hierarchy(
                    ctx, identifier, str(f.attributes["registry_id"]), str(f.attributes["legal_name"])
                )
            )
        return out

    def _org_finding(
        self,
        identifier: Identifier,
        rec: dict[str, Any],
        relationship: str,
        title: str,
        description: str,
        linked: list[LinkedIdentifier],
    ) -> Finding:
        lei = str(rec.get("id"))
        ent = (rec.get("attributes") or {}).get("entity") or {}
        name = (ent.get("legalName") or {}).get("name") or lei
        return self.finding(
            module="public_records",
            subject=identifier,
            finding_type="corporate_relationship",
            title=title.format(name=name, lei=lei),
            description=description.format(name=name, lei=lei),
            url=f"https://search.gleif.org/#/record/{lei}",
            attributes={
                "legal_name": name,
                "registry_id": lei,
                "id_scheme": "lei",
                "jurisdiction": ent.get("jurisdiction"),
                "status": ent.get("status"),
                "relationship": relationship,
                "registry_url": f"https://search.gleif.org/#/record/{lei}",
            },
            linked=linked,
            match_type=MatchType.RELATED,
            entity_hint=f"organization:lei:{lei}",
            entity_kind="organization",
            claim_key=f"org.relationship:{relationship}:{lei}",
        )

    async def _hierarchy(self, ctx: CollectionContext, identifier: Identifier, lei: str, name: str) -> list[Finding]:
        """GLEIF Level 2 data: who owns whom (accounting consolidation), as reported by the entities."""
        base = f"https://api.gleif.org/api/v1/lei-records/{quote(lei)}"
        hdr = {"Accept": "application/vnd.api+json"}
        child_link = Identifier(type=IdentifierType.ORGANIZATION, value=name)
        out: list[Finding] = []
        seen: set[str] = set()
        for rel, label in (("direct-parent", "direct_parent"), ("ultimate-parent", "ultimate_parent")):
            resp = await self.fetch(ctx, f"{base}/{rel}", headers=hdr)
            if resp.status_code == 404 or not resp.ok:
                continue
            rec = resp.json().get("data") or {}
            if not isinstance(rec, dict) or not rec.get("id") or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            out.append(
                self._org_finding(
                    identifier,
                    rec,
                    label,
                    "{name} is the " + label.replace("_", " ") + f" of {name}",
                    "GLEIF Level 2 data reports {name} (LEI {lei}) as the "
                    + label.replace("_", " ")
                    + f" of {name} (accounting consolidation, self-reported by the entity).",
                    [
                        LinkedIdentifier(
                            identifier=child_link, relation="parent_of", entity_key=f"organization:lei:{lei}"
                        )
                    ],
                )
            )
        resp = await self.fetch(ctx, f"{base}/direct-children", params={"page[size]": 10}, headers=hdr)
        if resp.ok:
            body = resp.json()
            total = ((body.get("meta") or {}).get("pagination") or {}).get("total")
            parent_link = Identifier(type=IdentifierType.ORGANIZATION, value=name)
            for rec in body.get("data") or []:
                f = self._org_finding(
                    identifier,
                    rec,
                    "direct_subsidiary",
                    "Subsidiary: {name}",
                    "GLEIF Level 2 data reports {name} (LEI {lei}) as a direct subsidiary of "
                    + name
                    + (f"; {total} direct subsidiaries are reported in total." if total else "."),
                    [
                        LinkedIdentifier(
                            identifier=parent_link, relation="subsidiary_of", entity_key=f"organization:lei:{lei}"
                        )
                    ],
                )
                if total:
                    f.attributes["subsidiary_count"] = total
                out.append(f)
        return out


_SEC_TICKERS: list[dict[str, Any]] = []


class SecEdgarAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="sec_edgar",
        display_name="U.S. SEC EDGAR",
        description="Registrant metadata and recent filings of SEC-reporting companies.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.ORGANIZATION],
        access_method=AccessMethod.OFFICIAL_API,
        homepage="https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        auth=AuthRequirement(
            required=True,
            kind="user_agent_contact",
            settings_fields=["sec_edgar_user_agent"],
            how_to_obtain="SEC fair-access policy requires a User-Agent with a contact email, "
            "e.g. 'Example Org security@example.org'.",
        ),
        rate_limit=RateLimit(requests=8, per_seconds=1, notes="SEC limit is 10 req/s"),
        legal=LegalInfo(
            terms_url="https://www.sec.gov/privacy#security",
            license="U.S. public domain",
            restrictions="Fair-access policy: identify yourself and stay below 10 requests/second.",
        ),
        fields=ORG_FIELDS,
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        ua = {"User-Agent": ctx.settings.sec_edgar_user_agent or ""}
        if not _SEC_TICKERS:
            resp = await self.fetch(ctx, "https://www.sec.gov/files/company_tickers.json", headers=ua)
            if not resp.ok:
                raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
            _SEC_TICKERS.extend(resp.json().values())
        q = name_key(identifier.value)
        matches = [t for t in _SEC_TICKERS if q and q in name_key(str(t.get("title", "")))][:3]
        out = []
        for t in matches:
            cik = int(t["cik_str"])
            sub = await self.fetch(ctx, f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=ua)
            if not sub.ok:
                continue
            d = sub.json()
            recent = (d.get("filings") or {}).get("recent") or {}
            filings = [
                {"form": f, "date": dt}
                for f, dt in list(zip(recent.get("form") or [], recent.get("filingDate") or [], strict=False))[:5]
            ]
            attrs = {
                "legal_name": d.get("name"),
                "registry_id": f"{cik:010d}",
                "id_scheme": "sec_cik",
                "jurisdiction": d.get("stateOfIncorporation"),
                "tickers": d.get("tickers"),
                "exchanges": d.get("exchanges"),
                "sic_description": d.get("sicDescription"),
                "fiscal_year_end": d.get("fiscalYearEnd"),
                "recent_filings": filings,
                "former_names": [f.get("name") for f in d.get("formerNames") or []][:5],
                "registry_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
            }
            links = []
            website = d.get("website")
            if website:
                from integrations.sources.username import website_links

                links = website_links(website)
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="securities_registrant",
                    title=f"SEC registrant {d.get('name')} (CIK {cik})",
                    description=f"{d.get('name')} files with the SEC (SIC: {d.get('sicDescription')}); "
                    f"tickers: {', '.join(d.get('tickers') or []) or 'none'}.",
                    url=attrs["registry_url"],
                    attributes=attrs,
                    linked=links,
                    match_type=_org_match(identifier.value, d.get("name") or ""),
                    raw=sub.content,
                    entity_hint=f"organization:sec:{cik}",
                    entity_kind="organization",
                    claim_key=f"org.sec:{cik}",
                )
            )
        return out


class CompaniesHouseAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="companies_house",
        display_name="UK Companies House",
        description="Official register of UK companies: status, type, incorporation date.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.ORGANIZATION],
        access_method=AccessMethod.OFFICIAL_API,
        homepage="https://developer.company-information.service.gov.uk/",
        auth=AuthRequirement(
            required=True,
            kind="api_key",
            settings_fields=["companies_house_api_key"],
            how_to_obtain="Register a free application on the Companies House developer hub.",
        ),
        rate_limit=RateLimit(requests=600, per_seconds=300),
        legal=LegalInfo(
            license="Open Government Licence v3.0",
            terms_url="https://developer.company-information.service.gov.uk/terms-and-conditions",
            restrictions="Officer/PSC personal data is not collected by this adapter.",
        ),
        fields=ORG_FIELDS,
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        import base64

        key = ctx.secret("companies_house_api_key") or ""
        auth = base64.b64encode(f"{key}:".encode()).decode()
        resp = await self.fetch(
            ctx,
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": identifier.value, "items_per_page": 5},
            headers={"Authorization": f"Basic {auth}"},
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        out = []
        for c in resp.json().get("items") or []:
            number = c.get("company_number")
            attrs = {
                "legal_name": c.get("title"),
                "registry_id": number,
                "id_scheme": "gb_companies_house",
                "jurisdiction": "GB",
                "status": c.get("company_status"),
                "company_type": c.get("company_type"),
                "incorporation_date": c.get("date_of_creation"),
                "dissolution_date": c.get("date_of_cessation"),
                "registry_url": f"https://find-and-update.company-information.service.gov.uk/company/{number}",
            }
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="company_registration",
                    title=f"Companies House {number}: {c.get('title')}",
                    description=f"UK company '{c.get('title')}' ({c.get('company_type')}), status "
                    f"{c.get('company_status')}, incorporated {c.get('date_of_creation')}.",
                    url=attrs["registry_url"],
                    attributes=attrs,
                    match_type=_org_match(identifier.value, c.get("title") or ""),
                    published_at=parse_datetime(c.get("date_of_creation")),
                    entity_hint=f"organization:gb_ch:{number}",
                    entity_kind="organization",
                    claim_key=f"org.gb_ch:{number}",
                )
            )
        return out


class OpenCorporatesAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="opencorporates",
        display_name="OpenCorporates",
        description="Aggregated company registry data from 140+ jurisdictions.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.ORGANIZATION],
        access_method=AccessMethod.LICENSED_API,
        homepage="https://api.opencorporates.com/documentation/API-Reference",
        auth=AuthRequirement(
            required=True,
            kind="api_key",
            settings_fields=["opencorporates_api_token"],
            how_to_obtain="Request an API token from OpenCorporates (free for qualifying public-benefit projects).",
        ),
        rate_limit=RateLimit(requests=1, per_seconds=1),
        legal=LegalInfo(
            license="ODbL (share-alike, attribution required)",
            terms_url="https://opencorporates.com/terms-of-use/",
            restrictions="Attribution to OpenCorporates is required in reports; share-alike for derived data.",
        ),
        fields=ORG_FIELDS,
        freshness="varies by jurisdiction",
        reliability=Reliability.C,
        citation_format='Data from OpenCorporates (ODbL). "{title}". {url}. Retrieved {collected_at}.',
        default_enabled=False,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx,
            "https://api.opencorporates.com/v0.4/companies/search",
            params={"q": identifier.value, "per_page": 5, "api_token": ctx.secret("opencorporates_api_token")},
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        out = []
        for item in ((resp.json().get("results") or {}).get("companies")) or []:
            c = item.get("company") or {}
            jur, number = c.get("jurisdiction_code"), c.get("company_number")
            attrs = {
                "legal_name": c.get("name"),
                "registry_id": f"{jur}/{number}",
                "id_scheme": "opencorporates",
                "jurisdiction": jur,
                "status": c.get("current_status"),
                "company_type": c.get("company_type"),
                "incorporation_date": c.get("incorporation_date"),
                "dissolution_date": c.get("dissolution_date"),
                "registry_url": c.get("opencorporates_url"),
            }
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="company_registration",
                    title=f"{c.get('name')} ({jur} {number})",
                    description=f"Company '{c.get('name')}' registered in {jur} with number {number}; "
                    f"status {c.get('current_status')}.",
                    url=c.get("opencorporates_url") or "https://opencorporates.com/",
                    attributes=attrs,
                    match_type=_org_match(identifier.value, c.get("name") or ""),
                    published_at=parse_datetime(c.get("incorporation_date")),
                    entity_hint=f"organization:oc:{jur}/{number}",
                    entity_kind="organization",
                    claim_key=f"org.oc:{jur}/{number}",
                )
            )
        return out


class GdeltNewsAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="gdelt_news",
        display_name="GDELT 2.0 DOC news archive",
        description="Worldwide online news coverage mentioning an exact phrase (last ~3 months).",
        category=SourceCategory.NEWS,
        input_types=[IdentifierType.NAME, IdentifierType.ORGANIZATION],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        rate_limit=RateLimit(requests=1, per_seconds=5),
        legal=LegalInfo(
            terms_url="https://www.gdeltproject.org/about.html#termsofuse",
            restrictions="Unlimited, unrestricted use with citation. Only article metadata (title, outlet, date, "
            "URL) is stored; article text is not copied.",
            contains_personal_data=True,
        ),
        fields=["article_title", "outlet_domain", "language", "source_country", "seen_date"],
        freshness="15-minute updates; rolling 3-month window",
        reliability=Reliability.D,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx,
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": f'"{identifier.value}"',
                "mode": "artlist",
                "format": "json",
                "maxrecords": 15,
                "sort": "datedesc",
            },
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        try:
            articles = resp.json().get("articles") or []
        except ValueError:
            return []  # GDELT returns plain text for empty/invalid queries
        out = []
        for a in articles:
            seen = None
            if a.get("seendate"):
                try:
                    seen = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                except ValueError:
                    seen = None
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="news_mention",
                    title=a.get("title") or "News article",
                    description=f"News article on {a.get('domain')} matching the exact phrase "
                    f"'{identifier.value}'. A name mention is not evidence that the article concerns the subject.",
                    url=a.get("url") or "https://www.gdeltproject.org/",
                    attributes={
                        "article_title": a.get("title"),
                        "outlet_domain": a.get("domain"),
                        "language": a.get("language"),
                        "source_country": a.get("sourcecountry"),
                        "seen_date": seen.isoformat() if seen else None,
                    },
                    match_type=MatchType.SIMILAR,
                    excerpt=a.get("title"),
                    published_at=seen,
                    entity_kind="publication",
                    entity_hint=f"publication:url:{a.get('url')}",
                    claim_key=f"news.mention:{a.get('url')}",
                )
            )
        return out


class PublicDocumentAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="public_document",
        display_name="Public document metadata extractor",
        description="Retrieves a publicly accessible document (respecting robots.txt) and records its "
        "content hash, type, size, title and embedded document metadata.",
        category=SourceCategory.DOCUMENTS,
        input_types=[IdentifierType.DOCUMENT],
        access_method=AccessMethod.PUBLIC_WEB,
        homepage="https://www.rfc-editor.org/rfc/rfc9309",
        rate_limit=RateLimit(requests=1, per_seconds=2),
        legal=LegalInfo(
            restrictions="Only publicly reachable documents; robots.txt is honoured; content is hashed, not "
            "republished. Copyright remains with the publisher.",
            robots_txt_respected=True,
        ),
        fields=[
            "content_type",
            "size_bytes",
            "sha256",
            "last_modified",
            "doc_title",
            "doc_author",
            "doc_creator_tool",
            "doc_created",
            "doc_modified",
            "final_url",
            "outbound_domains",
        ],
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def _robots_allowed(self, ctx: CollectionContext, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            resp = await ctx.http.get(robots_url, max_bytes=500_000)
        except Exception:
            return True
        if resp.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser.can_fetch(ctx.settings.user_agent, url)

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        url = identifier.value
        if not await self._robots_allowed(ctx, url):
            raise SourceError(AdapterStatus.SKIPPED, "disallowed by the site's robots.txt")
        resp = await self.fetch(ctx, url, max_bytes=25_000_000)
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        attrs: dict[str, Any] = {
            "content_type": ctype,
            "size_bytes": len(resp.content),
            "sha256": Evidence.hash_bytes(resp.content),
            "last_modified": resp.headers.get("last-modified"),
            "final_url": resp.url,
        }
        if ctype == "application/pdf" or resp.content[:5] == b"%PDF-":
            attrs.update(_pdf_info(resp.content))
        elif "html" in ctype:
            text = resp.text
            title = re.search(r"<title[^>]*>([^<]{1,300})</title>", text, re.I)
            author = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']{1,200})', text, re.I)
            attrs["doc_title"] = title.group(1).strip() if title else None
            attrs["doc_author"] = author.group(1).strip() if author else None
            domains = sorted({m.lower() for m in re.findall(r'href=["\']https?://([^/"\':]+)', text)})[:50]
            attrs["outbound_domains"] = domains
        linked = []
        host = urlsplit(resp.url).hostname
        if host:
            linked.append(
                LinkedIdentifier(
                    identifier=Identifier(type=IdentifierType.DOMAIN, value=host.removeprefix("www.")),
                    relation="hosted_on",
                )
            )
        return [
            self.finding(
                module="public_records",
                subject=identifier,
                finding_type="public_document",
                title=attrs.get("doc_title") or f"Document at {url}",
                description=f"Publicly accessible {ctype or 'document'} of {attrs['size_bytes']} bytes "
                f"(sha256 {attrs['sha256'][:16]}…).",
                url=resp.url,
                attributes=attrs,
                linked=linked,
                raw=resp.content,
                published_at=parse_datetime(attrs.get("doc_created")),
                entity_hint=f"document:sha256:{attrs['sha256']}",
                entity_kind="document",
                claim_key=f"document.hash:{url}={attrs['sha256']}",
            )
        ]


def _pdf_info(data: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    head = data[:2_000_000]
    mapping = {
        "Title": "doc_title",
        "Author": "doc_author",
        "Creator": "doc_creator_tool",
        "CreationDate": "doc_created",
        "ModDate": "doc_modified",
    }
    for key, attr in mapping.items():
        m = re.search(rb"/" + key.encode() + rb"\s*\(([^)]{0,300})\)", head)
        if m:
            value = m.group(1).decode("latin-1", errors="replace").strip()
            if attr in ("doc_created", "doc_modified"):
                d = re.match(r"D:(\d{4})(\d{2})(\d{2})", value)
                value = f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else value
            out[attr] = value
    return out


class OpenSanctionsAdapter(SourceAdapter):
    """Sanctions, PEP, debarment and enforcement screening (OpenSanctions /match API)."""

    THRESHOLD = 0.7
    RISK_TOPICS = {
        "sanction": "risk:sanction",
        "sanction.linked": "risk:sanction",
        "sanction.control": "risk:sanction",
        "debarment": "risk:debarment",
        "role.pep": "risk:pep",
        "role.rca": "risk:pep",
        "crime": "risk:crime",
        "reg.action": "risk:regulatory",
        "reg.warn": "risk:regulatory",
        "poi": "risk:person_of_interest",
    }
    meta = SourceMetadata(
        name="opensanctions",
        display_name="OpenSanctions screening",
        description="Screens organisations (and, with consent, people) against consolidated sanctions lists, "
        "politically-exposed-person data, debarment and regulatory-action lists. A clear result is recorded too.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.ORGANIZATION, IdentifierType.NAME],
        access_method=AccessMethod.LICENSED_API,
        homepage="https://www.opensanctions.org/docs/api/",
        auth=AuthRequirement(
            required=True,
            kind="api_key",
            settings_fields=["opensanctions_api_key"],
            how_to_obtain="Request an API key at opensanctions.org (free grants for journalism, NGOs and academic "
            "research; business use requires a data licence).",
        ),
        rate_limit=RateLimit(requests=2, per_seconds=1),
        legal=LegalInfo(
            license="CC BY-NC 4.0 (non-commercial); commercial data licence otherwise",
            terms_url="https://www.opensanctions.org/licensing/",
            restrictions="Name matches are possible matches, not determinations: the score measures name "
            "similarity, not risk. Verify with registration numbers or other identifiers before acting.",
            contains_personal_data=True,
        ),
        fields=[
            "candidate_name",
            "legal_name",
            "opensanctions_id",
            "schema",
            "match_score",
            "risk_topics",
            "datasets",
            "countries",
            "last_change",
            "screening_threshold",
            "screened_collection",
        ],
        freshness="daily",
        reliability=Reliability.B,
        citation_format='OpenSanctions (CC BY-NC 4.0). "{title}". {url}. Retrieved {collected_at}.',
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        is_person = identifier.type == IdentifierType.NAME
        query = {
            "schema": "Person" if is_person else "Company",
            "properties": {"name": [identifier.value]},
        }
        resp = await self.fetch(
            ctx,
            "https://api.opensanctions.org/match/default",
            method="POST",
            params={"threshold": self.THRESHOLD, "limit": 5},
            json_body={"queries": {"q": query}},
            headers={"Authorization": f"ApiKey {ctx.secret('opensanctions_api_key')}"},
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        results = (((resp.json().get("responses") or {}).get("q")) or {}).get("results") or []
        hits = [r for r in results if r.get("match")]
        kind = "person" if is_person else "organization"
        if not hits:
            return [
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="sanctions_screening_clear",
                    title=f"No sanctions/PEP match for '{identifier.value}'",
                    description=f"OpenSanctions returned no candidate at or above the {self.THRESHOLD} match threshold "
                    "in the default collection (sanctions, PEPs, debarments, enforcement). A clear result covers only "
                    "the screened name spelling and the data as of the collection date.",
                    url=f"https://www.opensanctions.org/search/?q={quote(identifier.value)}",
                    attributes={"screening_threshold": self.THRESHOLD, "screened_collection": "default"},
                    raw=resp.content,
                    claim_key=f"screening.clear:{name_key(identifier.value)}",
                )
            ]
        out = []
        for r in hits:
            props = r.get("properties") or {}
            topics = sorted(set(props.get("topics") or []))
            flags = sorted({self.RISK_TOPICS[t] for t in topics if t in self.RISK_TOPICS})
            caption = str(r.get("caption") or r.get("id"))
            attrs: dict[str, Any] = {
                "opensanctions_id": r.get("id"),
                "schema": r.get("schema"),
                "match_score": r.get("score"),
                "risk_topics": topics,
                "datasets": (r.get("datasets") or [])[:10],
                "last_change": r.get("last_change"),
            }
            attrs["candidate_name" if is_person else "legal_name"] = caption
            if not is_person:
                attrs["countries"] = (props.get("country") or props.get("jurisdiction") or [])[:5]
            out.append(
                self.finding(
                    module="public_records",
                    subject=identifier,
                    finding_type="sanctions_screening_hit",
                    title=f"Screening hit: {caption} ({', '.join(topics) or 'listed'})",
                    description=f"OpenSanctions candidate '{caption}' matches the screened name with score "
                    f"{r.get('score')}. Topics: {', '.join(topics) or 'none'}. Datasets: "
                    f"{', '.join((r.get('datasets') or [])[:5])}. This is a possible match on name similarity – "
                    "confirm with additional identifiers before drawing conclusions.",
                    url=f"https://www.opensanctions.org/entities/{quote(str(r.get('id')))}/",
                    attributes=attrs,
                    match_type=MatchType.EXACT
                    if name_key(caption) == name_key(identifier.value)
                    else MatchType.SIMILAR,
                    raw=resp.content,
                    entity_hint=f"{kind}:opensanctions:{r.get('id')}",
                    entity_kind=kind,
                    claim_key=f"screening.hit:{r.get('id')}",
                    flags=flags,
                )
            )
        return out


PUBLIC_RECORD_ADAPTERS = [
    GleifAdapter,
    OpenSanctionsAdapter,
    SecEdgarAdapter,
    CompaniesHouseAdapter,
    OpenCorporatesAdapter,
    GdeltNewsAdapter,
    PublicDocumentAdapter,
]

__all__ = ["PUBLIC_RECORD_ADAPTERS", "quote"]
