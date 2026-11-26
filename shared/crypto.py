"""Encryption at rest and keyed hashing.

* Sensitive database columns are encrypted with Fernet (AES-128-CBC + HMAC-SHA256).
* Identifiers that must be looked up without being stored in clear text
  (suppression list, audit log) are stored as HMAC-SHA256 digests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from shared.config import get_settings


def _derive(material: str, label: bytes) -> bytes:
    return hashlib.sha256(label + material.encode()).digest()


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key is not None:
        return Fernet(settings.encryption_key.get_secret_value().encode())
    # Development fallback: derive from the secret key. Production refuses to start without a key.
    key = base64.urlsafe_b64encode(_derive(settings.secret_key.get_secret_value(), b"atlas-enc"))
    return Fernet(key)


def reset_crypto_cache() -> None:
    _fernet.cache_clear()


def encrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(token: str | None) -> str | None:
    if token is None:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def keyed_hash(value: str) -> str:
    settings = get_settings()
    key = (
        settings.hash_key.get_secret_value().encode()
        if settings.hash_key
        else _derive(settings.secret_key.get_secret_value(), b"atlas-hash")
    )
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()
