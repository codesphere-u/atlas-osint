"""FastAPI dependencies: authentication, CSRF and permission checks."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_api.db import get_db
from atlas_api.models import ApiKey, User
from atlas_api.security import API_KEY_PREFIX, Permission, decode_access_token, has_permission, hash_api_key
from shared.types import utcnow

SESSION_COOKIE = "atlas_session"
CSRF_HEADER = "x-atlas-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: User
    via: str  # bearer | api_key | cookie

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role

    def can(self, perm: Permission) -> bool:
        return has_permission(self.user.role, perm)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _unauthorized(detail: str = "authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    token, via = None, None
    if auth.lower().startswith("bearer "):
        token, via = auth[7:].strip(), "bearer"
    elif request.cookies.get(SESSION_COOKIE):
        token, via = request.cookies[SESSION_COOKIE], "cookie"
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status_code=403, detail="missing CSRF header")
    if not token:
        raise _unauthorized()
    if token.startswith(API_KEY_PREFIX):
        key = db.scalar(select(ApiKey).where(ApiKey.prefix == token[:12], ApiKey.key_hash == hash_api_key(token)))
        now = utcnow()
        if not key or key.revoked_at or (key.expires_at and _aware(key.expires_at) < now):
            raise _unauthorized("invalid API key")
        key.last_used_at = now
        db.commit()
        user = key.user
        via = "api_key"
    else:
        try:
            payload = decode_access_token(token)
        except jwt.PyJWTError as exc:
            raise _unauthorized("invalid or expired token") from exc
        user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise _unauthorized("account disabled")
    request.state.user_id = user.id
    return Principal(user=user, via=via or "bearer")


def _aware(dt):  # type: ignore[no-untyped-def]
    from datetime import UTC

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def require(perm: Permission):  # type: ignore[no-untyped-def]
    def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(perm):
            raise HTTPException(status_code=403, detail=f"permission '{perm.value}' required")
        return principal

    return dep
