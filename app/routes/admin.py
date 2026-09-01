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
import io
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

# ── Two steps to sign in ─────────────────────────────────────────────────────
#
# The password alone opens nothing. It is the first of two steps: get it right
# and a six-digit code goes to the admin mailbox, and only that code finishes
# the sign-in. Whoever ends up with the password still needs the mailbox.
#
# What carries a half-finished sign-in from the first step to the second is
# this cookie: signed, short-lived and naming only the username and the portal
# the password matched. It is not a session — nothing reads it except the OTP
# step, which checks it before it will look at a code at all.
_PENDING_COOKIE = "admin_login_pending"


def admin_url(suffix: str = "") -> str:
    """A link back to a page that moved behind ADMIN_PATH.

    The routes are still written as /admin/... — a middleware rewrites the
    secret path onto them — so every URL sent to a browser has to be built
    here, or it points at the door that now answers 404.
    """
    return f"{settings.admin_path}{suffix}"

_SURVEY_PORTAL = "survey"
_ORI_PORTAL = "orientation"

PORTAL_NAMES = {
    _SURVEY_PORTAL: "HACRI-E Survey Admin",
    _ORI_PORTAL: "Deeksharambh Orientation Admin",
}


def _portal_for(username: str) -> str | None:
    """Which portal a username belongs to, or None if it is not an admin."""
    if username in (settings.survey_admin_username, settings.admin_username):
        return _SURVEY_PORTAL
    if username == settings.orientation_admin_username:
        return _ORI_PORTAL
    return None


def _password_matches(username: str, password: str) -> bool:
    if username in (settings.survey_admin_username, settings.admin_username):
        return password in (settings.survey_admin_password, settings.admin_password)
    if username == settings.orientation_admin_username:
        return password == settings.orientation_admin_password
    return False


def _otp_email(portal: str) -> str:
    return (settings.orientation_admin_otp_email if portal == _ORI_PORTAL
            else settings.survey_admin_otp_email)


def _issue_pending(response, username: str, portal: str) -> None:
    """Remember that the password step was passed, for as long as the code lasts."""
    from app.deps import _sign
    response.set_cookie(
        _PENDING_COOKIE,
        _sign({"u": username, "p": portal, "exp": time.time() + _OTP_TTL}),
        httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, max_age=_OTP_TTL,
    )


def _read_pending(request: Request) -> dict | None:
    """The half-finished sign-in this browser is carrying, if it is still good."""
    from app.deps import _unsign

    token = request.cookies.get(_PENDING_COOKIE)
    if not token:
        return None
    data = _unsign(token)
    if not data or not data.get("u") or float(data.get("exp", 0)) < time.time():
        return None
    return data


def _login_page(request: Request, *, status_code: int = 200, **context):
    base = {"title": "Admin Login", "otp_sent": False, "error": None,
            "admin_path": settings.admin_path}
    base.update(context)
    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html", base, status_code=status_code)


def _mask_email(email: str) -> str:
    """sa***h@jainuniversity.ac.in — enough to recognise your own mailbox."""
    parts = email.split("@")
    if len(parts) != 2:
        return "registered admin email"
    userpart, domain = parts
    masked = userpart[:2] + "***" + userpart[-1] if len(userpart) > 3 else "***"
    return f"{masked}@{domain}"


async def _send_admin_otp(request: Request, username: str, portal: str):
    """Issue a code and mail it. Returns the rendered next page."""
    from app import db as _db, emailer

    portal_name = PORTAL_NAMES[portal]
    email = _otp_email(portal)
    ip, agent, country = client_ip(request), client_agent(request), client_country(request)

    otp = str(secrets.randbelow(900000) + 100000)  # 100000–999999
    from app.db import save_admin_otp
    await save_admin_otp(username, otp, time.time() + _OTP_TTL)

    # Mail off is a normal state in development, where the code goes to the log
    # and the flow carries on. What it must not do is claim the OTP was emailed:
    # in production that leaves an admin waiting for a message nobody sent.
    mail_off = emailer._is_dry_run()
    if mail_off:
        log.warning("OTP [%s] for %s NOT emailed — mail is off (%s).", otp, username,
                    "EMAIL_DRY_RUN is true" if settings.smtp_host
                    else "no SMTP_HOST configured")
        await _db.record_login_event(username=username, outcome=_db.LOGIN_MAIL_OFF,
                                     ip=ip, agent=agent, country=country,
                                     portal=portal_name, note="mail is switched off")

    try:
        body = (
            f"Your {portal_name} OTP is: {otp}\n\n"
            f"This OTP is valid for 10 minutes.\n\n"
            f"If you did not request this, please ignore this email."
        )
        await emailer.send_simple_email(email, portal_name,
                                        f"{portal_name} Login OTP", body)
        log.info("OTP [%s] sent to %s for %s", otp, email, username)
        await _db.record_login_event(username=username, outcome=_db.LOGIN_OTP_SENT,
                                     ip=ip, agent=agent, country=country,
                                     portal=portal_name,
                                     note="password accepted, code emailed")
    except Exception as exc:
        log.exception("Failed to send OTP email: %s", exc)
        hosts = ", ".join(a["hostname"] for a in emailer.smtp_accounts())
        return _login_page(
            request, status_code=500,
            error=f"Could not send the OTP. Tried: {hosts}. Last error: {exc}"
                  + ("" if len(emailer.smtp_accounts()) > 1 else
                     " Configuring SMTP_FALLBACK_HOST would give this a second "
                     "mailbox to try."))

    response = _login_page(
        request, otp_sent=True, otp_username=username,
        otp_email_hint=_mask_email(email), mail_off=mail_off)
    _issue_pending(response, username, portal)
    return response


# ── Resending the code ────────────────────────────────────────────────────────
@router.post("/admin/survey/request-otp")
async def survey_request_otp(request: Request, username: str = Form(default="")):
    """Send the code again — only to a browser that already passed the password.

    A code that could be requested with a username alone would be a login of
    its own, and the point of the second step is that it is a *second* step.
    """
    from app import db as _db

    ip, agent, country = client_ip(request), client_agent(request), client_country(request)

    if await _db.is_locked_out(ip):
        await _db.record_login_event(username=username.strip(), outcome=_db.LOGIN_LOCKED,
                                     ip=ip, agent=agent, country=country,
                                     note="blocked at the OTP request")
        return _login_page(request, status_code=429, error=_blocked_message(await _block_note(ip)))

    pending = _read_pending(request)
    if not pending:
        return _login_page(
            request, status_code=401,
            error="Your sign-in timed out. Please enter your password again.")

    return await _send_admin_otp(request, pending["u"], pending["p"])


async def _block_note(ip: str) -> dict | None:
    from app import db as _db
    return await _db.get_ip_block(ip)


def _blocked_message(block: dict | None) -> str:
    """What a turned-away address is told. Never why it was blocked by hand."""
    from app import db as _db
    if block:
        return ("This address has been blocked by an administrator. "
                "Contact the Office of Academics if you believe this is a mistake.")
    return (f"Too many failed attempts from this address. Try again in "
            f"{_db.LOGIN_LOCK_MINUTES} minutes.")


@router.get("/admin/login", response_class=HTMLResponse)
async def general_admin_login_get(request: Request):
    if _is_survey_admin(request):
        return RedirectResponse(url=admin_url("/survey"), status_code=303)
    if _is_ori_admin(request):
        return RedirectResponse(url=admin_url("/orientation"), status_code=303)
    return request.app.state.templates.TemplateResponse(
        request, "admin_login.html",
        {"error": None, "title": "Admin Login", "otp_sent": False},
    )


