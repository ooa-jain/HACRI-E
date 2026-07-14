"""
admin.py — Two separate admin sections with separate logins.

Survey Admin (HACRI-E):
  GET  /admin/survey/login    → login form
  POST /admin/survey/login    → authenticate
  GET  /admin/survey          → dashboard: survey users, flags, alerts
  GET  /admin/survey/logout

Orientation Admin (Deeksharambh):
  GET  /admin/orientation/login  → login form
  POST /admin/orientation/login  → authenticate
  GET  /admin/orientation        → dashboard: orientation responses, flag
  GET  /admin/orientation/logout

Shared API (each checks its own cookie):
  GET  /admin/api/flags
  POST /admin/api/flags
  GET  /admin/api/survey/users
  GET  /admin/api/orientation/responses
  POST /admin/api/alert/post-pending

OTP Login for Survey Admin:
  POST /admin/survey/request-otp  → generates and emails OTP to admin email
  POST /admin/login               → verifies OTP (or static password for orientation)
"""
from __future__ import annotations
import logging
import secrets
import time
from datetime import datetime
from fastapi import APIRouter, Form, HTTPException, Request, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from app.db import (
    FLAG_ORIENTATION, FLAG_SURVEY, FLAG_PRE_SURVEY,
    STATUS_PRE_DONE, STATUS_POST_DONE, FLAG_TEST_MODE,
    get_all_flags, list_orientation_responses, list_survey_users, set_flag,
    get_db, FLAGS, ORI,
)
from app.settings import settings

log = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory OTP store (otp, expiry timestamp) ────────────────────────────
_survey_otp_store: dict[str, float] = {}  # {otp_code: expiry_ts}
_OTP_TTL = 10 * 60  # 10 minutes


# ── OTP request endpoint ──────────────────────────────────────────────────────
@router.post("/admin/survey/request-otp")
async def survey_request_otp(request: Request, username: str = Form(...)):
    """Generate & email a 6-digit OTP to the admin email, then redirect back to login form."""
    if username != settings.survey_admin_username:
        # Show invalid username but don't reveal info
        return request.app.state.templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Invalid username.", "title": "Admin Login", "otp_sent": False},
            status_code=401,
        )

    # Generate a 6-digit OTP and store it
    otp = str(secrets.randbelow(900000) + 100000)  # 100000–999999
    expiry = time.time() + _OTP_TTL
    _survey_otp_store.clear()  # Only one valid OTP at a time
    _survey_otp_store[otp] = expiry

    # Send email
    try:
        from app import emailer
        body = (
            f"Your HACRI-E Admin OTP is: {otp}\n\n"
            f"This OTP is valid for 10 minutes.\n\n"
            f"If you did not request this, please ignore this email."
        )
        await emailer.send_simple_email(
            settings.survey_admin_otp_email,
            "HACRI-E Admin",
            "HACRI-E Admin Login OTP",
            body,
        )
        log.info("OTP [%s] sent to %s", otp, settings.survey_admin_otp_email)
    except Exception as exc:
        log.exception("Failed to send OTP email: %s", exc)
        return request.app.state.templates.TemplateResponse(
            request, "admin_login.html",
            {"error": f"Failed to send OTP email. Please check SMTP config. ({exc})",
             "title": "Admin Login", "otp_sent": False},
            status_code=500,
        )

    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html",
        {
            "title": "Admin Login",
            "otp_sent": True,
            "otp_username": username,
            "otp_email_hint": settings.survey_admin_otp_email,
            "error": None,
        },
    )


@router.get("/admin/login", response_class=HTMLResponse)
async def general_admin_login_get(request: Request):
    if _is_survey_admin(request):
        return RedirectResponse(url="/admin/survey", status_code=303)
    if _is_ori_admin(request):
        return RedirectResponse(url="/admin/orientation", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html",
        {"error": None, "title": "Admin Login", "otp_sent": False},
    )


