"""Risk highlights: the handful of things an analyst should look at first.

Derived deterministically from finding flags, finding types and failed high-severity posture checks.
Each highlight names its supporting findings and whether they are confirmed or still unconfirmed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from engine.assessment.posture import PostureReport
from engine.verification.scoring import classify
from shared.types import Finding

Severity = Literal["critical", "high", "medium", "low"]
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

FLAG_RULES: dict[str, tuple[Severity, str, str]] = {
    "risk:sanction": ("critical", "Possible sanctions-list match", "screening"),
    "risk:debarment": ("high", "Possible debarment / exclusion-list match", "screening"),
    "risk:crime": ("high", "Possible match on a crime-related list", "screening"),
    "risk:pep": ("medium", "Possible politically exposed person (PEP) match", "screening"),
    "risk:regulatory": ("medium", "Possible regulatory enforcement or warning", "screening"),
    "risk:person_of_interest": ("medium", "Possible person-of-interest listing", "screening"),
    "risk:exposed_service": ("high", "Sensitive service exposed to the Internet", "exposure"),
    "risk:potential_vulnerabilities": ("medium", "Software versions associated with known CVEs", "exposure"),
    "risk:lookalike_mail": ("medium", "Mail-capable lookalike domains registered", "brand"),
}


class Highlight(BaseModel):
    severity: Severity
    title: str
    detail: str
    category: str
    finding_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False


def risk_highlights(findings: list[Finding], posture: PostureReport | None = None) -> list[Highlight]:
    usable = [f for f in findings if classify(f) != "rejected"]
    grouped: dict[str, list[Finding]] = {}
    for f in usable:
        for flag in f.flags:
            if flag in FLAG_RULES:
                grouped.setdefault(flag, []).append(f)
    out: list[Highlight] = []
    for flag, fs in grouped.items():
        sev, title, cat = FLAG_RULES[flag]
        names = "; ".join(f.title for f in fs[:3]) + (f" (+{len(fs) - 3} more)" if len(fs) > 3 else "")
        out.append(
            Highlight(
                severity=sev,
                title=title + (f" ({len(fs)})" if len(fs) > 1 else ""),
                detail=names,
                category=cat,
                finding_ids=[f.id for f in fs],
                confirmed=all(classify(f) == "confirmed" for f in fs),
            )
        )
    breaches = [f for f in usable if f.finding_type == "breach_notification"]
    if breaches:
        out.append(
            Highlight(
                severity="medium",
                title=f"Address appears in {len(breaches)} disclosed breach(es)",
                detail=", ".join(str(f.attributes.get("breach_name")) for f in breaches[:5]),
                category="breach",
                finding_ids=[f.id for f in breaches],
                confirmed=all(classify(f) == "confirmed" for f in breaches),
            )
        )
    inactive = [
        f
        for f in usable
        if f.entity_kind == "organization"
        and classify(f) in ("confirmed", "possible")
        and str(f.attributes.get("status") or "").lower()
        in ("inactive", "dissolved", "liquidation", "closed", "converted-closed")
    ]
    if inactive:
        out.append(
            Highlight(
                severity="medium",
                title="Registry reports an inactive or dissolved entity",
                detail="; ".join(f.title for f in inactive[:3]),
                category="registry",
                finding_ids=[f.id for f in inactive],
                confirmed=all(classify(f) == "confirmed" for f in inactive),
            )
        )
    if posture:
        for c in posture.checks:
            if c.status == "fail" and c.severity == "high" and not c.id.startswith("EXPOSURE"):
                out.append(
                    Highlight(
                        severity="high",
                        title=c.title + " – failed",
                        detail=c.detail,
                        category="posture",
                        finding_ids=c.finding_ids,
                        confirmed=True,
                    )
                )
    return sorted(out, key=lambda h: (SEVERITY_ORDER[h.severity], h.title))
