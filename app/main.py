"""
FastAPI entrypoint — Unified AI Survey + Orientation (Deeksharambh)

Routes:
  /                       → AI Survey landing (name + email + program)
  /survey/pre             → HACRI-E baseline assessment
  /survey/post            → HACRI-E post-workshop survey
  /results/<slug>         → Personal results + JAIN Star
  /deeksharambh           → Deeksharambh landing (name + email + program)
  /orientation            → Deeksharambh form
  <ADMIN_PATH>/survey     → Survey admin dashboard (ADMIN_PATH, not /admin)
  <ADMIN_PATH>/orientation→ Orientation admin dashboard

Run:
  python run.py              (dev, Windows)
  python -m uvicorn app.main:app --reload    (dev, any)
  gunicorn app.main:app -c gunicorn.conf.py  (prod)
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from app import db
from app.routes import (
    admin, landing, orientation, orientation_landing, post_link,
    results, shared_analysis, surveys,
)
from app.settings import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hacri-e")

# Create generated dirs BEFORE StaticFiles mounts them (required at module load time)
_gen = settings.generated_root
for _d in [_gen, _gen / "users", _gen / "histograms", _gen / "scorecards"]:
    _d.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting HACRI-E + Deeksharambh app...")
    await db.init_indexes()
    log.info("Mongo indexes ready.")

    # Say out loud what the mail configuration is going to do. A .env written
    # with a hosting panel's variable names, or one that still has
    # EMAIL_DRY_RUN=true, leaves the app looking completely healthy while every
    # message goes to a log file instead of a student. This line is how that
    # gets noticed at deploy time rather than weeks later.
    from app import emailer
    accounts = emailer.smtp_accounts()
    if emailer._is_dry_run():
        log.warning(
            "MAIL IS OFF — nothing will be delivered. %s",
            "EMAIL_DRY_RUN is true; set it to false to send."
            if settings.smtp_host else
            "No SMTP_HOST is set. If your .env uses SMTP_SERVER / SMTP_EMAIL / "
            "SMTP_PASSWORD those are read as aliases, so check for a typo.")
    else:
        log.info("Mail is on via %s%s.",
                 accounts[0]["hostname"],
                 f", falling back to {accounts[1]['hostname']}"
                 if len(accounts) > 1 else " with no fallback configured")
    
    # Start auto-reminder background task
    import asyncio
    from app.routes.admin import run_auto_reminder_worker
    worker_task = asyncio.create_task(run_auto_reminder_worker())
    
    yield
    log.info("Shutting down...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await db.close_client()


app = FastAPI(
    title="HACRI-E Survey + Deeksharambh Orientation",
    version="3.0.0",
    lifespan=lifespan,
)

# ── The admin portal answers somewhere else ──────────────────────────────────
#
# Every install of everything has an /admin/login, which is why the sign-in log
# fills up with addresses that have never done anything but knock on it. The
# admin's own door is moved to ADMIN_PATH and the well-known one is closed:
#
#   <ADMIN_PATH>/login   → the login page, rewritten internally to /admin/login
#   /admin/login         → 404, exactly like a site that has no admin at all
#
# Only the pages a person opens move. Everything behind them — the JSON API,
# the exports, signing out — stays at /admin/... where the dashboard's own
# scripts already ask for it, and stays locked behind the session cookie. A
# scanner that guesses those gets 403 and has nothing to guess *at*: there is
# no password to try anywhere but the door it cannot find.
HIDDEN_ADMIN_PAGES = frozenset({
    "/admin",
    "/admin/",
    "/admin/login",
    "/admin/survey",
    "/admin/orientation",
    "/admin/survey/login",
    "/admin/orientation/login",
    "/admin/survey/request-otp",
})


@app.middleware("http")
async def admin_door(request: Request, call_next):
    secret = settings.admin_path
    path = request.scope.get("path", "")

    if secret != "/admin" and (path == secret or path.startswith(secret + "/")):
        # Behind the secret door the app is its ordinary self: rewrite the path
        # and let the normal /admin routes answer it.
        inner = path[len(secret):] or "/"
        request.scope["path"] = "/admin" + ("" if inner == "/" else inner)
        return await call_next(request)

    if secret != "/admin" and path.rstrip("/") in HIDDEN_ADMIN_PAGES:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return await call_next(request)


BASE_DIR  = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# Every link back to a page that moved is built from this, so changing
# ADMIN_PATH moves the portal without leaving a link pointing at the old door.
templates.env.globals["admin_path"] = settings.admin_path
# The department list is the same everywhere it is offered, so expose it to
# every template instead of threading it through each route's context.
from app.departments import DEPARTMENTS  # noqa: E402
templates.env.globals["departments"] = DEPARTMENTS


def asset(path: str) -> str:
    """A /static URL stamped with the file's modification time.

    Without this a browser keeps the previous stylesheet or script after a
    deploy and the page renders with last week's code — invisible from the
    server side and maddening to debug. The stamp changes when the file does,
    so a pull is enough to bust the cache.
    """
    relative = path.split("?", 1)[0].lstrip("/")
    if relative.startswith("static/"):
        relative = relative[len("static/"):]
    try:
        stamp = int((BASE_DIR / "static" / relative).stat().st_mtime)
    except OSError:
        return path
    return f"{path}?v={stamp}"


templates.env.globals["asset"] = asset
app.state.templates = templates

app.mount("/static",    StaticFiles(directory=str(BASE_DIR / "static")),         name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Browsers ask for this on every page whether or not anyone linked it, so
    without it every single page view logged a 404."""
    from fastapi.responses import FileResponse, Response

    icon = BASE_DIR / "static" / "logosmall.png"
    if icon.exists():
        return FileResponse(icon, media_type="image/png")
    return Response(status_code=204)
app.mount("/generated", StaticFiles(directory=str(_gen.resolve())),               name="generated")

app.include_router(landing.router,             tags=["landing"])
app.include_router(orientation_landing.router, tags=["orientation-landing"])
app.include_router(surveys.router,             tags=["surveys"])
app.include_router(post_link.router,           tags=["post-link"])
app.include_router(results.router,             tags=["results"])
app.include_router(orientation.router,         tags=["orientation"])
app.include_router(admin.router,               tags=["admin"])
app.include_router(shared_analysis.router,     tags=["shared-analysis"])



@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(url="/", status_code=303)
    if exc.status_code == status.HTTP_302_FOUND:
        return RedirectResponse(url=exc.headers.get("Location", "/"), status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def val_exc(request: Request, exc: RequestValidationError):
    log.warning("Validation error %s: %s", request.url.path, exc.errors())
    if request.method == "POST":
        return RedirectResponse(url=request.url.path, status_code=303)
    return JSONResponse({"detail": exc.errors()}, status_code=422)
