from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from atlas_api.audit import audit
from atlas_api.db import get_db
from atlas_api.deps import Principal, client_ip, require
from atlas_api.models import AnalystNote, Case, FindingRow, Investigation, User
from atlas_api.schemas import (
    BulkVerify,
    FindingVerify,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationOut,
    InvestigationUpdate,
    MonitoringUpdate,
    NoteCreate,
    PivotRequest,
)
from atlas_api.security import Permission
from atlas_api.services import investigations as svc
from atlas_api.tasks import dispatch_investigation
from engine.analysis.analyst import AnalysisReport
from engine.correlation.resolver import identifier_key
from engine.normalization.identifiers import try_normalize
from engine.reporting.model import ReportData, build_limitations
from engine.reporting.renderers import RENDERERS
from engine.reporting.stix import build_stix_bundle, render_stix
from shared.crypto import encrypt_str, keyed_hash
from shared.types import CorrelationResult, Finding, IdentifierType, VerificationStatus, new_id, utcnow

router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])


def to_out(inv: Investigation) -> InvestigationOut:
    return InvestigationOut(
        id=inv.id,
        title=inv.title,
        subject_type=inv.subject_type,
        subject=inv.subject_value,
        subject_kind=inv.subject_kind,
        status=inv.status,
        purpose=inv.purpose,
        legal_basis=inv.legal_basis,
        authorization_reference=inv.authorization_reference,
        consent_obtained=inv.consent_obtained,
        consent_reference=inv.consent_reference,
        authorized_domains=inv.authorized_domains or [],
        options=inv.options or {},
        created_by=inv.created_by,
        created_at=inv.created_at,
        started_at=inv.started_at,
        finished_at=inv.finished_at,
        retention_until=inv.retention_until,
        error=inv.error,
        progress=inv.progress or {},
        finding_count=inv.finding_count,
        confirmed_count=inv.confirmed_count,
        tlp=inv.tlp or "amber",
        case_id=inv.case_id,
        parent_id=inv.parent_id,
        monitor_interval_hours=inv.monitor_interval_hours,
        next_run_at=inv.next_run_at,
        run_count=inv.run_count or 0,
        risk_level=inv.risk_level,
        posture_grade=inv.posture_grade,
    )


