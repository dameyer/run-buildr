from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.utils import utcnow


class GarminToken(Base):
    __tablename__ = "garmin_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    tokens_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Compared against the copy in the session cookie on every request; bumping
    # it invalidates all outstanding sessions (logout, password change/reset).
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WahooToken(Base):
    __tablename__ = "wahoo_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    token_type: Mapped[str] = mapped_column(String, default="Bearer")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SavedWorkout(Base):
    __tablename__ = "saved_workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    wahoo_plan_id: Mapped[str | None] = mapped_column(String, nullable=True)
    wahoo_workout_id: Mapped[str | None] = mapped_column(String, nullable=True)
    garmin_workout_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
