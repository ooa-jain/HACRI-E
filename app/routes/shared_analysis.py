"""
Router for public shared department-wise analysis.
Exposes endpoints for viewing statistics, charts, downloading PPT, and exporting Excel.
Uses cryptographic token validation.
"""
from __future__ import annotations
import hmac
import hashlib
import io
from pathlib import Path
from typing import Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
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


def directory_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/shared/departments?token={get_directory_token()}"


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
        }
    )


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

    # Query users based on type
    users_list = []
    async for u in db["users"].find(query).sort("created_at", -1):
        # For pre: include everyone who at least completed pre
        # For post: include only those who completed post
        status = u.get("status", "")
        if survey_type == "pre" and status not in ("pre_done", "post_done"):
            continue
        if survey_type == "post" and status != "post_done":
            continue
        users_list.append(u)

    emails = {u["email"] for u in users_list}
    pre_docs = []
    if survey_type == "pre":
        async for doc in db["pre_responses"].find({"email": {"$in": list(emails)}}):
            pre_docs.append(doc)
    post_docs = []
    if survey_type == "post":
        async for doc in db["post_responses"].find({"email": {"$in": list(emails)}}):
            post_docs.append(doc)

    # The all-departments export gets a per-department breakdown sheet — a flat
    # student list across 30-odd departments says nothing on its own.
    dept_rows = await _department_breakdown_rows() if _is_overall(dept) else None

    excel_bytes = generate_cohort_excel(
        dept, users_list,
        pre_docs if survey_type == "pre" else [],
        post_docs if survey_type == "post" else [],
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
    
    ppt_bytes = generate_dept_ppt(dept, users_list, matched_data)
    
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
    }

    dept_list = [overall_row] + [
        {**r, "name": r["dept"], "dept_key": r["dept"]} for r in rows
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

