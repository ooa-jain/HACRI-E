"""
cohort_analysis.py — the cohort's outcome and impact, in one place.

The survey runs in three steps: the baseline (pre) survey, the Deeksharambh
orientation, then the post-workshop survey. This module answers the two
questions that matter about that run:

  Outcome — where the cohort stood at the baseline: how the literacy and
            readiness scores fell, which quadrants and bands students landed in.
  Impact  — where the same students ended up after the workshop, and how far
            each one moved.

plus the journey between them: who registered, who finished each step, and how
many are still owed. Everything is scoped by campus, department and level, and
every number here is shared by the dashboard, the shared link and the deck.
"""
from __future__ import annotations

from app.db import STATUS_POST_DONE, STATUS_PRE_DONE, get_db, list_survey_users
from app.orientation_analysis import CAMPUSES, normalize_campus
from app.scoring import score_for_user

PRE = "pre_responses"
POST = "post_responses"
ORI = "orientation_responses"

ALL_CAMPUSES = "All campuses"
UNSPECIFIED_CAMPUS = "Unspecified"

# Scores are 1-5 averages; half-point bins are fine enough to show a shape
# without pretending to a precision the Likert items do not have.
BINS = [(1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0),
        (3.0, 3.5), (3.5, 4.0), (4.0, 4.5), (4.5, 5.01)]
BIN_LABELS = ["1.0–1.5", "1.5–2.0", "2.0–2.5", "2.5–3.0",
              "3.0–3.5", "3.5–4.0", "4.0–4.5", "4.5–5.0"]

QUADRANTS = ["Q1: AI Champion", "Q2: AI Enthusiast", "Q3: AI Novice", "Q4: AI Sceptic"]
BANDS = ["AI-Fluent Student", "AI-Curious Student", "AI-Aware Student", "AI-Anxious Student"]

# The order students move through, and what each step is called on screen.
STAGES = [
    ("registered",  "Registered",   "Signed up on the portal"),
    ("pre",         "Baseline",     "Completed the pre-workshop survey"),
    ("orientation", "Deeksharambh", "Completed the orientation feedback"),
    ("post",        "Post survey",  "Completed the post-workshop survey"),
]


# ── Gathering ────────────────────────────────────────────────────────────────
async def cohort_dataset(*, campus: str = "", dept: str = "", ug_or_pg: str = "") -> list[dict]:
    """One row per student in scope, carrying their answers to each survey."""
    wanted = normalize_campus(campus) if campus else ""

    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)
    rows = []
    for u in users:
        student_campus = normalize_campus(u.get("location"))
        if wanted and student_campus != wanted:
            continue
        rows.append({
            "email": u.get("email", ""),
            "name": u.get("name", ""),
            "program": (u.get("program") or "").strip() or "No department",
            "ug_or_pg": u.get("ug_or_pg", "ug"),
            "campus": student_campus or UNSPECIFIED_CAMPUS,
            "status": u.get("status") or "not_started",
            "pre_at": u.get("pre_at", ""),
            "post_at": u.get("post_at", ""),
            "pre": None,
            "post": None,
            "orientation": False,
        })

    if not rows:
        return rows

    db = get_db()
    by_email = {r["email"].strip().lower(): r for r in rows}

    for collection, key in ((PRE, "pre"), (POST, "post")):
        async for doc in db[collection].find({}).sort("submitted_at", 1):
            row = by_email.get((doc.get("email") or "").strip().lower())
            if row is not None:
                row[key] = doc.get("fields", {}) or {}   # latest submission wins

    async for doc in db[ORI].find({}, {"email": 1}):
        row = by_email.get((doc.get("email") or "").strip().lower())
        if row is not None:
            row["orientation"] = True

    # The status flag is what the rest of the dashboard counts on, so trust it
    # for completion and use the stored answers only for scoring.
    for row in rows:
        if row["status"] in (STATUS_PRE_DONE, STATUS_POST_DONE) and row["pre"] is None:
            row["pre"] = {}
        if row["status"] == STATUS_POST_DONE and row["post"] is None:
            row["post"] = {}

    return rows


# ── Pure aggregation ─────────────────────────────────────────────────────────
def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _distribution(values: list[float]) -> list[dict]:
    total = len(values)
    out = []
    for (low, high), label in zip(BINS, BIN_LABELS):
        count = sum(1 for v in values if low <= v < high)
        out.append({"label": label, "count": count,
                    "pct": round(100.0 * count / total, 1) if total else 0.0})
    return out


