from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_api.audit import audit
from atlas_api.db import get_db
from atlas_api.deps import SESSION_COOKIE, Principal, client_ip, get_principal
from atlas_api.models import ApiKey, User
from atlas_api.schemas import ApiKeyCreate, ApiKeyOut, LoginRequest, TokenResponse, UserOut
from atlas_api.security import DUMMY_HASH, create_access_token, generate_api_key, verify_password
from shared.config import get_settings
from shared.crypto import keyed_hash
from shared.types import utcnow

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()
    ip = client_ip(request)
    if user is None:
        verify_password(body.password, DUMMY_HASH)  # equalise timing
        audit(
            db, actor_id=None, action="auth.login", outcome="failure", ip=ip, details={"email_hash": keyed_hash(email)}
        )
        raise HTTPException(status_code=401, detail="invalid credentials")
    locked = (
        user.locked_until
        and (user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=now.tzinfo)) > now
    )
    if locked or not user.is_active:
        audit(
            db,
            actor_id=user.id,
            action="auth.login",
            outcome="denied",
            ip=ip,
            details={"reason": "locked" if locked else "disabled"},
        )
        raise HTTPException(status_code=401, detail="account locked or disabled")
    if not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_logins = 0
        db.commit()
        audit(db, actor_id=user.id, action="auth.login", outcome="failure", ip=ip)
        raise HTTPException(status_code=401, detail="invalid credentials")
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    db.commit()
    token, expires = create_access_token(user.id, user.role)
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=expires,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    audit(db, actor_id=user.id, action="auth.login", ip=ip)
    return TokenResponse(access_token=token, expires_in=expires, user=user_out(user))


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(get_principal)) -> UserOut:
    return user_out(principal.user)


def key_out(k: ApiKey, full: str | None = None) -> ApiKeyOut:
    return ApiKeyOut(
        id=k.id,
        name=k.name,
        prefix=k.prefix,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
        expires_at=k.expires_at,
        revoked_at=k.revoked_at,
        key=full,
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> list[ApiKeyOut]:
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == principal.id).order_by(ApiKey.created_at.desc())).all()
    return [key_out(k) for k in keys]


@router.post("/api-keys", response_model=ApiKeyOut, status_code=201)
def create_key(
    body: ApiKeyCreate, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> ApiKeyOut:
    if principal.via == "api_key":
        raise HTTPException(status_code=403, detail="API keys cannot create API keys")
    full, prefix, hashed = generate_api_key()
    key = ApiKey(
        user_id=principal.id,
        name=body.name,
        prefix=prefix,
        key_hash=hashed,
        expires_at=utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None,
    )
    db.add(key)
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="apikey.create",
        target_type="api_key",
        target_id=key.id,
        ip=client_ip(request),
    )
    return key_out(key, full)


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(
    key_id: str, request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> Response:
    key = db.get(ApiKey, key_id)
    if not key or key.user_id != principal.id:
        raise HTTPException(status_code=404, detail="not found")
    key.revoked_at = utcnow()
    db.commit()
    audit(
        db,
        actor_id=principal.id,
        action="apikey.revoke",
        target_type="api_key",
        target_id=key.id,
        ip=client_ip(request),
    )
    return Response(status_code=204)
