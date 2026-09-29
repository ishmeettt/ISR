"""Gallery: submitted projects, visible to signed-in users (T1).

Auth is enforced server-side here; the UI merely hides the link for
anonymous visitors, so this route is the boundary.
"""
from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from ..core.deps import CurrentUser, DbDep
from ..models import Project, Team, Track
from ..schemas import ProjectOut

router = APIRouter(tags=["gallery"])


@router.get("/api/gallery", response_model=list[ProjectOut])
def gallery(
    db: DbDep,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=100),
    track: str | None = Query(default=None, max_length=64),
) -> list[ProjectOut]:
    stmt = (
        select(Project, Track.name, Team.name)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
        .where(Project.submitted_at.is_not(None))
        .order_by(Project.submitted_at.asc(), Project.id.asc())
    )
    if track:
        stmt = stmt.where(Track.external_id == track)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(Project.title.ilike(like), Project.summary.ilike(like)))
    rows = db.execute(stmt).all()
    return [
        ProjectOut(
            external_id=p.external_id, title=p.title, summary=p.summary,
            repo_url=p.repo_url, track=track_name, team=team_name,
            submitted_at=p.submitted_at,
        )
        for p, track_name, team_name in rows
    ]
