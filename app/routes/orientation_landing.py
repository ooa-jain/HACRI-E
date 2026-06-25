"""
orientation_landing.py — Deeksharambh entry point (separate from AI Survey)

  GET  /deeksharambh       → form: name + email + program
  POST /deeksharambh/start → save user, set session, redirect → /orientation

This is the URL sent to students for the orientation.
After filling Deeksharambh form → redirected to /survey/post (post survey).
Email is primary key — if student already did pre-survey,
their data is linked automatically.
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from app import deps
from app.db import FLAG_ORIENTATION, get_db, get_flag, upsert_user
from app.deps import issue_csrf, issue_session, make_csrf_token
from app.schemas import UserIdentity

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/deeksharambh", response_class=HTMLResponse)
async def deeksha_landing_get(
    request:    Request,
    hacri_session: str | None = Cookie(default=None),
    hacri_csrf:    str | None = Cookie(default=None),
):
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    if not orientation_enabled:
        return request.app.state.templates.TemplateResponse(
            request, "orientation_disabled.html", {}, status_code=200
        )

    # Check if already has session (returning student)
    user = None
    if hacri_session:
        sess = deps._unsign(hacri_session)
        if sess and "email" in sess:
            user = await get_db()["users"].find_one({"email": sess["email"]})

    csrf = hacri_csrf or make_csrf_token()
    response = request.app.state.templates.TemplateResponse(
        request, "deeksharambh_landing.html",
        {"user": user, "csrf_token": csrf, "error": None},
    )
    if not hacri_csrf:
        issue_csrf(response, csrf)
    return response


@router.post("/deeksharambh/start")
async def deeksha_landing_post(
    request:    Request,
    name:       str = Form(...),
    email:      str = Form(...),
    program:    str = Form(default=""),
    csrf:       str = Form(...),
    hacri_csrf: str | None = Cookie(default=None),
):
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    if not orientation_enabled:
        return request.app.state.templates.TemplateResponse(
            request, "orientation_disabled.html", {}, status_code=200
        )

    try:
        identity = UserIdentity(name=name, email=email)
    except ValidationError as e:
        csrf_token = hacri_csrf or make_csrf_token()
        return request.app.state.templates.TemplateResponse(
            request, "deeksharambh_landing.html",
            {"user": None, "csrf_token": csrf_token, "error": _fmt_val_error(e)},
            status_code=422,
        )

    deps.verify_csrf(csrf, hacri_csrf)

    # Upsert user — if pre-survey already done, this just updates name/program
    await upsert_user(identity.email, identity.name, program)

    response = RedirectResponse(url="/orientation", status_code=303)
    issue_session(response, identity.email, identity.name)
    issue_csrf(response, hacri_csrf or make_csrf_token())
    return response


def _fmt_val_error(e: ValidationError) -> str:
    parts = [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
    return "Please correct: " + "; ".join(parts)
