"""Data-subject rights: opt-out, correction and deletion requests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_api.audit import audit
from atlas_api.db import get_db
from atlas_api.deps import Principal, client_ip, require
from atlas_api.models import FindingRow, Investigation, PrivacyRequest, Suppression
from atlas_api.schemas import PrivacyRequestCreate, PrivacyRequestResolve
from atlas_api.security import Permission
from atlas_api.services.investigations import delete_investigation, recompute
from engine.correlation.resolver import identifier_key
from engine.normalization.identifiers import InvalidIdentifier, normalize
from engine.pipeline import suppression_keys
from shared.crypto import decrypt_str, encrypt_str, keyed_hash
from shared.types import Finding, utcnow

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])


@router.post("/requests", status_code=202)
def submit(body: PrivacyRequestCreate, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Public endpoint (no authentication, strict rate limit) for data subjects."""
    try:
        ident = normalize(body.identifier_type, body.identifier)
    except InvalidIdentifier as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    h = keyed_hash(identifier_key(ident))
    req = PrivacyRequest(
        kind=body.kind,
        identifier_type=ident.type.value,
        identifier_hash=h,
        identifier_enc=encrypt_str(ident.value) or "",
        contact_enc=encrypt_str(body.contact_email),
        details_enc=encrypt_str(body.details),
    )
    db.add(req)
    db.commit()
    audit(
        db,
        actor_id=None,
        action="privacy.request",
        target_type="privacy_request",
        target_id=req.id,
        ip=client_ip(request),
        details={"kind": body.kind, "identifier_hash": h},
    )
    return {
        "id": req.id,
        "status": "pending",
        "message": "Your request has been recorded and will be reviewed. Keep this reference ID.",
    }


def _req_out(r: PrivacyRequest) -> dict[str, Any]:
    return {
        "id": r.id,
        "kind": r.kind,
        "identifier_type": r.identifier_type,
        "identifier": decrypt_str(r.identifier_enc),
        "contact_email": decrypt_str(r.contact_enc),
        "details": decrypt_str(r.details_enc),
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "resolution_note": r.resolution_note,
    }


@router.get("/requests")
def list_requests(
    status: str | None = None,
    principal: Principal = Depends(require(Permission.PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(PrivacyRequest).order_by(PrivacyRequest.created_at.desc())
    if status:
        stmt = stmt.where(PrivacyRequest.status == status)
    return [_req_out(r) for r in db.scalars(stmt).all()]


def _purge_identifier(db: Session, ident_hash: str) -> dict[str, int]:
    """Delete investigations about the identifier and remove findings that reference it elsewhere."""
    removed_inv = 0
    for inv in db.scalars(select(Investigation).where(Investigation.subject_hash == ident_hash)).all():
        delete_investigation(db, inv, actor_id=None, ip=None, reason="privacy_deletion")  # type: ignore[arg-type]
        removed_inv += 1
    removed_findings = 0
    touched: set[str] = set()
    for row in db.scalars(select(FindingRow)).all():
        f = Finding.model_validate(row.data)
        keys = {f.entity_hint or ""} | {k for li in f.linked for k in suppression_keys(li.identifier)}
        if any(k and keyed_hash(k) == ident_hash for k in keys):
            touched.add(row.investigation_id)
            db.delete(row)
            removed_findings += 1
    db.commit()
    for inv_id in touched:
        inv = db.get(Investigation, inv_id)
        if inv:
            db.refresh(inv)
            recompute(db, inv)
    return {"investigations_deleted": removed_inv, "findings_deleted": removed_findings}


@router.post("/requests/{req_id}/resolve")
def resolve(
    req_id: str,
    body: PrivacyRequestResolve,
    request: Request,
    principal: Principal = Depends(require(Permission.PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    req = db.get(PrivacyRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="not found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="request already resolved")
    effects: dict[str, Any] = {}
    if body.status == "approved" and req.kind in ("opt_out", "deletion"):
        if not db.scalar(select(Suppression).where(Suppression.identifier_hash == req.identifier_hash)):
            db.add(
                Suppression(
                    identifier_hash=req.identifier_hash,
                    identifier_type=req.identifier_type,
                    reason=req.kind,
                    request_id=req.id,
                )
            )
            db.commit()
        effects["suppressed"] = True
        if req.kind == "deletion":
            effects.update(_purge_identifier(db, req.identifier_hash))
    req.status = "completed" if body.status == "approved" else body.status
    req.resolved_at, req.resolved_by, req.resolution_note = utcnow(), principal.id, body.note
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="privacy.resolve",
        target_type="privacy_request",
        target_id=req.id,
        ip=client_ip(request),
        details={"status": req.status, "kind": req.kind, **effects},
    )
    return {**_req_out(req), "effects": effects}
