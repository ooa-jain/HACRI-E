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
from app.orientation_analysis import CAMPUSES, normalize_campus, summarize_orientation

ORI = "orientation_responses"
FILLED = "filled"
PENDING = "pending"
UNSPECIFIED_CAMPUS = "Unspecified"
ALL_CAMPUSES = "All campuses"


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
            "detractors": head["detractors"],
            "top_session": (top["impactful"][0]["label"] if top["impactful"] else ""),
            "top_stressor": (top["stressors"][0]["label"] if top["stressors"] else ""),
        })

    rows.sort(key=lambda r: (-(r["vibe"] or 0), -r["filled"], r["dept"].lower()))
    return rows


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


async def deck_response(*, campus: str = "", dept: str = "", ug_or_pg: str = ""):
    """The orientation report as a downloadable .pptx, ready to return."""
    import io

    from fastapi.responses import StreamingResponse

    from app.orientation_ppt import generate_orientation_ppt
    from app.routes.shared_analysis import _in_thread

    data = await orientation_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    filled, pending = data[FILLED], data[PENDING]

    report = summarize_orientation([r["data"] for r in filled])
    report["coverage"] = coverage_of(filled, pending)
    report["departments"] = sorted({r["program"] for r in filled})

    scope = dept or "All departments"
    if ug_or_pg:
        scope += f" · {ug_or_pg.upper()}"

    ppt_bytes = await _in_thread(
        generate_orientation_ppt,
        campus=campus or ALL_CAMPUSES,
        scope=scope,
        report=report,
        # A department-scoped deck compares nothing, so its scoreboard is just
        # that one department; the campus deck compares them all.
        departments=department_rows(filled, pending),
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
