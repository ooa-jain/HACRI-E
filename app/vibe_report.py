"""
vibe_report.py — the figures behind the shareable impact page.

Every other report on the site counts whoever answered whichever survey. This
one counts **only students who finished both**: a baseline with no post survey
beside it cannot say what changed, so a student who did the baseline alone is
outside the population entirely rather than sitting in it as a blank. That
single rule is what makes "Outcome" and "Impact" comparable — the same people,
measured twice.

Everything is derived from `cohort_dataset`, which already carries one row per
student with their answers to each survey, their campus, their department and
whether they attended Deeksharambh.
"""

from __future__ import annotations

from typing import Any

from app.cohort_analysis import cohort_dataset
from app.db import STATUS_POST_DONE
from app.orientation_analysis import CAMPUSES, normalize_campus
from app.scoring import score_for_user

ALL_CAMPUSES = "All campuses"
UNSPECIFIED = "Not specified"

# The post survey asks what each parent does. These are the answers it offers.
SALARIED = "Salaried"
ENTREPRENEUR = "Entrepreneur"
HOMEMAKER = "Homemaker"


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 2) if clean else None


def _lift(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 2)


def completed_both(rows: list[dict]) -> list[dict]:
    """The population: students with a baseline *and* a post survey.

    `status` is what the rest of the dashboard trusts for completion, and
    cohort_dataset fills in an empty answers dict when the status says done but
    the stored response is missing, so both checks are needed — the status to
    know they finished, the dicts to know there is something to score.
    """
    return [
        r for r in rows
        if r.get("status") == STATUS_POST_DONE
        and r.get("pre") is not None
        and r.get("post") is not None
    ]


def _scores(rows: list[dict], key: str) -> dict[str, float | None]:
    scored = [score_for_user(r[key] or {}) for r in rows]
    return {
        "literacy": _mean([s["lit"] for s in scored]),
        "readiness": _mean([s["read"] for s in scored]),
    }


def _parents(rows: list[dict]) -> dict[str, Any]:
    """What the post survey says the students' parents do.

    Counted per student, not per parent: a student is salaried-household if
    either parent is salaried, and entrepreneurial if either is. A student
    whose parents are one of each is counted in both, so the parts do not sum
    to the whole — the page says so rather than pretending they do.
    """
    salaried = entrepreneur = homemaker = answered = 0
    for r in rows:
        post = r.get("post") or {}
        father = (post.get("father_occupation") or "").strip()
        mother = (post.get("mother_occupation") or "").strip()
        if not father and not mother:
            continue
        answered += 1
        pair = {father, mother}
        if SALARIED in pair:
            salaried += 1
        if ENTREPRENEUR in pair:
            entrepreneur += 1
        if HOMEMAKER in pair:
            homemaker += 1
    return {
        "answered": answered,
        "salaried": salaried,
        "entrepreneur": entrepreneur,
        "homemaker": homemaker,
    }


def _departments(rows: list[dict]) -> list[dict]:
    """One row per department, each counting its own students once."""
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["program"], []).append(r)

    out = []
    for dept, students in grouped.items():
        before = _scores(students, "pre")
        after = _scores(students, "post")
        out.append({
            "dept": dept,
            # Distinct students, so a second submission cannot inflate a
            # department's size.
            "count": len({s["email"].strip().lower() for s in students}),
            "outcome": before,
            "impact": after,
            "lift": {
                "literacy": _lift(before["literacy"], after["literacy"]),
                "readiness": _lift(before["readiness"], after["readiness"]),
            },
        })
    out.sort(key=lambda d: (-d["count"], d["dept"].lower()))
    return out


def _campus_counts(rows: list[dict]) -> list[dict]:
    counts = {name: 0 for name in CAMPUSES}
    other = 0
    for r in rows:
        campus = normalize_campus(r.get("campus"))
        if campus in counts:
            counts[campus] += 1
        else:
            other += 1
    out = [{"campus": name, "count": counts[name]} for name in CAMPUSES]
    if other:
        out.append({"campus": UNSPECIFIED, "count": other})
    return out


def build_vibe_report(rows: list[dict], *, campus: str = "") -> dict[str, Any]:
    """Everything the shareable page draws, from one pass over the rows."""
    scope = normalize_campus(campus) if campus else ""
    in_scope = [r for r in rows if not scope or normalize_campus(r.get("campus")) == scope]

    finished = completed_both(in_scope)
    outcome = _scores(finished, "pre")
    impact = _scores(finished, "post")

    return {
        "campus": scope or ALL_CAMPUSES,
        "campuses": _campus_counts(completed_both(rows)),
        # Registered in scope, so the page can say what share finished both.
        "registered": len(in_scope),
        "count": len(finished),
        "orientation": sum(1 for r in finished if r.get("orientation")),
        "levels": {
            "ug": sum(1 for r in finished if r.get("ug_or_pg") == "ug"),
            "pg": sum(1 for r in finished if r.get("ug_or_pg") == "pg"),
        },
        "outcome": outcome,
        "impact": impact,
        "lift": {
            "literacy": _lift(outcome["literacy"], impact["literacy"]),
            "readiness": _lift(outcome["readiness"], impact["readiness"]),
        },
        "departments": _departments(finished),
        "parents": _parents(finished),
        # The roll call: everyone who saw it through, newest first.
        "praise": [
            {"name": r.get("name") or r.get("email", ""),
             "dept": r["program"],
             "campus": normalize_campus(r.get("campus")) or UNSPECIFIED,
             "level": (r.get("ug_or_pg") or "ug").upper()}
            for r in sorted(finished, key=lambda r: r.get("post_at") or "", reverse=True)
        ],
    }


async def vibe_report(*, campus: str = "") -> dict[str, Any]:
    return build_vibe_report(await cohort_dataset(), campus=campus)
