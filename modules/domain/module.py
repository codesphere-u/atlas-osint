from __future__ import annotations

from typing import Any

from modules.base import IntelligenceModule
from shared.types import Finding, Identifier, IdentifierType


class DomainModule(IntelligenceModule):
    name = "domain"
    title = "Domain & infrastructure intelligence"
    input_types = (IdentifierType.DOMAIN, IdentifierType.URL, IdentifierType.IP)
    guardrails = (
        "Passive sources by default (DNS, RDAP, CT logs, archives, BGP).",
        "Active requests and subdomain listings only within the authorised scope.",
        "No port scanning, brute forcing or exploitation.",
    )

    def summarize(self, findings: list[Finding], subject: Identifier) -> dict[str, Any]:
        reg = next((f for f in findings if f.finding_type == "domain_registration"), None)
        web = next((f for f in findings if f.finding_type == "web_security_posture"), None)
        ips = sorted(x for x in {f.attributes.get("ip_address") for f in findings if f.finding_type == "ip_asn"} if x)
        return {
            "registrar": reg.attributes.get("registrar") if reg else None,
            "created": reg.attributes.get("created") if reg else None,
            "expires": reg.attributes.get("expires") if reg else None,
            # distinct names: crt.sh and Cert Spotter independently report (and corroborate) the same subdomains
            "subdomains": len({f.attributes.get("subdomain") for f in findings if f.finding_type == "subdomain"}),
            "ips": ips,
            "asns": sorted(x for x in {f.attributes.get("asn") for f in findings if f.finding_type == "ip_asn"} if x),
            "security_headers_missing": web.attributes.get("security_headers_missing") if web else None,
        }
