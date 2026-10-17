"""
deeksharambh_meeting_pdf.py — the Deeksharambh report as a clean document.

Laid out the way the University's own minutes and reports are: a white page,
black serif type, the JAIN logo at the top right of every page, plain headings
and bulleted findings. No colour blocks.

The report reads the whole scope as one — the overall picture only:

  Report Title · Objective · Key Figures · Summary · Strengths · Gaps ·
  What Students Want Next · Survey Findings (every section, every question,
  every answer) · About the Data

`dept=` builds the same document for one department alone, for the button on
that department's own page.

reportlab is imported lazily; a server without it can still serve the page.
"""
from __future__ import annotations

import io
import unicodedata
from pathlib import Path

INK = "#111111"
BODY = "#222222"
MUTED = "#595959"
RULE = "#bfbfbf"
FAINT = "#f2f2f2"
BAR = "#404040"
TRACK = "#e6e6e6"

LOGO = Path(__file__).resolve().parent / "static" / "img" / "jain-logo-grey.png"

# Emoji and typographic punctuation do not exist in the PDF core fonts, so the
# label "🙂 Smooth" would print as a box and a word. The options are all
# readable without their emoji, so the emoji goes and the words stay; the few
# punctuation marks that do have an ASCII twin are swapped rather than dropped.
PUNCTUATION = {
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", " ": " ",
    "→": "->", "•": "-", "−": "-",
}

WOULD_RECOMMEND = ("Would recommend: students were asked how likely they are to recommend JAIN, "
                   "from 0 to 10. The score is the share who answered 9 or 10, minus the share who "
                   "answered 0 to 6, so it runs from -100 (none would recommend) to +100 (all would).")


def _text(value) -> str:
    """Printable in the core fonts, and safe inside a reportlab Paragraph."""
    s = str(value if value is not None else "")
    s = "".join(PUNCTUATION.get(ch, ch) for ch in s)
    s = "".join(ch for ch in s
                if ord(ch) < 256 and unicodedata.category(ch) not in ("So", "Cs", "Co", "Cn"))
    s = " ".join(s.split())
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pct(value) -> str:
    return "-" if value is None else f"{value:g}%"


def _signed(value) -> str:
    return f"{value:+g}"


