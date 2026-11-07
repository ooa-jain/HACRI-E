"""
deeksharambh_report_docx.py — the Deeksharambh 2026 overall report as Word.

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
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm

    campus = _plain(pack.get("campus") or "All campuses")
    text = summary_paragraphs(pack, ai)
    d = pack.get("overall_dept") or {}
    a = _Answers(d)
    t = pack.get("totals") or {}
    h = d.get("headline") or {}
    j = (ai or {}).get("journey") or {}
    sc = (ai or {}).get("scores") or {}
    registered = t.get("registered", 0)

    W = _Doc(campus)
    doc = W.d

    # ── Cover ────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    _spacing(p, before=30, after=4)
    _font(p.add_run("JAIN (DEEMED-TO-BE UNIVERSITY)"), size=11, colour=INK)
    p = doc.add_paragraph()
    _spacing(p, after=40, line=1.0)
    _font(p.add_run("Deeksharambh 2026 — Overall Report"), size=36, bold=True, colour=NAVY)
    if LOGO.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, after=60)
        p.add_run().add_picture(str(LOGO), width=Cm(11))
    p = doc.add_paragraph()
    _spacing(p, after=2)
    _font(p.add_run(THEME), size=16, colour=NAVY)
    _bottom_rule(p, size=14)
    p = doc.add_paragraph()
    _spacing(p, before=4)
    _font(p.add_run(f"Student orientation feedback and the AI survey · {DEPARTMENTS} departments · "
                    f"{campus} · Generated {generated_at}"), size=11, colour=GREY)
    W.page_break()

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

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


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
