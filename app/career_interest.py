"""
career_interest.py — how many students lean toward higher education, starting
a business, or a career.

No form asks this outright, so it is read from the answers that hint at it,
and the page says so. A student counts toward an interest when ANY of that
interest's signals is present, and can count toward more than one:

  Entrepreneur     "Startup Founder" as their JAIN avatar (orientation q41) ·
                   chose the Entrepreneurship PRaiSE pillar (post survey) ·
                   expects innovation & entrepreneurship exposure (q33)
  Career           "Future CEO" or "Corporate Leader" avatar ·
                   expects career support & placement prep (q33) ·
                   expects industry-relevant skills & certifications (q33)
  Higher education "Academic Achiever" avatar · expects internship &
                   research opportunities (q33).  The weakest proxy of the
                   three — nothing asks about further study.

Matching goes through `_plain` so the same option counts whether the widget
stored it with its emoji ("🚀 Startup Founder") or without.
"""
from __future__ import annotations

from app.cohort_analysis import cohort_dataset
from app.deeksharambh_meeting import _plain
from app.orientation_data import orientation_dataset

AVATAR = "q41"
EXPECTS = "q33"

# interest key → (label, is_proxy, [(signal label, source, wanted option)])
INTERESTS: list[tuple[str, str, bool, list[tuple[str, str, str]]]] = [
    ("higher_education", "Interested in higher education", True, [
        ("Avatar: Academic Achiever", "avatar", "Academic Achiever"),
        ("Expects internship & research opportunities", "expects",
         "Internship & research opportunities"),
    ]),
    ("entrepreneur", "Interested in being an entrepreneur", False, [
        ("Avatar: Startup Founder", "avatar", "Startup Founder"),
        ("Chose the Entrepreneurship PRaiSE pillar", "praise", "Entrepreneurship"),
        ("Expects innovation & entrepreneurship exposure", "expects",
         "Innovation & entrepreneurship exposure"),
    ]),
    ("career", "Interested in having a career", False, [
        ("Avatar: Future CEO", "avatar", "Future CEO"),
        ("Avatar: Corporate Leader", "avatar", "Corporate Leader"),
        ("Expects career support & placement prep", "expects",
         "Career support & placement prep"),
        ("Expects industry-relevant skills & certifications", "expects",
         "Industry-relevant skills & certifications"),
    ]),
]

UNSURE = "Still Figuring It Out"

# The ten avatars the orientation form offers, so a matched (lower-cased) answer
# reads back the way the student saw it.
AVATARS = ["Future CEO", "Startup Founder", "Academic Achiever", "Change Maker",
           "AI Innovator", "Creative Maverick", "Corporate Leader", "The Rule Changer",
           "Sports Star", UNSURE]
AVATAR_NAMES = {_plain(a): a for a in AVATARS}


def _avatar(data: dict) -> str:
    """q41 is normally a string; older data holds a list or {text: …}."""
    v = data.get(AVATAR)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("text") or v.get("label") or ""
    return _plain(v)


def _expects(data: dict) -> set[str]:
    v = data.get(EXPECTS)
    if isinstance(v, str):
        v = [v]
    return {_plain(x) for x in (v or [])}


def student_signals(orientation: dict | None, post: dict | None) -> dict:
    """What one student's answers say: the avatar, expectations and pillar."""
    orientation, post = orientation or {}, post or {}
    return {
        "avatar": _avatar(orientation),
        "expects": _expects(orientation),
        "praise": _plain(post.get("praise_initiative")),
    }


def _hits(signals: dict, source: str, wanted: str) -> bool:
    want = _plain(wanted)
    if source == "avatar":
        return signals["avatar"] == want
    if source == "expects":
        return want in signals["expects"]
    return signals["praise"] == want


def _pct(n: int, of: int) -> float:
    return round(100.0 * n / of, 1) if of else 0.0


def career_interest_report(students: list[dict], *, scope: dict) -> dict:
    """`students`: one dict per student, each with 'orientation' and 'post'."""
    signals = [student_signals(s.get("orientation"), s.get("post")) for s in students]
    # Someone who answered none of the three questions says nothing either way,
    # so percentages are of the students who answered at least one.
    answered = [g for g in signals if g["avatar"] or g["expects"] or g["praise"]]

    groups = []
    for key, label, proxy, rules in INTERESTS:
        members = [g for g in answered if any(_hits(g, src, want) for _l, src, want in rules)]
        groups.append({
            "key": key, "label": label, "proxy": proxy,
            "count": len(members), "pct": _pct(len(members), len(answered)),
            "signals": [{
                "label": lab,
                "count": sum(1 for g in answered if _hits(g, src, want)),
            } for lab, src, want in rules],
        })

    with_any = sum(1 for g in answered
                   if any(_hits(g, src, want) for _k, _l, _p, rules in INTERESTS
                          for _lab, src, want in rules))
    avatars: dict[str, int] = {}
    for g in answered:
        if g["avatar"]:
            avatars[g["avatar"]] = avatars.get(g["avatar"], 0) + 1
    return {
        "scope": scope,
        "students": len(students),
        "answered": len(answered),
        "none": len(answered) - with_any,
        "unsure": sum(1 for g in answered if g["avatar"] == _plain(UNSURE)),
        "groups": groups,
        "avatars": [{"label": AVATAR_NAMES.get(a, a.title()), "count": n}
                    for a, n in sorted(avatars.items(), key=lambda kv: (-kv[1], kv[0]))],
    }


async def orientation_by_email(campus: str = "") -> dict[str, dict]:
    """Each student's Deeksharambh (orientation) answers, by lower-cased email."""
    ori = await orientation_dataset(campus=campus)
    return {(r.get("email") or "").strip().lower(): r.get("data") or {}
            for r in ori["filled"]}


def career_for_rows(rows: list[dict], by_email: dict[str, dict], *, scope: dict) -> dict:
    """The report for these cohort rows (see cohort_dataset), joined by email."""
    students = [{"orientation": by_email.get((r.get("email") or "").strip().lower()),
                 "post": r.get("post")} for r in rows]
    return career_interest_report(students, scope=scope)


async def career_interest(*, campus: str = "", dept: str = "") -> dict:
    """The report for one department (or all) on one campus (or all)."""
    rows = await cohort_dataset(campus=campus)
    departments = sorted({r["program"] for r in rows}, key=str.lower)
    chosen = [r for r in rows if not dept or r["program"] == dept]
    report = career_for_rows(
        chosen, await orientation_by_email(campus),
        scope={"campus": campus or "All campuses", "dept": dept or "All departments"})
    report["departments"] = departments
    return report
