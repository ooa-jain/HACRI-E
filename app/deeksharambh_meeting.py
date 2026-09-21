"""
deeksharambh_meeting.py — the one pack a department meeting is run from.

Two things sit in here, and nothing else:

  The count. How many students each department registered on the portal, and
  how many of them actually took Deeksharambh. That single conversion is what
  the meeting opens with, ranked, with the five strongest and the five weakest
  departments called out by name.

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
    "positive": "Top 2 answers — the good news",
    "asked":    "Top 2 asks — what students want changed",
    "top":      "Top 2 answers",
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
                    "answered": 0, "picks": [], "frame": "top",
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
                        "label": row["label"],
                        "answered": row.get("answered", 0),
                        "picks": picks,
                        "share": _share(picks, "single"),
                    })
                questions.append({
                    "key": key, "label": label, "kind": kind,
                    "answered": stats.get("answered", 0),
                    "picks": [], "rows": rows,
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
                "picks": picks,
                "rows": [],
                "frame": frame,
                "frame_label": FRAME_LABEL[frame],
                "share": _share(picks, kind),
            })
        out.append({"title": title, "questions": questions})
    return out


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
    """The strongest and the weakest departments on that conversion.

    `rows` arrives already ranked. The weakest list is handed back worst-first,
    because that is the order they get talked about in. When there are fewer
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
    for name in names:
        answers = by_dept.get(name, [])
        report = summarize_orientation([r["data"] for r in answers])
        count = counted.get(name, {"registered": 0, "took": len(answers),
                                   "missing": 0, "pct": 0.0, "campuses": []})
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
            "sections": question_picks(report),
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
