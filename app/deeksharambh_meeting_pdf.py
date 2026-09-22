"""
deeksharambh_meeting_pdf.py — the meeting pack as a PDF somebody can email.

The same document the meeting link shows, laid out for paper: a cover, the
registered-to-Deeksharambh count for every department, the strongest five and
the ones with the most room to grow, then one full section per department with
the two answers its students gave most.

It flows rather than paginating by hand — a department with forty questions
runs across as many pages as it needs, and none of it is trimmed to fit. The
meeting asked for all of it.

reportlab is imported lazily. A server without it can still build the deck, the
Word document and the meeting page; only this one download says what is missing.
"""
from __future__ import annotations

import io
import unicodedata

# ── Palette, shared with the meeting page ────────────────────────────────────
INK = "#0b1220"
BODY = "#24304a"
MUTED = "#64748b"
LINE = "#e2e8f0"
SOFT = "#f8fafc"
TEAL = "#0d9488"
TEAL_SOFT = "#ccfbf1"
AMBER = "#b45309"
AMBER_SOFT = "#fef3c7"
ROSE_SOFT = "#fff1f2"
PAPER_TEAL = "#f0fdfa"

# Emoji and typographic punctuation do not exist in the PDF core fonts, so the
# label "🙂 Smooth" would print as a box and a word. The options are all
# readable without their emoji, so the emoji goes and the words stay; the few
# punctuation marks that do have an ASCII twin are swapped rather than dropped.
PUNCTUATION = {
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", " ": " ",
    "→": "->", "•": "-",
}


def _text(value) -> str:
    """One option label, safe to set in Helvetica and safe inside a Paragraph."""
    raw = "".join(PUNCTUATION.get(ch, ch) for ch in str(value or ""))
    raw = unicodedata.normalize("NFKC", raw)
    kept = "".join(ch for ch in raw if ch == " " or (ord(ch) < 0x250 and ch.isprintable()))
    kept = " ".join(kept.split())
    return (kept.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            or _fallback(value))


def _fallback(value) -> str:
    """When a label was nothing but emoji, say so rather than printing blank."""
    return "(symbol)" if str(value or "").strip() else "-"


def _pct(value) -> str:
    return f"{value}%" if value is not None else "-"


