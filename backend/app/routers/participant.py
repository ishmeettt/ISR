"""Participant dashboard: the participant's own event view.

Serves only the participant's own data (their team, their projects, how many
reviews their project received). Judge identities and scores are never exposed
here — judge isolation applies to participants doubly.
"""
from fastapi import APIRouter
from sqlalchemy import func, select

from ..core.deps import DbDep, RoleParticipant
from ..models import (
    Evaluation, Event, Project, Team, TeamMember, Track, User, ensure_aware, utcnow,
)

router = APIRouter(prefix="/api/participant", tags=["participant"])


@router.get("/dashboard")
def dashboard(db: DbDep, user: RoleParticipant) -> dict:
    memberships = db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    ).scalars().all()
    teams_out = []
    my_project_ids: list[int] = []
    now = utcnow()
    for team_id in memberships:
        team = db.get(Team, team_id)
        event = db.get(Event, team.event_id)
        close = ensure_aware(event.submissions_close) if event else None
        members = db.execute(
            select(User.name, User.email)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team_id)
            .order_by(TeamMember.id.asc())
        ).all()
        projects = db.scalars(
            select(Project).where(Project.team_id == team_id).order_by(Project.id.asc())
        ).all()
        for p in projects:
            my_project_ids.append(p.id)

        track_names = [
            db.scalar(select(Track.name).where(Track.id == p.track_id)) for p in projects
        ]
        review_counts = [
            db.scalar(
                select(func.count(func.distinct(Evaluation.judge_id)))
                .where(Evaluation.project_id == p.id)
            ) or 0
            for p in projects
        ]
        teams_out.append({
            "name": team.name,
            "event": {
                "name": event.name if event else None,
                "submissions_close": close.isoformat() if close else None,
                "closed": bool(close is not None and now > close),
            },
            "members": [{"name": n, "email": e} for n, e in members],
            "projects": [
                {
                    "external_id": p.external_id,
                    "title": p.title,
                    "summary": p.summary,
                    "track": track_names[i],
                    "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
                    "review_count": review_counts[i],
                }
                for i, p in enumerate(projects)
            ],
        })

    return {
        "user": {"name": user.name, "email": user.email},
        "teams": teams_out,
        "totals": {
            "teams": len(teams_out),
            "projects": len(my_project_ids),
            "reviews_received": sum(
                sum(p["review_count"] for p in t["projects"]) for t in teams_out
            ),
        },
    }
