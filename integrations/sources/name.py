"""Name sources: professional, academic and encyclopaedic public profiles.

Name searches are inherently ambiguous. Every candidate returned here becomes
its own entity, keyed by the source's *persistent identifier* (ORCID iD,
OpenAlex ID, Wikidata QID). The correlation engine never merges candidates on
the basis of the name alone.
"""

from __future__ import annotations

from typing import Any

from engine.normalization.identifiers import name_key, org_name_key, try_normalize
from integrations.sources.base import (
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
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    MatchType,
    Reliability,
    SourceCategory,
)

PERSON_FIELDS = [
    "candidate_name",
    "persistent_id",
    "id_scheme",
    "affiliations",
    "works_count",
    "cited_by_count",
    "topics",
    "description",
    "orcid",
    "profile_url",
    "occupations",
    "employers",
    "official_website",
]


def _name_match(query: str, candidate: str) -> MatchType:
    return MatchType.EXACT if name_key(query) == name_key(candidate) else MatchType.SIMILAR


class OpenAlexAuthorsAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="openalex_authors",
        display_name="OpenAlex author index",
        description="Open catalogue of scholarly authors, works and institutional affiliations.",
        category=SourceCategory.ACADEMIC,
        input_types=[IdentifierType.NAME],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://docs.openalex.org/",
        rate_limit=RateLimit(requests=10, per_seconds=1, notes="polite pool; 100k/day"),
        legal=LegalInfo(
            license="CC0-1.0",
            terms_url="https://openalex.org/about",
            restrictions="CC0 data. Author disambiguation is algorithmic and can be wrong.",
            contains_personal_data=True,
        ),
        fields=PERSON_FIELDS,
        freshness="updated continuously",
        reliability=Reliability.C,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx, "https://api.openalex.org/authors", params={"search": identifier.value, "per-page": 5}
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        out: list[Finding] = []
        for a in resp.json().get("results") or []:
            name = a.get("display_name") or ""
            oa_id = (a.get("id") or "").rsplit("/", 1)[-1]
            if not oa_id:
                continue
            orcid = (a.get("orcid") or "").rsplit("/", 1)[-1] or None
            affs = [(i.get("display_name")) for i in (a.get("last_known_institutions") or []) if i.get("display_name")]
            topics = [t.get("display_name") for t in (a.get("topics") or [])[:5] if t.get("display_name")]
            linked = []
            if orcid:
                linked.append(
                    LinkedIdentifier(
                        identifier=Identifier(type=IdentifierType.URL, value=f"https://orcid.org/{orcid}"),
                        relation="orcid",
                    )
                )
            match = _name_match(identifier.value, name)
            out.append(
                self.finding(
                    module="name",
                    subject=identifier,
                    finding_type="academic_author_profile",
                    title=f"OpenAlex author: {name}",
                    description=f"Scholarly author profile '{name}'"
                    + (f" affiliated with {', '.join(affs)}" if affs else "")
                    + f"; {a.get('works_count', 0)} works. Name matches are not identity matches.",
                    url=f"https://openalex.org/{oa_id}",
                    attributes={
                        "candidate_name": name,
                        "persistent_id": oa_id,
                        "id_scheme": "openalex",
                        "affiliations": affs,
                        "works_count": a.get("works_count"),
                        "cited_by_count": a.get("cited_by_count"),
                        "topics": topics,
                        "orcid": orcid,
                    },
                    linked=linked,
                    match_type=match,
                    raw=None,
                    entity_hint=f"person:orcid:{orcid}" if orcid else f"person:openalex:{oa_id}",
                    entity_kind="person",
                    claim_key=f"person.candidate:openalex:{oa_id}",
                )
            )
        return out


class OrcidAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="orcid",
        display_name="ORCID public registry",
        description="Researcher-maintained persistent identifiers with self-declared affiliations.",
        category=SourceCategory.ACADEMIC,
        input_types=[IdentifierType.NAME],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://info.orcid.org/documentation/api-tutorials/api-tutorial-searching-the-orcid-registry/",
        rate_limit=RateLimit(requests=12, per_seconds=1),
        legal=LegalInfo(
            license="CC0-1.0 (public data file)",
            terms_url="https://info.orcid.org/public-client-terms-of-service/",
            restrictions="Only data the researcher marked public is returned.",
            contains_personal_data=True,
        ),
        fields=PERSON_FIELDS,
        freshness="real-time",
        reliability=Reliability.B,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        parts = identifier.value.split(" ")
        if len(parts) >= 2:
            q = f'given-names:"{parts[0]}" AND family-name:"{parts[-1]}"'
        else:
            q = f'"{identifier.value}"'
        resp = await self.fetch(
            ctx,
            "https://pub.orcid.org/v3.0/expanded-search/",
            params={"q": q, "rows": 5},
            headers={"Accept": "application/json"},
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        out: list[Finding] = []
        for r in resp.json().get("expanded-result") or []:
            orcid = r.get("orcid-id")
            if not orcid:
                continue
            name = " ".join(p for p in [r.get("given-names"), r.get("family-names")] if p)
            affs = (r.get("institution-name") or [])[:5]
            out.append(
                self.finding(
                    module="name",
                    subject=identifier,
                    finding_type="researcher_profile",
                    title=f"ORCID record {orcid}: {name}",
                    description=f"ORCID record for '{name}'"
                    + (f" with declared affiliations {', '.join(affs)}" if affs else "")
                    + ". ORCID data is self-asserted by the record holder.",
                    url=f"https://orcid.org/{orcid}",
                    attributes={
                        "candidate_name": name,
                        "persistent_id": orcid,
                        "id_scheme": "orcid",
                        "orcid": orcid,
                        "affiliations": affs,
                        "profile_url": f"https://orcid.org/{orcid}",
                    },
                    match_type=_name_match(identifier.value, name),
                    raw=None,
                    entity_hint=f"person:orcid:{orcid}",
                    entity_kind="person",
                    claim_key=f"person.candidate:orcid:{orcid}",
                )
            )
        return out


class WikidataAdapter(SourceAdapter):
    """Wikidata entity search, used for notable people (names) and organisations."""

    meta = SourceMetadata(
        name="wikidata",
        display_name="Wikidata",
        description="Structured, community-curated knowledge base of notable people and organisations.",
        category=SourceCategory.PUBLIC_RECORDS,
        input_types=[IdentifierType.NAME, IdentifierType.ORGANIZATION],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://www.wikidata.org/wiki/Wikidata:Data_access",
        rate_limit=RateLimit(requests=5, per_seconds=1),
        legal=LegalInfo(
            license="CC0-1.0",
            terms_url="https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
            restrictions="Community-edited; claims should be checked against their cited references.",
            contains_personal_data=True,
        ),
        fields=[*PERSON_FIELDS, "inception", "country", "legal_form", "official_name", "industry"],
        freshness="real-time",
        reliability=Reliability.C,
    )

    PERSON = "Q5"
    # Properties that indicate an item describes an organisation (rather than e.g. a report about one).
    ORG_PROPERTIES = ("P1278", "P856", "P571", "P159", "P452", "P1454", "P749", "P1128", "P414", "P2088")

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        search = await self.fetch(
            ctx,
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": identifier.value,
                "language": "en",
                "type": "item",
                "limit": 7,
                "format": "json",
            },
        )
        if not search.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {search.status_code}", search.status_code)
        ids = [r["id"] for r in search.json().get("search") or [] if r.get("id")]
        if not ids:
            return []
        ent = await self.fetch(
            ctx,
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "props": "labels|descriptions|claims|sitelinks",
                "languages": "en",
                "format": "json",
            },
        )
        if not ent.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {ent.status_code}", ent.status_code)
        entities: dict[str, Any] = ent.json().get("entities") or {}
        want_person = identifier.type == IdentifierType.NAME
        out: list[Finding] = []
        for qid in ids:
            e = entities.get(qid) or {}
            claims = e.get("claims") or {}
            instance_of = {_claim_id(c) for c in claims.get("P31", [])}
            is_person = self.PERSON in instance_of
            if want_person != is_person:
                continue
            if not is_person and not any(p in claims for p in self.ORG_PROPERTIES):
                continue
            label = ((e.get("labels") or {}).get("en") or {}).get("value") or qid
            desc = ((e.get("descriptions") or {}).get("en") or {}).get("value")
            website = _claim_str(claims.get("P856"))
            linked = []
            if website:
                from integrations.sources.username import website_links

                linked += website_links(website)
            orcid = _claim_str(claims.get("P496"))
            attrs: dict[str, Any] = {
                "candidate_name": label,
                "persistent_id": qid,
                "id_scheme": "wikidata",
                "description": desc,
                "official_website": website,
                "profile_url": f"https://www.wikidata.org/wiki/{qid}",
            }
            if is_person:
                attrs["orcid"] = orcid
                hint = f"person:orcid:{orcid}" if orcid else f"person:wikidata:{qid}"
                kind, ftype, module = "person", "notable_person_record", "name"
            else:
                inception = _claim_time(claims.get("P571"))
                attrs["inception"] = inception
                lei = _claim_str(claims.get("P1278"))
                hint = f"organization:lei:{lei}" if lei else f"organization:wikidata:{qid}"
                kind, ftype, module = "organization", "organization_record", "public_records"
            out.append(
                self.finding(
                    module=module,
                    subject=identifier,
                    finding_type=ftype,
                    title=f"Wikidata {qid}: {label}",
                    description=f"Wikidata item '{label}'" + (f" – {desc}" if desc else "") + ".",
                    url=f"https://www.wikidata.org/wiki/{qid}",
                    attributes=attrs,
                    linked=linked,
                    match_type=_name_match(identifier.value, label)
                    if is_person
                    else (
                        MatchType.EXACT if org_name_key(identifier.value) == org_name_key(label) else MatchType.SIMILAR
                    ),
                    excerpt=desc,
                    entity_hint=hint,
                    entity_kind=kind,
                    claim_key=f"{kind}.candidate:wikidata:{qid}",
                )
            )
        return out