def _tally(names: list[str], order: list[str]) -> list[dict]:
    total = len(names)
    counts = {name: names.count(name) for name in order}
    return [{"label": name, "count": counts[name],
             "pct": round(100.0 * counts[name] / total, 1) if total else 0.0}
            for name in order]


def scores_of(rows: list[dict], key: str) -> list[dict]:
    """Scored answers for one survey — students who skipped every item drop out."""
    scored = []
    for row in rows:
        fields = row.get(key)
        if not fields:
            continue
        score = score_for_user(fields)
        if score["lit"] is None or score["read"] is None:
            continue
        scored.append({**score, "email": row["email"], "program": row["program"],
                       "campus": row["campus"]})
    return scored


def score_block(scored: list[dict], title: str) -> dict:
    """Averages, distributions and the quadrant/band mix for one survey."""
    lits = [s["lit"] for s in scored]
    reads = [s["read"] for s in scored]
    return {
        "title": title,
        "scored": len(scored),
        "avg_lit": _mean(lits),
        "avg_read": _mean(reads),
        "avg_overall": _mean([(s["lit"] + s["read"]) / 2 for s in scored]),
        "literacy": _distribution(lits),
        "readiness": _distribution(reads),
        "quadrants": _tally([s["quadrant"] for s in scored], QUADRANTS),
        "bands": _tally([s["band"] for s in scored], BANDS),
    }


def movement_block(rows: list[dict]) -> dict:
    """How far the students who did both surveys actually moved."""
    pairs = []
    for row in rows:
        if not row.get("pre") or not row.get("post"):
            continue
        pre, post = score_for_user(row["pre"]), score_for_user(row["post"])
        if None in (pre["lit"], pre["read"], post["lit"], post["read"]):
            continue
        pairs.append({
            "d_lit": round(post["lit"] - pre["lit"], 2),
            "d_read": round(post["read"] - pre["read"], 2),
            "pre_quadrant": pre["quadrant"], "post_quadrant": post["quadrant"],
        })

    total = len(pairs)
    gained = sum(1 for p in pairs if p["d_lit"] + p["d_read"] > 0.05)
    fell = sum(1 for p in pairs if p["d_lit"] + p["d_read"] < -0.05)
    return {
        "matched": total,
        "avg_delta_lit": _mean([p["d_lit"] for p in pairs]),
        "avg_delta_read": _mean([p["d_read"] for p in pairs]),
        "gained": gained,
        "unchanged": total - gained - fell,
        "declined": fell,
        "gained_pct": round(100.0 * gained / total, 1) if total else 0.0,
        "moved_quadrant": sum(1 for p in pairs if p["pre_quadrant"] != p["post_quadrant"]),
    }


def journey_block(rows: list[dict]) -> dict:
    """The wire flow: registered, then each step, with who is still owed.

    Deeksharambh sits between the two surveys — a student fills the baseline,
    then the orientation feedback, then the post survey — so the drop between
    steps is the number still to be chased at that point.
    """
    registered = len(rows)
    pre = sum(1 for r in rows if r["status"] in (STATUS_PRE_DONE, STATUS_POST_DONE))
    orientation = sum(1 for r in rows if r["orientation"])
    post = sum(1 for r in rows if r["status"] == STATUS_POST_DONE)
    reached = {"registered": registered, "pre": pre, "orientation": orientation, "post": post}

    stages = []
    previous = registered
    for key, label, blurb in STAGES:
        count = reached[key]
        stages.append({
            "key": key,
            "label": label,
            "blurb": blurb,
            "count": count,
            "of_registered": round(100.0 * count / registered, 1) if registered else 0.0,
            # Against the step before it — the honest conversion.
            "of_previous": round(100.0 * count / previous, 1) if previous else 0.0,
            "dropped": max(0, previous - count) if key != "registered" else 0,
        })
        previous = count

    return {
        "stages": stages,
        "registered": registered,
        "pending_pre": max(0, registered - pre),
        "pending_orientation": max(0, pre - orientation),
        "pending_post": max(0, pre - post),
        "fully_done": post,
        "completion_pct": round(100.0 * post / registered, 1) if registered else 0.0,
    }


