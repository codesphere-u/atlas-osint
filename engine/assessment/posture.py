"""External exposure scorecard for domains and IPs.

A deterministic, explainable checklist built only from collected findings – no extra network requests.
Each check has a severity weight (high 10, medium 5, low 2). Status scoring: pass = full weight,
warn = half, fail = none; ``info`` and ``unknown`` checks are excluded from the score (unknown = the data
needed was not collected, e.g. the domain was outside the authorised scope for website checks).

Score = 100 × earned / possible, graded A (≥90) · B (≥80) · C (≥70) · D (≥60) · F (<60). A score is only
given when at least five checks could be evaluated. Vendor scores (UpGuard, SecurityScorecard, …) weight
controls differently, so ATLAS scores are not comparable with them; the per-check detail is the point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.verification.scoring import classify
from integrations.sources.base import parse_datetime
from shared.types import Finding

Status = Literal["pass", "warn", "fail", "info", "unknown"]
Severity = Literal["high", "medium", "low"]
WEIGHTS = {"high": 10, "medium": 5, "low": 2}
STATUSES = ("pass", "warn", "fail", "info", "unknown")
STATUS_FACTOR = dict(zip(STATUSES[:3], (1.0, 0.5, 0.0), strict=True))
METHODOLOGY = (
    "Checks are derived from collected evidence only. Weights: high 10, medium 5, low 2. pass = full weight, "
    "warn = half, fail = 0; info/unknown are excluded. Grade A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F < 60. "
    "Requires at least 5 evaluated checks. Not comparable with commercial rating vendors."
)


class Check(BaseModel):
    id: str
    category: str
    title: str
    status: Status
    severity: Severity
    detail: str
    recommendation: str | None = None
    reference: str | None = None
    finding_ids: list[str] = Field(default_factory=list)


class PostureReport(BaseModel):
    score: int | None = None
    grade: str | None = None
    evaluated: int = 0
    checks: list[Check] = Field(default_factory=list)
    categories: dict[str, dict[str, int]] = Field(default_factory=dict)
    methodology: str = METHODOLOGY


def _grade(score: int) -> str:
    for threshold, grade in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= threshold:
            return grade
    return "F"


def _first(findings: list[Finding], ftype: str) -> Finding | None:
    return next((f for f in findings if f.finding_type == ftype), None)


def assess_posture(findings: list[Finding], now: datetime | None = None) -> PostureReport:
    now = now or datetime.now(UTC)
    usable = [f for f in findings if classify(f) != "rejected"]
    checks: list[Check] = []

    def add(
        cid: str,
        cat: str,
        title: str,
        status: Status,
        sev: Severity,
        detail: str,
        rec: str | None = None,
        ref: str | None = None,
        src: Finding | list[Finding] | None = None,
    ) -> None:
        ids = [s.id for s in (src if isinstance(src, list) else [src] if src else [])]
        checks.append(
            Check(
                id=cid,
                category=cat,
                title=title,
                status=status,
                severity=sev,
                detail=detail,
                recommendation=rec if status not in ("pass", "info") else None,
                reference=ref,
                finding_ids=ids,
            )
        )

    # --- email authentication ---------------------------------------------------------------------------------
    mail = _first(usable, "email_security_posture")
    if mail:
        a: dict[str, Any] = mail.attributes
        policy = (a.get("dmarc_policy") or "").lower()
        spf_all = a.get("spf_all")
        enforced = policy in ("reject", "quarantine")
        if spf_all == "-all" or (spf_all == "~all" and enforced):
            add(
                "EMAIL-SPF",
                "Email",
                "SPF restricts senders",
                "pass",
                "high",
                f"SPF ends with {spf_all}.",
                ref="https://www.rfc-editor.org/rfc/rfc7208",
                src=mail,
            )
        elif spf_all == "~all":
            add(
                "EMAIL-SPF",
                "Email",
                "SPF restricts senders",
                "warn",
                "high",
                "SPF soft-fails (~all) and DMARC is not enforcing, so spoofed mail may be delivered.",
                "Enforce DMARC (p=quarantine/reject) or end SPF with -all.",
                "https://www.rfc-editor.org/rfc/rfc7208",
                mail,
            )
        else:
            add(
                "EMAIL-SPF",
                "Email",
                "SPF restricts senders",
                "fail",
                "high",
                f"SPF is {'missing' if not a.get('spf') else 'permissive (' + str(spf_all) + ')'}.",
                "Publish an SPF record ending in -all (use 'v=spf1 -all' for domains that send no mail).",
                "https://www.rfc-editor.org/rfc/rfc7208",
                mail,
            )
        if enforced:
            add(
                "EMAIL-DMARC",
                "Email",
                "DMARC enforced",
                "pass",
                "high",
                f"DMARC policy p={policy}.",
                ref="https://www.rfc-editor.org/rfc/rfc7489",
                src=mail,
            )
        else:
            add(
                "EMAIL-DMARC",
                "Email",
                "DMARC enforced",
                "warn" if policy == "none" else "fail",
                "high",
                "DMARC is in monitoring mode (p=none)." if policy == "none" else "No DMARC record.",
                "Move DMARC to p=quarantine, then p=reject, after reviewing aggregate reports.",
                "https://www.rfc-editor.org/rfc/rfc7489",
                mail,
            )
        add(
            "EMAIL-DMARC-RUA",
            "Email",
            "DMARC aggregate reporting",
            "pass" if a.get("dmarc_rua") else "warn",
            "low",
            "Aggregate reports (rua) are " + ("configured." if a.get("dmarc_rua") else "not configured."),
            "Add rua=mailto:… to receive DMARC aggregate reports.",
            "https://www.rfc-editor.org/rfc/rfc7489",
            mail,
        )
        mode = a.get("mta_sts_mode")
        if mode == "enforce":
            add(
                "EMAIL-MTASTS",
                "Email",
                "MTA-STS enforces TLS for inbound mail",
                "pass",
                "medium",
                "MTA-STS policy mode is enforce.",
                ref="https://www.rfc-editor.org/rfc/rfc8461",
                src=mail,
            )
        else:
            detail = (
                "MTA-STS is in testing mode."
                if mode == "testing"
                else "MTA-STS record present; policy file not verified (outside scope or unreachable)."
                if a.get("mta_sts")
                else "No MTA-STS policy; inbound mail can be downgraded to plaintext."
            )
            add(
                "EMAIL-MTASTS",
                "Email",
                "MTA-STS enforces TLS for inbound mail",
                "warn",
                "medium",
                detail,
                "Publish an MTA-STS policy in enforce mode.",
                "https://www.rfc-editor.org/rfc/rfc8461",
                mail,
            )
        add(
            "EMAIL-TLSRPT",
            "Email",
            "SMTP TLS reporting",
            "pass" if a.get("tls_rpt") else "warn",
            "low",
            "TLS-RPT is " + ("configured." if a.get("tls_rpt") else "not configured."),
            "Publish _smtp._tls TXT (v=TLSRPTv1; rua=…).",
            "https://www.rfc-editor.org/rfc/rfc8460",
            mail,
        )
        sels = a.get("dkim_selectors_found") or []
        add(
            "EMAIL-DKIM",
            "Email",
            "DKIM key published",
            "pass" if sels else "unknown",
            "medium",
            f"DKIM keys found for selector(s): {', '.join(sels)}."
            if sels
            else "No key at common selectors; DKIM may still use a custom selector (cannot be enumerated).",
            ref="https://www.rfc-editor.org/rfc/rfc6376",
            src=mail,
        )
        add(
            "DNS-DNSSEC",
            "DNS",
            "DNSSEC signed",
            "pass" if a.get("dnssec") else "warn",
            "medium",
            "The zone is " + ("signed (DS record at parent)." if a.get("dnssec") else "not DNSSEC-signed."),
            "Enable DNSSEC at the DNS provider and publish the DS record at the registrar.",
            "https://www.rfc-editor.org/rfc/rfc4033",
            mail,
        )

    # --- DNS -----------------------------------------------------------------------------------------------------
    dns_findings = [f for f in usable if f.finding_type == "dns_record"]
    if dns_findings:
        caa = [f for f in dns_findings if f.attributes.get("record_type") == "CAA"]
        add(
            "DNS-CAA",
            "DNS",
            "CAA restricts certificate issuers",
            "pass" if caa else "warn",
            "low",
            "CAA records are " + ("published." if caa else "absent: any CA may issue certificates."),
            "Publish CAA records naming the CAs you use.",
            "https://www.rfc-editor.org/rfc/rfc8659",
            caa or dns_findings[0],
        )

    # --- website -------------------------------------------------------------------------------------------------
    web = _first(usable, "web_security_posture")
    if web:
        a = web.attributes
        present = set(a.get("security_headers_present") or [])
        add(
            "WEB-HTTPS",
            "Web",
            "HTTP redirects to HTTPS",
            "pass" if a.get("https_redirect") else "fail",
            "high",
            f"Final URL: {a.get('final_url')}.",
            "Redirect all HTTP traffic to HTTPS.",
            None,
            web,
        )
        for cid, header, sev, rec in (
            ("WEB-HSTS", "HSTS", "medium", "Send Strict-Transport-Security with a long max-age."),
            ("WEB-CSP", "CSP", "medium", "Define a Content-Security-Policy."),
            ("WEB-XCTO", "X-Content-Type-Options", "low", "Send X-Content-Type-Options: nosniff."),
            ("WEB-REFERRER", "Referrer-Policy", "low", "Send a Referrer-Policy header."),
        ):
            add(
                cid,
                "Web",
                f"{header} header",
                "pass" if header in present else "warn",
                sev,  # type: ignore[arg-type]
                f"{header} is {'present' if header in present else 'missing'}.",
                rec,
                "https://owasp.org/www-project-secure-headers/",
                web,
            )
        framing = "X-Frame-Options" in present or "CSP" in present
        add(
            "WEB-FRAME",
            "Web",
            "Clickjacking protection",
            "pass" if framing else "warn",
            "low",
            "Framing is " + ("restricted." if framing else "not restricted (no X-Frame-Options or CSP)."),
            "Send X-Frame-Options: DENY or CSP frame-ancestors.",
            "https://owasp.org/www-project-secure-headers/",
            web,
        )
    sec_txt = _first(usable, "security_txt")
    if sec_txt:
        a = sec_txt.attributes
        status: Status = "pass" if a.get("present") and not a.get("expired") else "warn"
        add(
            "WEB-SECURITY-TXT",
            "Web",
            "security.txt vulnerability-disclosure contact",
            status,
            "low",
            "Published and current."
            if status == "pass"
            else ("Published but expired." if a.get("present") else "Not published."),
            "Publish /.well-known/security.txt with Contact and Expires.",
            "https://www.rfc-editor.org/rfc/rfc9116",
            sec_txt,
        )

    # --- exposure -------------------------------------------------------------------------------------------------
    exposure = [f for f in usable if f.finding_type == "internet_exposure"]
    if exposure:
        risky = [f for f in exposure if f.attributes.get("risky_ports")]
        ports = sorted({p for f in risky for p in f.attributes.get("risky_ports", [])})
        add(
            "EXPOSURE-PORTS",
            "Exposure",
            "No sensitive services exposed",
            "fail" if risky else "pass",
            "high",
            f"Exposed: {', '.join(ports)}." if risky else "No database, remote-access or file-sharing ports observed.",
            "Restrict these services to private networks or a VPN.",
            "https://internetdb.shodan.io/",
            risky or exposure,
        )
        vuln = [f for f in exposure if f.attributes.get("vuln_count")]
        total = sum(int(f.attributes.get("vuln_count") or 0) for f in vuln)
        add(
            "EXPOSURE-VULNS",
            "Exposure",
            "No known-vulnerable software versions",
            "warn" if vuln else "pass",
            "high",
            f"{total} CVE identifier(s) associated with observed software versions (inferred from banners, unverified)."
            if vuln
            else "No CVEs associated with observed software versions.",
            "Verify versions and patch or upgrade the affected services.",
            None,
            vuln or exposure,
        )

    # --- registration ---------------------------------------------------------------------------------------------
    reg = _first(usable, "domain_registration")
    if reg:
        expires = parse_datetime(reg.attributes.get("expires"))
        if expires:
            days = (expires - now).days
            st: Status = "fail" if days < 30 else "warn" if days < 90 else "pass"
            add(
                "REG-EXPIRY",
                "Registration",
                "Domain registration not expiring soon",
                st,
                "high",
                f"Registration expires {expires.date()} ({days} days).",
                "Renew the domain and enable auto-renewal.",
                None,
                reg,
            )
        statuses = " ".join(reg.attributes.get("status") or []).lower()
        locked = "transfer prohibited" in statuses
        add(
            "REG-LOCK",
            "Registration",
            "Registrar transfer lock",
            "pass" if locked else "warn",
            "low",
            "clientTransferProhibited is " + ("set." if locked else "not set."),
            "Ask the registrar to enable transfer (and update/delete) locks.",
            None,
            reg,
        )

    # --- brand -------------------------------------------------------------------------------------------------------
    look = _first(usable, "lookalike_summary")
    if look:
        a = look.attributes
        mail_cap, registered = int(a.get("mail_capable_count") or 0), int(a.get("registered_count") or 0)
        st2: Status = "warn" if mail_cap else ("info" if registered else "pass")
        add(
            "BRAND-LOOKALIKES",
            "Brand",
            "Lookalike domains",
            st2,
            "medium",
            f"{registered} of {a.get('candidates_checked')} permutations are registered; {mail_cap} accept email.",
            "Review the mail-capable lookalikes; consider defensive registration or takedown requests.",
            None,
            look,
        )

    possible = sum(WEIGHTS[c.severity] for c in checks if c.status in ("pass", "warn", "fail"))
    earned = sum(WEIGHTS[c.severity] * STATUS_FACTOR[c.status] for c in checks if c.status in ("pass", "warn", "fail"))
    evaluated = sum(1 for c in checks if c.status in ("pass", "warn", "fail"))
    report = PostureReport(checks=checks, evaluated=evaluated)
    cats: dict[str, dict[str, int]] = {}
    for c in checks:
        d = cats.setdefault(c.category, dict.fromkeys(STATUSES, 0))
        d[c.status] += 1
    report.categories = cats
    if evaluated >= 5 and possible:
        report.score = round(100 * earned / possible)
        report.grade = _grade(report.score)
    return report
