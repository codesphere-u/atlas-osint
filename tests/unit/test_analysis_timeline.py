from datetime import UTC, datetime

from engine.analysis.analyst import build_timeline, deterministic_analysis
from engine.correlation.resolver import resolve
from engine.verification.scoring import score_findings
from tests.unit.helpers import finding


def test_timeline_is_chronological_and_cites_findings():
    a = finding("rdap", attrs={"created": "1995-08-14T04:00:00Z"}, title="Registration")
    b = finding("wayback", attrs={"first_capture": "2002-01-20T14:25:10+00:00"}, title="Archive")
    c = finding("news", published_at=datetime(2026, 3, 1, tzinfo=UTC), title="Article")
    fs = score_findings([c, a, b])
    tl = build_timeline(fs)
    assert [e.date for e in tl] == ["1995-08-14", "2002-01-20", "2026-03-01"]
    assert {e.finding_id for e in tl} == {a.id, b.id, c.id}


def test_deterministic_analysis_separates_buckets_and_reports_gaps():
    strong = finding("github", hint="account:github:octo", kind="account")
    person = finding("openalex", subject=("name", "Ann Bee"), hint="person:openalex:1", kind="person")
    fs = [strong, person]
    corr = resolve(fs, strong.subject)
    score_findings(fs, corr)
    rep = deterministic_analysis(
        strong.subject, fs, corr, {"by_source": {"reddit": "unavailable", "hibp": "not_configured"}}
    )
    assert [s.finding_ids for s in rep.confirmed_facts] == [[strong.id]]
    assert [s.finding_ids for s in rep.possible_matches] == [[person.id]]
    assert any("reddit" in i and "not evidence of absence" in i for i in rep.insufficient_evidence)
    assert any("hibp" in i for i in rep.insufficient_evidence)
    assert all(e.reasons for e in rep.confidence_explanations)


def test_empty_investigation_states_insufficient_evidence():
    f = finding()
    rep = deterministic_analysis(f.subject, [], resolve([], f.subject))
    assert "No source returned information" in rep.insufficient_evidence[0]
