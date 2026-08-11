"""
orientation_ppt.py — the Deeksharambh orientation report as a slide deck.

Built to be read from the back of a room: one idea per slide, the number large,
the mood named in words, and the charts from `orientation_charts` doing the
explaining. Everything comes from `summarize_orientation()`, so the deck and
the dashboard can never tell different stories.
"""
from __future__ import annotations

import io
import tempfile
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from app.orientation_charts import (
    clean, mood_for, plot_dept_vibe, plot_feeling_meters, plot_nps_ring,
    plot_response_rate, plot_top_options, plot_vibe_hero,
)

NAVY = RGBColor(0x0D, 0x21, 0x47)
GOLD = RGBColor(0xE6, 0xB3, 0x24)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1A, 0x1A, 0x2E)
MUTED = RGBColor(0x64, 0x74, 0x8B)
MIST = RGBColor(0xF1, 0xF5, 0xF9)
TEAL = RGBColor(0x0D, 0x94, 0x88)
ROSE = RGBColor(0xE1, 0x1D, 0x48)
AMBER = RGBColor(0xF5, 0x9E, 0x0B)
GREEN = RGBColor(0x05, 0x96, 0x69)

W = Inches(13.333)
H = Inches(7.5)
RECT = 1  # MSO_SHAPE.RECTANGLE
ROUND = 5  # MSO_SHAPE.ROUNDED_RECTANGLE


def _hex(colour: str) -> RGBColor:
    return RGBColor.from_string(colour.lstrip("#").upper())


def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _text(slide, left, top, width, height, text, *, size=18, bold=False,
          colour=INK, align=PP_ALIGN.LEFT, italic=False):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    para = frame.paragraphs[0]
    para.text = text
    para.alignment = align
    para.font.size = Pt(size)
    para.font.bold = bold
    para.font.italic = italic
    para.font.color.rgb = colour
    return box


def _band(slide, colour=NAVY, height=Inches(0.16), top=Emu(0)):
    bar = slide.shapes.add_shape(RECT, Emu(0), top, W, height)
    bar.fill.solid()
    bar.fill.fore_color.rgb = colour
    bar.line.fill.background()
    return bar


def _heading(slide, title: str, kicker: str = "") -> None:
    _band(slide, GOLD, Inches(0.12))
    if kicker:
        _text(slide, Inches(0.7), Inches(0.32), Inches(11.9), Inches(0.3),
              kicker.upper(), size=11, bold=True, colour=GOLD)
    _text(slide, Inches(0.7), Inches(0.58), Inches(11.9), Inches(0.7),
          title, size=28, bold=True, colour=NAVY)


