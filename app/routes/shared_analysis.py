"""
Router for public shared department-wise analysis.
Exposes endpoints for viewing statistics, charts, downloading PPT, and exporting Excel.
Uses cryptographic token validation.
"""
from __future__ import annotations
import asyncio
import hmac
import hashlib
import io
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from app import deps
from app.db import get_db, list_survey_users, list_matched_users
from app.settings import settings
from app.excel_export import generate_cohort_excel
from app.ppt_export import generate_dept_ppt

router = APIRouter()

OVERALL = "Overall"
# Key the directory token off a name no real department can take.
DIRECTORY_KEY = "__all_departments__"


def get_dept_token(dept: str, survey_type: str = "pre") -> str:
    """Generate a secure cryptographic token for a department name + type."""
    key = f"{dept}:{survey_type}"
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        key.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:16]

def verify_token(dept: str, token: str, survey_type: str = "pre") -> bool:
    """Verify that the token matches the department and type."""
    return hmac.compare_digest(get_dept_token(dept, survey_type), token)


def get_directory_token() -> str:
    """Token for the one link that opens the whole department directory."""
    return get_dept_token(DIRECTORY_KEY, "directory")


# ── Deeksharambh orientation report ──────────────────────────────────────────
ORIENTATION_KEY = "__orientation__"


def get_orientation_token(campus: str = "", dept: str = "") -> str:
    """Token for the shareable orientation report of one campus (or all).

    Naming a department mints a different token, so a link built for one
    department cannot be edited into another's. Campus links already handed
    out keep working: their key is exactly what it always was.
    """
    scope = f"{ORIENTATION_KEY}:{campus or 'all'}"
    if dept:
        scope += f"::{dept}"
    return get_dept_token(scope, "orientation")


def verify_orientation_token(campus: str, token: str, dept: str = "") -> bool:
    return hmac.compare_digest(get_orientation_token(campus, dept), token or "")


def orientation_share_url(base_url: str, campus: str = "", dept: str = "") -> str:
    """The link an admin copies out of the dashboard."""
    from urllib.parse import urlencode

    fields = {"campus": campus, "token": get_orientation_token(campus, dept)}
    if dept:
        fields["dept"] = dept
    return f"{base_url.rstrip('/')}/shared/orientation?{urlencode(fields)}"


def resolve_orientation_scope(campus: str, token: str, dept: str = "") -> tuple[str, bool]:
    """What this link may read: the department in scope, and whether it is stuck there.

    Two kinds of link open the orientation report. A campus link reads the
    whole campus and its holder may narrow the view to any department at will.
    A department link opens that one department and nothing else — the token
    only verifies while `dept` stays what it was minted for.
    """
    if verify_orientation_token(campus, token):
        return dept, False
    if dept and verify_orientation_token(campus, token, dept):
        return dept, True
    raise HTTPException(
        status_code=403, detail="Access denied: Invalid or expired sharing link.")


# ── Cohort outcome and impact report ─────────────────────────────────────────
COHORT_KEY = "__cohort__"


def get_cohort_token(campus: str = "") -> str:
    """Token for the shareable outcome and impact report of one campus (or all)."""
    return get_dept_token(f"{COHORT_KEY}:{campus or 'all'}", "cohort")


def verify_cohort_token(campus: str, token: str) -> bool:
    return hmac.compare_digest(get_cohort_token(campus), token or "")


def cohort_share_url(base_url: str, campus: str = "") -> str:
    from urllib.parse import urlencode

    query = urlencode({"campus": campus, "token": get_cohort_token(campus)})
    return f"{base_url.rstrip('/')}/shared/cohort?{query}"


# ── The impact page students and parents get sent ────────────────────────────
VIBE_KEY = "__vibe__"


def get_vibe_token(campus: str = "") -> str:
    """Token for the shareable impact page of one campus (or all)."""
    return get_dept_token(f"{VIBE_KEY}:{campus or 'all'}", "vibe")


def verify_vibe_token(campus: str, token: str) -> bool:
    return hmac.compare_digest(get_vibe_token(campus), token or "")


def vibe_share_url(base_url: str, campus: str = "") -> str:
    from urllib.parse import urlencode

    query = urlencode({"campus": campus, "token": get_vibe_token(campus)})
    return f"{base_url.rstrip('/')}/shared/impact?{query}"


def directory_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/shared/departments?token={get_directory_token()}"


