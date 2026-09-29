"""Submissions: create a project; deadline enforced server-side (T1)."""
import datetime as dt

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..core.audit import record
from ..core.deps import CurrentUser, DbDep
from ..models import Event, Project, Team, TeamMember, Track, ensure_aware, utcnow
from ..schemas import SubmitIn

router = APIRouter(tags=["submissions"])


def _event_is_open(event: Event, at: dt.datetime) -> bool:
    close = ensure_aware(event.submissions_close)
    return close is not None and at <= close


@router.post("/api/projects", status_code=status.HTTP_201_CREATED)
def submit_project(body: SubmitIn, db: DbDep, user: CurrentUser) -> dict:
    event = db.scalar(select(Event).order_by(Event.id.asc()))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No event exists")

    now = utcnow()
    if not _event_is_open(event, now):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Submissions closed at {event.submissions_close.isoformat()}",
        )

    membership = db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    ).first()
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not on a team for this event")
    team = db.get(Team, membership[0])

    track = None
    if body.track:
        track = db.scalar(select(Track).where(Track.external_id == body.track))
        if track is None or track.event_id != event.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown track for this event")
    if track is None:
        track = db.scalar(
            select(Track).where(Track.event_id == event.id).order_by(Track.id.asc())
        )
        if track is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Event has no tracks configured")

    project = Project(
        event_id=event.id,
        team_id=team.id,
        track_id=track.id,
        title=body.title,
        summary=body.summary,
        repo_url=body.repo_url,
        submitted_at=now,
    )
    db.add(project)
    db.flush()
    record(db, actor_id=user.id, actor_role=user.role, action="PROJECT_SUBMITTED",
           resource_type="project", resource_id=project.external_id,
           after_state={"title": project.title, "team": team.name})
    db.commit()
    return {"external_id": project.external_id, "title": project.title}
