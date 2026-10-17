"""
deeksharambh_meeting_pdf.py — the Deeksharambh department-wise report as a PDF.

The same reading the meeting page shows, laid out for paper in JAIN navy and
gold, with the JAIN logo on the cover and across the top of every page:

  Cover   the four headline counts, the overall summary, what is inside
  01      registered on the portal → took Deeksharambh, every department,
          most students first
  02      the most active departments and the ones with the most room to grow
  03      overall — all departments, read the way one department is
  04      department by department

Every department reading (and the overall one) carries the same parts as its
page: the stat chips (with "Would recommend" explained, not abbreviated), the
summary, strengths and gaps, what its students want next (higher education, a
business, a career), then the eight sections with every question and every
answer its students gave, most-chosen first.

`dept=` builds the same report for one department alone.

It flows rather than paginating by hand — a department with forty questions
runs across as many pages as it needs, and none of it is trimmed to fit.
reportlab is imported lazily; a server without it can still serve the page.
"""
from __future__ import annotations

import io
import unicodedata
from pathlib import Path

# ── JAIN palette, shared with the meeting page ───────────────────────────────
NAVY = "#0d2147"
BLUE = "#1e4f9a"
GOLD = "#c9a84c"
INK = "#101828"
BODY = "#24304a"
MUTED = "#64748b"
LINE = "#dde3ee"
SOFT = "#f4f7fc"
MIST = "#eef3fb"
GREEN = "#15803d"
GREEN_SOFT = "#ecf8ef"
AMBER = "#b45309"
AMBER_SOFT = "#fef3c7"
TRACK = "#e8edf5"

LOGO = Path(__file__).resolve().parent / "static" / "img" / "jain-logo.png"   # white, for navy

# Emoji and typographic punctuation do not exist in the PDF core fonts, so the
# label "🙂 Smooth" would print as a box and a word. The options are all
# readable without their emoji, so the emoji goes and the words stay; the few
# punctuation marks that do have an ASCII twin are swapped rather than dropped.
PUNCTUATION = {
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", " ": " ",
    "→": "->", "•": "-", "−": "-",
}

CAREER_TINT = {"higher_education": BLUE, "entrepreneur": GOLD, "career": GREEN}

WOULD_RECOMMEND = ("<b>Would recommend</b> - students were asked how likely they are to recommend "
                   "JAIN, from 0 to 10. The score is the share who answered 9 or 10, minus the share "
                   "who answered 0 to 6. It runs from -100 (none would recommend) to +100 (all would).")


