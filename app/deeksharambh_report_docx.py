"""
deeksharambh_report_docx.py — the Deeksharambh 2026 overall report, as Word and PDF.

Laid out like the department AI Survey Outcome & Impact reports (the BBA one is
the model): a cover with the JAIN logo, numbered sections in navy Times New
Roman with a teal rule, number tiles for the headline figures, a "Key findings"
list, navy-headed tables and captioned charts.

  Cover · 1 Executive Summary · 2 Theme · 3 Our Approach (the flow, the
  participation table and chart) · 4 AI Survey: Before and After · 5 Student
  Feedback (one sub-section and chart per survey section) · 6 What Students
  Want Next · 7 Strengths and Gaps · 8 Way Forward

Every sentence of prose is the short summary's own (`summary_paragraphs`), so
the two documents never disagree; the tables and charts are read from the same
live pack.
"""
from __future__ import annotations

import html
import io
import re
from pathlib import Path

from app.deeksharambh_summary_pdf import (
    DEPARTMENTS, SCHOOL_THEMES, THEME, _Answers, _n, _p, _text, summary_paragraphs,
)

NAVY = "1F3A5F"
TEAL = "2A9D8F"
INK = "222222"
GREY = "555555"
TILE = "EAF0F7"
ZEBRA = "F6F8FB"
RULE = "D9DEE7"
FONT = "Times New Roman"

LOGO = Path(__file__).resolve().parent / "static" / "logo.png"     # dark, for white paper

# Chart colours, as the department reports draw them.
C_SLATE, C_NAVY, C_TEAL, C_GOLD = "#8DA0B9", "#1F3A5F", "#2A9D8F", "#E9C46A"

# The question each Student Feedback sub-section charts.
SECTION_CHART = {
    "Transition and Settling In": ("q5", "Ease of transition into university life"),
    "Pre-Arrival Preparation (Footsteps)": ("q9", "Most useful Footsteps content"),
    "Orientation Programme Experience": ("q11", "Sessions with the biggest impact"),
    "Bridge Course": ("q17", "Bridge Course areas that helped most"),
    "NEP 2020 and Digital Readiness": ("q21", "Understands ABC ID / APAAR / credits after"),
    "Student Perspective": ("q23b", "Now thinks university will be"),
    "Belonging and Expectations": ("q33", "Top academic expectations"),
    "Student Experience Ratings": ("q1", "Words describing the Deeksharambh experience"),
}


def _plain(text) -> str:
    """Printable label text, no markup."""
    return html.unescape(_text(text))


# ── Word helpers ─────────────────────────────────────────────────────────────

def _rgb(hex_colour: str):
    from docx.shared import RGBColor
    return RGBColor.from_string(hex_colour)


def _font(run, *, size=12, bold=False, italic=False, colour=INK):
    from docx.oxml.ns import qn
    from docx.shared import Pt
    run.font.name = FONT
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = _rgb(colour)
    return run


def _rich(paragraph, markup: str, *, size=12, colour=INK):
    """Add the short summary's light markup (<b>, <i>, entities) as Word runs."""
    bold = italic = False
    for part in re.split(r"(</?[bi]>)", markup):
        if part in ("<b>", "</b>"):
            bold = part == "<b>"
        elif part in ("<i>", "</i>"):
            italic = part == "<i>"
        elif part:
            _font(paragraph.add_run(html.unescape(part)), size=size, bold=bold, italic=italic,
                  colour=colour)
    return paragraph


def _spacing(paragraph, before=0, after=6, line=1.15):
    from docx.shared import Pt
    pf = paragraph.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), line


def _bottom_rule(paragraph, colour=TEAL, size=12):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", str(size)), ("w:space", "4"), ("w:color", colour)):
        bottom.set(qn(k), v)
    borders.append(bottom)
    p_pr.append(borders)


def _shade(cell, fill: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _cell_borders(cell, *, top=None, others=RULE, top_size=4):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        colour = top if (edge == "top" and top) else others
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(top_size if edge == "top" and top else 4))
        el.set(qn("w:color"), colour)
        borders.append(el)
    tc_pr.append(borders)


def _width(cell, inches: float):
    from docx.shared import Inches
    cell.width = Inches(inches)


