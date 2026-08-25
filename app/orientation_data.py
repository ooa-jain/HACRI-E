"""
orientation_data.py — gathering the Deeksharambh orientation cohort.

The admin dashboard and the public shared report ask the same three questions:
who is in scope, who answered, and what does that add up to. This module owns
those answers so the two surfaces can never disagree — the admin routes and the
shared routes both build their JSON from here.

Pure aggregation lives in `orientation_analysis`; this is the layer that talks
to Mongo.
"""
from __future__ import annotations

from datetime import datetime

from app.db import (
    STATUS_POST_DONE, STATUS_PRE_DONE, get_db, list_survey_users,
)
from app.orientation_analysis import (
    CAMPUSES, MIN_REPORTABLE, normalize_campus, summarize_orientation,
)

ORI = "orientation_responses"
FILLED = "filled"
PENDING = "pending"
UNSPECIFIED_CAMPUS = "Unspecified"
ALL_CAMPUSES = "All campuses"

# The programme every reply whose student we could not match is filed under.
# It is not a department, and anything counting departments has to say so.
UNMATCHED_PROGRAM = "—"


def _fmt_date(doc) -> str:
    from app.db import _fmt
    return _fmt((doc or {}).get("submitted_at")) if doc else ""


def _iso_date(doc) -> str:
    """Sortable stamp — the display format ("07 Aug 2026 14:03") is not."""
    when = (doc or {}).get("submitted_at")
    return when.isoformat() if isinstance(when, datetime) else ""


async def orientation_dataset(
    *, campus: str = "", dept: str = "", ug_or_pg: str = ""
) -> dict:
    """Everyone in scope, split by whether they filled the orientation form.

    Scope is the department / level chosen in the dashboard, narrowed to one
    campus when asked. A student's campus comes from the orientation answer
    first (that is where they confirmed it) and from their registration record
    otherwise.
    """
    wanted = normalize_campus(campus) if campus else ""
    unspecified_only = bool(campus) and not wanted and campus.strip().lower() in (
        "unspecified", "unknown", "other",
    )

    db = get_db()
    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)

    responses: dict[str, dict] = {}
    async for doc in db[ORI].find({}).sort("submitted_at", 1):
        key = (doc.get("email") or "").strip().lower()
        if key:
            responses[key] = doc  # latest submission wins

    filled: list[dict] = []
    pending: list[dict] = []
    seen: set[str] = set()

    for u in users:
        key = (u.get("email") or "").strip().lower()
        seen.add(key)
        doc = responses.get(key)
        data = (doc or {}).get("data", {}) or {}
        student_campus = normalize_campus(data.get("location")) or normalize_campus(u.get("location"))

        if wanted and student_campus != wanted:
            continue
        if unspecified_only and student_campus:
            continue

        row = {
            "email": u.get("email", ""),
            "email_slug": u.get("email_slug", ""),
            "name": u.get("name", "") or (doc or {}).get("name", ""),
            "program": u.get("program", "") or "—",
            "ug_or_pg": u.get("ug_or_pg", "ug"),
            "campus": student_campus or UNSPECIFIED_CAMPUS,
            "status": u.get("status") or "not_started",
            "pre_at": u.get("pre_at", ""),
            "post_at": u.get("post_at", ""),
            "orientation_at": _fmt_date(doc),
            "orientation_at_iso": _iso_date(doc),
            "baseline_done": (u.get("status") in (STATUS_PRE_DONE, STATUS_POST_DONE)),
        }
        if doc:
            row["data"] = data
            filled.append(row)
        elif row["baseline_done"]:
            pending.append(row)

    # Orientation replies with no matching user record still belong in the
    # report — but only when no department/level filter is narrowing the view,
    # since we have nothing to filter them by.
    if not dept and not ug_or_pg:
        for key, doc in responses.items():
            if key in seen:
                continue
            data = doc.get("data", {}) or {}
            student_campus = normalize_campus(data.get("location"))
            if wanted and student_campus != wanted:
                continue
            if unspecified_only and student_campus:
                continue
            filled.append({
                "email": doc.get("email", ""),
                "email_slug": "",
                "name": doc.get("name", ""),
                "program": "—",
                "ug_or_pg": "ug",
                "campus": student_campus or UNSPECIFIED_CAMPUS,
                "status": "not_started",
                "pre_at": "", "post_at": "",
                "orientation_at": _fmt_date(doc),
                "orientation_at_iso": _iso_date(doc),
                "baseline_done": False,
                "data": data,
            })

    filled.sort(key=lambda r: r["orientation_at_iso"], reverse=True)
    pending.sort(key=lambda r: r["name"].lower())
    return {FILLED: filled, PENDING: pending}