@router.post("/admin/login")
async def general_admin_login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    # Survey admin: verify OTP
    if username == settings.survey_admin_username:
        otp = password.strip()
        expiry = _survey_otp_store.get(otp)
        if expiry and time.time() < expiry:
            _survey_otp_store.pop(otp, None)  # Consume OTP
            r = RedirectResponse(url="/admin/survey", status_code=303)
            _set_cookie(r, _SURVEY_COOKIE, settings.cookie_secure, settings.cookie_samesite)
            return r
        return request.app.state.templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Invalid or expired OTP. Please request a new one.",
             "title": "Admin Login", "otp_sent": True, "otp_username": username},
            status_code=401,
        )
    elif username == settings.orientation_admin_username and password == settings.orientation_admin_password:
        r = RedirectResponse(url="/admin/orientation", status_code=303)
        _set_cookie(r, _ORI_COOKIE, settings.cookie_secure, settings.cookie_samesite)
        return r
    
    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html",
        {"error": "Invalid credentials", "title": "Admin Login", "otp_sent": False},
        status_code=401,
    )


@router.get("/admin")
async def general_admin(request: Request):
    if _is_survey_admin(request):
        return RedirectResponse(url="/admin/survey", status_code=303)
    if _is_ori_admin(request):
        return RedirectResponse(url="/admin/orientation", status_code=303)
    return RedirectResponse(url="/admin/login", status_code=303)


# Redirect legacy login routes
@router.get("/admin/survey/login")
@router.post("/admin/survey/login")
async def old_survey_login_redirect():
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/admin/orientation/login")
@router.post("/admin/orientation/login")
async def old_ori_login_redirect():
    return RedirectResponse(url="/admin/login", status_code=303)


_SURVEY_COOKIE = "survey_admin_session"
_ORI_COOKIE    = "orientation_admin_session"


# ── Auth helpers ───────────────────────────────────────────────────────────────
def _is_survey_admin(request: Request) -> bool:
    return request.cookies.get(_SURVEY_COOKIE) == "1"

def _is_ori_admin(request: Request) -> bool:
    return request.cookies.get(_ORI_COOKIE) == "1"

def _set_cookie(response, key, secure=False, samesite="lax"):
    response.set_cookie(key, "1", httponly=True, secure=secure,
                        samesite=samesite, max_age=60*60*8)

def _del_cookie(response, key):
    response.delete_cookie(key)


# ══════════════════════════════════════════════════════════════════════════════
# SURVEY ADMIN
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/admin/survey/logout")
async def survey_logout():
    r = RedirectResponse(url="/admin/login", status_code=303)
    _del_cookie(r, _SURVEY_COOKIE)
    return r

