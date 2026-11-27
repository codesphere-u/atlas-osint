"""v0.2 workflows: assessment, change detection, monitoring, pivots, cases, TLP, STIX, bulk verification."""

import json
from datetime import timedelta

import pytest
import stix2
from atlas_api.db import get_sessionmaker
from atlas_api.models import Investigation
from atlas_api.services.investigations import run_due_monitors

from shared.types import utcnow
from tests.integration.test_api_flow import DOMAIN_INV, USER_INV


@pytest.fixture
def dom_inv(client, analyst_headers, mocked_collection):
    r = client.post("/api/v1/investigations", json={**DOMAIN_INV, "tlp": "green"}, headers=analyst_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_assessment_scorecard_and_risk(client, analyst_headers, dom_inv):
    d = client.get(f"/api/v1/investigations/{dom_inv}", headers=analyst_headers).json()
    assert d["status"] == "completed" and d["tlp"] == "green"
    assert d["posture_grade"] in list("ABCDF") and d["risk_level"] in ("critical", "high", "medium", "low", "none")
    a = client.get(f"/api/v1/investigations/{dom_inv}/assessment", headers=analyst_headers).json()
    checks = {c["id"]: c for c in a["posture"]["checks"]}
    assert checks["EMAIL-DMARC"]["status"] == "pass"  # fixture publishes p=reject
    assert checks["EMAIL-MTASTS"]["status"] == "warn"  # fixture policy is in testing mode
    assert checks["EXPOSURE-PORTS"]["status"] == "fail"  # MySQL exposed in the InternetDB fixture
    assert checks["WEB-SECURITY-TXT"]["status"] == "pass"
    assert any(h["category"] == "exposure" for h in a["risk"])
    assert a["changes"]["baseline"] is True and len(a["run_history"]) == 1
    assert a["monitoring"]["allowed"] is True


def test_rerun_reports_changes(client, analyst_headers, dom_inv, mocked_collection, fake_dns):
    fake_dns.records[("example.com", "CAA")] = ['0 issue "letsencrypt.org"']
    r = client.post(f"/api/v1/investigations/{dom_inv}/run", headers=analyst_headers)
    assert r.status_code == 200
    a = client.get(f"/api/v1/investigations/{dom_inv}/assessment", headers=analyst_headers).json()
    assert a["changes"]["baseline"] is False and a["changes"]["added_count"] >= 1
    assert any("CAA" in x["title"] for x in a["changes"]["added"])
    assert len(a["run_history"]) == 2


def test_monitoring_rules_and_scheduler(client, analyst_headers, dom_inv, mocked_collection):
    r = client.put(f"/api/v1/investigations/{dom_inv}/monitoring", json={"interval_hours": 24}, headers=analyst_headers)
    assert r.status_code == 200 and r.json()["monitor_interval_hours"] == 24 and r.json()["next_run_at"]
    assert (
        client.put(
            f"/api/v1/investigations/{dom_inv}/monitoring", json={"interval_hours": 5}, headers=analyst_headers
        ).status_code
        == 422
    )
    person = client.post("/api/v1/investigations", json=USER_INV, headers=analyst_headers).json()["id"]
    r = client.put(f"/api/v1/investigations/{person}/monitoring", json={"interval_hours": 24}, headers=analyst_headers)
    assert r.status_code == 422 and "individuals" in r.text
    with get_sessionmaker()() as db:
        db.get(Investigation, dom_inv).next_run_at = utcnow() - timedelta(minutes=1)
        db.commit()
        ran = run_due_monitors(db)
    assert dom_inv in ran
    a = client.get(f"/api/v1/investigations/{dom_inv}/assessment", headers=analyst_headers).json()
    assert a["run_history"][-1]["trigger"] == "monitor"
    assert (
        client.put(
            f"/api/v1/investigations/{dom_inv}/monitoring", json={"interval_hours": None}, headers=analyst_headers
        ).json()["monitor_interval_hours"]
        is None
    )


def test_pivot_creates_case_and_child(client, analyst_headers, analyst2_headers, dom_inv, mocked_collection):
    body = {"subject_type": "ip", "subject": "93.184.216.34"}
    r = client.post(f"/api/v1/investigations/{dom_inv}/pivot", json=body, headers=analyst_headers)
    assert r.status_code == 422  # must confirm the pivot is covered by the authorisation
    r = client.post(
        f"/api/v1/investigations/{dom_inv}/pivot",
        json={**body, "covered_by_authorization": True},
        headers=analyst_headers,
    )
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["parent_id"] == dom_inv and child["case_id"] and child["tlp"] == "green"
    assert child["legal_basis"] == "authorized_security_assessment"
    parent = client.get(f"/api/v1/investigations/{dom_inv}", headers=analyst_headers).json()
    assert parent["case_id"] == child["case_id"]
    # pivoting to a person re-applies the consent rules for individuals
    r = client.post(
        f"/api/v1/investigations/{dom_inv}/pivot",
        json={"subject_type": "username", "subject": "octo-sample", "covered_by_authorization": True},
        headers=analyst_headers,
    )
    assert r.status_code == 422 and "consent" in r.text
    # other analysts cannot pivot from someone else's investigation
    assert (
        client.post(
            f"/api/v1/investigations/{dom_inv}/pivot",
            json={**body, "covered_by_authorization": True},
            headers=analyst2_headers,
        ).status_code
        == 403
    )
    # case views merge both investigations
    case_id = child["case_id"]
    case = client.get(f"/api/v1/cases/{case_id}", headers=analyst_headers).json()
    assert case["investigation_count"] == 2
    g = client.get(f"/api/v1/cases/{case_id}/graph", headers=analyst_headers).json()
    assert sum(1 for n in g["nodes"] if n["is_subject"]) == 2
    ip_nodes = [n for n in g["nodes"] if "ip:93.184.216.34" in n["identifiers"]]
    assert len(ip_nodes) == 1  # the IP seen in both investigations is one entity
    tl = client.get(f"/api/v1/cases/{case_id}/timeline", headers=analyst_headers).json()
    assert tl and all(e["investigation_id"] for e in tl)
    exp = client.get(f"/api/v1/cases/{case_id}/export?format=stix", headers=analyst_headers)
    assert exp.status_code == 200
    stix2.parse(exp.content.decode(), allow_custom=False)
    assert client.get(f"/api/v1/cases/{case_id}", headers=analyst2_headers).status_code == 404


def test_case_crud_and_assignment(client, analyst_headers, dom_inv):
    r = client.post(
        "/api/v1/cases",
        json={"title": "Vendor review", "description": "Q4 vendor checks", "tlp": "amber"},
        headers=analyst_headers,
    )
    assert r.status_code == 201
    case_id = r.json()["id"]
    r = client.patch(
        f"/api/v1/investigations/{dom_inv}", json={"case_id": case_id, "tlp": "red"}, headers=analyst_headers
    )
    assert r.json()["case_id"] == case_id and r.json()["tlp"] == "red"
    cases = client.get("/api/v1/cases", headers=analyst_headers).json()
    assert any(c["id"] == case_id and c["investigation_count"] == 1 for c in cases)
    r = client.patch(f"/api/v1/cases/{case_id}", json={"status": "closed"}, headers=analyst_headers)
    assert r.json()["status"] == "closed" and r.json()["description"] == "Q4 vendor checks"
    assert client.delete(f"/api/v1/cases/{case_id}", headers=analyst_headers).status_code == 204
    assert client.get(f"/api/v1/investigations/{dom_inv}", headers=analyst_headers).json()["case_id"] is None


def test_stix_report_export_uses_investigation_tlp(client, analyst_headers, dom_inv):
    r = client.get(f"/api/v1/investigations/{dom_inv}/report?format=stix", headers=analyst_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/stix+json")
    bundle = json.loads(r.content)
    stix2.parse(r.content.decode(), allow_custom=False)
    markings = [o for o in bundle["objects"] if o["type"] == "marking-definition"]
    assert [m["name"] for m in markings] == ["TLP:GREEN"]


def test_reports_include_tlp_and_executive_summary(client, analyst_headers, dom_inv):
    html = client.get(f"/api/v1/investigations/{dom_inv}/report?format=html", headers=analyst_headers).text
    assert "TLP:GREEN" in html and "Executive summary" in html and "Exposure scorecard" in html
    data = json.loads(
        client.get(f"/api/v1/investigations/{dom_inv}/report?format=json", headers=analyst_headers).content
    )
    assert data["tlp"] == "green" and data["posture"]["grade"] and isinstance(data["risk"], list)


def test_bulk_verification(client, analyst_headers, viewer_headers, dom_inv):
    fs = client.get(f"/api/v1/investigations/{dom_inv}/findings", headers=analyst_headers).json()
    ids = [f["id"] for f in fs[:3]]
    r = client.post(
        f"/api/v1/investigations/{dom_inv}/findings/bulk",
        json={"finding_ids": ids, "status": "rejected", "note": "out of scope"},
        headers=analyst_headers,
    )
    assert r.json() == {"updated": 3, "status": "rejected"}
    after = {
        f["id"]: f for f in client.get(f"/api/v1/investigations/{dom_inv}/findings", headers=analyst_headers).json()
    }
    assert all(after[i]["classification"] == "rejected" for i in ids)
    assert (
        client.post(
            f"/api/v1/investigations/{dom_inv}/findings/bulk",
            json={"finding_ids": ["nope"], "status": "verified"},
            headers=analyst_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/investigations/{dom_inv}/findings/bulk",
            json={"finding_ids": ids, "status": "verified"},
            headers=viewer_headers,
        ).status_code
        == 403
    )


def test_stats_include_trends_and_attention(client, analyst_headers, dom_inv):
    s = client.get("/api/v1/investigations/stats", headers=analyst_headers).json()
    assert len(s["by_day"]) == 30 and sum(s["by_day"].values()) >= 1
    assert "risk_levels" in s and "posture_grades" in s and "attention" in s and "recent_changes" in s