def _card(slide, left, top, width, height, value: str, label: str,
          accent: RGBColor, value_size=40):
    shape = slide.shapes.add_shape(ROUND, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = MIST
    shape.line.color.rgb = MIST
    shape.shadow.inherit = False
    stripe = slide.shapes.add_shape(RECT, left, top, Inches(0.07), height)
    stripe.fill.solid()
    stripe.fill.fore_color.rgb = accent
    stripe.line.fill.background()

    frame = shape.text_frame
    frame.word_wrap = True
    frame.margin_top = Inches(0.25)
    head = frame.paragraphs[0]
    head.text = value
    head.alignment = PP_ALIGN.CENTER
    head.font.size = Pt(value_size)
    head.font.bold = True
    head.font.color.rgb = accent
    sub = frame.add_paragraph()
    sub.text = label
    sub.alignment = PP_ALIGN.CENTER
    sub.font.size = Pt(12)
    sub.font.bold = True
    sub.font.color.rgb = MUTED


def _picture(slide, image: Path, left, top, max_w, max_h) -> None:
    """Drop a chart in, scaled to fit its box and centred in it.

    Charts are as tall as their data needs (one bar per department), so a
    fixed width alone would push the long ones off the bottom of the slide.
    """
    if not image or not Path(image).exists():
        return
    from PIL import Image

    with Image.open(image) as img:
        px_w, px_h = img.size
    scale = min(max_w / px_w, max_h / px_h)
    width, height = int(px_w * scale), int(px_h * scale)
    slide.shapes.add_picture(
        str(image),
        left + int((max_w - width) / 2),
        top + int((max_h - height) / 2),
        width=width, height=height,
    )


def _fmt(value, digits=1, suffix="") -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def _bullets(slide, left, top, width, height, rows: list[dict], accent: RGBColor,
             empty: str = "No answers yet") -> None:
    """A ranked list of options with their counts — used beside the charts."""
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    if not rows:
        para = frame.paragraphs[0]
        para.text = empty
        para.font.size = Pt(13)
        para.font.italic = True
        para.font.color.rgb = MUTED
        return
    for i, row in enumerate(rows):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.text = f"{i + 1}.  {clean(row['label'], 46)}"
        para.font.size = Pt(14)
        para.font.bold = i == 0
        para.font.color.rgb = accent if i == 0 else INK
        tail = frame.add_paragraph()
        tail.text = f"      {row['count']} students · {row.get('pct', 0):.0f}%"
        tail.font.size = Pt(11)
        tail.font.color.rgb = MUTED


def generate_orientation_ppt(
    *,
    campus: str,
    scope: str,
    report: dict,
    departments: list[dict],
) -> bytes:
    """Build the deck. `report` is a summarize_orientation() result."""
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H

    head = report.get("headline", {})
    cover = report.get("coverage", {})
    highlights = report.get("highlights", {})
    questions = {q["key"]: q for s in report.get("sections", []) for q in s["questions"]}
    mood_word, mood_hex = mood_for(head.get("vibe"))

    # ── Slide 1 · Cover ───────────────────────────────────────────────────────
    slide = _blank(prs)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = NAVY
    stripe = slide.shapes.add_shape(RECT, Emu(0), Inches(2.62), W, Inches(0.06))
    stripe.fill.solid()
    stripe.fill.fore_color.rgb = GOLD
    stripe.line.fill.background()

    _text(slide, Inches(0.9), Inches(1.35), Inches(11.5), Inches(0.4),
          "DEEKSHARAMBH 2026 · JAIN UNIVERSITY", size=14, bold=True, colour=GOLD)
    _text(slide, Inches(0.9), Inches(1.8), Inches(11.5), Inches(0.9),
          "Orientation Experience Report", size=42, bold=True, colour=WHITE)
    _text(slide, Inches(0.9), Inches(2.85), Inches(11.5), Inches(0.5),
          f"{campus}  ·  {scope}", size=20, colour=WHITE)
    _text(slide, Inches(0.9), Inches(3.35), Inches(11.5), Inches(0.4),
          f"{report.get('count', 0)} student responses  ·  generated {datetime.now():%d %B %Y}",
          size=13, italic=True, colour=RGBColor(0xB4, 0xC0, 0xD4))

    # The one number the room came for.
    hero = slide.shapes.add_shape(ROUND, Inches(0.9), Inches(4.15), Inches(4.2), Inches(2.35))
    hero.fill.solid()
    hero.fill.fore_color.rgb = _hex(mood_hex)
    hero.line.fill.background()
    hero.shadow.inherit = False
    frame = hero.text_frame
    frame.margin_top = Inches(0.3)
    top_line = frame.paragraphs[0]
    top_line.text = _fmt(head.get("vibe"), 1, " / 10")
    top_line.alignment = PP_ALIGN.CENTER
    top_line.font.size = Pt(48)
    top_line.font.bold = True
    top_line.font.color.rgb = WHITE
    bottom = frame.add_paragraph()
    bottom.text = f"OVERALL VIBE · {mood_word.upper()}"
    bottom.alignment = PP_ALIGN.CENTER
    bottom.font.size = Pt(14)
    bottom.font.bold = True
    bottom.font.color.rgb = WHITE

    for i, (value, label) in enumerate([
        (_fmt(head.get("nps"), 0, ""), "Net Promoter Score"),
        (_fmt(head.get("belonging"), 1, " / 10"), "Sense of belonging"),
        (_fmt(cover.get("pct"), 0, "%"), "Response rate"),
    ]):
        left = Inches(5.5) + i * Inches(2.65)
        box = slide.shapes.add_shape(ROUND, left, Inches(4.15), Inches(2.4), Inches(2.35))
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(0x14, 0x2C, 0x59)
        box.line.color.rgb = RGBColor(0x2A, 0x40, 0x69)
        box.shadow.inherit = False
        tf = box.text_frame
        tf.margin_top = Inches(0.45)
        p1 = tf.paragraphs[0]
        p1.text = value
        p1.alignment = PP_ALIGN.CENTER
        p1.font.size = Pt(34)
        p1.font.bold = True
        p1.font.color.rgb = GOLD
        p2 = tf.add_paragraph()
        p2.text = label
        p2.alignment = PP_ALIGN.CENTER
        p2.font.size = Pt(12)
        p2.font.color.rgb = WHITE

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # ── Slide 2 · Participation ───────────────────────────────────────────
        slide = _blank(prs)
        _heading(slide, "Who answered", "Participation")
        for i, (value, label, accent) in enumerate([
            (str(report.get("count", 0)), "Responses", NAVY),
            (_fmt(cover.get("pct"), 0, "%"), "Response rate", TEAL),
            (str(cover.get("pending", 0)), "Still pending", AMBER),
            (str(len(report.get("departments", []))), "Departments covered", GOLD),
        ]):
            _card(slide, Inches(0.7) + i * Inches(3.15), Inches(1.6),
                  Inches(2.85), Inches(1.9), value, label, accent)

        rate_img = plot_response_rate(departments, tmpdir / "rate.png")
        _picture(slide, rate_img, Inches(0.7), Inches(3.75), Inches(11.9), Inches(3.4))

        # ── Slide 3 · The vibe ────────────────────────────────────────────────
        slide = _blank(prs)
        _heading(slide, f"Overall vibe — {mood_word.lower()}", "How the week felt")
        vibe_img = plot_vibe_hero(questions.get("q2", {"options": [], "avg": head.get("vibe")}),
                                  tmpdir / "vibe.png")
        _picture(slide, vibe_img, Inches(0.7), Inches(1.55), Inches(8.6), Inches(5.4))

        _card(slide, Inches(9.6), Inches(1.7), Inches(3.0), Inches(1.6),
              _fmt(head.get("vibe"), 1), "Average vibe / 10", _hex(mood_hex), value_size=36)
        _card(slide, Inches(9.6), Inches(3.5), Inches(3.0), Inches(1.6),
              _fmt(head.get("belonging"), 1), "I belong here / 10", TEAL, value_size=36)
        _card(slide, Inches(9.6), Inches(5.3), Inches(3.0), Inches(1.6),
              _fmt(head.get("success"), 1), "I can succeed / 10", GOLD, value_size=36)

        # ── Slide 4 · Feeling meters + welcome ────────────────────────────────
        slide = _blank(prs)
        _heading(slide, "The mood, measured", "Headline averages")
        meters = plot_feeling_meters([
            ("Overall vibe", head.get("vibe"), 10),
            ("Sense of belonging", head.get("belonging"), 10),
            ("Confidence of succeeding", head.get("success"), 10),
            ("Bridge course confidence", head.get("bridge"), 5),
            ("Recommendation score", head.get("nps_avg"), 10),
        ], tmpdir / "meters.png", title="")
        _picture(slide, meters, Inches(0.7), Inches(1.6), Inches(7.6), Inches(5.3))

        _text(slide, Inches(8.7), Inches(1.6), Inches(4.0), Inches(0.4),
              "FELT WELCOMED", size=12, bold=True, colour=GOLD)
        _bullets(slide, Inches(8.7), Inches(2.0), Inches(4.0), Inches(2.2),
                 (questions.get("q3", {}).get("options") or [])[:4], TEAL)
        _text(slide, Inches(8.7), Inches(4.3), Inches(4.0), Inches(0.4),
              "WORDS THEY CHOSE", size=12, bold=True, colour=GOLD)
        _bullets(slide, Inches(8.7), Inches(4.7), Inches(4.0), Inches(2.5),
                 (questions.get("q1", {}).get("options") or [])[:4], NAVY)

        # ── Slide 5 · Recommendation ──────────────────────────────────────────
        slide = _blank(prs)
        _heading(slide, "Would they recommend JAIN?", "Net Promoter Score")
        ring = plot_nps_ring(questions.get("q34") or {
            "promoters": head.get("promoters", 0),
            "passives": head.get("passives", 0),
            "detractors": head.get("detractors", 0),
            "nps": head.get("nps"),
        }, tmpdir / "nps.png")
        _picture(slide, ring, Inches(0.9), Inches(1.7), Inches(6.0), Inches(5.2))

        _text(slide, Inches(7.4), Inches(1.8), Inches(5.2), Inches(0.4),
              "WHAT WORKED", size=12, bold=True, colour=GOLD)
        _bullets(slide, Inches(7.4), Inches(2.2), Inches(5.2), Inches(2.0),
                 (highlights.get("keep") or [])[:3], GREEN)
        _text(slide, Inches(7.4), Inches(4.3), Inches(5.2), Inches(0.4),
              "WHAT DRAGGED", size=12, bold=True, colour=GOLD)
        _bullets(slide, Inches(7.4), Inches(4.7), Inches(5.2), Inches(2.5),
                 (highlights.get("needs_work") or [])[:3], ROSE)

        # ── Slide 6 · Department vibe ─────────────────────────────────────────
        slide = _blank(prs)
        _heading(slide, "Vibe, department by department", "Where the energy is")
        dept_img = plot_dept_vibe(departments, tmpdir / "dept.png", title="")
        _picture(slide, dept_img, Inches(0.7), Inches(1.55), Inches(11.9), Inches(5.5))

        # ── Slide 7 · Department table ────────────────────────────────────────
        if departments:
            slide = _blank(prs)
            _heading(slide, "Department scoreboard", "Every number in one place")
            rows = sorted(departments, key=lambda r: -(r.get("vibe") or 0))[:12]
            table = slide.shapes.add_table(
                len(rows) + 1, 6, Inches(0.7), Inches(1.6),
                Inches(11.9), Inches(0.42) * (len(rows) + 1)
            ).table
            headers = ["Department", "Responses", "Response rate", "Vibe /10", "Belonging /10", "NPS"]
            for col, label in enumerate(headers):
                cell = table.cell(0, col)
                cell.text = label
                para = cell.text_frame.paragraphs[0]
                para.font.size = Pt(12)
                para.font.bold = True
                para.font.color.rgb = WHITE
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY
            for r, row in enumerate(rows, start=1):
                values = [
                    clean(row["dept"], 38),
                    str(row.get("filled", 0)),
                    _fmt(row.get("pct"), 0, "%"),
                    _fmt(row.get("vibe"), 1),
                    _fmt(row.get("belonging"), 1),
                    _fmt(row.get("nps"), 0),
                ]
                for c, value in enumerate(values):
                    cell = table.cell(r, c)
                    cell.text = value
                    para = cell.text_frame.paragraphs[0]
                    para.font.size = Pt(11)
                    para.font.color.rgb = INK
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = WHITE if r % 2 else MIST

        # ── Slides 8-10 · Sessions, stress, next year ─────────────────────────
        pairs = [
            ("Sessions that landed", "What to protect",
             highlights.get("impactful"), "#059669",
             "Sessions that missed", "What to redesign",
             highlights.get("needs_work"), "#e11d48"),
            ("What stressed them", "Friction in week one",
             highlights.get("stressors"), "#f59e0b",
             "Keep this next year", "Their own words",
             highlights.get("keep"), "#2563eb"),
            ("Stop doing this", "Cut from next year",
             highlights.get("stop"), "#9f1239",
             "Add this next year", "What they are asking for",
             highlights.get("introduce"), "#7c3aed"),
        ]
        for i, (t1, k1, o1, c1, t2, k2, o2, c2) in enumerate(pairs):
            slide = _blank(prs)
            _heading(slide, f"{t1}  ·  {t2}", k1)
            left_img = plot_top_options(o1 or [], tmpdir / f"pair{i}a.png", t1, c1, limit=6)
            right_img = plot_top_options(o2 or [], tmpdir / f"pair{i}b.png", t2, c2, limit=6)
            _picture(slide, left_img, Inches(0.55), Inches(1.7), Inches(6.1), Inches(5.2))
            _picture(slide, right_img, Inches(6.75), Inches(1.7), Inches(6.1), Inches(5.2))

        # ── Closing ───────────────────────────────────────────────────────────
        slide = _blank(prs)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = NAVY
        _text(slide, Inches(0.9), Inches(2.6), Inches(11.5), Inches(0.5),
              "IN ONE LINE", size=14, bold=True, colour=GOLD)
        summary = (
            f"{report.get('count', 0)} students at {campus} rated Deeksharambh 2026 "
            f"{_fmt(head.get('vibe'), 1)} out of 10 — {mood_word.lower()} — "
            f"with an NPS of {_fmt(head.get('nps'), 0)} and a belonging score of "
            f"{_fmt(head.get('belonging'), 1)} out of 10."
        )
        _text(slide, Inches(0.9), Inches(3.1), Inches(11.5), Inches(2.0),
              summary, size=26, bold=True, colour=WHITE)
        _text(slide, Inches(0.9), Inches(5.6), Inches(11.5), Inches(0.4),
              "Office of Academics · JAIN (Deemed-to-be University)",
              size=13, colour=RGBColor(0xB4, 0xC0, 0xD4))

        buffer = io.BytesIO()
        prs.save(buffer)
        return buffer.getvalue()
