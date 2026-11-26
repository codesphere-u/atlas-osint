"""Role-based access control and investigation ownership."""

import pytest

from tests.integration.test_api_flow import DOMAIN_INV


@pytest.fixture
def analyst_inv(client, analyst_headers, mocked_collection):
    return client.post("/api/v1/investigations", json=DOMAIN_INV, headers=analyst_headers).json()["id"]


def test_viewer_cannot_create_or_modify(client, viewer_headers, analyst_inv):
    assert client.post("/api/v1/investigations", json=DOMAIN_INV, headers=viewer_headers).status_code == 403
    assert client.get(f"/api/v1/investigations/{analyst_inv}", headers=viewer_headers).status_code == 200
    assert client.delete(f"/api/v1/investigations/{analyst_inv}", headers=viewer_headers).status_code == 403
    findings = client.get(f"/api/v1/investigations/{analyst_inv}/findings", headers=viewer_headers).json()
    r = client.patch(
        f"/api/v1/investigations/{analyst_inv}/findings/{findings[0]['id']}",
        json={"status": "verified"},
        headers=viewer_headers,
    )
    assert r.status_code == 403
    assert (
        client.get(f"/api/v1/investigations/{analyst_inv}/report?format=json", headers=viewer_headers).status_code
        == 200
    )


def test_analysts_are_isolated_from_each_other(client, analyst2_headers, analyst_inv):
    assert client.get(f"/api/v1/investigations/{analyst_inv}", headers=analyst2_headers).status_code == 404
    assert client.get(f"/api/v1/investigations/{analyst_inv}/findings", headers=analyst2_headers).status_code == 404
    assert client.get(f"/api/v1/investigations/{analyst_inv}/report", headers=analyst2_headers).status_code == 404
    assert client.delete(f"/api/v1/investigations/{analyst_inv}", headers=analyst2_headers).status_code == 403
    listed = client.get("/api/v1/investigations", headers=analyst2_headers).json()
    assert all(i["id"] != analyst_inv for i in listed)


def test_admin_only_endpoints(client, analyst_headers, viewer_headers, auditor_headers, admin_headers):
    for h in (analyst_headers, viewer_headers, auditor_headers):
        assert client.get("/api/v1/admin/users", headers=h).status_code == 403
        assert client.post("/api/v1/admin/retention/run", headers=h).status_code == 403
        assert client.get("/api/v1/admin/system", headers=h).status_code == 403
        assert client.get("/api/v1/privacy/requests", headers=h).status_code == 403
    assert client.get("/api/v1/admin/audit", headers=analyst_headers).status_code == 403
    assert client.get("/api/v1/admin/audit", headers=auditor_headers).status_code == 200
    assert client.get("/api/v1/admin/system", headers=admin_headers).status_code == 200


def test_admin_cannot_demote_self(client, admin_headers):
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    r = client.patch(f"/api/v1/admin/users/{me['id']}", json={"role": "viewer"}, headers=admin_headers)
    assert r.status_code == 409


def test_source_min_role_access_control(client, admin_headers, analyst_headers, mocked_collection):
    client.patch("/api/v1/sources/rdap_domain", json={"min_role": "admin"}, headers=admin_headers)
    try:
        r = client.post("/api/v1/investigations", json=DOMAIN_INV, headers=analyst_headers)
        cov = client.get(f"/api/v1/investigations/{r.json()['id']}", headers=analyst_headers).json()["coverage"]
        assert "rdap_domain" not in cov["by_source"]
        r = client.post("/api/v1/investigations", json=DOMAIN_INV, headers=admin_headers)
        cov = client.get(f"/api/v1/investigations/{r.json()['id']}", headers=admin_headers).json()["coverage"]
        assert cov["by_source"]["rdap_domain"] == "ok"
    finally:
        client.patch("/api/v1/sources/rdap_domain", json={"min_role": "analyst"}, headers=admin_headers)
