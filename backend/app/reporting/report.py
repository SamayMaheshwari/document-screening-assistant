"""Case report PDF (reportlab). Role-based redaction is applied before this is called."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STATUS_COLORS = {"PASS": "#15803d", "FAIL": "#b91c1c", "REVIEW": "#b45309", "INCONCLUSIVE": "#6d28d9",
                 "UNAVAILABLE": "#475569", "NOT_APPLICABLE": "#64748b", "INFO": "#0369a1"}
NAVY = colors.HexColor("#14264f")


def _esc(s) -> str:
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(results: dict, audit_rows: list[dict], viewer: str, image_png: bytes | None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Case report {results['case']['case_number']}", author="Document Screening Assistant (demo)")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, textColor=colors.HexColor("#475569"))
    c = results["case"]
    story = [Paragraph("Document Screening Assistant - Case Report", h1),
             Paragraph("<b>DEMO - SYNTHETIC DATA.</b> Decision-support document. It lists evidence and review needs; it is not a finding of fraud and "
                       "no automatic decision was made.", small), Spacer(1, 4 * mm)]
    meta = [["Case number", c["case_number"], "Status", c["status"]],
            ["Document", c.get("document_type") or "-", "Review priority", c.get("priority") or "-"],
            ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "Generated for", viewer],
            ["Holder", c.get("holder") or "-", "PII", "REDACTED for this role" if results["pii_redacted"] else "visible to this role"]]
    t = Table(meta, colWidths=[28 * mm, 62 * mm, 28 * mm, 56 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f9")),
                           ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef2f9")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                           ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold")]))
    story += [t]
    if image_png:
        story += [Spacer(1, 3 * mm), Image(io.BytesIO(image_png), width=100 * mm, height=100 * mm * 880 / 1250)]

    r = results.get("risk")
    story.append(Paragraph("1. Evidence summary", h2))
    if r:
        dims = [[d["label"], d["level"], f"pass {d['counts']['pass']} / fail {d['counts']['fail']} / review {d['counts']['review']} / unresolved {d['counts']['unresolved']}"]
                for d in r["dimensions"].values()]
        dt = Table([["Evidence dimension", "Level", "Counts"]] + dims, colWidths=[55 * mm, 28 * mm, 91 * mm])
        dt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1"))]))
        story += [dt, Spacer(1, 2 * mm)]
        for x in r["reasons"]:
            story.append(Paragraph(f"&bull; <b>[{_esc(x['status'])}]</b> {_esc(x['text'])}", body))
        for x in r["unresolved"]:
            story.append(Paragraph(f"&bull; <b>[UNRESOLVED - {_esc(x['status'])}]</b> {_esc(x['text'])} <i>(not a fraud signal)</i>", body))
        story.append(Paragraph(f"Policy: {_esc(r['policy_version'])}", small))

    story.append(Paragraph("2. All checks", h2))
    rows = [["Check", "Status", "Detail"]]
    for ch in results["checks"]:
        col = STATUS_COLORS.get(ch["status"], "#000000")
        rows.append([Paragraph(_esc(ch["title"]), body), Paragraph(f"<font color='{col}'><b>{ch['status']}</b></font>", body), Paragraph(_esc(ch["message"]), small)])
    ct = Table(rows, colWidths=[50 * mm, 24 * mm, 100 * mm], repeatRows=1)
    ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, 0), 8),
                            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(ct)

    story.append(Paragraph("3. Extracted fields", h2))
    frows = [["Field", "Source", "Value", "Confidence", "Corrected"]]
    for f in results["fields"]:
        if f["name"].startswith("mrz_line"):
            continue
        frows.append([f["label"], f["source"], _esc(f["value"] or f["raw"]), f"{f['confidence']:.0%}", _esc(f["corrected_value"] or "")])
    ft = Table(frows, colWidths=[40 * mm, 18 * mm, 70 * mm, 22 * mm, 24 * mm], repeatRows=1)
    ft.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1"))]))
    story.append(ft)

    story.append(Paragraph("4. Forensics (review aid, not proof)", h2))
    fx = results.get("forensics") or {}
    story.append(Paragraph(_esc(fx.get("reason") or "Not run."), body))
    for f in fx.get("findings", []):
        if f["status"] == "REVIEW":
            story.append(Paragraph(f"&bull; <b>{_esc(f['zone'])}</b>: {_esc(f['message'])}", body))

    story.append(Paragraph("5. Officer review", h2))
    if results["reviews"]:
        for rv in results["reviews"]:
            story.append(Paragraph(f"<b>{_esc(rv['outcome'])}</b> by {_esc(rv['officer'])} at {rv['reviewed_at']}<br/>Rationale: {_esc(rv['rationale'])}", body))
    else:
        story.append(Paragraph("No officer review has been recorded yet.", body))

    story.append(Paragraph("6. Audit trail (most recent)", h2))
    arows = [["Time (UTC)", "Actor", "Action"]] + [[a["timestamp"][:19].replace("T", " "), f"{a['actor']} ({a['actor_role']})", a["action"]] for a in audit_rows[:25]]
    at = Table(arows, colWidths=[40 * mm, 60 * mm, 74 * mm], repeatRows=1)
    at.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1"))]))
    story.append(at)

    d = results.get("document") or {}
    story.append(Paragraph("7. Provenance and limitations", h2))
    story.append(Paragraph(f"Original SHA-256: <font face='Courier'>{_esc(d.get('sha256', '-'))}</font><br/>"
                           f"Ruleset: {_esc(results['checks'][0]['rule_version'] if results['checks'] else '-')}", body))
    for l in results["limitations"]:
        story.append(Paragraph("&bull; " + _esc(l), small))
    doc.build(story)
    return buf.getvalue()
