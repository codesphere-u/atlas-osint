"""Investigation lifecycle: authorisation checks, execution, persistence, verification, deletion."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from atlas_api.audit import audit
from atlas_api.db import get_sessionmaker
from atlas_api.models import AnalystNote, Case, FindingRow, Investigation, SourceConfig, Suppression, User
from atlas_api.schemas import InvestigationCreate, InvestigationOptions, LegalBasis, PivotRequest
from atlas_api.security import role_at_least
from engine.analysis.analyst import AnalysisReport, deterministic_analysis, run_analysis
from engine.assessment.posture import assess_posture
from engine.assessment.risk import risk_highlights
from engine.changes import diff as diff_findings
from engine.changes import snapshot as finding_snapshot
from engine.collectors.orchestrator import collect
from engine.correlation.resolver import identifier_key
from engine.normalization.identifiers import InvalidIdentifier, normalize, normalize_domain
from engine.pipeline import process, rescore
from engine.verification.scoring import classify
from integrations.providers.llm import ProviderError, build_provider
from integrations.sources.base import AuthorizationScope
from integrations.sources.registry import SourceRegistry, get_registry
from modules.registry import module_for
from shared.config import get_settings
from shared.crypto import keyed_hash
from shared.types import (
    INDIVIDUAL_IDENTIFIER_TYPES,
    CorrelationResult,
    Finding,
    Identifier,
    IdentifierType,
    SubjectKind,
    VerificationStatus,
    utcnow,
)

log = logging.getLogger("atlas.investigations")

# Test/extension hooks: lets integration tests inject a mocked HTTP client and DNS resolver.
collection_hooks: dict[str, Any] = {"http_factory": None, "extra": {}}

INDIVIDUAL_ALLOWED_BASES = {LegalBasis.CONSENT, LegalBasis.SELF}


def default_subject_kind(t: IdentifierType) -> SubjectKind:
    if t in INDIVIDUAL_IDENTIFIER_TYPES:
        return SubjectKind.INDIVIDUAL
    if t == IdentifierType.ORGANIZATION:
        return SubjectKind.ORGANIZATION
    if t in (IdentifierType.DOMAIN, IdentifierType.URL, IdentifierType.IP):
        return SubjectKind.INFRASTRUCTURE
    return SubjectKind.INDIVIDUAL  # documents: strictest default


def suppression_checker(db: Session) -> Callable[[str], bool]:
    hashes = set(db.scalars(select(Suppression.identifier_hash)).all())
    return lambda key: bool(hashes) and keyed_hash(key) in hashes


def validate_authorization(payload: InvestigationCreate, subject_kind: SubjectKind) -> list[str]:
    """Return a list of authorisation problems (empty = acceptable)."""
    settings = get_settings()
    problems = []
    if not payload.attestation:
        problems.append("You must attest that this investigation is lawful, proportionate and authorised.")
    if subject_kind == SubjectKind.INDIVIDUAL and settings.require_consent_for_individuals:
        if payload.legal_basis not in INDIVIDUAL_ALLOWED_BASES:
            problems.append("Profiling an individual requires legal basis 'consent' or 'self'.")
        if payload.legal_basis == LegalBasis.CONSENT and not (payload.consent_obtained and payload.consent_reference):
            problems.append("Record that consent was obtained and provide a consent reference.")
    if payload.legal_basis == LegalBasis.AUTHORIZED_SECURITY_ASSESSMENT and not payload.authorization_reference:
        problems.append("Authorised security assessments require an authorisation reference (e.g. engagement ID).")
    if payload.legal_basis == LegalBasis.LEGITIMATE_INTEREST and len(payload.purpose) < 30:
        problems.append("Describe the legitimate interest in the purpose field (at least 30 characters).")
    return problems


def create_investigation(
    db: Session, payload: InvestigationCreate, user: User, ip: str | None, *, parent: Investigation | None = None
) -> Investigation:
    settings = get_settings()
    try:
        subject = normalize(payload.subject_type, payload.subject, default_region=payload.default_region)
    except InvalidIdentifier as exc:
        raise HTTPException(status_code=422, detail=f"invalid {payload.subject_type.value}: {exc}") from exc
    kind = payload.subject_kind or default_subject_kind(subject.type)
    if (
        subject.type in (IdentifierType.NAME, IdentifierType.USERNAME, IdentifierType.PHONE, IdentifierType.EMAIL)
        and kind != SubjectKind.INDIVIDUAL
        and payload.subject_kind is not None
    ):
        # Declaring e.g. a business phone line is allowed but recorded; it relaxes consent rules only for
        # identifiers that genuinely belong to an organisation, so require a reference for accountability.
        if not payload.authorization_reference:
            raise HTTPException(
                status_code=422,
                detail="Declaring a personal-type identifier as organisational requires an authorisation reference.",
            )
    problems = validate_authorization(payload, kind)
    if problems:
        audit(
            db,
            actor_id=user.id,
            action="investigation.create",
            outcome="denied",
            ip=ip,
            details={"reasons": problems, "subject_type": subject.type.value},
        )
        raise HTTPException(status_code=422, detail={"authorization": problems})
    subject_hash = keyed_hash(identifier_key(subject))
    if db.scalar(select(Suppression).where(Suppression.identifier_hash == subject_hash)):
        audit(
            db,
            actor_id=user.id,
            action="investigation.create",
            outcome="denied",
            ip=ip,
            details={"reason": "subject_opted_out", "subject_hash": subject_hash},
        )
        raise HTTPException(
            status_code=451, detail="This identifier is subject to an opt-out request and cannot be investigated."
        )
    domains = []
    for d in payload.authorized_domains:
        try:
            domains.append(normalize_domain(d))
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=f"invalid authorised domain '{d}': {exc}") from exc
    retention = min(payload.retention_days or settings.default_retention_days, settings.max_retention_days)
    reg = get_registry()
    if payload.options.sources:
        unknown = [s for s in payload.options.sources if reg.get(s) is None]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown sources: {', '.join(unknown)}")
    inv = Investigation(
        title=payload.title,
        subject_type=subject.type.value,
        subject_hash=subject_hash,
        subject_kind=kind.value,
        status="queued" if payload.run else "draft",
        options=payload.options.model_dump(),
        purpose=payload.purpose,
        legal_basis=payload.legal_basis.value,
        authorization_reference=payload.authorization_reference,
        consent_obtained=payload.consent_obtained,
        consent_reference=payload.consent_reference,
        authorized_domains=domains,
        attestation=payload.attestation,
        created_by=user.id,
        retention_until=utcnow() + timedelta(days=retention),
        progress={},
        tlp=payload.tlp,
        case_id=_checked_case_id(db, payload.case_id, user),
        parent_id=parent.id if parent else None,
    )
    inv.set_subject(subject.value)
    db.add(inv)
    db.commit()
    audit(
        db,
        actor_id=user.id,
        action="investigation.create",
        target_type="investigation",
        target_id=inv.id,
        ip=ip,
        details={
            "subject_type": subject.type.value,
            "subject_hash": subject_hash,
            "legal_basis": inv.legal_basis,
            "subject_kind": kind.value,
            "retention_days": retention,
        },
    )
    return inv


def _checked_case_id(db: Session, case_id: str | None, user: User) -> str | None:
    if not case_id:
        return None
    case = db.get(Case, case_id)
    if case is None or (case.created_by != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="case not found")
    return case.id


def pivot_investigation(
    db: Session, parent: Investigation, body: PivotRequest, user: User, ip: str | None
) -> Investigation:
    """Create a child investigation for an identifier discovered in ``parent``, inheriting its authorisation."""
    if not body.covered_by_authorization:
        raise HTTPException(
            status_code=422,
            detail={
                "authorization": [
                    "Confirm that the pivot target is the same subject or is covered by the existing authorisation."
                ]
            },
        )
    if parent.case_id is None:
        case = Case(title=parent.title[:200], created_by=parent.created_by, tlp=parent.tlp)
        db.add(case)
        db.flush()
        parent.case_id = case.id
        db.commit()
    remaining = max(1, (_aware(parent.retention_until) - utcnow()).days)
    payload = InvestigationCreate(
        title=(body.title or f"{parent.title} → {body.subject_type.value}: {body.subject}")[:200],
        subject_type=body.subject_type,
        subject=body.subject,
        subject_kind=body.subject_kind,
        purpose=f"Pivot from investigation {parent.id[:8]} ({parent.title}): {parent.purpose}"[:2000],
        legal_basis=LegalBasis(parent.legal_basis),
        authorization_reference=parent.authorization_reference,
        consent_obtained=parent.consent_obtained,
        consent_reference=body.consent_reference or parent.consent_reference,
        authorized_domains=list(parent.authorized_domains or []),
        attestation=True,
        retention_days=remaining,
        options=InvestigationOptions(
            **{k: v for k, v in (parent.options or {}).items() if k in InvestigationOptions.model_fields}
        ),
        tlp=parent.tlp,  # type: ignore[arg-type]
        case_id=parent.case_id,
        run=body.run,
    )
    child = create_investigation(db, payload, user, ip, parent=parent)
    audit(
        db,
        actor_id=user.id,
        action="investigation.pivot",
        target_type="investigation",
        target_id=child.id,
        ip=ip,
        details={"parent_id": parent.id, "subject_type": body.subject_type.value},
    )
    return child


MONITORABLE_KINDS = {SubjectKind.ORGANIZATION.value, SubjectKind.INFRASTRUCTURE.value}


def set_monitoring(
    db: Session, inv: Investigation, interval_hours: int | None, actor_id: str, ip: str | None
) -> Investigation:
    """Scheduled re-collection. Not available for individuals: continuous monitoring of a person is surveillance."""
    if interval_hours is not None and inv.subject_kind not in MONITORABLE_KINDS:
        raise HTTPException(
            status_code=422,
            detail="Monitoring is only available for organisations and "
            "infrastructure. Continuous monitoring of individuals is not "
            "supported.",
        )
    inv.monitor_interval_hours = interval_hours
    inv.next_run_at = utcnow() + timedelta(hours=interval_hours) if interval_hours else None
    db.commit()
    audit(
        db,
        actor_id=actor_id,
        action="investigation.monitoring",
        target_type="investigation",
        target_id=inv.id,
        ip=ip,
        details={"interval_hours": interval_hours},
    )
    return inv


def run_due_monitors(db: Session, dispatch: Callable[[str], None] | None = None) -> list[str]:
    """Queue monitored investigations whose next run is due (called by Celery beat or the inline scheduler)."""
    now = utcnow()
    due = db.scalars(
        select(Investigation).where(
            Investigation.monitor_interval_hours.is_not(None),
            Investigation.next_run_at.is_not(None),
            Investigation.next_run_at <= now,
            Investigation.status.in_(("completed", "failed")),
            Investigation.retention_until > now,
        )
    ).all()
    ids = []
    for inv in due:
        inv.status = "queued"
        inv.options = {**(inv.options or {}), "_trigger": "monitor"}
        inv.next_run_at = now + timedelta(hours=inv.monitor_interval_hours or 24)
        ids.append(inv.id)
    db.commit()
    for inv_id in ids:
        (dispatch or execute_investigation)(inv_id)
    return ids


def _aware(dt):  # type: ignore[no-untyped-def]
    from datetime import UTC

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def enabled_sources_for(
    db: Session, user_role: str, registry: SourceRegistry, restrict: list[str] | None = None
) -> set[str]:
    configs = {c.source_name: c for c in db.scalars(select(SourceConfig)).all()}
    out = set()
    for a in registry.all():
        cfg = configs.get(a.meta.name)
        enabled = cfg.enabled if cfg else a.meta.default_enabled
        min_role = cfg.min_role if cfg else "analyst"
        if enabled and role_at_least(user_role, min_role):
            out.add(a.meta.name)
    if restrict:
        out &= set(restrict)
    return out


def load_findings(inv: Investigation) -> list[Finding]:
    return [Finding.model_validate(row.data) for row in inv.findings]


def subject_of(inv: Investigation) -> Identifier:
    return Identifier(type=IdentifierType(inv.subject_type), value=inv.subject_value)


def _store_findings(db: Session, inv: Investigation, findings: list[Finding]) -> None:
    db.execute(delete(FindingRow).where(FindingRow.investigation_id == inv.id))
    for f in findings:
        row = FindingRow(
            id=f.id,
            investigation_id=inv.id,
            module=f.module,
            source_name=f.source_name,
            finding_type=f.finding_type,
            classification=classify(f),
            score=f.confidence.score if f.confidence else 0.0,
            level=f.confidence.level.value if f.confidence else "very_low",
            verification_status=f.verification_status.value,
            claim_key=(f.claim_key or "")[:500] or None,
            collected_at=f.collected_at,
            published_at=f.published_at,
        )
        row.set_data(f.model_dump(mode="json"))
        db.add(row)
    inv.finding_count = len(findings)
    inv.confirmed_count = sum(1 for f in findings if classify(f) == "confirmed")


POSTURE_TYPES = {IdentifierType.DOMAIN, IdentifierType.URL, IdentifierType.IP}
MAX_RUN_HISTORY = 30


def compute_assessments(subject: Identifier, findings: list[Finding]) -> dict[str, Any]:
    """Exposure scorecard (infrastructure subjects) and risk highlights."""
    posture = assess_posture(findings) if subject.type in POSTURE_TYPES else None
    highlights = risk_highlights(findings, posture)
    return {
        "posture": posture.model_dump(mode="json") if posture and posture.checks else None,
        "risk": [h.model_dump(mode="json") for h in highlights],
    }


def _risk_level(risk: list[dict[str, Any]]) -> str:
    for level in ("critical", "high", "medium", "low"):
        if any(h["severity"] == level for h in risk):
            return level
    return "none"


def execute_investigation(investigation_id: str) -> None:
    """Run collection + processing for an investigation (called inline or by a Celery worker)."""
    settings = get_settings()
    db = get_sessionmaker()()
    try:
        inv = db.get(Investigation, investigation_id)
        if inv is None or inv.status not in ("queued", "draft", "failed", "completed"):
            return
        creator = db.get(User, inv.created_by)
        registry = get_registry()
        subject = subject_of(inv)
        module = module_for(subject.type)
        enabled = enabled_sources_for(db, creator.role if creator else "viewer", registry, inv.options.get("sources"))
        prior = {
            f"{r.source_name}|{r.claim_key}": VerificationStatus(r.verification_status)
            for r in inv.findings
            if r.verification_status in ("verified", "rejected")
        }
        scope = AuthorizationScope(
            subject_kind=SubjectKind(inv.subject_kind),
            consent_obtained=inv.consent_obtained,
            legal_basis=inv.legal_basis,
            authorized_domains=inv.authorized_domains or [],
        )
        inv.status, inv.started_at, inv.error = "running", utcnow(), None
        inv.progress = {"done": 0, "total": 0, "sources": {}}
        db.commit()

        def on_progress(run, done, total):  # type: ignore[no-untyped-def]
            prog = dict(inv.progress or {})
            sources = dict(prog.get("sources") or {})
            sources[run.source_name] = run.status.value
            inv.progress = {"done": done, "total": total, "sources": sources}
            db.commit()

        http = collection_hooks["http_factory"]() if collection_hooks.get("http_factory") else None
        outcome = asyncio.run(
            collect(
                subject=subject,
                module=module,
                registry=registry,
                enabled_sources=enabled,
                scope=scope,
                settings=settings,
                options=inv.options,
                http=http,
                progress=on_progress,
                extra=dict(collection_hooks.get("extra") or {}),
                investigation_id=inv.id,
            )
        )
        processed = process(
            subject=subject,
            subject_kind=SubjectKind(inv.subject_kind),
            module=module,
            outcome=outcome,
            registry=registry,
            enabled=enabled,
            is_suppressed=suppression_checker(db),
            prior_status=prior,
        )
        provider = None
        notes: list[str] = []
        if inv.options.get("ai_analysis"):
            try:
                provider = build_provider(settings)
                if provider is None:
                    notes.append("AI analysis requested but no AI provider is configured (ATLAS_AI_PROVIDER).")
            except ProviderError as exc:
                notes.append(f"AI provider unavailable: {exc}")
        analysis = asyncio.run(
            run_analysis(
                subject,
                processed.findings,
                processed.correlation,
                provider=provider,
                coverage=processed.coverage,
                max_findings=settings.ai_max_findings,
            )
        )
        analysis.validation_notes = notes + analysis.validation_notes
        previous = inv.results
        prev_finished = previous.get("finished_at")
        assessments = compute_assessments(subject, processed.findings)
        changes = diff_findings(previous.get("snapshot"), processed.findings, prev_finished)
        finished = utcnow()
        history = list(previous.get("run_history") or [])[-(MAX_RUN_HISTORY - 1) :]
        history.append(
            {
                "at": finished.isoformat(),
                "findings": len(processed.findings),
                "confirmed": sum(1 for f in processed.findings if classify(f) == "confirmed"),
                "added": changes["added_count"],
                "removed": changes["removed_count"],
                "grade": (assessments["posture"] or {}).get("grade"),
                "trigger": "monitor" if inv.options.get("_trigger") == "monitor" else "manual",
            }
        )
        _store_findings(db, inv, processed.findings)
        inv.set_results(
            {
                "correlation": processed.correlation.model_dump(mode="json"),
                "coverage": processed.coverage,
                "module_summary": processed.module_summary,
                "analysis": analysis.model_dump(mode="json"),
                **assessments,
                "changes": changes,
                "snapshot": finding_snapshot(processed.findings),
                "run_history": history,
                "finished_at": finished.isoformat(),
            }
        )
        inv.risk_level = _risk_level(assessments["risk"])
        inv.posture_grade = (assessments["posture"] or {}).get("grade")
        inv.run_count = (inv.run_count or 0) + 1
        inv.options = {k: v for k, v in (inv.options or {}).items() if k != "_trigger"}
        if inv.monitor_interval_hours:
            inv.next_run_at = finished + timedelta(hours=inv.monitor_interval_hours)
        inv.status, inv.finished_at = "completed", finished
        db.commit()
        audit(
            db,
            actor_id=inv.created_by,
            action="investigation.completed",
            target_type="investigation",
            target_id=inv.id,
            details={"findings": len(processed.findings), "sources": processed.coverage.get("sources_consulted")},
        )
    except Exception as exc:
        log.exception("investigation %s failed", investigation_id)
        db.rollback()
        inv = db.get(Investigation, investigation_id)
        if inv:
            inv.status, inv.error, inv.finished_at = "failed", f"{type(exc).__name__}: {str(exc)[:500]}", utcnow()
            db.commit()
    finally:
        db.close()


def recompute(db: Session, inv: Investigation) -> None:
    """Re-score and re-correlate after analyst decisions; regenerate the deterministic analysis."""
    findings = load_findings(inv)
    subject = subject_of(inv)
    correlation = rescore(findings, subject)
    results = inv.results
    coverage = results.get("coverage", {})
    from collections import Counter

    coverage["classification_counts"] = dict(Counter(classify(f) for f in findings))
    analysis = deterministic_analysis(subject, findings, correlation, coverage)
    prev = results.get("analysis") or {}
    if prev.get("ai_generated"):
        analysis.validation_notes.append("AI narrative removed after analyst changes; regenerate analysis to refresh.")
    _store_findings(db, inv, findings)
    assessments = compute_assessments(subject, findings)
    results.update(
        {
            "correlation": correlation.model_dump(mode="json"),
            "coverage": coverage,
            "analysis": analysis.model_dump(mode="json"),
            **assessments,
        }
    )
    inv.set_results(results)
    inv.risk_level = _risk_level(assessments["risk"])
    inv.posture_grade = (assessments["posture"] or {}).get("grade")
    db.commit()


def regenerate_analysis(db: Session, inv: Investigation, use_ai: bool) -> AnalysisReport:
    settings = get_settings()
    findings = load_findings(inv)
    subject = subject_of(inv)
    results = inv.results
    correlation = CorrelationResult.model_validate(results.get("correlation") or {})
    provider = None
    notes = []
    if use_ai:
        try:
            provider = build_provider(settings)
            if provider is None:
                notes.append("No AI provider configured (ATLAS_AI_PROVIDER=none); deterministic analysis only.")
        except ProviderError as exc:
            notes.append(f"AI provider unavailable: {exc}")
    analysis = asyncio.run(
        run_analysis(
            subject,
            findings,
            correlation,
            provider=provider,
            coverage=results.get("coverage"),
            max_findings=settings.ai_max_findings,
        )
    )
    analysis.validation_notes = notes + analysis.validation_notes
    results["analysis"] = analysis.model_dump(mode="json")
    inv.set_results(results)
    db.commit()
    return analysis


def delete_investigation(db: Session, inv: Investigation, actor_id: str, ip: str | None, reason: str) -> None:
    inv_id = inv.id
    db.execute(delete(AnalystNote).where(AnalystNote.investigation_id == inv_id))
    db.execute(delete(FindingRow).where(FindingRow.investigation_id == inv_id))
    db.delete(inv)
    db.commit()
    audit(
        db,
        actor_id=actor_id,
        action="investigation.delete",
        target_type="investigation",
        target_id=inv_id,
        ip=ip,
        details={"reason": reason},
    )


def purge_expired(db: Session) -> int:
    now = utcnow()
    expired = db.scalars(select(Investigation).where(Investigation.retention_until < now)).all()
    for inv in expired:
        delete_investigation(db, inv, actor_id=None, ip=None, reason="retention_expired")  # type: ignore[arg-type]
    if expired:
        log.info("retention purge removed %d investigations", len(expired))
    return len(expired)
