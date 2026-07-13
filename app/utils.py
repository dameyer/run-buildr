from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time as a naive datetime (timezone stripped for SQLite compat)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