def client_ip(request: Request) -> str:
    """The address the request really came from.

    Behind nginx every request appears to come from 127.0.0.1, so the proxy's
    own headers are the only place the client's address survives.
    X-Forwarded-For is a chain and the client is its first entry; the rest are
    proxies. Anyone can forge the header, but they cannot forge it *past* our
    nginx, which overwrites what it sets — so the first hop is trustworthy for
    our own traffic and this is only ever used for rate limiting and for a log
    a human reads, never for authorisation.
    """
    chain = request.headers.get("x-forwarded-for", "")
    if chain:
        return chain.split(",")[0].strip()[:64]
    return (request.headers.get("x-real-ip")
            or (request.client.host if request.client else "")).strip()[:64]


def client_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:400]


def client_country(request: Request) -> str:
    """A country, only if something in front of us resolved one.

    Nothing here guesses at a location from an address: that needs a GeoIP
    database this app does not ship. If a CDN is ever put in front, its header
    lands in the log automatically.
    """
    for header in ("cf-ipcountry", "x-country-code", "x-geo-country"):
        value = request.headers.get(header, "").strip()
        if value and value.upper() not in ("XX", "T1"):
            return value.upper()[:8]
    return ""


def _open_portal(portal: str):
    """The response that actually signs someone in."""
    if portal == _ORI_PORTAL:
        response = RedirectResponse(url=admin_url("/orientation"), status_code=303)
        _set_cookie(response, _ORI_COOKIE, settings.cookie_secure, settings.cookie_samesite)
    else:
        response = RedirectResponse(url=admin_url("/survey"), status_code=303)
        _set_cookie(response, _SURVEY_COOKIE, settings.cookie_secure, settings.cookie_samesite)
    response.delete_cookie(_PENDING_COOKIE)
    return response


@router.post("/admin/login")
async def general_admin_login_post(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(...),   # the password on step one, the code on step two
    stage: str = Form(default="password"),
):
    """Sign in, in two steps: the password, then the code it triggers.

    Which step this is comes from the pending cookie, not from the form: a
    browser that has not passed the password has nothing for the code step to
    check against, so a code on its own can never be a login.
    """
    from app import db as _db

    username = username.strip()
    submitted = password.strip()
    ip, agent, country = client_ip(request), client_agent(request), client_country(request)

    async def note(outcome: str, portal: str = "", detail: str = ""):
        await _db.record_login_event(username=username, outcome=outcome, ip=ip,
                                     agent=agent, portal=portal, country=country,
                                     note=detail)

    # Turn an address away once it has failed too often in a short window, or
    # because an admin blocked it by hand. Checked before the credentials are
    # looked at, so a guesser learns nothing from how long the answer takes.
    if await _db.is_locked_out(ip):
        block = await _block_note(ip)
        await note(_db.LOGIN_LOCKED,
                   detail="blocked by an administrator" if block
                          else f"blocked after {_db.LOGIN_FAIL_LIMIT} failures")
        log.warning("Admin login blocked: %s (%s)", ip,
                    "blocked by hand" if block else
                    f"{_db.LOGIN_FAIL_LIMIT} failures in {_db.LOGIN_FAIL_WINDOW_MINUTES} min")
        return _login_page(request, status_code=429, error=_blocked_message(block))

    # ── Step two: the code ───────────────────────────────────────────────────
    #
    # Only the code form posts stage=otp. Someone who goes back and types their
    # password again starts a fresh sign-in instead of having it read as a
    # wrong code.
    pending = _read_pending(request) if stage == "otp" else None
    if pending:
        username = username or pending["u"]
        if username != pending["u"]:
            return _login_page(
                request, status_code=401,
                error="That sign-in was started for a different username. "
                      "Please start again.")

        from app.db import verify_admin_otp
        if await verify_admin_otp(pending["u"], submitted):
            await note(_db.LOGIN_OK, portal=PORTAL_NAMES[pending["p"]],
                       detail="password and emailed code")
            return _open_portal(pending["p"])

        await note(_db.LOGIN_BAD, portal=PORTAL_NAMES[pending["p"]], detail="wrong code")
        log.warning("Wrong admin OTP for %r from %s", pending["u"], ip or "an unknown address")
        return _login_page(
            request, status_code=401, otp_sent=True, otp_username=pending["u"],
            otp_email_hint=_mask_email(_otp_email(pending["p"])),
            error="That code is not right, or it has expired. "
                  "Check the latest email, or send a new code.")

    if stage == "otp":
        # The code step with nothing behind it: the pending cookie ran out, or
        # the code was posted straight at the endpoint.
        await note(_db.LOGIN_BAD, detail="code submitted with no password step")
        return _login_page(
            request, status_code=401,
            error="Your sign-in timed out. Please enter your password again.")

    # ── Step one: the password ───────────────────────────────────────────────
    portal = _portal_for(username)
    if portal and _password_matches(username, submitted):
        if not settings.admin_require_otp:
            # The escape hatch for a server whose mail is down. Off by default,
            # and the log says plainly that the code was skipped.
            await note(_db.LOGIN_OK, portal=PORTAL_NAMES[portal],
                       detail="password only — ADMIN_REQUIRE_OTP is off")
            log.warning("Admin signed in without an OTP: ADMIN_REQUIRE_OTP is false")
            return _open_portal(portal)
        return await _send_admin_otp(request, username, portal)

    # The message is the same either way: telling the difference between "no
    # such user" and "wrong password" hands a guesser half the answer.
    await note(_db.LOGIN_BAD if portal else _db.LOGIN_UNKNOWN)
    log.warning("Failed admin login for %r from %s", username, ip or "an unknown address")
    return _login_page(request, status_code=401, otp_username=username,
                       error="Invalid username or password.")


@router.get("/admin")
async def general_admin(request: Request):
    if _is_survey_admin(request):
        return RedirectResponse(url=admin_url("/survey"), status_code=303)
    if _is_ori_admin(request):
        return RedirectResponse(url=admin_url("/orientation"), status_code=303)
    return RedirectResponse(url=admin_url("/login"), status_code=303)


# Redirect legacy login routes
@router.get("/admin/survey/login")
@router.post("/admin/survey/login")
async def old_survey_login_redirect():
    return RedirectResponse(url=admin_url("/login"), status_code=303)


@router.get("/admin/orientation/login")
@router.post("/admin/orientation/login")
async def old_ori_login_redirect():
    return RedirectResponse(url=admin_url("/login"), status_code=303)


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
    r = RedirectResponse(url=admin_url("/login"), status_code=303)
    _del_cookie(r, _SURVEY_COOKIE)
    return r

@router.get("/admin/survey", response_class=HTMLResponse)
async def survey_dashboard(request: Request):
    if not _is_survey_admin(request):
        return RedirectResponse(url=admin_url("/login"), status_code=303)
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
    r = RedirectResponse(url=admin_url("/login"), status_code=303)
    _del_cookie(r, _ORI_COOKIE)
    return r

@router.get("/admin/orientation", response_class=HTMLResponse)
async def ori_dashboard(request: Request):
    if not _is_ori_admin(request):
        return RedirectResponse(url=admin_url("/login"), status_code=303)
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


