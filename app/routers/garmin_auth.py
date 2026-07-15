import asyncio
import logging
import secrets
import time
import threading

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.ratelimit import allow
from app.routers.login import current_user_id
from app.services import garmin as garmin_svc

router = APIRouter(prefix="/auth/garmin", tags=["garmin-auth"])

# ── In-memory MFA pending store ───────────────────────────────────────────────
# Keyed by a short-lived nonce stored in the session. Credentials and the
# in-flight Garmin client object never touch the session cookie.
# NOTE: this store is process-local. Run uvicorn with a single worker only
# (the default); multiple workers will cause MFA to fail with "session expired"
# when the /mfa request lands on a different worker than /connect.

_MFA_TTL = 300  # seconds
_mfa_store: dict[str, dict] = {}
_mfa_lock = threading.Lock()


def _store_mfa(client, client_state) -> str:
    nonce = secrets.token_urlsafe(16)
    with _mfa_lock:
        # Evict expired entries opportunistically
        now = time.monotonic()
        expired = [k for k, v in _mfa_store.items() if v["exp"] < now]
        for k in expired:
            del _mfa_store[k]
        _mfa_store[nonce] = {"client": client, "state": client_state, "exp": now + _MFA_TTL}
    return nonce


def _pop_mfa(nonce: str) -> dict | None:
    with _mfa_lock:
        entry = _mfa_store.pop(nonce, None)
    if entry and entry["exp"] >= time.monotonic():
        return entry
    return None


# ── Models ────────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    email: str
    password: str


class MfaRequest(BaseModel):
    mfa_code: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def status(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    return {"connected": garmin_svc.is_connected(db, user_id)}


@router.post("/connect")
async def connect(body: ConnectRequest, request: Request, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    # These endpoints relay credentials to Garmin — throttle per user + IP so an
    # invited account can't use the server as a credential-stuffing proxy.
    if not allow(request, bucket=f"garmin-connect:{user_id}", max_attempts=5, window_s=600):
        raise HTTPException(status_code=429, detail="Too many Garmin sign-in attempts. Please wait a few minutes and try again.")

    from garminconnect import Garmin, GarminConnectAuthenticationError

    client = Garmin(email=body.email, password=body.password, return_on_mfa=True)
    try:
        mfa_status, _ = await asyncio.to_thread(client.login)
    except GarminConnectAuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid Garmin email or password.")
    except Exception as e:
        msg = str(e)
        log.warning("Garmin login failed: %s", msg)
        if "429" in msg or "rate limit" in msg.lower():
            raise HTTPException(status_code=429, detail="Garmin is rate limiting sign-ins. Please wait and try again.")
        raise HTTPException(status_code=422, detail="Garmin login failed. Please try again.")

    if mfa_status is not None:
        nonce = _store_mfa(client, mfa_status)
        request.session["garmin_mfa_nonce"] = nonce
        return JSONResponse({"needs_mfa": True})

    garmin_svc.save_tokens(db, user_id, client)
    return {"connected": True}


@router.post("/connect/mfa")
async def connect_mfa(body: MfaRequest, request: Request, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    if not allow(request, bucket=f"garmin-mfa:{user_id}", max_attempts=5, window_s=600):
        raise HTTPException(status_code=429, detail="Too many MFA attempts. Please wait a few minutes and try again.")

    nonce = request.session.get("garmin_mfa_nonce")
    if not nonce:
        raise HTTPException(status_code=400, detail="No pending MFA session — connect first")

    entry = _pop_mfa(nonce)
    if not entry:
        raise HTTPException(status_code=400, detail="MFA session expired — please connect again")

    from garminconnect import GarminConnectAuthenticationError

    client = entry["client"]
    try:
        await asyncio.to_thread(client.resume_login, entry["state"], body.mfa_code)
    except GarminConnectAuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid MFA code.")
    except Exception as e:
        log.warning("Garmin MFA failed: %s", e)
        raise HTTPException(status_code=422, detail="Garmin MFA failed. Please try again.")

    request.session.pop("garmin_mfa_nonce", None)
    garmin_svc.save_tokens(db, user_id, client)
    return {"connected": True}


@router.post("/disconnect")
async def disconnect(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    garmin_svc.delete_tokens(db, user_id)
    return {"disconnected": True}
