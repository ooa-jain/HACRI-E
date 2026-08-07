"""
post_link.py — Department-wise post-survey entry links.

The admin generates one link per department in the admin portal:

    GET  /post/<dept-slug>   → page asking the student for their email
    POST /post/<dept-slug>   → check the email, then open the post survey

A student who opens the link types the email they registered with. If that
email belongs to the link's department AND already has a completed baseline
(pre) survey, a session is issued and the post survey opens straight away —
no landing page, no re-registration. Everything else (wrong department, no
baseline yet, unknown email) is answered with a plain message on the same page.

`/post/all` works the same way but accepts any department.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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


async def resolve_dept(slug: str) -> str:
    """Name the department a slug refers to.

    Returns "" for the all-departments link. Otherwise the department name as
    it is spelled on the student records, falling back to a readable form of
    the slug when no student carries that department (yet).
    """
    slug = (slug or "").strip().lower()
    if slug == ALL_SLUG:
        return ""
    if slug == NO_DEPT_SLUG:
        return NO_DEPARTMENT
    for dept in await list_departments():
        if dept_slug(dept) == slug:
            return dept
    return slug.replace("-", " ").title()


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
            email: str = "", status_code: int = 200):
    return request.app.state.templates.TemplateResponse(
        request,
        "post_entry.html",
        {
            "dept": dept,
            "dept_label": dept or "All Departments",
            "slug": slug,
            "error": error,
            "email": email,
        },
        status_code=status_code,
    )


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

    response = RedirectResponse(url="/survey/post", status_code=303)
    issue_session(response, email, user.get("name", ""))
    issue_csrf(response, make_csrf_token())
    return response
