import asyncio
import calendar as cal_module
from datetime import datetime
from app.utils import utcnow

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_garmin_client, require_wahoo_token
from app.models import SavedWorkout
from app.routers.login import current_user_id, is_admin, require_auth
from app.schemas import Plan, PushGarminRequest, PushWorkoutRequest
from app.services import garmin as garmin_svc
from app.services import wahoo
from app.services.wahoo import WahooAPIError

router = APIRouter(prefix="/workouts", tags=["workouts"])


def _parse_scheduled_at(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.rstrip("Z"))
    except ValueError:
        return None


def _save_workout(
    db: Session,
    *,
    user_id: int,
    plan: Plan,
    sched: datetime | None,
    wahoo_plan_id: str | None = None,
    wahoo_workout_id: str | None = None,
    garmin_workout_id: str | None = None,
) -> SavedWorkout:
    saved = SavedWorkout(
        user_id=user_id,
        name=plan.header.name,
        plan_json=plan.model_dump_json(),
        wahoo_plan_id=wahoo_plan_id,
        wahoo_workout_id=wahoo_workout_id,
        garmin_workout_id=garmin_workout_id,
        scheduled_at=sched,
        pushed_at=utcnow(),
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


@router.post("/validate")
async def validate(plan: Plan, _: int = Depends(current_user_id)):
    return {"valid": True}


@router.post("/push")
async def push(
    body: PushWorkoutRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
    access_token: str = Depends(require_wahoo_token),
):
    try:
        plan_data = await wahoo.push_plan(body.plan, access_token)
    except WahooAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=f"Wahoo /v1/plans error: {e.body}")

    plan_id = str(plan_data["id"])
    scheduled_at = body.scheduled_at or utcnow().isoformat() + "Z"

    try:
        workout_data = await wahoo.push_workout(plan_id, body.plan, scheduled_at, access_token)
    except WahooAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=f"Wahoo /v1/workouts error: {e.body}")

    saved = _save_workout(
        db,
        user_id=user_id,
        plan=body.plan,
        sched=_parse_scheduled_at(body.scheduled_at),
        wahoo_plan_id=plan_id,
        wahoo_workout_id=str(workout_data.get("id", "")),
    )
    return {"success": True, "local_id": saved.id, "plan_id": plan_id, "workout_id": workout_data.get("id")}


@router.get("/wahoo-raw")
async def wahoo_raw(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    access_token: str = Depends(require_wahoo_token),
):
    try:
        return await wahoo.list_workouts(access_token, page=page, per_page=per_page)
    except WahooAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body)


@router.get("/history")
async def history(
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
):
    admin = is_admin(db, user_id)
    query = db.query(SavedWorkout).filter(SavedWorkout.is_archived == False)
    if not admin:
        query = query.filter(SavedWorkout.user_id == user_id)

    rows = query.order_by(SavedWorkout.pushed_at.desc()).limit(20).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "wahoo_workout_id": r.wahoo_workout_id,
            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
            "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
            "plan_json": r.plan_json,
        }
        for r in rows
    ]


@router.get("/calendar")
async def calendar_data(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
):
    admin = is_admin(db, user_id)
    first = datetime(year, month, 1)
    last = datetime(year, month, cal_module.monthrange(year, month)[1], 23, 59, 59)

    query = db.query(SavedWorkout).filter(
        SavedWorkout.is_archived == False,
        or_(
            and_(SavedWorkout.scheduled_at >= first, SavedWorkout.scheduled_at <= last),
            and_(SavedWorkout.scheduled_at == None, SavedWorkout.pushed_at >= first, SavedWorkout.pushed_at <= last),
        )
    )
    if not admin:
        query = query.filter(SavedWorkout.user_id == user_id)

    rows = query.order_by(SavedWorkout.scheduled_at, SavedWorkout.pushed_at).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "scheduled_at": (r.scheduled_at or r.pushed_at).isoformat() if (r.scheduled_at or r.pushed_at) else None,
            "plan_json": r.plan_json,
        }
        for r in rows
    ]


@router.post("/push-garmin")
async def push_garmin(
    body: PushGarminRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
    client=Depends(require_garmin_client),
):
    workout_json = garmin_svc.plan_to_garmin(body.plan, window_s=body.pace_window_s)

    try:
        result = await asyncio.to_thread(garmin_svc.push_workout, client, workout_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Garmin error: {e}")

    garmin_id = str(result.get("workoutId", result.get("id", "")))

    # Schedule on the calendar so it syncs to the watch
    scheduled_date = None
    if garmin_id:
        sched_dt = _parse_scheduled_at(body.scheduled_at)
        scheduled_date = sched_dt.date().isoformat() if sched_dt else utcnow().date().isoformat()
        try:
            await asyncio.to_thread(garmin_svc.schedule_workout, client, garmin_id, scheduled_date)
        except Exception:
            pass  # scheduling failure shouldn't block the push response

    saved = _save_workout(
        db,
        user_id=user_id,
        plan=body.plan,
        sched=_parse_scheduled_at(body.scheduled_at),
        garmin_workout_id=garmin_id,
    )
    return {"success": True, "local_id": saved.id, "garmin_workout_id": garmin_id, "scheduled_date": scheduled_date}


@router.post("/{local_id}/archive")
async def archive_workout(
    local_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
):
    admin = is_admin(db, user_id)
    row = db.get(SavedWorkout, local_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workout not found")
    if not admin and row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your workout")

    row.is_archived = True
    db.commit()
    return {"success": True}
