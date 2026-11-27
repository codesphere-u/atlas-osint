"""Report renderers: JSON, CSV, HTML and PDF."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from engine.reporting.model import ReportData
from engine.verification.scoring import classify

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def render_json(report: ReportData) -> bytes:
    payload = report.model_dump(mode="json")
    payload["format"] = "atlas-osint-report/1"
    payload["summary_counts"] = {
        "verified": len(report.verified),
        "possible": len(report.possible),
        "unverified": len(report.unverified),
        "contradictions": len(report.correlation.contradictions),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode()


CSV_COLUMNS = [
    "finding_id",
    "classification",
    "confidence",
    "confidence_level",
    "verification_status",
    "module",
    "finding_type",
    "title",
    "description",
    "source_name",
    "source_url",
    "reliability",
    "match_type",
    "evidence_kind",
    "collected_at",
    "published_at",
    "evidence_excerpt",
    "content_sha256",
    "citation",
]


def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection (CWE-1236)."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def render_csv(report: ReportData) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)
    for f in report.findings:
        writer.writerow(
            [
                _csv_safe(v)
                for v in [
                    f.id,
                    classify(f),
                    f.confidence.score if f.confidence else "",
                    f.confidence.level.value if f.confidence else "",
                    f.verification_status.value,
                    f.module,
                    f.finding_type,
                    f.title,
                    f.description,
                    f.source_display_name,
                    f.source_url,
                    f.reliability.value,
                    f.match_type.value,
                    f.evidence_kind.value,
                    f.collected_at.isoformat(),
                    f.published_at.isoformat() if f.published_at else "",
                    f.evidence.excerpt or "",
                    f.evidence.content_hash or "",
                    f.citation or "",
                ]
            ]
        )
    return ("﻿" + buf.getvalue()).encode("utf-8")


def render_html(report: ReportData) -> bytes:
    template = _env.get_template("report.html")
    entities = {e.id: e for e in report.correlation.entities}
    html = template.render(r=report, classify=classify, entities=entities)
    return html.encode()


def _latin1(text: object) -> str:
    s = "" if text is None else str(text)
    replacements = {
        "—": "-",
        "–": "-",
        "→": "->",
        "…": "...",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "≥": ">=",
        "≤": "<=",
        "−": "-",
        "•": "*",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return s.encode("latin-1", errors="replace").decode("latin-1")


def render_pdf(report: ReportData) -> bytes:
    from fpdf import FPDF

    inv = report.investigation
    tlp_colors = {
        "clear": (255, 255, 255),
        "green": (51, 255, 0),
        "amber": (255, 192, 0),
        "amber+strict": (255, 192, 0),
        "red": (255, 43, 43),
    }
    tlp_label = report.tlp_label

    class MarkedPDF(FPDF):
        """Every page carries the TLP marking in its header and footer (FIRST TLP 2.0 guidance)."""

        def _marking(self, y: float) -> None:
            self.set_xy(self.l_margin, y)
            self.set_font("Helvetica", "B", 8)
            self.set_fill_color(0, 0, 0)
            self.set_text_color(*tlp_colors.get(report.tlp, (255, 192, 0)))
            self.cell(self.get_string_width(tlp_label) + 6, 5, tlp_label, fill=True)
            self.set_text_color(0, 0, 0)

        def header(self) -> None:
            self._marking(8)
            self.set_y(16)

        def footer(self) -> None:
            self._marking(-12)
            self.set_font("Helvetica", "", 7)
            self.set_xy(-30, -12)
            self.cell(20, 5, f"Page {self.page_no()}", align="R")

    pdf = MarkedPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(_latin1(f"ATLAS OSINT report {report.report_id}"))
    pdf.set_creator("ATLAS OSINT")
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def h(text: str, size: int = 13) -> None:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", size)
        pdf.multi_cell(width, 7, _latin1(text))
        pdf.set_font("Helvetica", "", 9)

    def p(text: str, size: int = 9) -> None:
        pdf.set_font("Helvetica", "", size)
        pdf.multi_cell(width, 4.8, _latin1(text))

    h("ATLAS OSINT - Intelligence Report", 17)
    p(f"Report {report.report_id} - generated {report.generated_at:%Y-%m-%d %H:%M UTC} by {report.generated_by}")
    p("Open-source intelligence. Connected evidence. Verifiable insights.")
    h("Executive summary")
    posture = report.posture or {}
    if posture.get("grade"):
        p(
            f"Exposure grade: {posture['grade']} ({posture.get('score')}/100, "
            f"{posture.get('evaluated')} checks evaluated)"
        )
    p(
        f"Findings: {len(report.findings)} ({len(report.verified)} confirmed, {len(report.possible)} possible). "
        f"Risk highlights: {len(report.risk)}."
    )
    ch = report.changes or {}
    if ch and not ch.get("baseline"):
        p(f"Changes since the previous run: +{ch.get('added_count', 0)} added, -{ch.get('removed_count', 0)} removed.")
    for hl in report.risk[:12]:
        p(
            f"* [{str(hl.get('severity', '')).upper()}] {hl.get('title')} - {hl.get('detail')}"
            + ("" if hl.get("confirmed") else " (requires confirmation)")
        )
    if not report.risk:
        p("No risk highlights were derived from the evidence.")
    h("1. Investigation scope")
    for label, key in (
        ("Title", "title"),
        ("Subject", "subject_display"),
        ("Subject kind", "subject_kind"),
        ("Purpose", "purpose"),
        ("Legal basis", "legal_basis"),
        ("Authorisation reference", "authorization_reference"),
        ("Authorised domains", "authorized_domains"),
    ):
        p(f"{label}: {inv.get(key) or '-'}")
    h("2. Collection period")
    p(f"Started: {inv.get('collection_started_at') or '-'}   Finished: {inv.get('collection_finished_at') or '-'}")
    h("3. Summary")
    if report.analysis:
        p(report.analysis.summary)
        if report.analysis.ai_generated:
            p(f"[AI narrative by {report.analysis.provider}/{report.analysis.model}; analyst review required]")
    h("4. Verified findings")
    for f in report.verified or []:
        p(f"* [{(f.confidence.score if f.confidence else 0):.2f}] {f.title} - {f.description}")
        p(f"    Source: {f.source_display_name} - {f.source_url} (collected {f.collected_at:%Y-%m-%d})", 8)
    if not report.verified:
        p("None.")
    h("5. Possible matches")
    for f in report.possible or []:
        p(f"* [{(f.confidence.score if f.confidence else 0):.2f}] {f.title} - {f.description}")
        p(f"    Source: {f.source_display_name} - {f.source_url}", 8)
    if not report.possible:
        p("None.")
    h("6. Contradictions and name collisions")
    for c in report.correlation.contradictions:
        p(f"* {c.explanation}")
    for nc in report.correlation.name_collisions:
        p(f"* {nc.explanation}")
    if not report.correlation.contradictions and not report.correlation.name_collisions:
        p("None detected.")
    if posture.get("checks"):
        h("Exposure scorecard")
        for c in posture["checks"]:
            p(
                f"* {str(c['status']).upper():7} {c['title']} [{c['severity']}] - {c['detail']}"
                + (f" -> {c['recommendation']}" if c.get("recommendation") else ""),
                8,
            )
    h("7. Sources consulted")
    for run in report.coverage.get("runs", []):
        p(
            f"* {run['display_name']} [{run['status']}] {run['findings']} findings"
            + (f" - {run['message']}" if run.get("message") else ""),
            8,
        )
    h("8. Confidence methodology")
    for m in report.methodology:
        p(f"* {m}", 8)
    h("9. Coverage limitations")
    for lim in report.limitations:
        p(f"* {lim}", 8)
    h("10. Analyst notes")
    for n in report.analyst_notes:
        p(f"* {n.get('created_at', '')} {n.get('author', '')}: {n.get('body', '')}")
    if not report.analyst_notes:
        p("None.")
    out = pdf.output()
    return bytes(out)


RENDERERS = {
    "json": (render_json, "application/json", "json"),
    "csv": (render_csv, "text/csv; charset=utf-8", "csv"),
    "html": (render_html, "text/html; charset=utf-8", "html"),
    "pdf": (render_pdf, "application/pdf", "pdf"),
}
