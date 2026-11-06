"""
deeksharambh_summary_pdf.py — the Deeksharambh short summary: three pages of text.

The same clean document style as the full report (white page, serif type, the
grey JAIN logo at the top right, "Deeksharambh 2026 Overall Analysis" at the
foot), but prose only, no tables:

  Report Title · Objective · Our Approach · Department Approach · At a Glance ·
  Student Feedback (a short paragraph for each survey section) ·
  What Students Want Next · Way Forward

Every sentence is written from the live answers in `meeting_pack()`'s overall
reading. Answers are found by the option text students chose (matched without
case or punctuation); a clause whose answer is not on file is left out rather
than printed as zero, so the summary never states a figure the data does not
hold.
"""
from __future__ import annotations

import io
import math

from app.deeksharambh_meeting_pdf import LOGO, _text

INK = "#111111"
BODY = "#222222"
MUTED = "#595959"

# Sessions the departments themselves lead, as the session lists name them.
DEPARTMENT_SESSIONS = [
    "Faculty Interaction", "School and Dept Introduction", "Academic Roadmap Session",
    "Lab / Discipline Demo Session", "Mentor Meet",
]
NEGATIVE_WORDS = ["Average", "Overwhelming", "Boring", "Disconnected", "Too rushed", "Stressful"]


def _norm(text) -> str:
    s = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text or ""))
    return " ".join(s.split())


def _matches(label, name) -> bool:
    a, b = _norm(label), _norm(name)
    return bool(b) and (a == b or a.startswith(b + " "))


def _p(value) -> str:
    return f"{value:.1f}%"


def _n(value) -> str:
    return f"{int(value):,}"


def _lower(label) -> str:
    """'Excited and Ready to Begin' reads mid-sentence as 'excited and ready to begin';
    acronyms such as NEP, ERP or JAIN keep their capitals."""
    s = str(label or "")
    while s and not s[0].isalnum():          # an emoji or a stray mark ahead of the words
        s = s[1:]
    return " ".join(w if (len(w) > 1 and w.isupper()) else w.lower() for w in s.split(" "))


def _join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


class _Answers:
    """The overall reading's questions, looked up by form key."""

    def __init__(self, reading: dict):
        self.q = {q["key"]: q for sec in reading.get("sections", []) for q in sec["questions"]}

    def answered(self, key) -> int:
        return (self.q.get(key) or {}).get("answered") or 0

    def options(self, key, row: str = "") -> list[dict]:
        q = self.q.get(key) or {}
        if row:
            for r in q.get("rows") or []:
                if _norm(row) in _norm(r["label"]):
                    return [o for o in r.get("all") or [] if str(o["label"]).strip()]
            return []
        return [o for o in q.get("all") or [] if str(o["label"]).strip()]

    def share(self, key, *names, row: str = "") -> float | None:
        """The combined share of the named answers, or None if none is on file."""
        found = [o for o in self.options(key, row) if any(_matches(o["label"], n) for n in names)]
        return round(sum(o.get("pct") or 0 for o in found), 1) if found else None

    def top(self, key, n: int = 3, skip=()) -> list[dict]:
        return [o for o in self.options(key)
                if not any(_matches(o["label"], s) for s in skip)][:n]

    def at_least(self, key, low: float) -> float | None:
        opts = self.options(key)
        nums = []
        for o in opts:
            try:
                nums.append((float(o["label"]), o.get("pct") or 0))
            except (TypeError, ValueError):
                continue
        return round(sum(p for v, p in nums if v >= low), 1) if nums else None

    def avg(self, key):
        return (self.q.get(key) or {}).get("avg")


def _listed(options: list[dict], lower: bool = False) -> str:
    return _join([f"{_text(_lower(o['label']) if lower else o['label'])} ({_p(o['pct'])})"
                  for o in options])


