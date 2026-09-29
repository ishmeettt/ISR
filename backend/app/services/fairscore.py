"""FairScore: deterministic, reproducible scoring pipeline.

RAW → NORMALIZATION → WEIGHTING → FINAL

Pipeline per run (method: zscore_per_judge):
  1. Raw composite per evaluation:  Σ_c (score_c / max_c) × weight_c  ∈ [0, 1]
  2. Judge statistics:              mean and population SD of a judge's composites
  3. Normalized:                    z = (raw − mean) / sd   (z = 0 when sd = 0,
     i.e. the fixture's uniform judge is neutral, not ±∞)
  4. Final per project:             mean z across that project's evaluations

Determinism: iteration order is fixed by ORDER BY id everywhere; ties in final
score are broken by lower project id. Same inputs ⇒ byte-identical outputs.

Raw scores in evaluations/rubric_scores are NEVER modified — every run writes
fresh rows in normalization_runs/normalized_scores/ranking_results.
"""
import json
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import (
    Evaluation, NormalizationRun, NormalizedScore, Project, RankingResult,
    RubricCriterion, RubricScore,
)

METHOD = "zscore_per_judge"
PARAMS = {
    "raw": "sum((score / max_score) * weight) per evaluation",
    "normalization": "z = (raw - judge_mean) / judge_sd (population sd); z=0 when sd=0",
    "aggregation": "final = mean(z) per project; ties broken by lower project id",
}


def _load_evaluations(db: OrmSession) -> list[dict[str, Any]]:
    """All submitted evaluations with their raw scores, stably ordered."""
    rows = db.execute(
        select(Evaluation, RubricScore.score, RubricCriterion.name,
               RubricCriterion.weight, RubricCriterion.max_score)
        .join(RubricScore, RubricScore.evaluation_id == Evaluation.id)
        .join(RubricCriterion, RubricScore.criterion_id == RubricCriterion.id)
        .order_by(Evaluation.id.asc(), RubricScore.id.asc())
    ).all()
    evaluations: dict[int, dict[str, Any]] = {}
    for ev, score, name, weight, max_score in rows:
        item = evaluations.setdefault(ev.id, {
            "evaluation_id": ev.id, "judge_id": ev.judge_id,
            "project_id": ev.project_id, "scores": [],
        })
        item["scores"].append({
            "criterion": name, "score": score,
            "weight": float(weight), "max_score": max_score,
        })
    return [evaluations[k] for k in sorted(evaluations)]


def compute(db: OrmSession, event_id: int, created_by: int | None = None) -> dict[str, Any]:
    evaluations = _load_evaluations(db)
    if not evaluations:
        raise ValueError("No submitted evaluations to score")

    # 1. raw composites
    for ev in evaluations:
        ev["raw_weighted"] = sum(
            (s["score"] / s["max_score"]) * s["weight"] for s in ev["scores"]
        )

    # 2. judge statistics (over each judge's raw composites)
    by_judge: dict[int, list[float]] = {}
    for ev in evaluations:
        by_judge.setdefault(ev["judge_id"], []).append(ev["raw_weighted"])
    judge_mean = {j: mean(vals) for j, vals in by_judge.items()}
    judge_sd = {j: pstdev(vals) if len(vals) > 1 else 0.0 for j, vals in by_judge.items()}

    # 3. normalize
    for ev in evaluations:
        j = ev["judge_id"]
        sd = judge_sd[j]
        ev["judge_mean"] = judge_mean[j]
        ev["judge_sd"] = sd
        ev["z_score"] = (ev["raw_weighted"] - judge_mean[j]) / sd if sd > 0 else 0.0

    # 4. aggregate per project (mean z, mean raw), then rank
    by_project: dict[int, list[dict[str, Any]]] = {}
    for ev in evaluations:
        by_project.setdefault(ev["project_id"], []).append(ev)

    project_ids = sorted(by_project)  # deterministic tie-break order
    project_rows: list[dict[str, Any]] = []
    for pid in project_ids:
        evals = by_project[pid]
        project_rows.append({
            "project_id": pid,
            "final_score": mean(e["z_score"] for e in evals),
            "raw_weighted": mean(e["raw_weighted"] for e in evals),
            "judge_count": len({e["judge_id"] for e in evals}),
        })

    ranked = sorted(project_rows, key=lambda r: (-r["final_score"], r["project_id"]))
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i

    # coverage: a project is fully covered when it has the modal number of
    # distinct judges among all projects (the fixture's honest baseline —
    # some projects legitimately have fewer reviews).
    counts = [r["judge_count"] for r in project_rows]
    modal_count = max(set(counts), key=counts.count)
    for row in project_rows:
        row["coverage_ok"] = row["judge_count"] >= modal_count

    # --- persist run + intermediates (append-only) ----------------------------
    run = NormalizationRun(
        event_id=event_id, method=METHOD, params=json.dumps(PARAMS),
        project_count=len(project_rows), evaluation_count=len(evaluations),
        created_by=created_by,
    )
    db.add(run)
    db.flush()

    for ev in evaluations:
        db.add(NormalizedScore(
            run_id=run.id, evaluation_id=ev["evaluation_id"],
            raw_weighted=ev["raw_weighted"], judge_mean=ev["judge_mean"],
            judge_sd=ev["judge_sd"], z_score=ev["z_score"],
        ))
    for row in ranked:
        db.add(RankingResult(
            run_id=run.id, project_id=row["project_id"], rank=row["rank"],
            final_score=row["final_score"], raw_weighted=row["raw_weighted"],
            judge_count=row["judge_count"], coverage_ok=row["coverage_ok"],
        ))
    db.flush()

    return {"run_id": run.id, "ranked": ranked, "evaluations": evaluations,
            "judge_mean": judge_mean, "judge_sd": judge_sd, "modal_count": modal_count}


