from datetime import datetime, timedelta
from app.utils import utcnow

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import WahooToken
from app.schemas import Plan
from app.services.crypto import InvalidToken, decrypt, encrypt
from app.services.plan import plan_to_base64

# Single shared client — connection pooling across all Wahoo API calls
_http = httpx.AsyncClient(base_url=settings.wahoo_api_base, timeout=30.0)


class WahooAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Wahoo API {status_code}: {body}")


class WahooTokenExpiredError(Exception):
    pass


async def get_valid_token(db: Session, user_id: int) -> str | None:
    token = db.query(WahooToken).filter(WahooToken.user_id == user_id).order_by(WahooToken.id.desc()).first()
    if not token:
        return None
    try:
        if token.expires_at <= utcnow():
            token = await _refresh_token(token, db)
        return decrypt(token.access_token)
    except InvalidToken:
        return None  # legacy/undecryptable row — treat as not connected, forces reconnect


async def _refresh_token(token: WahooToken, db: Session) -> WahooToken:
    resp = await _http.post(settings.wahoo_token_url, data={
        "grant_type": "refresh_token",
        "refresh_token": decrypt(token.refresh_token),
        "client_id": settings.wahoo_client_id,
        "client_secret": settings.wahoo_client_secret,
    })
    if not resp.is_success:
        raise WahooTokenExpiredError()
    data = resp.json()

    token.access_token = encrypt(data["access_token"])
    token.refresh_token = encrypt(data.get("refresh_token")) if data.get("refresh_token") else token.refresh_token
    token.expires_at = utcnow() + timedelta(seconds=data["expires_in"])
    db.commit()
    db.refresh(token)
    return token


async def push_plan(plan: Plan, access_token: str) -> dict:
    resp = await _http.post(
        "/v1/plans",
        headers={"Authorization": f"Bearer {access_token}"},
        data={
            "plan[file]": plan_to_base64(plan),
            "plan[filename]": "workout.json",
            "plan[external_id]": f"kickr-{int(utcnow().timestamp())}",
            "plan[provider_updated_at]": utcnow().isoformat() + "Z",
        },
    )
    if not resp.is_success:
        raise WahooAPIError(resp.status_code, resp.text)
    return resp.json()


async def push_workout(plan_id: str, plan: Plan, scheduled_at: str, access_token: str) -> dict:
    resp = await _http.post(
        "/v1/workouts",
        headers={"Authorization": f"Bearer {access_token}"},
        data={
            "workout[name]": plan.header.name,
            "workout[workout_token]": f"kickr-{int(utcnow().timestamp())}",
            "workout[workout_type_id]": int(plan.header.workout_type_family),
            "workout[starts]": scheduled_at,
            "workout[minutes]": (plan.header.duration_s or 0) // 60,
            "workout[plan_id]": plan_id,
        },
    )
    if not resp.is_success:
        raise WahooAPIError(resp.status_code, resp.text)
    return resp.json()


async def list_workouts(access_token: str, page: int = 1, per_page: int = 10) -> dict:
    resp = await _http.get(
        "/v1/workouts",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"page": page, "per_page": per_page},
    )
    if not resp.is_success:
        raise WahooAPIError(resp.status_code, resp.text)
    return resp.json()


async def get_workout(workout_id: str, access_token: str) -> dict:
    resp = await _http.get(
        f"/v1/workouts/{workout_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not resp.is_success:
        raise WahooAPIError(resp.status_code, resp.text)
    return resp.json()


async def delete_workout(workout_id: str, access_token: str) -> None:
    resp = await _http.delete(
        f"/v1/workouts/{workout_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not resp.is_success:
        raise WahooAPIError(resp.status_code, resp.text)
