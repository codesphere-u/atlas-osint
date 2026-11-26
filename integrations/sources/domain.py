"""Domain and infrastructure sources.

All of these are passive (public DNS, RDAP registries, certificate-transparency
logs, internet archives, BGP routing data) except
:class:`HttpSecurityAdapter`, which makes one ordinary ``GET`` request to the
target's home page and therefore requires the domain to be in the
investigation's authorised scope. No port scanning, brute-force subdomain
enumeration or exploitation is performed.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from engine.normalization.identifiers import try_normalize
from integrations.sources.base import (
    CollectionContext,
    LegalInfo,
    RateLimit,
    SourceAdapter,
    SourceError,
    SourceMetadata,
    parse_datetime,
)
from shared.dns import DnsLookupError, resolve
from shared.types import (
    AccessMethod,
    AdapterStatus,
    EvidenceKind,
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    MatchType,
    Reliability,
    SourceCategory,
)


def _dns(ctx: CollectionContext):
    return ctx.extra.get("dns_resolver", resolve)


def _domain_of(identifier: Identifier) -> str:
    if identifier.type == IdentifierType.DOMAIN:
        return identifier.value
    if identifier.type in (IdentifierType.URL, IdentifierType.DOCUMENT):
        host = re.sub(r"^https?://", "", identifier.value).split("/", 1)[0].split(":", 1)[0]
        return host.removeprefix("www.")
    raise SourceError(AdapterStatus.SKIPPED, "no domain in identifier")


class DnsRecordsAdapter(SourceAdapter):
    RECORD_TYPES = ("A", "AAAA", "MX", "NS", "TXT", "CAA", "SOA")
    meta = SourceMetadata(
        name="dns_records",
        display_name="Public DNS",
        description="Authoritative public DNS records (A, AAAA, MX, NS, TXT, CAA, SOA).",
        category=SourceCategory.DOMAIN,
        input_types=[IdentifierType.DOMAIN, IdentifierType.URL],
        access_method=AccessMethod.DNS,
        homepage="https://www.rfc-editor.org/rfc/rfc1035",
        rate_limit=RateLimit(requests=50, per_seconds=1),
        legal=LegalInfo(restrictions="Public DNS data."),
        fields=["record_type", "values", "spf", "dmarc", "verification_tokens_count"],
        freshness="real-time (subject to TTLs)",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = _domain_of(identifier)
        resolver = _dns(ctx)
        out: list[Finding] = []
        errors = 0
        for rtype in self.RECORD_TYPES:
            try:
                values = await resolver(domain, rtype)
            except DnsLookupError:
                errors += 1
                continue
            if not values:
                continue
            values = sorted(v.rstrip(".") if rtype in ("NS", "MX") else v for v in values)
            attrs: dict[str, Any] = {"record_type": rtype, "values": values[:50]}
            linked: list[LinkedIdentifier] = []
            if rtype in ("A", "AAAA"):
                for v in values[:20]:
                    linked.append(
                        LinkedIdentifier(identifier=Identifier(type=IdentifierType.IP, value=v), relation="resolves_to")
                    )
            if rtype == "NS":
                for v in values[:10]:
                    ns_domain = try_normalize(IdentifierType.DOMAIN, ".".join(v.split(".")[-2:]))
                    if ns_domain and ns_domain.value != domain:
                        linked.append(LinkedIdentifier(identifier=ns_domain, relation="dns_hosted_by"))
            if rtype == "TXT":
                spf = [v for v in values if v.lower().startswith("v=spf1")]
                attrs["spf"] = spf[0] if spf else None
                # Count (do not store) site-verification tokens: they can be secrets for some providers.
                tokens = [v for v in values if "verification" in v.lower() or "-site-verification" in v.lower()]
                attrs["verification_tokens_count"] = len(tokens)
                attrs["values"] = [v for v in values if v not in tokens][:50]
            out.append(
                self.finding(
                    module="domain",
                    subject=identifier,
                    finding_type="dns_record",
                    title=f"{rtype} records for {domain}",
                    description=f"{domain} has {len(values)} {rtype} record(s).",
                    url=f"dns:{domain}?type={rtype}",
                    attributes=attrs,
                    linked=linked,
                    excerpt="; ".join(str(v) for v in attrs["values"][:5]),
                    entity_hint=f"domain:{domain}",
                    entity_kind="domain",
                    claim_key=f"domain.dns.{rtype}:{domain}={','.join(values)}",
                )
            )
        if errors == len(self.RECORD_TYPES):
            raise SourceError(AdapterStatus.UNAVAILABLE, "all DNS lookups failed")
        return out


_RDAP_BOOTSTRAP: dict[str, str] = {}


class RdapDomainAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="rdap_domain",
        display_name="RDAP domain registration data (IANA bootstrap)",
        description="Registration Data Access Protocol – the ICANN-mandated successor of WHOIS.",
        category=SourceCategory.DOMAIN,
        input_types=[IdentifierType.DOMAIN, IdentifierType.URL],
        access_method=AccessMethod.RDAP,
        homepage="https://www.iana.org/domains/rdap",
        rate_limit=RateLimit(requests=5, per_seconds=1),
        legal=LegalInfo(
            terms_url="https://www.icann.org/rdap",
            restrictions="Registries redact personal registrant data (GDPR). ATLAS records registrant "
            "organisation names only and never personal registrant contact details.",
        ),
        fields=[
            "registrar",
            "registrar_iana_id",
            "created",
            "expires",
            "updated",
            "status",
            "nameservers",
            "registrant_org",
            "dnssec",
            "rdap_server",
        ],
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def _base_url(self, ctx: CollectionContext, tld: str) -> str:
        if not _RDAP_BOOTSTRAP:
            try:
                resp = await self.fetch(ctx, "https://data.iana.org/rdap/dns.json")
                if resp.ok:
                    for service in resp.json().get("services", []):
                        tlds, urls = service[0], service[1]
                        https = [u for u in urls if u.startswith("https://")]
                        for t in tlds:
                            if https:
                                _RDAP_BOOTSTRAP[t.lower()] = https[0]
            except SourceError:
                pass
        base = _RDAP_BOOTSTRAP.get(tld, "https://rdap.org/")
        return base if base.endswith("/") else base + "/"

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = _domain_of(identifier)
        labels = domain.split(".")
        registered = ".".join(labels[-2:]) if len(labels) > 2 and len(labels[-1]) > 2 else domain
        base = await self._base_url(ctx, labels[-1])
        url = f"{base}domain/{quote(registered)}"
        resp = await self.fetch(ctx, url, headers={"Accept": "application/rdap+json"})
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        events = {e.get("eventAction"): e.get("eventDate") for e in d.get("events") or []}
        registrar, iana_id, registrant_org = None, None, None
        for ent in d.get("entities") or []:
            roles = ent.get("roles") or []
            vcard = _vcard(ent)
            if "registrar" in roles:
                registrar = vcard.get("fn") or registrar
                for pid in ent.get("publicIds") or []:
                    if pid.get("type") == "IANA Registrar ID":
                        iana_id = pid.get("identifier")
            if "registrant" in roles and vcard.get("kind") in ("org", None) and vcard.get("org"):
                org = vcard["org"]
                if org and "redacted" not in org.lower():
                    registrant_org = org
        nameservers = sorted((ns.get("ldhName") or "").lower().rstrip(".") for ns in d.get("nameservers") or [])
        attrs = {
            "registrar": registrar,
            "registrar_iana_id": iana_id,
            "created": events.get("registration"),
            "expires": events.get("expiration"),
            "updated": events.get("last changed"),
            "status": d.get("status"),
            "nameservers": [n for n in nameservers if n],
            "registrant_org": registrant_org,
            "dnssec": (d.get("secureDNS") or {}).get("delegationSigned"),
            "rdap_server": base,
        }
        linked = []
        if registrant_org:
            linked.append(
                LinkedIdentifier(
                    identifier=Identifier(type=IdentifierType.ORGANIZATION, value=registrant_org),
                    relation="registrant_org",
                )
            )
        findings = [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="domain_registration",
                title=f"Registration record for {registered}",
                description=f"{registered} is registered via {registrar or 'an undisclosed registrar'}; created "
                f"{attrs['created'] or 'unknown'}, expires {attrs['expires'] or 'unknown'}.",
                url=url,
                attributes=attrs,
                linked=linked,
                raw=resp.content,
                published_at=parse_datetime(events.get("registration")),
                entity_hint=f"domain:{registered}",
                entity_kind="domain",
                claim_key=f"domain.registrar:{registered}={(registrar or '').lower()}",
            )
        ]
        if attrs["created"]:
            findings.append(
                self.finding(
                    module="domain",
                    subject=identifier,
                    finding_type="domain_created",
                    title=f"{registered} registered on {attrs['created'][:10]}",
                    description=f"Registry creation date for {registered}.",
                    url=url,
                    attributes={"created": attrs["created"]},
                    published_at=parse_datetime(attrs["created"]),
                    entity_hint=f"domain:{registered}",
                    entity_kind="domain",
                    claim_key=f"domain.created:{registered}={attrs['created'][:10]}",
                )
            )
        return findings


def _vcard(entity: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    arr = entity.get("vcardArray")
    if not isinstance(arr, list) or len(arr) < 2:
        return out
    for item in arr[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] in ("fn", "org", "kind"):
            value = item[3]
            out[item[0]] = value if isinstance(value, str) else " ".join(map(str, value))
    return out


class CrtShAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="crtsh",
        display_name="crt.sh certificate-transparency search",
        description="Certificates logged in public Certificate Transparency logs (RFC 6962).",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.DOMAIN],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://crt.sh/",
        rate_limit=RateLimit(requests=1, per_seconds=5, notes="shared community service; be gentle"),
        legal=LegalInfo(
            terms_url="https://crt.sh/",
            restrictions="Public CT log data. Subdomain names are listed only for domains inside the "
            "investigation's authorised scope.",
        ),
        fields=[
            "certificate_count",
            "issuers",
            "first_seen",
            "last_seen",
            "subdomain",
            "subdomain_count",
            "first_cert_not_before",
            "listing_withheld",
        ],
        freshness="near real-time",
        reliability=Reliability.A,
        timeout_seconds=45.0,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = identifier.value
        url = "https://crt.sh/"
        resp = await self.fetch(ctx, url, params={"q": f"%.{domain}", "output": "json"}, max_bytes=20_000_000)
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        try:
            rows = resp.json()
        except ValueError as exc:
            raise SourceError(AdapterStatus.UNAVAILABLE, "crt.sh returned a non-JSON response") from exc
        if not rows:
            return []
        names: set[str] = set()
        issuers: dict[str, int] = {}
        not_befores = []
        for r in rows:
            for n in str(r.get("name_value", "")).split("\n"):
                n = n.strip().lower().lstrip("*.")
                if n == domain or n.endswith("." + domain):
                    names.add(n)
            issuer = re.search(r"O=([^,]+)", str(r.get("issuer_name", "")))
            if issuer:
                issuers[issuer.group(1).strip('"')] = issuers.get(issuer.group(1).strip('"'), 0) + 1
            if r.get("not_before"):
                not_befores.append(str(r["not_before"]))
        subs = sorted(n for n in names if n != domain)
        in_scope = ctx.scope.domain_in_scope(domain)
        search_url = f"https://crt.sh/?q=%25.{quote(domain)}"
        first = min(not_befores) if not_befores else None
        findings = [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="certificate_transparency_summary",
                title=f"{len(rows)} CT-logged certificates for *.{domain}",
                description=f"{len(rows)} certificates covering {domain} or its subdomains appear in CT logs, "
                f"from {len(issuers)} issuing organisation(s); {len(subs)} distinct subdomain names."
                + ("" if in_scope else " Subdomain names withheld: domain not in authorised scope."),
                url=search_url,
                attributes={
                    "certificate_count": len(rows),
                    "issuers": dict(sorted(issuers.items(), key=lambda kv: -kv[1])[:10]),
                    "first_cert_not_before": first,
                    "subdomain_count": len(subs),
                    "listing_withheld": not in_scope,
                },
                raw=resp.content,
                published_at=parse_datetime(first),
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.ct_count:{domain}",
            )
        ]
        if in_scope:
            for sub in subs[:200]:
                findings.append(
                    self.finding(
                        module="domain",
                        subject=identifier,
                        finding_type="subdomain",
                        title=f"Subdomain {sub}",
                        description=f"{sub} appears in at least one CT-logged certificate.",
                        url=f"https://crt.sh/?q={quote(sub)}",
                        attributes={"subdomain": sub},
                        linked=[
                            LinkedIdentifier(
                                identifier=Identifier(type=IdentifierType.DOMAIN, value=sub), relation="subdomain_of"
                            )
                        ],
                        match_type=MatchType.RELATED,
                        entity_hint=f"domain:{domain}",
                        entity_kind="domain",
                        claim_key=f"domain.subdomain:{sub}",
                    )
                )
        return findings


SECURITY_HEADERS = {
    "strict-transport-security": "HSTS",
    "content-security-policy": "CSP",
    "x-frame-options": "X-Frame-Options",
    "x-content-type-options": "X-Content-Type-Options",
    "referrer-policy": "Referrer-Policy",
    "permissions-policy": "Permissions-Policy",
    "cross-origin-opener-policy": "COOP",
}

TECH_FINGERPRINTS: list[tuple[str, re.Pattern[str]]] = [
    ("WordPress", re.compile(r"wp-content/|wp-includes/", re.I)),
    ("Drupal", re.compile(r"Drupal\.settings|/sites/default/files", re.I)),
    ("Joomla", re.compile(r"/media/jui/|Joomla!", re.I)),
    ("Shopify", re.compile(r"cdn\.shopify\.com", re.I)),
    ("Wix", re.compile(r"static\.wixstatic\.com", re.I)),
    ("Squarespace", re.compile(r"static1\.squarespace\.com", re.I)),
    ("Next.js", re.compile(r"__NEXT_DATA__|/_next/static/", re.I)),
    ("Nuxt", re.compile(r"__NUXT__|/_nuxt/", re.I)),
    ("Gatsby", re.compile(r"___gatsby", re.I)),
    ("React", re.compile(r"data-reactroot|react-dom", re.I)),
    ("Angular", re.compile(r"ng-version=", re.I)),
    ("Vue.js", re.compile(r"data-v-[0-9a-f]{8}", re.I)),
    ("jQuery", re.compile(r"jquery(?:\.min)?\.js", re.I)),
    ("Bootstrap", re.compile(r"bootstrap(?:\.min)?\.(?:css|js)", re.I)),
    ("Google Tag Manager", re.compile(r"googletagmanager\.com/gtm\.js", re.I)),
    ("Cloudflare", re.compile(r"cdnjs\.cloudflare\.com|/cdn-cgi/", re.I)),
]


class HttpSecurityAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="http_security",
        display_name="Website security headers & technology fingerprint",
        description="Single GET of the public home page to record security headers, TLS redirect behaviour "
        "and publicly exposed technologies.",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.DOMAIN, IdentifierType.URL],
        access_method=AccessMethod.PUBLIC_WEB,
        homepage="https://owasp.org/www-project-secure-headers/",
        rate_limit=RateLimit(requests=1, per_seconds=2),
        legal=LegalInfo(
            restrictions="Active (but ordinary) request to the target website. Only performed when the domain "
            "is in the investigation's authorised scope.",
            active_probe=True,
        ),
        fields=[
            "final_url",
            "status_code",
            "https_redirect",
            "security_headers_present",
            "security_headers_missing",
            "server",
            "x_powered_by",
            "generator",
            "technologies",
            "title",
        ],
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = _domain_of(identifier)
        start = identifier.value if identifier.type == IdentifierType.URL else f"http://{domain}/"
        resp = await self.fetch(ctx, start, max_bytes=2_000_000)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        present = sorted(label for h, label in SECURITY_HEADERS.items() if h in headers)
        missing = sorted(label for h, label in SECURITY_HEADERS.items() if h not in headers)
        body = resp.text[:500_000] if "html" in headers.get("content-type", "") else ""
        techs = sorted({name for name, pat in TECH_FINGERPRINTS if pat.search(body)})
        gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']{1,100})', body, re.I)
        title = re.search(r"<title[^>]*>([^<]{1,200})</title>", body, re.I)
        attrs = {
            "final_url": resp.url,
            "status_code": resp.status_code,
            "https_redirect": resp.url.startswith("https://"),
            "security_headers_present": present,
            "security_headers_missing": missing,
            "server": headers.get("server"),
            "x_powered_by": headers.get("x-powered-by"),
            "generator": gen.group(1).strip() if gen else None,
            "technologies": techs,
            "title": title.group(1).strip() if title else None,
        }
        return [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="web_security_posture",
                title=f"Web security headers of {domain}",
                description=f"Home page served with HTTP {resp.status_code}; "
                f"{len(present)}/{len(SECURITY_HEADERS)} recommended security headers present"
                + (f"; missing: {', '.join(missing)}" if missing else "")
                + (f". Detected technologies: {', '.join(techs)}" if techs else "")
                + ".",
                url=resp.url,
                attributes=attrs,
                raw=resp.content,
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.web_headers:{domain}",
            )
        ]


class TeamCymruAsnAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="team_cymru_asn",
        display_name="Team Cymru IP-to-ASN mapping (DNS)",
        description="Maps IP addresses to the announcing autonomous system, prefix and registry via DNS.",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.DOMAIN, IdentifierType.IP],
        access_method=AccessMethod.DNS,
        homepage="https://www.team-cymru.com/ip-asn-mapping",
        rate_limit=RateLimit(requests=20, per_seconds=1),
        legal=LegalInfo(
            terms_url="https://www.team-cymru.com/ip-asn-mapping",
            restrictions="Free community service; bulk use should go through the netcat interface.",
        ),
        fields=["ip_address", "asn", "prefix", "country", "registry", "allocated", "as_name"],
        freshness="near real-time (BGP)",
        reliability=Reliability.B,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resolver = _dns(ctx)
        ips: list[str]
        try:
            if identifier.type == IdentifierType.IP:
                ips = [identifier.value]
            else:
                ips = (await resolver(identifier.value, "A"))[:5] + (await resolver(identifier.value, "AAAA"))[:2]
            out: list[Finding] = []
            for ip in ips:
                addr = ipaddress.ip_address(ip)
                if not addr.is_global:
                    continue
                if addr.version == 4:
                    q = ".".join(reversed(ip.split("."))) + ".origin.asn.cymru.com"
                else:
                    nibbles = addr.exploded.replace(":", "")
                    q = ".".join(reversed(nibbles)) + ".origin6.asn.cymru.com"
                origin = await resolver(q, "TXT")
                if not origin:
                    continue
                parts = [p.strip() for p in origin[0].split("|")]
                asn = parts[0].split()[0] if parts and parts[0] else None
                as_name = None
                if asn:
                    as_txt = await resolver(f"AS{asn}.asn.cymru.com", "TXT")
                    if as_txt:
                        as_name = as_txt[0].split("|")[-1].strip()
                attrs = {
                    "ip_address": ip,
                    "asn": f"AS{asn}" if asn else None,
                    "prefix": parts[1] if len(parts) > 1 else None,
                    "country": parts[2] if len(parts) > 2 else None,
                    "registry": parts[3] if len(parts) > 3 else None,
                    "allocated": parts[4] if len(parts) > 4 else None,
                    "as_name": as_name,
                }
                out.append(
                    self.finding(
                        module="domain",
                        subject=identifier,
                        finding_type="ip_asn",
                        title=f"{ip} is announced by AS{asn}" + (f" ({as_name})" if as_name else ""),
                        description=f"{ip} belongs to prefix {attrs['prefix']} announced by AS{asn}"
                        + (f" ({as_name})" if as_name else "")
                        + f", registry {attrs['registry']}. "
                        "Hosting location reflects network registration, not the operator's location.",
                        url=f"https://bgp.he.net/ip/{ip}",
                        attributes=attrs,
                        linked=[
                            LinkedIdentifier(
                                identifier=Identifier(type=IdentifierType.IP, value=ip), relation="resolves_to"
                            )
                        ],
                        match_type=MatchType.RELATED if identifier.type != IdentifierType.IP else MatchType.EXACT,
                        entity_hint=f"ip:{ip}",
                        entity_kind="ip",
                        claim_key=f"ip.asn:{ip}=AS{asn}",
                    )
                )
            return out
        except DnsLookupError as exc:
            raise SourceError(AdapterStatus.UNAVAILABLE, str(exc)) from exc


class WaybackAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="wayback",
        display_name="Internet Archive Wayback Machine (CDX API)",
        description="Historical captures of a website: first and most recent archived snapshots.",
        category=SourceCategory.ARCHIVE,
        input_types=[IdentifierType.DOMAIN, IdentifierType.URL, IdentifierType.DOCUMENT],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server",
        rate_limit=RateLimit(requests=1, per_seconds=2),
        legal=LegalInfo(
            terms_url="https://archive.org/about/terms.php",
            restrictions="Archived public web content; respect site owners' exclusion requests.",
        ),
        fields=["first_capture", "last_capture", "first_capture_url", "last_capture_url", "capture_status"],
        freshness="historical",
        reliability=Reliability.A,
        timeout_seconds=40.0,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        target = identifier.value
        cdx = "https://web.archive.org/cdx/search/cdx"
        first = await self.fetch(
            ctx, cdx, params={"url": target, "output": "json", "fl": "timestamp,original,statuscode", "limit": 1}
        )
        if not first.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {first.status_code}", first.status_code)
        rows = first.json() if first.content.strip() else []
        if len(rows) < 2:
            return []
        last = await self.fetch(
            ctx, cdx, params={"url": target, "output": "json", "fl": "timestamp,original,statuscode", "limit": -1}
        )
        lrows = last.json() if last.ok and last.content.strip() else []
        f_ts, f_orig, f_status = rows[1][0], rows[1][1], rows[1][2]
        l_ts = lrows[1][0] if len(lrows) > 1 else f_ts
        f_dt = datetime.strptime(f_ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        l_dt = datetime.strptime(l_ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        attrs = {
            "first_capture": f_dt.isoformat(),
            "last_capture": l_dt.isoformat(),
            "first_capture_url": f"https://web.archive.org/web/{f_ts}/{f_orig}",
            "last_capture_url": f"https://web.archive.org/web/{l_ts}/{f_orig}",
            "capture_status": f_status,
        }
        return [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="web_archive_history",
                title=f"Archived since {f_dt.date()}",
                description=f"The Wayback Machine holds captures of {target} from {f_dt.date()} to {l_dt.date()}.",
                url=attrs["first_capture_url"],
                attributes=attrs,
                evidence_kind=EvidenceKind.DIRECT,
                published_at=f_dt,
                entity_hint=f"domain:{_domain_of(identifier)}" if identifier.type != IdentifierType.DOCUMENT else None,
                entity_kind="domain" if identifier.type != IdentifierType.DOCUMENT else "document",
                claim_key=f"web.first_capture:{target}={f_dt.date()}",
            )
        ]


class RdapIpAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="rdap_ip",
        display_name="RDAP IP network registration (RIR)",
        description="Registered network block, holder organisation and RIR for an IP address.",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.IP],
        access_method=AccessMethod.RDAP,
        homepage="https://rdap.org/",
        rate_limit=RateLimit(requests=5, per_seconds=1),
        legal=LegalInfo(restrictions="Regional Internet Registry public data; personal contacts are not stored."),
        fields=["network_name", "network_handle", "start_address", "end_address", "holder_org", "country"],
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        url = f"https://rdap.org/ip/{identifier.value}"
        resp = await self.fetch(ctx, url, headers={"Accept": "application/rdap+json"})
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        holder = None
        for ent in d.get("entities") or []:
            if "registrant" in (ent.get("roles") or []):
                vc = _vcard(ent)
                if vc.get("kind") in ("org", None):
                    holder = vc.get("fn") or vc.get("org")
        attrs = {
            "network_name": d.get("name"),
            "network_handle": d.get("handle"),
            "start_address": d.get("startAddress"),
            "end_address": d.get("endAddress"),
            "holder_org": holder,
            "country": d.get("country"),
        }
        return [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="ip_network_registration",
                title=f"{identifier.value} in network {attrs['network_name'] or attrs['network_handle']}",
                description=f"Registered network {attrs['start_address']}–{attrs['end_address']}"
                + (f" held by {holder}" if holder else "")
                + ".",
                url=url,
                attributes=attrs,
                raw=resp.content,
                entity_hint=f"ip:{identifier.value}",
                entity_kind="ip",
                claim_key=f"ip.network:{identifier.value}={attrs['network_handle']}",
            )
        ]


DOMAIN_ADAPTERS = [
    DnsRecordsAdapter,
    RdapDomainAdapter,
    CrtShAdapter,
    HttpSecurityAdapter,
    TeamCymruAsnAdapter,
    WaybackAdapter,
    RdapIpAdapter,
]
