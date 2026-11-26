"""End-to-end API workflow with mocked sources."""

import json

import pytest

DOMAIN_INV = {
    "title": "Example.com infrastructure review",
    "subject_type": "domain",
    "subject": "Example.COM",
    "purpose": "Authorised external attack-surface review of our own domain.",
    "legal_basis": "authorized_security_assessment",
    "authorization_reference": "ENG-2026-001",
    "authorized_domains": ["example.com"],
    "attestation": True,
}

USER_INV = {
    "title": "Self check of my handle",
    "subject_type": "username",
    "subject": "octo-sample",
    "purpose": "I am reviewing my own public footprint.",
    "legal_basis": "self",
    "attestation": True,
}


@pytest.fixture
def domain_investigation(client, analyst_headers, mocked_collection):
    r = client.post("/api/v1/investigations", json=DOMAIN_INV, headers=analyst_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_domain_investigation_end_to_end(client, analyst_headers, domain_investigation):
    inv_id = domain_investigation
    d = client.get(f"/api/v1/investigations/{inv_id}", headers=analyst_headers).json()
    assert d["status"] == "completed", d.get("error")
    assert d["subject"] == "example.com"
    cov = d["coverage"]
    assert cov["by_source"]["dns_records"] == "ok"
    assert cov["by_source"]["rdap_domain"] == "ok"
    assert cov["by_source"]["http_security"] == "ok"  # in authorised scope
    assert d["module_summary"]["registrar"].startswith("RESERVED")
    assert d["module_summary"]["subdomains"] == 3

    prog = client.get(f"/api/v1/investigations/{inv_id}/progress", headers=analyst_headers).json()
    assert prog["progress"]["done"] == prog["progress"]["total"] > 0

    findings = client.get(f"/api/v1/investigations/{inv_id}/findings", headers=analyst_headers).json()
    assert findings and all(f["source_url"] and f["collected_at"] and f["confidence"] for f in findings)
    assert all(f["classification"] in ("confirmed", "possible", "unverified") for f in findings)
    confirmed = client.get(
        f"/api/v1/investigations/{inv_id}/findings?classification=confirmed", headers=analyst_headers
    ).json()
    assert confirmed and all(f["classification"] == "confirmed" for f in confirmed)
    searched = client.get(f"/api/v1/investigations/{inv_id}/findings?q=subdomain", headers=analyst_headers).json()
    assert searched and all("ubdomain" in f["title"] + f["description"] for f in searched)

    graph = client.get(f"/api/v1/investigations/{inv_id}/graph", headers=analyst_headers).json()
    assert any(n["is_subject"] for n in graph["nodes"]) and graph["edges"]
    node_ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source_entity_id"] in node_ids and e["target_entity_id"] in node_ids for e in graph["edges"])

    timeline = client.get(f"/api/v1/investigations/{inv_id}/timeline", headers=analyst_headers).json()
    dates = [e["date"] for e in timeline]
    assert dates == sorted(dates) and "1995-08-14" in dates

    analysis = client.get(f"/api/v1/investigations/{inv_id}/analysis", headers=analyst_headers).json()
    assert analysis["provider"] == "deterministic" and analysis["confidence_explanations"]


def test_verification_rescoring_and_notes(client, analyst_headers, domain_investigation):
    inv_id = domain_investigation
    findings = client.get(f"/api/v1/investigations/{inv_id}/findings", headers=analyst_headers).json()
    target = findings[-1]
    r = client.patch(
        f"/api/v1/investigations/{inv_id}/findings/{target['id']}",
        headers=analyst_headers,
        json={"status": "rejected", "note": "False positive after manual review"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["classification"] == "rejected" and r.json()["confidence"]["score"] == 0
    notes = client.get(f"/api/v1/investigations/{inv_id}/notes", headers=analyst_headers).json()
    assert notes[0]["body"] == "False positive after manual review" and notes[0]["finding_id"] == target["id"]
    r = client.post(f"/api/v1/investigations/{inv_id}/notes", headers=analyst_headers, json={"body": "Done."})
    assert r.status_code == 201
    r = client.patch(
        f"/api/v1/investigations/{inv_id}/findings/{target['id']}", headers=analyst_headers, json={"status": "verified"}
    )
    assert r.json()["classification"] == "confirmed"


@pytest.mark.parametrize(
    "fmt,ctype,magic",
    [
        ("json", "application/json", b"{"),
        ("csv", "text/csv", b"\xef\xbb\xbf"),
        ("html", "text/html", b"<!doctype"),
        ("pdf", "application/pdf", b"%PDF-"),
    ],
)
def test_report_exports(client, analyst_headers, domain_investigation, fmt, ctype, magic):
    r = client.get(f"/api/v1/investigations/{domain_investigation}/report?format={fmt}", headers=analyst_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(ctype)
    assert r.content.startswith(magic)
    assert "attachment" in r.headers["content-disposition"]
    if fmt == "json":
        data = json.loads(r.content)
        assert data["investigation"]["legal_basis"] == "authorized_security_assessment"
        assert data["coverage"]["runs"] and data["methodology"] and data["limitations"]


def test_username_self_investigation_with_privacy_filtering(client, analyst_headers, mocked_collection):
    r = client.post("/api/v1/investigations", json=USER_INV, headers=analyst_headers)
    assert r.status_code == 201, r.text
    inv_id = r.json()["id"]
    d = client.get(f"/api/v1/investigations/{inv_id}", headers=analyst_headers).json()
    assert d["status"] == "completed", d.get("error")
    assert set(d["module_summary"]["exact_platforms"]) == {"github", "devto", "keybase"}
    assert d["coverage"]["by_source"]["reddit"] == "unavailable"
    findings = client.get(f"/api/v1/investigations/{inv_id}/findings", headers=analyst_headers).json()
    blob = json.dumps(findings)
    assert "+1 415 555 0199" not in blob  # phone number in bio redacted
    assert "Exact Street" not in blob and "octo@private.example" not in blob
    gh = next(f for f in findings if f["source_name"] == "github")
    assert "location" not in gh["attributes"]
    analysis = client.get(f"/api/v1/investigations/{inv_id}/analysis", headers=analyst_headers).json()
    assert gh["id"] in analysis["injection_flags"]  # prompt-injection text in bio is flagged
    graph = client.get(f"/api/v1/investigations/{inv_id}/graph", headers=analyst_headers).json()
    edge_types = {e["type"] for e in graph["edges"]}
    # DEV and Keybase profiles reference the GitHub account; GitHub and DEV list the same website
    assert {"claims_account", "cryptographic_proof", "shares_website_with"} <= edge_types


def test_name_investigation_requires_consent_and_flags_collisions(client, analyst_headers, mocked_collection):
    body = {
        "title": "Due diligence",
        "subject_type": "name",
        "subject": "Maria Example",
        "purpose": "Background research on a speaker.",
        "legal_basis": "legitimate_interest",
        "attestation": True,
    }
    r = client.post("/api/v1/investigations", json=body, headers=analyst_headers)
    assert r.status_code == 422 and "consent" in json.dumps(r.json())
    body.update(legal_basis="consent", consent_obtained=True, consent_reference="CONSENT-42")
    r = client.post("/api/v1/investigations", json=body, headers=analyst_headers)
    assert r.status_code == 201, r.text
    inv_id = r.json()["id"]
    d = client.get(f"/api/v1/investigations/{inv_id}", headers=analyst_headers).json()
    assert d["status"] == "completed", d.get("error")
    assert d["module_summary"]["name_collision"] is True
    graph = client.get(f"/api/v1/investigations/{inv_id}/graph", headers=analyst_headers).json()
    people = [n for n in graph["nodes"] if n["kind"] == "person"]
    # OpenAlex+ORCID+Wikidata records sharing ORCID merge; the other namesakes stay separate
    merged = [p for p in people if len(p["finding_ids"]) >= 3]
    assert len(merged) == 1 and len(people) >= 3
    assert graph["name_collisions"]
    findings = client.get(f"/api/v1/investigations/{inv_id}/findings", headers=analyst_headers).json()
    assert not any(f["classification"] == "confirmed" for f in findings if f["entity_kind"] == "person")


def test_list_search_stats_and_delete(client, analyst_headers, domain_investigation):
    r = client.get("/api/v1/investigations?q=example.com", headers=analyst_headers)
    assert any(i["id"] == domain_investigation for i in r.json())
    assert int(r.headers["X-Total-Count"]) >= 1
    r = client.get("/api/v1/investigations?subject_type=domain&status=completed", headers=analyst_headers)
    assert all(i["subject_type"] == "domain" for i in r.json())
    stats = client.get("/api/v1/investigations/stats", headers=analyst_headers).json()
    assert stats["investigations"] >= 1 and "dns_records" in stats["source_status"]
    assert client.delete(f"/api/v1/investigations/{domain_investigation}", headers=analyst_headers).status_code == 204
    assert client.get(f"/api/v1/investigations/{domain_investigation}", headers=analyst_headers).status_code == 404


def test_audit_trail_records_actions_without_identifiers(client, admin_headers, analyst_headers, mocked_collection):
    r = client.post("/api/v1/investigations", json=DOMAIN_INV, headers=analyst_headers)
    inv_id = r.json()["id"]
    client.get(f"/api/v1/investigations/{inv_id}/report?format=json", headers=analyst_headers)
    logs = client.get("/api/v1/admin/audit?limit=500", headers=admin_headers).json()
    actions = {entry["action"] for entry in logs if entry["target_id"] == inv_id}
    assert {"investigation.create", "investigation.completed", "report.export"} <= actions
    assert "example.com" not in json.dumps(logs)


def test_sources_listing_and_admin_toggle(client, admin_headers, analyst_headers):
    srcs = client.get("/api/v1/sources", headers=analyst_headers).json()
    names = {s["name"] for s in srcs}
    assert {"github", "rdap_domain", "libphonenumber", "gleif"} <= names
    hibp = next(s for s in srcs if s["name"] == "hibp")
    assert hibp["configured"] is False and hibp["legal"]["requires_subject_consent"] is True
    assert client.patch("/api/v1/sources/github", json={"enabled": False}, headers=analyst_headers).status_code == 403
    r = client.patch("/api/v1/sources/github", json={"enabled": False, "min_role": "admin"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = client.patch("/api/v1/sources/github", json={"enabled": True, "min_role": "analyst"}, headers=admin_headers)
    assert r.json()["enabled"] is True
    cov = client.get("/api/v1/sources/coverage", headers=analyst_headers).json()["matrix"]
    assert any(row["source"] == "github" for row in cov["username"])


def test_disabled_source_is_not_queried(client, admin_headers, analyst_headers, mocked_collection):
    client.patch("/api/v1/sources/wayback", json={"enabled": False}, headers=admin_headers)
    try:
        r = client.post("/api/v1/investigations", json=DOMAIN_INV, headers=analyst_headers)
        d = client.get(f"/api/v1/investigations/{r.json()['id']}", headers=analyst_headers).json()
        assert "wayback" not in d["coverage"]["by_source"]
        assert "wayback" in d["coverage"]["sources_disabled"]
    finally:
        client.patch("/api/v1/sources/wayback", json={"enabled": True}, headers=admin_headers)


def test_meta_and_health(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"
    meta = client.get("/api/v1/meta").json()
    assert len(meta["modules"]) == 6 and "consent" in meta["legal_bases"]


def test_regenerate_analysis_without_provider(client, analyst_headers, domain_investigation):
    r = client.post(f"/api/v1/investigations/{domain_investigation}/analysis?use_ai=true", headers=analyst_headers)
    assert r.status_code == 200
    assert any("No AI provider configured" in n for n in r.json()["validation_notes"])
