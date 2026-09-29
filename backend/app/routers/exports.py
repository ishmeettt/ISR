"""CSV export (T2): organizer-only raw score dump."""
import csv
import io

from fastapi import APIRouter, Response
from sqlalchemy import select

from ..core.audit import record
from ..core.deps import DbDep, RoleOrganizer
from ..models import Evaluation, Project, RubricCriterion, RubricScore, Team, Track, User

router = APIRouter(tags=["exports"])


@router.get("/api/export.csv")
def export_csv(db: DbDep, organizer: RoleOrganizer) -> Response:
    rows = db.execute(
        select(Evaluation, Project.external_id, Project.title, Track.name,
               Team.name, User.name)
        .join(Project, Evaluation.project_id == Project.id)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
        .join(User, Evaluation.judge_id == User.id)
        .order_by(Evaluation.id.asc())
    ).all()

    scores_by_eval: dict[int, dict[str, int]] = {}
    for evaluation_id, criterion_name, score in db.execute(
        select(RubricScore.evaluation_id, RubricCriterion.name, RubricScore.score)
        .join(RubricCriterion, RubricScore.criterion_id == RubricCriterion.id)
    ):
        scores_by_eval.setdefault(evaluation_id, {})[criterion_name] = score
    criteria_names = sorted({c for scores in scores_by_eval.values() for c in scores})

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["project", "title", "track", "team", "judge"]
        + [f"score_{c}" for c in criteria_names] + ["comment", "submitted_at"]
    )
    for ev, ext, title, track_name, team_name, judge_name in rows:
        scores = scores_by_eval.get(ev.id, {})
        writer.writerow(
            [ext, title, track_name, team_name, judge_name]
            + [scores.get(c, "") for c in criteria_names]
            + [ev.comment, ev.submitted_at.isoformat()]
        )
    record(db, actor_id=organizer.id, actor_role=organizer.role,
           action="CSV_EXPORTED", resource_type="evaluation",
           metadata={"rows": len(rows)})
    db.commit()
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=isr-scores.csv"},
    )
