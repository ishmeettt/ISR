"""Event management (organizer) + public event page by share code.

The organizer's flow: list the events they host, create a new one (getting a
unique share code + link), and edit any details — including the open/submission
/close windows — at any time.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..core.audit import record
from ..core.deps import CurrentUser, DbDep, RoleOrganizer
from ..models import Event, Project, Team, Track, ensure_aware, utcnow
from ..services import events as evsvc

router = APIRouter(tags=["events"])


class EventIn(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    description: str = ""
    judge_count: int = Field(default=3, ge=1, le=50)
    submissions_open: datetime | None = None
    submissions_close: datetime
    registration_open: datetime | None = None
    registration_close: datetime | None = None
    judging_close: datetime | None = None
    tracks: list[str] = Field(default_factory=lambda: ["Open"])
    # Optional: enables Groq-powered detailed AI judgment for this event.
    # Judges stay free to ignore it; marks always come from humans.
    ai_api_key: str | None = Field(default=None, max_length=255)


class EventEdit(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = None
    judge_count: int | None = Field(default=None, ge=1, le=50)
    submissions_open: datetime | None = None
    submissions_close: datetime | None = None
    registration_open: datetime | None = None
    registration_close: datetime | None = None
    judging_close: datetime | None = None
    tracks: list[str] | None = None  # replaces the track list when provided
    # Set to enable Groq AI judgment; empty string clears it. Never returned.
    ai_api_key: str | None = Field(default=None, max_length=255)


def _project_count(db, event_id: int) -> int:
    return db.scalar(select(func.count(Project.id)).where(Project.event_id == event_id)) or 0


def _out(db, event: Event, include_private: bool = False) -> dict:
    tracks = db.scalars(select(Track).where(Track.event_id == event.id)).all()
    now = utcnow()
    close = ensure_aware(event.submissions_close)
    open_at = ensure_aware(event.submissions_open)
    out = {
        "id": event.id,
        "external_id": event.external_id,
        "code": event.code,
        "name": event.name,
        "description": event.description,
        "judge_count": event.judge_count,
        "submissions_open": event.submissions_open.isoformat() if event.submissions_open else None,
        "submissions_close": event.submissions_close.isoformat(),
        "judging_close": event.judging_close.isoformat() if event.judging_close else None,
        "registration_open": event.registration_open.isoformat() if event.registration_open else None,
        "registration_close": event.registration_close.isoformat() if event.registration_close else None,
        "is_open": bool(close is not None and now <= close and (open_at is None or now >= open_at)),
        "tracks": [t.name for t in tracks],
    }
    if include_private:
        out["project_count"] = _project_count(db, event.id)
        # The key itself never leaves the server — only whether one is set.
        out["ai_configured"] = bool(event.ai_api_key)
    return out


def _owned_event(db, event_id: int, organizer) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    if organizer.role != "admin" and event.created_by != organizer.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not host this event")
    return event


@router.get("/api/organizer/events")
def my_events(db: DbDep, organizer: RoleOrganizer) -> list[dict]:
    """The events this organizer hosts, newest first."""
    rows = db.scalars(
        select(Event).where(Event.created_by == organizer.id).order_by(Event.id.desc())
    ).all()
    return [{**_out(db, e, include_private=True)} for e in rows]


@router.post("/api/organizer/events", status_code=status.HTTP_201_CREATED)
def create_event(body: EventIn, db: DbDep, organizer: RoleOrganizer) -> dict:
    """Host a new event: ISR assigns a unique share code and share link."""
    payload = body.model_dump()
    try:
        evsvc.validate_windows(payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    code = evsvc.generate_code(db)
    event = Event(
        external_id=f"usr_{code.lower()}",
        code=code,
        created_by=organizer.id,
        name=body.name,
        description=body.description,
        judge_count=body.judge_count,
        submissions_open=body.submissions_open,
        submissions_close=body.submissions_close,
        registration_open=body.registration_open,
        registration_close=body.registration_close,
        judging_close=body.judging_close,
        ai_api_key=(body.ai_api_key or None),
    )
    db.add(event)
    db.flush()
    for i, name in enumerate(dict.fromkeys(body.tracks)):
        db.add(Track(external_id=f"{code.lower()}_t{i + 1}", event_id=event.id, name=name))
    record(db, actor_id=organizer.id, actor_role=organizer.role,
           action="EVENT_CREATED", resource_type="event", resource_id=str(event.id),
           after_state={"name": event.name, "code": event.code,
                        "submissions_close": event.submissions_close.isoformat()})
    db.commit()
    return {
        **_out(db, event, include_private=True),
        "share_link": f"/events/{event.code}",
        "message": "Share this link with participants and judges to join this event.",
    }


@router.patch("/api/organizer/events/{event_id}")
def edit_event(event_id: int, body: EventEdit, db: DbDep, organizer: RoleOrganizer) -> dict:
    """Edit any event detail — windows stay editable after creation."""
    event = _owned_event(db, event_id, organizer)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")

    merged = {
        "submissions_open": event.submissions_open,
        "submissions_close": event.submissions_close,
        "registration_open": event.registration_open,
        "registration_close": event.registration_close,
        "judging_close": event.judging_close,
        **changes,
    }
    try:
        evsvc.validate_windows(merged)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    before = {"name": event.name, "submissions_close": event.submissions_close.isoformat(),
              "judge_count": event.judge_count}
    for key, value in changes.items():
        if key == "tracks":
            continue
        if key == "ai_api_key":
            # Empty string clears the key; whitespace-only is ignored.
            event.ai_api_key = (value or None) if isinstance(value, str) and value.strip() else None
            continue
        setattr(event, key, value)
    if changes.get("tracks") is not None:
        for track in list(event.tracks):
            db.delete(track)
        db.flush()
        base = (event.code or event.external_id).lower()
        for i, name in enumerate(dict.fromkeys(changes["tracks"])):
            db.add(Track(external_id=f"{base}_t{i + 1}", event_id=event.id, name=name))
    record(db, actor_id=organizer.id, actor_role=organizer.role,
           action="EVENT_UPDATED", resource_type="event", resource_id=str(event.id),
           before_state=before,
           after_state={"name": event.name,
                        "submissions_close": event.submissions_close.isoformat(),
                        "judge_count": event.judge_count})
    db.commit()
    return _out(db, event, include_private=True)


@router.get("/api/events/{code}")
def public_event(code: str, db: DbDep, user: CurrentUser) -> dict:
    """Event details for a share code — any signed-in user can view it."""
    event = db.scalar(select(Event).where(Event.code == code.strip().upper()))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No event with that code")
    return {
        **_out(db, event),
        "project_count": _project_count(db, event.id),
        "team_count": db.scalar(select(func.count(Team.id)).where(Team.event_id == event.id)) or 0,
    }
