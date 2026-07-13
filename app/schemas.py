from __future__ import annotations
from pydantic import BaseModel, model_validator
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
    low: float
    high: float

    @model_validator(mode="after")
    def high_gte_low(self) -> Target:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self


class Control(BaseModel):
    type: ControlType
    value: float


class Interval(BaseModel):
    name: Optional[str] = None
    exit_trigger_type: TriggerType
    exit_trigger_value: float
    intensity_type: Optional[IntensityType] = None
    targets: Optional[List[Target]] = None
    controls: Optional[List[Control]] = None
    intervals: Optional[List[Interval]] = None

    @model_validator(mode="after")
    def validate_repeat(self) -> Interval:
        if self.exit_trigger_type == TriggerType.REPEAT:
            if self.targets is not None:
                raise ValueError('targets not valid when exit_trigger_type is "repeat"')
            if not self.intervals:
                raise ValueError('intervals required when exit_trigger_type is "repeat"')
        return self


Interval.model_rebuild()


class PlanHeader(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
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


class Plan(BaseModel):
    header: PlanHeader
    intervals: List[Interval]


class PushWorkoutRequest(BaseModel):
    plan: Plan
    scheduled_at: Optional[str] = None


class PushGarminRequest(BaseModel):
    plan: Plan
    pace_window_s: float = 10.0
    scheduled_at: Optional[str] = None
