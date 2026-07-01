"""
Results page + CSV download + cohort (admin) + healthz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

from app import deps
from app.csv_export import scorecard_csv_bytes
from app.db import (
    STATUS_POST_DONE,
    get_db,
    get_post_fields,
    get_pre_fields,
    list_matched_users,
)
from app.deps import get_current_session
from app.scoring import delta, score_for_user
from app.settings import settings
from app.routes.landing import email_to_slug, slug_to_email

router = APIRouter()


@router.get("/results/{email_slug}", response_class=HTMLResponse)
async def results_get(
    request: Request,
    email_slug: str,
    hacri_session: str | None = Cookie(default=None),
):
    email = slug_to_email(email_slug)
    if not email:
        raise HTTPException(status_code=404, detail="Invalid results link.")

    db = get_db()
    user = await db["users"].find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Parse existing session if any
    session = None
    if hacri_session:
        session = deps._unsign(hacri_session)

    # Auto-login if session is missing or belongs to a different email
    if not session or session.get("email") != email:
        response = RedirectResponse(url=f"/results/{email_slug}", status_code=303)
        deps.issue_session(response, email, user.get("name", ""))
        return response

    if user.get("status") != STATUS_POST_DONE:
        # Pre done, post not yet — show a "preparing" page
        return request.app.state.templates.TemplateResponse(
            request,
            "results_pending.html",
            {"name": user.get("name") if user else ""},
        )

    pre_fields = await get_pre_fields(email) or {}
    post_fields = await get_post_fields(email) or {}
    deltas = delta(pre_fields, post_fields)

    user_png_path = settings.generated_root / "users" / f"{email}.png"
    h_dir = settings.generated_root / "histograms"
    csv_path = settings.generated_root / "scorecards" / f"{email}.csv"

    from datetime import datetime
    post_at = user.get("post_submitted_at")
    ts = int(post_at.timestamp()) if isinstance(post_at, datetime) else _now_epoch()

    return request.app.state.templates.TemplateResponse(
        request,
        "results.html",
        {
            "name": user.get("name", ""),
            "email": email,
            "deltas": deltas,
            "user_png_url": f"/generated/users/{email}.png?v={ts}" if user_png_path.exists() else None,
            "h1_url": f"/generated/histograms/histogram_H1_understanding_change.png" if (h_dir / "histogram_H1_understanding_change.png").exists() else None,
            "h2_url": f"/generated/histograms/histogram_H2_most_useful.png" if (h_dir / "histogram_H2_most_useful.png").exists() else None,
            "h3_url": f"/generated/histograms/histogram_H3_most_valuable.png" if (h_dir / "histogram_H3_most_valuable.png").exists() else None,
            "csv_url": f"/results/{email_slug}/scorecard.csv" if csv_path.exists() else None,
        },
    )


@router.get("/results/{email_slug}/scorecard.csv")
async def scorecard_csv(
    email_slug: str,
):
    email = slug_to_email(email_slug)
    if not email:
        raise HTTPException(status_code=404, detail="Invalid results link.")

    db = get_db()
    user = await db["users"].find_one({"email": email})
    if not user or user.get("status") != STATUS_POST_DONE:
        raise HTTPException(status_code=404, detail="Results not ready yet.")

    pre_fields = await get_pre_fields(email) or {}
    post_fields = await get_post_fields(email) or {}
    csv_bytes = scorecard_csv_bytes(user.get("name", ""), email, pre_fields, post_fields)
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="HACRI_E2_{email}.csv"'
        },
    )


@router.get("/admin/cohort.png")
async def admin_cohort(
    request: Request,
    background: BackgroundTasks,
    token: str = Query(default=""),
    force: int = Query(default=0),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    from app.routes.admin import _is_survey_admin
    is_authed = _is_survey_admin(request) or (settings.admin_token and token == settings.admin_token)
    if not is_authed:
        raise HTTPException(status_code=403, detail="Forbidden")

    matched = await list_matched_users(program=dept or None, ug_or_pg=ug_or_pg or None)
    
    import hashlib
    key_str = f"cohort_dept={dept or ''}&ug_or_pg={ug_or_pg or ''}"
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


@router.get("/admin/histograms.png")
async def admin_histograms(
    request: Request,
    background: BackgroundTasks,
    token: str = Query(default=""),
    force: int = Query(default=0),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    from app.routes.admin import _is_survey_admin
    is_authed = _is_survey_admin(request) or (settings.admin_token and token == settings.admin_token)
    if not is_authed:
        raise HTTPException(status_code=403, detail="Forbidden")

    matched = await list_matched_users(program=dept or None, ug_or_pg=ug_or_pg or None)
    
    import hashlib
    key_str = f"histograms_dept={dept or ''}&ug_or_pg={ug_or_pg or ''}"
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


@router.get("/admin/h1_histogram.png")
async def admin_h1_histogram(
    request: Request,
    background: BackgroundTasks,
    token: str = Query(default=""),
    force: int = Query(default=0),
    dept: str = Query(default=""),
    ug_or_pg: str = Query(default=""),
):
    from app.routes.admin import _is_survey_admin
    is_authed = _is_survey_admin(request) or (settings.admin_token and token == settings.admin_token)
    if not is_authed:
        raise HTTPException(status_code=403, detail="Forbidden")

    matched = await list_matched_users(program=dept or None, ug_or_pg=ug_or_pg or None)
    
    import hashlib
    key_str = f"h1_dept={dept or ''}&ug_or_pg={ug_or_pg or ''}"
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


@router.get("/healthz")
async def healthz():
    try:
        await get_db().command("ping")
        return {"status": "ok", "db": settings.mongodb_db}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


def _now_epoch() -> int:
    from time import time
    return int(time())