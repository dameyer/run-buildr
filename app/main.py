import logging
import logging.handlers
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings

# ── File logging ──────────────────────────────────────────────────────────────
_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    _log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("uvicorn.error").addHandler(_handler)
logging.getLogger("uvicorn.access").addHandler(_handler)
from app.database import Base, engine, get_db
from app.routers import analysis, auth, garmin_auth, workouts, login, users
from app.routers.login import _LoginRedirect, session_user
from app.templates_env import templates

CACHE_BUSTER = str(int(time.time()))
templates.env.globals["cache_buster"] = CACHE_BUSTER

Base.metadata.create_all(bind=engine)

# Additive migrations for SQLite (safe to run repeatedly)
with engine.connect() as _conn:
    from sqlalchemy import exc as _exc
    from sqlalchemy import text as _text
    for _stmt in [
        "ALTER TABLE saved_workouts ADD COLUMN garmin_workout_id VARCHAR",
        "ALTER TABLE saved_workouts ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1",
    ]:
        try:
            _conn.execute(_text(_stmt))
            _conn.commit()
        except _exc.OperationalError:
            _conn.rollback()  # column already exists — safe to ignore

app = FastAPI(title="Run Builder")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.https_only,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


app.include_router(login.router)
app.include_router(auth.router)
app.include_router(garmin_auth.router)
app.include_router(workouts.router)
app.include_router(users.router)
app.include_router(analysis.router)


@app.exception_handler(_LoginRedirect)
async def login_redirect_handler(request: Request, exc: _LoginRedirect):
    return RedirectResponse("/login", status_code=302)


@app.get("/")
async def index(request: Request, db: Session = Depends(get_db)):
    if not session_user(request, db):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "editor.html")


@app.get("/analysis")
async def analysis_page(request: Request, db: Session = Depends(get_db)):
    if not session_user(request, db):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "analysis.html")