@router.get("/admin/api/survey/search")
async def api_survey_search(
    request: Request,
    q: str = Query(default=""),
    limit: int = Query(default=10),
):
    """Find students by name, email or department, for the admin search bar.

    Deliberately unfiltered by the dashboard's department/level selectors — the
    point of the search bar is to reach any student from anywhere.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    q = (q or "").strip().lower()
    if len(q) < 2:
        return JSONResponse({"query": q, "results": [], "total": 0})

    db = get_db()
    matches = []
    async for u in db["users"].find({}):
        haystacks = (u.get("name", ""), u.get("email", ""), u.get("program", ""))
        if any(q in (h or "").lower() for h in haystacks):
            matches.append(u)

    # Whoever matches on email first is almost always who the admin meant.
    def rank(u: dict) -> tuple:
        email = (u.get("email") or "").lower()
        name = (u.get("name") or "").lower()
        return (
            0 if email == q else 1 if email.startswith(q) else 2 if name.startswith(q) else 3,
            name,
        )

    matches.sort(key=rank)
    results = [{
        "email": u.get("email", ""),
        "name": u.get("name", ""),
        "program": u.get("program", ""),
        "ug_or_pg": u.get("ug_or_pg", "ug"),
        "status": u.get("status") or "not_started",
    } for u in matches[:max(1, min(limit, 50))]]

    return JSONResponse({"query": q, "results": results, "total": len(matches)})


def _answer_sections(fields: dict, *, kind: str) -> list[dict]:
    """Group one survey's answers into readable sections.

    Non-Likert questions carry their real wording (it lives in app/sections.py);
    Likert items are listed by their code, which is how the instrument and the
    exports refer to them anyway.
    """
    from app.hacri_e2_compat import SCHEMA
    from app.sections import (
        POST_REFLECTION, POST_USAGE, PRE_BACKGROUND, PRE_FUTURE, PRE_USAGE,
        SECTION_TITLES,
    )

    def fmt(value):
        if value is None or value == "":
            return "—"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) or "—"
        return str(value)

    def rows(spec):
        return [{"key": key, "label": label, "value": fmt(fields.get(key))}
                for key, label, *_ in spec]

    sections: list[dict] = []
    if kind == "pre":
        sections.append({"title": f"A — {SECTION_TITLES['A']}", "rows": rows(PRE_BACKGROUND)})
    else:
        sections.append({"title": "A — Family Background", "rows": [
            {"key": key, "label": label, "value": fmt(fields.get(key))}
            for key, label in [
                ("father_name", "Father's name"),
                ("father_occupation", "Father's occupation"),
                ("organization_name", "Father's organisation"),
                ("business_name", "Father's business"),
                ("business_type", "Father's business type"),
                ("mother_name", "Mother's name"),
                ("mother_occupation", "Mother's occupation"),
                ("mother_organization_name", "Mother's organisation"),
                ("mother_business_name", "Mother's business"),
                ("mother_business_type", "Mother's business type"),
                ("location", "Campus"),
            ]
        ]})

    # Likert blocks, in instrument order.
    for letter in ("B", "D", "E", "F", "G"):
        keys = [k for k in SCHEMA if k.startswith(letter)]
        if not keys:
            continue
        extra = []
        if kind == "pre" and letter == "B":
            extra = [("B11", "Anything else about AI awareness")]
        if kind == "pre" and letter == "E":
            extra = [("E11", "Scenario answer"), ("E11_reason", "Reason")]
        sections.append({
            "title": f"{letter} — {SECTION_TITLES.get(letter, letter)}",
            "rows": [{"key": k, "label": k, "value": fmt(fields.get(k))} for k in keys]
                    + [{"key": k, "label": lbl, "value": fmt(fields.get(k))} for k, lbl in extra],
        })

    if kind == "pre":
        sections.append({"title": f"C — {SECTION_TITLES['C']}", "rows": rows(PRE_USAGE)})
        sections.append({"title": f"H — {SECTION_TITLES['H']}", "rows": rows(PRE_FUTURE)})
    else:
        sections.append({"title": f"C — {SECTION_TITLES['C_POST']}", "rows": rows(POST_USAGE)})
        post_rows = rows(POST_REFLECTION)
        post_rows.append({"key": "praise_initiative", "label": "PRaiSE pillar chosen",
                          "value": fmt(fields.get("praise_initiative"))})
        sections.append({"title": f"H — {SECTION_TITLES['H_POST']}", "rows": post_rows})

    return [s for s in sections if any(r["value"] != "—" for r in s["rows"])]


@router.get("/admin/api/survey/student/{email}")
async def api_student_detail(request: Request, email: str):
    """Everything held about one student, for the admin search results panel."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.db import _fmt
    from app.routes.landing import email_to_slug
    from app.scoring import delta, score_for_user

    db = get_db()
    email = (email or "").strip().lower()
    user = await db["users"].find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")

    pre_doc = await db["pre_responses"].find_one({"email": email}, sort=[("submitted_at", -1)])
    post_doc = await db["post_responses"].find_one({"email": email}, sort=[("submitted_at", -1)])
    ori_doc = await db["orientation_responses"].find_one({"email": email}, sort=[("submitted_at", -1)])

    pre_fields = (pre_doc or {}).get("fields", {})
    post_fields = (post_doc or {}).get("fields", {})

    scores = {"pre": score_for_user(pre_fields) if pre_doc else None,
              "post": score_for_user(post_fields) if post_doc else None,
              "delta_lit": None, "delta_read": None, "movement": None}
    if pre_doc and post_doc:
        d = delta(pre_fields, post_fields)
        scores.update({"delta_lit": d["delta_lit"], "delta_read": d["delta_read"],
                       "movement": d["movement"]})

    return JSONResponse({
        "email": email,
        "email_slug": email_to_slug(email),
        "name": user.get("name", ""),
        "program": user.get("program", "") or "—",
        "ug_or_pg": user.get("ug_or_pg", "ug"),
        "education_type": user.get("education_type", ""),
        "location": user.get("location", ""),
        "status": user.get("status") or "not_started",
        "created_at": _fmt(user.get("created_at")),
        # Fall back to the response document for records imported before the
        # timestamp was mirrored onto the user.
        "pre_at": _fmt(user.get("pre_submitted_at") or (pre_doc or {}).get("submitted_at")),
        "post_at": _fmt(user.get("post_submitted_at") or (post_doc or {}).get("submitted_at")),
        "orientation_at": _fmt((ori_doc or {}).get("submitted_at")),
        "email_activity": {
            "pre_reminder_at": _fmt(user.get("pre_reminder_sent_at")),
            "post_reminder_at": _fmt(user.get("post_reminder_sent_at")),
            "pre_reminder_count": int(user.get("pre_reminder_count", 0) or 0),
            "post_reminder_count": int(user.get("post_reminder_count", 0) or 0),
            "clicked_at": _fmt(user.get("reminder_clicked_at")),
            "post_link_at": _fmt(user.get("post_link_at")),
            "last_error": user.get("last_email_error", ""),
        },
        "has_pre_draft": bool(user.get("pre_draft")),
        "has_post_draft": bool(user.get("post_draft")),
        "scores": scores,
        "pre_sections": _answer_sections(pre_fields, kind="pre") if pre_doc else [],
        "post_sections": _answer_sections(post_fields, kind="post") if post_doc else [],
        "orientation": (ori_doc or {}).get("data", {}),
    })


@router.get("/admin/api/survey/dept-analysis")
async def api_survey_dept_analysis(request: Request):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import get_dept_analysis_data
    return JSONResponse(await get_dept_analysis_data())


