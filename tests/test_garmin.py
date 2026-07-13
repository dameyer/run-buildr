import pytest
from app.services.garmin import _pace_target, _convert_steps, METERS_PER_MILE
from app.schemas import Interval, TriggerType, IntensityType, Target, TargetType


# ── _pace_target ──────────────────────────────────────────────────────────────

def test_pace_target_returns_none_for_zero_speed():
    assert _pace_target(0.0, 10) is None


def test_pace_target_returns_none_for_negative_speed():
    assert _pace_target(-1.0, 10) is None


def test_pace_target_returns_none_when_window_exceeds_pace():
    # very slow pace: center_spm = 1609/0.5 = 3218 sec/mile, window=10 → ok
    # but if speed = 0.3 m/s → center_spm = 5364, window = 6000 → none
    assert _pace_target(0.3, 6000) is None


def test_pace_target_valid_returns_tuple():
    # 4 m/s ≈ 6:42/mile pace, window 10s
    result = _pace_target(4.0, 10)
    assert result is not None
    target_type, slow_ms, fast_ms = result
    assert slow_ms < 4.0 < fast_ms  # slow pace = lower m/s, fast pace = higher m/s
    assert target_type["workoutTargetTypeKey"] == "pace.zone"


def test_pace_target_slow_lower_than_fast():
    _, slow_ms, fast_ms = _pace_target(3.5, 15)
    assert slow_ms < fast_ms


def test_pace_target_values_rounded_to_5_decimals():
    _, slow_ms, fast_ms = _pace_target(4.0, 10)
    assert round(slow_ms, 5) == slow_ms
    assert round(fast_ms, 5) == fast_ms


# ── _convert_steps ────────────────────────────────────────────────────────────

def _time_interval(intensity=IntensityType.ACTIVE, secs=120, targets=None):
    return Interval(
        exit_trigger_type=TriggerType.TIME,
        exit_trigger_value=secs,
        intensity_type=intensity,
        targets=targets,
    )


def _distance_interval(meters=400):
    return Interval(
        exit_trigger_type=TriggerType.DISTANCE,
        exit_trigger_value=meters,
        intensity_type=IntensityType.ACTIVE,
    )


def _repeat_interval(count, children):
    return Interval(
        exit_trigger_type=TriggerType.REPEAT,
        exit_trigger_value=count,
        intervals=children,
    )


def test_simple_time_step_type():
    steps = _convert_steps([_time_interval()], window_s=10)
    assert len(steps) == 1
    assert steps[0]["type"] == "ExecutableStepDTO"
    assert steps[0]["endCondition"]["conditionTypeId"] == 2  # time
    assert steps[0]["endConditionValue"] == 120.0


def test_distance_step_uses_conditionTypeId_3():
    steps = _convert_steps([_distance_interval(400)], window_s=10)
    assert steps[0]["endCondition"]["conditionTypeId"] == 3  # distance
    assert steps[0]["endConditionValue"] == 400.0


def test_step_order_increments():
    steps = _convert_steps([_time_interval(), _time_interval()], window_s=10)
    assert steps[0]["stepOrder"] == 1
    assert steps[1]["stepOrder"] == 2


def test_warmup_gets_correct_step_type():
    steps = _convert_steps([_time_interval(intensity=IntensityType.WU)], window_s=10)
    assert steps[0]["stepType"]["stepTypeId"] == 1  # warmup


def test_cooldown_gets_correct_step_type():
    steps = _convert_steps([_time_interval(intensity=IntensityType.CD)], window_s=10)
    assert steps[0]["stepType"]["stepTypeId"] == 2  # cooldown


def test_repeat_group_structure():
    children = [_time_interval(IntensityType.ACTIVE, 120), _time_interval(IntensityType.RECOVER, 60)]
    steps = _convert_steps([_repeat_interval(4, children)], window_s=10)
    assert len(steps) == 1
    repeat = steps[0]
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 4
    assert len(repeat["workoutSteps"]) == 2


def test_repeat_children_have_child_step_id():
    children = [_time_interval(), _time_interval()]
    steps = _convert_steps([_time_interval(), _repeat_interval(3, children)], window_s=10)
    repeat = steps[1]
    parent_order = repeat["stepOrder"]
    for child in repeat["workoutSteps"]:
        assert child["childStepId"] == parent_order


def test_top_level_steps_have_no_child_step_id():
    steps = _convert_steps([_time_interval(), _time_interval()], window_s=10)
    for step in steps:
        assert "childStepId" not in step


def test_pace_target_applied_when_speed_target_present():
    target = Target(type=TargetType.SPEED, low=3.8, high=4.2)
    steps = _convert_steps([_time_interval(targets=[target])], window_s=10)
    step = steps[0]
    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert "targetValueOne" in step
    assert "targetValueTwo" in step


def test_no_target_when_no_speed():
    steps = _convert_steps([_time_interval()], window_s=10)
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "no.target"
