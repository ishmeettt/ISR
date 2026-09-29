"""Trust detectors.

Each detector is a pure function over the database returning findings:
(dict with key, detector, severity, subject_type, subject_id, title, detail).
`scan` upserts findings into trust_flags keyed by (detector, subject) so
re-scanning updates evidence without duplicating rows and never re-opens a
flag an organizer already resolved or dismissed. Nothing here changes scores,
assignments, or results.
"""
import json
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import (
    Evaluation, JudgeTrack, Project, RubricScore, Team, Track, TrustFlag, User,
)

Fingerprint = tuple[int, ...]


def coverage_stats(db: OrmSession) -> dict[str, Any]:
    """Distinct-judge review coverage per project, plus the modal (typical) count.

    Shared by the trust detector and the Mission Control dashboard so both
    report identical numbers from one implementation.
    """
    project_judges: dict[int, set[int]] = defaultdict(set)
    for judge_id, project_id in db.execute(
        select(Evaluation.judge_id, Evaluation.project_id)
    ):
        project_judges[project_id].add(judge_id)
    counts = [len(v) for v in project_judges.values()]
    modal = max(Counter(counts).items(), key=lambda kv: kv[1])[0] if counts else 0
    return {
        "per_project": {pid: len(v) for pid, v in sorted(project_judges.items())},
        "modal_count": modal,
    }


def _findings(db: OrmSession) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    # One pass over evaluations + scores, reused by several detectors.
    evals = db.execute(
        select(Evaluation.id, Evaluation.judge_id, Evaluation.project_id)
        .order_by(Evaluation.id.asc())
    ).all()
    eval_meta = {ev_id: (judge_id, project_id) for ev_id, judge_id, project_id in evals}
    per_eval: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for ev_id, criterion_id, score in db.execute(
        select(RubricScore.evaluation_id, RubricScore.criterion_id, RubricScore.score)
        .order_by(RubricScore.evaluation_id.asc(), RubricScore.criterion_id.asc())
    ):
        per_eval[ev_id].append((criterion_id, score))

    judges = {u.id: u.name for u in db.scalars(select(User))}

    # --- 1. identical-score judges -------------------------------------------
    # A judge whose raw score vector repeats across evaluations gives those
    # projects no discriminating signal. (The fixture's jdg_07 does this.)
    by_judge: dict[int, dict[Fingerprint, list[int]]] = defaultdict(lambda: defaultdict(list))
    for ev_id, pairs in per_eval.items():
        judge_id, project_id = eval_meta[ev_id]
        fingerprint = tuple(score for _, score in sorted(pairs))
        by_judge[judge_id][fingerprint].append(project_id)
    for judge_id, fingerprints in sorted(by_judge.items()):
        for fingerprint, project_ids in sorted(fingerprints.items()):
            if len(project_ids) >= 3:
                findings.append({
                    "key": f"uniform_judge:user:{judge_id}:vec={'-'.join(map(str, fingerprint))}",
                    "detector": "uniform_judge",
                    "severity": "medium",
                    "subject_type": "user",
                    "subject_id": judge_id,
                    "title": f"{judges.get(judge_id, f'judge {judge_id}')} gave identical scores "
                             f"to {len(project_ids)} projects",
                    "detail": {"score_vector": list(fingerprint), "projects": project_ids},
                })

    # --- 2. low coverage -------------------------------------------------------
    coverage = coverage_stats(db)
    titles = {p.id: p.title for p in db.scalars(select(Project))}
    for project_id, count in sorted(coverage["per_project"].items()):
        if count < coverage["modal_count"]:
            findings.append({
                "key": f"low_coverage:project:{project_id}",
                "detector": "low_coverage",
                "severity": "info",
                "subject_type": "project",
                "subject_id": project_id,
                "title": f"{titles.get(project_id, f'project {project_id}')} has "
                         f"{count} review(s), modal coverage is {coverage['modal_count']}",
                "detail": {"judge_count": count, "modal_count": coverage["modal_count"]},
            })

    # --- 3. out-of-track reviews ------------------------------------------------
    eligible: dict[int, set[int]] = {}
    for judge_id, track_id in db.execute(select(JudgeTrack.judge_id, JudgeTrack.track_id)):
        eligible.setdefault(judge_id, set()).add(track_id)
    track_names = {t.id: t.name for t in db.scalars(select(Track))}
    for judge_id, project_id, track_id in db.execute(
        select(Evaluation.judge_id, Evaluation.project_id, Project.track_id)
        .join(Project, Evaluation.project_id == Project.id)
        .order_by(Evaluation.judge_id.asc(), Evaluation.project_id.asc())
    ):
        if track_id not in eligible.get(judge_id, set()):
            findings.append({
                "key": f"out_of_track:user:{judge_id}:project:{project_id}",
                "detector": "out_of_track",
                "severity": "medium",
                "subject_type": "user",
                "subject_id": judge_id,
                "title": f"{judges.get(judge_id, f'judge {judge_id}')} reviewed "
                         f"'{track_names.get(track_id, track_id)}' work outside their tracks",
                "detail": {"project_id": project_id, "track_id": track_id,
                           "eligible_tracks": sorted(eligible.get(judge_id, set()))},
            })

    # --- 4. duplicate submissions -------------------------------------------------
    teams = {t.id: t.name for t in db.scalars(select(Team))}
    projects = db.scalars(select(Project).order_by(Project.id.asc())).all()
    seen: dict[tuple[int, str, str], list[Project]] = defaultdict(list)
    for p in projects:
        seen[(p.team_id, p.title, p.repo_url or "")].append(p)
    for (team_id, title, repo), group in sorted(seen.items()):
        if len(group) > 1:
            exts = [p.external_id for p in group]
            findings.append({
                "key": f"duplicate_submission:project:{'+'.join(exts)}",
                "detector": "duplicate_submission",
                "severity": "high",
                "subject_type": "project",
                "subject_id": group[-1].id,
                "title": f"Team {teams.get(team_id, team_id)} submitted '{title}' "
                         f"{len(group)} times ({', '.join(exts)})",
                "detail": {"projects": exts, "team": teams.get(team_id, team_id),
                           "repo_url": repo or None},
            })

    return findings


def scan(db: OrmSession) -> dict[str, Any]:
    """Run all detectors, upsert findings, report counts."""
    existing = {f.flag_key: f for f in db.scalars(select(TrustFlag))}
    created, updated = 0, 0
    for finding in _findings(db):
        flag = existing.get(finding["key"])
        if flag is None:
            db.add(TrustFlag(
                flag_key=finding["key"],
                detector=finding["detector"],
                severity=finding["severity"],
                subject_type=finding["subject_type"],
                subject_id=finding["subject_id"],
                title=finding["title"],
                detail=json.dumps(finding["detail"], default=str),
                status="open",
            ))
            created += 1
        else:
            flag.title = finding["title"]
            flag.detail = json.dumps(finding["detail"], default=str)
            updated += 1
    db.flush()
    open_total = len(db.scalars(select(TrustFlag.id).where(TrustFlag.status == "open")).all())
    return {"created": created, "updated": updated, "open": open_total}
