"""Report data model and builder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from engine.analysis.analyst import AnalysisReport
from engine.verification.scoring import RELIABILITY_BASE, THRESHOLDS, classify
from shared.types import CorrelationResult, Finding, utcnow

METHODOLOGY = [
    "Base score = source reliability grade (A 0.90, B 0.80, C 0.65, D 0.50, E 0.30).",
    "Adjustments: similar match −0.30, inferred match −0.20, related object −0.05, inference-based evidence −0.15.",
    "Corroboration: +0.07 per independent source asserting the same claim (max +0.15).",
    "Contradiction: −0.25 when another source reports a conflicting value.",
    "Caps: person candidates found by name only ≤0.50; name collisions ≤0.40; handle variants ≤0.40; "
    "news phrase matches ≤0.35.",
    "Analyst decisions: verified → at least 0.95; rejected → 0.",
    "Levels: high ≥0.80, medium ≥0.60, low ≥0.40, very low <0.40.",
    "Confirmed = analyst-verified, or score ≥0.80 with direct evidence and an exact/related match and no "
    "dispute. Confirmed means the source-backed claim is established – not that a record belongs to a person.",
    "Entities are merged only on shared persistent identifiers; names and handles never merge entities.",
]

STATIC_LIMITATIONS = [
    "Coverage is limited to the sources listed under 'Sources consulted'. ATLAS does not search the entire internet.",
    "Absence of a result is not evidence of absence: sources may be unavailable, rate-limited or incomplete.",
    "Same names and same handles across sources do not establish that records concern the same person.",
    "Carrier data reflects the original number-range allocation; ported numbers are not detected.",
    "Data subject to a privacy opt-out, and categories prohibited by the ATLAS privacy policy, are withheld.",
    "Registration data may be redacted by registries in accordance with data-protection law.",
]


class ReportData(BaseModel):
    report_id: str
    generated_at: datetime = Field(default_factory=utcnow)
    generated_by: str
    investigation: dict[str, Any]
    findings: list[Finding]
    correlation: CorrelationResult
    coverage: dict[str, Any]
    analysis: AnalysisReport | None = None
    analyst_notes: list[dict[str, Any]] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=lambda: list(METHODOLOGY))
    limitations: list[str] = Field(default_factory=list)

    def bucket(self, name: str) -> list[Finding]:
        return [f for f in self.findings if classify(f) == name]

    @property
    def verified(self) -> list[Finding]:
        return self.bucket("confirmed")

    @property
    def possible(self) -> list[Finding]:
        return self.bucket("possible")

    @property
    def unverified(self) -> list[Finding]:
        return self.bucket("unverified")


def build_limitations(coverage: dict[str, Any]) -> list[str]:
    out = list(STATIC_LIMITATIONS)
    by_source = coverage.get("by_source", {})
    for status, label in (
        ("unavailable", "unavailable"),
        ("rate_limited", "rate-limited"),
        ("error", "failed"),
        ("not_configured", "not configured (missing credentials)"),
        ("skipped", "skipped (not authorised for this investigation's scope or consent)"),
    ):
        names = sorted(s for s, st in by_source.items() if st == status)
        if names:
            out.append(f"Sources {label}: {', '.join(names)}.")
    if coverage.get("sources_disabled"):
        out.append("Sources disabled by the administrator: " + ", ".join(coverage["sources_disabled"]) + ".")
    pol = coverage.get("policy") or {}
    removed = sum((pol.get("attributes_removed") or {}).values()) + sum((pol.get("redactions") or {}).values())
    if removed:
        out.append(f"{removed} data items were removed or redacted by the privacy policy (data minimisation).")
    if coverage.get("suppressed_items"):
        out.append(f"{coverage['suppressed_items']} items were withheld due to opt-out requests.")
    return out


__all__ = ["METHODOLOGY", "RELIABILITY_BASE", "THRESHOLDS", "ReportData", "build_limitations"]
