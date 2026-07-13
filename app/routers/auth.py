import secrets
from datetime import timedelta
from app.utils import utcnow
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import WahooToken
from app.routers.login import current_user_id, require_auth, session_user
from app.services.crypto import encrypt

router = APIRouter(prefix="/auth/wahoo", tags=["auth"])

SCOPES = "user_read workouts_read workouts_write plans_read plans_write"


@router.get("")
async def login(request: Request, db: Session = Depends(get_db)):
    require_auth(request, db)
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = urlencode({
        "client_id": settings.wahoo_client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    })
    return RedirectResponse(f"{settings.wahoo_auth_url}?{params}")


@router.get("/callback")
async def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    request.session.pop("oauth_state", None)

    async with httpx.AsyncClient() as client:
        resp = await client.post(settings.wahoo_token_url, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.wahoo_client_id,
            "client_secret": settings.wahoo_client_secret,
            "redirect_uri": settings.redirect_uri,
        })
    if not resp.is_success:
        raise HTTPException(status_code=422, detail="Wahoo token exchange failed")
    data = resp.json()

    user = session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    db.query(WahooToken).filter(WahooToken.user_id == user.id).delete()
    db.add(WahooToken(
        user_id=user.id,
        access_token=encrypt(data["access_token"]),
        refresh_token=encrypt(data["refresh_token"]),
        expires_at=utcnow() + timedelta(seconds=data["expires_in"]),
        token_type=data.get("token_type", "Bearer"),
    ))
    db.commit()

    return RedirectResponse("/")


@router.get("/status")
async def status(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return {"connected": False}
    token = db.query(WahooToken).filter(WahooToken.user_id == user.id).order_by(WahooToken.id.desc()).first()
    return {"connected": token is not None}


@router.post("/disconnect")
async def disconnect(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    db.query(WahooToken).filter(WahooToken.user_id == user_id).delete()
    db.commit()
    return {"disconnected": True}
