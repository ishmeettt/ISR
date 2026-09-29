"""Results endpoints (organizer-only). Deterministic FairScore + explanations."""
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..core.audit import record
from ..core.deps import DbDep, RoleOrganizer
from ..models import (
    Evaluation, Event, NormalizationRun, Project, RankingResult, Team, Track, User,
)
from ..services import fairscore

router = APIRouter(prefix="/api/results", tags=["results"])


def _ranking_out(db, run_id: int) -> list[dict]:
    rows = db.execute(
        select(RankingResult, Project.external_id, Project.title, Track.name, Team.name)
        .join(Project, RankingResult.project_id == Project.id)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
        .where(RankingResult.run_id == run_id)
        .order_by(RankingResult.rank.asc())
    ).all()
    return [
        {
            "rank": r.rank,
            "project": ext,
            "title": title,
            "track": track_name,
            "team": team_name,
            "final_score": round(r.final_score, 6),
            "raw_weighted": round(r.raw_weighted, 6),
            "judge_count": r.judge_count,
            "coverage_ok": r.coverage_ok,
        }
        for r, ext, title, track_name, team_name in rows
    ]


def _latest_run(db) -> NormalizationRun | None:
    return db.scalar(select(NormalizationRun).order_by(NormalizationRun.id.desc()).limit(1))


@router.post("/run", status_code=status.HTTP_201_CREATED)
def run_fairscore(db: DbDep, organizer: RoleOrganizer,
                  event_id: int | None = Query(default=None)) -> dict:
    """Compute a new normalization run (append-only).

    Defaults to the newest event with evaluations; pass ?event_id= to score a
    specific event explicitly.
    """
    if event_id is not None:
        event = db.get(Event, event_id)
    else:
        event = db.scalar(
            select(Event)
            .join(Project, Project.event_id == Event.id)
            .join(Evaluation, Evaluation.project_id == Project.id)
            .order_by(Event.id.desc())
            .limit(1)
        )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No event with evaluations exists")
    try:
        result = fairscore.compute(db, event_id=event.id, created_by=organizer.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    record(db, actor_id=organizer.id, actor_role=organizer.role,
           action="RESULT_CALCULATED", resource_type="normalization_run",
           resource_id=str(result["run_id"]),
           metadata={"method": fairscore.METHOD,
                     "projects": len(result["ranked"]),
                     "evaluations": len(result["evaluations"])})
    db.commit()
    return {
        "run_id": result["run_id"],
        "method": fairscore.METHOD,
        "projects": len(result["ranked"]),
        "evaluations": len(result["evaluations"]),
        "top": [
            {"rank": r["rank"], "project_id": r["project_id"], "final_score": round(r["final_score"], 6)}
            for r in result["ranked"][:3]
        ],
    }


@router.get("")
def get_results(db: DbDep, organizer: RoleOrganizer,
                run_id: int | None = Query(default=None)) -> dict:
    """Ranking for the latest (or given) run."""
    run = db.get(NormalizationRun, run_id) if run_id is not None else _latest_run(db)
    if run is None:
        return {"run": None, "ranking": []}
    return {
        "run": {"id": run.id, "method": run.method, "params": run.params,
                "created_at": run.created_at.isoformat(),
                "project_count": run.project_count, "evaluation_count": run.evaluation_count},
        "ranking": _ranking_out(db, run.id),
    }


@router.get("/why/{run_id}/{project_external_id}")
def why_this_rank(db: DbDep, organizer: RoleOrganizer,
                  run_id: int, project_external_id: str) -> dict:
    """Explain why a project holds its rank, re-derived from stored intermediates."""
    run = db.get(NormalizationRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    project = db.scalar(select(Project).where(Project.external_id == project_external_id))
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    try:
        return fairscore.explanation_for(db, run_id, project.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/runs")
def list_runs(db: DbDep, organizer: RoleOrganizer) -> list[dict]:
    """History of normalization runs (all immutable)."""
    runs = db.execute(
        select(NormalizationRun, User.name)
        .join(User, NormalizationRun.created_by == User.id, isouter=True)
        .order_by(NormalizationRun.id.desc())
    ).all()
    return [
        {"id": run.id, "method": run.method, "status": run.status,
         "project_count": run.project_count, "evaluation_count": run.evaluation_count,
         "created_by": name, "created_at": run.created_at.isoformat()}
        for run, name in runs
    ]
