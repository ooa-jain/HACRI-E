"""
FastAPI entrypoint — Unified AI Survey + Orientation (Deeksharambh)

Routes:
  /                       → AI Survey landing (name + email + program)
  /survey/pre             → HACRI-E baseline assessment
  /survey/post            → HACRI-E post-workshop survey
  /results/<slug>         → Personal results + JAIN Star
  /deeksharambh           → Deeksharambh landing (name + email + program)
  /orientation            → Deeksharambh form
  /admin/survey           → Survey admin dashboard
  /admin/orientation      → Orientation admin dashboard

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
from app.routes import admin, landing, orientation, orientation_landing, results, surveys, shared_analysis
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

BASE_DIR  = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates = templates

app.mount("/static",    StaticFiles(directory=str(BASE_DIR / "static")),         name="static")
app.mount("/generated", StaticFiles(directory=str(_gen.resolve())),               name="generated")

app.include_router(landing.router,             tags=["landing"])
app.include_router(orientation_landing.router, tags=["orientation-landing"])
app.include_router(surveys.router,             tags=["surveys"])
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