@router.get("/admin/api/survey/school-analysis")
async def api_survey_school_analysis(request: Request):
    """Every school: its departments folded up, plus what came in this week."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import get_school_analysis_data
    return JSONResponse(await get_school_analysis_data())


@router.get("/admin/survey/export-schools")
async def admin_export_schools(request: Request):
    """The school workbook: all schools, every department, then a tab each."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.db import get_school_analysis_data
    from app.school_export import generate_schools_excel
    from app.routes.shared_analysis import _in_thread

    data = await get_school_analysis_data()
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    book = await _in_thread(generate_schools_excel, data, generated_at=generated_at)

    filename = f"HACRI-E_All_Schools_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        io.BytesIO(book),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/api/survey/date-analysis")
async def api_survey_date_analysis(request: Request):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import get_date_analysis_data
    return JSONResponse(await get_date_analysis_data())



@router.get("/admin/api/survey/post-links")
async def api_survey_post_links(request: Request):
    """Department-wise survey links + how many students each one serves.

    Every department gets two links: Outcome Survey 1 (baseline registration
    with the department locked) and the Impact post survey.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.db import (
        FLAG_POST_DELAY, get_department_summary, get_setting_int,
        list_dept_post_delays,
    )
    from app.departments import DEPARTMENTS
    from app.routes.post_link import ALL_SLUG, dept_post_url, dept_pre_url, dept_slug

    base_url = str(request.base_url).rstrip("/")
    summary = {row["dept"]: row for row in await get_department_summary()}
    own_delays = await list_dept_post_delays()
    portal_delay = await get_setting_int(FLAG_POST_DELAY, default=0)

    # Every official department gets links, even before anyone registers under
    # it — that is exactly when an admin needs the baseline link to hand out.
    empty = {"registered": 0, "pre_done": 0, "post_done": 0, "pending_pre": 0, "pending_post": 0}
    names = sorted(set(DEPARTMENTS) | set(summary), key=str.lower)

    totals = {"registered": 0, "pre_done": 0, "post_done": 0, "pending_post": 0}
    links = []
    for dept in names:
        row = summary.get(dept, empty)
        for key in totals:
            totals[key] += row[key]
        links.append({
            "dept": dept,
            "slug": dept_slug(dept),
            "pre_url": dept_pre_url(base_url, dept),
            "url": dept_post_url(base_url, dept),      # kept: the post link
            "post_url": dept_post_url(base_url, dept),
            "registered": row["registered"],
            "pre_done": row["pre_done"],
            "post_done": row["post_done"],
            "pending_post": row["pending_post"],
            # How long after their baseline this department's students wait.
            # None means it follows the portal-wide setting.
            "post_delay_days": own_delays.get(dept),
            "effective_delay_days": own_delays.get(dept, portal_delay),
        })

    from app.routes.shared_analysis import directory_url

    return JSONResponse({
        "base_url": base_url,
        "all_url": f"{base_url}/post/{ALL_SLUG}",
        "pre_all_url": f"{base_url}/",
        # One shareable page covering every department at once.
        "directory_url": directory_url(base_url),
        "portal_delay_days": portal_delay,
        "totals": totals,
        "links": links,
    })


@router.post("/admin/api/survey/post-delay")
async def api_set_post_delay(request: Request):
    """Set how many days after their baseline a department's post survey opens.

    Sending null clears it, so that department follows the portal-wide setting
    again.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")

    dept = (body.get("dept") or "").strip()
    if not dept:
        raise HTTPException(status_code=400, detail="Which department?")

    raw = body.get("days")
    if raw is None or raw == "":
        days = None
    else:
        try:
            days = max(0, min(365, int(raw)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Days must be a number")

    from app.db import FLAG_POST_DELAY, get_setting_int, set_dept_post_delay
    await set_dept_post_delay(dept, days)
    portal_delay = await get_setting_int(FLAG_POST_DELAY, default=0)
    return JSONResponse({
        "ok": True, "dept": dept, "post_delay_days": days,
        "effective_delay_days": portal_delay if days is None else days,
    })


@router.get("/admin/api/survey/dept-stats")
async def api_survey_dept_stats(request: Request):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import get_dept_analysis_data
    data = await get_dept_analysis_data()
    return JSONResponse(data["departments"])



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

    if type_name == "pre-pending":
        stamp_field = "pre_reminder_sent_at"
        count_field = "pre_reminder_count"
        build_msg = emailer.build_pre_reminder_message
    else:
        stamp_field = "post_reminder_sent_at"
        count_field = "post_reminder_count"
        build_msg = emailer.build_post_reminder_message

    sent = 0
    failed = 0
    try:
        async with emailer.SmtpBatchSender() as sender:
            for i, u in enumerate(pending_users):
                if i > 0 and delay:
                    await asyncio.sleep(delay)

                email = u.get("email")
                name = u.get("name", "")
                if not email:
                    continue

                try:
                    slug = email_to_slug(email)
                    resume_link = f"{base_url}/resume/{slug}?src=reminder"
                    await sender.send(build_msg(email, name, resume_link))
                    await db["users"].update_one(
                        {"email": email},
                        {"$set": {stamp_field: datetime.now(timezone.utc)},
                         "$inc": {count_field: 1},
                         "$unset": {"last_email_error": "", "email_failed_at": ""}}
                    )
                    sent += 1
                except Exception as e:
                    failed += 1
                    log.warning("Bulk email failed for %s: %s", email, e)
                    await db["users"].update_one(
                        {"email": email},
                        {"$set": {"last_email_error": str(e),
                                  "email_failed_at": datetime.now(timezone.utc)}}
                    )

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


# ══════════════════════════════════════════════════════════════════════════════
# ORIENTATION REPORT (survey admin) — campus report, who filled, and mailing
# ══════════════════════════════════════════════════════════════════════════════
ORI_FILLED = "filled"
ORI_PENDING = "pending"


@router.get("/admin/api/orientation/campuses")
async def api_orientation_campuses(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """The landing page of the orientation report: one card per campus."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_data import (
        ALL_CAMPUSES, campus_card, campus_cards, orientation_dataset,
    )

    data = await orientation_dataset(dept=dept, ug_or_pg=ug_or_pg)
    filled, pending = data["filled"], data["pending"]

    return JSONResponse({
        "campuses": campus_cards(filled, pending),
        "all": campus_card(ALL_CAMPUSES, filled, pending),
    })


@router.get("/admin/api/orientation/report")
async def api_orientation_report(
    request: Request,
    campus: str = Query(default=""),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Question-by-question analysis of the orientation replies for one campus."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_data import build_report, orientation_dataset

    data = await orientation_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    return JSONResponse(build_report(data["filled"], data["pending"], campus))


@router.get("/admin/api/orientation/students")
async def api_orientation_students(
    request: Request,
    campus: str = Query(default=""),
    group: str = Query(default=ORI_FILLED),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Who filled the orientation form (or who still owes it), for one campus."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_analysis import QUESTIONS
    from app.orientation_data import orientation_dataset

    data = await orientation_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    group = ORI_PENDING if group == ORI_PENDING else ORI_FILLED
    rows = data[group]

    students = []
    for row in rows:
        answers = row.get("data", {}) or {}
        students.append({
            **{k: v for k, v in row.items() if k != "data"},
            "answered": sum(
                1 for key in QUESTIONS
                if answers.get(key) not in (None, "", [], {})
            ),
            "vibe": answers.get("q2"),
            "nps": answers.get("q34"),
            "belonging": answers.get("q29"),
            "avatar": answers.get("q41", ""),
        })

    return JSONResponse({
        "campus": campus or "All campuses",
        "group": group,
        "total": len(students),
        "students": students,
        "filled": len(data["filled"]),
        "pending": len(data["pending"]),
    })


@router.get("/admin/api/orientation/departments")
async def api_orientation_departments(
    request: Request,
    campus: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Department-by-department orientation analysis for one campus.

    Deliberately ignores the dashboard's department filter — this view exists
    to compare departments against each other and against the campus average.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_data import department_overview, orientation_dataset

    data = await orientation_dataset(campus=campus, ug_or_pg=ug_or_pg)
    return JSONResponse(department_overview(data["filled"], data["pending"], campus))


# ══════════════════════════════════════════════════════════════════════════════
# COHORT REPORT (survey admin) — outcome, impact and the journey between them
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/admin/api/cohort")
async def api_cohort(
    request: Request,
    campus: str = Query(default=""),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Outcome, impact and the journey, for one campus / department / level."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.cohort_analysis import cohort_report

    return JSONResponse(await cohort_report(campus=campus, dept=dept, ug_or_pg=ug_or_pg))


@router.get("/admin/survey/cohort-ppt")
async def admin_cohort_ppt(
    request: Request,
    campus: str = Query(default=""),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Download the outcome and impact report as a slide deck."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.cohort_analysis import cohort_deck_response

    return await cohort_deck_response(campus=campus, dept=dept, ug_or_pg=ug_or_pg)


@router.get("/admin/api/cohort/share-links")
async def api_cohort_share_links(request: Request):
    """Copyable links that open the outcome and impact report without a login."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.cohort_analysis import ALL_CAMPUSES
    from app.orientation_analysis import CAMPUSES
    from app.routes.shared_analysis import cohort_share_url

    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "links": [
            {"campus": ALL_CAMPUSES, "url": cohort_share_url(base, "")},
            *({"campus": name, "url": cohort_share_url(base, name)} for name in CAMPUSES),
        ]
    })


@router.get("/admin/api/security/logins")
async def api_login_events(request: Request, limit: int = Query(default=150)):
    """Who has signed in, who has tried, and from where.

    The admin portal opens onto every student's contact details and every
    department's figures. Until this existed nothing recorded who had opened
    it, so a stolen password left no trace at all.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app import db as _db

    return JSONResponse({
        "events": await _db.list_login_events(limit=max(10, min(limit, 500))),
        "summary": await _db.login_summary(),
        "policy": {
            "limit": _db.LOGIN_FAIL_LIMIT,
            "window_minutes": _db.LOGIN_FAIL_WINDOW_MINUTES,
            "lock_minutes": _db.LOGIN_LOCK_MINUTES,
        },
        "you": {"ip": client_ip(request), "country": client_country(request)},
    })


@router.post("/admin/api/security/block")
async def api_block_address(request: Request):
    """Shut one address out of the admin login, or let it back in.

    The automatic lock-out lasts fifteen minutes, which is right for someone
    fumbling their own password and useless against a scanner that comes back
    all day. This is the admin saying: that one, not any more.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app import db as _db

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")

    ip = (body.get("ip") or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="Which address?")

    action = (body.get("action") or "block").strip().lower()
    if action == "unblock":
        lifted = await _db.unblock_ip(ip)
        log.info("Admin lifted the block on %s (had one: %s)", ip, lifted)
        return JSONResponse({"ok": True, "ip": ip, "blocked": False,
                             "lifted": lifted, "blocks": await _db.list_ip_blocks()})

    # Blocking the address you are sitting on locks you out of your own next
    # sign-in, and the message you would get then says nothing about why.
    if ip == client_ip(request):
        raise HTTPException(
            status_code=400,
            detail="That is the address you are on — blocking it would lock you out.")

    hours_raw = body.get("hours")
    try:
        hours = float(hours_raw) if hours_raw not in (None, "", "forever") else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="How long, in hours?")
    if hours is not None and hours <= 0:
        hours = None

    await _db.block_ip(ip, by=client_ip(request),
                       reason=(body.get("reason") or "").strip(), hours=hours)
    log.warning("Admin blocked %s from the login%s", ip,
                f" for {hours} hours" if hours else " until it is lifted")
    return JSONResponse({"ok": True, "ip": ip, "blocked": True,
                         "blocks": await _db.list_ip_blocks()})


