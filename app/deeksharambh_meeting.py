"""
deeksharambh_meeting.py — the one pack a department meeting is run from.

Two things sit in here, and nothing else:

  The count. How many students each department registered on the portal, and
  how many of them actually took Deeksharambh. That single conversion is what
  the meeting opens with, ranked, naming the five most active departments and
  the five where a push would reach the most students.

  The department reading. Every department gets its own full analysis — every
  question the orientation form asked, with the two answers its own students
  gave most. Where a question has a good end, those two come from the good end,
  because the meeting exists to show departments that somebody read what their
  students said. Where a question only ever asked what went wrong, the two
  loudest asks are shown as asks: that is the same care, told honestly.

Nothing here is summarised away. A department with three responses gets the
same twenty-odd questions printed as a department with three hundred; a
question nobody answered says so rather than disappearing.

The count comes from `cohort_dataset` — every registered student, whether or
not they ever filled anything — so "registered" means registered on the portal
and not "registered and already past the baseline". The answers come from
`orientation_dataset`, the same source the dashboard and the shared report read.
"""
from __future__ import annotations

import re
import unicodedata

from app.orientation_analysis import (
    MIN_REPORTABLE, SECTIONS, summarize_orientation,
)

# A department nobody registered under — the bucket unmatched replies land in.
NO_DEPARTMENT = "No department"

# How many departments the two call-out lists name.
CALLOUT = 5

# How many answers each question shows. The meeting asked for two.
PICKS = 2


# ── Matching a stored answer to a known option ───────────────────────────────

def _plain(label: str) -> str:
    """An option label reduced to its words, for comparing like with like.

    The form stores the same option two ways depending on the widget that
    drew it — the chip questions keep the emoji ("🙂 Smooth"), the emoji-picker
    questions store the caption alone ("Smooth"). Both have to land on the same
    key or a curated list would silently match nothing, and a question whose
    positive answers never match reads as a department that said nothing good.
    """
    text = unicodedata.normalize("NFKD", str(label or ""))
    kept = [ch for ch in text if ch.isalnum() or ch.isspace()]
    return " ".join("".join(kept).split()).lower()


# ── What counts as a good answer ─────────────────────────────────────────────
# Copied option-for-option from the orientation form (app/templates/
# orientation.html), not inferred. Where the form itself splits a question into
# an upbeat set and a critical set — q1, q4, q36, q40 — the upbeat set is
# reproduced here exactly. Where the options are a graded scale, the top of the
# scale is listed. A question absent from this map either has no bad answer to
# exclude (a list of sessions, a list of expectations) or is listed in IMPROVE
# below as a question that only ever asked what went wrong.
POSITIVE_OPTIONS: dict[str, tuple[str, ...]] = {
    "q1": ("🔥 Inspiring", "🚀 Exciting", "😊 Welcoming", "💡 Eye-opening",
           "❤️ Memorable", "🎯 Productive", "🤝 Community-driven",
           "⚡ Energising", "🧠 Thought-provoking"),
    "q3": ("🤗 Absolutely yes!", "🙂 Yes, mostly"),
    "q4": ("😎 Confident", "🤔 Curious", "💪 Motivated", "✨ Inspired",
           "🤝 Connected", "🎉 Excited", "😊 Happy", "🎯 Focused"),
    "q5": ("🚀 Super easy", "🙂 Smooth"),
    # The one answer to the challenges question that is not a challenge.
    "q7": ("✅ Nothing — it was smooth!",),
    "q8": ("✅ Yes",),                       # matrix column
    "q10": ("😂 Absolutely!", "🙂 Maybe"),
    "q13": ("💯 Strongly Agree", "👍 Agree"),  # matrix column
    "q14": ("🔥 Fully interactive!", "🤸 Quite hands-on"),
    "q15": ("🔥 Couldn't Stop", "🚀 Super Engaging"),
    "q18": ("💪 Totally ready!", "🙂 Mostly ready"),
    "q20": ("😎 I knew well", "🙂 Basic idea"),
    "q21": ("🧠 Crystal clear now!", "🙂 Mostly understand"),
    "q23b": ("⚡ Challenging but exciting", "🤩 Better than I expected",
             "👍 About what I expected", "🤝 More social than I thought",
             "💼 Very professional", "🌱 A place to grow"),
    "q25": ("🎉 A celebration", "🌅 Fresh start"),
    "q30": ("🎉 More than 5 friends!", "👥 3–5 friends"),
    "q31": ("✅ Yes — I know exactly who to reach",),
    "q35": ("🤩 Absolutely loved it", "😄 Pretty good!"),
    "q36": ("🌟 Great overall experience", "👩‍🏫 Faculty impressed me",
            "🏫 Campus is outstanding", "🤗 Felt very welcomed & included",
            "🏆 Strong academic reputation", "💼 Good career support visible"),
    "q40": ("🚀 Excited & ready to begin", "💪 Motivated to excel here",
            "😎 Confident & positive", "❤️ Happy & glad to be here"),
}

