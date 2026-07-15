from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from enum import IntEnum, Enum


class WorkoutTypeFamily(IntEnum):
    BIKING = 0
    RUNNING = 1


class WorkoutTypeLocation(IntEnum):
    INDOOR = 0
    OUTDOOR = 1


class TriggerType(str, Enum):
    TIME = "time"
    DISTANCE = "distance"
    KJ = "kj"
    REPEAT = "repeat"


class IntensityType(str, Enum):
    ACTIVE = "active"
    WU = "wu"
    TEMPO = "tempo"
    LT = "lt"
    MAP = "map"
    AC = "ac"
    NM = "nm"
    FTP = "ftp"
    CD = "cd"
    RECOVER = "recover"
    REST = "rest"


class TargetType(str, Enum):
    RPM = "rpm"
    RPE = "rpe"
    WATTS = "watts"
    HR = "hr"
    SPEED = "speed"
    FTP = "ftp"
    MAP = "map"
    AC = "ac"
    NM = "nm"
    THRESHOLD_HR = "threshold_hr"
    MAX_HR = "max_hr"
    THRESHOLD_SPEED = "threshold_speed"


class ControlType(str, Enum):
    GRADE = "grade"


class Target(BaseModel):
    type: TargetType
    low: float = Field(ge=0, le=100_000)
    high: float = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def high_gte_low(self) -> Target:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self


class Control(BaseModel):
    type: ControlType
    value: float = Field(ge=-100, le=100)  # grade is decimal (1% = 0.01)


# Sanity caps per trigger type — these flow straight to Wahoo/Garmin devices.
_MAX_TRIGGER_VALUE = {
    TriggerType.TIME: 86_400.0,      # 24 h, seconds
    TriggerType.DISTANCE: 200_000.0, # 200 km, meters
    TriggerType.KJ: 100_000.0,
    TriggerType.REPEAT: 100.0,       # iterations
}


class Interval(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    exit_trigger_type: TriggerType
    exit_trigger_value: float = Field(gt=0)
    intensity_type: Optional[IntensityType] = None
    targets: Optional[List[Target]] = None
    controls: Optional[List[Control]] = None
    intervals: Optional[List[Interval]] = None

    @model_validator(mode="after")
    def validate_interval(self) -> Interval:
        if self.exit_trigger_value > _MAX_TRIGGER_VALUE[self.exit_trigger_type]:
            raise ValueError(
                f'exit_trigger_value too large for "{self.exit_trigger_type.value}" '
                f"(max {_MAX_TRIGGER_VALUE[self.exit_trigger_type]:g})"
            )
        if self.exit_trigger_type == TriggerType.REPEAT:
            if self.exit_trigger_value != int(self.exit_trigger_value):
                raise ValueError("repeat count must be a whole number")
            if self.targets is not None:
                raise ValueError('targets not valid when exit_trigger_type is "repeat"')
            if not self.intervals:
                raise ValueError('intervals required when exit_trigger_type is "repeat"')
        return self


Interval.model_rebuild()


class PlanHeader(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = "1.0.0"
    description: str = Field("", max_length=2000)
    duration_s: Optional[int] = None
    distance_m: Optional[int] = None
    workout_type_family: WorkoutTypeFamily = WorkoutTypeFamily.RUNNING
    workout_type_location: WorkoutTypeLocation = WorkoutTypeLocation.INDOOR
    ftp: Optional[int] = None
    map: Optional[int] = None
    ac: Optional[int] = None
    nm: Optional[int] = None
    threshold_hr: Optional[int] = None
    max_hr: Optional[int] = None
    threshold_speed: Optional[float] = None


_MAX_NESTING_DEPTH = 10
_MAX_TOTAL_STEPS = 500


class Plan(BaseModel):
    header: PlanHeader
    intervals: List[Interval]

    @model_validator(mode="after")
    def validate_size(self) -> Plan:
        # Iterative walk (no recursion): the converters in services/plan.py and
        # services/garmin.py recurse over this tree, so unbounded depth would
        # RecursionError into an unhandled 500.
        count = 0
        stack: list[tuple[Interval, int]] = [(iv, 1) for iv in self.intervals]
        while stack:
            iv, depth = stack.pop()
            count += 1
            if depth > _MAX_NESTING_DEPTH:
                raise ValueError(f"intervals nested deeper than {_MAX_NESTING_DEPTH} levels")
            if count > _MAX_TOTAL_STEPS:
                raise ValueError(f"plan has more than {_MAX_TOTAL_STEPS} steps")
            for child in iv.intervals or []:
                stack.append((child, depth + 1))
        return self


class PushWorkoutRequest(BaseModel):
    plan: Plan
    scheduled_at: Optional[str] = None


class PushGarminRequest(BaseModel):
    plan: Plan
    pace_window_s: float = Field(10.0, gt=0, le=120)
    scheduled_at: Optional[str] = None