def build_meeting_pdf(pack: dict, *, generated_at: str) -> bytes:
    """The whole meeting pack as PDF bytes."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
            Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - depends on the deployment
        raise RuntimeError(
            "The PDF export needs reportlab. Install it with "
            "`pip install reportlab` (it is pinned in requirements.txt)."
        ) from exc

    campus = _text(pack.get("campus", ""))
    totals = pack.get("totals", {})

    def style(name, **kw):
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("alignment", TA_LEFT)
        return ParagraphStyle(name, **kw)

    S = {
        "kicker": style("kicker", fontName="Helvetica-Bold", fontSize=8, leading=11,
                        textColor=colors.HexColor(TEAL), spaceAfter=4),
        "h1": style("h1", fontName="Helvetica-Bold", fontSize=24, leading=27,
                    textColor=colors.HexColor(INK), spaceAfter=8),
        "h2": style("h2", fontName="Helvetica-Bold", fontSize=15, leading=19,
                    textColor=colors.HexColor(INK), spaceBefore=6, spaceAfter=4),
        "h3": style("h3", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                    textColor=colors.HexColor(INK), spaceBefore=4, spaceAfter=3),
        "h4": style("h4", fontName="Helvetica-Bold", fontSize=9, leading=12,
                    textColor=colors.HexColor(TEAL), spaceBefore=8, spaceAfter=3),
        "body": style("body", fontSize=9.5, leading=13,
                      textColor=colors.HexColor(BODY), spaceAfter=3),
        "lede": style("lede", fontSize=8.5, leading=11.5,
                      textColor=colors.HexColor(MUTED), spaceAfter=4),
        "q": style("q", fontName="Helvetica-Bold", fontSize=9.5, leading=12.5,
                   textColor=colors.HexColor(INK), spaceBefore=5, spaceAfter=1),
        "meta": style("meta", fontSize=7.8, leading=10,
                      textColor=colors.HexColor(MUTED), spaceAfter=2),
        "pick": style("pick", fontSize=9, leading=12,
                      textColor=colors.HexColor(BODY), leftIndent=12, spaceAfter=0),
        "mrow": style("mrow", fontName="Helvetica-Bold", fontSize=8.8, leading=11.5,
                      textColor=colors.HexColor(BODY), leftIndent=8, spaceBefore=3),
        "none": style("none", fontName="Helvetica-Oblique", fontSize=8.5, leading=11,
                      textColor=colors.HexColor(MUTED), leftIndent=12, spaceAfter=1),
        "cell": style("cell", fontSize=8.5, leading=11, textColor=colors.HexColor(BODY)),
        "cellb": style("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                       textColor=colors.HexColor(INK)),
        "th": style("th", fontName="Helvetica-Bold", fontSize=7.5, leading=10,
                    textColor=colors.HexColor(MUTED)),
        "note": style("note", fontSize=8.5, leading=11.5,
                      textColor=colors.HexColor("#78350f"), spaceAfter=3,
                      leftIndent=6, rightIndent=6, spaceBefore=3),
    }

    page_w, page_h = A4
    margin = 14 * mm
    content_w = page_w - 2 * margin

    def chrome(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(margin, 9 * mm,
                          f"Deeksharambh 2026 - {campus} - department meeting pack")
        canvas.drawRightString(page_w - margin, 9 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor(LINE))
        canvas.setLineWidth(0.5)
        canvas.line(margin, 12 * mm, page_w - margin, 12 * mm)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=18 * mm,
        title=f"Deeksharambh 2026 department meeting pack - {campus}",
        author="JAIN University",
    )
    frame = Frame(margin, 18 * mm, content_w, page_h - margin - 18 * mm, id="body")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=chrome)])

    def table(rows, widths, *, head=True, zebra=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if head else 0, hAlign="LEFT")
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor(LINE)),
        ]
        if head:
            commands += [
                ("LINEBELOW", (0, 0), (-1, 0), 1.1, colors.HexColor(LINE)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
            ]
        if zebra:
            for i in range(2 if head else 1, len(rows), 2):
                commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(SOFT)))
        t.setStyle(TableStyle(commands))
        return t

    story = []

    # ── Cover ────────────────────────────────────────────────────────────
    story += [
        Spacer(1, 18 * mm),
        Paragraph(f"DEEKSHARAMBH 2026 &middot; {campus}", S["kicker"]),
        Paragraph("Department meeting pack", S["h1"]),
        Paragraph(
            "Registered on the portal against who actually took Deeksharambh, ranked, "
            "naming the most active departments and the ones where a push reaches the "
            "most students - then every department's own reading, question by question, "
            f"with the {pack.get('picks', 2)} answers its students gave most.", S["body"]),
        Spacer(1, 6 * mm),
    ]

    story.append(table(
        [[Paragraph(_text(label), S["th"]) for label in
          ("REGISTERED IN PORTAL", "TOOK DEEKSHARAMBH", "STILL TO REACH", "CONVERSION")],
         [Paragraph(f'<font size="17"><b>{value}</b></font>', S["cellb"]) for value in
          (totals.get("registered", 0), totals.get("took", 0),
           totals.get("missing", 0), _pct(totals.get("pct")))]],
        [content_w / 4] * 4, zebra=False))

    story += [Spacer(1, 4 * mm),
              Paragraph(f"Generated {_text(generated_at)}. Counts read from the "
                        "registration portal and the orientation responses directly; "
                        "no figure in this document is estimated.", S["lede"])]

    if totals.get("unmatched"):
        n = totals["unmatched"]
        story.append(_banner(
            Paragraph(f"<b>{n}</b> Deeksharambh {'reply' if n == 1 else 'replies'} came from an "
                      "email address with no portal registration. Those replies are read in the "
                      "department analysis but cannot appear in the conversion, which is why the "
                      f"two totals differ by exactly {n}.", S["note"]),
            content_w, AMBER_SOFT, AMBER, Table, TableStyle, colors))

    story.append(PageBreak())

    # ── 1. The count ─────────────────────────────────────────────────────
    story += [
        Paragraph("01 &middot; Registered on the portal, and who took Deeksharambh", S["h2"]),
        Paragraph("Every student the portal registered is in the denominator, whether or not "
                  "they ever opened the baseline survey. The numerator is the students with a "
                  "Deeksharambh reply on file.", S["lede"]),
    ]

    head = [Paragraph(h, S["th"]) for h in
            ("#", "DEPARTMENT", "CAMPUS", "REG.", "TOOK", "TO REACH", "CONV.")]
    rows = [head]
    for i, row in enumerate(pack.get("conversion", []), start=1):
        rows.append([
            Paragraph(str(i), S["cell"]),
            Paragraph(_text(row["dept"]), S["cellb"]),
            Paragraph(_text(", ".join(row.get("campuses") or [])) or "-", S["cell"]),
            Paragraph(str(row["registered"]), S["cell"]),
            Paragraph(str(row["took"]), S["cell"]),
            Paragraph(str(row["missing"]), S["cell"]),
            Paragraph(_pct(row["pct"]), S["cellb"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("No students registered in this scope yet.", S["cell"])] +
                    [Paragraph("", S["cell"])] * 6)

    widths = [10 * mm, content_w - 10 * mm - 26 * mm - 4 * 14 * mm, 26 * mm] + [14 * mm] * 4
    story += [table(rows, widths), PageBreak()]

    # ── 2. Top 5 / least 5 ───────────────────────────────────────────────
    callouts = pack.get("callouts", {})
    size = callouts.get("size", 5)
    story += [
        Paragraph("02 &middot; Most active departments, and where a push goes furthest",
                  S["h2"]),
        Paragraph("Ranked on the same conversion. Departments level on percentage are split by "
                  "how many students that percentage stands for, so 100% of forty ranks above "
                  "100% of four. The second list is not a ranking of failure - it is where the "
                  "next push reaches the most students.", S["lede"]),
    ]

    if callouts.get("overlap"):
        ranked = callouts.get("ranked", 0)
        story.append(_banner(
            Paragraph(f"Only {ranked} {'department has' if ranked == 1 else 'departments have'} "
                      f"students registered in this scope - fewer than the {size * 2} the two "
                      "lists need, so "
                      f"{_text(', '.join(callouts['overlap']))} "
                      f"{'appears' if len(callouts['overlap']) == 1 else 'appear'} in both.",
                      S["note"]),
            content_w, AMBER_SOFT, AMBER, Table, TableStyle, colors))

    for title, key, tint in (
        (f"Most active {len(callouts.get('top', []))} - departments whose students turned up in force",
         "top", PAPER_TEAL),
        (f"Room to grow - {len(callouts.get('least', []))} departments where a push reaches the most students",
         "least", ROSE_SOFT),
    ):
        story += [Spacer(1, 4 * mm), Paragraph(_text(title), S["h3"])]
        rows = [[Paragraph(h, S["th"]) for h in ("#", "DEPARTMENT", "TOOK / REGISTERED", "CONVERSION")]]
        for i, row in enumerate(callouts.get(key) or [], start=1):
            rows.append([
                Paragraph(str(i), S["cell"]),
                Paragraph(_text(row["dept"]), S["cellb"]),
                Paragraph(f"{row['took']} / {row['registered']}", S["cell"]),
                Paragraph(_pct(row["pct"]), S["cellb"]),
            ])
        if len(rows) == 1:
            rows.append([Paragraph("Nothing to rank yet.", S["cell"])] + [Paragraph("", S["cell"])] * 3)
        t = table(rows, [10 * mm, content_w - 10 * mm - 40 * mm - 26 * mm, 40 * mm, 26 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(tint))]))
        story.append(t)

    story.append(PageBreak())

    # ── 3. Department by department ──────────────────────────────────────
    departments = pack.get("departments", [])
    story += [
        Paragraph("03 &middot; Department by department, question by question", S["h2"]),
        Paragraph(
            "Every question the Deeksharambh form asked, for every department, with the "
            f"{pack.get('picks', 2)} answers its own students chose most. Where a question has a "
            "good end, both answers come from it. Where a question only ever asked what went "
            f"wrong, the {pack.get('picks', 2)} biggest asks are shown as asks. Percentages are "
            "of the students in that department who answered that question, not of the "
            "department.", S["lede"]),
    ]

    for index, dept in enumerate(departments, start=1):
        if index > 1:
            story.append(PageBreak())

        header = [
            Paragraph(_text(f"DEPARTMENT {index} OF {len(departments)}"
                            + (f"  ·  {', '.join(dept.get('campuses') or [])}"
                               if dept.get("campuses") else "")), S["kicker"]),
            Paragraph(_text(dept["dept"]), S["h3"]),
        ]
        stats = " &middot; ".join(filter(None, [
            f"Registered <b>{dept['registered']}</b>",
            f"Took Deeksharambh <b>{dept['took']}</b>",
            f"Conversion <b>{_pct(dept['pct'])}</b>",
            f"Replies analysed <b>{dept['responses']}</b>",
            (f"Vibe <b>{dept['headline']['vibe']}/10</b>"
             if dept["headline"].get("vibe") is not None else ""),
            (f"NPS <b>{dept['headline']['nps']}</b>"
             if dept["headline"].get("nps") is not None else ""),
            (f"Belonging <b>{dept['headline']['belonging']}/10</b>"
             if dept["headline"].get("belonging") is not None else ""),
        ]))
        header.append(Paragraph(stats, S["meta"]))
        story.append(KeepTogether(header))

        if not dept["responses"]:
            story.append(Paragraph(
                f"No Deeksharambh replies from this department yet - the {dept['registered']} "
                f"registered {'student has' if dept['registered'] == 1 else 'students have'} "
                "nothing on file to read.", S["none"]))
            continue

        if not dept.get("reportable", True):
            n = dept["responses"]
            story.append(Paragraph(
                f"{n} {'reply' if n == 1 else 'replies'} - below the "
                f"{pack.get('min_reportable', 10)} this report treats as safe to quote outside "
                f"the department. Read the answers as {n} named "
                f"{'student' if n == 1 else 'students'}, not as a percentage of anything.",
                S["none"]))

        for section in dept["sections"]:
            story.append(Paragraph(_text(section["title"]).upper(), S["h4"]))
            for q in section["questions"]:
                block = [Paragraph(f"{q['key'].upper()} &middot; {_text(q['label'])}", S["q"])]

                if q["answered"]:
                    meta = [q["frame_label"], f"{q['answered']} answered"]
                    if q.get("avg") is not None:
                        meta.append(f"avg {q['avg']}" + (f"/{q['max']}" if q.get("max") else ""))
                    if q.get("nps") is not None:
                        meta.append(f"NPS {q['nps']}")
                    block.append(Paragraph(" &middot; ".join(_text(m) for m in meta), S["meta"]))
                else:
                    block.append(Paragraph("Not answered by anyone in this department.", S["none"]))
                    story.append(KeepTogether(block))
                    continue

                if q["kind"] == "matrix":
                    if not q["rows"]:
                        block.append(Paragraph("Nobody in this department filled this grid in.",
                                               S["none"]))
                    for row in q["rows"]:
                        block.append(Paragraph(
                            f"{_text(row['label'])} <font color='{MUTED}'>"
                            f"- {row['answered']} answered</font>", S["mrow"]))
                        if row["picks"]:
                            for i, pick in enumerate(row["picks"], start=1):
                                block.append(Paragraph(
                                    f"{i}. {_text(pick['label'])} &mdash; "
                                    f"<b>{_pct(pick['pct'])}</b> ({pick['count']})", S["pick"]))
                        else:
                            block.append(Paragraph(
                                "No answer at the positive end of this statement.", S["none"]))
                elif q["picks"]:
                    for i, pick in enumerate(q["picks"], start=1):
                        block.append(Paragraph(
                            f"{i}. {_text(pick['label'])} &mdash; "
                            f"<b>{_pct(pick['pct'])}</b> ({pick['count']})", S["pick"]))
                    if q.get("share") is not None:
                        block.append(Paragraph(
                            f"Between them, {q['share']}% of the {q['answered']} who "
                            "answered this question.", S["none"]))
                elif q["frame"] == "positive":
                    block.append(Paragraph(
                        f"{q['answered']} answered, but none of them picked an answer from the "
                        "positive end of this question.", S["none"]))
                else:
                    block.append(Paragraph(f"{q['answered']} answered, with nothing to rank.",
                                           S["none"]))

                story.append(KeepTogether(block))

    if not departments:
        story.append(Paragraph("No departments in this scope yet.", S["none"]))

    doc.build(story)
    return buffer.getvalue()


def _banner(paragraph, width, fill, edge, Table, TableStyle, colors):
    """A tinted box with a coloured spine — the page's `.note`, on paper."""
    t = Table([[paragraph]], colWidths=[width], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(fill)),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, colors.HexColor(edge)),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t
