"""Lawful-use controls: authorisation records, consent, scope, opt-outs, retention and deletion."""

from datetime import timedelta

from atlas_api.db import get_sessionmaker
from atlas_api.models import FindingRow, Investigation
from sqlalchemy import select

from shared.types import utcnow
from tests.integration.test_api_flow import DOMAIN_INV, USER_INV


def post(client, headers, **overrides):
    return client.post("/api/v1/investigations", json={**DOMAIN_INV, **overrides}, headers=headers)


def test_attestation_required(client, analyst_headers, mocked_collection):
    r = post(client, analyst_headers, attestation=False)
    assert r.status_code == 422 and "attest" in str(r.json())


def test_security_assessment_needs_reference(client, analyst_headers, mocked_collection):
    r = post(client, analyst_headers, authorization_reference=None)
    assert r.status_code == 422 and "authorisation reference" in str(r.json())


def test_individuals_need_consent_or_self(client, analyst_headers, mocked_collection):
    for basis in ("legitimate_interest", "research", "journalism"):
        r = client.post(
            "/api/v1/investigations",
            json={**USER_INV, "legal_basis": basis, "purpose": "x" * 40},
            headers=analyst_headers,
        )
        assert r.status_code == 422, basis
    r = client.post(
        "/api/v1/investigations",
        json={**USER_INV, "legal_basis": "consent", "consent_obtained": True},
        headers=analyst_headers,
    )
    assert r.status_code == 422  # consent reference missing


def test_active_probe_out_of_scope_is_skipped(client, analyst_headers, mocked_collection):
    r = post(client, analyst_headers, authorized_domains=["other.org"])
    cov = client.get(f"/api/v1/investigations/{r.json()['id']}", headers=analyst_headers).json()["coverage"]
    assert cov["by_source"]["http_security"] == "skipped"
    run = next(x for x in cov["runs"] if x["source"] == "http_security")
    assert "authorised scope" in run["message"]


def test_opt_out_blocks_future_investigations(client, admin_headers, analyst_headers, mocked_collection):
    r = client.post(
        "/api/v1/privacy/requests",
        json={
            "kind": "opt_out",
            "identifier_type": "username",
            "identifier": "opted-out-user",
            "contact_email": "me@atlas-osint-test.com",
        },
    )
    assert r.status_code == 202
    req_id = r.json()["id"]
    pending = client.get("/api/v1/privacy/requests?status=pending", headers=admin_headers).json()
    assert any(p["id"] == req_id and p["identifier"] == "opted-out-user" for p in pending)
    r = client.post(f"/api/v1/privacy/requests/{req_id}/resolve", json={"status": "approved"}, headers=admin_headers)
    assert r.json()["effects"]["suppressed"] is True
    r = client.post("/api/v1/investigations", json={**USER_INV, "subject": "Opted-Out-User"}, headers=analyst_headers)
    assert r.status_code == 451


def test_opt_out_suppresses_linked_accounts_in_other_investigations(
    client, admin_headers, analyst_headers, mocked_collection
):
    r = client.post(
        "/api/v1/privacy/requests",
        json={"kind": "opt_out", "identifier_type": "domain", "identifier": "octo.example.org"},
    )
    client.post(
        f"/api/v1/privacy/requests/{r.json()['id']}/resolve", json={"status": "approved"}, headers=admin_headers
    )
    r = client.post("/api/v1/investigations", json=USER_INV, headers=analyst_headers)
    inv_id = r.json()["id"]
    findings = client.get(f"/api/v1/investigations/{inv_id}/findings", headers=analyst_headers).json()
    assert "octo.example.org" not in str([f["linked"] for f in findings])
    detail = client.get(f"/api/v1/investigations/{inv_id}", headers=analyst_headers).json()
    assert detail["coverage"]["suppressed_items"] >= 1


def test_deletion_request_purges_data(client, admin_headers, analyst_headers, mocked_collection):
    body = {**USER_INV, "subject": "delete-me"}
    inv_id = client.post("/api/v1/investigations", json=body, headers=analyst_headers).json()["id"]
    r = client.post(
        "/api/v1/privacy/requests", json={"kind": "deletion", "identifier_type": "username", "identifier": "delete-me"}
    )
    res = client.post(
        f"/api/v1/privacy/requests/{r.json()['id']}/resolve", json={"status": "approved"}, headers=admin_headers
    ).json()
    assert res["effects"]["investigations_deleted"] == 1
    assert client.get(f"/api/v1/investigations/{inv_id}", headers=analyst_headers).status_code == 404
    with get_sessionmaker()() as db:
        assert db.scalars(select(FindingRow).where(FindingRow.investigation_id == inv_id)).all() == []


def test_retention_purge(client, admin_headers, analyst_headers, mocked_collection):
    inv_id = post(client, analyst_headers, retention_days=1).json()["id"]
    with get_sessionmaker()() as db:
        inv = db.get(Investigation, inv_id)
        assert inv.retention_until <= (utcnow() + timedelta(days=1, minutes=1)).replace(tzinfo=None)
        inv.retention_until = utcnow() - timedelta(days=1)
        db.commit()
    r = client.post("/api/v1/admin/retention/run", headers=admin_headers)
    assert r.json()["removed"] >= 1
    assert client.get(f"/api/v1/investigations/{inv_id}", headers=analyst_headers).status_code == 404


def test_retention_is_capped(client, analyst_headers, mocked_collection):
    inv = post(client, analyst_headers, retention_days=3000).json()
    from datetime import datetime

    until = datetime.fromisoformat(inv["retention_until"])
    assert (until.replace(tzinfo=None) - utcnow().replace(tzinfo=None)).days <= 365