async def _in_thread(fn, *args, **kwargs):
    """Run a slow, CPU-bound builder off the event loop.

    Building a full-cohort workbook is seconds of solid CPU; left inline it
    blocks every other request on the worker for that whole time.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def _is_overall(dept: str) -> bool:
    return (dept or "").strip().lower() in ("overall", "all", "all departments")


async def _department_breakdown_rows() -> list[dict]:
    """One row per department: counts, reminder-mail figures, average scores.

    Shared by the directory page and the all-departments Excel export so the
    two can never show different numbers.
    """
    from app.db import get_dept_analysis_data, get_email_notification_stats

    analysis = await get_dept_analysis_data()
    mail_stats = {row["dept"]: row for row in await get_email_notification_stats()}

    from app.routes.post_link import dept_slug

    rows = []
    for item in analysis["departments"]:
        dept = item.get("dept")
        if not dept:
            continue
        mail = mail_stats.get(dept, {})
        registered = item.get("registered", 0)
        pre_done = item.get("pre_done", 0)
        post_done = item.get("post_done", 0)
        rows.append({
            "dept": dept,
            "registered": registered,
            "pre_done": pre_done,
            "post_done": post_done,
            "pre_pending": max(0, registered - pre_done),
            "post_pending": max(0, pre_done - post_done),
            "reminders_sent": mail.get("pre_sent", 0) + mail.get("post_sent", 0),
            "clicked": mail.get("clicked", 0),
            "completed_after": mail.get("completed_after", 0),
            "avg_lit_pre": item.get("avg_lit_pre"),
            "avg_read_pre": item.get("avg_read_pre"),
            "avg_lit_post": item.get("avg_lit_post"),
            "avg_read_post": item.get("avg_read_post"),
            "token_pre": item.get("token_pre"),
            "token_post": item.get("token_post"),
            # The student-facing survey link, for drafting mails from the
            # directory page.
            "student_post_path": f"/post/{dept_slug(dept)}",
        })
    return rows

@router.get("/shared/analysis", response_class=HTMLResponse)
async def shared_analysis_get(
    request: Request,
    dept: str = Query(...),
    token: str = Query(...),
    type: str = Query(default="pre"),
):
    survey_type = type if type in ("pre", "post") else "pre"
    if not verify_token(dept, token, survey_type):
        raise HTTPException(status_code=403, detail="Access denied: Invalid or expired sharing link.")

    from app.db import get_dept_analysis_data
    from app.routes.post_link import dept_slug

    analysis_data = await get_dept_analysis_data()

    # Fetch users for this department
    users_list = await list_survey_users(dept=dept)
    
    total = len(users_list)
    pre_done = sum(1 for u in users_list if u.get("status") in ("pre_done", "post_done"))
    post_done = sum(1 for u in users_list if u.get("status") == "post_done")
    pending = pre_done - post_done

    # Find department or overall scores
    dept_info = None
    if dept.lower() in ("overall", "all", "all departments"):
        dept_info = analysis_data["overall"]
    else:
        for d in analysis_data["departments"]:
            if d["dept"].strip().lower() == dept.strip().lower():
                dept_info = d
                break
    if not dept_info:
        dept_info = {
            "dept": dept,
            "avg_lit_pre": None, "avg_read_pre": None,
            "avg_lit_post": None, "avg_read_post": None,
        }

    return request.app.state.templates.TemplateResponse(
        request,
        "shared_analysis.html",
        {
            "dept": dept,
            "token": token,
            "survey_type": survey_type,
            "total": total,
            "pre_done": pre_done,
            "post_done": post_done,
            "pending": pending,
            "dept_info": dept_info,
            "overall_info": analysis_data["overall"],
            "dept_list": analysis_data["departments"],
            "rankings": analysis_data["rankings"],
            # The student-facing survey link, for the "Mail this report" draft.
            "student_post_path": "/post/all" if _is_overall(dept)
                                 else f"/post/{dept_slug(dept)}",
            "mail_history": await _mail_history(dept),
        }
    )


MAIL_EXPORTS = "mail_exports"


async def _mail_history(dept: str) -> dict:
    """Who this department's report has been mailed to, and how often."""
    db = get_db()
    people: dict[str, dict] = {}
    total = 0
    last_at = None

    async for doc in db[MAIL_EXPORTS].find({"dept": dept}).sort("created_at", -1):
        total += 1
        when = doc.get("created_at")
        if last_at is None and isinstance(when, datetime):
            last_at = when
        for address in doc.get("recipients", []) or []:
            entry = people.setdefault(address, {"email": address, "count": 0, "last_at": None})
            entry["count"] += 1
            if entry["last_at"] is None and isinstance(when, datetime):
                entry["last_at"] = when

    rows = sorted(people.values(), key=lambda r: (-r["count"], r["email"]))
    for row in rows:
        row["last"] = row["last_at"].strftime("%d %b %Y, %H:%M") if row["last_at"] else "—"
        row.pop("last_at", None)

    return {
        "total": total,
        "recipients": rows,
        "last": last_at.strftime("%d %b %Y, %H:%M") if last_at else "",
    }


