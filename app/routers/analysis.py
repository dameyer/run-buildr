import asyncio
import io
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from garminconnect import Garmin

log = logging.getLogger(__name__)

from app.dependencies import require_garmin_client, require_wahoo_token
from app.services.garmin import METERS_PER_MILE
from app.services import wahoo
from app.services.wahoo import WahooAPIError

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/workouts")
async def list_completed(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    access_token: str = Depends(require_wahoo_token),
):
    try:
        data = await wahoo.list_workouts(access_token, page=page, per_page=per_page)
    except WahooAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body)

    completed = [w for w in data.get("workouts", []) if w.get("workout_summary")]
    return {"workouts": completed, "total": len(completed)}


@router.get("/fit/{wahoo_workout_id}")
async def fit_data(wahoo_workout_id: str, access_token: str = Depends(require_wahoo_token)):
    try:
        workout = await wahoo.get_workout(wahoo_workout_id, access_token)
    except WahooAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body)

    fit_url = (workout.get("workout_summary") or {}).get("file", {}).get("url")
    if not fit_url:
        raise HTTPException(status_code=404, detail="No FIT file available for this workout")

    async with httpx.AsyncClient() as client:
        resp = await client.get(fit_url, follow_redirects=True, timeout=30)
        if not resp.is_success:
            raise HTTPException(status_code=502, detail="Failed to download FIT file")
        fit_bytes = resp.content

    result = _parse_fit(fit_bytes, workout)
    result["raw"] = workout
    return result


@router.get("/garmin/activities")
async def garmin_activities(
    start: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    client: Garmin = Depends(require_garmin_client),
):
    try:
        activities = await asyncio.to_thread(client.get_activities, start=start, limit=limit, activitytype="running")
    except Exception:
        log.exception("Garmin get_activities failed")
        raise HTTPException(status_code=422, detail="Garmin request failed. Please try again.")

    def _is_outdoor(a: dict) -> bool:
        type_key = (a.get("activityType") or {}).get("typeKey", "")
        return "treadmill" not in type_key.lower()

    return {"activities": [a for a in activities if _is_outdoor(a)]}


@router.get("/garmin/fit/{activity_id}")
async def garmin_fit(
    activity_id: str,
    name: str = "",
    client: Garmin = Depends(require_garmin_client),
):
    try:
        zip_bytes = await asyncio.to_thread(client.download_activity, activity_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL)
    except Exception:
        log.exception("Garmin download_activity failed for %s", activity_id)
        raise HTTPException(status_code=422, detail="Garmin download failed. Please try again.")

    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            fit_name = next((n for n in zf.namelist() if n.lower().endswith(".fit")), None)
            if not fit_name:
                raise HTTPException(status_code=422, detail="No FIT file found in Garmin download")
            fit_bytes = zf.read(fit_name)
    except zipfile.BadZipFile:
        # Some activities return raw FIT directly
        fit_bytes = zip_bytes

    workout = {"name": name or "", "id": activity_id}
    result = _parse_fit(fit_bytes, workout)
    try:
        result["raw"] = await asyncio.to_thread(client.get_activity, activity_id)
    except Exception:
        log.exception("Garmin get_activity failed for %s", activity_id)
        result["raw"] = {"activityId": activity_id, "note": "Raw activity detail unavailable"}
    return result


def _parse_fit(fit_bytes: bytes, workout: dict) -> dict:
    import fitparse

    fit = fitparse.FitFile(io.BytesIO(fit_bytes))

    records = []
    laps = []

    for msg in fit.get_messages():
        if msg.name == "record":
            row = {}
            for f in msg.fields:
                row[f.name] = f.value
            t = row.get("timestamp")
            if t is not None:
                records.append(row)
        elif msg.name == "lap":
            lap = {}
            for f in msg.fields:
                lap[f.name] = f.value
            laps.append(lap)

    if not records:
        return {"records": [], "laps": [], "interval_markers": [], "meta": {}}

    # Build active-time axis: cap inter-record gap at 3s so pauses don't stretch the chart
    _active_t = 0.0
    _active_times = [0.0]
    for i in range(1, len(records)):
        try:
            dt = (records[i]["timestamp"] - records[i-1]["timestamp"]).total_seconds()
        except Exception:
            dt = 1.0
        _active_t += min(dt, 3.0)
        _active_times.append(_active_t)

    def to_elapsed(idx):
        return _active_times[idx] if idx < len(_active_times) else None

    def safe(v):
        if v is None:
            return None
        try:
            float(v)
            return v
        except (TypeError, ValueError):
            return str(v)

    MIN_SPEED_MS = 0.5  # below this (~1.1 mph) treat as stopped — avoids GPS-noise outliers

    out_records = []
    for _idx, row in enumerate(records):
        speed = row.get("enhanced_speed") or row.get("speed")
        cadence = row.get("cadence")
        moving = speed and speed >= MIN_SPEED_MS
        pace_mi = round(METERS_PER_MILE / speed, 2) if moving else None
        pace_km = round(1000.0 / speed, 2) if moving else None
        stride = round(speed / (cadence / 60), 3) if (moving and cadence and cadence > 0) else None
        elev = row.get("enhanced_altitude") or row.get("altitude")
        out_records.append({
            "t": to_elapsed(_idx),
            "speed": safe(speed),
            "pace": pace_mi,
            "pace_km": pace_km,
            "cadence": safe(cadence),
            "vo": safe(row.get("vertical_oscillation")),
            "stance": safe(row.get("stance_time")),
            "grade": safe(row.get("grade")),
            "distance": safe(row.get("distance")),
            "stride": stride,
            "elevation": round(float(elev), 1) if elev is not None else None,
            "heart_rate": safe(row.get("heart_rate")),
            "form_power": safe(row.get("Form Power")),
            "leg_spring": safe(row.get("Leg Spring Stiffness")),
            "smoothness": safe(row.get("running_smoothness")),
            "air_power": safe(row.get("Air Power")),
            "effectiveness": safe(row.get("Running Effectiveness")),
        })

    out_laps = []
    lap_t = 0.0
    for lap in laps:
        duration = None
        te = lap.get("total_elapsed_time")
        tm = lap.get("total_moving_time")
        d = te if te is not None else tm
        if d is not None:
            try:
                duration = float(d)
            except (TypeError, ValueError):
                pass
        avg_speed = lap.get("enhanced_avg_speed") or lap.get("avg_speed")
        avg_cadence = lap.get("avg_running_cadence")
        out_laps.append({
            "start_t": lap_t,
            "duration": duration,
            "distance": safe(lap.get("total_distance")),
            "avg_pace": round(METERS_PER_MILE / float(avg_speed), 2) if avg_speed and float(avg_speed) > 0 else None,
            "avg_cadence": safe(avg_cadence),
            "avg_vo": safe(lap.get("avg_vertical_oscillation")),
            "avg_stance": safe(lap.get("avg_stance_time")),
            "avg_grade": safe(lap.get("avg_grade")),
            "ascent": safe(lap.get("total_ascent")),
            "descent": safe(lap.get("total_descent")),
        })
        if duration:
            lap_t += duration

    meta = {
        "name": workout.get("name", ""),
        "starts": workout.get("starts"),
        "minutes": workout.get("minutes"),
        "workout_id": workout.get("id"),
        "total_distance": (workout.get("workout_summary") or {}).get("total_distance"),
        "total_time": (workout.get("workout_summary") or {}).get("total_moving_time"),
    }

    return {"records": out_records, "laps": out_laps, "interval_markers": [], "meta": meta}