@router.get("/admin/api/share-links")
async def api_all_share_links(request: Request):
    """Every shareable link in the app, in one call.

    They were spread over five endpoints and three separate pages, so nobody
    could see the whole set at once and it was easy to hand out the wrong one —
    a campus report where a department report was meant, or a login-free
    analysis link where a student form was meant. One list, grouped by who the
    link is for, with what each one opens said in words.

    Each entry carries `downloads` where the same token also fetches a file, so
    the deck and the workbook are offered next to the link rather than only
    from inside the page it opens.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_analysis import CAMPUSES
    from app.orientation_data import (
        ALL_CAMPUSES, department_rows, orientation_dataset,
    )
    from app.routes.post_link import dept_post_url, dept_pre_url
    from app.routes.shared_analysis import (
        cohort_share_url, directory_url, orientation_share_url,
        schools_directory_url, vibe_share_url,
    )

    base = str(request.base_url).rstrip("/")
    public = (settings.public_base_url or base).rstrip("/")

    def orientation(campus: str = "", dept: str = "") -> dict:
        return {
            "url": orientation_share_url(base, campus, dept),
            "downloads": [
                {"label": "Deck", "url": orientation_share_url(
                    base, campus, dept, "/shared/orientation/ppt")},
                {"label": "Excel", "url": orientation_share_url(
                    base, campus, dept, "/shared/orientation/excel")},
            ],
        }

    groups = [{
        "key": "students",
        "title": "For students",
        "note": "Hand these to students. They ask for an email and open a form — "
                "no report, no figures.",
        "links": [
            {"label": "Deeksharambh orientation form",
             "sub": "The orientation feedback form. Closes when the form is switched off.",
             "url": f"{public}/deeksharambh"},
            {"label": "Baseline survey — registration",
             "sub": "The normal sign-up page; the student picks their own department.",
             "url": dept_pre_url(public, None)},
            {"label": "Post survey — by email",
             "sub": "Asks only for the address they registered with.",
             "url": dept_post_url(public, None)},
        ],
    }, {
        "key": "directory",
        "title": "For the office",
        "note": "Every department on one page, with its own exports. Opens without a login.",
        "links": [
            {"label": "School directory",
             "sub": "Every school, the departments folded into it, and which are "
                    "filling now — with a link through to each school's own report.",
             "url": schools_directory_url(base)},
            {"label": "Department directory",
             "sub": "Counts, reminder-mail outcomes and average scores for every department.",
             "url": directory_url(base)},
        ],
    }]

    # Deeksharambh — the whole cohort, each campus, then each department.
    ori_links = [{"label": ALL_CAMPUSES,
                  "sub": "Every department, every campus.", **orientation()}]
    for name in CAMPUSES:
        ori_links.append({"label": name, "sub": f"Everything answered at {name}.",
                          **orientation(name)})

    data = await orientation_dataset()
    for row in department_rows(data["filled"], data["pending"]):
        if not row["dept"] or row["dept"] == "—":
            continue
        ori_links.append({
            "label": row["dept"],
            "sub": f"{row['filled']} of {row['eligible']} answered "
                   f"({row['pct']:.0f}%) — this department only.",
            "count": row["filled"],
            **orientation("", row["dept"]),
        })

    groups.append({
        "key": "orientation",
        "title": "Deeksharambh report",
        "note": "Opens the orientation report without a login. A department link "
                "opens that department alone and cannot be edited into another's.",
        "links": ori_links,
    })

    groups.append({
        "key": "impact",
        "title": "Student impact page",
        "note": "The public-facing page written for students and parents.",
        "links": [{"label": "All campuses", "sub": "Every campus together.",
                   "url": vibe_share_url(base, "")}]
                 + [{"label": n, "sub": f"{n} only.", "url": vibe_share_url(base, n)}
                    for n in CAMPUSES],
    })

    groups.append({
        "key": "cohort",
        "title": "Outcome and impact report",
        "note": "Baseline against post survey, for the students who did both.",
        "links": [{"label": ALL_CAMPUSES, "sub": "Every campus together.",
                   "url": cohort_share_url(base, "")}]
                 + [{"label": n, "sub": f"{n} only.", "url": cohort_share_url(base, n)}
                    for n in CAMPUSES],
    })

    return JSONResponse({"groups": groups,
                         "total": sum(len(g["links"]) for g in groups)})


@router.get("/admin/api/orientation/share-links")
async def api_orientation_share_links(request: Request):
    """Copyable links that open the orientation report without a login.

    One per campus plus one for everything — each carries a token that only
    unlocks that campus, so a Kochi link cannot be edited into a Bangalore one.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_analysis import CAMPUSES
    from app.orientation_data import ALL_CAMPUSES
    from app.routes.shared_analysis import orientation_share_url

    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "links": [
            {"campus": ALL_CAMPUSES, "url": orientation_share_url(base, "")},
            *({"campus": name, "url": orientation_share_url(base, name)} for name in CAMPUSES),
        ]
    })