def department_rows(filled: list[dict], pending: list[dict]) -> list[dict]:
    """One row per department: how many answered, and how that department feels.

    Departments with nobody registered are left out — the point of the table is
    to compare places where students actually are.
    """
    groups: dict[str, dict] = {}
    for row in filled:
        groups.setdefault(row["program"], {"filled": [], "pending": []})["filled"].append(row)
    for row in pending:
        groups.setdefault(row["program"], {"filled": [], "pending": []})["pending"].append(row)

    rows = []
    for dept, members in groups.items():
        answered = members["filled"]
        waiting = members["pending"]
        eligible = len(answered) + len(waiting)
        summary = summarize_orientation([r["data"] for r in answered])
        head = summary["headline"]
        top = summary["highlights"]
        rows.append({
            "dept": dept,
            "filled": len(answered),
            "pending": len(waiting),
            "eligible": eligible,
            "pct": round(100.0 * len(answered) / eligible, 1) if eligible else 0.0,
            "vibe": head["vibe"],
            "nps": head["nps"],
            "belonging": head["belonging"],
            "success": head["success"],
            "bridge": head["bridge"],
            "promoters": head["promoters"],
            "passives": head["passives"],
            "detractors": head["detractors"],
            # The denominator for the two above: promoters + passives +
            # detractors, which is not the same as the department's response
            # count — plenty of students skip the question.
            "nps_answered": head["nps_answered"],
            "top_session": (top["impactful"][0]["label"] if top["impactful"] else ""),
            "top_stressor": (top["stressors"][0]["label"] if top["stressors"] else ""),
            # Whether this row's scores can be published without describing a
            # named handful of students. The row itself always can be.
            "reportable": len(answered) >= MIN_REPORTABLE,
        })

    rows.sort(key=lambda r: (-(r["vibe"] or 0), -r["filled"], r["dept"].lower()))
    return rows


# The five numbers that say how a cohort felt, in the order a reader wants
# them: the vibe first, then whether they would say so out loud, then whether
# they feel at home, whether they think they will make it, and whether the
# academics landed.
VIBE_METRICS: tuple[tuple[str, str, int | None], ...] = (
    ("vibe",      "Overall vibe",     10),
    ("nps",       "Would recommend",  None),
    ("belonging", "Belonging",        10),
    ("success",   "Will succeed",     10),
    ("bridge",    "Bridge course",    5),
)


def department_scorecard(
    filled: list[dict], pending: list[dict], dept: str, campus: str = "",
) -> dict:
    """One department's vibe, measured against the campus it sits in.

    This is what a department-scoped share link opens with: where the
    department stands among its peers, every headline number next to the campus
    figure it should be read against, and the two things its own students were
    loudest about. `filled` / `pending` are the whole campus — the department is
    picked out here, because a rank means nothing without the rest of the field.

    Not redacted: this is the department's own link showing the department its
    own students' answers. What `redact_small_cells` exists to stop is a small
    department's scores being published to everybody else.
    """
    rows = department_rows(filled, pending)
    ranked = [r for r in rows if r["vibe"] is not None]
    mine = next((r for r in rows if r["dept"] == dept), None) or {
        "dept": dept, "filled": 0, "pending": 0, "eligible": 0, "pct": 0.0,
        "vibe": None, "nps": None, "belonging": None, "success": None,
        "bridge": None, "promoters": 0, "detractors": 0,
        "top_session": "", "top_stressor": "",
    }
    campus_head = summarize_orientation([r["data"] for r in filled])["headline"]

    def compare(key: str, label: str, maximum: int | None) -> dict:
        value, average = mine.get(key), campus_head.get(key)
        return {
            "key": key,
            "label": label,
            "max": maximum,
            "value": value,
            "campus": average,
            "delta": (None if value is None or average is None
                      else round(value - average, 1)),
        }

    return {
        "dept": dept,
        "campus": campus or ALL_CAMPUSES,
        "rank": next((i + 1 for i, r in enumerate(ranked) if r["dept"] == dept), None),
        "of": len(ranked),
        "department": mine,
        "campus_overall": {
            **coverage_of(filled, pending),
            **{key: campus_head.get(key) for key, _, _ in VIBE_METRICS},
        },
        "metrics": [compare(key, label, maximum) for key, label, maximum in VIBE_METRICS],
    }


