"""
outcome_departments.py — the AI survey (Outcome & Impact), one department at a time.

For every department: who filled the baseline (before) and the post survey
(after), how the literacy and readiness scores moved between them, section by
section, which PRaiSE pillar each student chose to contribute to, and which
students come from an entrepreneur family. The same numbers feed the
department's own page, its share link and the Excel workbook, so none of them
can disagree.

Scores come from `cohort_analysis`, which reads them the one way the rest of
the dashboard does.
"""
from __future__ import annotations

from app.cohort_analysis import (
    BANDS, QUADRANTS, cohort_dataset, journey_block, movement_block,
    score_block, scores_of,
)
from app.hacri_e2_compat import SCHEMA
from app.scoring import score_for_user
from app.sections import SECTION_TITLES

# The Likert sections the scores are built from, in form order.
SECTIONS = ["B", "D", "E", "F", "G"]

# The post survey's PRaiSE question, in the order the form offers it.
PRAISE_PILLARS = ["Societal Impact", "Human Excellence", "Social Good", "Entrepreneurship"]
PRAISE_NONE = "None"

ENTREPRENEUR = "Entrepreneur"
ALL_DEPARTMENTS = "All departments"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 2)


def section_score(fields: dict | None, letter: str) -> float | None:
    """A student's 1-5 average on one section, reversed items flipped."""
    if not fields:
        return None
    values = []
    for key, (_, reverse) in SCHEMA.items():
        if not key.startswith(letter):
            continue
        try:
            v = float(fields.get(key))
        except (TypeError, ValueError):
            continue
        if 1.0 <= v <= 5.0:
            values.append(6.0 - v if reverse else v)
    return round(sum(values) / len(values), 3) if values else None


def _scores(fields: dict | None) -> dict:
    """Literacy, readiness and their average for one survey, or all None."""
    if not fields:
        return {"lit": None, "read": None, "overall": None, "quadrant": "", "band": ""}
    s = score_for_user(fields)
    overall = (round((s["lit"] + s["read"]) / 2, 2)
               if s["lit"] is not None and s["read"] is not None else None)
    return {"lit": s["lit"], "read": s["read"], "overall": overall,
            "quadrant": s["quadrant"] if overall is not None else "",
            "band": s["band"] if overall is not None else ""}


def _parent_business(post: dict) -> list[dict]:
    """The parents a post survey names as entrepreneurs, with their business."""
    out = []
    if post.get("father_occupation") == ENTREPRENEUR:
        out.append({"parent": "Father", "name": post.get("father_name") or "",
                    "business": post.get("business_name") or "",
                    "type": post.get("business_type") or ""})
    if post.get("mother_occupation") == ENTREPRENEUR:
        out.append({"parent": "Mother", "name": post.get("mother_name") or "",
                    "business": post.get("mother_business_name") or "",
                    "type": post.get("mother_business_type") or ""})
    return out


def student_rows(rows: list[dict]) -> list[dict]:
    """One line per student: before, after, the change, PRaiSE, family business."""
    out = []
    for r in rows:
        before, after = _scores(r.get("pre")), _scores(r.get("post"))
        post = r.get("post") or {}
        pillar = (post.get("praise_initiative") or "").strip()
        out.append({
            "name": r.get("name") or "",
            "email": r.get("email") or "",
            "dept": r.get("program") or "",
            "campus": r.get("campus") or "",
            "baseline_done": r.get("pre") is not None,
            "post_done": r.get("post") is not None,
            "before": before,
            "after": after,
            "change": _change(before["overall"], after["overall"]),
            "praise": pillar,
            "entrepreneur_family": _parent_business(post),
        })
    out.sort(key=lambda s: (s["name"] or s["email"]).lower())
    return out


def section_rows(rows: list[dict]) -> list[dict]:
    """Section by section: the average before, after, and how far it moved."""
    out = []
    for letter in SECTIONS:
        before = [v for v in (section_score(r.get("pre"), letter) for r in rows) if v is not None]
        after = [v for v in (section_score(r.get("post"), letter) for r in rows) if v is not None]
        b, a = _mean(before), _mean(after)
        out.append({
            "key": letter,
            "title": SECTION_TITLES.get(letter, letter),
            "before": b, "after": a, "change": _change(b, a),
            "before_n": len(before), "after_n": len(after),
        })
    return out