def _claim_id(claim: dict[str, Any]) -> str | None:
    val = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
    return val.get("id") if isinstance(val, dict) else None


def _claim_str(claims: list[dict[str, Any]] | None) -> str | None:
    for c in claims or []:
        val = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(val, str):
            return val
    return None


def _claim_time(claims: list[dict[str, Any]] | None) -> str | None:
    for c in claims or []:
        val = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(val, dict) and val.get("time"):
            return str(val["time"]).lstrip("+")[:10]
    return None


# Re-export for adapters that only need URL normalisation.
__all__ = ["CrossrefWorksAdapter", "OpenAlexAuthorsAdapter", "OrcidAdapter", "WikidataAdapter", "try_normalize"]


class CrossrefWorksAdapter(SourceAdapter):
    """Scholarly works whose author list contains the searched name (Crossref REST API)."""

    meta = SourceMetadata(
        name="crossref",
        display_name="Crossref works index",
        description="Publication metadata (DOI, title, venue, year, co-author count) for works listing an author "
        "with the searched name. Author ORCID iDs, when deposited, link works to researcher records.",
        category=SourceCategory.ACADEMIC,
        input_types=[IdentifierType.NAME],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://api.crossref.org/swagger-ui/index.html",
        rate_limit=RateLimit(requests=5, per_seconds=1, notes="public pool; be polite"),
        legal=LegalInfo(
            license="Metadata is free to reuse (Crossref: facts, no rights reserved)",
            terms_url="https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
            restrictions="Bibliographic metadata only; abstracts and full text are not collected.",
            contains_personal_data=True,
        ),
        fields=[
            "publication_title",
            "doi",
            "year",
            "venue",
            "work_type",
            "author_position",
            "coauthor_count",
            "author_orcid",
            "candidate_name",
        ],
        freshness="daily",
        reliability=Reliability.B,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx,
            "https://api.crossref.org/works",
            params={
                "query.author": identifier.value,
                "rows": 10,
                "select": "DOI,title,author,published,container-title,type",
            },
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        items = ((resp.json().get("message") or {}).get("items")) or []
        target = name_key(identifier.value)
        out: list[Finding] = []
        for item in items:
            authors = item.get("author") or []
            best = None
            for pos, a in enumerate(authors, start=1):
                full = " ".join(p for p in (a.get("given"), a.get("family")) if p)
                if full and name_key(full) == target:
                    best = (pos, a, full)
                    break
            if best is None:
                continue  # fuzzy hit without an author of that name – not evidence about the name
            pos, author, full = best
            doi = str(item.get("DOI") or "").lower()
            if not doi:
                continue
            title = ((item.get("title") or [""])[0] or "Untitled")[:300]
            parts = ((item.get("published") or {}).get("date-parts") or [[None]])[0]
            year = parts[0] if parts else None
            orcid = (author.get("ORCID") or "").rsplit("/", 1)[-1] or None
            linked = []
            if orcid:
                linked.append(
                    LinkedIdentifier(
                        identifier=Identifier(type=IdentifierType.URL, value=f"https://orcid.org/{orcid}"),
                        relation="authored_by",
                    )
                )
            out.append(
                self.finding(
                    module="name",
                    subject=identifier,
                    finding_type="publication",
                    title=title,
                    description=f"Publication ({item.get('type') or 'work'}, {year or 'n.d.'}) listing '{full}' as "
                    f"author #{pos} of {len(authors)}."
                    + (
                        f" The author entry carries ORCID {orcid}."
                        if orcid
                        else " No ORCID deposited; the author may be a namesake."
                    ),
                    url=f"https://doi.org/{doi}",
                    attributes={
                        "publication_title": title,
                        "doi": doi,
                        "year": year,
                        "venue": ((item.get("container-title") or [None])[0]),
                        "work_type": item.get("type"),
                        "author_position": pos,
                        "coauthor_count": max(0, len(authors) - 1),
                        "author_orcid": orcid,
                        "candidate_name": full,
                    },
                    linked=linked,
                    match_type=MatchType.EXACT,
                    published_at=parse_datetime(f"{year}-01-01") if year else None,
                    entity_hint=f"publication:doi:{doi}",
                    entity_kind="publication",
                    claim_key=f"publication.author:{doi}={target}",
                )
            )
        return out
