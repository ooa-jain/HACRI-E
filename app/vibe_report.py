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
from app.db import ORI, STATUS_POST_DONE, STATUS_PRE_DONE, get_db
from app.hacri_e2_compat import quadrant
from app.orientation_analysis import CAMPUSES, _answer_for, _num, normalize_campus
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


def filled_pre(rows: list[dict]) -> list[dict]:
    """Everyone who filled the baseline, whether or not they came back.

    The Outcome half of the page describes this larger group: the baseline
    stands on its own, and reporting it over only the students who later
    returned would throw away most of the answers.
    """
    return [
        r for r in rows
        if r.get("status") in (STATUS_PRE_DONE, STATUS_POST_DONE)
        and r.get("pre") is not None
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


def _departments(rows: list[dict], key: str = "both") -> list[dict]:
    """One row per department, each counting its own students once.

    `key="pre"` describes the baseline alone, where there is no post score to
    put beside it; the default carries both ends.
    """
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["program"], []).append(r)

    out = []
    for dept, students in grouped.items():
        before = _scores(students, "pre")
        after = _scores(students, "post") if key == "both" else {"literacy": None, "readiness": None}
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


def _movement(rows: list[dict]) -> dict[str, Any]:
    """Each student as a pair of points, baseline to post.

    This is what the quadrant chart draws: one dot where a student started,
    one where they reached, and the line between. Anyone missing either score
    is left out rather than pinned to an axis at zero.
    """
    points, gained, held, slipped = [], 0, 0, 0
    for r in rows:
        before = score_for_user(r.get("pre") or {})
        after = score_for_user(r.get("post") or {})
        if None in (before["lit"], before["read"], after["lit"], after["read"]):
            continue
        move = round((after["lit"] - before["lit"]) + (after["read"] - before["read"]), 3)
        if move > 0.05:
            gained += 1
        elif move < -0.05:
            slipped += 1
        else:
            held += 1
        points.append({
            "x0": before["lit"], "y0": before["read"],
            "x1": after["lit"],  "y1": after["read"],
            "up": move > 0.05,
        })
    return {
        "points": points,
        "gained": gained, "held": held, "slipped": slipped,
        "quadrants": _quadrant_tally(rows),
    }


def _quadrant_tally(rows: list[dict]) -> dict[str, dict[str, int]]:
    """How many sit in each quadrant, before and after."""
    def tally(key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in rows:
            s = score_for_user(r.get(key) or {})
            name = quadrant(s["lit"], s["read"])
            if name:
                counts[name] = counts.get(name, 0) + 1
        return counts
    return {"outcome": tally("pre"), "impact": tally("post")}


async def _orientation_vibe(emails: set[str]) -> dict[str, Any]:
    """The Deeksharambh vibe, for the students the page is counting.

    The orientation report scores the whole orientation cohort; this scores
    only the students in scope here, so the vibe sits beside the AI figures as
    the same people's answer.
    """
    scores: list[float] = []
    belonging: list[float] = []
    async for doc in get_db()[ORI].find({}):
        email = (doc.get("email") or "").strip().lower()
        if emails and email not in emails:
            continue
        record = doc.get("data") or {}
        vibe = _num(_answer_for(record, "q2"))
        belong = _num(_answer_for(record, "q29"))
        if vibe is not None:
            scores.append(vibe)
        if belong is not None:
            belonging.append(belong)
    return {
        "answered": len(scores),
        "vibe": _mean(scores),
        "belonging": _mean(belonging),
        "max": 10,
    }


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


def build_vibe_report(rows: list[dict], *, campus: str = "",
                      orientation: dict | None = None) -> dict[str, Any]:
    """Everything the shareable page draws, from one pass over the rows.

    Two populations, deliberately different sizes. **Outcome** describes
    everyone who filled the baseline — the survey stands on its own and most
    of those answers would be thrown away by narrowing it. **Impact** describes
    only students who came back for the post survey, because a change needs
    both ends. The page labels which is which rather than blurring them.
    """
    scope = normalize_campus(campus) if campus else ""
    in_scope = [r for r in rows if not scope or normalize_campus(r.get("campus")) == scope]

    baseline = filled_pre(in_scope)
    finished = completed_both(in_scope)
    outcome = _scores(baseline, "pre")
    impact_before = _scores(finished, "pre")
    impact_after = _scores(finished, "post")

    return {
        "campus": scope or ALL_CAMPUSES,
        "campuses": _campus_counts(completed_both(rows)),
        # Everyone on the portal, whatever they have or have not filled — the
        # denominator the page opens with.
        "registered_total": len(rows),
        "registered": len(in_scope),
        "count": len(finished),
        "orientation": sum(1 for r in finished if r.get("orientation")),
        "levels": {
            "ug": sum(1 for r in finished if r.get("ug_or_pg") == "ug"),
            "pg": sum(1 for r in finished if r.get("ug_or_pg") == "pg"),
        },

        # ── Outcome: the baseline, over everyone who filled it ──────────
        "outcome_count": len(baseline),
        "outcome": outcome,
        "outcome_departments": _departments(baseline, key="pre"),

        # ── Impact: the move, over the students who did both ────────────
        "impact_before": impact_before,
        "impact": impact_after,
        "lift": {
            "literacy": _lift(impact_before["literacy"], impact_after["literacy"]),
            "readiness": _lift(impact_before["readiness"], impact_after["readiness"]),
        },
        "movement": _movement(finished),
        "deeksharambh": orientation or {"answered": 0, "vibe": None, "belonging": None, "max": 10},

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
    rows = await cohort_dataset()
    scope = normalize_campus(campus) if campus else ""
    in_scope = [r for r in rows if not scope or normalize_campus(r.get("campus")) == scope]
    emails = {r["email"].strip().lower() for r in completed_both(in_scope)}
    return build_vibe_report(rows, campus=campus,
                             orientation=await _orientation_vibe(emails))