def summary_paragraphs(pack: dict) -> dict:
    """Every paragraph of the summary, as plain reportlab-safe strings."""
    d = pack.get("overall_dept") or {}
    t = pack.get("totals") or {}
    a = _Answers(d)
    h = d.get("headline") or {}
    out: dict[str, object] = {}

    # ── Our approach ─────────────────────────────────────────────────────
    out["approach"] = (
        "Deeksharambh was run as a structured induction in three stages: the Footsteps pre-arrival "
        "module, an orientation week of University, School and Department sessions, club fairs, "
        "industry and alumni talks, mentor meets and cultural events, and a Bridge Course with NEP "
        "2020, ABC ID / APAAR and ERP / LMS onboarding. Students then answered one feedback survey. "
        f"Of <b>{_n(t.get('registered', 0))}</b> students registered across "
        f"<b>{t.get('departments', 0)} departments</b>, <b>{_n(t.get('took', 0))}</b> completed "
        f"Deeksharambh (<b>{_p(t.get('pct') or 0)}</b>), and every figure below is read from "
        "their replies.")

    # ── Department approach ──────────────────────────────────────────────
    rated = []
    for name in DEPARTMENT_SESSIONS:
        s = a.share("q11", name)
        if s is not None:
            rated.append((name, s))
    rated.sort(key=lambda x: -x[1])
    text = ("Within the common programme, departments led the sessions closest to each student's "
            "own discipline: the School and Department Introduction, Faculty Interaction, the "
            "Academic Roadmap Session, Lab / Discipline Demos and Mentor Meets.")
    if len(rated) >= 3:
        best = _join([f"{_text(n)} ({_p(s)})" for n, s in rated[:3]])
        low = _join([f"{_text(n)} ({_p(s)})" for n, s in rated[-2:]])
        text += (f" Students named {best} among the sessions with the biggest impact, while "
                 f"{low} registered least and are where departments can add the most next year.")
    out["department"] = text

    # ── At a glance ──────────────────────────────────────────────────────
    bits = []
    if h.get("vibe") is not None:
        hi = a.at_least("q2", 8)
        bits.append(f"Students rated the week <b>{h['vibe']}/10</b> on average"
                    + (f", and {_p(hi)} scored it 8 or higher." if hi is not None else "."))
    welcomed = a.share("q3", "Strongly Agree", "Agree")
    if welcomed is not None:
        bits.append(f"<b>{_p(welcomed)}</b> felt welcomed.")
    if h.get("belonging") is not None:
        bits.append(f"Belonging averaged <b>{h['belonging']}/10</b>.")
    if a.avg("q32") is not None:
        bits.append(f"Confidence of succeeding at JAIN averaged <b>{a.avg('q32')}/10</b>.")
    if h.get("nps") is not None:
        promoters, detractors = a.share("q34", "9", "10"), a.share("q34", *map(str, range(7)))
        bits.append(f"The would-recommend score is <b>{h['nps']:+g}</b>"
                    + (f": {_p(promoters)} would strongly recommend JAIN (9 or 10) against "
                       f"{_p(detractors)} who gave 6 or less" if promoters is not None
                       and detractors is not None else "")
                    + ", on a scale that runs from -100 to +100.")
    out["glance"] = " ".join(bits)

    # ── Student feedback, section by section ─────────────────────────────
    fb = []

    s = []
    man, easy = a.share("q5", "Manageable"), a.share("q5", "Very Easy")
    hard = a.share("q5", "Difficult", "Very Difficult")
    if man is not None or easy is not None:
        smooth = (man or 0) + (easy or 0)
        s.append(("The move into university was smooth for most: " if smooth >= 50 else
                  "On the move into university, ")
                 + _join([f"{_p(man)} found it manageable" if man is not None else "",
                          (f"{_p(easy)} very easy" if man is not None
                           else f"{_p(easy)} found it very easy") if easy is not None else ""])
                 + (f", while {'only ' if (hard or 0) < 10 else ''}{_p(hard)} found it difficult."
                    if hard is not None else "."))
    none = a.share("q7", "No Challenges Reported")
    if none is not None:
        s.append(f"{_p(none)} reported no challenges at all.")
    struggles = a.top("q7", 3, skip=["No Challenges Reported"])
    if struggles:
        s.append("The challenges most often named were " + _join(
            [f"&ldquo;{_text(o['label'])}&rdquo; ({_p(o['pct'])})" for o in struggles]) + ".")
    fb.append(("Transition and Settling In", s))

    s = []
    rows = [(lab, a.share("q8", "Yes", row=row)) for lab, row in (
        ("the University", "University overview"), ("their School and Department", "School"),
        ("their programme structure", "Programme"))]
    rows = [(lab, v) for lab, v in rows if v is not None]
    if rows:
        s.append(("Footsteps prepared students well before they arrived: "
                  if min(v for _l, v in rows) >= 60 else "On the Footsteps pre-arrival module, ")
                 + _join([f"{_p(v)} said it helped them understand {lab}" if i == 0
                          else f"{_p(v)} {lab}" for i, (lab, v) in enumerate(rows)]) + ".")
    useful = a.top("q9", 3)
    if useful:
        s.append(f"The most useful parts were {_listed(useful, lower=True)}.")
    again = a.share("q10", "Definitely", "Possibly")
    if again is not None:
        s.append(f"{_p(again)} would watch a second season.")
    fb.append(("Pre-Arrival Preparation (Footsteps)", s))

    s = []
    impact = a.top("q11", 2)
    if impact:
        s.append(f"{_listed(impact)} made the biggest impact.")
    ready = a.share("q13", "Strongly Agree", "Agree", row="Ready for classes")
    culture = a.share("q13", "Strongly Agree", "Agree", row="University culture")
    if ready is not None or culture is not None:
        s.append("Students agreed the programme "
                 + _join([f"readied them for classes ({_p(ready)})" if ready is not None else "",
                          f"helped them understand the University culture ({_p(culture)})"
                          if culture is not None else ""]) + ".")
    engaged = a.share("q15", "Engaged", "Highly Engaged", "Exceptionally Engaged")
    inter = a.share("q14", "Highly Interactive", "Fully Interactive")
    fix = a.top("q12", 1)
    tail = []
    if engaged is not None:
        tail.append(f"{_p(engaged)} found the sessions engaging")
    if inter is not None:
        tail.append(f"{'only ' if inter < 50 else ''}{_p(inter)} found them highly interactive")
    if tail:
        s.append((", but " if inter is not None and inter < 50 else ", and ").join(tail)
                 + (f", and {_text(fix[0]['label'])} was the session most often marked for "
                    f"improvement ({_p(fix[0]['pct'])})." if fix else "."))
    fb.append(("Orientation Programme Experience", s))

    s = []
    if a.avg("q16") is not None:
        four = a.at_least("q16", 4)
        s.append(f"Academic confidence after the Bridge Course averaged {a.avg('q16')}/5"
                 + (f", with {_p(four)} rating it 4 or 5." if four is not None else "."))
    helped = a.top("q17", 3)
    if helped:
        s.append(f"{_listed(helped)} helped most.")
    prepared = a.share("q18", "Well Prepared", "Very Well Prepared")
    unprepared = a.share("q18", "Somewhat Unprepared", "Not Prepared")
    if prepared is not None:
        s.append(f"{_p(prepared)} now feel well or very well prepared for regular classes"
                 + (f" and {'only ' if unprepared < 10 else ''}{_p(unprepared)} feel unprepared."
                    if unprepared is not None else "."))
    aspect = a.top("q19", 1)
    if aspect:
        s.append(f"{_text(aspect[0]['label'])} ({_p(aspect[0]['pct'])}) was named the most "
                 "helpful aspect of the programme.")
    fb.append(("Bridge Course", s))

    s = []
    unaware = a.share("q20", "Not Aware", "Minimally Aware")
    informed = a.share("q20", "Well Informed")
    if unaware is not None:
        s.append(f"Before Deeksharambh, {_p(unaware)} of students were unaware or only minimally "
                 "aware of NEP 2020" + (f", and {'just ' if informed < 25 else ''}{_p(informed)} were well informed."
                                        if informed is not None else "."))
    understood = a.share("q21", "Mostly Understood", "Fully Understood")
    limited = a.share("q21", "Limited Understanding", "Not Understood")
    if understood is not None:
        s.append(f"Afterwards, {_p(understood)} mostly or fully understood ABC ID, APAAR and credits"
                 + (f", and {'only ' if limited < 10 else ''}{_p(limited)} still had limited or no understanding."
                    if limited is not None else "."))
    if a.answered("q22"):
        dig = a.top("q22", 1)
        if dig:
            s.append(f"On digital and tech confidence, the most common answer was "
                     f"{_text(_lower(dig[0]['label']))} ({_p(dig[0]['pct'])}).")
    else:
        s.append("The digital and tech confidence question received no answers and should be "
                 "checked in the form.")
    fb.append(("NEP 2020 and Digital Readiness", s))

    s = []
    before, now = a.top("q23a", 2), a.top("q23b", 2)
    if before and now:
        s.append(f"Students arrived expecting university to be {_listed(before, lower=True)}, and "
                 f"now describe it as {_listed(now, lower=True)}.")
    better = a.share("q23b", "Better than I expected")
    if better is not None:
        s.append(f"{_p(better)} say it is better than they expected.")
    surprise, smile = a.top("q26", 1), a.top("q27", 1)
    if surprise and smile:
        s.append(f"{_text(surprise[0]['label'])} ({_p(surprise[0]['pct'])}) was the biggest "
                 f"surprise and {_text(_lower(smile[0]['label']))} ({_p(smile[0]['pct'])}) what "
                 "made them smile.")
    stress = a.top("q28", 2)
    if stress:
        s.append(f"The main stress was {_listed(stress, lower=True)}.")
    fb.append(("Student Perspective", s))

    s = []
    if h.get("belonging") is not None:
        eight = a.at_least("q29", 8)
        s.append(f"Belonging averaged {h['belonging']}/10"
                 + (f" ({_p(eight)} scored 8 or higher)." if eight is not None else "."))
    many, lonely = a.share("q30", "More than 5 friends"), a.share("q30", "No close friends yet")
    if many is not None:
        s.append(f"{_p(many)} have already made more than five friends"
                 + (f", though {_p(lonely)} have no close friend yet." if lonely is not None else "."))
    know, unclear = a.share("q31", "Yes"), a.share("q31", "Not really")
    if know is not None:
        s.append(f"{_p(know)} know exactly whom to contact for help"
                 + (f" and {_p(unclear)} need more clarity." if unclear is not None else "."))
    expect = a.top("q33", 4)
    if expect:
        s.append(f"Students' top expectations from JAIN are {_listed(expect, lower=True)}.")
    fb.append(("Belonging and Expectations", s))

    s = []
    words = a.top("q1", 3)
    if words:
        worst = max((a.share("q1", w) or 0 for w in NEGATIVE_WORDS), default=0)
        s.append(f"Students most often described Deeksharambh as {_listed(words, lower=True)}"
                 + (f"; no negative word reached {max(5, 5 * math.ceil(worst / 5)):g}%."
                    if worst < 10 else "."))
    felt, left = a.top("q4", 3), a.top("q40", 1)
    if felt:
        s.append(f"They felt {_listed(felt, lower=True)}"
                 + (f", and left {_text(_lower(left[0]['label']))} ({_p(left[0]['pct'])})."
                    if left else "."))
    good = a.share("q35", "Good", "Excellent", "Outstanding")
    below = a.share("q35", "Below Expectations")
    if good is not None:
        s.append(f"{_p(good)} rated the learning experience good or better"
                 + (f" and {_p(below)} below expectations." if below is not None else "."))
    keep, stop, add = a.top("q37", 2), a.top("q38", 1), a.top("q39", 1)
    asks = []
    if keep:
        asks.append(f"to keep {_listed(keep, lower=True)}")
    if stop:
        asks.append(f"to stop {_listed(stop, lower=True)}")
    if add:
        asks.append(f"to add {_listed(add, lower=True)}")
    if asks:
        s.append("They asked " + _join(asks) + ".")
    fb.append(("Student Experience Ratings", s))

    out["feedback"] = [(title, " ".join(x for x in parts if x)) for title, parts in fb
                       if any(parts)]

    # ── What students want next ──────────────────────────────────────────
    c = d.get("career") or {}
    if c.get("answered"):
        g = {x["key"]: x for x in c["groups"]}
        bits = [f"<b>{_p(g[k]['pct'])}</b> ({_n(g[k]['count'])}) "
                f"{'lean towards' if i == 0 else 'towards'} {what}"
                for i, (k, what) in enumerate(
                    [(k, w) for k, w in (("career", "a career"),
                                         ("higher_education", "higher education"),
                                         ("entrepreneur", "starting a business")) if k in g])]
        exploring = a.share("q41", "Exploring Options", "Still Figuring It Out")
        out["next"] = (f"Read from the JAIN avatar, expectations and PRaiSE answers of "
                       f"{_n(c['answered'])} students: " + _join(bits)
                       + ". A student can count under more than one"
                       + (f", and {_p(exploring)} are still exploring their options."
                          if exploring is not None else "."))
    else:
        out["next"] = ("No student has answered the JAIN avatar, expectations or PRaiSE questions "
                       "yet.")

    # ── Way forward, from what students asked for ────────────────────────
    way = []
    stop2 = a.top("q38", 2)
    if stop2:
        way.append(f"Act on what students asked to stop: {_listed(stop2, lower=True)}.")
    add3 = a.top("q39", 3)
    if add3:
        way.append(f"Add what they asked for next year: {_listed(add3, lower=True)}.")
    if unclear is not None:
        way.append(f"Give every student a clear first point of contact: {_p(unclear)} still need "
                   "clarity on whom to ask for help.")
    if len(rated) >= 2 or fix:
        weak = [_text(n) for n, _s in rated[-2:]] + ([_text(fix[0]["label"])] if fix else [])
        way.append(f"Strengthen the sessions students rated least: {_join(list(dict.fromkeys(weak)))}.")
    out["way"] = way
    return out