@router.post("/shared/analysis/mail-log")
async def shared_mail_log(request: Request):
    """Record that this department's report was handed to a mail client.

    The mail itself is sent from someone's own mailbox, so this is a record of
    what was drafted and for whom — not proof of delivery.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")

    dept = (body.get("dept") or "").strip()
    survey_type = body.get("type") if body.get("type") in ("pre", "post") else "pre"
    if not dept or not verify_token(dept, body.get("token") or "", survey_type):
        raise HTTPException(status_code=403, detail="Access denied")

    seen: list[str] = []
    for address in (body.get("to") or [])[:200]:
        address = str(address).strip().lower()
        if address and "@" in address and address not in seen:
            seen.append(address)

    await get_db()[MAIL_EXPORTS].insert_one({
        "dept": dept,
        "survey_type": survey_type,
        "format": "html" if body.get("format") == "html" else "plain",
        "via": str(body.get("via") or "")[:40],
        "subject": str(body.get("subject") or "")[:300],
        "recipients": seen,
        "created_at": datetime.now(timezone.utc),
    })
    return JSONResponse({"ok": True, "history": await _mail_history(dept)})


@router.get("/shared/analysis/export-excel")
async def shared_export_excel(
    dept: str = Query(...),
    token: str = Query(...),
    type: str = Query(default="pre"),
):
    survey_type = type if type in ("pre", "post") else "pre"
    if not verify_token(dept, token, survey_type):
        raise HTTPException(status_code=403, detail="Access denied")

    db = get_db()

    # "Overall" is every department, not a department literally named that.
    query = {} if _is_overall(dept) else {"program": dept}

    # Everyone registered, filled or not. The workbook splits them into the
    # two rosters itself, and its counts have to match the page — which they
    # cannot if the students who never answered are dropped here.
    users_list = [u async for u in db["users"].find(query).sort("created_at", -1)]

    # The all-departments export gets a per-department breakdown sheet — a flat
    # student list across 30-odd departments says nothing on its own.
    dept_rows = await _department_breakdown_rows() if _is_overall(dept) else None

    excel_bytes = await _in_thread(
        generate_cohort_excel,
        dept, users_list, survey_type,
        dept_rows=dept_rows,
    )
    
    filename = f"HACRI_E2_{survey_type.upper()}_Export_{dept}.xlsx"
    filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

@router.get("/shared/analysis/download-ppt")
async def shared_download_ppt(
    dept: str = Query(...),
    token: str = Query(...),
    type: str = Query(default="pre"),
):
    survey_type = type if type in ("pre", "post") else "pre"
    if not verify_token(dept, token, survey_type):
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch all users in department filtered by type
    users_list_all = await list_survey_users(dept=dept)
    if survey_type == "post":
        users_list = [u for u in users_list_all if u.get("status") == "post_done"]
    else:
        users_list = [u for u in users_list_all if u.get("status") in ("pre_done", "post_done")]
    
    # Fetch matched pre/post records
    matched_data = await list_matched_users(program=dept)
    
    ppt_bytes = await _in_thread(generate_dept_ppt, dept, users_list, matched_data)
    
    filename = f"HACRI_E2_{survey_type.upper()}_Analysis_{dept}.pptx"
    filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    
    return StreamingResponse(
        io.BytesIO(ppt_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

@router.get("/shared/analysis/charts/cohort.png")
async def shared_chart_cohort(
    dept: str = Query(...),
    token: str = Query(...),
    type: str = Query(default="pre"),
    force: int = Query(default=0),
):
    survey_type = type if type in ("pre", "post") else "pre"
    if not verify_token(dept, token, survey_type):
        raise HTTPException(status_code=403, detail="Access denied")

    matched = await list_matched_users(program=dept)
    
    import hashlib
    key_str = f"cohort_dept={dept}"
    h = hashlib.md5(key_str.encode("utf-8")).hexdigest()
    out = settings.generated_root / f"cohort_{h}.png"

    if not matched:
        from app.charts import _write_placeholder
        _write_placeholder(out, "No matched responses yet for this cohort.")
        return FileResponse(str(out), media_type="image/png")

    if force or not out.exists():
        from app import charts as chart_helpers
        import asyncio
        await asyncio.get_running_loop().run_in_executor(
            None, chart_helpers.plot_cohort_png, matched, None, out
        )
    return FileResponse(str(out), media_type="image/png")

@router.get("/shared/analysis/charts/histograms.png")
async def shared_chart_histograms(
    dept: str = Query(...),
    token: str = Query(...),
    type: str = Query(default="pre"),
    force: int = Query(default=0),
):
    survey_type = type if type in ("pre", "post") else "pre"
    if not verify_token(dept, token, survey_type):
        raise HTTPException(status_code=403, detail="Access denied")

    matched = await list_matched_users(program=dept)
    
    import hashlib
    key_str = f"histograms_dept={dept}"
    h = hashlib.md5(key_str.encode("utf-8")).hexdigest()
    out = settings.generated_root / f"histograms_{h}.png"

    if not matched:
        from app.charts import _write_placeholder
        _write_placeholder(out, "No matched responses yet for this cohort.")
        return FileResponse(str(out), media_type="image/png")

    if force or not out.exists():
        from app import charts as chart_helpers
        import asyncio
        await asyncio.get_running_loop().run_in_executor(
            None, chart_helpers.plot_histograms_png, matched, None, out
        )
    return FileResponse(str(out), media_type="image/png")

@router.get("/shared/analysis/charts/h1_histogram.png")
async def shared_chart_h1(
    dept: str = Query(...),
    token: str = Query(...),
    type: str = Query(default="pre"),
    force: int = Query(default=0),
):
    survey_type = type if type in ("pre", "post") else "pre"
    if not verify_token(dept, token, survey_type):
        raise HTTPException(status_code=403, detail="Access denied")

    matched = await list_matched_users(program=dept)
    
    import hashlib
    key_str = f"h1_dept={dept}"
    h = hashlib.md5(key_str.encode("utf-8")).hexdigest()
    out = settings.generated_root / f"h1_histogram_{h}.png"

    if not matched:
        from app.charts import _write_placeholder
        _write_placeholder(out, "No matched responses yet for this cohort.")
        return FileResponse(str(out), media_type="image/png")

    if force or not out.exists():
        from app import charts as chart_helpers
        import asyncio
        await asyncio.get_running_loop().run_in_executor(
            None, chart_helpers.plot_h1_histogram_custom, matched, out
        )
    return FileResponse(str(out), media_type="image/png")


@router.get("/shared/orientation", response_class=HTMLResponse)
async def shared_orientation_page(
    request: Request,
    token: str = Query(...),
    campus: str = Query(default=""),
    dept: str = Query(default=""),
):
    """The Deeksharambh orientation report, readable without an admin login.

    The page itself is a shell; everything on it comes from the data endpoint
    below, which checks the same token again. A department link opens the same
    shell locked to that one department.
    """
    dept, locked = resolve_orientation_scope(campus, token, dept)

    return request.app.state.templates.TemplateResponse(
        request,
        "shared_orientation.html",
        {
            "campus": campus,
            "campus_label": campus or "All campuses",
            "dept": dept,
            "locked": locked,
            "scope_label": dept if locked else (campus or "All campuses"),
            "token": token,
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        },
    )


@router.get("/shared/orientation/data")
async def shared_orientation_data(
    token: str = Query(...),
    campus: str = Query(default=""),
    dept: str = Query(default=""),
):
    """Everything the shared orientation page draws, in one payload.

    `dept` narrows the report the way the dashboard's filter does — freely for
    a campus link, and only to its own department for a department link.
    """
    dept, locked = resolve_orientation_scope(campus, token, dept)

    from app.orientation_data import (
        build_report, department_overview, department_scorecard,
        orientation_dataset,
    )

    scoped = await orientation_dataset(campus=campus, dept=dept)
    report = build_report(scoped["filled"], scoped["pending"], campus)

    # Department comparison always covers the whole campus — narrowing it to
    # one department would leave nothing to compare against.
    whole = scoped if not dept else await orientation_dataset(campus=campus)
    departments = department_overview(whole["filled"], whole["pending"], campus)

    payload = {
        "campus": campus or "All campuses",
        "dept": dept,
        "locked": locked,
        "report": report,
        "departments": departments,
        "dept_options": sorted({r["program"] for r in whole["filled"] if r["program"] != "—"}),
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }

    if locked:
        # A department link is that department's own report. It still gets the
        # campus average to read its numbers against, but not the leaderboard
        # naming everybody else.
        payload["scorecard"] = department_scorecard(
            whole["filled"], whole["pending"], dept, campus)
        payload["departments"] = {
            **departments,
            "departments": [r for r in departments["departments"] if r["dept"] == dept],
        }
        payload["dept_options"] = [dept]

    return JSONResponse(payload)


@router.get("/shared/orientation/ppt")
async def shared_orientation_ppt(
    token: str = Query(...),
    campus: str = Query(default=""),
    dept: str = Query(default=""),
):
    """The same slide deck the admin can download, for whoever holds the link."""
    dept, _ = resolve_orientation_scope(campus, token, dept)

    from app.orientation_data import deck_response

    return await deck_response(campus=campus, dept=dept)


@router.get("/shared/cohort", response_class=HTMLResponse)
async def shared_cohort_page(
    request: Request,
    token: str = Query(...),
    campus: str = Query(default=""),
):
    """The outcome and impact report, readable without an admin login."""
    if not verify_cohort_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied: Invalid or expired sharing link.")

    return request.app.state.templates.TemplateResponse(
        request,
        "shared_cohort.html",
        {
            "campus": campus,
            "campus_label": campus or "All campuses",
            "token": token,
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        },
    )


@router.get("/shared/cohort/data")
async def shared_cohort_data(
    token: str = Query(...),
    campus: str = Query(default=""),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Everything the shared cohort page draws, in one payload."""
    if not verify_cohort_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.cohort_analysis import cohort_report

    report = await cohort_report(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    # The department picker lists the whole campus, not just what is in scope.
    whole = report if not dept else await cohort_report(campus=campus)
    return JSONResponse({
        "report": report,
        "dept_options": sorted({d["dept"] for d in whole["departments"]}),
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    })


@router.get("/shared/cohort/ppt")
async def shared_cohort_ppt(
    token: str = Query(...),
    campus: str = Query(default=""),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """The same deck the admin can download, for whoever holds the link."""
    if not verify_cohort_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.cohort_analysis import cohort_deck_response

    return await cohort_deck_response(campus=campus, dept=dept, ug_or_pg=ug_or_pg)


@router.get("/shared/departments", response_class=HTMLResponse)
async def shared_departments_list(request: Request, token: str = Query(...)):
    """One shareable page covering every department.

    Shows, per department: how many registered, how many finished the baseline
    and the post survey, how many are still pending, and how the reminder mails
    landed — with links through to that department's own analysis page and
    Excel exports. Reachable only with the directory token.
    """
    if not hmac.compare_digest(get_directory_token(), token):
        raise HTTPException(status_code=403, detail="Access denied: Invalid or expired sharing link.")

    from app.db import get_dept_analysis_data

    analysis_data = await get_dept_analysis_data()
    rows = await _department_breakdown_rows()

    ov = analysis_data["overall"]
    registered = ov.get("registered", 0)
    pre_done = ov.get("pre_done", 0)
    post_done = ov.get("post_done", 0)
    overall_row = {
        "name": "Overall (All Departments)",
        "dept_key": OVERALL,
        "registered": registered,
        "pre_done": pre_done,
        "post_done": post_done,
        "pre_pending": max(0, registered - pre_done),
        "post_pending": max(0, pre_done - post_done),
        "reminders_sent": sum(r["reminders_sent"] for r in rows),
        "clicked": sum(r["clicked"] for r in rows),
        "completed_after": sum(r["completed_after"] for r in rows),
        "avg_lit_pre": ov.get("avg_lit_pre"),
        "avg_read_pre": ov.get("avg_read_pre"),
        "avg_lit_post": ov.get("avg_lit_post"),
        "avg_read_post": ov.get("avg_read_post"),
        "token_pre": ov.get("token_pre"),
        "token_post": ov.get("token_post"),
        "student_post_path": "/post/all",
    }

    # Each department also gets its own Deeksharambh link, locked to it.
    overall_row["orientation_token"] = get_orientation_token("")
    dept_list = [overall_row] + [
        {**r, "name": r["dept"], "dept_key": r["dept"],
         "orientation_token": get_orientation_token("", r["dept"])}
        for r in rows
    ]

    return request.app.state.templates.TemplateResponse(
        request,
        "shared_departments.html",
        {
            "dept_list": dept_list,
            "overall": overall_row,
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        }
    )


@router.get("/shared/impact", response_class=HTMLResponse)
async def shared_impact(request: Request, token: str = Query(...), campus: str = Query(default="")):
    """The impact page, open to anyone holding the link.

    Counts only students who finished both surveys, so "Outcome" and "Impact"
    describe the same people measured twice. A campus token opens that campus
    alone — a Kochi link cannot be edited into a Bangalore one.
    """
    if not verify_vibe_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied: Invalid or expired sharing link.")

    from app.vibe_report import vibe_report

    from app.orientation_analysis import CAMPUSES

    report = await vibe_report(campus=campus)

    # Every Deeksharambh report reachable from this one page: the campus as a
    # whole, then each department on its own signed link. Anyone holding the
    # impact link can open all of them — that is the point of gathering them
    # here, and they carry aggregate figures only, never a named student.
    base = str(request.base_url).rstrip("/")
    orientation_links = [{
        "dept": "",
        "label": campus or "Every department, every campus",
        "count": report.get("orientation", 0),
        "url": orientation_share_url(base, campus),
    }] + [
        {
            "dept": row["dept"],
            "label": row["dept"],
            "count": row["count"],
            "url": orientation_share_url(base, campus, row["dept"]),
        }
        for row in sorted(report.get("departments") or [], key=lambda r: r["dept"].lower())
    ]

    from app.deeksharambh_brief_export import THEME_LINE, THEME_TITLE

    return request.app.state.templates.TemplateResponse(
        request, "shared_vibe.html", {
            "report": report,
            "campus": campus,
            "orientation_links": orientation_links,
            "brief_theme_title": THEME_TITLE,
            "brief_theme_line": THEME_LINE,
            # The switcher in the hero needs each campus's own token: a link is
            # only ever valid for the campus it names.
            "all_token": get_vibe_token(""),
            "campus_tokens": {name: get_vibe_token(name) for name in CAMPUSES},
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        },
    )


def _brief_filename(campus: str, ext: str) -> str:
    name = f"Deeksharambh_2026_Student_Experience_Brief_{campus or 'All'}.{ext}"
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


@router.get("/shared/impact/brief-ppt")
async def shared_impact_brief_ppt(token: str = Query(...), campus: str = Query(default="")):
    """The Student Experience & Orientation Impact Analysis brief, for
    whoever holds the impact link — the same deck the admin can download."""
    if not verify_vibe_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.deeksharambh_brief_export import build_deeksharambh_brief_pptx
    from app.orientation_data import deeksharambh_brief

    data = await deeksharambh_brief(campus=campus)
    ppt_bytes = await _in_thread(
        build_deeksharambh_brief_pptx, data,
        generated_at=datetime.now().strftime("%d %b %Y, %H:%M"))

    return StreamingResponse(
        io.BytesIO(ppt_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{_brief_filename(campus, "pptx")}"'},
    )


@router.get("/shared/impact/brief-docx")
async def shared_impact_brief_docx(token: str = Query(...), campus: str = Query(default="")):
    """The same brief, as a Word document."""
    if not verify_vibe_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.deeksharambh_brief_export import build_deeksharambh_brief_docx
    from app.orientation_data import deeksharambh_brief

    data = await deeksharambh_brief(campus=campus)
    docx_bytes = await _in_thread(
        build_deeksharambh_brief_docx, data,
        generated_at=datetime.now().strftime("%d %b %Y, %H:%M"))

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{_brief_filename(campus, "docx")}"'},
    )


@router.get("/shared/impact/brief-xlsx")
async def shared_impact_brief_xlsx(token: str = Query(...), campus: str = Query(default="")):
    """The same brief's numbers, as a workbook."""
    if not verify_vibe_token(campus, token):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.deeksharambh_brief_export import build_deeksharambh_brief_xlsx
    from app.orientation_data import deeksharambh_brief

    data = await deeksharambh_brief(campus=campus)
    xlsx_bytes = await _in_thread(
        build_deeksharambh_brief_xlsx, data,
        generated_at=datetime.now().strftime("%d %b %Y, %H:%M"))

    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_brief_filename(campus, "xlsx")}"'},
    )
