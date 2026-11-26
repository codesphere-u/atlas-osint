import csv
import io
import json

from engine.analysis.analyst import deterministic_analysis
from engine.correlation.resolver import resolve
from engine.reporting.model import ReportData, build_limitations
from engine.reporting.renderers import render_csv, render_html, render_json, render_pdf
from engine.verification.scoring import score_findings
from tests.unit.helpers import finding

REQUIRED_SECTIONS = [
    "Investigation scope",
    "Collection period",
    "Verified findings",
    "Possible matches",
    "Contradictions",
    "Sources consulted",
    "Confidence methodology",
    "Coverage limitations",
    "Analyst notes",
]


def sample_report():
    fs = [
        finding("github", hint="account:github:octo", kind="account", title="<script>alert(1)</script>"),
        finding(
            "devto",
            hint="account:devto:octo",
            kind="account",
            title='=HYPERLINK("http://evil")',
            match=__import__("shared.types", fromlist=["MatchType"]).MatchType.SIMILAR,
        ),
    ]
    corr = resolve(fs, fs[0].subject)
    score_findings(fs, corr)
    coverage = {
        "by_source": {"github": "ok", "reddit": "unavailable"},
        "sources_consulted": 2,
        "sources_answered": 1,
        "runs": [
            {"display_name": "GitHub", "identifier": "username:octo", "status": "ok", "findings": 1, "message": None}
        ],
    }
    return ReportData(
        report_id="r1",
        generated_by="analyst@atlas-osint-test.com",
        investigation={
            "title": "T",
            "subject_display": "username: octo",
            "subject_kind": "individual",
            "purpose": "Consent-based self check",
            "legal_basis": "consent",
            "collection_started_at": "2026-01-01T00:00:00",
            "collection_finished_at": "2026-01-01T00:01:00",
        },
        findings=fs,
        correlation=corr,
        coverage=coverage,
        analysis=deterministic_analysis(fs[0].subject, fs, corr, coverage),
        analyst_notes=[{"created_at": "2026-01-01", "author": "a", "body": "checked"}],
        limitations=build_limitations(coverage),
    )


def test_json_report_contains_all_sections():
    data = json.loads(render_json(sample_report()))
    for key in (
        "investigation",
        "findings",
        "correlation",
        "coverage",
        "analysis",
        "methodology",
        "limitations",
        "analyst_notes",
    ):
        assert key in data
    assert data["summary_counts"]["verified"] == 1
    assert any("reddit" in lim for lim in data["limitations"])


def test_csv_report_neutralises_formula_injection():
    rows = list(csv.reader(io.StringIO(render_csv(sample_report()).decode("utf-8-sig"))))
    titles = [r[7] for r in rows[1:]]
    assert '\'=HYPERLINK("http://evil")' in titles


def test_html_report_escapes_content_and_has_sections():
    html = render_html(sample_report()).decode()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    for section in REQUIRED_SECTIONS:
        assert section in html
    assert "Content-Security-Policy" in html


def test_pdf_report_renders():
    pdf = render_pdf(sample_report())
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1500
