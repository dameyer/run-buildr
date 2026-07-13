from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import verify_password
from app.database import get_db
from app.models import User
from app.ratelimit import allow
from app.templates_env import templates

router = APIRouter(tags=["login"])


class _LoginRedirect(Exception):
    pass


def session_user(request: Request, db: Session) -> User | None:
    """Return the logged-in User, or None if the session is missing or revoked.

    The session cookie carries a copy of ``users.session_version``; a mismatch
    means the account bumped it (logout, password change/reset), so every
    cookie issued before the bump is dead regardless of its signed expiry.
    """
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = db.get(User, uid)
    if not user or request.session.get("session_version") != user.session_version:
        request.session.clear()  # stale/revoked cookie — drop it
        return None
    return user


def _set_session(request: Request, user: User) -> None:
    request.session["user_id"] = user.id
    request.session["is_admin"] = user.is_admin
    request.session["session_version"] = user.session_version


def require_auth(request: Request, db: Session = Depends(get_db)):
    if not session_user(request, db):
        raise _LoginRedirect()


def current_user_id(request: Request, db: Session = Depends(get_db)) -> int:
    user = session_user(request, db)
    if not user:
        raise _LoginRedirect()
    return user.id


def is_admin(db: Session, user_id: int) -> bool:
    user = db.get(User, user_id)
    return bool(user and user.is_admin)


def require_admin(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        raise _LoginRedirect()
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/login")
async def login_page(request: Request, db: Session = Depends(get_db)):
    if session_user(request, db):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not allow(request, bucket="login", max_attempts=10, window_s=300):
        return templates.TemplateResponse(request, "login.html", {"error": "Too many attempts. Please wait a few minutes and try again."})
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid username or password"})
    _set_session(request, user)
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if user:
        user.session_version += 1  # sign out everywhere — revokes all outstanding cookies
        db.commit()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
