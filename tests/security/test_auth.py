"""Authentication: tokens, API keys, cookies + CSRF, lockout."""

from datetime import timedelta

import jwt
from atlas_api.security import JWT_ALG

from shared.config import get_settings
from shared.types import utcnow


def test_unauthenticated_requests_rejected(client):
    for method, path in [
        ("get", "/api/v1/investigations"),
        ("get", "/api/v1/sources"),
        ("get", "/api/v1/admin/users"),
        ("post", "/api/v1/investigations"),
    ]:
        assert getattr(client, method)(path).status_code == 401


def test_invalid_and_expired_tokens(client, analyst_headers):
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    secret = get_settings().secret_key.get_secret_value()
    me = client.get("/api/v1/auth/me", headers=analyst_headers).json()
    expired = jwt.encode(
        {
            "sub": me["id"],
            "role": "admin",
            "typ": "access",
            "iat": 0,
            "exp": int((utcnow() - timedelta(minutes=1)).timestamp()),
        },
        secret,
        algorithm=JWT_ALG,
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode(
        {"sub": me["id"], "role": "admin", "typ": "access", "iat": 0, "exp": 9999999999},
        "wrong-secret-wrong-secret-wrong-secret",
        algorithm=JWT_ALG,
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"sub": me["id"], "typ": "access", "iat": 0, "exp": 9999999999}, None, algorithm="none")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401


def test_role_in_token_is_not_trusted(client, viewer_headers):
    # A viewer's token carries role=viewer; permissions come from the database record, not the token claim.
    me = client.get("/api/v1/auth/me", headers=viewer_headers).json()
    secret = get_settings().secret_key.get_secret_value()
    tok = jwt.encode(
        {"sub": me["id"], "role": "admin", "typ": "access", "iat": 0, "exp": 9999999999}, secret, algorithm=JWT_ALG
    )
    assert client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_api_key_lifecycle(client, analyst_headers):
    r = client.post("/api/v1/auth/api-keys", json={"name": "ci", "expires_in_days": 30}, headers=analyst_headers)
    assert r.status_code == 201
    key = r.json()["key"]
    assert key.startswith("atl_")
    kh = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/v1/auth/me", headers=kh).status_code == 200
    listed = client.get("/api/v1/auth/api-keys", headers=analyst_headers).json()
    assert all(k["key"] is None for k in listed)  # never returned again
    assert client.post("/api/v1/auth/api-keys", json={"name": "x"}, headers=kh).status_code == 403
    assert client.delete(f"/api/v1/auth/api-keys/{r.json()['id']}", headers=analyst_headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=kh).status_code == 401


def test_cookie_session_requires_csrf_header_for_writes(client, make_user):
    make_user("cookie@atlas-osint-test.com", "analyst")
    r = client.post(
        "/api/v1/auth/login", json={"email": "cookie@atlas-osint-test.com", "password": "User-Password-123"}
    )
    assert "atlas_session" in r.cookies
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    try:
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.post("/api/v1/auth/api-keys", json={"name": "x"}).status_code == 403
        assert (
            client.post("/api/v1/auth/api-keys", json={"name": "x"}, headers={"X-Atlas-CSRF": "1"}).status_code == 201
        )
    finally:
        client.cookies.clear()


def test_login_lockout(client, make_user):
    make_user("lock@atlas-osint-test.com", "viewer")
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"email": "lock@atlas-osint-test.com", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "lock@atlas-osint-test.com", "password": "User-Password-123"})
    assert r.status_code == 401 and "locked" in r.json()["detail"]
    client.cookies.clear()


def test_unknown_user_and_wrong_password_are_indistinguishable(client):
    a = client.post("/api/v1/auth/login", json={"email": "nobody@atlas-osint-test.com", "password": "x"})
    b = client.post("/api/v1/auth/login", json={"email": "admin@atlas-osint-test.com", "password": "x"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_weak_passwords_rejected(client, admin_headers):
    r = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"email": "weak@atlas-osint-test.com", "password": "aaaaaaaaaaaa", "role": "viewer"},
    )
    assert r.status_code == 422


def test_cli_reset_password_clears_lockout_and_is_audited(client, make_user, admin_headers, monkeypatch, capsys):
    import io

    from atlas_api.cli import main

    email = "reset@atlas-osint-test.com"
    make_user(email, "viewer")
    for _ in range(6):
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert "locked" in client.post("/api/v1/auth/login", json={"email": email, "password": "User-Password-123"}).text

    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert main(["reset-password", email, "--stdin"]) == 1  # strength rules still apply
    monkeypatch.setattr("sys.stdin", io.StringIO("Recovered-Pass-2026\n"))
    assert main(["reset-password", "nobody@atlas-osint-test.com", "--stdin"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("Recovered-Pass-2026\n"))
    assert main(["reset-password", email, "--stdin"]) == 0
    assert "lockout cleared" in capsys.readouterr().out

    assert client.post("/api/v1/auth/login", json={"email": email, "password": "User-Password-123"}).status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": "Recovered-Pass-2026"}).status_code == 200
    )
    actions = [e["action"] for e in client.get("/api/v1/admin/audit?limit=200", headers=admin_headers).json()]
    assert "user.password_reset_cli" in actions
