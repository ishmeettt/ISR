"""Mission Control (organizer-only): one event's whole story on one endpoint.

Defaults to the newest event that has projects; `?event_id=` selects explicitly.
Read-only composition of existing domain state — no new sources of truth.
Numbers come from the same helpers the trust engine uses (coverage_stats), so
the dashboard and the flag list can never disagree.
"""
from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ..core.deps import DbDep, RoleOrganizer
from ..models import (
    Assignment, Evaluation, Event, NormalizationRun, Project, RankingResult, Team,
    TeamMember, TrustFlag, User, ensure_aware, utcnow,
)
from ..services.trust import coverage_stats

router = APIRouter(prefix="/api/mission-control", tags=["mission-control"])


@router.get("")
def mission_control(db: DbDep, organizer: RoleOrganizer,
                    event_id: int | None = Query(default=None)) -> dict:
    if event_id is not None:
        event = db.get(Event, event_id)
    else:
        event = db.scalar(
            select(Event).join(Project, Project.event_id == Event.id)
            .order_by(Event.id.desc()).limit(1)
        )
    if event is None:
        event = db.scalar(select(Event).order_by(Event.id.desc()).limit(1))
    if event is None:
        return {"event": None}

    eid = event.id
    close = ensure_aware(event.submissions_close)
    now = utcnow()

    # --- participation ---------------------------------------------------------
    participants = db.scalar(
        select(func.count(func.distinct(User.id)))
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(User.role == "participant")
    ) or 0
    teams = db.scalar(select(func.count(Team.id)).where(Team.event_id == eid)) or 0
    projects = db.scalar(select(func.count(Project.id)).where(Project.event_id == eid)) or 0
    submitted = db.scalar(
        select(func.count(Project.id))
        .where(Project.event_id == eid, Project.submitted_at.is_not(None))
    ) or 0

    # --- judging progress --------------------------------------------------------
    completed = db.scalar(
        select(func.count(Evaluation.id))
        .join(Project, Evaluation.project_id == Project.id)
        .where(Project.event_id == eid)
    ) or 0
    assigned = db.scalar(
        select(func.count(Assignment.id))
        .join(Project, Assignment.project_id == Project.id)
        .where(Project.event_id == eid)
    ) or 0
    pending = max(assigned - completed, 0)
    completion = round(100 * completed / assigned, 1) if assigned else 0.0

    # --- judge workload (across all events, since judges may serve several) -------
    judges = db.scalar(select(func.count(User.id)).where(User.role == "judge")) or 0
    workload_rows = db.execute(
        select(
            User.id, User.name, User.email,
            func.count(func.distinct(Assignment.id)),
            func.count(func.distinct(Evaluation.id)),
        )
        .outerjoin(Assignment, Assignment.judge_id == User.id)
        .outerjoin(Evaluation, Evaluation.judge_id == User.id)
        .where(User.role == "judge")
        .group_by(User.id, User.name, User.email)
        .order_by(func.count(func.distinct(Evaluation.id)).desc(), User.id.asc())
    ).all()
    workload = [
        {
            "judge": name, "email": email,
            "assigned": assigned_n, "completed": completed_n,
            "pending": max(assigned_n - completed_n, 0),
        }
        for _jid, name, email, assigned_n, completed_n in workload_rows
    ]

    # --- coverage gaps (same implementation the trust engine flags with) ----------
    coverage = coverage_stats(db)
    titles = {p.id: p.title for p in db.scalars(select(Project))}
    gaps = [
        {
            "project": titles.get(pid, f"project {pid}"),
            "reviews": count,
            "modal": coverage["modal_count"],
        }
        for pid, count in coverage["per_project"].items()
        if count < coverage["modal_count"]
    ]

    # --- trust summary (counts only; details live in the Trust Center) -----------
    trust_rows = db.execute(
        select(TrustFlag.status, TrustFlag.detector, func.count(TrustFlag.id))
        .group_by(TrustFlag.status, TrustFlag.detector)
    ).all()
    trust_by_status = {"open": 0, "resolved": 0, "dismissed": 0}
    by_detector: dict[str, int] = {}
    for status_name, detector, count in trust_rows:
        trust_by_status[status_name] = trust_by_status.get(status_name, 0) + count
        if status_name == "open":
            by_detector[detector] = count

    # --- normalization runs ----------------------------------------------------------
    runs = db.execute(
        select(NormalizationRun.id, NormalizationRun.method, NormalizationRun.created_at,
               NormalizationRun.project_count, NormalizationRun.evaluation_count)
        .order_by(NormalizationRun.id.desc())
        .limit(10)
    ).all()
    latest_run_id = runs[0][0] if runs else None
    leader = None
    if latest_run_id is not None:
        top = db.execute(
            select(Project.external_id, Project.title, RankingResult.rank,
                   RankingResult.final_score)
            .join(RankingResult, RankingResult.project_id == Project.id)
            .where(RankingResult.run_id == latest_run_id, RankingResult.rank == 1)
        ).first()
        if top:
            leader = {"project": top[0], "title": top[1],
                      "final_score": round(top[3], 4)}

    return {
        "event": {
            "id": event.id,
            "code": event.code,
            "name": event.name,
            "submissions_close": event.submissions_close.isoformat(),
            "closed": bool(close is not None and now > close),
        },
        "participation": {
            "participants": participants, "teams": teams,
            "projects": projects, "submitted": submitted,
        },
        "judging": {
            "judges": judges, "assigned": assigned, "completed": completed,
            "pending": pending, "completion_percent": completion,
        },
        "workload": workload,
        "coverage_gaps": gaps,
        "trust": {"by_status": trust_by_status, "open_by_detector": by_detector},
        "runs": [
            {"id": r_id, "method": method, "created_at": created_at.isoformat(),
             "project_count": project_count, "evaluation_count": evaluation_count}
            for r_id, method, created_at, project_count, evaluation_count in runs
        ],
        "leader": leader,
    }