def praise_block(students: list[dict]) -> dict:
    """Who chose which PRaiSE pillar — counts and the students by name."""
    answered = [s for s in students if s["praise"]]
    joining = [s for s in answered if s["praise"] != PRAISE_NONE]
    pillars = []
    for name in PRAISE_PILLARS:
        members = [s for s in answered if s["praise"] == name]
        pillars.append({
            "pillar": name,
            "count": len(members),
            "pct": round(100.0 * len(members) / len(answered), 1) if answered else 0.0,
            "students": [{"name": s["name"], "email": s["email"]} for s in members],
        })
    none = sum(1 for s in answered if s["praise"] == PRAISE_NONE)
    return {
        "answered": len(answered),
        "joining": len(joining),
        "joining_pct": round(100.0 * len(joining) / len(answered), 1) if answered else 0.0,
        "none": none,
        "pillars": pillars,
    }


def entrepreneur_block(students: list[dict]) -> dict:
    """Students from an entrepreneur family, as the post survey records it."""
    families = [s for s in students if s["entrepreneur_family"]]
    answered = sum(1 for s in students if s["post_done"])
    return {
        "count": len(families),
        "of_post": answered,
        "pct": round(100.0 * len(families) / answered, 1) if answered else 0.0,
        "students": [{
            "name": s["name"], "email": s["email"],
            "parents": s["entrepreneur_family"],
        } for s in families],
    }


# The literacy × readiness chart: a 1-5 square split at 3, drawn as SVG. The
# numbers are laid out here so the page only has to place them.
PLOT_W, PLOT_H, PLOT_L, PLOT_R, PLOT_T, PLOT_B = 620, 520, 58, 22, 20, 52


def _px(v: float) -> float:
    return round(PLOT_L + (v - 1) / 4 * (PLOT_W - PLOT_L - PLOT_R), 1)


def _py(v: float) -> float:
    return round(PLOT_H - PLOT_B - (v - 1) / 4 * (PLOT_H - PLOT_T - PLOT_B), 1)


def paired_quadrant(rows: list[dict]) -> dict:
    """Literacy × readiness for the students who filled BOTH surveys.

    One baseline point, one post point and the line between them per student;
    the averages are of the same students, so the two big markers compare like
    with like. Students who filled only one survey are left out on purpose —
    a line needs both ends.
    """
    pairs = []
    for r in rows:
        if not r.get("pre") or not r.get("post"):
            continue
        pre, post = score_for_user(r["pre"]), score_for_user(r["post"])
        if None in (pre["lit"], pre["read"], post["lit"], post["read"]):
            continue
        pairs.append({
            "name": r.get("name") or "",
            "pre_lit": pre["lit"], "pre_read": pre["read"],
            "post_lit": post["lit"], "post_read": post["read"],
            "x1": _px(pre["lit"]), "y1": _py(pre["read"]),
            "x2": _px(post["lit"]), "y2": _py(post["read"]),
            "rising": post["lit"] + post["read"] >= pre["lit"] + pre["read"],
            "moved": pre["quadrant"] != post["quadrant"],
        })

    def centre(prefix: str) -> dict | None:
        if not pairs:
            return None
        lit = round(sum(p[f"{prefix}_lit"] for p in pairs) / len(pairs), 2)
        read = round(sum(p[f"{prefix}_read"] for p in pairs) / len(pairs), 2)
        return {"lit": lit, "read": read, "x": _px(lit), "y": _py(read)}

    return {
        "pairs": pairs,
        "matched": len(pairs),
        "moved": sum(1 for p in pairs if p["moved"]),
        "backwards": sum(1 for p in pairs if not p["rising"]),
        "pre_centre": centre("pre"),
        "post_centre": centre("post"),
        "geo": {
            "w": PLOT_W, "h": PLOT_H, "l": PLOT_L, "r": PLOT_R, "t": PLOT_T, "b": PLOT_B,
            "mid_x": _px(3), "mid_y": _py(3),
            "right": PLOT_W - PLOT_R, "bottom": PLOT_H - PLOT_B,
            "ticks": [{"v": v, "x": _px(v), "y": _py(v)} for v in (1, 2, 3, 4, 5)],
        },
    }


