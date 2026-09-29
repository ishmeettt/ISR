"""Event service: share codes, window validation, legacy backfill."""
import datetime as dt
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import Event

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I/L/O/0/1: unambiguous when read aloud


def generate_code(db: OrmSession) -> str:
    """A unique, human-friendly share code."""
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if db.scalar(select(Event.id).where(Event.code == code)) is None:
            return code
    raise RuntimeError("could not generate a unique event code")


def validate_windows(payload: dict[str, Any]) -> None:
    """Windows are editable later, but never allowed to be internally inconsistent."""
    from ..models import ensure_aware

    def aware(value):
        return ensure_aware(value) if isinstance(value, dt.datetime) else value

    for open_key, close_key in (("registration_open", "registration_close"),
                                ("submissions_open", "submissions_close")):
        o, c = aware(payload.get(open_key)), aware(payload.get(close_key))
        if o and c and o >= c:
            raise ValueError(f"{open_key} must be before {close_key}")
    sc, jc = aware(payload.get("submissions_close")), aware(payload.get("judging_close"))
    if sc and jc and jc < sc:
        raise ValueError("judging_close cannot be before submissions_close")
    ro, so = aware(payload.get("registration_open")), aware(payload.get("submissions_open"))
    if ro and so and ro > so:
        raise ValueError("registration_open should not be after submissions_open")


def link_judge_to_event(db: OrmSession, judge, event) -> bool:
    """Give a judge eligibility for every track of an event. Returns True when
    they were already fully linked (idempotent, safe on every login)."""
    from ..models import JudgeTrack, Track

    track_ids = db.scalars(select(Track.id).where(Track.event_id == event.id)).all()
    if not track_ids:
        return False
    existing = set(
        db.scalars(
            select(JudgeTrack.track_id).where(
                JudgeTrack.judge_id == judge.id,
                JudgeTrack.track_id.in_(track_ids),
            )
        )
    )
    missing = [t for t in track_ids if t not in existing]
    for t in missing:
        db.add(JudgeTrack(judge_id=judge.id, track_id=t))
    return not missing


def backfill_legacy_events(db: OrmSession) -> int:
    """One-time migration for events created before codes/ownership existed.

    New events get codes at creation, but a database seeded before this feature
    (like the long-lived docker volume) has events with code/owner unset. This
    runs during the seed's idempotent path, so it executes on every boot and
    patches any legacy event it finds.
    """
    from ..models import User

    owner = db.scalar(select(User).where(User.email == "organizer@isr.local"))
    legacy = db.scalars(
        select(Event).where(Event.created_by.is_(None) | Event.code.is_(None))
    ).all()
    for event in legacy:
        if event.code is None:
            event.code = "SAMPLE26" if event.external_id == "evt_01" else generate_code(db)
        if owner is not None:
            event.created_by = owner.id
    return len(legacy)