# Questions that only ever asked what went wrong or what is missing. There is
# no positive answer to pick from, so what gets shown is the two biggest asks —
# labelled as asks. Reading those out is the care, not hiding them.
IMPROVE = {
    "q5b",   # sessions that felt least connecting
    "q12",   # sessions needing the most improvement
    "q23a",  # what they feared university would be, before arriving
    "q28",   # what stressed them out
    "q38",   # what to stop next year
    "q39",   # what to introduce next year
}

# The share of a 1..max slider that reads as a good score, and the NPS scores
# that count as a promoter.
SCALE_POSITIVE = {10: (8, 9, 10), 5: (4, 5)}
NPS_POSITIVE = (9, 10)

FRAME_LABEL = {
    "positive": "Good news",
    "asked":    "What would lift it",
    "top":      "Most chosen",
}


def _positive_set(key: str) -> set[str] | None:
    options = POSITIVE_OPTIONS.get(key)
    return {_plain(o) for o in options} if options else None


def _pick(options: list[dict], key: str, kind: str) -> tuple[list[dict], str]:
    """The two answers this question contributes, and why those two.

    Returns the picks and the frame they should be read under: "positive" when
    they were chosen from the question's good end, "asked" when the question
    only ever collected complaints, and "top" when the question has no good end
    to choose from (a list of sessions, a list of film genres) so the two
    most-chosen answers are simply the two most-chosen answers.
    """
    if key in IMPROVE:
        return options[:PICKS], "asked"

    if kind in ("scale", "nps"):
        wanted = (NPS_POSITIVE if kind == "nps"
                  else SCALE_POSITIVE.get(len(options), ()))
        good = [o for o in options if o["label"].isdigit() and int(o["label"]) in wanted]
        good.sort(key=lambda o: (-o["count"], -int(o["label"])))
        picked = [o for o in good if o["count"]][:PICKS]
        return picked, "positive"

    wanted_labels = _positive_set(key)
    if wanted_labels is None:
        return options[:PICKS], "top"

    good = [o for o in options if _plain(o["label"]) in wanted_labels]
    return good[:PICKS], "positive"


def _share(picks: list[dict], kind: str) -> float | None:
    """What share of the students who answered chose one of these two.

    Only where the question let a student choose one thing. A multi-select
    counts the same student under every option they ticked, so adding two of
    those shares together answers no question anybody asked — it produced
    "together 166.7% of the 3 who answered" on the first draft of this page.
    Those questions get no combined figure, and the per-option lines above it
    already say what each one was picked by.
    """
    if kind == "multi" or len(picks) < 2:
        return None
    return round(sum(o["pct"] for o in picks), 1)


# ── The section explorer ─────────────────────────────────────────────────────
# One question per section carries that section's headline as a pie: the
# single-choice question whose answers say most about what the section asked.
# A multi-select cannot be a pie — one student ticks several options, so the
# slices would add past the whole — so every lead here is single-choice.
SECTION_LEAD: dict[str, str] = {
    "🔥 The Vibe Check":                "q3",   # felt welcomed
    "🧭 Settling In":                   "q5",   # ease of transition
    "👣 Footsteps (pre-arrival)":       "q10",  # would watch a season 2
    "🎯 Orientation Experience":        "q15",  # how engaging
    "🌉 Bridge Course":                 "q18",  # feels prepared
    "📜 NEP 2020 & Digital Readiness":  "q21",  # understands ABC ID / credits
    "💬 The Gen Z Lens":                "q25",  # the first week felt like
    "❤️ Belonging & Expectations":      "q31",  # knows whom to contact
    "📊 Score & Mic Drop":              "q35",  # overall learning experience
}

# The validated ordinal ramp is five steps deep, so a question with more
# answers than that folds its smallest into one final slice. Five named
# slices and an "Other" beats six slices nobody can tell apart.
MAX_SLICES = 5
OTHER = "Other answers"


