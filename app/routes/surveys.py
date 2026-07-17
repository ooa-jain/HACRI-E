"""
Pre and Post survey routes.

GET /survey/pre   → render pre form
POST /survey/pre  → validate, store, atomic status transition
GET /survey/post  → render post form (or redirect to /locked if not pre_done)
POST /survey/post → validate, store, atomic transition, BackgroundTasks for charts/email

Server-side enforcement: every state-changing endpoint re-checks Mongo,
never trusts the cookie alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app import charts as chart_helpers
from app import deps, emailer
from app.db import (
    STATUS_POST_DONE,
    STATUS_PRE_DONE,
    FLAG_SURVEY,
    FLAG_PRE_SURVEY,
    FLAG_ORIENTATION,
    FLAG_TEST_MODE,
    get_db,
    get_flag,
    get_setting_int,
    save_post_response,
    save_pre_response,
)
from app.deps import get_current_session
from app.hacri_e2_compat import SCHEMA
from app.schemas import coerce_checkbox_list, coerce_int, coerce_str, coerce_text
from app.scoring import is_complete_post, is_complete_pre
from app.sections import (
    POST_REFLECTION,
    PRE_BACKGROUND,
    PRE_E11_OPTIONS,
    PRE_FUTURE,
    PRE_USAGE,
    SECTION_TITLES,
)
from app.settings import settings

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _likert_field_keys(section: str) -> list[str]:
    return [k for k in SCHEMA if k.startswith(section)]


def _build_pre_fields(form: Any) -> dict[str, Any]:
    """Coerce raw form data into the canonical fields dict.

    `form` is a starlette FormData (which supports both `get(k)` for single
    values and `getlist(k)` for multi-value fields like checkboxes).
    """
    fields: dict[str, Any] = {}

    # Section A — selects
    for key, _label, _kind, _opts in PRE_BACKGROUND:
        fields[key] = coerce_str(form.get(key))

    # Section B — Likert (B1–B10), plus B11 free text
    for k in _likert_field_keys("B"):
        fields[k] = coerce_int(form.get(k))
    fields["B11"] = coerce_text(form.get("B11"), max_len=1500)

    # Section C — checkbox multi / selects
    for key, _label, kind, _opts in PRE_USAGE:
        if kind == "checkbox":
            fields[key] = coerce_checkbox_list(form.getlist(key))
        else:
            fields[key] = coerce_str(form.get(key))

    # Section D — Likert
    for k in _likert_field_keys("D"):
        fields[k] = coerce_int(form.get(k))

    # Section E — Likert + scenario sub-question + reason
    for k in _likert_field_keys("E"):
        fields[k] = coerce_int(form.get(k))
    fields["E11"] = coerce_str(form.get("E11"))
    fields["E11_reason"] = coerce_text(form.get("E11_reason"), max_len=500)

    # Section F — Likert
    for k in _likert_field_keys("F"):
        fields[k] = coerce_int(form.get(k))

    # Section G — Likert
    for k in _likert_field_keys("G"):
        fields[k] = coerce_int(form.get(k))

    # Section H — Future Expectations
    fields["H1"] = coerce_int(form.get("H1"))
    fields["H2"] = coerce_checkbox_list(form.getlist("H2"))
    fields["H3"] = coerce_int(form.get("H3"))
    fields["H4"] = coerce_str(form.get("H4"))
    fields["H5"] = coerce_text(form.get("H5"), max_len=2000)
    fields["H6"] = coerce_text(form.get("H6"), max_len=2000)

    return fields


def _build_post_fields(form: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    # Section A fields — Father
    fields["father_name"] = coerce_str(form.get("father_name"))
    fields["father_occupation"] = coerce_str(form.get("father_occupation"))
    fields["organization_name"] = coerce_str(form.get("organization_name"))
    fields["business_name"] = coerce_str(form.get("business_name"))
    fields["business_type"] = coerce_text(form.get("business_type"), max_len=500)

    # Section A fields — Mother
    fields["mother_name"] = coerce_str(form.get("mother_name"))
    fields["mother_occupation"] = coerce_str(form.get("mother_occupation"))
    fields["mother_organization_name"] = coerce_str(form.get("mother_organization_name"))
    fields["mother_business_name"] = coerce_str(form.get("mother_business_name"))
    fields["mother_business_type"] = coerce_text(form.get("mother_business_type"), max_len=500)

    # Identical B/D/E/F/G Likert items
    for section in ("B", "D", "E", "F", "G"):
        for k in _likert_field_keys(section):
            fields[k] = coerce_int(form.get(k))

    # E11 sub-question is not repeated in the post survey per the PDF
    # (post only re-uses identical Likert wording for B/D/E/F/G)

    # Post H reflection
    fields["H1"] = coerce_str(form.get("H1"))        # radio → option text
    fields["H2"] = coerce_int(form.get("H2"))        # 1-5 scale
    fields["H3"] = coerce_str(form.get("H3"))        # radio → option text
    fields["H4"] = coerce_text(form.get("H4"), max_len=2000)

    return fields


async def _render_form(
    request: Request,
    template: str,
    *,
    values: dict | None = None,
    errors: list[str] | None = None,
    extra_ctx: dict | None = None,
):
    values = values or {}
    csrf_token = request.cookies.get("hacri_csrf", "")
    test_mode = await get_flag(FLAG_TEST_MODE, default=False)
    ctx = {
        "values": values,
        "errors": errors or [],
        "csrf_token": csrf_token,
        "section_titles": SECTION_TITLES,
        "schema": SCHEMA,
        "pre_background": PRE_BACKGROUND,
        "pre_usage": PRE_USAGE,
        "pre_future": PRE_FUTURE,
        "pre_e11_options": PRE_E11_OPTIONS,
        "post_reflection": POST_REFLECTION,
        "test_mode_enabled": test_mode,
        "likert_choices": [(1, "Strongly Disagree"), (2, "Disagree"),
                           (3, "Neutral"), (4, "Agree"), (5, "Strongly Agree")],
    }
    if extra_ctx:
        ctx.update(extra_ctx)
    return request.app.state.templates.TemplateResponse(request, template, ctx)


# ── Pre ──────────────────────────────────────────────────────────────────────
@router.get("/survey/pre", response_class=HTMLResponse)
async def pre_get(
    request: Request,
    session: Annotated[dict, Depends(get_current_session)],
    msg: str | None = None,
):
    # Gate on survey feature flag
    if not await get_flag(FLAG_SURVEY, default=True):
        return RedirectResponse(url="/locked", status_code=303)

    # Check if pre-survey is disabled
    pre_survey_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)
    if not pre_survey_enabled:
        orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
        if orientation_enabled:
            return RedirectResponse(url="/orientation", status_code=303)
        return RedirectResponse(url="/survey/post", status_code=303)

    user = await get_db()["users"].find_one({"email": session["email"]})
    if user and user.get("status") == STATUS_POST_DONE:
        from app.routes.landing import email_to_slug
        return RedirectResponse(url=f"/results/{email_to_slug(session['email'])}", status_code=303)

    db_draft = (user or {}).get("pre_draft", {})
    draft_fields = db_draft.get("fields", {})
    draft_step = db_draft.get("step", 0)

    extra = {
        "ug_or_pg": (user or {}).get("ug_or_pg", "ug") if user else "ug",
        "education_type": (user or {}).get("education_type", ""),
        "draft_step": draft_step,
    }
    if msg == "complete_pre_first":
        extra["banner"] = "Please complete the Baseline Survey before accessing the Post-Workshop Survey."
    return await _render_form(request, "pre_survey.html", values=draft_fields, extra_ctx=extra)


@router.post("/survey/pre")
async def pre_post(
    request: Request,
    csrf: Annotated[str, Form()],
    session: Annotated[dict, Depends(get_current_session)],
    hacri_csrf: Annotated[str | None, Cookie()] = None,
):
    deps.verify_csrf(csrf, hacri_csrf)
    # Check if pre-survey is disabled
    pre_survey_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)
    if not pre_survey_enabled:
        orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
        if orientation_enabled:
            return RedirectResponse(url="/orientation", status_code=303)
        return RedirectResponse(url="/survey/post", status_code=303)

    email = session["email"]
    name = session["name"]

    form = await request.form()
    fields = _build_pre_fields(form)

    test_mode = await get_flag(FLAG_TEST_MODE, default=False)
    errors = []
    if not test_mode:
        if not is_complete_pre(fields):
            errors.append("Please answer every Likert item (B1–B10, D, E, F, G) before submitting.")
        if not fields.get("C1"):
            errors.append("Please select at least 1 option in question C1.")
        if not fields.get("C3"):
            errors.append("Please select at least 1 option in question C3.")
        if not fields.get("H2"):
            errors.append("Please select at least 1 option in question H2.")

    if errors:
        return await _render_form(
            request,
            "pre_survey.html",
            values=fields,
            errors=errors,
        ), 422

    pre_id, _user = await save_pre_response(email, name, fields)
    await get_db()["users"].update_one(
        {"email": email},
        {"$unset": {"pre_draft": ""}}
    )
    return RedirectResponse(url="/survey/pre/done", status_code=303)


@router.get("/survey/pre/done", response_class=HTMLResponse)
async def pre_done(
    request: Request,
    session: Annotated[dict, Depends(get_current_session)],
):
    """Thank the user after the pre-survey and remind them to keep using the
    same email for any upcoming forms. No post-survey link is shown here."""
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    user = await get_db()["users"].find_one({"email": session.get("email")})
    orientation_submitted = bool(user and user.get("orientation_submitted", False))
    return request.app.state.templates.TemplateResponse(
        request,
        "pre_done.html",
        {
            "name": session.get("name", ""),
            "email": session.get("email", ""),
            "orientation_enabled": orientation_enabled and not orientation_submitted,
        },
    )


# ── Post ─────────────────────────────────────────────────────────────────────
@router.get("/survey/post", response_class=HTMLResponse)
async def post_get(
    request: Request,
    session: Annotated[dict, Depends(get_current_session)],
):
    user = await get_db()["users"].find_one({"email": session["email"]})
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if user.get("status") == STATUS_POST_DONE:
        from app.routes.landing import email_to_slug
        return RedirectResponse(url=f"/results/{email_to_slug(session['email'])}", status_code=303)

    if not await get_flag(FLAG_SURVEY, default=True):
        return RedirectResponse(url="/locked", status_code=303)

    post_enabled = await get_flag("post_survey_enabled", default=True)
    if not post_enabled:
        return request.app.state.templates.TemplateResponse(
            request, "post_locked.html",
            {"reason": "disabled", "name": user.get("name", "")}
        )

    pre_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    status_v = user.get("status")

    if pre_enabled:
        if status_v not in (STATUS_PRE_DONE, STATUS_POST_DONE):
            return RedirectResponse(url="/survey/pre?msg=complete_pre_first", status_code=303)
    else:
        if orientation_enabled:
            if not user.get("orientation_submitted"):
                return RedirectResponse(url="/orientation", status_code=303)

    delay_days = await get_setting_int("post_delay_days", default=0)
    if delay_days > 0:
        start_time = user.get("pre_submitted_at") or user.get("created_at")
        if start_time:
            from app.db import _now
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            now_time = _now()
            elapsed = now_time - start_time
            if elapsed.total_seconds() < delay_days * 86400:
                from datetime import timedelta
                available_at = start_time + timedelta(days=delay_days)
                days_left = (available_at - now_time).total_seconds() / 86400
                return request.app.state.templates.TemplateResponse(
                    request, "post_locked.html",
                    {
                        "reason": "delay",
                        "name": user.get("name", ""),
                        "days_left": round(days_left, 1),
                        "available_at": available_at.strftime("%d %b %Y %H:%M"),
                    }
                )

    db_draft = (user or {}).get("post_draft", {})
    draft_fields = db_draft.get("fields", {})
    draft_step = db_draft.get("step", 0)
    extra = {
        "draft_step": draft_step,
    }
    return await _render_form(request, "post_survey.html", values=draft_fields, extra_ctx=extra)


@router.post("/survey/post")
async def post_post(
    request: Request,
    background: BackgroundTasks,
    csrf: Annotated[str, Form()],
    session: Annotated[dict, Depends(get_current_session)],
    hacri_csrf: Annotated[str | None, Cookie()] = None,
):
    deps.verify_csrf(csrf, hacri_csrf)
    email = session["email"]
    name = session["name"]

    # Re-check Mongo state server-side
    user = await get_db()["users"].find_one({"email": email})
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if not await get_flag(FLAG_SURVEY, default=True):
        return RedirectResponse(url="/locked", status_code=303)

    post_enabled = await get_flag("post_survey_enabled", default=True)
    if not post_enabled:
        raise HTTPException(status_code=400, detail="Post survey is closed.")

    pre_enabled = await get_flag(FLAG_PRE_SURVEY, default=True)
    orientation_enabled = await get_flag(FLAG_ORIENTATION, default=False)
    status_v = user.get("status")

    if pre_enabled:
        if status_v not in (STATUS_PRE_DONE, STATUS_POST_DONE):
            return RedirectResponse(url="/survey/pre?msg=complete_pre_first", status_code=303)
    else:
        if orientation_enabled:
            if not user.get("orientation_submitted"):
                return RedirectResponse(url="/orientation", status_code=303)

    delay_days = await get_setting_int("post_delay_days", default=0)
    if delay_days > 0:
        start_time = user.get("pre_submitted_at") or user.get("created_at")
        if start_time:
            from app.db import _now
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            elapsed = _now() - start_time
            if elapsed.total_seconds() < delay_days * 86400:
                raise HTTPException(status_code=400, detail="Post survey is locked due to start delay gating.")

    form = await request.form()
    fields = _build_post_fields(form)

    test_mode = await get_flag(FLAG_TEST_MODE, default=False)
    errors = []
    if not test_mode:
        if not is_complete_post(fields):
            errors.append("Please answer every Likert item (B, D, E, F, G) before submitting.")
        
        # Section A validation — Father
        if not fields.get("father_name"):
            errors.append("Please enter Father's Name.")
        
        occupation = fields.get("father_occupation")
        if not occupation:
            errors.append("Please select Father's Occupation.")
        elif occupation == "Salaried":
            if not fields.get("organization_name"):
                errors.append("Please enter Father's Organization Name.")
        elif occupation == "Entrepreneur":
            if not fields.get("business_name"):
                errors.append("Please enter Father's Business Name.")
            if not fields.get("business_type"):
                errors.append("Please explain Father's Type of Business.")

        # Section A validation — Mother
        if not fields.get("mother_name"):
            errors.append("Please enter Mother's Name.")

        mother_occ = fields.get("mother_occupation")
        if not mother_occ:
            errors.append("Please select Mother's Occupation.")
        elif mother_occ == "Salaried":
            if not fields.get("mother_organization_name"):
                errors.append("Please enter Mother's Organization Name.")
        elif mother_occ == "Entrepreneur":
            if not fields.get("mother_business_name"):
                errors.append("Please enter Mother's Business Name.")
            if not fields.get("mother_business_type"):
                errors.append("Please explain Mother's Type of Business.")

    if errors:
        return await _render_form(
            request,
            "post_survey.html",
            values=fields,
            errors=errors,
        ), 422

    post_id, updated_user = await save_post_response(email, name, fields)
    await get_db()["users"].update_one(
        {"email": email},
        {"$unset": {"post_draft": ""}}
    )

    if updated_user is None or updated_user.get("status") != STATUS_POST_DONE:
        # Should not normally happen — the re-check above allows it.
        raise HTTPException(status_code=403, detail="Could not transition to post_done.")

    # Schedule chart generation + email in the background
    background.add_task(_after_post_submit, email, name)

    from app.routes.landing import email_to_slug
    return RedirectResponse(
        url=f"/results/{email_to_slug(email)}",
        status_code=303,
    )


async def _after_post_submit(email: str, name: str) -> None:
    """Background task: render PNGs, write CSV, send results email."""
    try:
        db = get_db()
        pre_doc = await db["pre_responses"].find_one(
            {"email": email}, sort=[("submitted_at", -1)]
        )
        post_doc = await db["post_responses"].find_one(
            {"email": email}, sort=[("submitted_at", -1)]
        )
        if not post_doc:
            return
        pre_fields = pre_doc.get("fields", {}) if pre_doc else {}
        post_fields = post_doc.get("fields", {})

        # 1. Per-user 2x2 PNG
        user_png = await _to_thread(
            chart_helpers.plot_user_png, email, pre_fields, post_fields
        )

        # 2. H histograms (Cohort-level)
        all_posts = {}
        async for p_doc in db["post_responses"].find():
            p_email = p_doc["email"]
            p_fields = dict(p_doc.get("fields", {}))
            
            # Find the corresponding pre response for H2 checklist mapping
            pr_doc = await db["pre_responses"].find_one({"email": p_email})
            if pr_doc:
                pre_h2 = pr_doc.get("fields", {}).get("H2") or []
                from app.hacri_e2_compat import H2_LABELS
                for idx, label in enumerate(H2_LABELS):
                    if label in pre_h2:
                        p_fields[f"H2_{idx}"] = "Yes"
            all_posts[p_email] = p_fields

        h_paths = await _to_thread(
            chart_helpers.plot_h_histograms_png,
            all_posts,
        )

        # 3. CSV
        from app.csv_export import scorecard_csv_bytes
        csv_bytes = scorecard_csv_bytes(name, email, pre_fields, post_fields)
        csv_path = settings.generated_root / "scorecards" / f"{email}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(csv_bytes)

        # 4. Scoring deltas
        from app.scoring import delta
        deltas = delta(pre_fields, post_fields)

        # 5. Email
        from app.routes.landing import email_to_slug
        slug = email_to_slug(email)
        results_url = f"{settings.public_base_url.rstrip('/')}/results/{slug}"
        await emailer.send_results_email(
            name=name,
            email=email,
            results_url=results_url,
            png_paths={
                "user_2x2": user_png,
                "H1": h_paths["H1"],
                "H2": h_paths["H2"],
                "H3": h_paths["H3"],
            },
            csv_path=csv_path,
            deltas=deltas,
        )
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger(__name__).exception("after_post_submit failed: %s", e)


async def _to_thread(func, *args, **kwargs):
    """Run a blocking function in the default threadpool and await the result."""
    import asyncio
    return await asyncio.get_running_loop().run_in_executor(
        None, lambda: func(*args, **kwargs)
    )


@router.post("/survey/draft/{survey_type}")
async def save_draft(
    survey_type: str,
    request: Request,
    session: Annotated[dict, Depends(get_current_session)],
):
    if survey_type not in ("pre", "post"):
        raise HTTPException(status_code=400, detail="Invalid survey type")

    data = await request.json()
    csrf_token = data.get("csrf")
    hacri_csrf = request.cookies.get("hacri_csrf")
    
    from app import deps
    deps.verify_csrf(csrf_token, hacri_csrf)

    db = get_db()
    await db["users"].update_one(
        {"email": session["email"]},
        {
            "$set": {
                f"{survey_type}_draft": {
                    "step": data.get("step", 0),
                    "fields": data.get("fields", {}),
                    "updated_at": _now()
                }
            }
        }
    )
    return {"ok": True}