def get_inv(db: Session, principal: Principal, inv_id: str, write: bool = False) -> Investigation:
    inv = db.get(Investigation, inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    owner = inv.created_by == principal.id
    if write:
        if not (owner or principal.role == "admin"):
            raise HTTPException(status_code=403, detail="only the owner or an administrator may modify this")
    elif not (owner or principal.can(Permission.INVESTIGATION_READ_ALL)):
        raise HTTPException(status_code=404, detail="investigation not found")
    return inv


@router.post("", response_model=InvestigationOut, status_code=201)
def create(
    body: InvestigationCreate,
    request: Request,
    background: BackgroundTasks,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    inv = svc.create_investigation(db, body, principal.user, client_ip(request))
    if body.run:
        dispatch_investigation(inv.id, background)
    return to_out(inv)


@router.get("", response_model=list[InvestigationOut])
def list_investigations(
    response: Response,
    status: str | None = Query(default=None, max_length=20),
    subject_type: IdentifierType | None = None,
    q: str | None = Query(default=None, max_length=200, description="Title substring or exact identifier"),
    mine: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> list[InvestigationOut]:
    stmt = select(Investigation)
    if mine or not principal.can(Permission.INVESTIGATION_READ_ALL):
        stmt = stmt.where(Investigation.created_by == principal.id)
    if status:
        stmt = stmt.where(Investigation.status == status)
    if subject_type:
        stmt = stmt.where(Investigation.subject_type == subject_type.value)
    if q:
        hashes = []
        for t in IdentifierType:
            ident = try_normalize(t, q)
            if ident:
                hashes.append(keyed_hash(identifier_key(ident)))
        conds = [Investigation.title.ilike(f"%{q.replace('%', '').replace('_', '')}%")]
        if hashes:
            conds.append(Investigation.subject_hash.in_(hashes))
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    rows = db.scalars(stmt.order_by(Investigation.created_at.desc()).limit(limit).offset(offset)).all()
    return [to_out(i) for i in rows]


@router.get("/stats")
def stats(
    principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    base = select(Investigation)
    if not principal.can(Permission.INVESTIGATION_READ_ALL):
        base = base.where(Investigation.created_by == principal.id)
    invs = db.scalars(base).all()
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    source_status: dict[str, dict[str, int]] = {}
    for i in invs:
        by_status[i.status] = by_status.get(i.status, 0) + 1
        by_type[i.subject_type] = by_type.get(i.subject_type, 0) + 1
        for src, st in ((i.progress or {}).get("sources") or {}).items():
            source_status.setdefault(src, {})
            source_status[src][st] = source_status[src].get(st, 0) + 1
    ids = [i.id for i in invs]
    by_class = (
        dict(
            db.execute(
                select(FindingRow.classification, func.count())
                .where(FindingRow.investigation_id.in_(ids))
                .group_by(FindingRow.classification)
            ).all()
        )
        if ids
        else {}
    )
    recent = sorted(invs, key=lambda i: i.created_at, reverse=True)[:8]
    today = utcnow().date()
    by_day = {(today - timedelta(days=d)).isoformat(): 0 for d in range(29, -1, -1)}
    for i in invs:
        day = i.created_at.date().isoformat()
        if day in by_day:
            by_day[day] += 1
    risk_levels: dict[str, int] = {}
    grades: dict[str, int] = {}
    for i in invs:
        if i.risk_level:
            risk_levels[i.risk_level] = risk_levels.get(i.risk_level, 0) + 1
        if i.posture_grade:
            grades[i.posture_grade] = grades.get(i.posture_grade, 0) + 1
    recent_changes = []
    attention = []
    completed = sorted(
        (i for i in invs if i.status == "completed" and i.finished_at), key=lambda i: i.finished_at, reverse=True
    )[:25]
    for i in completed:
        res = i.results
        ch = res.get("changes") or {}
        if ch and not ch.get("baseline") and (ch.get("added_count") or ch.get("removed_count")):
            recent_changes.append(
                {
                    "investigation_id": i.id,
                    "title": i.title,
                    "at": res.get("finished_at"),
                    "added": ch.get("added_count", 0),
                    "removed": ch.get("removed_count", 0),
                    "sample": [a["title"] for a in (ch.get("added") or [])[:3]],
                }
            )
        for h in (res.get("risk") or [])[:3]:
            if h.get("severity") in ("critical", "high"):
                attention.append({"investigation_id": i.id, "investigation": i.title, **h})
    return {
        "by_day": by_day,
        "monitored": sum(1 for i in invs if i.monitor_interval_hours),
        "risk_levels": risk_levels,
        "posture_grades": grades,
        "recent_changes": recent_changes[:8],
        "attention": attention[:10],
        "cases": len({i.case_id for i in invs if i.case_id}),
        "investigations": len(invs),
        "by_status": by_status,
        "by_subject_type": by_type,
        "findings_by_classification": by_class,
        "findings_total": sum(i.finding_count for i in invs),
        "source_status": source_status,
        "recent": [to_out(i).model_dump(mode="json") for i in recent],
    }


@router.get("/{inv_id}", response_model=InvestigationDetail)
def detail(
    inv_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> InvestigationDetail:
    inv = get_inv(db, principal, inv_id)
    res = inv.results
    corr = res.get("correlation") or {}
    return InvestigationDetail(
        **to_out(inv).model_dump(),
        coverage=res.get("coverage") or {},
        module_summary=res.get("module_summary") or {},
        entity_count=len(corr.get("entities") or []),
        relationship_count=len(corr.get("relationships") or []),
        contradiction_count=len(corr.get("contradictions") or []),
    )


@router.get("/{inv_id}/progress")
def progress(
    inv_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id)
    return {"status": inv.status, "progress": inv.progress or {}, "error": inv.error}


@router.post("/{inv_id}/run", response_model=InvestigationOut)
def rerun(
    inv_id: str,
    request: Request,
    background: BackgroundTasks,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    inv = get_inv(db, principal, inv_id, write=True)
    if inv.status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="investigation already running")
    inv.status = "queued"
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="investigation.run",
        target_type="investigation",
        target_id=inv.id,
        ip=client_ip(request),
    )
    dispatch_investigation(inv.id, background)
    return to_out(inv)


@router.get("/{inv_id}/findings")
def findings(
    inv_id: str,
    classification: str | None = Query(default=None, pattern="^(confirmed|possible|unverified|rejected)$"),
    source: str | None = Query(default=None, max_length=60),
    module: str | None = Query(default=None, max_length=30),
    finding_type: str | None = Query(default=None, max_length=60),
    min_score: float = Query(default=0.0, ge=0, le=1),
    q: str | None = Query(default=None, max_length=200),
    principal: Principal = Depends(require(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    inv = get_inv(db, principal, inv_id)
    stmt = select(FindingRow).where(FindingRow.investigation_id == inv.id, FindingRow.score >= min_score)
    if classification:
        stmt = stmt.where(FindingRow.classification == classification)
    if source:
        stmt = stmt.where(FindingRow.source_name == source)
    if module:
        stmt = stmt.where(FindingRow.module == module)
    if finding_type:
        stmt = stmt.where(FindingRow.finding_type == finding_type)
    out = []
    needle = q.lower() if q else None
    for row in db.scalars(stmt.order_by(FindingRow.score.desc())).all():
        data = row.data
        if (
            needle
            and needle not in f"{data.get('title')} {data.get('description')} {data.get('source_display_name')}".lower()
        ):
            continue
        data["classification"] = row.classification
        out.append(data)
    return out


@router.patch("/{inv_id}/findings/{finding_id}")
def verify_finding(
    inv_id: str,
    finding_id: str,
    body: FindingVerify,
    request: Request,
    principal: Principal = Depends(require(Permission.FINDING_VERIFY)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id, write=True)
    row = db.get(FindingRow, finding_id)
    if not row or row.investigation_id != inv.id:
        raise HTTPException(status_code=404, detail="finding not found")
    data = row.data
    old = data.get("verification_status")
    data["verification_status"] = body.status
    row.set_data(data)
    row.verification_status = body.status
    if body.note:
        db.add(
            AnalystNote(
                investigation_id=inv.id,
                finding_id=finding_id,
                author_id=principal.id,
                body_enc=encrypt_str(body.note) or "",
            )
        )
    db.commit()
    db.refresh(inv)
    svc.recompute(db, inv)
    audit(
        db,
        actor_id=principal.id,
        action="finding.verify",
        target_type="finding",
        target_id=finding_id,
        ip=client_ip(request),
        details={"from": old, "to": body.status, "investigation_id": inv.id},
    )
    updated = db.get(FindingRow, finding_id)
    result = updated.data if updated else data
    result["classification"] = updated.classification if updated else None
    return result


@router.get("/{inv_id}/graph")
def graph(
    inv_id: str,
    min_confidence: float = Query(default=0.0, ge=0, le=1),
    principal: Principal = Depends(require(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id)
    corr = CorrelationResult.model_validate(inv.results.get("correlation") or {})
    nodes = [
        {
            "id": e.id,
            "label": e.label,
            "kind": e.kind,
            "is_subject": e.is_subject,
            "confidence": e.confidence,
            "finding_ids": e.finding_ids,
            "identifiers": [i.key for i in e.identifiers],
            "attributes": e.attributes,
        }
        for e in corr.entities
        if e.is_subject or e.confidence >= min_confidence
    ]
    ids = {n["id"] for n in nodes}
    edges = [
        r.model_dump(mode="json")
        for r in corr.relationships
        if r.source_entity_id in ids and r.target_entity_id in ids and r.confidence >= min_confidence
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "name_collisions": [c.model_dump(mode="json") for c in corr.name_collisions],
        "contradictions": [c.model_dump(mode="json") for c in corr.contradictions],
    }


@router.get("/{inv_id}/timeline")
def timeline(
    inv_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    inv = get_inv(db, principal, inv_id)
    return (inv.results.get("analysis") or {}).get("timeline") or []


@router.get("/{inv_id}/analysis")
def get_analysis(
    inv_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id)
    return inv.results.get("analysis") or {}


@router.post("/{inv_id}/analysis")
def regenerate(
    inv_id: str,
    request: Request,
    use_ai: bool = True,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id, write=True)
    if inv.status != "completed":
        raise HTTPException(status_code=409, detail="investigation has not completed")
    analysis = svc.regenerate_analysis(db, inv, use_ai)
    audit(
        db,
        actor_id=principal.id,
        action="analysis.generate",
        target_type="investigation",
        target_id=inv.id,
        ip=client_ip(request),
        details={"ai": analysis.ai_generated, "provider": analysis.provider},
    )
    return analysis.model_dump(mode="json")


@router.get("/{inv_id}/notes")
def list_notes(
    inv_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    inv = get_inv(db, principal, inv_id)
    return [_note_out(n) for n in sorted(inv.notes, key=lambda n: n.created_at)]


def _note_out(n: AnalystNote) -> dict[str, Any]:
    return {
        "id": n.id,
        "finding_id": n.finding_id,
        "author": n.author.email if n.author else n.author_id,
        "body": n.body,
        "created_at": n.created_at.isoformat(),
    }


@router.post("/{inv_id}/notes", status_code=201)
def add_note(
    inv_id: str,
    body: NoteCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.FINDING_VERIFY)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id, write=True)
    if body.finding_id and not db.get(FindingRow, body.finding_id):
        raise HTTPException(status_code=404, detail="finding not found")
    note = AnalystNote(
        investigation_id=inv.id,
        finding_id=body.finding_id,
        author_id=principal.id,
        body_enc=encrypt_str(body.body) or "",
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    audit(
        db,
        actor_id=principal.id,
        action="note.create",
        target_type="investigation",
        target_id=inv.id,
        ip=client_ip(request),
    )
    return _note_out(note)


@router.get("/{inv_id}/report")
def report(
    inv_id: str,
    request: Request,
    format: str = Query(default="html", pattern="^(json|csv|html|pdf|stix)$"),
    principal: Principal = Depends(require(Permission.REPORT_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    inv = get_inv(db, principal, inv_id)
    if inv.status != "completed":
        raise HTTPException(status_code=409, detail="investigation has not completed")
    res = inv.results
    coverage = res.get("coverage") or {}
    owner = db.get(User, inv.created_by)
    data = ReportData(
        report_id=new_id()[:12],
        generated_by=principal.user.email,
        investigation={
            **to_out(inv).model_dump(mode="json"),
            "subject_display": f"{inv.subject_type}: {inv.subject_value}",
            "owner": owner.email if owner else inv.created_by,
            "collection_started_at": inv.started_at.isoformat() if inv.started_at else None,
            "collection_finished_at": inv.finished_at.isoformat() if inv.finished_at else None,
            "authorized_domains": ", ".join(inv.authorized_domains or []) or None,
        },
        findings=[Finding.model_validate(r.data) for r in sorted(inv.findings, key=lambda r: -r.score)],
        correlation=CorrelationResult.model_validate(res.get("correlation") or {}),
        coverage=coverage,
        analysis=AnalysisReport.model_validate(res["analysis"]) if res.get("analysis") else None,
        analyst_notes=[_note_out(n) for n in sorted(inv.notes, key=lambda n: n.created_at)],
        limitations=build_limitations(coverage),
        tlp=inv.tlp or "amber",
        posture=res.get("posture"),
        risk=res.get("risk") or [],
        changes=res.get("changes"),
    )
    if format == "stix":
        content = render_stix(
            build_stix_bundle(
                investigation=data.investigation, findings=data.findings, correlation=data.correlation, tlp=data.tlp
            )
        )
        media_type, ext = "application/stix+json;version=2.1", "stix.json"
    else:
        renderer, media_type, ext = RENDERERS[format]
        content = renderer(data)
    audit(
        db,
        actor_id=principal.id,
        action="report.export",
        target_type="investigation",
        target_id=inv.id,
        ip=client_ip(request),
        details={"format": format, "report_id": data.report_id},
    )
    headers = {
        "Content-Disposition": f'attachment; filename="atlas-report-{inv.id[:8]}-{data.report_id}.{ext}"',
        "Cache-Control": "no-store",
    }
    if format == "html":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return Response(content=content, media_type=media_type, headers=headers)


@router.patch("/{inv_id}", response_model=InvestigationOut)
def update_investigation(
    inv_id: str,
    body: InvestigationUpdate,
    request: Request,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    inv = get_inv(db, principal, inv_id, write=True)
    changes: dict[str, Any] = {}
    if body.title:
        inv.title = changes["title"] = body.title
    if body.tlp:
        inv.tlp = changes["tlp"] = body.tlp
    if body.remove_from_case:
        inv.case_id = None
        changes["case_id"] = None
    elif body.case_id:
        case = db.get(Case, body.case_id)
        if case is None or (case.created_by != principal.id and principal.role != "admin"):
            raise HTTPException(status_code=404, detail="case not found")
        inv.case_id = changes["case_id"] = case.id
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="investigation.update",
        target_type="investigation",
        target_id=inv.id,
        ip=client_ip(request),
        details=changes,
    )
    return to_out(inv)


@router.post("/{inv_id}/pivot", response_model=InvestigationOut, status_code=201)
def pivot(
    inv_id: str,
    body: PivotRequest,
    request: Request,
    background: BackgroundTasks,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    parent = get_inv(db, principal, inv_id, write=True)
    child = svc.pivot_investigation(db, parent, body, principal.user, client_ip(request))
    if body.run:
        dispatch_investigation(child.id, background)
    return to_out(child)


@router.put("/{inv_id}/monitoring", response_model=InvestigationOut)
def monitoring(
    inv_id: str,
    body: MonitoringUpdate,
    request: Request,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> InvestigationOut:
    inv = get_inv(db, principal, inv_id, write=True)
    return to_out(svc.set_monitoring(db, inv, body.interval_hours, principal.id, client_ip(request)))


@router.post("/{inv_id}/findings/bulk")
def bulk_verify(
    inv_id: str,
    body: BulkVerify,
    request: Request,
    principal: Principal = Depends(require(Permission.FINDING_VERIFY)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id, write=True)
    rows = {r.id: r for r in inv.findings}
    unknown = [fid for fid in body.finding_ids if fid not in rows]
    if unknown:
        raise HTTPException(status_code=404, detail=f"{len(unknown)} finding(s) not in this investigation")
    for fid in body.finding_ids:
        row = rows[fid]
        data = row.data
        data["verification_status"] = body.status
        row.set_data(data)
        row.verification_status = body.status
    if body.note:
        db.add(
            AnalystNote(
                investigation_id=inv.id,
                finding_id=None,
                author_id=principal.id,
                body_enc=encrypt_str(f"[bulk {body.status}: {len(body.finding_ids)} findings] {body.note}") or "",
            )
        )
    db.commit()
    db.refresh(inv)
    svc.recompute(db, inv)
    audit(
        db,
        actor_id=principal.id,
        action="finding.bulk_verify",
        target_type="investigation",
        target_id=inv.id,
        ip=client_ip(request),
        details={"status": body.status, "count": len(body.finding_ids)},
    )
    return {"updated": len(body.finding_ids), "status": body.status}


@router.get("/{inv_id}/assessment")
def assessment(
    inv_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    inv = get_inv(db, principal, inv_id)
    res = inv.results
    return {
        "posture": res.get("posture"),
        "risk": res.get("risk") or [],
        "changes": res.get("changes"),
        "run_history": res.get("run_history") or [],
        "monitoring": {
            "interval_hours": inv.monitor_interval_hours,
            "next_run_at": inv.next_run_at.isoformat() if inv.next_run_at else None,
            "allowed": inv.subject_kind in svc.MONITORABLE_KINDS,
        },
    }


@router.delete("/{inv_id}", status_code=204)
def delete(
    inv_id: str,
    request: Request,
    principal: Principal = Depends(require(Permission.INVESTIGATION_DELETE)),
    db: Session = Depends(get_db),
) -> Response:
    inv = get_inv(db, principal, inv_id, write=True)
    svc.delete_investigation(db, inv, principal.id, client_ip(request), reason="user_request")
    return Response(status_code=204)


__all__ = ["VerificationStatus", "router"]