# The figures that describe what a department said, as opposed to how many of
# them said it. These are what a small cell has to withhold.
OPINION_KEYS = ("vibe", "nps", "belonging", "success", "bridge",
                "promoters", "passives", "detractors", "nps_answered",
                "top_session", "top_stressor")


def redact_small_cells(rows: list[dict]) -> list[dict]:
    """Blank the scores of departments too small to report, keep the counts.

    A department where one student answered has no average — it has that
    student's own answers under their department's name, and both the campus
    deck and the campus share link put every department's name in a list
    anyone can read. So those rows keep their coverage and lose their figures.

    `filled`, `pending`, `eligible` and `pct` survive: how many students
    answered is the coverage question the report exists to answer, and it is
    not what any of them told us in confidence.

    Applied where a report describes departments other than the reader's own —
    the campus deck and the campus share link. A department's own scoped deck
    or link shows it its own students' answers unredacted, and so does the
    admin dashboard.
    """
    out = []
    for row in rows:
        if row.get("reportable", True):
            out.append(dict(row))
            continue
        out.append({**row, **{key: (None if not isinstance(row.get(key), str) else "")
                              for key in OPINION_KEYS}})
    return out


def coverage_of(filled: list[dict], pending: list[dict]) -> dict:
    eligible = len(filled) + len(pending)
    return {
        "filled": len(filled),
        "pending": len(pending),
        "eligible": eligible,
        "pct": round(100.0 * len(filled) / eligible, 1) if eligible else 0.0,
    }


def build_report(filled: list[dict], pending: list[dict], campus: str = "") -> dict:
    """The full question-by-question report for one scope."""
    dept_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    for row in filled:
        dept_counts[row["program"]] = dept_counts.get(row["program"], 0) + 1
        level = (row["ug_or_pg"] or "ug").upper()
        level_counts[level] = level_counts.get(level, 0) + 1

    report = summarize_orientation([r["data"] for r in filled])
    report.update({
        "campus": campus or ALL_CAMPUSES,
        "coverage": coverage_of(filled, pending),
        "departments": sorted(
            ({"dept": name, "count": count,
              "pct": round(100.0 * count / len(filled), 1) if filled else 0.0}
             for name, count in dept_counts.items()),
            key=lambda r: (-r["count"], r["dept"]),
        ),
        # How many named departments answered. `departments` above also carries
        # the unmatched bucket, so its length is one too many whenever a reply
        # arrived without a student record — which is why the overview slide
        # used to disagree with its own campus lines.
        "department_count": sum(1 for name in dept_counts if name != UNMATCHED_PROGRAM),
        "unmatched": dept_counts.get(UNMATCHED_PROGRAM, 0),
        "levels": sorted(
            ({"level": name, "count": count} for name, count in level_counts.items()),
            key=lambda r: -r["count"],
        ),
        "last_at": filled[0]["orientation_at"] if filled else "",
    })
    return report


def department_overview(filled: list[dict], pending: list[dict], campus: str = "") -> dict:
    """Every department in this campus, plus the campus average to judge them by."""
    overall = summarize_orientation([r["data"] for r in filled])["headline"]
    return {
        "campus": campus or ALL_CAMPUSES,
        "departments": department_rows(filled, pending),
        "overall": {
            "dept": "All departments",
            **coverage_of(filled, pending),
            "vibe": overall["vibe"],
            "nps": overall["nps"],
            "belonging": overall["belonging"],
            "success": overall["success"],
            "bridge": overall["bridge"],
        },
    }


def campus_split(filled: list[dict], pending: list[dict]) -> list[dict]:
    """Responses per campus, split UG / PG — the deck's opening slide.

    Campuses nobody answered from are left out: an empty row on the overview
    slide reads as a missing campus rather than a quiet one.
    """
    names = list(CAMPUSES) + [UNSPECIFIED_CAMPUS]
    rows = []
    for name in names:
        answered = [r for r in filled if r["campus"] == name]
        waiting = [p for p in pending if p["campus"] == name]
        if not answered and not waiting:
            continue
        rows.append({
            "campus": name,
            "filled": len(answered),
            "pending": len(waiting),
            "eligible": len(answered) + len(waiting),
            "ug": sum(1 for r in answered if (r["ug_or_pg"] or "ug").lower() == "ug"),
            "pg": sum(1 for r in answered if (r["ug_or_pg"] or "ug").lower() == "pg"),
            "departments": len({r["program"] for r in answered
                                if r["program"] != UNMATCHED_PROGRAM}),
        })
    rows.sort(key=lambda r: -r["filled"])
    return rows