class _Doc:
    """The document and its running section numbers."""

    def __init__(self, campus: str):
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Inches, Pt

        self.d = Document()
        sec = self.d.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.top_margin, sec.bottom_margin = Cm(2.3), Cm(2.1)
        sec.left_margin = sec.right_margin = Cm(2.0)
        sec.different_first_page_header_footer = True

        normal = self.d.styles["Normal"]
        normal.font.name = FONT
        normal.font.size = Pt(12)
        normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)

        # Running header: the logo left, the report's name right; page number below.
        head = sec.header.paragraphs[0]
        head.paragraph_format.tab_stops.add_tab_stop(Cm(17.0), alignment=2)
        if LOGO.exists():
            head.add_run().add_picture(str(LOGO), height=Cm(0.9))
        _font(head.add_run(f"\tDeeksharambh 2026 · Overall Report · {campus}"), size=8,
              colour=GREY)
        foot = sec.footer.paragraphs[0]
        foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = _font(foot.add_run("Page "), size=8, colour=GREY)
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), "PAGE")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = "1"
        r.append(t)
        fld.append(r)
        foot._p.append(fld)
        del run
        self.Inches = Inches
        self.n = 0
        self.fig = 0

    # Headings ------------------------------------------------------------
    def h1(self, title: str):
        self.n += 1
        self.sub = 0
        p = self.d.add_paragraph()
        _spacing(p, before=14, after=8)
        _font(p.add_run(f"{self.n}. {title}"), size=20, bold=True, colour=NAVY)
        _bottom_rule(p)
        return p

    def h2(self, title: str):
        self.sub += 1
        p = self.d.add_paragraph()
        _spacing(p, before=10, after=4)
        p.paragraph_format.keep_with_next = True
        _font(p.add_run(f"{self.n}.{self.sub} {title}"), size=14, bold=True, colour=NAVY)
        return p

    def label(self, text: str):
        p = self.d.add_paragraph()
        _spacing(p, before=8, after=3)
        p.paragraph_format.keep_with_next = True
        _font(p.add_run(text), size=14, bold=True, colour=TEAL)
        return p

    # Text ------------------------------------------------------------------
    def para(self, markup: str, *, size=12, colour=INK, after=6):
        p = self.d.add_paragraph()
        _spacing(p, after=after)
        return _rich(p, markup, size=size, colour=colour)

    def bullets(self, items: list[str]):
        for markup in items:
            p = self.d.add_paragraph(style="List Bullet")
            _spacing(p, after=3)
            _rich(p, markup)

    def numbered(self, items: list[str]):
        for markup in items:
            p = self.d.add_paragraph(style="List Number")
            _spacing(p, after=4)
            _rich(p, markup)

    # Tiles and tables ------------------------------------------------------
    def tiles(self, items: list[tuple[str, str]]):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        t = self.d.add_table(rows=1, cols=len(items))
        width = 6.7 / len(items)
        for cell, (value, lab) in zip(t.rows[0].cells, items):
            _width(cell, width)
            _shade(cell, TILE)
            _cell_borders(cell, top=TEAL, others="FFFFFF", top_size=18)
            v = cell.paragraphs[0]
            v.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _spacing(v, before=4, after=0)
            _font(v.add_run(value), size=20 if len(value) < 12 else 16, bold=True, colour=NAVY)
            lp = cell.add_paragraph()
            lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _spacing(lp, after=4)
            _font(lp.add_run(lab), size=9, colour=GREY)
        self.d.add_paragraph()

    def table(self, head: list[str], rows: list[list[str]], widths: list[float]):
        """A navy-headed table that keeps its columns and never splits across a page.
        Figures are centred; text reads from the left."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        def figure_like(text: str) -> bool:
            return bool(re.fullmatch(r"[\d.,%+\-–→ /()]+|-|—", text.strip()))

        t = self.d.add_table(rows=1, cols=len(head))
        t.autofit = False
        numeric = [all(figure_like(r[i]) for r in rows) if rows else False
                   for i in range(len(head))]
        align = [WD_ALIGN_PARAGRAPH.CENTER if numeric[i] else WD_ALIGN_PARAGRAPH.LEFT
                 for i in range(len(head))]
        for i, (cell, text) in enumerate(zip(t.rows[0].cells, head)):
            _shade(cell, NAVY)
            _cell_borders(cell)
            p = cell.paragraphs[0]
            p.alignment = align[i]
            _font(p.add_run(text), size=11, bold=True, colour="FFFFFF")
        for k, row in enumerate(rows):
            cells = t.add_row().cells
            for i, (cell, text) in enumerate(zip(cells, row)):
                _cell_borders(cell)
                if k % 2:
                    _shade(cell, ZEBRA)
                p = cell.paragraphs[0]
                p.alignment = align[i]
                _font(p.add_run(text), size=11)
        for i, col in enumerate(t.columns):
            col.width = self.Inches(widths[i])
            for cell in col.cells:
                _width(cell, widths[i])
        last = len(t.rows) - 1
        for r, row in enumerate(t.rows):
            tr_pr = row._tr.get_or_add_trPr()
            cant = OxmlElement("w:cantSplit")
            tr_pr.append(cant)
            if r == 0:
                tr_pr.append(OxmlElement("w:tblHeader"))
            if r < last:                       # hold the table together on one page
                for cell in row.cells:
                    for para in cell.paragraphs:
                        para.paragraph_format.keep_with_next = True
        del qn
        self.d.add_paragraph()

    def figure(self, png: bytes, caption: str, width: float = 6.0):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        self.fig += 1
        p = self.d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(io.BytesIO(png), width=self.Inches(width))
        c = self.d.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(c, after=10)
        _font(c.add_run(f"Figure {self.fig} — {caption}"), size=10, italic=True, colour=GREY)

    def page_break(self):
        from docx.enum.text import WD_BREAK
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def cover(self, title: str, theme: str, line: str):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Cm
        p = self.d.add_paragraph()
        _spacing(p, before=30, after=4)
        _font(p.add_run("JAIN (DEEMED-TO-BE UNIVERSITY)"), size=11, colour=INK)
        p = self.d.add_paragraph()
        _spacing(p, after=40, line=1.0)
        _font(p.add_run(title), size=36, bold=True, colour=NAVY)
        if LOGO.exists():
            p = self.d.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _spacing(p, after=60)
            p.add_run().add_picture(str(LOGO), width=Cm(11))
        p = self.d.add_paragraph()
        _spacing(p, after=2)
        _font(p.add_run(theme), size=16, colour=NAVY)
        _bottom_rule(p, size=14)
        p = self.d.add_paragraph()
        _spacing(p, before=4)
        _font(p.add_run(line), size=11, colour=GREY)
        self.page_break()

    def save(self) -> bytes:
        buf = io.BytesIO()
        self.d.save(buf)
        return buf.getvalue()


class _Pdf:
    """The `_Doc` interface drawn as a PDF: Times, navy titles, a teal rule, the
    logo and report name across the top of every page, the page number below."""

    def __init__(self, campus: str):
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm

        self.C = lambda h: colors.HexColor("#" + h)
        self.cm, self.A4 = cm, A4
        self.campus = campus
        self.story = []
        self.n = self.sub = self.fig = 0
        self.width = A4[0] - 4.0 * cm

        def st(name, **kw):
            base = dict(fontName="Times-Roman", fontSize=12, leading=16, textColor=self.C(INK),
                        alignment=TA_JUSTIFY)
            base.update(kw)
            return ParagraphStyle(name, **base)

        self.S = {
            "body": st("body", spaceAfter=6),
            "small": st("small", fontSize=10, leading=13, textColor=self.C(GREY)),
            "h1": st("h1", fontName="Times-Bold", fontSize=20, leading=24, textColor=self.C(NAVY),
                     alignment=0, spaceBefore=12, spaceAfter=2),
            "h2": st("h2", fontName="Times-Bold", fontSize=14, leading=18, textColor=self.C(NAVY),
                     alignment=0, spaceBefore=9, spaceAfter=3),
            "label": st("label", fontName="Times-Bold", fontSize=14, leading=18,
                        textColor=self.C(TEAL), alignment=0, spaceBefore=8, spaceAfter=3),
            "list": st("list", spaceAfter=3),
            "cell": st("cell", fontSize=11, leading=13.5, alignment=0),
            "cellc": st("cellc", fontSize=11, leading=13.5, alignment=TA_CENTER),
            "th": st("th", fontName="Times-Bold", fontSize=11, leading=13.5,
                     textColor=colors.white, alignment=0),
            "thc": st("thc", fontName="Times-Bold", fontSize=11, leading=13.5,
                      textColor=colors.white, alignment=TA_CENTER),
            "tile_v": st("tile_v", fontName="Times-Bold", fontSize=20, leading=24,
                         textColor=self.C(NAVY), alignment=TA_CENTER),
            "tile_vs": st("tile_vs", fontName="Times-Bold", fontSize=15, leading=19,
                          textColor=self.C(NAVY), alignment=TA_CENTER),
            "tile_l": st("tile_l", fontSize=9, leading=11, textColor=self.C(GREY),
                         alignment=TA_CENTER),
            "caption": st("caption", fontName="Times-Italic", fontSize=10, leading=12,
                          textColor=self.C(GREY), alignment=TA_CENTER, spaceAfter=10),
            "kicker": st("kicker", fontSize=11, leading=14, alignment=0),
            "title": st("title", fontName="Times-Bold", fontSize=36, leading=40,
                        textColor=self.C(NAVY), alignment=0),
            "theme": st("theme", fontSize=16, leading=20, textColor=self.C(NAVY), alignment=0),
            "line": st("line", fontSize=11, leading=14, textColor=self.C(GREY), alignment=0),
        }

    @staticmethod
    def _esc(text) -> str:
        return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _rule(self, colour=TEAL, thickness=1.2, space=4):
        from reportlab.platypus import HRFlowable
        return HRFlowable(width="100%", thickness=thickness, color=self.C(colour),
                          spaceBefore=1, spaceAfter=space)

    # Headings ------------------------------------------------------------
    def h1(self, title: str):
        from reportlab.platypus import CondPageBreak, Paragraph
        self.n += 1
        self.sub = 0
        self.story += [CondPageBreak(4 * self.cm),
                       Paragraph(f"{self.n}. {self._esc(title)}", self.S["h1"]), self._rule()]

    def h2(self, title: str):
        from reportlab.platypus import CondPageBreak, Paragraph
        self.sub += 1
        self.story += [CondPageBreak(3 * self.cm),
                       Paragraph(f"{self.n}.{self.sub} {self._esc(title)}", self.S["h2"])]

    def label(self, text: str):
        from reportlab.platypus import CondPageBreak, Paragraph
        self.story += [CondPageBreak(3 * self.cm), Paragraph(self._esc(text), self.S["label"])]

    # Text ------------------------------------------------------------------
    def para(self, markup: str, *, size=12, colour=INK, after=6):
        from reportlab.platypus import Paragraph
        style = self.S["small"] if size < 12 else self.S["body"]
        self.story.append(Paragraph(markup, style))

    def _list(self, items, kind):
        from reportlab.platypus import ListFlowable, ListItem, Paragraph
        self.story.append(ListFlowable(
            [ListItem(Paragraph(m, self.S["list"]), leftIndent=16) for m in items],
            bulletType=kind, start="\u2022" if kind == "bullet" else None,
            bulletFormat="%s." if kind == "1" else None, leftIndent=18,
            bulletFontName="Times-Roman", bulletFontSize=12, spaceAfter=6))

    def bullets(self, items: list[str]):
        self._list(items, "bullet")

    def numbered(self, items: list[str]):
        self._list(items, "1")

    # Tiles and tables ------------------------------------------------------
    def tiles(self, items: list[tuple[str, str]]):
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        w = self.width / len(items)
        cells = [[Paragraph(self._esc(v), self.S["tile_v" if len(v) < 12 else "tile_vs"]),
                  Paragraph(self._esc(lab), self.S["tile_l"])] for v, lab in items]
        t = Table([cells], colWidths=[w] * len(items))
        style = [("BACKGROUND", (0, 0), (-1, -1), self.C(TILE)),
                 ("LINEABOVE", (0, 0), (-1, 0), 2.2, self.C(TEAL)),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]
        for i in range(1, len(items)):
            style.append(("LINEBEFORE", (i, 0), (i, 0), 3, self.C("FFFFFF")))
        t.setStyle(TableStyle(style))
        self.story += [t, Spacer(1, 10)]

    def table(self, head: list[str], rows: list[list[str]], widths: list[float]):
        from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

        def figure_like(text: str) -> bool:
            return bool(re.fullmatch(r"[\d.,%+\-–→ /()]+|-|—", text.strip()))

        numeric = [all(figure_like(r[i]) for r in rows) if rows else False
                   for i in range(len(head))]
        scale = self.width / (sum(widths) * 72)
        data = [[Paragraph(self._esc(h), self.S["thc" if numeric[i] else "th"])
                 for i, h in enumerate(head)]]
        data += [[Paragraph(self._esc(v), self.S["cellc" if numeric[i] else "cell"])
                  for i, v in enumerate(r)] for r in rows]
        t = Table(data, colWidths=[w * 72 * scale for w in widths], repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), self.C(NAVY)),
                 ("GRID", (0, 0), (-1, -1), 0.5, self.C(RULE)),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        for k in range(2, len(data), 2):
            style.append(("BACKGROUND", (0, k), (-1, k), self.C(ZEBRA)))
        t.setStyle(TableStyle(style))
        self.story += [KeepTogether([t]), Spacer(1, 10)]

    def figure(self, png: bytes, caption: str, width: float = 6.0):
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image, KeepTogether, Paragraph
        self.fig += 1
        iw, ih = ImageReader(io.BytesIO(png)).getSize()
        w = min(width * 72, self.width)
        img = Image(io.BytesIO(png), width=w, height=w * ih / iw)
        self.story.append(KeepTogether([img, Paragraph(
            f"Figure {self.fig} — {self._esc(caption)}", self.S["caption"])]))

    def page_break(self):
        from reportlab.platypus import PageBreak
        self.story.append(PageBreak())

    def cover(self, title: str, theme: str, line: str):
        from reportlab.platypus import Image, NextPageTemplate, Paragraph, Spacer
        self.story += [Spacer(1, 30), Paragraph("JAIN (DEEMED-TO-BE UNIVERSITY)", self.S["kicker"]),
                       Spacer(1, 4), Paragraph(self._esc(title), self.S["title"]), Spacer(1, 50)]
        if LOGO.exists():
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(str(LOGO)).getSize()
            w = 11 * self.cm
            self.story += [Image(str(LOGO), width=w, height=w * ih / iw), Spacer(1, 70)]
        self.story += [Paragraph(self._esc(theme), self.S["theme"]), self._rule(thickness=1.6),
                       Paragraph(self._esc(line), self.S["line"]),
                       NextPageTemplate("body"), self.page_break_flowable()]

    def page_break_flowable(self):
        from reportlab.platypus import PageBreak
        return PageBreak()

    def save(self) -> bytes:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

        cm, (W, H) = self.cm, self.A4
        campus = self.campus

        def header(canvas, doc):
            canvas.saveState()
            if LOGO.exists():
                from reportlab.lib.utils import ImageReader
                img = ImageReader(str(LOGO))
                iw, ih = img.getSize()
                h = 0.9 * cm
                canvas.drawImage(img, 2 * cm, H - 1.25 * cm - h, width=h * iw / ih, height=h,
                                 mask="auto")
            canvas.setFont("Times-Roman", 8)
            canvas.setFillColor(self.C(GREY))
            canvas.drawRightString(W - 2 * cm, H - 1.25 * cm - 0.6 * cm,
                                   f"Deeksharambh 2026 · Overall Report · {campus}")
            canvas.restoreState()

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Times-Roman", 8)
            canvas.setFillColor(self.C(GREY))
            canvas.drawCentredString(W / 2, 1.1 * cm, f"Page {doc.page}")
            canvas.restoreState()

        def body(canvas, doc):
            header(canvas, doc)
            footer(canvas, doc)

        buf = io.BytesIO()
        doc = BaseDocTemplate(buf, pagesize=self.A4, title="Deeksharambh 2026 — Overall Report",
                              author="JAIN University")
        frame = Frame(2 * cm, 2.1 * cm, W - 4 * cm, H - 2.1 * cm - 2.6 * cm, id="f",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate(id="cover", frames=[frame], onPage=footer),
                              PageTemplate(id="body", frames=[frame], onPage=body)])
        doc.build(self.story)
        return buf.getvalue()


# ── Charts ───────────────────────────────────────────────────────────────────

def _png(fig) -> bytes:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _bars(labels, values, colours, title, ylabel="Students"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    bars = ax.bar(labels, values, color=colours, width=0.6)
    for b, v in zip(bars, values):
        ax.annotate(f"{v:,}", (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=8, xytext=(0, 2), textcoords="offset points")
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    return _png(fig)


def _grouped(labels, before, after, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    x = range(len(labels))
    w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], before, w, color=C_SLATE, label="Before (baseline)")
    b2 = ax.bar([i + w / 2 for i in x], after, w, color=C_NAVY, label="After (post)")
    for bars in (b1, b2):
        for b in bars:
            ax.annotate(f"{b.get_height():.2f}", (b.get_x() + b.get_width() / 2, b.get_height()),
                        ha="center", va="bottom", fontsize=8, xytext=(0, 2),
                        textcoords="offset points")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 5.4)
    ax.set_ylabel("Average out of 5", fontsize=9)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.legend(fontsize=8, frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.12))
    ax.spines[["top", "right"]].set_visible(False)
    return _png(fig)


def _hbars(options: list[dict], title: str, colour=C_TEAL, top: int = 6):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    opts = options[:top][::-1]
    labels = [_plain(o["label"]) for o in opts]
    labels = [lab if len(lab) <= 46 else lab[:44] + "…" for lab in labels]
    vals = [o.get("pct") or 0 for o in opts]
    fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(opts) + 0.9))
    ax.barh(labels, vals, color=colour, height=0.6)
    for i, v in enumerate(vals):
        ax.text(v + 0.8, i, f"{v:.1f}%", va="center", fontsize=8)
    ax.set_xlim(0, max(vals + [10]) * 1.18)
    ax.set_xlabel("Share of students who answered (%)", fontsize=8)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    return _png(fig)


# ── The report ───────────────────────────────────────────────────────────────

def build_report_docx(pack: dict, *, generated_at: str, ai: dict | None = None) -> bytes:
    """The overall report as Word."""
    W = _Doc(_plain(pack.get("campus") or "All campuses"))
    _write_report(W, pack, generated_at=generated_at, ai=ai)
    return W.save()


def build_report_pdf(pack: dict, *, generated_at: str, ai: dict | None = None) -> bytes:
    """The same report, page for page in the same order, as a PDF."""
    W = _Pdf(_plain(pack.get("campus") or "All campuses"))
    _write_report(W, pack, generated_at=generated_at, ai=ai)
    return W.save()


def _write_report(W, pack: dict, *, generated_at: str, ai: dict | None) -> None:
    """Everything the report says, written to either writer (`_Doc` or `_Pdf`)."""
    campus = _plain(pack.get("campus") or "All campuses")
    text = summary_paragraphs(pack, ai)
    d = pack.get("overall_dept") or {}
    a = _Answers(d)
    t = pack.get("totals") or {}
    h = d.get("headline") or {}
    j = (ai or {}).get("journey") or {}
    sc = (ai or {}).get("scores") or {}
    registered = t.get("registered", 0)

    W.cover("Deeksharambh 2026 — Overall Report", THEME,
            f"Student orientation feedback and the AI survey · {DEPARTMENTS} departments · "
            f"{campus} · Generated {generated_at}")

    # ── 1. Executive summary ─────────────────────────────────────────────
    W.h1("Executive Summary")
    W.para("This report brings together Deeksharambh 2026 for all departments: how students moved "
           "from the AI pre survey through the Deeksharambh orientation week and Bridge Course to "
           "the AI post survey, what they said about every part of the programme, and what they "
           "expect from JAIN next.")
    took_pct = t.get("pct") or 0
    tiles = [(_n(registered), "Registered"),
             (_n(t.get("took", 0)), f"Completed Deeksharambh ({_p(took_pct)})")]
    if j.get("baseline") is not None:
        tiles.append((_n(j["baseline"]), f"AI pre survey ({_p(j.get('baseline_pct') or 0)})"))
    if j.get("post") is not None:
        tiles.append((_n(j["post"]), f"AI post survey ({_p(j.get('post_pct') or 0)})"))
    W.tiles(tiles)
    second = []
    if h.get("vibe") is not None:
        second.append((f"{h['vibe']}/10", "Vibe of the week"))
    welcomed = a.share("q3", "Strongly Agree", "Agree")
    if welcomed is not None:
        second.append((_p(welcomed), "Felt welcomed"))
    if h.get("belonging") is not None:
        second.append((f"{h['belonging']}/10", "Belonging"))
    if h.get("nps") is not None:
        second.append((f"{h['nps']:+g}", "Would recommend (-100 to +100)"))
    overall = sc.get("overall") or {}
    if overall.get("before") is not None and overall.get("after") is not None and len(second) < 5:
        second.append((f"{overall['before']} → {overall['after']}", "Overall AI score"))
    if second:
        W.tiles(second[:4])

    W.label("Key findings")
    findings = [f"<b>Participation.</b> {_n(t.get('took', 0))} of {_n(registered)} registered "
                f"students ({_p(took_pct)}) completed Deeksharambh across {DEPARTMENTS} departments."]
    if text["glance"]:
        findings.append(f"<b>How the week felt.</b> {text['glance']}")
    for title, para in text["feedback"]:
        if title == "NEP 2020 and Digital Readiness":
            short = " ".join(re.split(r"(?<=\.)\s+(?=[A-Z])", para)[:2])
            findings.append(f"<b>NEP 2020 awareness moved.</b> {short}")
        if title == "Student Perspective":
            stress = a.top("q28", 2)
            if stress:
                findings.append("<b>The main stress was the schedule.</b> "
                                + ", ".join(f"{_plain(o['label'])} ({_p(o['pct'])})" for o in stress)
                                + " were what stressed students most.")
    findings.append(f"<b>What students want next.</b> {text['next']}")
    if overall.get("before") is not None and overall.get("after") is not None:
        findings.append(f"<b>AI survey.</b> The average AI score moved from {overall['before']} to "
                        f"{overall['after']} ({overall['change']:+.2f}) between the pre and post "
                        "survey.")
    W.bullets(findings)
    W.para(f"<b>Read with care:</b> the student feedback describes the {_n(t.get('took', 0))} "
           f"students who completed Deeksharambh ({_p(took_pct)} of those registered); shares are "
           "of the students who answered each question.", after=10)

    # ── 2. Theme ─────────────────────────────────────────────────────────
    W.h1("Theme")
    W.para(text["theme"])
    W.table(["School", "How the school carried the theme"],
            [[s, line] for s, line in SCHOOL_THEMES], [2.4, 4.3])

    # ── 3. Our approach ──────────────────────────────────────────────────
    W.h1("Our Approach")
    W.para(text["approach_intro"])
    W.numbered(text["approach_steps"])
    stages = [("Registered on the portal", registered)]
    if j.get("baseline") is not None:
        stages.append(("AI pre survey (baseline)", j["baseline"]))
    stages.append(("Completed Deeksharambh", t.get("took", 0)))
    if j.get("post") is not None:
        stages.append(("AI post survey", j["post"]))
    W.table(["Stage", "Students", "Share of registered"],
            [[s, _n(v), _p(100.0 * v / registered) if registered else "-"] for s, v in stages],
            [3.4, 1.4, 1.9])
    W.figure(_bars([s.replace(" (baseline)", "\n(baseline)").replace("Registered on the portal",
                                                                      "Registered")
                    for s, _v in stages], [v for _s, v in stages],
                   [C_SLATE, C_NAVY, C_TEAL, C_GOLD][:len(stages)], "Participation at each stage"),
             "Participation at each stage")

    # ── 4. AI survey before and after ────────────────────────────────────
    measures = [("AI literacy", sc.get("literacy") or {}), ("AI readiness", sc.get("readiness") or {}),
                ("Overall AI score", overall)]
    measures = [(m, v) for m, v in measures if v.get("before") is not None and v.get("after") is not None]
    if measures:
        W.h1("AI Survey: Before and After")
        W.para("The same AI survey was taken before the programme (the baseline) and after it (the "
               "post survey). Literacy is knowing how AI works and where it fails; readiness is "
               "being willing and able to work with it. Scores are averages out of 5.")
        W.table(["Measure", f"Before (n = {_n(sc.get('before_n') or j.get('baseline') or 0)})",
                 f"After (n = {_n(sc.get('after_n') or j.get('post') or 0)})", "Change"],
                [[m, f"{v['before']}", f"{v['after']}", f"{v.get('change') or 0:+.2f}"]
                 for m, v in measures], [2.5, 1.5, 1.5, 1.2])
        W.figure(_grouped([m for m, _v in measures], [v["before"] for _m, v in measures],
                          [v["after"] for _m, v in measures], "Average scores before and after"),
                 "AI survey averages before and after")

    # ── 5. Student feedback ──────────────────────────────────────────────
    W.page_break()
    W.h1("Student Feedback")
    W.para("What the students who completed Deeksharambh said, section by section. Each "
           "sub-section explains the section in a few lines, with the question that best shows it.")
    for title, para in text["feedback"]:
        W.h2(title)
        W.para(para)
        key, chart_title = SECTION_CHART.get(title, (None, ""))
        opts = a.options(key) if key else []
        if opts:
            W.figure(_hbars(opts, chart_title), f"{chart_title} (top answers)", width=5.6)

    # ── 6. What students want next ───────────────────────────────────────
    W.h1("What Students Want Next")
    W.para(text["next"])
    c = d.get("career") or {}
    if c.get("answered"):
        rows = []
        for g in c["groups"]:
            parts = "; ".join(f"{_plain(sg['label'])} {sg['count']}" for sg in g["signals"])
            rows.append([_plain(g["label"]), _n(g["count"]), _p(g["pct"]), parts])
        W.table(["Interest", "Students", f"% of {_n(c['answered'])}", "Counted from"], rows,
                [1.9, 0.9, 0.9, 3.0])

    # ── 7. Strengths and gaps ────────────────────────────────────────────
    if d.get("strengths") or d.get("gaps"):
        W.h1("Strengths and Gaps")
        W.para("The questions with the clearest lead on their good end (strengths), and the asks "
               "and complaints students raised most (gaps).")
        if d.get("strengths"):
            W.label("Strengths")
            W.table(["Question", "Top answer", "Share"],
                    [[_plain(s["label"]), _plain(s["top"]), _p(s["pct"])] for s in d["strengths"]],
                    [2.9, 2.8, 1.0])
        if d.get("gaps"):
            W.label("Gaps")
            W.table(["Question", "Top answer", "Share"],
                    [[_plain(g["label"]), _plain(g["top"]), _p(g["pct"])] for g in d["gaps"]],
                    [2.9, 2.8, 1.0])

    # ── 8. Way forward ───────────────────────────────────────────────────
    if text["way"]:
        W.h1("Way Forward")
        W.bullets(text["way"])
    W.para("Counts are read directly from the registration portal, the Deeksharambh replies and "
           "the AI surveys; no figure in this report is estimated.", size=10, colour=GREY)


async def report_pdf_response(*, campus: str = ""):
    """The overall report as a PDF attachment: the Word report, page for page."""
    from datetime import datetime

    from fastapi.responses import StreamingResponse

    from app.deeksharambh_meeting import meeting_pack
    from app.outcome_departments import outcome_pack
    from app.routes.shared_analysis import _in_thread

    pack = await meeting_pack(campus=campus)
    ai = (await outcome_pack(campus=campus))["overall"]
    data = await _in_thread(build_report_pdf, pack, ai=ai,
                            generated_at=datetime.now().strftime("%d %b %Y, %H:%M"))
    name = f"Deeksharambh_2026_Overall_Report_{campus or 'All'}.pdf"
    name = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def report_docx_response(*, campus: str = ""):
    """The overall Word report as an attachment."""
    from datetime import datetime

    from fastapi.responses import StreamingResponse

    from app.deeksharambh_meeting import meeting_pack
    from app.outcome_departments import outcome_pack
    from app.routes.shared_analysis import _in_thread

    pack = await meeting_pack(campus=campus)
    ai = (await outcome_pack(campus=campus))["overall"]
    data = await _in_thread(build_report_docx, pack, ai=ai,
                            generated_at=datetime.now().strftime("%d %b %Y, %H:%M"))
    name = f"Deeksharambh_2026_Overall_Report_{campus or 'All'}.docx"
    name = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})
