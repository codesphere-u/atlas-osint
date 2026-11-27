"""Cases: group related investigations and analyse them together (merged entity graph and timeline)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_api.audit import audit
from atlas_api.db import get_db
from atlas_api.deps import Principal, client_ip, require
from atlas_api.models import Case, Investigation
from atlas_api.routers.investigations import to_out
from atlas_api.schemas import CaseCreate, CaseUpdate
from atlas_api.security import Permission
from atlas_api.services.investigations import load_findings, subject_of
from engine.analysis.analyst import build_timeline
from engine.correlation.resolver import finalize_entity_confidence, resolve
from engine.reporting.stix import build_stix_bundle, render_stix
from engine.verification.scoring import score_findings
from shared.crypto import encrypt_str
from shared.types import Finding, Identifier

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])
RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}


def _visible(principal: Principal, inv: Investigation) -> bool:
    return inv.created_by == principal.id or principal.can(Permission.INVESTIGATION_READ_ALL)


def _get_case(db: Session, principal: Principal, case_id: str, write: bool = False) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    owner = case.created_by == principal.id
    if write and not (owner or principal.role == "admin"):
        raise HTTPException(status_code=403, detail="only the owner or an administrator may modify this case")
    if not write and not (owner or principal.can(Permission.INVESTIGATION_READ_ALL)):
        raise HTTPException(status_code=404, detail="case not found")
    return case


def _case_out(case: Case, principal: Principal) -> dict[str, Any]:
    invs = [i for i in case.investigations if _visible(principal, i)]
    risk = min((i.risk_level or "none" for i in invs), key=lambda r: RISK_ORDER.get(r, 9), default="none")
    last = max((i.finished_at or i.created_at for i in invs), default=case.created_at)
    return {
        "id": case.id,
        "title": case.title,
        "description": case.description,
        "status": case.status,
        "tlp": case.tlp,
        "created_by": case.created_by,
        "created_at": case.created_at.isoformat(),
        "updated_at": last.isoformat(),
        "investigation_count": len(invs),
        "finding_count": sum(i.finding_count for i in invs),
        "confirmed_count": sum(i.confirmed_count for i in invs),
        "risk_level": risk,
        "subject_types": sorted({i.subject_type for i in invs}),
    }


@router.get("")
def list_cases(
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
    principal: Principal = Depends(require(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Case).order_by(Case.created_at.desc())
    if not principal.can(Permission.INVESTIGATION_READ_ALL):
        stmt = stmt.where(Case.created_by == principal.id)
    if status:
        stmt = stmt.where(Case.status == status)
    return [_case_out(c, principal) for c in db.scalars(stmt).all()]


@router.post("", status_code=201)
def create_case(
    body: CaseCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    case = Case(
        title=body.title,
        description_enc=encrypt_str(body.description) if body.description else None,
        tlp=body.tlp,
        created_by=principal.id,
    )
    db.add(case)
    db.commit()
    audit(db, actor_id=principal.id, action="case.create", target_type="case", target_id=case.id, ip=client_ip(request))
    return _case_out(case, principal)


@router.get("/{case_id}")
def get_case(
    case_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    case = _get_case(db, principal, case_id)
    invs = sorted((i for i in case.investigations if _visible(principal, i)), key=lambda i: i.created_at)
    return {**_case_out(case, principal), "investigations": [to_out(i).model_dump(mode="json") for i in invs]}


@router.patch("/{case_id}")
def update_case(
    case_id: str,
    body: CaseUpdate,
    request: Request,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    case = _get_case(db, principal, case_id, write=True)
    if body.title:
        case.title = body.title
    if body.description is not None:
        case.description_enc = encrypt_str(body.description) if body.description else None
    if body.status:
        case.status = body.status
    if body.tlp:
        case.tlp = body.tlp
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="case.update",
        target_type="case",
        target_id=case.id,
        ip=client_ip(request),
        details=body.model_dump(exclude_none=True, exclude={"description"}),
    )
    return _case_out(case, principal)


@router.delete("/{case_id}", status_code=204)
def delete_case(
    case_id: str,
    request: Request,
    principal: Principal = Depends(require(Permission.INVESTIGATION_CREATE)),
    db: Session = Depends(get_db),
) -> Response:
    case = _get_case(db, principal, case_id, write=True)
    for inv in list(case.investigations):
        inv.case_id = None  # investigations are kept; only the grouping is removed
    db.delete(case)
    db.commit()
    audit(db, actor_id=principal.id, action="case.delete", target_type="case", target_id=case_id, ip=client_ip(request))
    return Response(status_code=204)


def _merged(db: Session, principal: Principal, case: Case) -> tuple[list[Investigation], list[Finding], Any]:
    invs = [i for i in case.investigations if _visible(principal, i) and i.status == "completed"]
    findings: list[Finding] = []
    subjects: list[Identifier] = []
    for inv in invs:
        findings.extend(load_findings(inv))
        subjects.append(subject_of(inv))
    if not subjects:
        return invs, [], None
    corr = resolve(findings, subjects[0], subjects[1:])
    score_findings(findings, corr)
    finalize_entity_confidence(corr, findings)
    return invs, findings, corr


@router.get("/{case_id}/graph")
def case_graph(
    case_id: str,
    min_confidence: float = Query(default=0.0, ge=0, le=1),
    principal: Principal = Depends(require(Permission.INVESTIGATION_READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    case = _get_case(db, principal, case_id)
    _, _, corr = _merged(db, principal, case)
    if corr is None:
        return {"nodes": [], "edges": [], "name_collisions": [], "contradictions": []}
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


@router.get("/{case_id}/timeline")
def case_timeline(
    case_id: str, principal: Principal = Depends(require(Permission.INVESTIGATION_READ)), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    case = _get_case(db, principal, case_id)
    invs, findings, _corr = _merged(db, principal, case)
    owner = {}
    for inv in invs:
        for row in inv.findings:
            owner[row.id] = (inv.id, inv.title)
    events = []
    for e in build_timeline(findings):
        inv_id, title = owner.get(e.finding_id, (None, None))
        events.append({**e.model_dump(mode="json"), "investigation_id": inv_id, "investigation": title})
    return events


@router.get("/{case_id}/export")
def case_export(
    case_id: str,
    request: Request,
    format: str = Query(default="stix", pattern="^(stix|json)$"),
    principal: Principal = Depends(require(Permission.REPORT_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    case = _get_case(db, principal, case_id)
    invs, findings, corr = _merged(db, principal, case)
    if corr is None:
        raise HTTPException(status_code=409, detail="the case has no completed investigations")
    meta = {
        "id": case.id,
        "title": case.title,
        "subject_type": "case",
        "legal_basis": ", ".join(sorted({i.legal_basis for i in invs})),
        "purpose": case.description or case.title,
        "finished_at": max(i.finished_at for i in invs if i.finished_at).isoformat(),
    }
    if format == "stix":
        content = render_stix(build_stix_bundle(investigation=meta, findings=findings, correlation=corr, tlp=case.tlp))
        media, ext = "application/stix+json;version=2.1", "stix.json"
    else:
        content = json.dumps(
            {
                "case": _case_out(case, principal),
                "investigations": [to_out(i).model_dump(mode="json") for i in invs],
                "findings": [f.model_dump(mode="json") for f in findings],
                "correlation": corr.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        ).encode()
        media, ext = "application/json", "json"
    audit(
        db,
        actor_id=principal.id,
        action="case.export",
        target_type="case",
        target_id=case.id,
        ip=client_ip(request),
        details={"format": format, "investigations": len(invs)},
    )
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="atlas-case-{case.id[:8]}.{ext}"',
            "Cache-Control": "no-store",
        },
    )