@router.get("/admin/api/orientation/dept-share-links")
async def api_orientation_dept_share_links(
    request: Request,
    campus: str = Query(default=""),
):
    """One copyable link per department, for the campus that is open.

    Each carries a token minted for that department alone, so a head of
    department can be handed their own Deeksharambh report without it opening
    anybody else's. Counts and vibe ride along so the list says which links are
    worth sending — a department with two replies is not a report yet.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_data import (
        ALL_CAMPUSES, department_rows, orientation_dataset,
    )
    from app.routes.shared_analysis import orientation_share_url

    base = str(request.base_url).rstrip("/")
    # Campus-wide on purpose: the link carries no level filter, so counting
    # only UG here would promise a figure the link itself would not show.
    data = await orientation_dataset(campus=campus)
    rows = department_rows(data["filled"], data["pending"])

    return JSONResponse({
        "campus": campus or ALL_CAMPUSES,
        "links": [
            {
                "dept": row["dept"],
                "filled": row["filled"],
                "pending": row["pending"],
                "eligible": row["eligible"],
                "pct": row["pct"],
                "vibe": row["vibe"],
                "nps": row["nps"],
                "belonging": row["belonging"],
                "url": orientation_share_url(base, campus, row["dept"]),
            }
            for row in rows if row["dept"] and row["dept"] != "—"
        ],
    })


@router.get("/admin/survey/orientation-ppt")
async def admin_orientation_ppt(
    request: Request,
    campus: str = Query(default=""),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Download the orientation report as a slide deck."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_data import deck_response

    return await deck_response(campus=campus, dept=dept, ug_or_pg=ug_or_pg)


@router.get("/admin/survey/orientation-count-ppt")
async def admin_orientation_count_ppt(request: Request, campus: str = Query(default="")):
    """Just the department headcount, as a slide deck — no scores, no charts."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from datetime import datetime
    from fastapi.responses import StreamingResponse
    import io

    from app.orientation_data import department_count_summary
    from app.orientation_count_export import build_department_count_pptx
    from app.routes.shared_analysis import _in_thread

    data = await department_count_summary(campus=campus)
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    ppt_bytes = await _in_thread(
        build_department_count_pptx, data, generated_at=generated_at)

    filename = f"Deeksharambh_2026_Department_Count_{campus or 'All'}.pptx"
    filename = "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)
    return StreamingResponse(
        io.BytesIO(ppt_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/survey/orientation-count-docx")
async def admin_orientation_count_docx(request: Request, campus: str = Query(default="")):
    """The same headcount, as a Word document."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from datetime import datetime
    from fastapi.responses import StreamingResponse
    import io

    from app.orientation_data import department_count_summary
    from app.orientation_count_export import build_department_count_docx
    from app.routes.shared_analysis import _in_thread

    data = await department_count_summary(campus=campus)
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    docx_bytes = await _in_thread(
        build_department_count_docx, data, generated_at=generated_at)

    filename = f"Deeksharambh_2026_Department_Count_{campus or 'All'}.docx"
    filename = "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _brief_filename(campus: str, ext: str) -> str:
    name = f"Deeksharambh_2026_Student_Experience_Brief_{campus or 'All'}.{ext}"
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


@router.get("/admin/survey/deeksharambh-brief-ppt")
async def admin_deeksharambh_brief_ppt(request: Request, campus: str = Query(default="")):
    """The Student Experience & Orientation Impact Analysis brief — the
    journey, every department, the theme, what students said and asked for,
    and a closing summary. Same shape as the report already circulated."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from datetime import datetime
    from fastapi.responses import StreamingResponse
    import io

    from app.deeksharambh_brief_export import build_deeksharambh_brief_pptx
    from app.orientation_data import deeksharambh_brief
    from app.routes.shared_analysis import _in_thread

    data = await deeksharambh_brief(campus=campus)
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    ppt_bytes = await _in_thread(build_deeksharambh_brief_pptx, data, generated_at=generated_at)

    return StreamingResponse(
        io.BytesIO(ppt_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{_brief_filename(campus, "pptx")}"'},
    )


@router.get("/admin/survey/deeksharambh-brief-docx")
async def admin_deeksharambh_brief_docx(request: Request, campus: str = Query(default="")):
    """The same brief, as a Word document."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from datetime import datetime
    from fastapi.responses import StreamingResponse
    import io

    from app.deeksharambh_brief_export import build_deeksharambh_brief_docx
    from app.orientation_data import deeksharambh_brief
    from app.routes.shared_analysis import _in_thread

    data = await deeksharambh_brief(campus=campus)
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    docx_bytes = await _in_thread(build_deeksharambh_brief_docx, data, generated_at=generated_at)

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{_brief_filename(campus, "docx")}"'},
    )


@router.get("/admin/survey/deeksharambh-brief-xlsx")
async def admin_deeksharambh_brief_xlsx(request: Request, campus: str = Query(default="")):
    """The same brief's numbers, as a workbook — one sheet per section."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from datetime import datetime
    from fastapi.responses import StreamingResponse
    import io

    from app.deeksharambh_brief_export import build_deeksharambh_brief_xlsx
    from app.orientation_data import deeksharambh_brief, deeksharambh_roster
    from app.routes.shared_analysis import _in_thread

    data = await deeksharambh_brief(campus=campus)
    # Named, so it only ever rides along on this admin download — never the
    # copy built for the shared/token route.
    data["roster"] = await deeksharambh_roster(campus=campus)
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    xlsx_bytes = await _in_thread(build_deeksharambh_brief_xlsx, data, generated_at=generated_at)

    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_brief_filename(campus, "xlsx")}"'},
    )


async def run_orientation_mail_task(
    task_id: str,
    recipients: list[dict],
    subject: str,
    message: str,
    base_url: str,
    campus: str,
    link_label: str,
) -> None:
    """Mail one orientation cohort over a single SMTP connection.

    Same shape as the reminder batch task, so the dashboard can poll progress
    through the existing /admin/api/alert/status endpoint.
    """
    import asyncio
    from datetime import datetime, timezone
    from app import emailer
    from app.routes.landing import email_to_slug

    db = get_db()
    delay = max(0.0, float(getattr(settings, "email_batch_delay_seconds", 0.4)))
    sent = 0
    failed = 0

    try:
        async with emailer.SmtpBatchSender() as sender:
            for i, person in enumerate(recipients):
                if i > 0 and delay:
                    await asyncio.sleep(delay)

                email = (person.get("email") or "").strip()
                if not email:
                    continue
                name = person.get("name", "")

                try:
                    # src=reminder keeps the orientation form open for this
                    # student even when it is closed to everyone else.
                    link = f"{base_url}/resume/{email_to_slug(email)}?src=reminder"
                    await sender.send(emailer.build_orientation_message(
                        email, name, subject, message,
                        link=link, link_label=link_label,
                        campus=person.get("campus", "") or campus,
                    ))
                    await db["users"].update_one(
                        {"email": email},
                        {"$set": {"orientation_mail_sent_at": datetime.now(timezone.utc)},
                         "$inc": {"orientation_mail_count": 1},
                         "$unset": {"last_email_error": "", "email_failed_at": ""}},
                    )
                    sent += 1
                except Exception as exc:
                    failed += 1
                    log.warning("Orientation mail failed for %s: %s", email, exc)
                    await db["users"].update_one(
                        {"email": email},
                        {"$set": {"last_email_error": str(exc),
                                  "email_failed_at": datetime.now(timezone.utc)}},
                    )

                await db["admin_tasks"].update_one(
                    {"_id": task_id},
                    {"$set": {"sent": sent, "failed": failed,
                              "updated_at": datetime.now(timezone.utc)}},
                )
    except Exception as exc:
        log.exception("Orientation mail task %s aborted: %s", task_id, exc)
        await db["admin_tasks"].update_one(
            {"_id": task_id},
            {"$set": {"status": "error", "error": str(exc),
                      "updated_at": datetime.now(timezone.utc)}},
        )
        return

    await db["admin_tasks"].update_one(
        {"_id": task_id},
        {"$set": {"status": "completed", "sent": sent, "failed": failed,
                  "updated_at": datetime.now(timezone.utc)}},
    )


@router.post("/admin/api/orientation/mail")
async def api_orientation_mail(
    request: Request,
    background_tasks: BackgroundTasks,
    campus: str = Query(default=""),
    group: str = Query(default=ORI_FILLED),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    """Mail every student in one campus who filled the orientation (or hasn't).

    The subject and body are written by the admin; each mail is addressed
    personally and carries the student's own resume link.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")

    subject = str(body.get("subject") or "").strip()
    message = str(body.get("message") or "").strip()
    link_label = str(body.get("link_label") or "").strip() or "Open my survey"
    if not subject or not message:
        raise HTTPException(status_code=400, detail="A subject and a message are both required.")

    from app.orientation_data import orientation_dataset

    group = ORI_PENDING if group == ORI_PENDING else ORI_FILLED
    data = await orientation_dataset(campus=campus, dept=dept, ug_or_pg=ug_or_pg)
    recipients = [r for r in data[group] if r.get("email")]

    if not recipients:
        return JSONResponse({"ok": False, "error": "No students match this selection.",
                             "total": 0}, status_code=400)

    from datetime import datetime, timezone
    task_id = "ori_mail_" + secrets.token_hex(8)
    await get_db()["admin_tasks"].insert_one({
        "_id": task_id,
        "type": f"orientation-{group}",
        "campus": campus or "All campuses",
        "status": "running",
        "total": len(recipients),
        "sent": 0,
        "failed": 0,
        "subject": subject[:300],
        "started_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    background_tasks.add_task(
        run_orientation_mail_task,
        task_id,
        recipients,
        subject,
        message,
        str(request.base_url).rstrip("/"),
        campus or "",
        link_label,
    )

    return JSONResponse({"ok": True, "task_id": task_id, "total": len(recipients)})


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


@router.post("/admin/api/alert/dept-post-mail")
async def api_send_dept_post_mail(
    request: Request,
    background_tasks: BackgroundTasks,
    dept: str = Query(..., description="Target department name"),
):
    """Send post survey email (Orientation -> Post flow) to all pending students in a specific department."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    users = await list_survey_users(dept=dept or None)
    pending = [u for u in users if u.get("status") == STATUS_PRE_DONE]
    pending.sort(key=lambda u: bool(u.get("post_reminder_at")))

    import secrets
    task_id = "dept_post_" + secrets.token_hex(8)

    db = get_db()
    from datetime import datetime, timezone
    await db["admin_tasks"].insert_one({
        "_id": task_id,
        "type": "dept-post-pending",
        "dept": dept,
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
        "total_pending": len(pending),
        "dept": dept
    })


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    mins = int(seconds // 60)
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    rem_mins = mins % 60
    if hrs < 24:
        return f"{hrs}h {rem_mins}m" if rem_mins > 0 else f"{hrs}h"
    days = hrs // 24
    rem_hrs = hrs % 24
    return f"{days}d {rem_hrs}h"


@router.post("/admin/api/alert/targeted")
async def api_send_targeted_alert(
    request: Request,
    background_tasks: BackgroundTasks,
    target_type: str = Query(default="post-pending"),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    users = await list_survey_users(dept=dept or None, ug_or_pg=ug_or_pg or None)
    
    if target_type == "pre-pending":
        pending = [u for u in users if u.get("status") in ("not_started", None)]
        task_prefix = "pre_"
        type_name = "pre-pending"
    elif target_type == "sent-not-clicked":
        pending = [u for u in users if (u.get("pre_reminder_at") or u.get("post_reminder_at") or u.get("pre_reminder_count", 0) > 0 or u.get("post_reminder_count", 0) > 0) and not u.get("reminder_clicked_at") and u.get("status") != STATUS_POST_DONE]
        task_prefix = "unclicked_"
        type_name = "post-pending"
    elif target_type == "all-pending":
        pending = [u for u in users if u.get("status") != STATUS_POST_DONE]
        task_prefix = "all_"
        type_name = "post-pending"
    else:  # post-pending default
        pending = [u for u in users if u.get("status") == STATUS_PRE_DONE]
        task_prefix = "post_"
        type_name = "post-pending"

    pending.sort(key=lambda u: bool(u.get("post_reminder_at") or u.get("pre_reminder_at")))

    import secrets
    task_id = task_prefix + secrets.token_hex(8)
    
    db = get_db()
    from datetime import datetime, timezone
    await db["admin_tasks"].insert_one({
        "_id": task_id,
        "type": type_name,
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
        type_name,
        pending,
        base_url
    )
    
    return JSONResponse({
        "ok": True,
        "task_id": task_id,
        "total_pending": len(pending)
    })


@router.get("/admin/api/survey/time-analysis")
async def api_time_analysis(
    request: Request,
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    if not (_is_survey_admin(request) or _is_ori_admin(request)):
        raise HTTPException(status_code=403)
    users = await list_survey_users(limit=10000, dept=dept or None, ug_or_pg=ug_or_pg or None)
    
    dept_map = {}
    student_times = []
    
    for u in users:
        c_iso = u.get("created_at_iso")
        pre_iso = u.get("pre_submitted_at_iso")
        post_iso = u.get("post_submitted_at_iso")
        
        pre_mins = None
        post_mins = None
        total_mins = None
        
        try:
            if c_iso and pre_iso:
                t0 = datetime.fromisoformat(c_iso)
                t1 = datetime.fromisoformat(pre_iso)
                pre_mins = max(0.0, (t1 - t0).total_seconds() / 60.0)
        except Exception:
            pass

        try:
            if pre_iso and post_iso:
                t1 = datetime.fromisoformat(pre_iso)
                t2 = datetime.fromisoformat(post_iso)
                post_mins = max(0.0, (t2 - t1).total_seconds() / 60.0)
            elif c_iso and post_iso:
                t0 = datetime.fromisoformat(c_iso)
                t2 = datetime.fromisoformat(post_iso)
                post_mins = max(0.0, (t2 - t0).total_seconds() / 60.0)
        except Exception:
            pass

        try:
            if c_iso and post_iso:
                t0 = datetime.fromisoformat(c_iso)
                t2 = datetime.fromisoformat(post_iso)
                total_mins = max(0.0, (t2 - t0).total_seconds() / 60.0)
        except Exception:
            pass

        d_name = u.get("program") or "No Department"
        if d_name not in dept_map:
            dept_map[d_name] = {
                "dept": d_name,
                "total_users": 0,
                "pre_mins_sum": 0.0, "pre_count": 0,
                "post_mins_sum": 0.0, "post_count": 0,
                "total_mins_sum": 0.0, "total_count": 0,
            }

        dm = dept_map[d_name]
        dm["total_users"] += 1
        if pre_mins is not None:
            dm["pre_mins_sum"] += pre_mins
            dm["pre_count"] += 1
        if post_mins is not None:
            dm["post_mins_sum"] += post_mins
            dm["post_count"] += 1
        if total_mins is not None:
            dm["total_mins_sum"] += total_mins
            dm["total_count"] += 1

        student_times.append({
            "name": u.get("name"),
            "email": u.get("email"),
            "program": d_name,
            "ug_or_pg": u.get("ug_or_pg"),
            "status": u.get("status"),
            "created_at": u.get("created_at"),
            "pre_at": u.get("pre_at"),
            "post_at": u.get("post_at"),
            "pre_mins": round(pre_mins, 1) if pre_mins is not None else None,
            "post_mins": round(post_mins, 1) if post_mins is not None else None,
            "total_mins": round(total_mins, 1) if total_mins is not None else None,
            "pre_fmt": _fmt_duration(pre_mins * 60 if pre_mins is not None else None),
            "post_fmt": _fmt_duration(post_mins * 60 if post_mins is not None else None),
            "total_fmt": _fmt_duration(total_mins * 60 if total_mins is not None else None),
        })

    dept_averages = []
    for d_name, dm in dept_map.items():
        avg_pre = (dm["pre_mins_sum"] / dm["pre_count"]) if dm["pre_count"] > 0 else None
        avg_post = (dm["post_mins_sum"] / dm["post_count"]) if dm["post_count"] > 0 else None
        avg_total = (dm["total_mins_sum"] / dm["total_count"]) if dm["total_count"] > 0 else None
        dept_averages.append({
            "dept": d_name,
            "total_users": dm["total_users"],
            "avg_pre_mins": round(avg_pre, 1) if avg_pre is not None else None,
            "avg_post_mins": round(avg_post, 1) if avg_post is not None else None,
            "avg_total_mins": round(avg_total, 1) if avg_total is not None else None,
            "avg_pre_fmt": _fmt_duration(avg_pre * 60 if avg_pre is not None else None),
            "avg_post_fmt": _fmt_duration(avg_post * 60 if avg_post is not None else None),
            "avg_total_fmt": _fmt_duration(avg_total * 60 if avg_total is not None else None),
        })

    dept_averages.sort(key=lambda x: x["dept"])

    return JSONResponse({
        "departments": dept_averages,
        "students": student_times
    })


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


@router.get("/admin/survey/export-department-summary")
async def admin_export_department_summary(request: Request):
    """One workbook, one sheet: Registered / Baseline / Post / Deeksharambh,
    department by department. The single-tab export the overview page offers
    next to the roster export — a scan-and-sort view of the whole cohort
    rather than a report per department.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.db import department_registration_summary
    from app.excel_export import generate_department_summary_excel
    from app.routes.shared_analysis import _in_thread

    summary = await department_registration_summary()
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    book = await _in_thread(generate_department_summary_excel, summary,
                            generated_at=generated_at)

    filename = f"Deeksharambh_Department_Summary_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        io.BytesIO(book),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/survey/export-full-report")
async def admin_export_full_report(request: Request):
    """The "whole report" workbook: overview, charts, then one tab per
    department (descending by registered count) with that department's
    summary and every student behind it — everything the overview page's
    quicker exports offer, plus the roster-level detail, in one file.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.db import department_full_report
    from app.excel_export import generate_full_report_excel
    from app.routes.shared_analysis import _in_thread

    report = await department_full_report()
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    book = await _in_thread(generate_full_report_excel, report,
                            generated_at=generated_at)

    filename = f"Deeksharambh_Full_Report_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        io.BytesIO(book),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/survey/export-all-data")
async def admin_export_all_data(request: Request):
    """The heaviest export: department tabs carrying the actual
    question-by-question answers behind the Full report's done/pending —
    Pre, Post and Deeksharambh alike — plus the literacy/readiness scores
    derived from them.
    """
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.db import department_master_report
    from app.excel_export import generate_master_data_excel
    from app.routes.shared_analysis import _in_thread

    report = await department_master_report()
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    book = await _in_thread(generate_master_data_excel, report,
                            generated_at=generated_at)

    filename = f"Deeksharambh_All_Data_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        io.BytesIO(book),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    if dept and dept not in ("All Departments", "all", "All"):
        if dept in ("No Program", "No Department", "none", "None"):
            query["program"] = {"$in": ["", None, "No Program", "No Department"]}
        else:
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
    from app.routes.shared_analysis import _in_thread
    file_data, media_type, ext = await _in_thread(
        custom_cohort_export,
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
    if dept and dept not in ("All Departments", "all", "All"):
        if dept in ("No Program", "No Department", "none", "None"):
            query["program"] = {"$in": ["", None, "No Program", "No Department"]}
        else:
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
async def api_email_notification_stats(request: Request):
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)
    from app.db import get_email_notification_stats
    stats = await get_email_notification_stats()
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


@router.get("/admin/api/survey/impact-links")
async def api_survey_impact_links(request: Request):
    """Copyable links to the public impact page — all campuses, then each one."""
    if not _is_survey_admin(request):
        raise HTTPException(status_code=403)

    from app.orientation_analysis import CAMPUSES
    from app.routes.shared_analysis import vibe_share_url

    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "links": [
            {"campus": "All campuses", "url": vibe_share_url(base, "")},
            *({"campus": name, "url": vibe_share_url(base, name)} for name in CAMPUSES),
        ]
    })