def department_rows(rows: list[dict]) -> list[dict]:
    """Per department: how far each step got, and how much the scores moved."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["program"], []).append(row)

    out = []
    for dept, members in groups.items():
        journey = journey_block(members)
        pre_block = score_block(scores_of(members, "pre"), "Baseline")
        post_block = score_block(scores_of(members, "post"), "Post")
        movement = movement_block(members)
        out.append({
            "dept": dept,
            "registered": journey["registered"],
            "pre": journey["stages"][1]["count"],
            "orientation": journey["stages"][2]["count"],
            "post": journey["stages"][3]["count"],
            "pending_pre": journey["pending_pre"],
            "pending_orientation": journey["pending_orientation"],
            "pending_post": journey["pending_post"],
            "completion_pct": journey["completion_pct"],
            "pre_avg": pre_block["avg_overall"],
            "post_avg": post_block["avg_overall"],
            "delta": (round(post_block["avg_overall"] - pre_block["avg_overall"], 2)
                      if (pre_block["avg_overall"] is not None
                          and post_block["avg_overall"] is not None) else None),
            "matched": movement["matched"],
            "gained_pct": movement["gained_pct"],
        })

    out.sort(key=lambda r: (-r["completion_pct"], -r["registered"], r["dept"].lower()))
    return out


def campus_rows(rows: list[dict]) -> list[dict]:
    """The same headline numbers per campus, for the campus toggle."""
    out = []
    for name in (*CAMPUSES, UNSPECIFIED_CAMPUS):
        members = [r for r in rows if r["campus"] == name]
        if not members and name == UNSPECIFIED_CAMPUS:
            continue
        journey = journey_block(members)
        out.append({
            "campus": name,
            "registered": journey["registered"],
            "pre": journey["stages"][1]["count"],
            "orientation": journey["stages"][2]["count"],
            "post": journey["stages"][3]["count"],
            "pending_pre": journey["pending_pre"],
            "pending_orientation": journey["pending_orientation"],
            "pending_post": journey["pending_post"],
            "completion_pct": journey["completion_pct"],
            "pre_avg": score_block(scores_of(members, "pre"), "Baseline")["avg_overall"],
            "post_avg": score_block(scores_of(members, "post"), "Post")["avg_overall"],
        })
    return out


async def cohort_report(*, campus: str = "", dept: str = "", ug_or_pg: str = "") -> dict:
    """Fetch and aggregate in one call — what every route actually wants."""
    rows = await cohort_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    return build_cohort_report(rows, campus=campus, dept=dept, ug_or_pg=ug_or_pg)


async def cohort_deck_response(*, campus: str = "", dept: str = "", ug_or_pg: str = ""):
    """The outcome and impact deck, ready to return from a route."""
    import io
    from datetime import datetime

    from fastapi.responses import StreamingResponse

    from app.cohort_ppt import generate_cohort_ppt
    from app.routes.shared_analysis import _in_thread

    report = await cohort_report(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    ppt_bytes = await _in_thread(
        generate_cohort_ppt,
        report=report,
        generated_at=datetime.now().strftime("%d %B %Y"),
    )

    filename = f"HACRI_E_Outcome_Impact_{campus or 'All'}_{dept or 'All'}.pptx"
    filename = "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)
    return StreamingResponse(
        io.BytesIO(ppt_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def build_cohort_report(rows: list[dict], *, campus: str = "", dept: str = "",
                        ug_or_pg: str = "") -> dict:
    """Everything the cohort page draws, for one scope."""
    outcome = score_block(scores_of(rows, "pre"), "Outcome · Baseline")
    impact = score_block(scores_of(rows, "post"), "Impact · Post workshop")
    movement = movement_block(rows)
    departments = department_rows(rows)

    ranked = [d for d in departments if d["registered"]]
    scored = [d for d in departments if d["delta"] is not None]

    return {
        "scope": {
            "campus": campus or ALL_CAMPUSES,
            "dept": dept or "All departments",
            "level": (ug_or_pg or "").upper() or "UG & PG",
        },
        "journey": journey_block(rows),
        "outcome": outcome,
        "impact": impact,
        "movement": movement,
        "departments": departments,
        "campuses": campus_rows(rows),
        "leaders": {
            "most_complete": ranked[0] if ranked else None,
            "least_complete": ranked[-1] if ranked else None,
            "biggest_gain": max(scored, key=lambda d: d["delta"]) if scored else None,
            "smallest_gain": min(scored, key=lambda d: d["delta"]) if scored else None,
        },
    }
