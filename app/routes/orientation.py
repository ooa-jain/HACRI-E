"""
orientation.py — Deeksharambh form + submit

  GET  /orientation               → show Deeksharambh form (email pre-filled from session/pre-survey)
  POST /api/orientation/submit    → save to orientation_responses, redirect → /survey/post
"""
from __future__ import annotations
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.db import (
    FLAG_ORIENTATION, STATUS_PRE_DONE, STATUS_POST_DONE,
    get_db, get_flag, get_pre_name, save_orientation_response,
)
from app.deps import get_current_session

router = APIRouter()


@router.get("/orientation", response_class=HTMLResponse)
async def orientation_get(
    request: Request,
    session: Annotated[dict, Depends(get_current_session)],
):
    email = session["email"]
    clean_email = email.strip().lower()
    name  = session["name"]

    from app.db import email_filter
    user = await get_db()["users"].find_one(email_filter(email))
    if user and user.get("status") == STATUS_POST_DONE:
        from app.routes.landing import email_to_slug
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/results/{email_to_slug(email)}", status_code=303)

    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    # Personally invited students (reminder email or department post link) keep
    # access to the orientation even when it is closed to everyone else.
    from app.routes.surveys import _has_post_access
    from_reminder = bool(user and _has_post_access(user))
    if not orientation_enabled and not from_reminder:
        return request.app.state.templates.TemplateResponse(
            request, "orientation_disabled.html", {}, status_code=200
        )

    already_done = bool(user and user.get("orientation_submitted", False))
    if not already_done:
        ori_doc = await get_db()["orientation_responses"].find_one({"email": {"$in": [clean_email, email]}})
        if ori_doc:
            already_done = True
            await get_db()["users"].update_one(
                email_filter(email), {"$set": {"orientation_submitted": True}})

    saved_responses = {}
    if already_done:
        ori_doc = await get_db()["orientation_responses"].find_one({"email": {"$in": [clean_email, email]}}, sort=[("submitted_at", -1)])
        if ori_doc:
            saved_responses = ori_doc.get("data", {})

    # Get name from pre-survey record if available (more accurate)
    pre_name = await get_pre_name(email)
    display_name = pre_name or name

    from app.db import FLAG_TEST_MODE
    test_mode = await get_flag(FLAG_TEST_MODE, default=False)

    return request.app.state.templates.TemplateResponse(
        request, "orientation.html",
        {
            "prefill_email": email,
            "prefill_name": display_name,
            # Everything below is already on the student's registration — the
            # orientation form shows it back instead of asking again.
            "prefill_dept": (user or {}).get("program", ""),
            "prefill_ugpg": ((user or {}).get("ug_or_pg", "") or "").upper(),
            "prefill_location": (user or {}).get("location", ""),
            "already_done": already_done,
            "saved_responses": saved_responses,
            "test_mode_enabled": test_mode,
        },
    )


@router.post("/api/orientation/submit")
async def orientation_submit(
    request: Request,
    session: Annotated[dict, Depends(get_current_session)],
):
    email = session["email"]
    name  = session["name"]

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    if not data:
        return JSONResponse({"ok": False, "error": "Empty payload"}, status_code=400)

    data.pop("_id", None)
    clean_email = email.strip().lower()
    data["email"] = clean_email
    data["name"]  = name
    if not data.get("id"):
        data["id"] = str(uuid.uuid4())[:8]

    await save_orientation_response(email, name, data)

    # Case-insensitively: the address on the session is whatever the student
    # typed, and the record holds whatever they typed at registration. When
    # these disagreed this update matched nothing, the student was never marked
    # as having answered, and the page after submit bounced them.
    from app.db import email_filter
    db = get_db()
    await db["users"].update_one(
        email_filter(email), {"$set": {"orientation_submitted": True}}
    )

    return JSONResponse({"ok": True, "id": data["id"], "redirect": "/survey/post"})
