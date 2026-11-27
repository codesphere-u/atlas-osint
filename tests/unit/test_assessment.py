"""Exposure scorecard, risk highlights, change detection and STIX export."""

import json
from datetime import UTC, datetime

import stix2

from engine.assessment.posture import assess_posture
from engine.assessment.risk import risk_highlights
from engine.changes import diff, snapshot
from engine.correlation.resolver import resolve
from engine.reporting.stix import TLP_MARKINGS, build_stix_bundle, sco_id
from engine.verification.scoring import score_findings
from shared.types import Reliability, VerificationStatus
from tests.unit.helpers import finding

NOW = datetime(2026, 11, 27, tzinfo=UTC)


def dom(ftype, attrs, flags=None, **kw):
    return finding(
        "src-" + ftype,
        subject=("domain", "example.com"),
        ftype=ftype,
        hint="domain:example.com",
        kind="domain",
        attrs=attrs,
        flags=flags,
        reliability=Reliability.A,
        **kw,
    )


def strong_email():
    return dom(
        "email_security_posture",
        {
            "mail_enabled": True,
            "spf": "v=spf1 -all",
            "spf_all": "-all",
            "dmarc": "v=DMARC1; p=reject",
            "dmarc_policy": "reject",
            "dmarc_rua": True,
            "mta_sts": True,
            "mta_sts_mode": "enforce",
            "tls_rpt": True,
            "dnssec": True,
            "dkim_selectors_found": ["selector1"],
        },
    )


def checks_by_id(report):
    return {c.id: c for c in report.checks}


def test_strong_configuration_scores_a():
    fs = score_findings(
        [
            strong_email(),
            dom(
                "web_security_posture",
                {
                    "https_redirect": True,
                    "final_url": "https://example.com/",
                    "security_headers_present": [
                        "CSP",
                        "HSTS",
                        "X-Content-Type-Options",
                        "X-Frame-Options",
                        "Referrer-Policy",
                    ],
                },
            ),
            dom("domain_registration", {"expires": "2030-01-01T00:00:00Z", "status": ["client transfer prohibited"]}),
            dom("internet_exposure", {"open_ports": [80, 443], "risky_ports": [], "vuln_count": 0}),
        ]
    )
    r = assess_posture(fs, now=NOW)
    assert r.grade == "A" and r.score == 100
    assert all(c.recommendation is None for c in r.checks if c.status == "pass")


def test_weak_configuration_fails_with_explanations():
    fs = score_findings(
        [
            dom(
                "email_security_posture",
                {
                    "mail_enabled": True,
                    "spf": "v=spf1 +all",
                    "spf_all": "+all",
                    "dmarc": None,
                    "dmarc_policy": None,
                    "mta_sts": False,
                    "tls_rpt": False,
                    "dnssec": False,
                    "dkim_selectors_found": [],
                },
            ),
            dom("internet_exposure", {"open_ports": [22, 3306], "risky_ports": ["3306/MySQL"], "vuln_count": 4}),
            dom("domain_registration", {"expires": "2026-12-10T00:00:00Z", "status": []}),
        ]
    )
    r = assess_posture(fs, now=NOW)
    c = checks_by_id(r)
    assert c["EMAIL-SPF"].status == "fail" and c["EMAIL-DMARC"].status == "fail"
    assert c["EXPOSURE-PORTS"].status == "fail" and "3306/MySQL" in c["EXPOSURE-PORTS"].detail
    assert c["REG-EXPIRY"].status == "fail"
    assert c["EMAIL-DKIM"].status == "unknown"  # cannot enumerate custom selectors
    assert r.grade == "F" and all(ch.recommendation for ch in r.checks if ch.status in ("fail", "warn"))
    assert all(ch.finding_ids for ch in r.checks)


def test_soft_fail_spf_depends_on_dmarc():
    base = {"mail_enabled": True, "spf": "v=spf1 ~all", "spf_all": "~all", "dmarc_rua": True}
    ok = assess_posture(score_findings([dom("email_security_posture", {**base, "dmarc_policy": "reject"})]), NOW)
    weak = assess_posture(score_findings([dom("email_security_posture", {**base, "dmarc_policy": "none"})]), NOW)
    assert checks_by_id(ok)["EMAIL-SPF"].status == "pass"
    assert checks_by_id(weak)["EMAIL-SPF"].status == "warn" and checks_by_id(weak)["EMAIL-DMARC"].status == "warn"