# ── Presentation for a leadership audience ───────────────────────────────────
# Everything above this line matches and ranks answers by their original,
# unaltered text — a curated label here can never change what counts as a
# good answer, because that classification has already happened by the time
# a label reaches this section. All that changes below is the words a label
# is printed in: no emoji, and — for the rating-scale questions — the
# vocabulary an academic reader already reads comfortably (a five-point
# agreement scale becomes "Strongly Agree .. Strongly Disagree", not
# "Absolutely yes! .. Not at all"). The ordinal meaning and the ranking are
# untouched; only the register is.
_EMOJI_RE = re.compile(
    "["
    "🌀-🫿"   # pictographs, emoticons, symbols, supplemental
    "☀-➿"   # misc symbols & dingbats
    "🇦-🇿"   # regional indicators
    "️"              # variation selector-16
    "‍"              # zero-width joiner (emoji sequences)
    "]+"
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


# The rating and sentiment scales only — copied by exact raw string from the
# orientation form, the same way POSITIVE_OPTIONS is. A string not listed
# here (every topic, session and expectation list — nominal categories, not
# a scale) falls back to the mechanical cleanup in `clean_label` below, which
# is already enough: "🎪 Student Club Fair" reads perfectly once the emoji is
# gone, without inventing a new vocabulary for it.
_SCALE_LABELS: dict[str, str] = {
    # q3 — felt welcomed during Deeksharambh
    "🤗 Absolutely yes!": "Strongly Agree",
    "🙂 Yes, mostly": "Agree",
    "😐 Neutral": "Neutral",
    "🤔 Not really": "Disagree",
    "😞 Not at all": "Strongly Disagree",
    # q18 — feels prepared for regular classes
    "💪 Totally ready!": "Very Well Prepared",
    "🙂 Mostly ready": "Well Prepared",
    "😐 Somewhat ready": "Moderately Prepared",
    "😬 Not quite": "Somewhat Unprepared",
    "😰 Not ready at all": "Not Prepared",
    # q21 — understands ABC ID / APAAR / credits, after
    "🧠 Crystal clear now!": "Fully Understood",
    "🙂 Mostly understand": "Mostly Understood",
    "😐 Kind of": "Partially Understood",
    "🤔 Still confused": "Limited Understanding",
    "😕 No idea still": "Not Understood",
    # q5 — ease of transition (the emoji-picker widget stores no emoji, so
    # these keys already match the raw stored value exactly)
    "Very hard": "Very Difficult",
    "Tough": "Difficult",
    "Okay": "Moderate",
    "Smooth": "Manageable",
    "Super easy": "Very Easy",
    # q10 — would watch a Footsteps season 2
    "Absolutely!": "Definitely",
    "Maybe": "Possibly",
    "Not sure": "Uncertain",
    "Probably not": "Unlikely",
    # q14 — how hands-on / interactive the sessions were
    "All sitting, no doing": "Entirely Passive",
    "Mostly passive": "Largely Passive",
    "Some activities": "Moderately Interactive",
    "Quite hands-on": "Highly Interactive",
    "Fully interactive!": "Fully Interactive",
    # q15 — how engaging the sessions were
    "Sleep Mode": "Disengaged",
    "Interesting": "Engaged",
    "Super Engaging": "Highly Engaged",
    "Couldn't Stop": "Exceptionally Engaged",
    # q20 — knew what NEP 2020 means, before
    "No idea": "Not Aware",
    "Heard of it": "Minimally Aware",
    "Basic idea": "Somewhat Aware",
    "I knew well": "Well Informed",
    # q25 — the first week felt like
    "A rollercoaster": "An Eventful Experience",
    "A blur": "An Overwhelming Experience",
    "A celebration": "A Positive Experience",
    "Study mode": "An Academically Focused Experience",
    "Fresh start": "A New Beginning",
    "Survive mode": "A Challenging Experience",
    # q35 — overall learning experience
    "Not great": "Unsatisfactory",
    "Could be better": "Below Expectations",
    "It was okay": "Satisfactory",
    "Pretty good!": "Good",
    "Absolutely loved it": "Excellent",
    # q41 — their JAIN avatar (mkAv stores no emoji either)
    "Future CEO": "Aspiring Executive Leader",
    "Startup Founder": "Aspiring Entrepreneur",
    "Academic Achiever": "Academically Driven",
    "Change Maker": "Aspiring Social Change Agent",
    "AI Innovator": "Technology and Innovation Focused",
    "Creative Maverick": "Creatively Driven",
    "Corporate Leader": "Aspiring Corporate Leader",
    "The Rule Changer": "Reform-Minded",
    "Sports Star": "Athletically Driven",
    "Still Figuring It Out": "Exploring Options",
    # q7 — the one answer to the challenges question that is not a challenge
    "✅ Nothing — it was smooth!": "No Challenges Reported",
    # q36 — reasons behind the NPS rating (the positive set)
    "🌟 Great overall experience": "Excellent Overall Experience",
    "👩‍🏫 Faculty impressed me": "Strong Faculty Impression",
    "🏫 Campus is outstanding": "Outstanding Campus Facilities",
    "🤗 Felt very welcomed & included": "Strong Sense of Welcome and Inclusion",
    "🏆 Strong academic reputation": "Strong Academic Reputation",
    "💼 Good career support visible": "Visible Career Support",
    # q40 — Deeksharambh left them feeling (the positive set)
    "🚀 Excited & ready to begin": "Excited and Ready to Begin",
    "💪 Motivated to excel here": "Motivated to Excel",
    "😎 Confident & positive": "Confident and Positive",
    "❤️ Happy & glad to be here": "Happy to Be Here",
}


def clean_label(label) -> str:
    """One label, in the words a leadership report reads in.

    Looks the raw text up in the curated scale vocabulary first; anything
    else is emoji-stripped and lightly tidied (an ampersand spelled out, a
    trailing exclamation point dropped) rather than reworded, since a topic
    or session name is already descriptive and a report should not invent a
    new one for it.
    """
    text = str(label or "")
    if text in _SCALE_LABELS:
        return _SCALE_LABELS[text]
    cleaned = _strip_emoji(text)
    cleaned = cleaned.replace(" & ", " and ")
    if cleaned.endswith("!") and len(cleaned) > 1:
        cleaned = cleaned[:-1].strip()
    return cleaned or text


def _clean_options(options: list[dict]) -> list[dict]:
    """A copy of an options/picks list with every label cleaned for display.

    A copy, not a mutation: `options` here is what `_pick()` and the matrix
    branch already selected using the original text, and nothing downstream
    should ever compare against the cleaned version.
    """
    return [{**o, "label": clean_label(o["label"])} for o in options]


# The nine section titles, exactly as `orientation_analysis.SECTIONS` writes
# them (emoji included), mapped to the title and the icon a leadership report
# shows instead. Changing this touches only this page — the shared SECTIONS
# constant everywhere else (the admin dashboard, the shared report, every
# export) keeps its own emoji-led titles unchanged.
SECTION_DISPLAY: dict[str, tuple[str, str]] = {
    "🔥 The Vibe Check":               ("Orientation Sentiment", "pulse"),
    "🧭 Settling In":                  ("Transition and Settling In", "compass"),
    "👣 Footsteps (pre-arrival)":      ("Pre-Arrival Preparation (Footsteps)", "route"),
    "🎯 Orientation Experience":       ("Orientation Programme Experience", "target"),
    "🌉 Bridge Course":                ("Bridge Course", "bridge"),
    "📜 NEP 2020 & Digital Readiness": ("NEP 2020 and Digital Readiness", "document"),
    "💬 The Gen Z Lens":               ("Student Perspective", "chat"),
    "❤️ Belonging & Expectations":     ("Belonging and Expectations", "heart"),
    "📊 Score & Mic Drop":             ("Outcomes Summary", "chart"),
}


def _display_section(title: str) -> tuple[str, str]:
    """A section's title and icon key, for a leadership-facing report."""
    return SECTION_DISPLAY.get(title, (clean_label(title), "document"))


# ── Colour for the one chart on this page that has a real best/worst axis ────
# A pie is only ever drawn for a SECTION_LEAD question, and every one of them
# is a rating: an agreement scale, a readiness scale, an engagement scale.
# That is the case the house dataviz rules call out by name — "when a series
# means good/bad, it wears status tokens" — so colour here is not decoration,
# it is the same worst-to-best axis the numbers already show. The four
# reserved status steps (good, warning, serious, critical) are the same ones
# used everywhere else a state is shown; the fifth, for a five-point scale's
# very best answer, is one shade deeper than "good" in the same hue rather
# than a new colour family.
_SENTIMENT_RAMP: tuple[str, ...] = (
    "#d03b3b",  # critical — the worst answer on the scale
    "#ec835a",  # serious
    "#fab219",  # warning — the midpoint
    "#0ca30c",  # good
    "#0a7d0a",  # the best answer, one shade deeper than "good"
)
# A slice this page has no ranking for — the folded "Other answers" bucket,
# or a label that reaches here from outside the curated scales below.
_NEUTRAL_SLICE = "#9099a8"

# Each SECTION_LEAD question's options, worst to best, by the CLEAN label
# `clean_label` already produces for it — not the raw form text. A question
# not listed here draws every slice in the neutral grey rather than guessing
# at an order it was never given.
_SCALE_ORDER: dict[str, tuple[str, ...]] = {
    "q3":  ("Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"),
    "q5":  ("Very Difficult", "Difficult", "Moderate", "Manageable", "Very Easy"),
    "q10": ("Unlikely", "Uncertain", "Possibly", "Definitely"),
    "q15": ("Disengaged", "Moderate", "Engaged", "Highly Engaged", "Exceptionally Engaged"),
    "q18": ("Not Prepared", "Somewhat Unprepared", "Moderately Prepared",
            "Well Prepared", "Very Well Prepared"),
    "q21": ("Not Understood", "Limited Understanding", "Partially Understood",
            "Mostly Understood", "Fully Understood"),
    "q25": ("A Challenging Experience", "An Overwhelming Experience",
            "An Eventful Experience", "An Academically Focused Experience",
            "A New Beginning", "A Positive Experience"),
    "q31": ("Not really — need more clarity", "Somewhat — have a rough idea",
            "Yes — I know exactly who to reach"),
    "q35": ("Unsatisfactory", "Below Expectations", "Satisfactory", "Good", "Excellent"),
}


def _slice_color(question_key: str, label: str) -> str:
    """Where one answer sits on its question's own worst-to-best axis.

    A scale of any length spreads evenly across the same five-stop ramp, so
    a three-point scale still reads as clearly red/amber/green as a
    five-point one — position on its own scale, not the raw option count,
    is what a colour like this can honestly represent.
    """
    order = _SCALE_ORDER.get(question_key)
    if not order or label not in order:
        return _NEUTRAL_SLICE
    span = len(order) - 1
    step = round(order.index(label) * (len(_SENTIMENT_RAMP) - 1) / span) if span else 2
    return _SENTIMENT_RAMP[step]


def lead_slices(stats: dict | None) -> dict | None:
    """One question's answers, ready to draw as a pie.

    Ordered by how many chose each, so the ramp reads most-chosen to least,
    and capped: everything past the fifth is summed into one honest "Other"
    slice rather than being dropped. Every slice carries its own worst-to-best
    colour and is named in the legend, so neither the ranking nor the colour
    has to be read off a swatch alone.
    """
    if not stats or not stats.get("answered"):
        return None

    options = list(stats.get("options") or [])
    if not options:
        return None

    head = options[:MAX_SLICES]
    tail = options[MAX_SLICES:]
    if tail:
        head = head[:MAX_SLICES - 1] + [{
            "label": OTHER,
            "count": sum(o["count"] for o in options[MAX_SLICES - 1:]),
            "pct": round(sum(o["pct"] for o in options[MAX_SLICES - 1:]), 1),
        }]

    key = stats["key"]
    coloured = []
    for o in head:
        label = clean_label(o["label"])
        coloured.append({**o, "label": label, "color": _slice_color(key, label)})

    return {
        "key": key,
        "label": clean_label(stats["label"]),
        "answered": stats["answered"],
        "options": coloured,
        "folded": len(tail) + 1 if tail else 0,
    }

def question_picks(report: dict) -> list[dict]:
    """Every question the form asks, in form order, with its two answers.

    Built from the section map rather than from the report, so a question
    nobody in this department answered still gets a line saying nobody
    answered it. The meeting asked for all the questions; a question quietly
    dropped is a question the department cannot be asked about.
    """
    answered = {
        q["key"]: q
        for section in report.get("sections", [])
        for q in section["questions"]
    }

    out = []
    for title, items in SECTIONS:
        questions = []
        for key, label, kind, maximum in items:
            stats = answered.get(key)
            if not stats:
                questions.append({
                    "key": key, "label": label, "kind": kind,
                    "answered": 0, "picks": [], "all": [], "frame": "top",
                    "frame_label": "", "share": None, "rows": [],
                })
                continue

            if kind == "matrix":
                wanted = _positive_set(key)
                rows = []
                for row in stats.get("rows", []):
                    options = row.get("options") or []
                    good = ([o for o in options if _plain(o["label"]) in wanted]
                            if wanted else options)
                    picks = good[:PICKS]
                    rows.append({
                        "label": clean_label(row["label"]),
                        "answered": row.get("answered", 0),
                        "picks": _clean_options(picks),
                        # Every option this row's students chose from, not
                        # just the two picked out above — the department view
                        # prints all of them, the PDF's summary still reads
                        # off `picks`.
                        "all": _clean_options(options),
                        "share": _share(picks, "single"),
                    })
                questions.append({
                    "key": key, "label": label, "kind": kind,
                    "answered": stats.get("answered", 0),
                    "picks": [], "rows": rows, "all": [],
                    "frame": "positive",
                    "frame_label": FRAME_LABEL["positive"],
                    "share": None,
                })
                continue

            picks, frame = _pick(stats.get("options") or [], key, kind)
            questions.append({
                "key": key, "label": label, "kind": kind,
                "answered": stats.get("answered", 0),
                "avg": stats.get("avg"),
                "max": stats.get("max"),
                "nps": stats.get("nps"),
                "picks": _clean_options(picks),
                # The full option list, in the same most- to least-chosen
                # order the two picks above were taken from.
                "all": _clean_options(stats.get("options") or []),
                "rows": [],
                "frame": frame,
                "frame_label": FRAME_LABEL[frame],
                "share": _share(picks, kind),
            })
        clean_title, icon = _display_section(title)
        out.append({
            "title": clean_title,
            "icon": icon,
            "questions": questions,
            # What the section's card draws before a department is picked.
            "lead": lead_slices(answered.get(SECTION_LEAD.get(title, ""))),
            # How many of this scope's students answered anything in the
            # section at all — the card's own headline number.
            "answered": max((q["answered"] for q in questions), default=0),
        })
    return out


# How many strengths or gaps a department's own summary names.
HIGHLIGHTS = 5


def department_highlights(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """A department's own best-answered and most-complained-about questions,
    read off the same frame every question already carries in the detail
    below it.

    A "positive" question — one with a good end its students could pick —
    counts as a strength, ranked by how large a share of the department
    picked its single most-chosen answer. A question that only ever
    collected what went wrong ("asked") counts as a gap, ranked the same
    way. Matrix grids are skipped: they carry a reading per row rather than
    one top pick, so they print in the full detail below but do not
    summarise into either list.
    """
    strengths, gaps = [], []
    for sec in sections:
        for q in sec["questions"]:
            if q["kind"] == "matrix" or not q["answered"] or not q["all"]:
                continue
            top = q["all"][0]
            if not top["count"]:
                continue
            entry = {"label": q["label"], "top": top["label"], "pct": top["pct"]}
            if q["frame"] == "positive":
                strengths.append(entry)
            elif q["frame"] == "asked":
                gaps.append(entry)
    strengths.sort(key=lambda s: -s["pct"])
    gaps.sort(key=lambda g: -g["pct"])
    return strengths[:HIGHLIGHTS], gaps[:HIGHLIGHTS]


def merge_ratings_section(sections: list[dict]) -> list[dict]:
    """Fold the two "how did the week feel overall" sections — Orientation
    Sentiment (first) and Outcomes Summary (last) — into one, renamed
    "Student Experience Ratings" and moved to the end, so a department's own
    detail works through the specific sections first and closes on the two
    headline reads together.

    Only the department view calls this. The section explorer (nine cards,
    one pie each) reads `question_picks()` straight, unmerged — merging
    there would drop a section the pie/carousel/department-pick machinery
    all key off by title, which is a much larger change than was asked for.
    Each section still carries `explorer_index`, the position (or, for the
    merged one, both positions) it held in that unmerged nine — the section
    explorer clones a department's own reading of a section straight out of
    this drill-down's markup by that index, so the mapping has to survive
    the fold.
    """
    indexed = list(enumerate(sections))
    (i0, first), *middle, (i8, last) = indexed
    questions = first["questions"] + last["questions"]
    merged = {
        "title": "Student Experience Ratings",
        "icon": "chart",
        "questions": questions,
        "lead": None,
        "answered": max((q["answered"] for q in questions), default=0),
        "explorer_index": f"{i0} {i8}",
    }
    out = [{**sec, "explorer_index": str(i)} for i, sec in middle]
    out.append(merged)
    return out


def department_synopsis(responses: int, headline: dict,
                         strengths: list[dict], gaps: list[dict]) -> str:
    """One or two plain sentences opening a department's own page, built
    from the same headline numbers already on its stat chips and the same
    strengths/gaps computed below it — nothing here can say something the
    detail underneath it does not already say.
    """
    if not responses:
        return ""
    bits = [f"{responses} {'student' if responses == 1 else 'students'} in this "
            "department replied."]
    if headline.get("vibe") is not None:
        bits.append(f"The week averaged a vibe of {headline['vibe']}/10.")
    if strengths:
        top = strengths[0]
        bits.append(f"The strongest read was on {top['label']}, where "
                     f"{top['pct']}% said {top['top']}.")
    if gaps:
        top = gaps[0]
        bits.append(f"The loudest ask was on {top['label']}, where "
                     f"{top['pct']}% said {top['top']}.")
    return " ".join(bits)


# ── The count ────────────────────────────────────────────────────────────────

def conversion_rows(rows: list[dict]) -> list[dict]:
    """Registered on the portal → took Deeksharambh, one row per department.

    `rows` is a `cohort_dataset()` list: one entry per registered student,
    carrying whether an orientation reply exists for them. So "registered" here
    is every student on the portal, including the ones who never opened the
    baseline — which is what the meeting means by registered, and is a larger
    denominator than the orientation dashboard's own eligible pool.
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["program"] or NO_DEPARTMENT, []).append(row)

    out = []
    for dept, members in groups.items():
        took = sum(1 for m in members if m["orientation"])
        registered = len(members)
        out.append({
            "dept": dept,
            "registered": registered,
            "took": took,
            "missing": registered - took,
            "pct": round(100.0 * took / registered, 1) if registered else 0.0,
            "campuses": sorted({m["campus"] for m in members}),
        })

    # Best conversion first. Two departments on the same percentage are split
    # by how many students that percentage is of — 100% of forty outranks 100%
    # of four, and the reverse at the bottom of the table.
    out.sort(key=lambda r: (-r["pct"], -r["took"], -r["registered"], r["dept"].lower()))
    return out


def callouts(rows: list[dict], size: int = CALLOUT) -> dict:
    """The most active departments, and the ones with the most room to grow.

    `rows` arrives already ranked. The second list is handed back with the
    largest opportunity first, because that is the order it gets worked in. When there are fewer
    than twice `size` departments the two lists share members, and `overlap`
    says so — a meeting told "top five and bottom five" about eight
    departments is being told the same department twice.
    """
    ranked = [r for r in rows if r["dept"] != NO_DEPARTMENT]
    top = ranked[:size]
    least = list(reversed(ranked[-size:])) if ranked else []
    top_names = {r["dept"] for r in top}
    return {
        "top": top,
        "least": least,
        "size": size,
        "ranked": len(ranked),
        "overlap": sorted(r["dept"] for r in least if r["dept"] in top_names),
    }


def gap_rows(rows: list[dict], limit: int = 8) -> list[dict]:
    """Where a push reaches the most students.

    The percentage is the fair way to read a department and the wrong way to
    plan a week: 0% of four students sits at the bottom of that table and
    moves almost nothing, while a large department at 60% can still be
    hundreds of students short. This ranks by how many students a push would
    actually reach, which is the list somebody works through.
    """
    ranked = [r for r in rows if r["dept"] != NO_DEPARTMENT and r["missing"] > 0]
    ranked.sort(key=lambda r: (-r["missing"], r["pct"], r["dept"].lower()))
    return ranked[:limit]


def campus_rows(students: list[dict]) -> list[dict]:
    """The same conversion, per campus."""
    groups: dict[str, list[dict]] = {}
    for row in students:
        groups.setdefault(row["campus"] or "Unspecified", []).append(row)

    out = []
    for campus, members in groups.items():
        took = sum(1 for m in members if m["orientation"])
        registered = len(members)
        out.append({
            "campus": campus,
            "registered": registered,
            "took": took,
            "missing": registered - took,
            "pct": round(100.0 * took / registered, 1) if registered else 0.0,
            "departments": len({m["program"] or NO_DEPARTMENT for m in members}),
        })
    out.sort(key=lambda r: (-r["registered"], r["campus"]))
    return out


# ── The pack ─────────────────────────────────────────────────────────────────

async def meeting_pack(*, campus: str = "") -> dict:
    """Everything the meeting link and the meeting PDF show, in one call."""
    from app.cohort_analysis import cohort_dataset
    from app.orientation_data import (
        ALL_CAMPUSES, UNMATCHED_PROGRAM, orientation_dataset,
    )

    students = await cohort_dataset(campus=campus)
    conversion = conversion_rows(students)

    scoped = await orientation_dataset(campus=campus)
    filled = scoped["filled"]

    by_dept: dict[str, list[dict]] = {}
    for row in filled:
        name = row["program"]
        by_dept.setdefault(NO_DEPARTMENT if name == UNMATCHED_PROGRAM else name,
                           []).append(row)

    # Every department that registered anybody gets a section, in the order the
    # count ranked them, plus any department only the replies know about.
    names = [r["dept"] for r in conversion]
    names += sorted(d for d in by_dept if d not in set(names))

    counted = {r["dept"]: r for r in conversion}
    departments = []
    # One lead per section per department, in `question_picks()`'s own nine
    # -section order — kept apart from `sections` below, because the section
    # explorer's per-department pie indexes into this by the same position
    # as its own nine cards, and the drill-down's sections are about to be
    # folded down to eight.
    dept_leads: list[list[dict | None]] = []
    for name in names:
        answers = by_dept.get(name, [])
        report = summarize_orientation([r["data"] for r in answers])
        count = counted.get(name, {"registered": 0, "took": len(answers),
                                   "missing": 0, "pct": 0.0, "campuses": []})
        sections = question_picks(report)
        strengths, gaps = department_highlights(sections)
        synopsis = department_synopsis(len(answers), report["headline"], strengths, gaps)
        dept_leads.append([sec["lead"] for sec in sections])
        departments.append({
            "dept": name,
            "registered": count["registered"],
            "took": count["took"],
            "missing": count["missing"],
            "pct": count["pct"],
            "campuses": count["campuses"],
            # What the analysis below is actually built from. It can differ
            # from `took` when a reply arrived from somebody the portal has no
            # record of, and saying which number the percentages are of is the
            # difference between an accurate slide and a plausible one.
            "responses": len(answers),
            "headline": report["headline"],
            "reportable": len(answers) >= MIN_REPORTABLE,
            # The drill-down's own eight sections: Orientation Sentiment and
            # Outcomes Summary folded into one, moved to the end.
            "sections": merge_ratings_section(sections),
            "strengths": strengths,
            "gaps": gaps,
            "synopsis": synopsis,
        })

    registered = len(students)
    took = sum(1 for r in students if r["orientation"])
    unmatched = sum(1 for r in filled if r["program"] == UNMATCHED_PROGRAM)

    return {
        "campus": campus or ALL_CAMPUSES,
        "totals": {
            "registered": registered,
            "took": took,
            "missing": registered - took,
            "pct": round(100.0 * took / registered, 1) if registered else 0.0,
            "departments": len([r for r in conversion if r["dept"] != NO_DEPARTMENT]),
            # Replies from an email the portal has no registration for. They
            # are in the analysis and cannot be in the conversion, so the two
            # totals differ by exactly this much and the page says so.
            "unmatched": unmatched,
        },
        "conversion": conversion,
        "callouts": callouts(conversion),
        # The nine sections as the whole scope answered them: what the
        # explorer opens on before anybody picks a department.
        "overall_sections": question_picks(summarize_orientation(
            [r["data"] for r in filled])),
        # Just the pie's slices, per department per section, so the explorer
        # can redraw without the page carrying every option of every question
        # a second time. The question detail it shows is cloned out of the
        # department reading that is already on the page. Built from the
        # nine unmerged sections, matching `overall_sections`' own order —
        # `departments[i]["sections"]` has since been folded to eight.
        "dept_leads": dept_leads,
        "gaps": gap_rows(conversion),
        "campuses": campus_rows(students),
        "departments": departments,
        "picks": PICKS,
        "min_reportable": MIN_REPORTABLE,
    }


# ── Responses ────────────────────────────────────────────────────────────────
# The admin route and the shared-link route serve exactly the same document, so
# they build it here rather than each assembling their own and drifting.

def _filename(campus: str) -> str:
    name = f"Deeksharambh_2026_Department_Meeting_Pack_{campus or 'All'}.pdf"
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


async def meeting_page(request, *, campus: str = "", pdf_url: str,
                       share_url: str = ""):
    """The meeting pack as one page — every department, nothing folded away."""
    from datetime import datetime

    pack = await meeting_pack(campus=campus)
    return request.app.state.templates.TemplateResponse(
        request, "deeksharambh_meeting.html", {
            "pack": pack,
            "pdf_url": pdf_url,
            "share_url": share_url,
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        },
    )


async def meeting_pdf_response(*, campus: str = ""):
    """The same document as a PDF attachment."""
    import io
    from datetime import datetime

    from fastapi.responses import StreamingResponse

    from app.deeksharambh_meeting_pdf import build_meeting_pdf
    from app.routes.shared_analysis import _in_thread

    pack = await meeting_pack(campus=campus)
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    pdf_bytes = await _in_thread(build_meeting_pdf, pack, generated_at=generated_at)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(campus)}"'},
    )