async def excel_response(*, campus: str = "", dept: str = "", ug_or_pg: str = ""):
    """The orientation report as a downloadable .xlsx, ready to return.

    The same scope, the same redaction and the same figures as the deck — it is
    the deck's numbers in a form somebody can sort and filter.
    """
    import io

    from fastapi.responses import StreamingResponse

    from app.orientation_excel import generate_orientation_excel
    from app.routes.shared_analysis import _in_thread

    data = await orientation_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    filled, pending = data[FILLED], data[PENDING]
    report = build_report(filled, pending, campus)
    rows = department_rows(filled, pending)

    scope = dept or "All departments"
    if ug_or_pg:
        scope += f" · {ug_or_pg.upper()}"

    book = await _in_thread(
        generate_orientation_excel,
        campus=campus or ALL_CAMPUSES,
        scope=scope,
        report=report,
        departments=(rows if dept else redact_small_cells(rows)),
        campuses=campus_split(filled, pending),
        generated_at=datetime.now().strftime("%d %b %Y, %H:%M"),
    )

    filename = f"Deeksharambh_2026_Orientation_{campus or 'All'}_{dept or 'All'}.xlsx"
    filename = "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)
    return StreamingResponse(
        io.BytesIO(book),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def deck_response(*, campus: str = "", dept: str = "", ug_or_pg: str = ""):
    """The orientation report as a downloadable .pptx, ready to return."""
    import io

    from fastapi.responses import StreamingResponse

    from app.orientation_ppt import generate_orientation_ppt
    from app.routes.shared_analysis import _in_thread

    data = await orientation_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    filled, pending = data[FILLED], data[PENDING]

    # The same report the dashboard draws — coverage, the department mix and
    # the UG/PG split included, since the deck opens on all three.
    report = build_report(filled, pending, campus)
    rows = department_rows(filled, pending)

    scope = dept or "All departments"
    if ug_or_pg:
        scope += f" · {ug_or_pg.upper()}"

    ppt_bytes = await _in_thread(
        generate_orientation_ppt,
        campus=campus or ALL_CAMPUSES,
        scope=scope,
        report=report,
        # A department-scoped deck compares nothing, so its scoreboard is just
        # that one department; the campus deck compares them all — and is
        # handed around, so there the departments too small to report keep
        # their coverage and lose their scores.
        departments=(rows if dept else redact_small_cells(rows)),
        campuses=campus_split(filled, pending),
    )

    filename = f"Deeksharambh_2026_Orientation_{campus or 'All'}_{dept or 'All'}.pptx"
    filename = "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)
    return StreamingResponse(
        io.BytesIO(ppt_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def campus_card(name: str, filled: list[dict], pending: list[dict]) -> dict:
    """The summary shown on a campus tile."""
    headline = summarize_orientation([r["data"] for r in filled])["headline"]
    return {
        "campus": name,
        "filled": len(filled),
        "pending": len(pending),
        "eligible": len(filled) + len(pending),
        "departments": len({r["program"] for r in filled if r["program"] != "—"}),
        "vibe": headline["vibe"],
        "nps": headline["nps"],
        "belonging": headline["belonging"],
        "last_at": filled[0]["orientation_at"] if filled else "",
    }


def campus_cards(filled: list[dict], pending: list[dict]) -> list[dict]:
    """A tile per campus, plus one for replies whose campus we never learned."""
    cards = [
        campus_card(name,
                    [r for r in filled if r["campus"] == name],
                    [p for p in pending if p["campus"] == name])
        for name in CAMPUSES
    ]
    stray_filled = [r for r in filled if r["campus"] == UNSPECIFIED_CAMPUS]
    stray_pending = [p for p in pending if p["campus"] == UNSPECIFIED_CAMPUS]
    if stray_filled or stray_pending:
        cards.append(campus_card(UNSPECIFIED_CAMPUS, stray_filled, stray_pending))
    return cards
