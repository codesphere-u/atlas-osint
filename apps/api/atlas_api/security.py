"""Authentication primitives and role-based access control."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from enum import StrEnum

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from shared.config import get_settings
from shared.types import utcnow

_hasher = PasswordHasher()
JWT_ALG = "HS256"
API_KEY_PREFIX = "atl_"
MIN_PASSWORD_LENGTH = 12


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"
    AUDITOR = "auditor"


ROLE_RANK = {Role.VIEWER: 1, Role.AUDITOR: 1, Role.ANALYST: 2, Role.ADMIN: 3}


class Permission(StrEnum):
    INVESTIGATION_CREATE = "investigation:create"
    INVESTIGATION_READ = "investigation:read"
    INVESTIGATION_READ_ALL = "investigation:read_all"
    INVESTIGATION_DELETE = "investigation:delete"
    FINDING_VERIFY = "finding:verify"
    REPORT_EXPORT = "report:export"
    SOURCE_READ = "source:read"
    SOURCE_MANAGE = "source:manage"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"
    PRIVACY_MANAGE = "privacy:manage"
    SYSTEM_MANAGE = "system:manage"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.ANALYST: frozenset(
        {
            Permission.INVESTIGATION_CREATE,
            Permission.INVESTIGATION_READ,
            Permission.INVESTIGATION_DELETE,
            Permission.FINDING_VERIFY,
            Permission.REPORT_EXPORT,
            Permission.SOURCE_READ,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.INVESTIGATION_READ,
            Permission.INVESTIGATION_READ_ALL,
            Permission.REPORT_EXPORT,
            Permission.SOURCE_READ,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.INVESTIGATION_READ,
            Permission.INVESTIGATION_READ_ALL,
            Permission.AUDIT_READ,
            Permission.SOURCE_READ,
            Permission.REPORT_EXPORT,
        }
    ),
}


def has_permission(role: str, perm: Permission) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


def role_at_least(role: str, minimum: str) -> bool:
    try:
        return ROLE_RANK[Role(role)] >= ROLE_RANK[Role(minimum)]
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    classes = sum(bool(any(f(c) for c in password)) for f in (str.islower, str.isupper, str.isdigit))
    if classes < 2 and not any(not c.isalnum() for c in password):
        raise ValueError("password must mix character classes")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def create_access_token(user_id: str, role: str, ttl_minutes: int | None = None) -> tuple[str, int]:
    settings = get_settings()
    ttl = ttl_minutes or settings.access_token_ttl_minutes
    now = utcnow()
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "jti": secrets.token_hex(8),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALG), ttl * 60


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        get_settings().secret_key.get_secret_value(),
        algorithms=[JWT_ALG],
        options={"require": ["exp", "sub", "iat"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, hash). Only the hash is stored."""
    body = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}{body}"
    return full, full[:12], hash_api_key(full)


def hash_api_key(key: str) -> str:
    secret = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(secret, key.encode(), hashlib.sha256).hexdigest()
