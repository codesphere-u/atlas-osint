"""Additional infrastructure sources (v0.2).

* Shodan InternetDB – passive exposure data (open ports, CPEs, version-based CVEs) from Shodan's own scans.
* Cert Spotter – second certificate-transparency source (unexpired issuances).
* security.txt (RFC 9116) – the organisation's published security contact policy (scope required).
* Email-security DNS – SPF, DMARC, MTA-STS, TLS-RPT, BIMI, DNSSEC, common DKIM selectors.
* Lookalike domains – typosquat/homoglyph permutations of an authorised domain checked via DNS only.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

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
from integrations.sources.domain import _dns, _domain_of
from shared.dns import DnsLookupError
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

RISKY_PORTS = {
    21: "FTP",
    23: "Telnet",
    445: "SMB",
    1433: "MSSQL",
    1521: "Oracle DB",
    2375: "Docker API (unauthenticated)",
    3306: "MySQL",
    3389: "RDP",
    5432: "PostgreSQL",
    5900: "VNC",
    6379: "Redis",
    9200: "Elasticsearch",
    11211: "Memcached",
    27017: "MongoDB",
}


async def _resolve_ipv4(ctx: CollectionContext, identifier: Identifier, limit: int = 5) -> list[str]:
    """Public IPv4 addresses of the identifier (InternetDB indexes IPv4 only)."""
    if identifier.type == IdentifierType.IP:
        ips = [identifier.value]
    else:
        try:
            ips = (await _dns(ctx)(_domain_of(identifier), "A"))[:limit]
        except DnsLookupError as exc:
            raise SourceError(AdapterStatus.UNAVAILABLE, str(exc)) from exc
    out = []
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if addr.version == 4 and addr.is_global:
            out.append(ip)
    return out


class ShodanInternetDbAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="shodan_internetdb",
        display_name="Shodan InternetDB",
        description="Open ports, software (CPE), hostnames and version-based vulnerability identifiers for an IP, "
        "from Shodan's own periodic Internet scans. ATLAS does not scan anything itself.",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.IP, IdentifierType.DOMAIN],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://internetdb.shodan.io/",
        rate_limit=RateLimit(requests=5, per_seconds=1, notes="high burst limit; abusive traffic is throttled"),
        legal=LegalInfo(
            terms_url="https://blog.shodan.io/introducing-the-internetdb-api/",
            license="Free for non-commercial use (Shodan)",
            restrictions="Free for non-commercial use; building commercial products requires a Shodan licence. "
            "Vulnerability IDs are inferred from banner versions and are unverified.",
        ),
        fields=["ip_address", "open_ports", "risky_ports", "hostnames", "cpes", "tags", "vulns", "vuln_count"],
        freshness="weekly scan cadence (Shodan)",
        reliability=Reliability.B,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        out: list[Finding] = []
        for ip in await _resolve_ipv4(ctx, identifier):
            resp = await self.fetch(ctx, f"https://internetdb.shodan.io/{quote(ip)}")
            if resp.status_code == 404:
                continue
            if not resp.ok:
                raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
            d = resp.json()
            ports = sorted(int(p) for p in d.get("ports") or [])
            risky = [f"{p}/{RISKY_PORTS[p]}" for p in ports if p in RISKY_PORTS]
            vulns = sorted(d.get("vulns") or [], reverse=True)
            attrs = {
                "ip_address": ip,
                "open_ports": ports,
                "risky_ports": risky,
                "hostnames": (d.get("hostnames") or [])[:20],
                "cpes": (d.get("cpes") or [])[:20],
                "tags": d.get("tags") or [],
                "vulns": vulns[:50],
                "vuln_count": len(vulns),
            }
            desc = f"Shodan last observed {len(ports)} open port(s) on {ip}: {', '.join(map(str, ports)) or 'none'}."
            if risky:
                desc += f" Sensitive services exposed: {', '.join(risky)}."
            if vulns:
                desc += (
                    f" {len(vulns)} CVE identifier(s) are associated with the detected software versions "
                    "(version-based inference – not confirmed exploitable)."
                )
            flags = ["risk:exposed_service"] if risky else []
            if vulns:
                flags.append("risk:potential_vulnerabilities")
            out.append(
                self.finding(
                    module="domain",
                    subject=identifier,
                    finding_type="internet_exposure",
                    title=f"Internet exposure of {ip}: {len(ports)} open port(s)",
                    description=desc,
                    url=f"https://internetdb.shodan.io/{ip}",
                    attributes=attrs,
                    linked=[
                        LinkedIdentifier(
                            identifier=Identifier(type=IdentifierType.IP, value=ip), relation="resolves_to"
                        )
                    ],
                    match_type=MatchType.EXACT if identifier.type == IdentifierType.IP else MatchType.RELATED,
                    excerpt=f"ports={ports}; cpes={attrs['cpes'][:3]}",
                    raw=resp.content,
                    entity_hint=f"ip:{ip}",
                    entity_kind="ip",
                    claim_key=f"ip.ports:{ip}={','.join(map(str, ports))}",
                    flags=flags,
                )
            )
        return out


class CertSpotterAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="certspotter",
        display_name="SSLMate Cert Spotter (CT issuances)",
        description="Unexpired certificates for a domain and its subdomains from Certificate Transparency logs. "
        "Complements crt.sh (independent infrastructure, corroborates subdomains).",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.DOMAIN],
        access_method=AccessMethod.PUBLIC_API,
        homepage="https://sslmate.com/certspotter/api/docs-v1",
        auth=AuthRequirement(
            required=False,
            optional=True,
            kind="bearer",
            settings_fields=["certspotter_api_key"],
            how_to_obtain="Optional SSLMate API key for higher limits.",
        ),
        rate_limit=RateLimit(requests=1, per_seconds=10, notes="small anonymous allowance"),
        legal=LegalInfo(
            terms_url="https://sslmate.com/terms",
            license="SSLMate terms of service",
            restrictions="Subdomain names are listed only for domains inside the authorised scope.",
        ),
        fields=[
            "certificate_count",
            "issuers",
            "subdomain",
            "subdomain_count",
            "earliest_not_after",
            "listing_withheld",
        ],
        freshness="near real-time",
        reliability=Reliability.A,
        timeout_seconds=40.0,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = identifier.value
        headers = {}
        key = ctx.secret("certspotter_api_key")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        resp = await self.fetch(
            ctx,
            "https://api.certspotter.com/v1/issuances",
            params={"domain": domain, "include_subdomains": "true", "expand": ["dns_names", "issuer"]},
            headers=headers,
            max_bytes=15_000_000,
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        rows = resp.json()
        if not rows:
            return []
        names: set[str] = set()
        issuers: dict[str, int] = {}
        not_after: list[str] = []
        for r in rows:
            for n in r.get("dns_names") or []:
                n = str(n).lower().lstrip("*.")
                if n == domain or n.endswith("." + domain):
                    names.add(n)
            issuer = ((r.get("issuer") or {}).get("friendly_name")) or "unknown"
            issuers[issuer] = issuers.get(issuer, 0) + 1
            if r.get("not_after"):
                not_after.append(str(r["not_after"]))
        subs = sorted(n for n in names if n != domain)
        in_scope = ctx.scope.domain_in_scope(domain)
        url = f"https://sslmate.com/certspotter/?domain={quote(domain)}"
        findings = [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="certificate_transparency_active",
                title=f"{len(rows)} unexpired certificates for *.{domain}",
                description=f"Cert Spotter lists {len(rows)} unexpired certificates covering {domain} or its "
                f"subdomains from {len(issuers)} issuer(s); {len(subs)} distinct subdomain names."
                + ("" if in_scope else " Subdomain names withheld: domain not in authorised scope."),
                url=url,
                attributes={
                    "certificate_count": len(rows),
                    "issuers": dict(sorted(issuers.items(), key=lambda kv: -kv[1])[:10]),
                    "subdomain_count": len(subs),
                    "earliest_not_after": min(not_after) if not_after else None,
                    "listing_withheld": not in_scope,
                },
                raw=resp.content,
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.ct_active:{domain}",
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
                        description=f"{sub} appears in an unexpired CT-logged certificate (Cert Spotter).",
                        url=url,
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


SECURITY_TXT_FIELDS = (
    "contact",
    "expires",
    "encryption",
    "policy",
    "preferred-languages",
    "canonical",
    "hiring",
    "acknowledgments",
)


def parse_security_txt(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in SECURITY_TXT_FIELDS:
            out.setdefault(key, []).append(value.strip()[:300])
    return out


class SecurityTxtAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="security_txt",
        display_name="security.txt (RFC 9116)",
        description="The organisation's published vulnerability-disclosure contact and policy file.",
        category=SourceCategory.INFRASTRUCTURE,
        input_types=[IdentifierType.DOMAIN, IdentifierType.URL],
        access_method=AccessMethod.PUBLIC_WEB,
        homepage="https://www.rfc-editor.org/rfc/rfc9116",
        rate_limit=RateLimit(requests=1, per_seconds=2),
        legal=LegalInfo(
            restrictions="Single request for a file published for public consumption; only performed when the "
            "domain is in the investigation's authorised scope.",
            active_probe=True,
        ),
        fields=[
            "present",
            "location",
            "contact",
            "expires",
            "expired",
            "encryption",
            "policy",
            "canonical",
            "preferred_languages",
            "pgp_signed",
        ],
        freshness="real-time",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = _domain_of(identifier)
        resp = None
        for path in ("/.well-known/security.txt", "/security.txt"):
            url = f"https://{domain}{path}"
            try:
                r = await self.fetch(ctx, url, max_bytes=64_000)
            except SourceError:
                continue
            ctype = r.headers.get("content-type", "")
            if r.ok and "text/plain" in ctype and "contact:" in r.text.lower():
                resp = r
                break
        if resp is None:
            return [
                self.finding(
                    module="domain",
                    subject=identifier,
                    finding_type="security_txt",
                    title=f"No security.txt published for {domain}",
                    description=f"Neither /.well-known/security.txt nor /security.txt returned a valid file on "
                    f"{domain}. Security researchers have no standard channel to report vulnerabilities.",
                    url=f"https://{domain}/.well-known/security.txt",
                    attributes={"present": False},
                    entity_hint=f"domain:{domain}",
                    entity_kind="domain",
                    claim_key=f"domain.security_txt:{domain}=absent",
                )
            ]
        fields = parse_security_txt(resp.text)
        expires = parse_datetime((fields.get("expires") or [None])[0])
        expired = bool(expires and expires < datetime.now(UTC))
        attrs: dict[str, Any] = {
            "present": True,
            "location": resp.url,
            "contact": fields.get("contact", [])[:5],
            "expires": expires.isoformat() if expires else None,
            "expired": expired,
            "encryption": fields.get("encryption", [])[:3],
            "policy": fields.get("policy", [])[:3],
            "canonical": fields.get("canonical", [])[:3],
            "preferred_languages": (fields.get("preferred-languages") or [None])[0],
            "pgp_signed": "-----BEGIN PGP SIGNED MESSAGE-----" in resp.text,
        }
        desc = f"{domain} publishes security.txt with {len(attrs['contact'])} contact(s)"
        desc += (
            "; the file has EXPIRED."
            if expired
            else (f", valid until {expires.date()}." if expires else "; required Expires field missing.")
        )
        return [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="security_txt",
                title=f"security.txt published by {domain}",
                description=desc,
                url=resp.url,
                attributes=attrs,
                raw=resp.content,
                excerpt="; ".join(attrs["contact"][:3]),
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.security_txt:{domain}=present",
            )
        ]


COMMON_DKIM_SELECTORS = ("google", "selector1", "selector2", "default", "k1", "s1", "dkim", "mail")


def _tag(record: str | None, tag: str) -> str | None:
    if not record:
        return None
    for part in record.split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip().lower() == tag:
            return v.strip()
    return None


class EmailSecurityAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="email_security",
        display_name="Email-security DNS records",
        description="SPF, DMARC, MTA-STS, TLS-RPT, BIMI, DNSSEC and common DKIM selectors. The MTA-STS policy "
        "file is fetched only for domains in the authorised scope.",
        category=SourceCategory.DOMAIN,
        input_types=[IdentifierType.DOMAIN],
        access_method=AccessMethod.DNS,
        homepage="https://www.rfc-editor.org/rfc/rfc8461",
        rate_limit=RateLimit(requests=50, per_seconds=1),
        legal=LegalInfo(restrictions="Public DNS data; one public policy-file request within authorised scope."),
        fields=[
            "spf",
            "spf_all",
            "dmarc",
            "dmarc_policy",
            "dmarc_pct",
            "dmarc_rua",
            "mta_sts",
            "mta_sts_mode",
            "tls_rpt",
            "bimi",
            "dnssec",
            "dkim_selectors_found",
            "mail_enabled",
        ],
        freshness="real-time (subject to TTLs)",
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = identifier.value
        resolver = _dns(ctx)

        async def txt(name: str) -> list[str]:
            try:
                return await resolver(name, "TXT")
            except DnsLookupError:
                return []

        try:
            mx = await resolver(domain, "MX")
        except DnsLookupError as exc:
            raise SourceError(AdapterStatus.UNAVAILABLE, str(exc)) from exc
        root_txt, dmarc_txt, sts_txt, rpt_txt, bimi_txt = await asyncio.gather(
            txt(domain),
            txt(f"_dmarc.{domain}"),
            txt(f"_mta-sts.{domain}"),
            txt(f"_smtp._tls.{domain}"),
            txt(f"default._bimi.{domain}"),
        )
        try:
            ds = await resolver(domain, "DS")
        except DnsLookupError:
            ds = []
        dkim_hits = []
        dkim_results = await asyncio.gather(*(txt(f"{s}._domainkey.{domain}") for s in COMMON_DKIM_SELECTORS))
        for sel, recs in zip(COMMON_DKIM_SELECTORS, dkim_results, strict=True):
            if any("p=" in r for r in recs):
                dkim_hits.append(sel)
        spf = next((t for t in root_txt if t.lower().startswith("v=spf1")), None)
        spf_all = None
        if spf:
            m = re.search(r"([+\-~?]?)all\b", spf)
            spf_all = (m.group(1) or "+") + "all" if m else "none"
        dmarc = next((t for t in dmarc_txt if t.lower().startswith("v=dmarc1")), None)
        sts = next((t for t in sts_txt if t.lower().startswith("v=stsv1")), None)
        rpt = next((t for t in rpt_txt if t.lower().startswith("v=tlsrptv1")), None)
        bimi = next((t for t in bimi_txt if t.lower().startswith("v=bimi1")), None)
        mode = None
        if sts and ctx.scope.domain_in_scope(domain):
            try:
                pol = await self.fetch(ctx, f"https://mta-sts.{domain}/.well-known/mta-sts.txt", max_bytes=64_000)
                if pol.ok:
                    m = re.search(r"(?im)^mode:\s*(enforce|testing|none)\s*$", pol.text)
                    mode = m.group(1).lower() if m else None
            except Exception:
                mode = None
        attrs = {
            "mail_enabled": bool(mx),
            "spf": spf,
            "spf_all": spf_all,
            "dmarc": dmarc,
            "dmarc_policy": _tag(dmarc, "p"),
            "dmarc_pct": _tag(dmarc, "pct"),
            "dmarc_rua": bool(_tag(dmarc, "rua")),
            "mta_sts": bool(sts),
            "mta_sts_mode": mode,
            "tls_rpt": bool(rpt),
            "bimi": bool(bimi),
            "dnssec": bool(ds),
            "dkim_selectors_found": dkim_hits,
        }
        parts = [
            f"SPF {spf_all or 'absent'}",
            f"DMARC {attrs['dmarc_policy'] or 'absent'}",
            f"MTA-STS {mode or ('present' if sts else 'absent')}",
            f"TLS-RPT {'present' if rpt else 'absent'}",
            f"DNSSEC {'signed' if ds else 'unsigned'}",
            f"DKIM selectors found: {', '.join(dkim_hits) or 'none of the common ones'}",
        ]
        return [
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="email_security_posture",
                title=f"Email-security records of {domain}",
                description="; ".join(parts) + ". Absence of a common DKIM selector does not prove DKIM is unused.",
                url=f"dns:{domain}?email-security",
                attributes=attrs,
                excerpt=(dmarc or spf or "")[:200] or None,
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.email_security:{domain}",
            )
        ]


# --- lookalike domains -------------------------------------------------------------------------------------------

_HOMOGLYPHS = {
    "o": ["0"],
    "l": ["1", "i"],
    "i": ["1", "l"],
    "e": ["3"],
    "a": ["4"],
    "s": ["5"],
    "m": ["rn"],
    "w": ["vv"],
    "g": ["q"],
    "b": ["d"],
    "d": ["b", "cl"],
}
_KEYBOARD = {
    "q": "wa",
    "w": "qes",
    "e": "wrd",
    "r": "etf",
    "t": "ryg",
    "y": "tuh",
    "u": "yij",
    "i": "uok",
    "o": "ipl",
    "p": "ol",
    "a": "qsz",
    "s": "awdz",
    "d": "sefx",
    "f": "drgc",
    "g": "fthv",
    "h": "gyjb",
    "j": "hukn",
    "k": "jilm",
    "l": "kop",
    "z": "asx",
    "x": "zsdc",
    "c": "xdfv",
    "v": "cfgb",
    "b": "vghn",
    "n": "bhjm",
    "m": "njk",
}
_ALT_TLDS = ("com", "net", "org", "co", "io", "info", "biz", "app", "online", "site")


def lookalike_candidates(domain: str, limit: int = 150) -> list[tuple[str, str]]:
    """Return (candidate, technique) pairs for the registrable label of ``domain`` (deterministic order)."""
    label, _, tld = domain.partition(".")
    if not label or not tld:
        return []
    out: dict[str, str] = {}

    def add(lbl: str, technique: str, t: str = tld) -> None:
        if lbl and lbl != label and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", lbl):
            out.setdefault(f"{lbl}.{t}", technique)

    for i in range(len(label)):
        add(label[:i] + label[i + 1 :], "omission")
        add(label[:i] + label[i] + label[i:], "repetition")
        if i < len(label) - 1:
            add(label[:i] + label[i + 1] + label[i] + label[i + 2 :], "transposition")
        for rep in _HOMOGLYPHS.get(label[i], []):
            add(label[:i] + rep + label[i + 1 :], "homoglyph")
        for rep in _KEYBOARD.get(label[i], ""):
            add(label[:i] + rep + label[i + 1 :], "keyboard")
        if 0 < i < len(label):
            add(label[:i] + "-" + label[i:], "hyphenation")
    for t in _ALT_TLDS:
        if t != tld:
            out.setdefault(f"{label}.{t}", "tld-swap")  # same label, different TLD
    for word in ("login", "secure", "account", "support"):
        add(f"{label}-{word}", "keyword")
    ordered = sorted(
        out.items(),
        key=lambda kv: (
            [
                "tld-swap",
                "homoglyph",
                "omission",
                "transposition",
                "repetition",
                "hyphenation",
                "keyword",
                "keyboard",
            ].index(kv[1]),
            kv[0],
        ),
    )
    return [(d, t) for d, t in ordered if d != domain][:limit]


class LookalikeDomainsAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="lookalike_domains",
        display_name="Lookalike-domain discovery (DNS)",
        description="Generates typosquat, homoglyph, TLD-swap and keyword permutations of an authorised domain and "
        "checks which are registered and mail-capable using DNS only – a brand-protection check.",
        category=SourceCategory.DOMAIN,
        input_types=[IdentifierType.DOMAIN],
        access_method=AccessMethod.DNS,
        homepage="https://github.com/elceef/dnstwist",
        rate_limit=RateLimit(requests=200, per_seconds=1),
        legal=LegalInfo(
            restrictions="Only for domains in the authorised scope (your own brand). DNS lookups only; no requests "
            "are sent to the lookalike domains' web servers.",
            requires_authorized_scope=True,
        ),
        fields=[
            "lookalike_domain",
            "technique",
            "a_records",
            "mx_records",
            "mail_capable",
            "candidates_checked",
            "registered_count",
            "mail_capable_count",
        ],
        freshness="real-time",
        reliability=Reliability.A,
        timeout_seconds=90.0,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        domain = identifier.value
        resolver = _dns(ctx)
        candidates = lookalike_candidates(domain, ctx.settings.lookalike_max_candidates)
        sem = asyncio.Semaphore(20)

        async def check(cand: str) -> tuple[list[str], list[str], list[str]]:
            async with sem:
                try:
                    a = await resolver(cand, "A")
                    mx = await resolver(cand, "MX")
                    ns = [] if (a or mx) else await resolver(cand, "NS")
                except DnsLookupError:
                    return [], [], []
            return a, mx, ns

        results = await asyncio.gather(*(check(c) for c, _ in candidates))
        findings: list[Finding] = []
        registered = mail_capable = 0
        for (cand, technique), (a, mx, ns) in zip(candidates, results, strict=True):
            if not (a or mx or ns):
                continue
            registered += 1
            # Null MX (RFC 7505, "0 .") and localhost cannot receive mail.
            mx_hosts = sorted(
                h for h in (r.split()[-1].rstrip(".").lower() for r in mx if r.split()) if h and h != "localhost"
            )
            if mx_hosts:
                mail_capable += 1
            findings.append(
                self.finding(
                    module="domain",
                    subject=identifier,
                    finding_type="lookalike_domain",
                    title=f"Registered lookalike: {cand} ({technique})",
                    description=f"{cand} resembles {domain} ({technique}) and is registered"
                    + (f"; it can receive email via {', '.join(mx_hosts[:2])}" if mx_hosts else "")
                    + ". Registration alone does not prove malicious intent – review ownership and content.",
                    url=f"dns:{cand}",
                    attributes={
                        "lookalike_domain": cand,
                        "technique": technique,
                        "a_records": sorted(a)[:5],
                        "mx_records": mx_hosts[:5],
                        "mail_capable": bool(mx_hosts),
                    },
                    linked=[
                        LinkedIdentifier(
                            identifier=Identifier(type=IdentifierType.DOMAIN, value=cand),
                            relation="lookalike_of",
                            evidence_kind=EvidenceKind.INFERENCE,
                        )
                    ],
                    match_type=MatchType.RELATED,
                    entity_hint=f"domain:{domain}",
                    entity_kind="domain",
                    claim_key=f"domain.lookalike:{cand}",
                    flags=["risk:lookalike_mail"] if mx_hosts else ["risk:lookalike"],
                )
            )
        findings.insert(
            0,
            self.finding(
                module="domain",
                subject=identifier,
                finding_type="lookalike_summary",
                title=f"{registered} of {len(candidates)} lookalike domains are registered",
                description=f"Checked {len(candidates)} permutations of {domain}; {registered} resolve in DNS, "
                f"{mail_capable} of them accept email.",
                url=f"dns:{domain}?lookalikes",
                attributes={
                    "candidates_checked": len(candidates),
                    "registered_count": registered,
                    "mail_capable_count": mail_capable,
                },
                entity_hint=f"domain:{domain}",
                entity_kind="domain",
                claim_key=f"domain.lookalike_summary:{domain}",
            ),
        )
        return findings


INFRASTRUCTURE_ADAPTERS = [
    ShodanInternetDbAdapter,
    CertSpotterAdapter,
    SecurityTxtAdapter,
    EmailSecurityAdapter,
    LookalikeDomainsAdapter,
]
