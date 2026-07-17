"""
landing.py — AI Survey entry point
  GET  /          → form: name + email + program
  POST /start     → save user, set session, redirect → /survey/pre
  GET  /locked    → survey closed page
  GET  /logout    → clear session
"""
from __future__ import annotations
import base64
import binascii
from datetime import datetime, timezone
from fastapi import APIRouter, Cookie, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from app import deps
from app.db import (
    FLAG_SURVEY, FLAG_PRE_SURVEY, FLAG_ORIENTATION,
    STATUS_PRE_DONE, STATUS_POST_DONE,
    get_db, get_flag, upsert_user
)
from app.deps import issue_csrf, issue_session, make_csrf_token
from app.schemas import UserIdentity

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _email_to_slug(email: str) -> str:
    return base64.urlsafe_b64encode(email.lower().encode()).rstrip(b"=").decode()


def slug_to_email(slug: str) -> str | None:
    try:
        padded = slug + "=" * (-len(slug) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode().lower()
    except (binascii.Error, UnicodeDecodeError):
        return None


email_to_slug = _email_to_slug


@router.get("/", response_class=HTMLResponse)
async def landing_get(
    request: Request,
    hacri_session: str | None = Cookie(default=None),
    hacri_csrf:    str | None = Cookie(default=None),
):
    survey_enabled = await get_flag(FLAG_SURVEY, default=True)
    user = None
    if hacri_session:
        sess = deps._unsign(hacri_session)
        if sess and "email" in sess:
            user = await get_db()["users"].find_one({"email": sess["email"]})
            if user:
                user["email_slug"] = email_to_slug(user["email"])

    pre_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    post_enabled = await get_flag("post_survey_enabled", default=True)

    csrf = hacri_csrf or make_csrf_token()
    response = request.app.state.templates.TemplateResponse(
        request, "landing.html",
        {
            "user": user,
            "csrf_token": csrf,
            "error": None,
            "survey_enabled": survey_enabled,
            "pre_survey_enabled": pre_enabled,
            "orientation_enabled": orientation_enabled,
            "post_survey_enabled": post_enabled,
        },
    )
    if not hacri_csrf:
        issue_csrf(response, csrf)
    return response


@router.post("/start")
async def landing_post(
    request:    Request,
    name:       str = Form(...),
    email:      str = Form(...),
    confirm_email: str | None = Form(default=None),
    ug_or_pg:   str = Form(default="ug"),
    education_type: str = Form(default=""),
    program:    str = Form(default=""),
    csrf:       str = Form(...),
    hacri_csrf: str | None = Cookie(default=None),
):
    survey_enabled = await get_flag(FLAG_SURVEY, default=True)
    if not survey_enabled:
        return RedirectResponse(url="/locked", status_code=303)

    if confirm_email is not None and email.strip().lower() != confirm_email.strip().lower():
        csrf_token = hacri_csrf or make_csrf_token()
        return request.app.state.templates.TemplateResponse(
            request, "landing.html",
            {"user": None, "csrf_token": csrf_token,
             "error": "Please correct: Email addresses do not match.", "survey_enabled": survey_enabled},
            status_code=422,
        )

    try:
        identity = UserIdentity(
            name=name,
            email=email,
            ug_or_pg=ug_or_pg or "ug",
            education_type=education_type or None,
        )
    except ValidationError as e:
        csrf_token = hacri_csrf or make_csrf_token()
        return request.app.state.templates.TemplateResponse(
            request, "landing.html",
            {"user": None, "csrf_token": csrf_token,
             "error": _fmt_val_error(e), "survey_enabled": survey_enabled},
            status_code=422,
        )

    deps.verify_csrf(csrf, hacri_csrf)
    user = await upsert_user(identity.email, identity.name, program, identity.ug_or_pg, identity.education_type)

    status_v = user.get("status")
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    orientation_submitted = bool(user.get("orientation_submitted", False))
    pre_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)

    if status_v == STATUS_POST_DONE:
        dest_url = f"/results/{email_to_slug(identity.email)}"
    elif pre_enabled and status_v != STATUS_PRE_DONE:
        dest_url = "/survey/pre"
    elif orientation_enabled and not orientation_submitted:
        dest_url = "/orientation"
    else:
        dest_url = "/survey/post"

    response = RedirectResponse(url=dest_url, status_code=303)
    issue_session(response, identity.email, identity.name)
    issue_csrf(response, hacri_csrf or make_csrf_token())
    return response


@router.get("/resume/{email_slug}")
async def resume_session(request: Request, email_slug: str, src: str | None = None):
    email = slug_to_email(email_slug)
    if not email:
        return RedirectResponse(url="/", status_code=303)

    db = get_db()
    user = await db["users"].find_one({"email": email})
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if src == "reminder":
        from datetime import datetime, timezone
        await db["users"].update_one(
            {"email": email},
            {"$set": {"reminder_clicked_at": datetime.now(timezone.utc)}}
        )

    status_v = user.get("status")
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    orientation_submitted = bool(user.get("orientation_submitted", False))
    pre_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)

    if status_v == STATUS_POST_DONE:
        dest_url = f"/results/{email_slug}"
    elif pre_enabled and status_v != STATUS_PRE_DONE:
        dest_url = "/survey/pre"
    elif orientation_enabled and not orientation_submitted:
        dest_url = "/orientation"
    else:
        dest_url = "/survey/post"

    response = RedirectResponse(url=dest_url, status_code=303)
    issue_session(response, user["email"], user.get("name", ""))
    issue_csrf(response, make_csrf_token())
    return response


@router.get("/locked", response_class=HTMLResponse)
async def locked(request: Request):
    return request.app.state.templates.TemplateResponse(request, "locked.html", {})


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    deps.clear_session(response)
    return response


def _fmt_val_error(e: ValidationError) -> str:
    parts = [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
    return "Please correct: " + "; ".join(parts)