@router.get("/admin/survey", response_class=HTMLResponse)
async def survey_dashboard(request: Request):
    if not _is_survey_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    flags = await get_all_flags()
    public_url = str(settings.public_base_url).rstrip('/')
    orientation_share_url = f"{public_url}/deeksharambh"
    return request.app.state.templates.TemplateResponse(
        request, "admin_survey.html", {
            "flags": flags,
            "orientation_share_url": orientation_share_url
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# ORIENTATION ADMIN
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/admin/orientation/logout")
async def ori_logout():
    r = RedirectResponse(url="/admin/login", status_code=303)
    _del_cookie(r, _ORI_COOKIE)
    return r

@router.get("/admin/orientation", response_class=HTMLResponse)
async def ori_dashboard(request: Request):
    if not _is_ori_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    flags = await get_all_flags()
    return request.app.state.templates.TemplateResponse(
        request, "admin_orientation.html", {"flags": flags},
    )


# ══════════════════════════════════════════════════════════════════════════════
# SHARED API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ── Feature flags (either admin can toggle their own flag) ─────────────────────
@router.get("/admin/api/flags")
async def api_get_flags(request: Request):
    if not (_is_survey_admin(request) or _is_ori_admin(request)):
        raise HTTPException(status_code=403)
    return JSONResponse(await get_all_flags())

@router.post("/admin/api/flags")
async def api_set_flags(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400)

    # Survey admin can toggle survey flag, pre-survey flag, post-survey flag, post delay setting, and test mode
    if _is_survey_admin(request):
        if FLAG_SURVEY in body:
            await set_flag(FLAG_SURVEY, bool(body[FLAG_SURVEY]))
        if FLAG_PRE_SURVEY in body:
            await set_flag(FLAG_PRE_SURVEY, bool(body[FLAG_PRE_SURVEY]))
        if "post_survey_enabled" in body:
            await set_flag("post_survey_enabled", bool(body["post_survey_enabled"]))
        if FLAG_ORIENTATION in body:
            await set_flag(FLAG_ORIENTATION, bool(body[FLAG_ORIENTATION]))
        if FLAG_TEST_MODE in body:
            await set_flag(FLAG_TEST_MODE, bool(body[FLAG_TEST_MODE]))
        if "post_delay_days" in body:
            from app.db import _now
            val = int(body["post_delay_days"])
            await get_db()[FLAGS].update_one(
                {"key": "post_delay_days"},
                {"$set": {"key": "post_delay_days", "value": val, "updated_at": _now()}},
                upsert=True,
            )
    # Orientation admin can only toggle orientation flag
    if _is_ori_admin(request) and FLAG_ORIENTATION in body:
        await set_flag(FLAG_ORIENTATION, bool(body[FLAG_ORIENTATION]))
    # If neither → 403
    if not (_is_survey_admin(request) or _is_ori_admin(request)):
        raise HTTPException(status_code=403)

    return JSONResponse({"ok": True, "flags": await get_all_flags()})


# ── Survey users (survey admin only) ──────────────────────────────────────────
@router.get("/admin/api/survey/users")
async def api_survey_users(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    return JSONResponse(await list_survey_users(
        dept=dept or None,
        ug_or_pg=ug_or_pg or None,
    ))


@router.get("/admin/api/survey/dept-stats")
async def api_survey_dept_stats(request: Request):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    
    from app.db import get_dept_stats
    from app.routes.shared_analysis import get_dept_token
    
    raw_stats = await get_dept_stats()
    
    # Append two shareable tokens per department (pre and post)
    stats = []
    for s in raw_stats:
        dept_name = s["dept"]
        token_pre = get_dept_token(dept_name, "pre")
        token_post = get_dept_token(dept_name, "post")
        base = str(settings.public_base_url).rstrip('/')
        stats.append({
            **s,
            "token_pre": token_pre,
            "token_post": token_post,
            "share_url_pre": f"{base}/shared/analysis?dept={dept_name}&token={token_pre}&type=pre",
            "share_url_post": f"{base}/shared/analysis?dept={dept_name}&token={token_post}&type=post",
        })
        
    return JSONResponse(stats)


# ── Orientation responses (both admins can view) ───────────────────────────────
@router.get("/admin/api/orientation/responses")
async def api_orientation_responses(request: Request):
    if not (_is_survey_admin(request) or _is_ori_admin(request)):
        raise HTTPException(status_code=403)
    return JSONResponse(await list_orientation_responses())


# ── Send alert emails to registered-only students (survey admin only) ──
@router.post("/admin/api/alert/pre-pending")
async def api_send_pre_alert(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)
    pending = [u for u in users if u.get("status") in ("not_started", None)]
    sent = failed = 0
    for u in pending:
        try:
            await _send_pre_alert_email(u["email"], u["name"])
            sent += 1
        except Exception as e:
            log.warning("Pre alert email failed for %s: %s", u["email"], e)
            failed += 1
    return JSONResponse({"ok": True, "sent": sent, "failed": failed, "total_pending": len(pending)})


async def _send_pre_alert_email(email: str, name: str) -> None:
    from app import emailer
    from app.routes.landing import email_to_slug
    slug = email_to_slug(email)
    resume_link = f"{settings.public_base_url.rstrip('/')}/resume/{slug}"
    
    subject = "Reminder: Please complete the AI Baseline Survey"
    body = (
        f"Hi {name},\n\n"
        "We noticed you registered for the AI Baseline Survey but haven't completed it yet.\n\n"
        "Please click the link below to directly resume and finish your survey (no login required):\n"
        f"{resume_link}\n\n"
        "Thank you,\nOffice of Academics\nJAIN (Deemed-to-be University)"
    )
    await emailer.send_simple_email(email, name, subject, body)


# ── Send alert emails to pre-done / post-pending students (survey admin only) ──
@router.post("/admin/api/alert/post-pending")
async def api_send_alert(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)
    pending = [u for u in users if u.get("status") == STATUS_PRE_DONE]
    sent = failed = 0
    for u in pending:
        try:
            await _send_alert_email(u["email"], u["name"])
            sent += 1
        except Exception as e:
            log.warning("Alert email failed for %s: %s", u["email"], e)
            failed += 1
    return JSONResponse({"ok": True, "sent": sent, "failed": failed, "total_pending": len(pending)})


async def _send_alert_email(email: str, name: str) -> None:
    from app import emailer
    from app.routes.landing import email_to_slug
    slug = email_to_slug(email)
    resume_link = f"{settings.public_base_url.rstrip('/')}/resume/{slug}"
    
    subject = "Reminder: Please complete the Post-Workshop Survey"
    body = (
        f"Hi {name},\n\n"
        "Thank you for completing the Baseline Survey.\n\n"
        "You haven't yet submitted the Post-Workshop Survey. Please click the link below to directly resume and complete it (no login required):\n"
        f"{resume_link}\n\n"
        "Thank you,\nOffice of Academics\nJAIN (Deemed-to-be University)"
    )
    await emailer.send_simple_email(email, name, subject, body)


@router.post("/admin/api/send-results/{email}")
async def api_send_results(
    request: Request,
    email: str,
    background_tasks: BackgroundTasks,
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    db = get_db()
    user = await db["users"].find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("status") != STATUS_POST_DONE:
        raise HTTPException(status_code=400, detail="User has not completed both surveys")

    from app.routes.surveys import _after_post_submit
    background_tasks.add_task(_after_post_submit, user["email"], user["name"])
    return JSONResponse({"ok": True, "message": f"Results email queued for {email}"})


@router.get("/admin/survey/export-cohort")
async def admin_export_cohort(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
    format: str = Query(default="xlsx"),
    status_filter: str = Query(default="all"),
    inc_profile: bool = Query(default=False),
    inc_timestamps: bool = Query(default=False),
    inc_scores: bool = Query(default=False),
    inc_responses: bool = Query(default=False),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    db = get_db()
    query = {}
    if dept:
        query["program"] = dept
    if ug_or_pg:
        query["ug_or_pg"] = ug_or_pg

    # Check if request comes from the new custom modal
    is_modal = "status_filter" in request.query_params
    if not is_modal:
        format = "csv"
        status_filter = "all"
        inc_profile = True
        inc_timestamps = True
        inc_scores = True
        inc_responses = True  # Legacy behavior included all question responses

    users_list = []
    async for u in db["users"].find(query).sort("created_at", -1):
        status_v = u.get("status") or "not_started"
        if status_filter == "pre_done" and status_v not in ("pre_done", "post_done"):
            continue
        if status_filter == "post_done" and status_v != "post_done":
            continue
        if status_filter == "pending_pre" and status_v in ("pre_done", "post_done"):
            continue
        if status_filter == "pending_post" and status_v != "pre_done":
            continue
        users_list.append(u)

    emails = {u["email"] for u in users_list}
    pre_docs = []
    async for doc in db["pre_responses"].find({"email": {"$in": list(emails)}}):
        pre_docs.append(doc)

    post_docs = []
    async for doc in db["post_responses"].find({"email": {"$in": list(emails)}}):
        post_docs.append(doc)

    from app.csv_export import custom_cohort_export
    file_data, media_type, ext = custom_cohort_export(
        users_list,
        pre_docs,
        post_docs,
        format=format,
        inc_profile=inc_profile,
        inc_timestamps=inc_timestamps,
        inc_scores=inc_scores,
        inc_responses=inc_responses,
    )

    import io
    suffix = ""
    if dept:
        suffix += f"_{dept}"
    if ug_or_pg:
        suffix += f"_{ug_or_pg.upper()}"
    if status_filter != "all":
        suffix += f"_{status_filter}"
    filename = f"HACRI_E2_Cohort_Export{suffix}.{ext}"
    # remove spaces and special characters from filename
    filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.delete("/admin/api/survey/users/{email}")
async def api_delete_user(request: Request, email: str):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import delete_user_and_responses
    await delete_user_and_responses(email)
    return JSONResponse({"ok": True})


# ── View a single orientation response ─────────────────────────────────────────
@router.get("/admin/orientation/view/{email}")
async def api_view_orientation(request: Request, email: str):
    if not (_is_survey_admin(request) or _is_ori_admin(request)):
        raise HTTPException(status_code=403)
    doc = await get_db()[ORI].find_one(
        {"email": email}, sort=[("submitted_at", -1)]
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Orientation response not found")
    return JSONResponse({
        "email": doc.get("email", ""),
        "name": doc.get("name", ""),
        "submitted_at": doc.get("submitted_at").strftime("%d %b %Y %H:%M") if doc.get("submitted_at") else "",
        "data": doc.get("data", {}),
    })