def build_meeting_pdf(pack: dict, *, generated_at: str, dept: str = "") -> bytes:
    """The overall report — or, with `dept`, the same report for that department."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, ListFlowable,
            ListItem, PageTemplate, Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:                                  # pragma: no cover
        raise RuntimeError(
            "The PDF export needs reportlab. Install it with "
            "`pip install reportlab` (it is pinned in requirements.txt)."
        ) from exc

    C = colors.HexColor
    campus = _text(pack.get("campus") or "All campuses")
    departments = pack.get("departments", [])
    if dept:
        d = next((x for x in departments if x["dept"] == dept), None)
        if d is None:
            raise KeyError(dept)
        scope_name = _text(dept)
    else:
        d = pack.get("overall_dept") or {}
        scope_name = "All departments"
    # The line at the foot of every page, and the document's own title.
    label = (f"Deeksharambh 2026 {scope_name} Analysis" if dept
             else "Deeksharambh 2026 Overall Analysis").replace("&amp;", "&")

    def style(name, **kw):
        base = dict(fontName="Times-Roman", fontSize=11.5, leading=15.5, textColor=C(BODY))
        base.update(kw)
        return ParagraphStyle(name, **base)

    S = {
        "title": style("title", fontSize=21, leading=26, textColor=C(INK), alignment=TA_CENTER,
                       spaceAfter=4),
        "subtitle": style("subtitle", fontSize=11, leading=14, textColor=C(MUTED),
                          alignment=TA_CENTER, spaceAfter=10),
        "h1": style("h1", fontSize=16.5, leading=21, textColor=C(INK), spaceBefore=12, spaceAfter=4),
        "h2": style("h2", fontName="Times-Bold", fontSize=12.5, leading=16, textColor=C(INK),
                    spaceBefore=10, spaceAfter=3),
        "lead": style("lead", fontName="Times-Bold", fontSize=12, leading=16, textColor=C(INK)),
        "body": style("body"),
        "bullet": style("bullet", leading=15),
        "q": style("q", fontName="Times-Bold", fontSize=11, leading=14, textColor=C(INK),
                   spaceBefore=6),
        "meta": style("meta", fontName="Times-Italic", fontSize=9.5, leading=12, textColor=C(MUTED)),
        "cell": style("cell", fontSize=10, leading=12.5),
        "cellr": style("cellr", fontSize=10, leading=12.5, alignment=2),
        "th": style("th", fontName="Times-Bold", fontSize=10, leading=12.5, textColor=C(INK)),
        "thr": style("thr", fontName="Times-Bold", fontSize=10, leading=12.5, textColor=C(INK),
                     alignment=2),
        "small": style("small", fontSize=9.5, leading=12.5, textColor=C(MUTED)),
        "none": style("none", fontName="Times-Italic", fontSize=10, leading=13, textColor=C(MUTED)),
    }

    page_w, page_h = A4
    margin = 22 * mm
    content_w = page_w - 2 * margin
    header_h = 20 * mm

    def page(canvas, doc):
        canvas.saveState()
        if LOGO.exists():
            from reportlab.lib.utils import ImageReader
            img = ImageReader(str(LOGO))
            iw, ih = img.getSize()
            h = 11 * mm
            w = h * iw / ih
            canvas.drawImage(img, page_w - margin - w, page_h - 8 * mm - h, width=w, height=h,
                             mask="auto")
        canvas.setFont("Times-Roman", 9)
        canvas.setFillColor(C(MUTED))
        canvas.drawString(margin, 12 * mm, label)
        canvas.drawRightString(page_w - margin, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=A4, leftMargin=margin, rightMargin=margin,
        topMargin=8 * mm + header_h, bottomMargin=20 * mm,
        title=label,
        author="JAIN University",
    )
    doc.addPageTemplates([PageTemplate(id="page", onPage=page, frames=[Frame(
        margin, 20 * mm, content_w, page_h - 8 * mm - header_h - 20 * mm, id="body",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])

    class Bar(Flowable):
        """A plain share-of-answers bar: a light track, filled to `pct`."""

        def __init__(self, pct, width, height=4.2):
            super().__init__()
            self.pct, self.width, self.height = pct or 0, width, height

        def wrap(self, *_):
            return self.width, self.height

        def draw(self):
            c = self.canv
            c.setFillColor(C(TRACK))
            c.rect(0, 0, self.width, self.height, stroke=0, fill=1)
            filled = max(0.0, min(100.0, float(self.pct))) / 100 * self.width
            if filled > 0:
                c.setFillColor(C(BAR))
                c.rect(0, 0, filled, self.height, stroke=0, fill=1)

    def bullets(items):
        return ListFlowable(
            [ListItem(Paragraph(it, S["bullet"]), leftIndent=14) for it in items],
            bulletType="bullet", start="•", leftIndent=16, bulletFontName="Times-Roman",
            bulletFontSize=11, spaceBefore=2, spaceAfter=4)

    def grid(rows, widths):
        t = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, C(RULE)),
            ("BACKGROUND", (0, 0), (-1, 0), C(FAINT)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    ans_w = content_w - 34 * mm - 18 * mm - 16 * mm

    def answers(options):
        rows = [[Paragraph("Answer", S["th"]), Paragraph("", S["th"]),
                 Paragraph("Students", S["thr"]), Paragraph("Share", S["thr"])]]
        for o in options:
            rows.append([Paragraph(_text(o["label"]), S["cell"]), Bar(o.get("pct"), 30 * mm),
                         Paragraph(str(o.get("count", 0)), S["cellr"]),
                         Paragraph(_pct(o.get("pct")), S["cellr"])])
        return grid(rows, [ans_w, 34 * mm, 18 * mm, 16 * mm])

    story = []

    # ── Title ────────────────────────────────────────────────────────────
    story += [
        Paragraph("Deeksharambh 2026 Report", S["title"]),
        Paragraph(f"{scope_name} &middot; {campus} &middot; Generated {_text(generated_at)}",
                  S["subtitle"]),
        Paragraph("Report Title", S["h1"]),
        Paragraph(f"Deeksharambh 2026 &ndash; Student Orientation Feedback, {scope_name}", S["lead"]),
        Paragraph("Objective", S["h1"]),
        Paragraph("To understand how students experienced the Deeksharambh orientation week and what "
                  "they expect next, across three areas:", S["body"]),
        bullets(["Participation: how many registered students completed Deeksharambh",
                 "Experience: how each part of the week was rated, its strengths and its gaps",
                 "Aspirations: interest in higher education, a business or a career"]),
    ]

    # ── Key figures ──────────────────────────────────────────────────────
    h = d.get("headline") or {}
    figures = [
        ["Registered on the portal", str(d.get("registered", 0))],
        ["Completed Deeksharambh", str(d.get("took", 0))],
        ["Still to reach", str(d.get("missing", 0))],
        ["Conversion", _pct(d.get("pct"))],
        ["Replies analysed", str(d.get("responses", 0))],
    ]
    if not dept:
        figures.insert(0, ["Departments", str(pack.get("totals", {}).get("departments", 0))])
    if h.get("vibe") is not None:
        figures.append(["Average vibe of the week", f"{h['vibe']} / 10"])
    if h.get("nps") is not None:
        figures.append(["Would recommend JAIN (score from -100 to +100)", _signed(h["nps"])])
    if h.get("belonging") is not None:
        figures.append(["Sense of belonging", f"{h['belonging']} / 10"])
    rows = [[Paragraph("Measure", S["th"]), Paragraph("Value", S["thr"])]] + [
        [Paragraph(_text(a), S["cell"]), Paragraph(f"<b>{_text(b)}</b>", S["cellr"])]
        for a, b in figures]
    story += [Paragraph("Key Figures", S["h1"]), grid(rows, [content_w - 40 * mm, 40 * mm])]
    if h.get("nps") is not None:
        story += [Spacer(1, 4), Paragraph(WOULD_RECOMMEND, S["small"])]

    if not d.get("responses"):
        story += [Paragraph("Summary", S["h1"]),
                  Paragraph("No Deeksharambh replies are on file for this scope yet.", S["body"])]
        doc.build(story)
        return buffer.getvalue()

    # ── Summary, strengths, gaps ─────────────────────────────────────────
    if d.get("synopsis"):
        story += [Paragraph("Summary", S["h1"]), Paragraph(_text(d["synopsis"]), S["body"])]
    if not d.get("reportable", True):
        n = d["responses"]
        story.append(Paragraph(f"Only {n} {'reply' if n == 1 else 'replies'} - read the answers as "
                               f"{n} named {'student' if n == 1 else 'students'}, not as a "
                               "percentage of anything.", S["none"]))

    def highlight(items):
        return [f"<b>{_text(x['label'])}</b> &ndash; {_text(x['top'])} ({_pct(x['pct'])})"
                for x in items]

    story += [Paragraph("Strengths", S["h1"]),
              bullets(highlight(d["strengths"])) if d.get("strengths")
              else Paragraph("No question had a clear lead on its good end yet.", S["none"])]
    story += [Paragraph("Gaps", S["h1"]),
              bullets(highlight(d["gaps"])) if d.get("gaps")
              else Paragraph("Nothing rose to the top of the complaint-only questions.", S["none"])]

    # ── What students want next ──────────────────────────────────────────
    c = d.get("career") or {}
    story.append(Paragraph("What Students Want Next", S["h1"]))
    if c.get("answered"):
        story.append(Paragraph(
            "Read from the Deeksharambh survey (the JAIN avatar each student picked and what they "
            "expect from JAIN) and the AI post survey (the PRaiSE pillar). A student counts when any "
            f"listed answer points that way, and can count under more than one. {c['answered']} of "
            f"{c['students']} registered students answered at least one of these questions; the "
            "percentages are of them.", S["body"]))
        items = []
        for g in c["groups"]:
            parts = "; ".join(f"{_text(sg['label'])} {sg['count']}" for sg in g["signals"])
            items.append(f"<b>{_text(g['label'])}: {g['count']} ({_pct(g['pct'])})</b> "
                         f"&ndash; counted from {parts}")
        story.append(bullets(items))
        if c.get("avatars"):
            line = ", ".join(f"{_text(a['label'])} {a['count']}" for a in c["avatars"])
            story.append(Paragraph(f"JAIN avatars picked: {line}.", S["small"]))
    else:
        story.append(Paragraph("No student has answered the JAIN avatar, expectations or PRaiSE "
                               "questions yet.", S["none"]))

    # ── Every section, every question, every answer ──────────────────────
    story += [CondPageBreak(60 * mm), Paragraph("Survey Findings", S["h1"]),
              Paragraph("Every section of the Deeksharambh survey, with every question and every "
                        "answer, most chosen first. Shares are of the students who answered that "
                        "question.", S["body"])]
    n = 0
    for sec in d.get("sections", []):
        # The section's heading travels with its first question, never alone.
        head = [Paragraph(_text(sec["title"]), S["h2"])]
        for q in sec["questions"]:
            n += 1
            meta = []
            if q["answered"]:
                meta.append(f"{q['answered']} answered")
                if q.get("avg") is not None:
                    meta.append(f"average {q['avg']}" + (f" / {q['max']}" if q.get("max") else ""))
                if q.get("nps") is not None:
                    meta.append(f"would-recommend score {_signed(q['nps'])}")
            block = [Paragraph(f"Q{n}. {_text(q['label'])}", S["q"]),
                     Paragraph(", ".join(meta) if meta else "Not answered yet.",
                               S["meta"] if meta else S["none"]), Spacer(1, 3)]
            block, head = head + block, []
            if not q["answered"]:
                story.append(KeepTogether(block))
                continue
            if q["kind"] == "matrix":
                # The question's heading stays with its first row's table.
                lead = block
                for row in q.get("rows") or []:
                    part = lead + [Paragraph(f"<i>{_text(row['label'])}</i> "
                                             f"({row['answered']} answered)", S["cell"]),
                                   Spacer(1, 2)]
                    part.append(answers(row["all"]) if row.get("all")
                                else Paragraph("No answers on file for this row.", S["none"]))
                    story += [KeepTogether(part), Spacer(1, 4)]
                    lead = []
                if lead:
                    story.append(KeepTogether(lead))
                continue
            if q.get("all"):
                block.append(answers(q["all"]))
            else:
                block.append(Paragraph(f"{q['answered']} answered, with nothing to rank.", S["none"]))
            story += [KeepTogether(block), Spacer(1, 4)]

    # ── About the data ───────────────────────────────────────────────────
    story += [CondPageBreak(30 * mm), Paragraph("About the Data", S["h1"]), Paragraph(
        "Counts are read directly from the registration portal, the Deeksharambh replies and the AI "
        "post survey; no figure in this report is estimated. No survey question asks students about "
        "their future plans outright, so the interests above are the students whose answers point "
        "that way.", S["body"])]

    doc.build(story)
    return buffer.getvalue()