def _text(value) -> str:
    """Printable in Helvetica, and safe inside a reportlab Paragraph."""
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
    """The whole report — or, with `dept`, that one department's report."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, NextPageTemplate,
            PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:                                  # pragma: no cover
        raise RuntimeError(
            "The PDF export needs reportlab. Install it with "
            "`pip install reportlab` (it is pinned in requirements.txt)."
        ) from exc

    campus_raw = pack.get("campus") or "All campuses"
    campus = _text(campus_raw)
    totals = pack.get("totals", {})
    departments = pack.get("departments", [])
    focus = None
    if dept:
        focus = next((d for d in departments if d["dept"] == dept), None)
        if focus is None:
            raise KeyError(dept)

    C = colors.HexColor

    def style(name, **kw):
        base = dict(fontName="Helvetica", fontSize=9.5, leading=13, textColor=C(BODY))
        base.update(kw)
        return ParagraphStyle(name, **base)

    S = {
        "kicker": style("kicker", fontName="Helvetica-Bold", fontSize=8, leading=11,
                        textColor=C(GOLD), spaceAfter=2),
        "h2": style("h2", fontName="Helvetica-Bold", fontSize=16, leading=20,
                    textColor=C(NAVY), spaceAfter=3),
        "h2n": style("h2n", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=C(GOLD)),
        "h3": style("h3", fontName="Helvetica-Bold", fontSize=12, leading=15,
                    textColor=C(NAVY), spaceBefore=4, spaceAfter=4),
        "sec": style("sec", fontName="Helvetica-Bold", fontSize=11, leading=14,
                     textColor=C(BLUE)),
        "body": style("body", fontSize=9.5, leading=13.5),
        "lede": style("lede", fontSize=8.6, leading=12, textColor=C(MUTED), spaceAfter=6),
        "syn": style("syn", fontSize=10, leading=14.5, textColor=C(INK)),
        "q": style("q", fontName="Helvetica-Bold", fontSize=9.4, leading=12.4, textColor=C(INK)),
        "meta": style("meta", fontSize=7.8, leading=10.5, textColor=C(MUTED)),
        "ans": style("ans", fontSize=8.6, leading=11, textColor=C(BODY)),
        "mrow": style("mrow", fontName="Helvetica-Bold", fontSize=8.6, leading=11.5,
                      textColor=C(BLUE)),
        "none": style("none", fontName="Helvetica-Oblique", fontSize=8.4, leading=11,
                      textColor=C(MUTED)),
        "cell": style("cell", fontSize=8.5, leading=11),
        "cellb": style("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                       textColor=C(INK)),
        "cellr": style("cellr", fontSize=8.5, leading=11, alignment=2),
        "cellbr": style("cellbr", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                        textColor=C(INK), alignment=2),
        "th": style("th", fontName="Helvetica-Bold", fontSize=7.4, leading=9.5,
                    textColor=colors.white),
        "thr": style("thr", fontName="Helvetica-Bold", fontSize=7.4, leading=9.5,
                     textColor=colors.white, alignment=2),
        "tile_n": style("tile_n", fontName="Helvetica-Bold", fontSize=17, leading=20,
                        textColor=C(NAVY)),
        "tile_l": style("tile_l", fontSize=7.6, leading=9.6, textColor=C(MUTED)),
        "hl_h": style("hl_h", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
                      textColor=C(GREEN)),
        "hl": style("hl", fontSize=8.6, leading=11.4),
        "dept_k": style("dept_k", fontName="Helvetica-Bold", fontSize=7.8, leading=10,
                        textColor=C(GOLD)),
        "dept_h": style("dept_h", fontName="Helvetica-Bold", fontSize=15, leading=18.5,
                        textColor=colors.white),
        "note": style("note", fontSize=8, leading=11, textColor=C("#78350f")),
        "toc": style("toc", fontSize=10, leading=15, textColor=C(INK)),
        "car_h": style("car_h", fontName="Helvetica-Bold", fontSize=9, leading=11.5,
                       textColor=C(INK)),
        "car_n": style("car_n", fontName="Helvetica-Bold", fontSize=18, leading=21,
                       textColor=C(INK)),
        "car_s": style("car_s", fontSize=7.8, leading=10.2, textColor=C(BODY)),
    }

    page_w, page_h = A4
    margin = 15 * mm
    content_w = page_w - 2 * margin
    band = 15 * mm                       # the navy strip across the top of every page
    cover_band = 92 * mm

    scope_line = (f"{_text(focus['dept'])} - {campus}" if focus
                  else f"Department-wise report - {campus}")

    def _logo(canvas, x, y, height):
        if LOGO.exists():
            from reportlab.lib.utils import ImageReader
            img = ImageReader(str(LOGO))
            iw, ih = img.getSize()
            canvas.drawImage(img, x, y, width=height * iw / ih, height=height, mask="auto")

    def _footer(canvas, doc):
        canvas.setStrokeColor(C(GOLD))
        canvas.setLineWidth(0.8)
        canvas.line(margin, 12 * mm, page_w - margin, 12 * mm)
        canvas.setFont("Helvetica", 7.4)
        canvas.setFillColor(C(MUTED))
        canvas.drawString(margin, 8 * mm, "JAIN (Deemed-to-be University) - Deeksharambh 2026")
        canvas.drawRightString(page_w - margin, 8 * mm, f"Page {doc.page}")

    def body_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C(NAVY))
        canvas.rect(0, page_h - band, page_w, band, stroke=0, fill=1)
        canvas.setFillColor(C(GOLD))
        canvas.rect(0, page_h - band - 1.2, page_w, 1.2, stroke=0, fill=1)
        _logo(canvas, margin, page_h - band + 3.6 * mm, 7.8 * mm)
        canvas.setFont("Helvetica-Bold", 7.6)
        canvas.setFillColor(C(GOLD))
        canvas.drawRightString(page_w - margin, page_h - band + 8.6 * mm, "DEEKSHARAMBH 2026")
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(colors.white)
        canvas.drawRightString(page_w - margin, page_h - band + 4.4 * mm,
                               scope_line.replace("&amp;", "&"))
        _footer(canvas, doc)
        canvas.restoreState()

    def cover_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C(NAVY))
        canvas.rect(0, page_h - cover_band, page_w, cover_band, stroke=0, fill=1)
        canvas.setFillColor(C(GOLD))
        canvas.rect(0, page_h - cover_band - 2.2, page_w, 2.2, stroke=0, fill=1)
        _logo(canvas, margin, page_h - 34 * mm, 19 * mm)
        canvas.setFont("Helvetica-Bold", 8.6)
        canvas.setFillColor(C(GOLD))
        canvas.drawString(margin, page_h - 47 * mm, f"JAIN UNIVERSITY - 2026 - {campus.upper()}"
                          .replace("&AMP;", "&"))
        canvas.setFont("Helvetica-Bold", 30)
        canvas.setFillColor(colors.white)
        canvas.drawString(margin, page_h - 61 * mm, "Deeksharambh")
        canvas.setFont("Helvetica", 13)
        canvas.setFillColor(C("#dbe6f7"))
        sub = (focus["dept"] if focus else "Department-wise survey report")
        canvas.drawString(margin, page_h - 71 * mm, _text(sub).replace("&amp;", "&")[:80])
        canvas.setFont("Helvetica", 8.4)
        canvas.setFillColor(C("#b8c4d9"))
        canvas.drawString(margin, page_h - 80 * mm, f"Generated {generated_at}")
        _footer(canvas, doc)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=A4, leftMargin=margin, rightMargin=margin,
        topMargin=band + 7 * mm, bottomMargin=17 * mm,
        title=(f"Deeksharambh 2026 - {focus['dept']}" if focus
               else f"Deeksharambh 2026 department-wise report - {campus}"),
        author="JAIN University",
    )
    bottom = 17 * mm
    doc.addPageTemplates([
        PageTemplate(id="cover", onPage=cover_page, frames=[Frame(
            margin, bottom, content_w, page_h - cover_band - 8 * mm - bottom, id="cover")]),
        PageTemplate(id="body", onPage=body_page, frames=[Frame(
            margin, bottom, content_w, page_h - band - 7 * mm - bottom, id="body")]),
    ])

    class Bar(Flowable):
        """A share-of-answers bar: a pale track, filled to `pct`."""

        def __init__(self, pct, width, color, height=5.2):
            super().__init__()
            self.pct, self.width, self.height, self.color = pct or 0, width, height, color

        def wrap(self, *_):
            return self.width, self.height

        def draw(self):
            c = self.canv
            c.setFillColor(C(TRACK))
            c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
            filled = max(0.0, min(100.0, float(self.pct))) / 100 * self.width
            if filled > 0:
                c.setFillColor(C(self.color))
                c.roundRect(0, 0, max(filled, self.height), self.height, self.height / 2,
                            stroke=0, fill=1)

    def grid(rows, widths, *, head=True, zebra=True, head_fill=BLUE):
        t = Table(rows, colWidths=widths, repeatRows=1 if head else 0, hAlign="LEFT")
        cmds = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, C(LINE)),
        ]
        if head:
            cmds.append(("BACKGROUND", (0, 0), (-1, 0), C(head_fill)))
        if zebra:
            for i in range(2 if head else 1, len(rows), 2):
                cmds.append(("BACKGROUND", (0, i), (-1, i), C(SOFT)))
        t.setStyle(TableStyle(cmds))
        return t

    def box(flowables, fill=SOFT, edge=None, pad=8):
        t = Table([[flowables]], colWidths=[content_w], hAlign="LEFT")
        cmds = [("BACKGROUND", (0, 0), (-1, -1), C(fill)),
                ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                ("LEFTPADDING", (0, 0), (-1, -1), pad + 2), ("RIGHTPADDING", (0, 0), (-1, -1), pad + 2)]
        if edge:
            cmds.append(("LINEBEFORE", (0, 0), (0, -1), 2.4, C(edge)))
        t.setStyle(TableStyle(cmds))
        return t

    def tiles(items, *, cols=None):
        """Number-over-label tiles in one row."""
        cols = cols or len(items)
        w = content_w / cols
        cells = [[Paragraph(_text(n), S["tile_n"]), Paragraph(_text(lab), S["tile_l"])]
                 for n, lab in items]
        t = Table([cells], colWidths=[w] * cols, hAlign="LEFT")
        cmds = [("BACKGROUND", (0, 0), (-1, -1), C(MIST)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("LINEABOVE", (0, 0), (-1, 0), 2, C(BLUE))]
        for i in range(1, cols):
            cmds.append(("LINEBEFORE", (i, 0), (i, 0), 2.5, colors.white))
        t.setStyle(TableStyle(cmds))
        return t

    def heading(number, title, lede=None):
        out = [Paragraph(f'<font color="{GOLD}">{number}</font>&nbsp;&nbsp;{_text(title)}', S["h2"])]
        if lede:
            out.append(Paragraph(lede, S["lede"]))
        return out

    # ── Answers: one row per option, most-chosen first ───────────────────
    label_w, bar_w, pct_w, cnt_w, idx_w = None, 38 * mm, 15 * mm, 14 * mm, 7 * mm
    label_w = content_w - bar_w - pct_w - cnt_w - idx_w

    def answers_table(options, color=BLUE):
        rows = []
        for i, o in enumerate(options, start=1):
            rows.append([
                Paragraph(f"{i}.", S["meta"]),
                Paragraph(_text(o["label"]), S["ans"]),
                Bar(o.get("pct"), bar_w - 10, color),
                Paragraph(f"<b>{_pct(o.get('pct'))}</b>", S["cellr"]),
                Paragraph(f"({o.get('count', 0)})", S["meta"]),
            ])
        t = Table(rows, colWidths=[idx_w, label_w, bar_w, pct_w, cnt_w], hAlign="LEFT")
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    def question_block(n, q):
        meta = []
        if q["answered"]:
            if q.get("frame_label"):
                meta.append(q["frame_label"])
            meta.append(f"{q['answered']} answered")
            if q.get("avg") is not None:
                meta.append(f"average {q['avg']}" + (f"/{q['max']}" if q.get("max") else ""))
            if q.get("nps") is not None:
                meta.append(f"would-recommend score {_signed(q['nps'])} (-100 to +100)")
        block = [Paragraph(f'<font color="{BLUE}">Q{n}</font>&nbsp;&nbsp;{_text(q["label"])}', S["q"]),
                 Paragraph(" - ".join(_text(m) for m in meta) if meta
                           else "Not answered by anyone here.", S["meta"] if meta else S["none"])]
        if not q["answered"]:
            return [KeepTogether(block), Spacer(1, 5)]
        color = GREEN if q.get("frame") == "positive" else (AMBER if q.get("frame") == "asked" else BLUE)
        if q["kind"] == "matrix":
            out = [KeepTogether(block)]
            if not q.get("rows"):
                out.append(Paragraph("Nobody filled this grid in.", S["none"]))
            for row in q.get("rows") or []:
                part = [Paragraph(f"{_text(row['label'])} "
                                  f'<font color="{MUTED}">- {row["answered"]} answered</font>',
                                  S["mrow"])]
                part.append(answers_table(row["all"], BLUE) if row.get("all")
                            else Paragraph("No answers on file for this row.", S["none"]))
                out.append(KeepTogether(part))
            return out + [Spacer(1, 6)]
        if q.get("all"):
            block.append(answers_table(q["all"], color))
        elif q.get("frame") == "positive":
            block.append(Paragraph(f"{q['answered']} answered, but none of them picked an answer "
                                   "from the positive end of this question.", S["none"]))
        else:
            block.append(Paragraph(f"{q['answered']} answered, with nothing to rank.", S["none"]))
        return [KeepTogether(block), Spacer(1, 6)]

    def highlights(d):
        def column(title, items, empty):
            cell = [Paragraph(_text(title), S["hl_h"]), Spacer(1, 3)]
            if items:
                for i, it in enumerate(items, start=1):
                    cell.append(Paragraph(f"{i}. <b>{_text(it['label'])}</b><br/>"
                                          f'<font color="{GREEN}">{_text(it["top"])} - '
                                          f"{_pct(it['pct'])}</font>", S["hl"]))
                    cell.append(Spacer(1, 3))
            else:
                cell.append(Paragraph(empty, S["none"]))
            return cell
        half = content_w / 2
        t = Table([[column("Strengths", d.get("strengths"),
                           "No question had a clear lead on its good end yet."),
                    column("Gaps", d.get("gaps"),
                           "Nothing rose to the top of the complaint-only questions.")]],
                  colWidths=[half - 3, half - 3], hAlign="LEFT", spaceBefore=4)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C(GREEN_SOFT)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEABOVE", (0, 0), (-1, 0), 2, C(GREEN)),
            ("LINEBEFORE", (1, 0), (1, 0), 6, colors.white),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ]))
        return t

    def career_block(c):
        out = [Paragraph("What students want next - higher education, a business or a career",
                         S["h3"])]
        if not c or not c.get("answered"):
            out.append(Paragraph("None of these students has answered the JAIN avatar, "
                                 "expectations or PRaiSE questions yet.", S["none"]))
            return out
        out.append(Paragraph(
            "From the Deeksharambh survey (the JAIN avatar each student picked and what they "
            "expect from JAIN) and the AI post survey (the PRaiSE pillar). A student counts when "
            f"any listed answer points that way, and can count under more than one. "
            f"<b>{c['answered']}</b> of {c['students']} registered students answered at least one "
            "of these questions; the percentages are of them.", S["lede"]))
        w = (content_w - 8) / 3
        cells = []
        for g in c["groups"]:
            tint = CAREER_TINT.get(g["key"], BLUE)
            cell = [Paragraph(_text(g["label"]), S["car_h"]),
                    Paragraph(f'{g["count"]} <font size="9" color="{MUTED}">'
                              f'{_pct(g["pct"])} of {c["answered"]}</font>', S["car_n"]),
                    Bar(g["pct"], w - 18, tint, height=6), Spacer(1, 4)]
            for sg in g["signals"]:
                cell.append(Paragraph(f"{_text(sg['label'])}: <b>{sg['count']}</b>", S["car_s"]))
            cells.append(cell)
        t = Table([cells], colWidths=[w] * 3, hAlign="LEFT")
        cmds = [("BACKGROUND", (0, 0), (-1, -1), C(SOFT)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]
        for i, g in enumerate(c["groups"]):
            cmds.append(("LINEABOVE", (i, 0), (i, 0), 2.4, C(CAREER_TINT.get(g["key"], BLUE))))
            if i:
                cmds.append(("LINEBEFORE", (i, 0), (i, 0), 4, colors.white))
        t.setStyle(TableStyle(cmds))
        out.append(t)
        if c.get("avatars"):
            line = " - ".join(f"{_text(a['label'])} {a['count']}" for a in c["avatars"])
            out.append(Spacer(1, 4))
            out.append(Paragraph(f"<b>Every JAIN avatar picked:</b> {line}. {c['none']} answered but "
                                 f"pointed to none of the three; {c['unsure']} picked "
                                 '"Still Figuring It Out".', S["meta"]))
        return out

    def department_reading(d, kicker):
        story = []
        head = Table([[[Paragraph(_text(kicker), S["dept_k"]), Paragraph(_text(d["dept"]), S["dept_h"])]]],
                     colWidths=[content_w], hAlign="LEFT")
        head.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C(BLUE)),
            ("LINEBELOW", (0, 0), (-1, -1), 2, C(GOLD)),
            ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ]))
        story += [head, Spacer(1, 5)]

        h = d.get("headline") or {}
        items = [(str(d["registered"]), "Registered on the portal"),
                 (str(d["took"]), "Took Deeksharambh"),
                 (_pct(d["pct"]), "Conversion"),
                 (str(d["responses"]), "Replies analysed")]
        if h.get("vibe") is not None:
            items.append((f"{h['vibe']}/10", "Vibe"))
        if h.get("nps") is not None:
            items.append((_signed(h["nps"]), "Would recommend"))
        if h.get("belonging") is not None:
            items.append((f"{h['belonging']}/10", "Belonging"))
        story.append(tiles(items))
        if h.get("nps") is not None:
            story += [Spacer(1, 3), Paragraph(WOULD_RECOMMEND, S["meta"])]

        if not d["responses"]:
            story += [Spacer(1, 6), Paragraph(
                f"No Deeksharambh replies from here yet - the {d['registered']} registered "
                f"{'student has' if d['registered'] == 1 else 'students have'} nothing on file to read.",
                S["none"])]
            story += [Spacer(1, 4), KeepTogether(career_block(d.get("career")))]
            return story

        if not d.get("reportable", True):
            n = d["responses"]
            story += [Spacer(1, 5), box([Paragraph(
                f"{n} {'reply' if n == 1 else 'replies'} - below the "
                f"{pack.get('min_reportable', 10)} this report treats as safe to quote outside the "
                f"department. Read the answers as {n} named {'student' if n == 1 else 'students'}, "
                "not as a percentage of anything.", S["note"])], AMBER_SOFT, AMBER, 6)]

        if d.get("synopsis"):
            story += [Spacer(1, 7), box([Paragraph(_text(d["synopsis"]), S["syn"])], MIST, BLUE)]
        story += [Spacer(1, 6), highlights(d), Spacer(1, 4)]
        story.append(KeepTogether(career_block(d.get("career"))))

        story += [Spacer(1, 8), CondPageBreak(70 * mm),
                  Paragraph("Every section, every question, every answer", S["h3"]),
                  Paragraph("Percentages are of the students here who answered that question. "
                            "Green bars are answers from a question's good end, amber bars are "
                            "asks and complaints.", S["lede"])]
        n = 0
        for sec in d["sections"]:
            story.append(CondPageBreak(40 * mm))
            sec_head = Table([[Paragraph(_text(sec["title"]), S["sec"]),
                               Paragraph(f"{len(sec['questions'])} question"
                                         f"{'s' if len(sec['questions']) != 1 else ''}", S["cellr"])]],
                             colWidths=[content_w - 30 * mm, 30 * mm], hAlign="LEFT")
            sec_head.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 1.4, C(GOLD)),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ]))
            story += [Spacer(1, 6), sec_head, Spacer(1, 5)]
            for q in sec["questions"]:
                n += 1
                story += question_block(n, q)
        return story

    story = [NextPageTemplate("body")]

    # ── One department alone ─────────────────────────────────────────────
    if focus:
        index = departments.index(focus) + 1
        story += department_reading(
            focus, f"DEPARTMENT {index} OF {len(departments)}"
                   + (f"  -  {', '.join(focus.get('campuses') or [])}" if focus.get("campuses") else ""))
        doc.build(story)
        return buffer.getvalue()

    # ── Cover ────────────────────────────────────────────────────────────
    overall = pack.get("overall_dept") or {}
    story += [
        tiles([(str(totals.get("registered", 0)), "Registered on the portal"),
               (str(totals.get("took", 0)), "Took Deeksharambh"),
               (str(totals.get("missing", 0)), "Still to reach"),
               (_pct(totals.get("pct")), "Conversion")]),
        Spacer(1, 8),
    ]
    if overall.get("synopsis"):
        story += [Paragraph("At a glance", S["h3"]),
                  box([Paragraph(_text(overall["synopsis"]), S["syn"])], MIST, BLUE), Spacer(1, 8)]
    story += [
        Paragraph("Inside this report", S["h3"]),
        Paragraph(f'<font color="{GOLD}"><b>01</b></font>&nbsp;&nbsp;Registered on the portal and '
                  "who took Deeksharambh - every department", S["toc"]),
        Paragraph(f'<font color="{GOLD}"><b>02</b></font>&nbsp;&nbsp;The most active departments, '
                  "and the most room to grow", S["toc"]),
        Paragraph(f'<font color="{GOLD}"><b>03</b></font>&nbsp;&nbsp;Overall - all departments: '
                  "summary, strengths and gaps, what students want next, every question",
                  S["toc"]),
        Paragraph(f'<font color="{GOLD}"><b>04</b></font>&nbsp;&nbsp;Department by department - '
                  f"{len(departments)} departments, most replies first", S["toc"]),
        Spacer(1, 8),
        Paragraph("Counts read from the registration portal, the Deeksharambh replies and the AI "
                  "post survey directly; no figure in this document is estimated.", S["lede"]),
    ]
    if totals.get("unmatched"):
        n = totals["unmatched"]
        story.append(box([Paragraph(
            f"<b>{n}</b> Deeksharambh {'reply' if n == 1 else 'replies'} came from an email address "
            "with no portal registration. Those replies are read in the analysis but cannot appear "
            f"in the registered count, which is why the two totals differ by exactly {n}.",
            S["note"])], AMBER_SOFT, AMBER, 6))
    story.append(PageBreak())

    # ── 01 · The count, most students first ──────────────────────────────
    story += heading("01", "Registered on the portal, and who took Deeksharambh",
                     "Every student the portal registered is in the count, whether or not they "
                     "opened the baseline survey. Departments are listed by how many took "
                     "Deeksharambh, most first.")
    ranked = sorted(pack.get("conversion", []),
                    key=lambda r: (-r["took"], -r["pct"], r["dept"].lower()))
    rows = [[Paragraph(x, S["th"]) for x in ("#", "DEPARTMENT", "CAMPUS")] +
            [Paragraph(x, S["thr"]) for x in ("REG.", "TOOK", "TO REACH")] +
            [Paragraph("CONVERSION", S["th"])]]
    conv_w = 42 * mm
    for i, row in enumerate(ranked, start=1):
        rows.append([
            Paragraph(str(i), S["cell"]),
            Paragraph(_text(row["dept"]), S["cellb"]),
            Paragraph(_text(", ".join(row.get("campuses") or [])) or "-", S["cell"]),
            Paragraph(str(row["registered"]), S["cellr"]),
            Paragraph(f"<b>{row['took']}</b>", S["cellr"]),
            Paragraph(str(row["missing"]), S["cellr"]),
            Table([[Bar(row["pct"], conv_w - 28 * mm, BLUE),
                    Paragraph(f"<b>{_pct(row['pct'])}</b>", S["cellr"])]],
                  colWidths=[conv_w - 25 * mm, 15 * mm],
                  style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                         ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("No students registered in this scope yet.", S["cell"])] +
                    [Paragraph("", S["cell"])] * 6)
    fixed = 9 * mm + 24 * mm + 2 * 13 * mm + 17 * mm + conv_w
    story += [grid(rows, [9 * mm, content_w - fixed, 24 * mm, 13 * mm, 13 * mm, 17 * mm, conv_w]),
              PageBreak()]

    # ── 02 · Most active / room to grow ──────────────────────────────────
    callouts = pack.get("callouts", {})
    story += heading("02", "The most active departments, and the most room to grow",
                     "Ranked on conversion. Departments level on percentage are split by how many "
                     "students that percentage stands for. The second list is not a ranking of "
                     "failure - it is where the next push reaches the most students.")
    if callouts.get("overlap"):
        story.append(box([Paragraph(
            f"Only {callouts.get('ranked', 0)} departments have students registered in this scope, "
            f"so {_text(', '.join(callouts['overlap']))} appear in both lists.", S["note"])],
            AMBER_SOFT, AMBER, 6))
    for title, key, fill in (
        (f"Most active {len(callouts.get('top', []))}", "top", GREEN),
        (f"Room to grow - {len(callouts.get('least', []))} departments", "least", AMBER),
    ):
        story += [Spacer(1, 6), Paragraph(_text(title), S["h3"])]
        rows = [[Paragraph("#", S["th"]), Paragraph("DEPARTMENT", S["th"]),
                 Paragraph("TOOK / REGISTERED", S["thr"]), Paragraph("CONVERSION", S["thr"])]]
        for i, row in enumerate(callouts.get(key) or [], start=1):
            rows.append([Paragraph(str(i), S["cell"]), Paragraph(_text(row["dept"]), S["cellb"]),
                         Paragraph(f"{row['took']} / {row['registered']}", S["cellr"]),
                         Paragraph(f"<b>{_pct(row['pct'])}</b>", S["cellr"])])
        if len(rows) == 1:
            rows.append([Paragraph("Nothing to rank yet.", S["cell"])] + [Paragraph("", S["cell"])] * 3)
        story.append(grid(rows, [9 * mm, content_w - 9 * mm - 40 * mm - 28 * mm, 40 * mm, 28 * mm],
                          head_fill=fill))

    # ── 03 · Overall ─────────────────────────────────────────────────────
    if overall:
        story += [PageBreak()] + heading(
            "03", "Overall - all departments",
            "The whole scope read the way one department is: the same summary, strengths and gaps, "
            "what students want next, and every question with every answer.")
        story += department_reading(overall, f"ALL {len(departments)} DEPARTMENTS - {campus_raw}")

    # ── 04 · Department by department ────────────────────────────────────
    story += [PageBreak()] + heading(
        "04", "Department by department",
        f"All {len(departments)} departments, most Deeksharambh replies first. Each starts on its "
        "own page.")
    for i, d in enumerate(departments, start=1):
        if i > 1:
            story.append(PageBreak())
        story += department_reading(
            d, f"DEPARTMENT {i} OF {len(departments)}"
               + (f"  -  {', '.join(d.get('campuses') or [])}" if d.get("campuses") else ""))
    if not departments:
        story.append(Paragraph("No departments in this scope yet.", S["none"]))

    doc.build(story)
    return buffer.getvalue()