def build_summary_pdf(pack: dict, *, generated_at: str) -> bytes:
    """The short summary as a PDF."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            BaseDocTemplate, Frame, KeepTogether, ListFlowable, ListItem, PageTemplate, Paragraph,
        )
    except ImportError as exc:                                  # pragma: no cover
        raise RuntimeError(
            "The PDF export needs reportlab. Install it with "
            "`pip install reportlab` (it is pinned in requirements.txt)."
        ) from exc

    C = colors.HexColor
    campus = _text(pack.get("campus") or "All campuses")
    text = summary_paragraphs(pack)

    def st(name, **kw):
        base = dict(fontName="Times-Roman", fontSize=12, leading=17, textColor=C(BODY),
                    alignment=TA_JUSTIFY)
        base.update(kw)
        return ParagraphStyle(name, **base)

    S = {
        "title": st("title", fontSize=21, leading=26, textColor=C(INK), alignment=TA_CENTER,
                    spaceAfter=2),
        "sub": st("sub", fontSize=11, leading=14, textColor=C(MUTED), alignment=TA_CENTER,
                  spaceAfter=8),
        "h1": st("h1", fontSize=16.5, leading=21, textColor=C(INK), alignment=0, spaceBefore=12,
                 spaceAfter=3),
        "h2": st("h2", fontName="Times-Bold", fontSize=12.5, leading=16, textColor=C(INK),
                 alignment=0, spaceBefore=9, spaceAfter=2),
        "lead": st("lead", fontName="Times-Bold", textColor=C(INK), alignment=0),
        "body": st("body"),
        "small": st("small", fontSize=10, leading=13.5, textColor=C(MUTED), spaceBefore=10),
    }

    W, H = A4
    M = 22 * mm

    def page(c, doc):
        c.saveState()
        if LOGO.exists():
            from reportlab.lib.utils import ImageReader
            img = ImageReader(str(LOGO))
            iw, ih = img.getSize()
            h = 11 * mm
            c.drawImage(img, W - M - h * iw / ih, H - 8 * mm - h, width=h * iw / ih, height=h,
                        mask="auto")
        c.setFont("Times-Roman", 9)
        c.setFillColor(C(MUTED))
        c.drawString(M, 12 * mm, "Deeksharambh 2026 Overall Analysis")
        c.drawRightString(W - M, 12 * mm, f"Page {doc.page}")
        c.restoreState()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=27 * mm,
                          bottomMargin=19 * mm, title="Deeksharambh 2026 Overall Analysis",
                          author="JAIN University")
    doc.addPageTemplates([PageTemplate(id="p", onPage=page, frames=[Frame(
        M, 19 * mm, W - 2 * M, H - 27 * mm - 19 * mm, leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0)])])

    def P(t, s="body"):
        return Paragraph(t, S[s])

    story = [
        P("Deeksharambh 2026 Report", "title"),
        P(f"Overall Analysis &middot; All departments &middot; {campus} &middot; "
          f"Generated {_text(generated_at)}", "sub"),
        P("Report Title", "h1"),
        P("Deeksharambh 2026 &ndash; Student Orientation Feedback, Overall Analysis", "lead"),
        P("Objective", "h1"),
        P("To understand how first-year students experienced Deeksharambh 2026, how well it "
          "prepared them for university life, and what they expect from JAIN next, so that the "
          "programme can be strengthened for the coming year."),
        P("Our Approach", "h1"), P(text["approach"]),
        P("Department Approach", "h1"), P(text["department"]),
    ]
    if text["glance"]:
        story += [P("At a Glance", "h1"), P(text["glance"])]
    if text["feedback"]:
        story.append(P("Student Feedback", "h1"))
        for title, para in text["feedback"]:
            story.append(KeepTogether([P(_text(title), "h2"), P(para)]))
    story += [P("What Students Want Next", "h1"), P(text["next"])]
    if text["way"]:
        story += [P("Way Forward", "h1"), ListFlowable(
            [ListItem(P(w), leftIndent=14) for w in text["way"]], bulletType="bullet",
            start="•", leftIndent=16, bulletFontName="Times-Roman", bulletFontSize=12,
            spaceBefore=1, spaceAfter=2)]
    story.append(P("Counts are read directly from the registration portal, the Deeksharambh "
                   "replies and the AI post survey; no figure in this report is estimated. Shares "
                   "are of the students who answered each question.", "small"))
    doc.build(story)
    return buffer.getvalue()


async def summary_pdf_response(*, campus: str = ""):
    """The short summary as a PDF attachment."""
    from datetime import datetime

    from fastapi.responses import StreamingResponse

    from app.deeksharambh_meeting import meeting_pack
    from app.routes.shared_analysis import _in_thread

    pack = await meeting_pack(campus=campus)
    data = await _in_thread(build_summary_pdf, pack,
                            generated_at=datetime.now().strftime("%d %b %Y, %H:%M"))
    name = f"Deeksharambh_2026_Short_Summary_{campus or 'All'}.pdf"
    name = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