def explanation_for(db: OrmSession, run_id: int, project_id: int) -> dict[str, Any]:
    """Re-derive the 'why this rank' explanation from persisted intermediates."""
    run = db.get(NormalizationRun, run_id)
    if run is None:
        raise ValueError("Run not found")
    mine = db.scalar(
        select(RankingResult).where(
            RankingResult.run_id == run_id, RankingResult.project_id == project_id
        )
    )
    if mine is None:
        raise ValueError("Project not in this run")

    project = db.get(Project, project_id)
    all_rows = db.scalars(
        select(RankingResult).where(RankingResult.run_id == run_id)
    ).all()

    # My evaluation-level numbers, with the project title + judge for context.
    eval_rows = db.execute(
        select(NormalizedScore, Evaluation.judge_id)
        .join(Evaluation, NormalizedScore.evaluation_id == Evaluation.id)
        .where(NormalizedScore.run_id == run_id, Evaluation.project_id == project_id)
        .order_by(NormalizedScore.evaluation_id.asc())
    ).all()
    from ..models import User
    judge_names = {
        u.id: u.name for u in db.scalars(
            select(User).where(User.id.in_([jr.judge_id for jr in eval_rows] or [0]))
        )
    }

    # Peer comparison: the two projects immediately above and below.
    neighbors = sorted(
        (r for r in all_rows if r.project_id != project_id),
        key=lambda r: r.rank,
    )
    above = [r for r in neighbors if r.rank < mine.rank][-2:]
    below = [r for r in neighbors if r.rank > mine.rank][:2]
    names = {r.project_id: db.get(Project, r.project_id).title for r in all_rows}

    return {
        "run": {"id": run.id, "method": run.method, "params": json.loads(run.params),
                "created_at": run.created_at.isoformat()},
        "project": {"id": project.external_id, "title": project.title},
        "rank": mine.rank,
        "of": len(all_rows),
        "final_score": mine.final_score,
        "raw_weighted": mine.raw_weighted,
        "judge_count": mine.judge_count,
        "coverage_ok": mine.coverage_ok,
        "evaluations": [
            {
                "judge": judge_names.get(judge_id, f"judge {judge_id}"),
                "raw_weighted": ns.raw_weighted,
                "judge_mean": ns.judge_mean,
                "judge_sd": ns.judge_sd,
                "z_score": ns.z_score,
            }
            for ns, judge_id in eval_rows
        ],
        "neighbors": {
            "above": [{"rank": r.rank, "title": names[r.project_id], "final_score": r.final_score}
                      for r in reversed(above)],
            "below": [{"rank": r.rank, "title": names[r.project_id], "final_score": r.final_score}
                      for r in below],
        },
    }
