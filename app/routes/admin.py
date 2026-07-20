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

# ── In-memory OTP store (username -> (otp, expiry timestamp)) ────────────────
_admin_otp_store: dict[str, tuple[str, float]] = {}
_OTP_TTL = 10 * 60  # 10 minutes


# ── OTP request endpoint ──────────────────────────────────────────────────────
@router.post("/admin/survey/request-otp")
async def survey_request_otp(request: Request, username: str = Form(...)):
    """Generate & email a 6-digit OTP to the admin email, then redirect back to login form."""
    username = username.strip()
    if username == settings.survey_admin_username:
        email = settings.survey_admin_otp_email
        portal_name = "HACRI-E Survey Admin"
    elif username == settings.orientation_admin_username:
        email = settings.orientation_admin_otp_email
        portal_name = "Deeksharambh Orientation Admin"
    else:
        # Show invalid username but don't reveal info
        return request.app.state.templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Invalid username.", "title": "Admin Login", "otp_sent": False},
            status_code=401,
        )

    # Generate a 6-digit OTP and store it
    otp = str(secrets.randbelow(900000) + 100000)  # 100000–999999
    expiry = time.time() + _OTP_TTL
    from app.db import save_admin_otp
    await save_admin_otp(username, otp, expiry)

    # Send email
    try:
        from app import emailer
        body = (
            f"Your {portal_name} OTP is: {otp}\n\n"
            f"This OTP is valid for 10 minutes.\n\n"
            f"If you did not request this, please ignore this email."
        )
        await emailer.send_simple_email(
            email,
            portal_name,
            f"{portal_name} Login OTP",
            body,
        )
        log.info("OTP [%s] sent to %s for %s", otp, email, username)
    except Exception as exc:
        log.exception("Failed to send OTP email: %s", exc)
        err_str = str(exc).lower()
        if "451" in err_str or "ratelimit" in err_str or "rate limit" in err_str:
            msg = ("The mail server is temporarily rate-limited, so the OTP email "
                   "couldn't be sent right now. Use “Login with password instead” "
                   "below, or try the OTP again in about an hour.")
        else:
            msg = (f"Couldn't send the OTP email ({exc}). Use “Login with password "
                   f"instead” below, or check the SMTP configuration.")
        return request.app.state.templates.TemplateResponse(
            request, "admin_login.html",
            {"error": msg, "title": "Admin Login", "otp_sent": False},
            status_code=200,
        )

    # Mask email hint for privacy, e.g. "sa***.ks@jainuniversity.ac.in"
    email_parts = email.split("@")
    if len(email_parts) == 2:
        userpart, domain = email_parts
        if len(userpart) > 3:
            masked_user = userpart[:2] + "***" + userpart[-1]
        else:
            masked_user = "***"
        masked_email = f"{masked_user}@{domain}"
    else:
        masked_email = "registered admin email"

    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html",
        {
            "title": "Admin Login",
            "otp_sent": True,
            "otp_username": username,
            "otp_email_hint": masked_email,
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
    password: str = Form(...)  # This acts as the OTP
):
    username = username.strip()
    otp = password.strip()
    
    if username == settings.orientation_admin_username and otp == settings.orientation_admin_password:
        r = RedirectResponse(url="/admin/orientation", status_code=303)
        _set_cookie(r, _ORI_COOKIE, settings.cookie_secure, settings.cookie_samesite)
        return r

    if username == settings.survey_admin_username and otp == settings.survey_admin_password:
        r = RedirectResponse(url="/admin/survey", status_code=303)
        _set_cookie(r, _SURVEY_COOKIE, settings.cookie_secure, settings.cookie_samesite)
        return r

    from app.db import verify_admin_otp
    is_valid = await verify_admin_otp(username, otp)
    if is_valid:
        if username == settings.survey_admin_username:
            r = RedirectResponse(url="/admin/survey", status_code=303)
            _set_cookie(r, _SURVEY_COOKIE, settings.cookie_secure, settings.cookie_samesite)
            return r
        elif username == settings.orientation_admin_username:
            r = RedirectResponse(url="/admin/orientation", status_code=303)
            _set_cookie(r, _ORI_COOKIE, settings.cookie_secure, settings.cookie_samesite)
            return r
    else:
        err_msg = "Invalid credentials or expired OTP. Please request a new one."

    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html",
        {
            "error": err_msg,
            "title": "Admin Login",
            "otp_sent": True,
            "otp_username": username,
            "otp_email_hint": "registered admin email"
        },
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
        if "auto_reminders_enabled" in body:
            await set_flag("auto_reminders_enabled", bool(body["auto_reminders_enabled"]))
        if "auto_reminder_delay_days" in body:
            from app.db import _now
            val = int(body["auto_reminder_delay_days"])
            await get_db()[FLAGS].update_one(
                {"key": "auto_reminder_delay_days"},
                {"$set": {"key": "auto_reminder_delay_days", "value": val, "updated_at": _now()}},
                upsert=True,
            )
        if "auto_reminder_repeat_days" in body:
            from app.db import _now
            val = max(1, int(body["auto_reminder_repeat_days"]))
            await get_db()[FLAGS].update_one(
                {"key": "auto_reminder_repeat_days"},
                {"$set": {"key": "auto_reminder_repeat_days", "value": val, "updated_at": _now()}},
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


async def run_bulk_reminder_task(task_id: str, type_name: str, pending_users: list[dict], base_url: str):
    """Send reminders to every pending user over a SINGLE SMTP connection.

    Reusing one connection (via emailer.SmtpBatchSender) is what makes large
    batches fast and keeps us under the provider's "too many connections" limit,
    so there is no longer a 100-recipient cap. Progress is written to the
    admin_tasks doc so the dashboard can poll it live.
    """
    import asyncio
    from datetime import datetime, timezone
    from app.db import get_db
    from app import emailer
    from app.routes.landing import email_to_slug

    db = get_db()
    delay = max(0.0, float(getattr(settings, "email_batch_delay_seconds", 0.4)))

    # Each pending entry may carry its own "kind" ("pre" | "post") — used by the
    # custom-segment sender where one batch mixes baseline and post reminders.
    # Entries without a kind fall back to the task-level type.
    default_kind = "pre" if type_name == "pre-pending" else "post"

    def _fields_for(kind: str):
        if kind == "pre":
            return ("pre_reminder_sent_at", "pre_reminder_count",
                    emailer.build_pre_reminder_message)
        return ("post_reminder_sent_at", "post_reminder_count",
                emailer.build_post_reminder_message)

    cooldown = max(0.0, float(getattr(settings, "email_ratelimit_cooldown_seconds", 60.0)))

    sent = 0
    failed = 0
    rate_limited = False
    try:
        async with emailer.SmtpBatchSender() as sender:
            for i, u in enumerate(pending_users):
                if i > 0 and delay:
                    await asyncio.sleep(delay)

                email = u.get("email")
                name = u.get("name", "")
                if not email:
                    continue

                stamp_field, count_field, build_msg = _fields_for(u.get("kind") or default_kind)
                slug = email_to_slug(email)
                resume_link = f"{base_url}/resume/{slug}?src=reminder"
                msg = build_msg(email, name, resume_link)

                try:
                    try:
                        await sender.send(msg)
                    except Exception as e1:
                        # Outbound rate-limit → wait once, then retry this message.
                        if emailer.is_rate_limit_error(e1) and cooldown:
                            log.warning("Rate-limited on %s; cooling down %.0fs then retrying.",
                                        email, cooldown)
                            await db["admin_tasks"].update_one(
                                {"_id": task_id},
                                {"$set": {"status": "cooling_down",
                                          "updated_at": datetime.now(timezone.utc)}})
                            await asyncio.sleep(cooldown)
                            await db["admin_tasks"].update_one(
                                {"_id": task_id},
                                {"$set": {"status": "running",
                                          "updated_at": datetime.now(timezone.utc)}})
                            await sender.send(msg)
                        else:
                            raise
                    await db["users"].update_one(
                        {"email": email},
                        {"$set": {stamp_field: datetime.now(timezone.utc)},
                         "$inc": {count_field: 1},
                         "$unset": {"last_email_error": "", "email_failed_at": ""}}
                    )
                    sent += 1
                except Exception as e:
                    log.warning("Bulk email failed for %s: %s", email, e)
                    await db["users"].update_one(
                        {"email": email},
                        {"$set": {"last_email_error": str(e),
                                  "email_failed_at": datetime.now(timezone.utc)}}
                    )
                    # If the provider is still rate-limiting after a cooldown+retry,
                    # stop now so the remaining recipients aren't burned — the admin
                    # can resume once the hourly quota resets.
                    if emailer.is_rate_limit_error(e):
                        rate_limited = True
                        await db["admin_tasks"].update_one(
                            {"_id": task_id},
                            {"$set": {"sent": sent, "failed": failed,
                                      "updated_at": datetime.now(timezone.utc)}})
                        break
                    failed += 1

                # Persist progress every message so the poller shows live counts.
                await db["admin_tasks"].update_one(
                    {"_id": task_id},
                    {"$set": {"sent": sent, "failed": failed,
                              "updated_at": datetime.now(timezone.utc)}}
                )
    except Exception as e:
        # Connection/login failure — mark everything remaining as failed.
        log.exception("Bulk reminder task %s aborted: %s", task_id, e)
        await db["admin_tasks"].update_one(
            {"_id": task_id},
            {"$set": {"status": "error", "error": str(e),
                      "updated_at": datetime.now(timezone.utc)}}
        )
        return

    if rate_limited:
        remaining = len(pending_users) - sent - failed
        await db["admin_tasks"].update_one(
            {"_id": task_id},
            {"$set": {
                "status": "rate_limited",
                "sent": sent, "failed": failed,
                "error": (f"Provider outbound rate limit hit. Sent {sent} before "
                          f"stopping; {max(0, remaining)} not yet sent. Wait for the "
                          f"hourly quota to reset, then click send again to continue."),
                "updated_at": datetime.now(timezone.utc)}}
        )
    else:
        await db["admin_tasks"].update_one(
            {"_id": task_id},
            {"$set": {"status": "completed", "sent": sent, "failed": failed,
                      "updated_at": datetime.now(timezone.utc)}}
        )


@router.post("/admin/api/alert/pre-pending")
async def api_send_pre_pending(
    request: Request,
    background_tasks: BackgroundTasks,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)
    pending = [u for u in users if u.get("status") in ("not_started", None)]

    # Sort so those who never received a reminder come first. No cap — the batch
    # sender reuses one SMTP connection, so all pending recipients are handled.
    pending.sort(key=lambda u: bool(u.get("pre_reminder_at")))

    import secrets
    task_id = "pre_" + secrets.token_hex(8)
    
    db = get_db()
    from datetime import datetime, timezone
    await db["admin_tasks"].insert_one({
        "_id": task_id,
        "type": "pre-pending",
        "status": "running",
        "total": len(pending),
        "sent": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    })
    
    base_url = str(request.base_url).rstrip("/")
    background_tasks.add_task(
        run_bulk_reminder_task,
        task_id,
        "pre-pending",
        pending,
        base_url
    )
    
    return JSONResponse({
        "ok": True,
        "task_id": task_id,
        "total_pending": len(pending)
    })


# ── Orientation responses (both admins can view) ───────────────────────────────
@router.get("/admin/api/orientation/responses")
async def api_orientation_responses(request: Request):
    if not (_is_survey_admin(request) or _is_ori_admin(request)):
        raise HTTPException(status_code=403)
    return JSONResponse(await list_orientation_responses())


# ── Send alert emails to pre-done / post-pending students (survey admin only) ──
@router.post("/admin/api/alert/post-pending")
async def api_send_alert(
    request: Request,
    background_tasks: BackgroundTasks,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)
    pending = [u for u in users if u.get("status") == STATUS_PRE_DONE]

    # Sort so those who never received a reminder come first. No cap — the batch
    # sender reuses one SMTP connection, so all pending recipients are handled.
    pending.sort(key=lambda u: bool(u.get("post_reminder_at")))

    import secrets
    task_id = "post_" + secrets.token_hex(8)
    
    db = get_db()
    from datetime import datetime, timezone
    await db["admin_tasks"].insert_one({
        "_id": task_id,
        "type": "post-pending",
        "status": "running",
        "total": len(pending),
        "sent": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    })
    
    base_url = str(request.base_url).rstrip("/")
    background_tasks.add_task(
        run_bulk_reminder_task,
        task_id,
        "post-pending",
        pending,
        base_url
    )
    
    return JSONResponse({
        "ok": True,
        "task_id": task_id,
        "total_pending": len(pending)
    })


# ── Send reminders to an explicit list of students (segment drill-down) ───────
@router.post("/admin/api/alert/custom")
async def api_send_custom_alert(request: Request, background_tasks: BackgroundTasks):
    """Send reminders to a specific set of students, e.g. the "clicked but not
    submitted" segment from the Email Notifications drill-down. The reminder
    kind is chosen per student: not-started → baseline (pre), pre-done → post.
    Students who already finished both surveys are skipped."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    try:
        body = await request.json()
        emails = [str(e).strip().lower() for e in (body.get("emails") or []) if e]
    except Exception:
        raise HTTPException(status_code=400, detail="Expected JSON body {emails: [...]}")
    if not emails:
        raise HTTPException(status_code=400, detail="No recipients given")
    emails = emails[:5000]

    db = get_db()
    pending = []
    async for u in db["users"].find({"email": {"$in": emails}}):
        status_v = u.get("status")
        if status_v in (None, "not_started"):
            kind = "pre"
        elif status_v == STATUS_PRE_DONE:
            kind = "post"
        else:
            continue  # both surveys done — nothing to remind about
        pending.append({"email": u["email"], "name": u.get("name", ""), "kind": kind})

    task_id = "custom_" + secrets.token_hex(8)
    from datetime import datetime, timezone
    await db["admin_tasks"].insert_one({
        "_id": task_id,
        "type": "custom",
        "status": "running",
        "total": len(pending),
        "sent": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    base_url = str(request.base_url).rstrip("/")
    background_tasks.add_task(run_bulk_reminder_task, task_id, "custom", pending, base_url)
    return JSONResponse({"ok": True, "task_id": task_id, "total_pending": len(pending)})


@router.get("/admin/api/alert/status/{task_id}")
async def api_get_alert_status(request: Request, task_id: str):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    db = get_db()
    task = await db["admin_tasks"].find_one({"_id": task_id})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return JSONResponse({
        "task_id": task["_id"],
        "type": task["type"],
        "status": task["status"],
        "total": task["total"],
        "sent": task.get("sent", 0),
        "failed": task.get("failed", 0),
        "error": task.get("error", ""),
    })


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


# ── Student Parental Background Analysis ─────────────────────────────────────
@router.get("/admin/api/survey/background-analysis")
async def api_background_analysis(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    
    db = get_db()
    
    query = {"status": STATUS_POST_DONE}
    if dept:
        query["program"] = dept
    if ug_or_pg:
        query["ug_or_pg"] = ug_or_pg
        
    users_dict = {}
    async for u in db["users"].find(query):
        users_dict[u["email"]] = u
        
    post_responses = []
    if users_dict:
        async for p in db["post_responses"].find({"email": {"$in": list(users_dict.keys())}}):
            post_responses.append(p)
            
    total = len(post_responses)
    salaried_count = 0
    entrepreneur_count = 0
    homemaker_count = 0
    
    salaried_list = []
    entrepreneur_list = []
    
    for p in post_responses:
        fields = p.get("fields", {})
        email = p.get("email", "")
        u_info = users_dict.get(email, {})
        student_name = u_info.get("name") or p.get("name", "")
        
        father_name = fields.get("father_name") or ""
        occupation = fields.get("father_occupation") or ""
        org_name = fields.get("organization_name") or ""
        biz_name = fields.get("business_name") or ""
        biz_type = fields.get("business_type") or ""

        mother_name = fields.get("mother_name") or ""
        mother_occupation = fields.get("mother_occupation") or ""
        mother_org_name = fields.get("mother_organization_name") or ""
        mother_biz_name = fields.get("mother_business_name") or ""
        mother_biz_type = fields.get("mother_business_type") or ""
        
        if not occupation:
            continue
            
        if occupation == "Salaried":
            salaried_count += 1
            salaried_list.append({
                "student_name": student_name,
                "email": email,
                "father_name": father_name,
                "organization_name": org_name,
                "mother_name": mother_name,
                "mother_occupation": mother_occupation,
                "mother_organization_name": mother_org_name,
                "mother_business_name": mother_biz_name,
                "mother_business_type": mother_biz_type,
            })
        elif occupation == "Entrepreneur":
            entrepreneur_count += 1
            entrepreneur_list.append({
                "student_name": student_name,
                "email": email,
                "father_name": father_name,
                "business_name": biz_name,
                "business_type": biz_type,
                "mother_name": mother_name,
                "mother_occupation": mother_occupation,
                "mother_organization_name": mother_org_name,
                "mother_business_name": mother_biz_name,
                "mother_business_type": mother_biz_type,
            })
        elif occupation == "Homemaker":
            homemaker_count += 1

    return JSONResponse({
        "total": total,
        "salaried_count": salaried_count,
        "entrepreneur_count": entrepreneur_count,
        "homemaker_count": homemaker_count,
        "salaried_list": salaried_list,
        "entrepreneur_list": entrepreneur_list
    })


@router.get("/admin/api/email-notification/stats")
async def api_email_notification_stats(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import get_email_notification_stats
    stats = await get_email_notification_stats(dept=dept or None, ug_or_pg=ug_or_pg or None)
    return JSONResponse(stats)


logger = logging.getLogger("hacri-e.auto-reminders")

# How often the worker wakes to check for due reminders (seconds).
AUTO_REMINDER_TICK_SECONDS = 3600  # hourly


def _reminder_is_due(prev, resend_cutoff) -> bool:
    """Decide (in Python, so we never mix types in a DB query) whether a
    reminder is due given the previously-stored stamp value.

    Due when: never sent (absent / None), a legacy "sending" sentinel, or the
    last send was on/before the daily resend cutoff.
    """
    from datetime import datetime, timezone
    if prev is None or prev == "sending":
        return True
    if isinstance(prev, datetime):
        # Some drivers (and mongomock) return naive datetimes; treat as UTC so
        # we never compare naive against aware.
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        return prev <= resend_cutoff
    return False  # unknown type — leave it alone


async def _run_daily_reminders(
    db,
    *,
    status_values: list,
    reg_field: str,
    stamp_field: str,
    count_field: str,
    build_msg,
    reg_cutoff,
    resend_cutoff,
    now,
    delay: float,
) -> dict:
    """One reminder pass for a single kind (pre or post).

    Sends over ONE shared SMTP connection and re-sends daily until the student
    completes the relevant survey. Returns {'sent': n, 'failed': m}.
    """
    import asyncio
    from pymongo import ReturnDocument
    from app.settings import settings
    from app import emailer
    from app.routes.landing import email_to_slug

    # Broad candidate query — only datetime fields are range-compared here, so
    # this is safe on both MongoDB and mongomock. Fine-grained "is it due yet?"
    # is decided in Python below.
    candidates = []
    async for u in db["users"].find({
        "status": {"$in": status_values},
        reg_field: {"$lte": reg_cutoff},
    }):
        if u.get("email") and _reminder_is_due(u.get(stamp_field), resend_cutoff):
            candidates.append(u)

    if not candidates:
        return {"sent": 0, "failed": 0}

    base_url = settings.public_base_url.rstrip("/")
    sent = 0
    failed = 0

    async with emailer.SmtpBatchSender() as sender:
        for i, u in enumerate(candidates):
            email = u["email"]
            name = u.get("name", "")
            prev = u.get(stamp_field)

            # Atomically claim by matching the EXACT prior value (no type-mixed
            # range query). If another worker already claimed it, skip.
            if prev is None and stamp_field not in u:
                match = {stamp_field: {"$exists": False}}
            else:
                match = {stamp_field: prev}
            claim = await db["users"].find_one_and_update(
                {"email": email, **match},
                {"$set": {stamp_field: now}},
                return_document=ReturnDocument.BEFORE,
            )
            if claim is None:
                continue  # lost the race to another worker

            try:
                if i > 0 and delay:
                    await asyncio.sleep(delay)
                slug = email_to_slug(email)
                resume_link = f"{base_url}/resume/{slug}?src=reminder"
                logger.info("Sending automated %s reminder to %s...", stamp_field, email)
                await sender.send(build_msg(email, name, resume_link))
                await db["users"].update_one(
                    {"email": email},
                    {"$inc": {count_field: 1},
                     "$unset": {"last_email_error": "", "email_failed_at": ""}},
                )
                sent += 1
            except Exception as ex:  # roll the claim back so we retry next tick
                logger.error("Failed auto-reminder to %s: %s", email, ex)
                restore = {"$set": {stamp_field: prev}} if prev is not None or stamp_field in u \
                    else {"$unset": {stamp_field: ""}}
                restore.setdefault("$set", {})
                restore["$set"].update({
                    "last_email_error": str(ex),
                    "email_failed_at": now,
                })
                await db["users"].update_one({"email": email}, restore)
                failed += 1
                # If the provider is rate-limiting, stop this pass and let the
                # next scheduled tick pick up where we left off.
                if emailer.is_rate_limit_error(ex):
                    logger.warning("Auto-reminders rate-limited; pausing until next tick.")
                    break

    return {"sent": sent, "failed": failed}


async def process_auto_reminders() -> dict:
    """Run a single auto-reminder pass across baseline- and post-pending
    students. Safe to call directly (used by tests) or on a schedule."""
    from datetime import datetime, timezone, timedelta
    from app.db import get_db, get_all_flags, STATUS_PRE_DONE
    from app import emailer

    flags = await get_all_flags()
    if not flags.get("auto_reminders_enabled", False):
        return {"enabled": False, "pre": {"sent": 0, "failed": 0}, "post": {"sent": 0, "failed": 0}}

    delay_days = int(flags.get("auto_reminder_delay_days", 5) or 5)
    repeat_days = int(flags.get("auto_reminder_repeat_days", 1) or 1)
    post_enabled = bool(flags.get("post_survey_enabled", True))
    batch_delay = max(0.0, float(getattr(settings, "email_batch_delay_seconds", 0.4)))

    db = get_db()
    now = datetime.now(timezone.utc)
    reg_cutoff = now - timedelta(days=delay_days)
    resend_cutoff = now - timedelta(days=repeat_days)

    # Baseline (pre) reminders: registered but never started the survey.
    pre = await _run_daily_reminders(
        db,
        status_values=[None, "not_started"],
        reg_field="created_at",
        stamp_field="pre_reminder_sent_at",
        count_field="pre_reminder_count",
        build_msg=emailer.build_pre_reminder_message,
        reg_cutoff=reg_cutoff,
        resend_cutoff=resend_cutoff,
        now=now,
        delay=batch_delay,
    )

    # Post reminders: completed baseline but not the post-workshop survey.
    post = {"sent": 0, "failed": 0}
    if post_enabled:
        post = await _run_daily_reminders(
            db,
            status_values=[STATUS_PRE_DONE],
            reg_field="pre_submitted_at",
            stamp_field="post_reminder_sent_at",
            count_field="post_reminder_count",
            build_msg=emailer.build_post_reminder_message,
            reg_cutoff=reg_cutoff,
            resend_cutoff=resend_cutoff,
            now=now,
            delay=batch_delay,
        )

    logger.info("Auto-reminder pass complete: pre=%s post=%s", pre, post)
    return {"enabled": True, "pre": pre, "post": post}


async def run_auto_reminder_worker():
    """Background loop: sends the first reminder after the configured delay and
    then re-sends daily until the student completes the survey."""
    import asyncio
    logger.info("Auto-reminder background task starting...")
    while True:
        try:
            await process_auto_reminders()
        except Exception as e:  # never let the loop die
            logger.error("Error in auto-reminder worker loop: %s", e)
        await asyncio.sleep(AUTO_REMINDER_TICK_SECONDS)
