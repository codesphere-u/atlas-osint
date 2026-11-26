from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas_api import __version__
from atlas_api.audit import audit
from atlas_api.db import get_db
from atlas_api.deps import Principal, client_ip, require
from atlas_api.models import AuditLog, Investigation, PrivacyRequest, Suppression, User
from atlas_api.routers.auth import user_out
from atlas_api.schemas import UserCreate, UserOut, UserUpdate
from atlas_api.security import Permission, hash_password, validate_password_strength
from atlas_api.services.investigations import purge_expired
from integrations.sources.registry import get_registry
from shared.config import get_settings

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    principal: Principal = Depends(require(Permission.USER_MANAGE)), db: Session = Depends(get_db)
) -> list[UserOut]:
    return [user_out(u) for u in db.scalars(select(User).order_by(User.created_at)).all()]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> UserOut:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="user exists")
    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    u = User(email=email, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="user.create",
        target_type="user",
        target_id=u.id,
        ip=client_ip(request),
        details={"role": body.role},
    )
    return user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    principal: Principal = Depends(require(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> UserOut:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="not found")
    if u.id == principal.id and (body.role not in (None, "admin") or body.is_active is False):
        raise HTTPException(status_code=409, detail="you cannot demote or disable yourself")
    if body.role:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        try:
            validate_password_strength(body.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        u.password_hash = hash_password(body.password)
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="user.update",
        target_type="user",
        target_id=u.id,
        ip=client_ip(request),
        details=body.model_dump(exclude_none=True, exclude={"password"}) | {"password_changed": bool(body.password)},
    )
    return user_out(u)


@router.get("/audit")
def audit_logs(
    action: str | None = Query(default=None, max_length=60),
    actor_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return [
        {
            "id": r.id,
            "ts": r.ts.isoformat(),
            "actor_id": r.actor_id,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "ip": r.ip,
            "outcome": r.outcome,
            "details": r.details,
        }
        for r in rows
    ]


@router.post("/retention/run")
def run_retention(
    request: Request, principal: Principal = Depends(require(Permission.SYSTEM_MANAGE)), db: Session = Depends(get_db)
) -> dict[str, int]:
    removed = purge_expired(db)
    audit(db, actor_id=principal.id, action="retention.run", ip=client_ip(request), details={"removed": removed})
    return {"removed": removed}


@router.get("/system")
def system(
    principal: Principal = Depends(require(Permission.SYSTEM_MANAGE)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    s = get_settings()
    return {
        "version": __version__,
        "environment": s.env,
        "database": s.database_url.split(":", 1)[0],
        "task_backend": s.task_backend,
        "redis": bool(s.redis_url),
        "ai_provider": s.ai_provider,
        "ai_model": s.ai_model if s.ai_provider != "none" else None,
        "require_consent_for_individuals": s.require_consent_for_individuals,
        "default_retention_days": s.default_retention_days,
        "max_retention_days": s.max_retention_days,
        "encryption_key_configured": s.encryption_key is not None,
        "hash_key_configured": s.hash_key is not None,
        "production_config_problems": s.validate_production(),
        "sources_registered": len(get_registry().names()),
        "counts": {
            "users": db.scalar(select(func.count()).select_from(User)),
            "investigations": db.scalar(select(func.count()).select_from(Investigation)),
            "suppressions": db.scalar(select(func.count()).select_from(Suppression)),
            "pending_privacy_requests": db.scalar(
                select(func.count()).select_from(PrivacyRequest).where(PrivacyRequest.status == "pending")
            ),
        },
    }
