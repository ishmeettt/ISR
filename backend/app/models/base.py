"""Shared model base plus common helpers."""
import datetime as dt

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def ensure_aware(value: dt.datetime | None) -> dt.datetime | None:
    """Treat DB datetimes as UTC when the backend drops tzinfo (SQLite does).

    All writes are UTC, so naive values read back are unambiguous. On Postgres
    (timestamptz) values arrive aware and pass through unchanged.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.timezone.utc)
