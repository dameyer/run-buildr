from fastapi import Depends, HTTPException
from garminconnect import Garmin
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.login import current_user_id
from app.services import garmin as garmin_svc
from app.services import wahoo
from app.services.wahoo import WahooTokenExpiredError


async def require_wahoo_token(
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> str:
    try:
        token = await wahoo.get_valid_token(db, user_id)
    except WahooTokenExpiredError:
        raise HTTPException(status_code=401, detail="Wahoo token expired. Visit /auth/wahoo to reconnect.")
    if not token:
        raise HTTPException(status_code=401, detail="Not connected to Wahoo. Visit /auth/wahoo to connect.")
    return token


def require_garmin_client(
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> Garmin:
    client = garmin_svc.get_client(db, user_id)
    if not client:
        raise HTTPException(status_code=401, detail="Not connected to Garmin. Visit /auth/garmin to connect.")
    return client