def _mix(before: list[dict], after: list[dict]) -> list[dict]:
    """The quadrant or band mix before and after, side by side."""
    after_by = {x["label"]: x for x in after}
    return [{"label": x["label"],
             "before": x["count"], "before_pct": x["pct"],
             "after": after_by[x["label"]]["count"], "after_pct": after_by[x["label"]]["pct"]}
            for x in before]


def synopsis(o: dict) -> str:
    """A few plain sentences built from the numbers below them."""
    j = o["journey"]
    if not j["registered"]:
        return ""
    bits = [f"{j['registered']} registered; {j['baseline']} filled the baseline survey "
            f"before the workshop and {j['post']} filled the post survey after it."]
    s = o["scores"]["overall"]
    if s["change"] is not None:
        direction = "rose" if s["change"] > 0 else ("fell" if s["change"] < 0 else "held")
        bits.append(f"The overall AI score {direction} from {s['before']} to {s['after']} "
                    f"out of 5 ({s['change']:+.2f}).")
    m = o["movement"]
    if m["matched"]:
        bits.append(f"Of the {m['matched']} who filled both, {m['gained']} improved, "
                    f"{m['unchanged']} held steady and {m['declined']} slipped.")
    p = o["praise"]
    if p["answered"]:
        bits.append(f"{p['joining']} of {p['answered']} want to contribute to a PRaiSE pillar.")
    e = o["entrepreneurs"]
    if e["of_post"]:
        bits.append(f"{e['count']} come from an entrepreneur family.")
    return " ".join(bits)


def department_outcome(rows: list[dict], dept: str) -> dict:
    """Everything one department's page, share link and workbook show."""
    journey = journey_block(rows)
    before = score_block(scores_of(rows, "pre"), "Before")
    after = score_block(scores_of(rows, "post"), "After")
    students = student_rows(rows)
    out = {
        "dept": dept,
        "campuses": sorted({r["campus"] for r in rows if r.get("campus")}),
        "journey": {
            "registered": journey["registered"],
            "baseline": journey["stages"][1]["count"],
            "post": journey["stages"][3]["count"],
            "baseline_pct": journey["stages"][1]["of_registered"],
            "post_pct": journey["stages"][3]["of_registered"],
            "pending_baseline": journey["pending_pre"],
            "pending_post": journey["pending_post"],
        },
        "scores": {
            "literacy": {"before": before["avg_lit"], "after": after["avg_lit"],
                         "change": _change(before["avg_lit"], after["avg_lit"])},
            "readiness": {"before": before["avg_read"], "after": after["avg_read"],
                          "change": _change(before["avg_read"], after["avg_read"])},
            "overall": {"before": before["avg_overall"], "after": after["avg_overall"],
                        "change": _change(before["avg_overall"], after["avg_overall"])},
            "before_n": before["scored"], "after_n": after["scored"],
        },
        "movement": movement_block(rows),
        "sections": section_rows(rows),
        "quadrants": _mix(before["quadrants"], after["quadrants"]),
        "quadrant_chart": paired_quadrant(rows),
        "bands": _mix(before["bands"], after["bands"]),
        "praise": praise_block(students),
        "entrepreneurs": entrepreneur_block(students),
        "students": students,
    }
    out["synopsis"] = synopsis(out)
    return out


async def outcome_pack(*, campus: str = "", dept: str = "") -> dict:
    """The whole scope and every department in it — or just `dept`."""
    rows = await cohort_dataset(campus=campus, dept=dept)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["program"], []).append(r)
    departments = [department_outcome(members, name) for name, members in groups.items()]
    departments.sort(key=lambda d: (-d["journey"]["registered"], d["dept"].lower()))
    return {
        "campus": campus,
        "overall": department_outcome(rows, ALL_DEPARTMENTS),
        "departments": departments,
    }