def test_no_grade_without_enough_evidence_and_rejected_findings_ignored():
    r = assess_posture(score_findings([dom("security_txt", {"present": False})]), NOW)
    assert r.score is None and r.grade is None and r.evaluated == 1
    rejected = dom(
        "internet_exposure",
        {"risky_ports": ["3389/RDP"], "vuln_count": 0},
        verification_status=VerificationStatus.REJECTED,
    )
    assert assess_posture(score_findings([rejected]), NOW).checks == []


def test_risk_highlights_order_and_confirmation():
    hit = finding(
        "opensanctions",
        subject=("organization", "Example Corp"),
        ftype="sanctions_screening_hit",
        kind="organization",
        flags=["risk:sanction"],
        title="Screening hit: Example Corp",
    )
    exp = dom(
        "internet_exposure",
        {"risky_ports": ["3389/RDP"], "vuln_count": 2},
        flags=["risk:exposed_service", "risk:potential_vulnerabilities"],
    )
    breach = finding(
        "hibp",
        subject=("email", "a@example.com"),
        ftype="breach_notification",
        attrs={"breach_name": "SyntheticBreach"},
    )
    fs = score_findings([hit, exp, breach])
    hs = risk_highlights(fs)
    assert [h.severity for h in hs] == sorted([h.severity for h in hs], key=["critical", "high", "medium", "low"].index)
    assert hs[0].severity == "critical" and hs[0].finding_ids == [hit.id]
    assert any(h.category == "breach" for h in hs)


def test_change_detection():
    a = dom("subdomain", {"subdomain": "a.example.com"}, claim="domain.subdomain:a.example.com")
    b = dom("subdomain", {"subdomain": "b.example.com"}, claim="domain.subdomain:b.example.com")
    c = dom(
        "subdomain", {"subdomain": "c.example.com"}, claim="domain.subdomain:c.example.com", flags=["risk:lookalike"]
    )
    first = diff(None, [a, b], None)
    assert first["baseline"] is True
    second = diff(snapshot([a, b]), [b, c], "2026-11-26T00:00:00")
    assert second["added_count"] == 1 and second["added"][0]["flags"] == ["risk:lookalike"]
    assert second["removed_count"] == 1 and second["removed"][0]["title"] == a.title
    assert second["unchanged_count"] == 1


def test_stix_bundle_is_valid_and_deterministic():
    gh = finding(
        "github",
        hint="account:github:octo",
        kind="account",
        attrs={"display_name": "Octo"},
        linked=[("domain", "octo.example.org", "lists_website_domain")],
    )
    org = finding(
        "gleif",
        subject=("organization", "Example Corp"),
        hint="organization:lei:5493001KJTIIGC8Y1R12",
        kind="organization",
        attrs={"legal_name": "Example Corp"},
    )
    dns = finding(
        "dns",
        subject=("domain", "example.com"),
        hint="domain:example.com",
        kind="domain",
        linked=[("ip", "93.184.216.34", "resolves_to")],
    )
    rej = finding("devto", hint="account:devto:octo1", kind="account", verification_status=VerificationStatus.REJECTED)
    fs = [gh, org, dns, rej]
    corr = resolve(fs, gh.subject, [org.subject, dns.subject])
    score_findings(fs, corr)
    inv = {
        "id": "inv1",
        "title": "T",
        "subject_type": "username",
        "legal_basis": "self",
        "purpose": "p",
        "finished_at": "2026-11-27T10:00:00+00:00",
    }
    bundle = build_stix_bundle(investigation=inv, findings=fs, correlation=corr, tlp="amber+strict")
    parsed = stix2.parse(json.dumps(bundle), allow_custom=False)  # strict validation by the OASIS library
    ids = {o.id for o in parsed.objects}
    for o in bundle["objects"]:
        for ref in [*o.get("object_refs", []), o.get("source_ref"), o.get("target_ref")]:
            assert ref is None or ref in ids  # no dangling references
        if o["type"] != "marking-definition" and o.get("identity_class") != "system":  # producer is unmarked
            assert o["object_marking_refs"] == [TLP_MARKINGS["amber+strict"]["id"]]
    notes = [o for o in bundle["objects"] if o["type"] == "note"]
    assert len(notes) == 3 and all(rej.id not in n["content"] for n in notes)  # rejected findings excluded
    # Observable ids match the reference implementation's deterministic ids
    assert sco_id("domain-name", {"value": "example.com"}) == stix2.DomainName(value="example.com").id
    assert sco_id("ipv4-addr", {"value": "93.184.216.34"}) == stix2.IPv4Address(value="93.184.216.34").id
    assert (
        sco_id("user-account", {"account_type": "github", "account_login": "octo"})
        == stix2.UserAccount(account_type="github", account_login="octo").id
    )
