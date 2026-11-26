"""End-to-end processing pipeline (pure, I/O-free apart from optional AI calls).

collect → privacy policy → suppression (opt-outs) → module post-processing →
dedupe → correlation → confidence scoring → entity confidence → coverage →
analysis.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from engine.collectors.orchestrator import CollectionOutcome, SourceRun
from engine.correlation.resolver import dedupe, finalize_entity_confidence, identifier_key, resolve
from engine.verification.scoring import classify, score_findings
from integrations.sources.registry import SourceRegistry
from modules.base import IntelligenceModule
from shared.policy import PolicyReport, apply_privacy_policy
from shared.types import (
    AdapterStatus,
    CorrelationResult,
    Finding,
    Identifier,
    IdentifierType,
    SubjectKind,
    VerificationStatus,
)


def suppression_keys(identifier: Identifier) -> list[str]:
    """All keys under which an identifier can be subject to an opt-out (URLs also match their host domain)."""
    keys = [identifier_key(identifier)]
    if identifier.type in (IdentifierType.URL, IdentifierType.DOCUMENT):
        host = (urlsplit(identifier.value).hostname or "").removeprefix("www.")
        if host:
            keys.append(f"domain:{host}")
    return keys


@dataclass
class ProcessedInvestigation:
    findings: list[Finding]
    correlation: CorrelationResult
    coverage: dict[str, Any]
    policy: PolicyReport
    module_summary: dict[str, Any]
    suppressed: int = 0
    duplicates_collapsed: int = 0
    notes: list[str] = field(default_factory=list)


def build_coverage(
    runs: list[SourceRun], registry: SourceRegistry, enabled: set[str], identifier_type: str
) -> dict[str, Any]:
    by_source: dict[str, str] = {}
    sources = []
    for r in runs:
        adapter = registry.get(r.source_name)
        prev = by_source.get(r.source_name)
        # Report the most informative status when a source ran on several identifiers.
        rank = [
            AdapterStatus.OK,
            AdapterStatus.NO_RESULTS,
            AdapterStatus.RATE_LIMITED,
            AdapterStatus.UNAVAILABLE,
            AdapterStatus.ERROR,
            AdapterStatus.NOT_CONFIGURED,
            AdapterStatus.SKIPPED,
        ]
        if prev is None or rank.index(r.status) < rank.index(AdapterStatus(prev)):
            by_source[r.source_name] = r.status.value
        sources.append(
            {
                "source": r.source_name,
                "display_name": adapter.meta.display_name if adapter else r.source_name,
                "category": adapter.meta.category.value if adapter else None,
                "reliability": adapter.meta.reliability.value if adapter else None,
                "license": adapter.meta.legal.license if adapter else None,
                "identifier": r.identifier,
                "reason": r.reason,
                "status": r.status.value,
                "message": r.message,
                "findings": r.finding_count,
                "duration_ms": r.duration_ms,
                "http_status": r.http_status,
            }
        )
    all_applicable = {a.meta.name for a in registry.all() if identifier_type in [t.value for t in a.meta.input_types]}
    disabled = sorted(all_applicable - enabled)
    counts = Counter(by_source.values())
    queried = sum(1 for s in by_source.values() if s in ("ok", "no_results"))
    return {
        "by_source": by_source,
        "runs": sources,
        "status_counts": dict(counts),
        "sources_consulted": len(by_source),
        "sources_answered": queried,
        "sources_disabled": disabled,
        "coverage_ratio": round(queried / len(by_source), 3) if by_source else 0.0,
    }


def process(
    *,
    subject: Identifier,
    subject_kind: SubjectKind,
    module: IntelligenceModule,
    outcome: CollectionOutcome,
    registry: SourceRegistry,
    enabled: set[str],
    is_suppressed: Callable[[str], bool] | None = None,
    prior_status: dict[str, VerificationStatus] | None = None,
) -> ProcessedInvestigation:
    findings, policy = apply_privacy_policy(outcome.findings, subject_kind, keep_values={subject.value})
    suppressed = 0
    if is_suppressed is not None:
        kept: list[Finding] = []
        for f in findings:
            if f.entity_hint and is_suppressed(f.entity_hint):
                suppressed += 1
                continue
            before = len(f.linked)
            f.linked = [li for li in f.linked if not any(is_suppressed(k) for k in suppression_keys(li.identifier))]
            if len(f.linked) != before:
                f.flags.append("linked_identifier_suppressed")
                suppressed += before - len(f.linked)
            kept.append(f)
        findings = kept
    findings = module.postprocess(findings, subject)
    findings, collapsed = dedupe(findings)
    if prior_status:
        for f in findings:
            key = f"{f.source_name}|{f.claim_key}"
            if key in prior_status:
                f.verification_status = prior_status[key]
    correlation = resolve(findings, subject)
    correlation.duplicates_collapsed = collapsed
    score_findings(findings, correlation)
    finalize_entity_confidence(correlation, findings)
    coverage = build_coverage(outcome.runs, registry, enabled, subject.type.value)
    coverage["policy"] = policy.as_dict()
    coverage["suppressed_items"] = suppressed
    coverage["classification_counts"] = dict(Counter(classify(f) for f in findings))
    return ProcessedInvestigation(
        findings=findings,
        correlation=correlation,
        coverage=coverage,
        policy=policy,
        module_summary=module.summarize(findings, subject),
        suppressed=suppressed,
        duplicates_collapsed=collapsed,
    )


def rescore(findings: list[Finding], subject: Identifier) -> CorrelationResult:
    """Recompute correlation and scores after analyst verification decisions."""
    correlation = resolve(findings, subject)
    score_findings(findings, correlation)
    finalize_entity_confidence(correlation, findings)
    return correlation