async def department_outcome_for(dept: str, *, campus: str = "") -> dict | None:
    rows = await cohort_dataset(campus=campus, dept=dept)
    rows = [r for r in rows if r["program"] == dept]
    return department_outcome(rows, dept) if rows else None


def strip_emails(o: dict) -> dict:
    """The same reading with every student email removed — for share links."""
    import copy

    o = copy.deepcopy(o)
    for s in o["students"]:
        s["email"] = ""
    for p in o["praise"]["pillars"]:
        for s in p["students"]:
            s["email"] = ""
    for s in o["entrepreneurs"]["students"]:
        s["email"] = ""
    return o


def outcome_page(request, o: dict, *, campus: str, excel_url: str, share_url: str,
                 shared: bool):
    """One department's page. Share links (`shared`) carry no student emails."""
    from datetime import datetime

    return request.app.state.templates.TemplateResponse(
        request, "outcome_department.html", {
            "o": strip_emails(o) if shared else o,
            "campus": campus or "All campuses",
            "excel_url": excel_url,
            "share_url": share_url,
            "shared": shared,
            "sections_meta": [(k, SECTION_TITLES.get(k, k)) for k in SECTIONS],
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        },
    )


async def workbook_response(*, campus: str = "", dept: str = "", include_emails: bool = True):
    """The workbook for one department, or — without `dept` — for all of them."""
    import io
    from datetime import datetime

    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    from app.outcome_excel import build_outcome_workbook, workbook_filename
    from app.routes.shared_analysis import _in_thread

    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    where = campus or "All campuses"
    if dept:
        o = await department_outcome_for(dept, campus=campus)
        if o is None:
            raise HTTPException(status_code=404, detail="No such department.")
        departments, overall, scope = [o], None, f"{dept} · {where}"
    else:
        pack = await outcome_pack(campus=campus)
        departments, overall, scope = pack["departments"], pack["overall"], where
    data = await _in_thread(build_outcome_workbook, departments, scope=scope,
                            generated_at=stamp, overall=overall,
                            include_emails=include_emails)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{workbook_filename(scope)}"'},
    )


async def department_links(base_url: str, *, campus: str = "") -> list[dict]:
    """Every department: its headline numbers, its page, its share link, its workbook."""
    from urllib.parse import urlencode

    from app.routes.shared_analysis import outcome_dept_share_url

    pack = await outcome_pack(campus=campus)
    out = []
    for o in pack["departments"]:
        query = {"dept": o["dept"]}
        if campus:
            query["campus"] = campus
        q = urlencode(query)
        j, s = o["journey"], o["scores"]["overall"]
        out.append({
            "dept": o["dept"],
            "registered": j["registered"],
            "baseline": j["baseline"],
            "post": j["post"],
            "before": s["before"],
            "after": s["after"],
            "change": s["change"],
            "praise_joining": o["praise"]["joining"],
            "entrepreneurs": o["entrepreneurs"]["count"],
            "open_url": f"/admin/survey/outcome/department?{q}",
            "excel_url": f"/admin/survey/outcome/department.xlsx?{q}",
            "share_url": outcome_dept_share_url(base_url, o["dept"], campus),
        })
    return out


async def shared_department_links(base_url: str, *, campus: str = "") -> list[dict]:
    """The list on the shared Outcome & impact page: each department's headline
    numbers and the shared links to its analysis and its workbook. No admin URLs."""
    from app.routes.shared_analysis import outcome_dept_share_url

    out = []
    for row in await department_links(base_url, campus=campus):
        dept = row["dept"]
        out.append({
            **{k: row[k] for k in ("dept", "registered", "baseline", "post", "before",
                                   "after", "change", "praise_joining", "entrepreneurs")},
            "open_url": outcome_dept_share_url(base_url, dept, campus),
            "excel_url": outcome_dept_share_url(base_url, dept, campus,
                                                "/shared/outcome/department.xlsx"),
        })
    return out


# Kept here so both the page and the workbook label quadrants/bands the same.
QUADRANT_ORDER = QUADRANTS
BAND_ORDER = BANDS
