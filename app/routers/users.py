import hmac

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.config import settings
from app.database import get_db
from app.models import User
from app.ratelimit import allow
from app.routers.login import _set_session, current_user_id, require_admin, require_auth, session_user
from app.templates_env import templates

router = APIRouter(tags=["users"])


@router.get("/register")
async def register_page(request: Request, db: Session = Depends(get_db)):
    if session_user(request, db):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "register.html", {"error": None})


@router.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    invite_code: str = Form(...),
    db: Session = Depends(get_db),
):
    if not allow(request, bucket="register", max_attempts=5, window_s=600):
        return templates.TemplateResponse(request, "register.html", {"error": "Too many attempts. Please wait a few minutes and try again."})
    if not hmac.compare_digest(invite_code, settings.invite_code):
        return templates.TemplateResponse(request, "register.html", {"error": "Invalid invite code"})
    if len(username) < 3:
        return templates.TemplateResponse(request, "register.html", {"error": "Username must be at least 3 characters"})
    if len(password) < 8:
        return templates.TemplateResponse(request, "register.html", {"error": "Password must be at least 8 characters"})
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse(request, "register.html", {"error": "Username already taken"})

    is_admin = db.query(User).count() == 0  # first user becomes admin
    user = User(username=username, hashed_password=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)

    _set_session(request, user)
    return RedirectResponse("/", status_code=302)


@router.get("/admin")
async def admin_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse(request, "admin.html", {"users": users, "error": None})


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    request: Request,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        return RedirectResponse("/admin", status_code=302)
    if len(new_password) < 8:
        users = db.query(User).order_by(User.created_at).all()
        return templates.TemplateResponse(request, "admin.html", {
            "users": users,
            "error": f"Password too short for {user.username} (min 8 chars)",
        })
    user.hashed_password = hash_password(new_password)
    user.session_version += 1  # kick the reset account out of all sessions
    db.commit()
    if user.id == request.session.get("user_id"):
        request.session["session_version"] = user.session_version  # keep this device signed in
    return RedirectResponse("/admin", status_code=302)


@router.post("/admin/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    if user_id == request.session["user_id"]:
        users = db.query(User).order_by(User.created_at).all()
        return templates.TemplateResponse(request, "admin.html", {
            "users": users,
            "error": "You cannot change your own admin status",
        })
    user = db.get(User, user_id)
    if user:
        user.is_admin = not user.is_admin
        db.commit()
    return RedirectResponse("/admin", status_code=302)


@router.get("/calendar")
async def calendar_page(request: Request, db: Session = Depends(get_db)):
    require_auth(request, db)
    return templates.TemplateResponse(request, "calendar.html", {})


@router.post("/account/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
):
    user = db.get(User, user_id)
    if not user or not verify_password(current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user.hashed_password = hash_password(new_password)
    user.session_version += 1  # invalidate sessions on every other device
    db.commit()
    request.session["session_version"] = user.session_version  # keep this device signed in
    return {"success": True}
