"""Encryption at rest, input validation, rate limiting, headers, secrets handling."""

import logging

from atlas_api.db import get_sessionmaker
from sqlalchemy import text

from shared.config import Settings
from shared.logging import JsonFormatter, redact
from tests.integration.test_api_flow import USER_INV


def test_sensitive_columns_are_encrypted_at_rest(client, analyst_headers, mocked_collection):
    inv_id = client.post(
        "/api/v1/investigations", json={**USER_INV, "subject": "octo-sample"}, headers=analyst_headers
    ).json()["id"]
    with get_sessionmaker()() as db:
        row = db.execute(text("SELECT subject_enc, results_enc FROM investigations WHERE id=:i"), {"i": inv_id}).one()
        assert "octo-sample" not in row[0] and "octo-sample" not in row[1]
        blobs = [
            r[0] for r in db.execute(text("SELECT data_enc FROM findings WHERE investigation_id=:i"), {"i": inv_id})
        ]
        assert blobs and all("octo" not in b for b in blobs)


def test_extra_fields_and_invalid_identifiers_rejected(client, analyst_headers):
    r = client.post("/api/v1/investigations", json={**USER_INV, "is_admin": True}, headers=analyst_headers)
    assert r.status_code == 422
    for t, v in [
        ("email", "not-an-email"),
        ("phone", "12"),
        ("domain", "localhost"),
        ("username", "../../etc"),
        ("url", "file:///etc/passwd"),
        ("document", "javascript:alert(1)"),
    ]:
        r = client.post(
            "/api/v1/investigations", json={**USER_INV, "subject_type": t, "subject": v}, headers=analyst_headers
        )
        assert r.status_code == 422, (t, v)


def test_control_characters_and_oversized_payloads(client, analyst_headers):
    r = client.post("/api/v1/investigations", json={**USER_INV, "title": "bad\x07title"}, headers=analyst_headers)
    assert r.status_code == 422
    r = client.post(
        "/api/v1/investigations",
        content=b"{" + b" " * 1_100_000 + b"}",
        headers={**analyst_headers, "content-type": "application/json"},
    )
    assert r.status_code == 413


def test_unknown_source_rejected(client, analyst_headers):
    r = client.post(
        "/api/v1/investigations", json={**USER_INV, "options": {"sources": ["evil"]}}, headers=analyst_headers
    )
    assert r.status_code == 422


def test_security_headers(client):
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and "x-request-id" in r.headers
    r = client.get("/api/v1/meta")
    assert r.headers["cache-control"] == "no-store"


def test_rate_limiter_blocks_excess():
    from shared.ratelimit import WindowRateLimiter

    rl = WindowRateLimiter()
    results = [rl.hit("k", 3)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_public_endpoint_rate_limited(app):
    from fastapi.testclient import TestClient

    from shared.config import get_settings

    s = get_settings()
    old = s.public_rate_limit_per_minute
    s.public_rate_limit_per_minute = 2
    try:
        from atlas_api.main import create_app

        with TestClient(create_app()) as c:
            codes = [
                c.post(
                    "/api/v1/privacy/requests",
                    json={"kind": "opt_out", "identifier_type": "username", "identifier": f"rl-{i}"},
                ).status_code
                for i in range(4)
            ]
        assert codes[:2] == [202, 202] and 429 in codes[2:]
    finally:
        s.public_rate_limit_per_minute = old


def test_secrets_are_redacted_in_logs():
    assert "sk-ant-abc" not in redact("key sk-ant-abc123 used")
    assert "hunter2" not in redact('password="hunter2"')
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "Authorization: Bearer atl_abcdefghijklmnop", None, None)
    assert "atl_abcdefghijklmnop" not in JsonFormatter().format(rec)


def test_settings_repr_hides_secrets():
    s = Settings(secret_key="super-secret-value-super-secret-value-1234")
    assert "super-secret-value" not in repr(s)


def test_production_configuration_is_validated():
    s = Settings(
        env="production",
        secret_key="dev-insecure-change-me-dev-insecure-change-me",
        encryption_key=None,
        hash_key=None,
        cookie_secure=False,
        database_url="sqlite:///x.db",
    )
    problems = s.validate_production()
    assert any("SECRET_KEY" in p for p in problems) and any("ENCRYPTION_KEY" in p for p in problems)
    assert any("SQLite" in p for p in problems) and any("COOKIE_SECURE" in p for p in problems)
    ok = Settings(
        env="production",
        secret_key="k" * 40,
        encryption_key="x5Hk3ZbUq0Gv1H1Qd8qUe1c2bH9H8mJm3oT3n0W7k2Q=",
        hash_key="h",
        cookie_secure=True,
        database_url="postgresql+psycopg://a:b@db/atlas",
    )
    assert ok.validate_production() == []


def test_list_settings_accept_csv_and_json_env(monkeypatch):
    monkeypatch.setenv("ATLAS_CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("ATLAS_HTTP_ALLOWED_PORTS", "[80, 443, 8443]")
    s = Settings()
    assert s.cors_origins == ["https://a.example", "https://b.example"]
    assert s.http_allowed_ports == [80, 443, 8443]


def test_rotating_bogus_tokens_hit_per_ip_limit():
    from atlas_api.main import create_app
    from fastapi.testclient import TestClient

    from shared.config import get_settings

    s = get_settings()
    old = s.api_rate_limit_per_minute
    s.api_rate_limit_per_minute = 2  # per-IP ceiling = 8
    try:
        with TestClient(create_app()) as c:
            codes = [
                c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer bogus-token-{i:04d}"}).status_code
                for i in range(12)
            ]
        assert codes[0] == 401 and 429 in codes
    finally:
        s.api_rate_limit_per_minute = old
