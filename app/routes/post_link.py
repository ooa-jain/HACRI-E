"""
post_link.py — Department-wise survey entry links.

The admin generates two links per department in the admin portal:

    GET  /pre/<dept-slug>    → Outcome Survey 1 (Baseline): the normal
                               registration page with the department locked
    GET  /post/<dept-slug>   → Impact Post Survey: page asking for the email
    POST /post/<dept-slug>   → check the email, then open the post survey

A student who opens a post link types the email they registered with. If that
email belongs to the link's department AND already has a completed baseline
(pre) survey, a session is issued and the post survey opens straight away —
no landing page, no re-registration. Everything else (wrong department, no
baseline yet, unknown email) is answered with a plain message on the same page.

`/post/all` works the same way but accepts any department.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.departments import DEPARTMENTS
from app.db import (
    FLAG_PRE_SURVEY,
    NO_DEPARTMENT,
    STATUS_POST_DONE,
    STATUS_PRE_DONE,
    get_db,
    get_flag,
    get_setting_int,
    list_departments,
)
from app.deps import issue_csrf, issue_session, make_csrf_token

router = APIRouter()

ALL_SLUG = "all"
NO_DEPT_SLUG = "no-department"


def dept_slug(dept: str | None) -> str:
    """URL-safe slug for a department name ('' → the no-department slug)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (dept or "").strip().lower()).strip("-")
    return slug or NO_DEPT_SLUG


def dept_post_url(base_url: str, dept: str | None) -> str:
    return f"{base_url.rstrip('/')}/post/{dept_slug(dept)}"


def dept_pre_url(base_url: str, dept: str | None) -> str:
    return f"{base_url.rstrip('/')}/pre/{dept_slug(dept)}"


async def resolve_dept(slug: str) -> str:
    """Name the department a slug refers to.

    Returns "" for the all-departments link. Otherwise the department name as
    it is officially spelled — first from the canonical department list, then
    from the student records, and only as a last resort from the slug itself.
    Spelling matters here: this is the name new registrations are stored under.
    """
    slug = (slug or "").strip().lower()
    if slug == ALL_SLUG:
        return ""
    if slug == NO_DEPT_SLUG:
        return NO_DEPARTMENT
    for dept in DEPARTMENTS:
        if dept_slug(dept) == slug:
            return dept
    for dept in await list_departments():
        if dept_slug(dept) == slug:
            return dept
    return slug.replace("-", " ").title()


def _fmt_when(value) -> str:
    return value.strftime("%d %b %Y") if isinstance(value, datetime) else ""


def _matches_dept(user_dept: str, slug: str) -> bool:
    """Is this student covered by this link?

    Compared as slugs against the student's own department, so a link keeps
    working regardless of how the department name is cased or punctuated.
    """
    slug = (slug or "").strip().lower()
    if slug == ALL_SLUG:
        return True
    if slug == NO_DEPT_SLUG:
        return not (user_dept or "").strip()
    return dept_slug(user_dept) == slug


def _render(request: Request, slug: str, dept: str, *, error: str = "",
            email: str = "", status_code: int = 200, welcome: dict | None = None):
    return request.app.state.templates.TemplateResponse(
        request,
        "post_entry.html",
        {
            "dept": dept,
            "dept_label": dept or "All Departments",
            "slug": slug,
            "error": error,
            "email": email,
            "welcome": welcome,
        },
        status_code=status_code,
    )


@router.get("/pre/{slug}", response_class=HTMLResponse)
async def pre_entry_get(
    request: Request,
    slug: str,
    hacri_session: str | None = Cookie(default=None),
    hacri_csrf: str | None = Cookie(default=None),
):
    """Outcome Survey 1 (Baseline) for one department.

    The ordinary registration page with the department pre-filled and locked,
    so everyone arriving through a department's link is filed under it.
    """
    from app.routes.landing import render_landing

    dept = await resolve_dept(slug)
    if not dept:  # /pre/all — nothing to lock, just the normal page
        return await render_landing(request, hacri_session, hacri_csrf)
    return await render_landing(request, hacri_session, hacri_csrf, locked_program=dept)


@router.get("/post/{slug}", response_class=HTMLResponse)
async def post_entry_get(request: Request, slug: str):
    return _render(request, slug, await resolve_dept(slug))


@router.post("/post/{slug}", response_class=HTMLResponse)
async def post_entry_post(request: Request, slug: str, email: str = Form(...)):
    dept = await resolve_dept(slug)

    email = (email or "").strip().lower()
    if not email:
        return _render(request, slug, dept, error="Please enter your email address.",
                       status_code=422)

    db = get_db()
    user = await db["users"].find_one({"email": email})
    if not user:
        return _render(
            request, slug, dept, email=email,
            error="We could not find this email. Please use the same email "
                  "address you used for the baseline survey.",
            status_code=404,
        )

    if not _matches_dept(user.get("program", ""), slug):
        registered_dept = (user.get("program") or "").strip() or NO_DEPARTMENT
        return _render(
            request, slug, dept, email=email,
            error=f"This link is for {dept}, but your registration is under "
                  f"{registered_dept}. Please use your own department's link.",
            status_code=403,
        )

    from app.routes.landing import email_to_slug

    status_v = user.get("status")
    if status_v == STATUS_POST_DONE:
        response = RedirectResponse(url=f"/results/{email_to_slug(email)}", status_code=303)
        issue_session(response, email, user.get("name", ""))
        issue_csrf(response, make_csrf_token())
        return response

    # A completed baseline is the entry ticket — unless the baseline survey is
    # switched off entirely, in which case nobody has one.
    if status_v != STATUS_PRE_DONE and await get_flag(FLAG_PRE_SURVEY, default=True):
        return _render(
            request, slug, dept, email=email,
            error="We could not find a completed baseline survey for this "
                  "email. Please complete the baseline survey first.",
            status_code=403,
        )

    # The post survey can still be time-locked after the baseline. Say so here
    # instead of bouncing the student to a page they cannot act on.
    delay_days = await get_setting_int("post_delay_days", default=0)
    if delay_days > 0:
        start = user.get("pre_submitted_at") or user.get("created_at")
        if isinstance(start, datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            available_at = start + timedelta(days=delay_days)
            if datetime.now(timezone.utc) < available_at:
                return _render(
                    request, slug, dept, email=email,
                    error="Your post survey is not open yet. It becomes "
                          f"available on {available_at.strftime('%d %b %Y %H:%M')}.",
                    status_code=403,
                )

    # Grant post-survey access for this student, the same way a reminder email
    # does, so the post-survey gate lets them through.
    await db["users"].update_one(
        {"email": email},
        {"$set": {"post_link_at": datetime.now(timezone.utc), "post_link_dept": dept}},
    )

    # Greet them by name and show what is coming before handing over. The
    # Deeksharambh orientation comes first when they still owe it; the post
    # survey follows straight after it.
    orientation_pending = not bool(user.get("orientation_submitted"))
    name = (user.get("name") or "").strip()
    welcome = {
        "name": name or "there",
        "first_name": name.split(" ")[0] if name else "there",
        "program": (user.get("program") or "").strip() or dept or NO_DEPARTMENT,
        "next_url": "/orientation" if orientation_pending else "/survey/post",
        "orientation_pending": orientation_pending,
        "pre_at": _fmt_when(user.get("pre_submitted_at")),
    }

    response = _render(request, slug, dept, email=email, welcome=welcome)
    issue_session(response, email, user.get("name", ""))
    issue_csrf(response, make_csrf_token())
    return response
