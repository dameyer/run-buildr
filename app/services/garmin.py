import json
from datetime import datetime
from app.utils import utcnow

from garminconnect import Garmin
from sqlalchemy.orm import Session

from app.models import GarminToken
from app.schemas import Plan, TriggerType, IntensityType
from app.services.crypto import decrypt, encrypt


# ── Token persistence ─────────────────────────────────────────────────────────

def get_client(db: Session, user_id: int) -> Garmin | None:
    row = db.query(GarminToken).filter(GarminToken.user_id == user_id).first()
    if not row:
        return None
    try:
        client = Garmin()
        client.client.loads(decrypt(row.tokens_json))  # direct load, no network calls
        return client
    except Exception:
        return None


def save_tokens(db: Session, user_id: int, client: Garmin) -> None:
    tokens_json = encrypt(client.client.dumps())
    row = db.query(GarminToken).filter(GarminToken.user_id == user_id).first()
    if row:
        row.tokens_json = tokens_json
        row.updated_at = utcnow()
    else:
        row = GarminToken(user_id=user_id, tokens_json=tokens_json)
        db.add(row)
    db.commit()


def delete_tokens(db: Session, user_id: int) -> None:
    db.query(GarminToken).filter(GarminToken.user_id == user_id).delete()
    db.commit()


def is_connected(db: Session, user_id: int) -> bool:
    return db.query(GarminToken).filter(GarminToken.user_id == user_id).first() is not None


METERS_PER_MILE = 1609.344

# ── Plan → Garmin workout JSON ────────────────────────────────────────────────

_SPORT = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

# stepTypeId from garminconnect/workout.py: WARMUP=1,COOLDOWN=2,INTERVAL=3,RECOVERY=4,REST=5,REPEAT=6
_INTENSITY_TO_STEP_TYPE = {
    IntensityType.WU:      {"stepTypeId": 1, "stepTypeKey": "warmup",   "displayOrder": 1},
    IntensityType.CD:      {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    IntensityType.RECOVER: {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    IntensityType.REST:    {"stepTypeId": 5, "stepTypeKey": "rest",     "displayOrder": 5},
}
_DEFAULT_STEP_TYPE = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}

# endCondition types: DISTANCE=1, TIME=2, ITERATIONS=7
_END_DISTANCE = {"conditionTypeId": 3, "conditionTypeKey": "distance",   "displayOrder": 3, "displayable": True}
_END_TIME      = {"conditionTypeId": 2, "conditionTypeKey": "time",       "displayOrder": 2, "displayable": True}
_END_ITERS     = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}

_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_PACE_TARGET_TYPE = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}


def _end_condition(trigger: TriggerType) -> dict:
    if trigger == TriggerType.DISTANCE:
        return _END_DISTANCE
    return _END_TIME


def _pace_target(speed_ms: float, window_s: float) -> tuple[dict, float, float] | None:
    """Returns (targetType, targetValueOne, targetValueTwo) in m/s, or None."""
    if not speed_ms or speed_ms <= 0:
        return None
    center_spm = METERS_PER_MILE / speed_ms           # sec/mile at center
    if center_spm <= window_s:
        return None                             # window wider than pace, skip target
    slow_ms = METERS_PER_MILE / (center_spm + window_s)   # slower → lower m/s
    fast_ms = METERS_PER_MILE / (center_spm - window_s)   # faster → higher m/s
    return _PACE_TARGET_TYPE, round(slow_ms, 5), round(fast_ms, 5)


def _convert_steps(intervals, window_s: float, order_start: int = 1, child_step_id: int | None = None) -> list[dict]:
    steps = []
    order = order_start

    for iv in intervals:
        trigger = iv.exit_trigger_type

        if trigger == TriggerType.REPEAT:
            repeat_order = order
            iters = int(iv.exit_trigger_value)
            children = _convert_steps(iv.intervals or [], window_s, order_start=1, child_step_id=repeat_order)
            repeat_step: dict = {
                "type":               "RepeatGroupDTO",
                "stepOrder":          repeat_order,
                "stepType":           {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                "numberOfIterations": iters,
                "workoutSteps":       children,
                "endCondition":       _END_ITERS,
                "endConditionValue":  float(iters),
                "smartRepeat":        False,
            }
            if child_step_id is not None:
                repeat_step["childStepId"] = child_step_id
            steps.append(repeat_step)
            order += 1
            continue

        step_type = _INTENSITY_TO_STEP_TYPE.get(iv.intensity_type, _DEFAULT_STEP_TYPE)

        step: dict = {
            "type":               "ExecutableStepDTO",
            "stepOrder":          order,
            "stepType":           step_type,
            "endCondition":       _end_condition(trigger),
            "endConditionValue":  float(iv.exit_trigger_value),
            "targetType":         _NO_TARGET,
        }
        if child_step_id is not None:
            step["childStepId"] = child_step_id

        speed_target = next(
            (t for t in (iv.targets or []) if t.type.value == "speed"),
            None,
        )
        if speed_target:
            center_ms = (speed_target.low + speed_target.high) / 2
            result = _pace_target(center_ms, window_s)
            if result:
                ttype, v1, v2 = result
                step["targetType"]       = ttype
                step["targetValueOne"]   = v1
                step["targetValueTwo"]   = v2

        steps.append(step)
        order += 1

    return steps


def plan_to_garmin(plan: Plan, window_s: float = 10.0) -> dict:
    steps = _convert_steps(plan.intervals, window_s)
    return {
        "workoutName": plan.header.name,
        "description": plan.header.description or "",
        "sportType":   _SPORT,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType":    _SPORT,
                "workoutSteps": steps,
            }
        ],
    }


# ── Push & schedule ───────────────────────────────────────────────────────────

def push_workout(client: Garmin, workout_json: dict) -> dict:
    return client.upload_workout(workout_json)


def schedule_workout(client: Garmin, workout_id: str, date_str: str) -> dict:
    return client.schedule_workout(workout_id, date_str)
