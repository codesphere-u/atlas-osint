"""Explainable confidence scoring.

Confidence is computed by a fixed, documented set of additive rules and caps.
Every applied rule is recorded on the finding as a :class:`ConfidenceReason`,
so an analyst (or a report reader) can see exactly why a score was assigned.
No machine-learned or opaque weighting is used. See
``docs/confidence-methodology.md``.
"""

from __future__ import annotations

from collections import defaultdict

from shared.types import (
    Confidence,
    ConfidenceLevel,
    ConfidenceReason,
    CorrelationResult,
    EvidenceKind,
    Finding,
    IdentifierType,
    MatchType,
    Reliability,
    VerificationStatus,
)

RELIABILITY_BASE = {
    Reliability.A: 0.90,
    Reliability.B: 0.80,
    Reliability.C: 0.65,
    Reliability.D: 0.50,
    Reliability.E: 0.30,
}
MATCH_DELTA = {
    MatchType.EXACT: 0.0,
    MatchType.RELATED: -0.05,
    MatchType.INFERRED: -0.20,
    MatchType.SIMILAR: -0.30,
}
INFERENCE_DELTA = -0.15
CORROBORATION_STEP = 0.07
CORROBORATION_MAX = 0.15
CONTRADICTION_DELTA = -0.25
NAME_ONLY_CAP = 0.50
NEWS_MENTION_CAP = 0.35
VARIANT_CAP = 0.40
ANALYST_VERIFIED_FLOOR = 0.95

THRESHOLDS = ((0.80, ConfidenceLevel.HIGH), (0.60, ConfidenceLevel.MEDIUM), (0.40, ConfidenceLevel.LOW))


def level_for(score: float) -> ConfidenceLevel:
    for threshold, level in THRESHOLDS:
        if score >= threshold:
            return level
    return ConfidenceLevel.VERY_LOW


def score_findings(findings: list[Finding], correlation: CorrelationResult | None = None) -> list[Finding]:
    """Score all findings in place and update automatic verification status."""
    sources_by_claim: dict[str, set[str]] = defaultdict(set)
    for f in findings:
        if f.claim_key and f.verification_status != VerificationStatus.REJECTED:
            sources_by_claim[f.claim_key].add(f.source_name)
    contradicted: set[str] = set()
    if correlation:
        for c in correlation.contradictions:
            for ids in c.values.values():
                contradicted.update(ids)

    for f in findings:
        reasons: list[ConfidenceReason] = []
        score = RELIABILITY_BASE[f.reliability]
        reasons.append(
            ConfidenceReason(
                rule="source_reliability", delta=score, explanation=f"Source reliability grade {f.reliability.value}"
            )
        )
        d = MATCH_DELTA[f.match_type]
        if d:
            score += d
            reasons.append(
                ConfidenceReason(
                    rule=f"match_{f.match_type.value}",
                    delta=d,
                    explanation=f"Match type is '{f.match_type.value}', not exact",
                )
            )
        if f.evidence_kind == EvidenceKind.INFERENCE:
            score += INFERENCE_DELTA
            reasons.append(
                ConfidenceReason(
                    rule="inference",
                    delta=INFERENCE_DELTA,
                    explanation="Derived by inference rather than stated by the source",
                )
            )
        independent = len(sources_by_claim.get(f.claim_key or "", set()) - {f.source_name})
        if independent:
            bonus = min(CORROBORATION_MAX, CORROBORATION_STEP * independent)
            score += bonus
            reasons.append(
                ConfidenceReason(
                    rule="corroboration",
                    delta=bonus,
                    explanation=f"Corroborated by {independent} independent source(s)",
                )
            )
        if f.id in contradicted:
            score += CONTRADICTION_DELTA
            reasons.append(
                ConfidenceReason(
                    rule="contradiction",
                    delta=CONTRADICTION_DELTA,
                    explanation="Another source reports a conflicting value",
                )
            )
        caps: list[tuple[float, str, str]] = []
        if f.entity_kind == "person" and f.subject.type == IdentifierType.NAME:
            caps.append(
                (
                    NAME_ONLY_CAP,
                    "name_only_cap",
                    "Candidate found by name search only; a name does not establish identity",
                )
            )
        if f.finding_type == "news_mention":
            caps.append(
                (
                    NEWS_MENTION_CAP,
                    "news_mention_cap",
                    "Phrase match in news coverage does not establish that it concerns the subject",
                )
            )
        if "variant_query" in f.flags:
            caps.append((VARIANT_CAP, "variant_cap", "Found via a handle variant, not the queried handle"))
        if "name_collision" in f.flags:
            caps.append((NAME_ONLY_CAP - 0.1, "name_collision_cap", "Several distinct candidates share this name"))
        for cap, rule, why in caps:
            if score > cap:
                reasons.append(ConfidenceReason(rule=rule, delta=round(cap - score, 4), explanation=why))
                score = cap
        if f.verification_status == VerificationStatus.VERIFIED:
            if score < ANALYST_VERIFIED_FLOOR:
                reasons.append(
                    ConfidenceReason(
                        rule="analyst_verified",
                        delta=round(ANALYST_VERIFIED_FLOOR - score, 4),
                        explanation="Verified by an analyst",
                    )
                )
                score = ANALYST_VERIFIED_FLOOR
        elif f.verification_status == VerificationStatus.REJECTED:
            reasons.append(
                ConfidenceReason(rule="analyst_rejected", delta=-score, explanation="Rejected by an analyst")
            )
            score = 0.0
        else:
            if f.id in contradicted:
                f.verification_status = VerificationStatus.DISPUTED
            elif independent >= 1:
                f.verification_status = VerificationStatus.CORROBORATED
            else:
                f.verification_status = VerificationStatus.UNVERIFIED
        if score > 1.0:
            reasons.append(
                ConfidenceReason(
                    rule="upper_bound", delta=round(1.0 - score, 4), explanation="Scores are bounded at 1.0"
                )
            )
            score = 1.0
        score = round(max(0.0, score), 4)
        f.confidence = Confidence(score=score, level=level_for(score), reasons=reasons)
    return findings


def classify(f: Finding) -> str:
    """Report bucket: confirmed | possible | unverified | rejected.

    "Confirmed" means the source-backed *claim* is established (e.g. "an account
    with this handle exists on GitHub"). It never, by itself, establishes that
    an account or record belongs to a particular person.
    """
    if f.verification_status == VerificationStatus.REJECTED:
        return "rejected"
    if f.verification_status == VerificationStatus.VERIFIED:
        return "confirmed"
    score = f.confidence.score if f.confidence else 0.0
    if (
        score >= 0.80
        and f.evidence_kind == EvidenceKind.DIRECT
        and f.match_type in (MatchType.EXACT, MatchType.RELATED)
        and f.verification_status != VerificationStatus.DISPUTED
    ):
        return "confirmed"
    if score >= 0.40:
        return "possible"
    return "unverified"
