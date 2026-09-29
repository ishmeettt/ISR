"""Judge workspace (T2 + evaluator flow).

Isolation contract: every read/write is scoped to the authenticated judge
(resolved from the session cookie). A self-identifying parameter is accepted
only when it matches the caller; anything else is a 403 before data is touched.
AI reviews and manual scores are visible to exactly one principal: the judge
who produced them.
"""
import json
import os
import re

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..core.audit import record
from ..core.deps import DbDep, RoleJudge
from ..models.audit import AuditEvent
from ..models import (
    AiReview, Assignment, Evaluation, Event, JudgeTrack, Project, Rubric,
    RubricCriterion, RubricScore, RubricVersion, Team, Track, utcnow,
)
from ..schemas import AssignmentOut, EvaluationOut
from ..services import code_assist, groq

router = APIRouter(prefix="/api/judge", tags=["judge"])

# Every event must be scoreable, even when the organizer never defined a
# rubric (e.g. repos added by link to a bare event). These criteria are
# materialized as a real "Default rubric" v1 the first time a judge opens
# the scoring panel or submits marks — so weighting/fair-score logic sees
# ordinary rubric data everywhere else.
DEFAULT_RUBRIC_CRITERIA: list[tuple[str, float, int]] = [
    ("Functionality", 0.30, 10),
    ("Code Quality", 0.20, 10),
    ("Security", 0.20, 10),
    ("Testing", 0.15, 10),
    ("Documentation", 0.15, 10),
]


def _ensure_default_rubric(db, event) -> RubricVersion:
    """Return the event's latest rubric version, creating the default one lazily.

    Re-fetches before inserting; the tiny concurrent-first-load race window
    (two judges creating two defaults at once) is harmless — the latest
    version wins and the other is ignored.
    """
    rv = db.scalar(
        select(RubricVersion)
        .join(Rubric, RubricVersion.rubric_id == Rubric.id)
        .where(Rubric.event_id == event.id)
        .order_by(RubricVersion.version.desc())
        .limit(1)
    )
    if rv is not None:
        return rv
    rubric = Rubric(event_id=event.id, name="Default rubric")
    db.add(rubric)
    db.flush()  # assign rubric.id
    rv = RubricVersion(rubric_id=rubric.id, version=1)
    db.add(rv)
    db.flush()
    for name, weight, max_score in DEFAULT_RUBRIC_CRITERIA:
        db.add(RubricCriterion(rubric_version_id=rv.id, name=name,
                               weight=weight, max_score=max_score))
    db.commit()
    return rv


def _event_rubric(db, event) -> list[dict]:
    """The event's latest rubric as plain dicts (for AI suggested scoring).

    Uses the lazy default rubric so AI suggestions always speak the same
    criterion names as the scoring form the judge will fill in.
    """
    rv = _ensure_default_rubric(db, event)
    return [
        {"name": c.name, "weight": float(c.weight), "max_score": c.max_score}
        for c in db.scalars(
            select(RubricCriterion).where(RubricCriterion.rubric_version_id == rv.id)
        )
    ]


def _active_event(db):
    """The event an evaluator lands on when no signal says otherwise: the
    newest event that actually has projects. An empty just-created event must
    not shadow the live one for judges who never entered any code."""
    return db.scalar(
        select(Event)
        .join(Project, Project.event_id == Event.id)
        .order_by(Event.id.desc())
        .limit(1)
    )


def _workspace_event(db, judge) -> Event | None:
    """THE event this evaluator's workspace should show.

    Resolution order (strongest signal first):
    1. The event whose share code the judge entered at their most recent
       login — recorded in the audit trail (JUDGE_EVENT_LINKED / KNOWN). A
       judge who explicitly linked a brand-new, still-empty event must land
       in THAT event's workspace, not in the old one that merely has projects.
    2. The newest event the judge is linked to via JudgeTrack.
    3. The browse default (_active_event: newest event with projects) for
       judges who never entered a code.
    """
    last_link = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.actor_id == judge.id,
            AuditEvent.action.in_(["JUDGE_EVENT_LINKED", "JUDGE_EVENT_KNOWN"]),
        )
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    if last_link is not None and last_link.resource_id:
        event = db.get(Event, int(last_link.resource_id))
        if event is not None:
            return event
    return db.scalar(
        select(Event)
        .join(Track, Track.event_id == Event.id)
        .join(JudgeTrack, JudgeTrack.track_id == Track.id)
        .where(JudgeTrack.judge_id == judge.id)
        .order_by(Event.id.desc())
        .limit(1)
    ) or _active_event(db)


def _require_linked(db, judge, event) -> None:
    """The event code is the gate: only judges linked to THIS event (by
    entering its code at login, or by organizer assignment) may score or run
    stored reviews on it. Browsing stays open; scoring does not."""
    linked = db.scalar(
        select(JudgeTrack.track_id)
        .join(Track, Track.id == JudgeTrack.track_id)
        .where(JudgeTrack.judge_id == judge.id, Track.event_id == event.id)
        .limit(1)
    )
    if linked is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Enter this event's code at login to evaluate it",
        )


@router.get("/event")
def my_event(db: DbDep, judge: RoleJudge) -> dict:
    """The event this evaluator is working on.

    Same resolution as the rest of the workspace (last code entered at login,
    else newest linked, else browse default). `via` reports whether the judge
    is actually eligible to score the resolved event — the UI uses it to show
    the read-only banner when a code is still needed.
    """
    event = _workspace_event(db, judge)
    if event is None:
        return {"event": None}
    linked = db.scalar(
        select(JudgeTrack.track_id)
        .join(Track, Track.id == JudgeTrack.track_id)
        .where(JudgeTrack.judge_id == judge.id, Track.event_id == event.id)
        .limit(1)
    )
    return {
        "event": {"id": event.id, "name": event.name, "code": event.code,
                  "judge_count": event.judge_count},
        "via": "linked" if linked is not None else "event",
    }


@router.get("/scores", response_model=list[EvaluationOut])
def my_scores(
    db: DbDep,
    judge: RoleJudge,
    judge_email: str | None = Query(default=None, max_length=255),
) -> list[EvaluationOut]:
    """List THIS judge's evaluations. Passing judge_email=<someone else> is a 403."""
    if judge_email is not None and judge_email != judge.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You may only read your own scores")
    rows = db.execute(
        select(Evaluation, Project.external_id, Project.title)
        .join(Project, Evaluation.project_id == Project.id)
        .where(Evaluation.judge_id == judge.id)
        .order_by(Evaluation.submitted_at.asc())
    ).all()
    return [
        EvaluationOut(
            project=ext, project_title=title, comment=ev.comment,
            submitted_at=ev.submitted_at,
            scores=[
                {
                    "criterion": s.criterion.name,
                    "weight": float(s.criterion.weight),
                    "max_score": s.criterion.max_score,
                    "score": s.score,
                }
                for s in ev.scores
            ],
        )
        for ev, ext, title in rows
    ]


@router.get("/assignments", response_model=list[AssignmentOut])
def my_assignments(db: DbDep, judge: RoleJudge) -> list[AssignmentOut]:
    """Projects this judge is assigned to review, with completion state."""
    rows = db.execute(
        select(Assignment, Project, Track.name, Team.name)
        .join(Project, Assignment.project_id == Project.id)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
        .where(Assignment.judge_id == judge.id)
        .order_by(Project.title.asc())
    ).all()
    done = {
        ev.project_id for ev in db.scalars(
            select(Evaluation).where(Evaluation.judge_id == judge.id)
        )
    }
    return [
        AssignmentOut(
            project=p.external_id, project_title=p.title, track=track_name,
            completed=p.id in done,
        )
        for a, p, track_name, team_name in rows
    ]


@router.get("/rubric")
def event_rubric(db: DbDep, judge: RoleJudge) -> dict:
    """The workspace event's scoring criteria, so the UI never hardcodes them."""
    event = _workspace_event(db, judge)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active event")
    rubric_version = _ensure_default_rubric(db, event)
    criteria = db.scalars(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_version_id == rubric_version.id)
        .order_by(RubricCriterion.id.asc())
    ).all()
    return {
        "criteria": [
            {"name": c.name, "weight": float(c.weight), "max_score": c.max_score}
            for c in criteria
        ],
    }


@router.get("/projects")
def event_projects(db: DbDep, judge: RoleJudge,
                   event_id: int | None = Query(default=None)) -> list[dict]:
    """Projects of the workspace event: what this evaluator can look at and score."""
    if event_id is not None:
        event = db.get(Event, event_id)
    else:
        event = _workspace_event(db, judge)
    if event is None:
        return []
    rows = db.execute(
        select(Project, Track.name, Team.name)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
        .where(Project.event_id == event.id)
        .order_by(Project.title.asc())
    ).all()
    return [
        {
            "external_id": p.external_id, "title": p.title, "summary": p.summary,
            "repo_url": p.repo_url, "track": track_name, "team": team_name,
            "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
        }
        for p, track_name, team_name in rows
    ]


@router.get("/overview")
def workspace_overview(db: DbDep, judge: RoleJudge) -> dict:
    """One call powering the evaluator dashboard: the judge's name, every
    project in the workspace event with its evaluated/pending state, whether an
    AI review is stored, and where the judge's current marks would place the
    project against the others (advisory context, computed from the judge's
    OWN evaluations only — never another judge's data)."""
    event = _workspace_event(db, judge)
    if event is None:
        return {"judge": {"name": judge.name, "email": judge.email}, "event": None,
                "projects": []}

    projects = db.scalars(
        select(Project).where(Project.event_id == event.id).order_by(Project.title.asc())
    ).all()
    evaluations = db.scalars(
        select(Evaluation).where(Evaluation.judge_id == judge.id)
    ).all()
    by_project = {ev.project_id: ev for ev in evaluations}
    reviewed_ids = db.scalars(
        select(AiReview.project_id).where(AiReview.judge_id == judge.id)
    )
    has_ai = set(reviewed_ids)

    def weighted(ev: Evaluation) -> float:
        total = 0.0
        for s in ev.scores:
            total += (s.score / s.criterion.max_score) * float(s.criterion.weight)
        return round(total * 100, 1)  # percent of the weighted maximum

    def rank_of(project_id: int) -> tuple[int | None, int, float | None]:
        """Where this judge's own marks rank the projects (1-based)."""
        ranked = sorted(
            ((pid, weighted(ev)) for pid, ev in by_project.items()),
            key=lambda t: t[1], reverse=True,
        )
        for i, (pid, w) in enumerate(ranked, start=1):
            if pid == project_id:
                return i, len(ranked), w
        return None, len(ranked), None

    out = []
    for p in projects:
        ev = by_project.get(p.id)
        place, of, my_weighted = rank_of(p.id)
        out.append({
            "external_id": p.external_id,
            "title": p.title,
            "summary": p.summary,
            "repo_url": p.repo_url,
            "track": db.scalar(select(Track.name).where(Track.id == p.track_id)),
            "team": db.scalar(select(Team.name).where(Team.id == p.team_id)),
            "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
            "evaluated": p.id in by_project,
            "has_ai_review": p.id in has_ai,
            "my_weighted": weighted(ev) if ev else None,
            "my_rank": place,
            "ranked_count": of,
        })

    evaluated_count = sum(1 for p in projects if p.id in by_project)
    return {
        "judge": {"name": judge.name, "email": judge.email},
        "event": {"id": event.id, "name": event.name, "code": event.code},
        "projects": out,
        "totals": {
            "projects": len(projects),
            "evaluated": evaluated_count,
            "pending": len(projects) - evaluated_count,
            "ai_reviewed": len(has_ai & {p.id for p in projects}),
        },
    }


# --- AI (static, offline, advisory) review ---------------------------------

class AiReviewIn(BaseModel):
    projects: list[str] = Field(min_length=1, max_length=200,
                                description="project external_ids to review")
    event_id: int | None = None


@router.post("/ai-review")
def run_ai_review(body: AiReviewIn, db: DbDep, judge: RoleJudge) -> dict:
    """Run the offline static analyzer for the pasted/selected projects.

    Advisory only: findings (errors, security loopholes, improvements) are
    stored judge-private and never produce marks.
    """
    event = db.get(Event, body.event_id) if body.event_id else _workspace_event(db, judge)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No event to review against")
    _require_linked(db, judge, event)

    reviewed: list[dict] = []
    skipped: list[str] = []
    for ext in dict.fromkeys(body.projects):
        project = db.scalar(
            select(Project).where(Project.external_id == ext, Project.event_id == event.id)
        )
        if project is None:
            skipped.append(ext)
            continue
        payload = groq.review_with_optional_llm(
            event.ai_api_key, project.title, project.summary, project.repo_url,
            rubric=_event_rubric(db, event),
        )
        existing = db.scalar(
            select(AiReview).where(AiReview.judge_id == judge.id, AiReview.project_id == project.id)
        )
        if existing is None:
            db.add(AiReview(judge_id=judge.id, project_id=project.id,
                            repo_url=project.repo_url,
                            result=json.dumps(payload, default=str)))
        else:
            existing.repo_url = project.repo_url
            existing.result = json.dumps(payload, default=str)
        reviewed.append({"project": ext, "title": project.title,
                         "summary": payload["findings"]["summary"],
                         "source": payload["source"]})
    record(db, actor_id=judge.id, actor_role=judge.role, action="AI_REVIEW_RUN",
           resource_type="ai_review", metadata={"projects": len(reviewed),
                                                "skipped": skipped})
    db.commit()
    return {"reviewed": reviewed, "skipped": skipped, "advisory": True}


class LinkReviewIn(BaseModel):
    repo_url: str = Field(min_length=4, max_length=512)


@router.post("/ai-review/preview")
def preview_repo(body: LinkReviewIn, db: DbDep, judge: RoleJudge) -> dict:
    """Review of a pasted repository link — advisory, ephemeral.

    Not persisted anywhere: findings go back to this judge and nowhere else.
    A local checkout under ./repos/ is scanned when one exists (network
    fetches of repo contents are never performed); when the event has a Groq
    key configured, the static findings + source sample get a full LLM
    judgment, exactly like stored project reviews.
    """
    parsed = code_assist.parse_repo_url(body.repo_url)
    title = parsed["repo"] or body.repo_url
    event = _workspace_event(db, judge)
    payload = groq.review_with_optional_llm(
        event.ai_api_key if event else None, title, "", body.repo_url,
        rubric=(_event_rubric(db, event) if event else None),
    )
    # Same envelope as GET /ai-review/{ext} so the UI renders both alike.
    return {"project": None, "title": title, "repo_url": body.repo_url,
            "result": payload}


@router.get("/ai-review/{project_external_id}")
def get_ai_review(project_external_id: str, db: DbDep, judge: RoleJudge) -> dict:
    """THIS judge's stored AI review of a project (never another judge's)."""
    project = db.scalar(select(Project).where(Project.external_id == project_external_id))
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    review = db.scalar(
        select(AiReview).where(AiReview.judge_id == judge.id, AiReview.project_id == project.id)
    )
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No AI review yet for this project")

    return {"project": project_external_id, "title": project.title,
            "repo_url": review.repo_url, "result": json.loads(review.result)}


# --- run it locally: README + detected commands + terminal launcher ---------


def _project_checkout(db, project) -> tuple[object | None, object | None]:
    """The local checkout for a project, plus its containing root, or (None, None)."""
    if not project.repo_url:
        return None, None
    parsed = code_assist.parse_repo_url(project.repo_url)
    for root in code_assist._repos_roots():
        for candidate in code_assist._local_checkout_candidates(
                project.repo_url, parsed["owner"], parsed["repo"], project.title):
            try:
                if candidate.is_dir() and candidate.parent == root:
                    return candidate, root
            except OSError:
                continue
    return None, None


def _launch_hint(checkout_name: str, root: object, commands: list[dict]) -> str:
    """How to open a shell inside the checkout, for display in the UI."""
    first = commands[0]["command"] if commands else "ls"
    if str(root) in ("/repos", "/app/repos"):
        return (f"wsl -d Ubuntu -u root -e docker exec -it isr sh -c "
                f"'cd /repos/{checkout_name} && {first}'")
    return f"cd to the checkout and run: {first}"


def _in_container_volume(root: object) -> bool:
    """Checkouts inside the offline image's volumes are reached via docker
    exec, not host paths."""
    return str(root) in ("/repos", "/app/repos")


def _cmd_echo(text: str) -> str:
    """Escape cmd.exe metacharacters so an echo line can carry a literal
    command like `npm install && npm run dev` without cmd executing any of
    it. ^ escapes & < > | and itself."""
    for ch in ("^", "&", "<", ">", "|"):
        text = text.replace(ch, f"^{ch}")
    return text


def _terminal_script_lines(checkout_name: str, root, commands: list[dict],
                           container: str = "isr") -> list[str]:
    """Build the .bat contents that drops the judge into a live shell inside
    the checkout (docker exec for container volumes, cd + cmd /k for host
    checkouts). The suggested-command menu is echoed on the cmd side with
    metacharacters escaped — repo text is never executed by anything."""
    lines = ["@echo off", f"title ISR - run {checkout_name}"]
    if _in_container_volume(root):
        cd = f"/repos/{checkout_name}" if str(root) == "/repos" else f"/app/repos/{checkout_name}"
        lines += [
            f"echo Opening a shell in the ISR container at {cd} ...",
            "echo === suggested commands (copy into the shell below) ===",
        ]
        lines += [f"echo   {_cmd_echo(c['command'])}" for c in commands]
        lines += [
            f"wsl -d Ubuntu -u root -e docker exec -it {container} sh -c \"cd {cd}; exec sh\"",
            "pause",
        ]
    else:
        lines += [
            f'cd /d "{root / checkout_name}"',
            "echo === suggested commands ===",
        ]
        lines += [f"echo   {_cmd_echo(c['command'])}" for c in commands]
        lines.append("cmd /k")
    return lines


@router.get("/repos/{project_external_id}/runbook")
def repo_runbook(project_external_id: str, db: DbDep, judge: RoleJudge) -> dict:
    """Everything needed to run a judged project locally: its README and the
    run commands detected from its manifests (package.json scripts,
    requirements.txt, manage.py, Makefile targets, compose). Read-only —
    the judge executes the commands in their own terminal."""
    event = _active_event(db)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active event")
    project = db.scalar(
        select(Project).where(Project.external_id == project_external_id,
                              Project.event_id == event.id)
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not in the active event")

    checkout, root = _project_checkout(db, project)
    if checkout is None:
        # Best effort: auto-clone GitHub links (same self-heal as AI review).
        checkout = code_assist.ensure_checkout(project.repo_url, project.title)
        root = checkout.parent if checkout else None
    if checkout is None:
        return {
            "found": False,
            "repo_url": project.repo_url,
            "note": ("No local checkout yet. Re-run 'AI evaluate' to auto-clone "
                     "this GitHub repo, or add it again from the dashboard."),
            "commands": [], "readme": None, "launch": None,
        }

    runbook = code_assist.read_runbook(checkout)
    launch = _launch_hint(checkout.name, root, runbook["commands"])
    record(db, actor_id=judge.id, actor_role=judge.role, action="REPO_RUNBOOK_VIEWED",
           resource_type="project", resource_id=str(project.id),
           metadata={"checkout": checkout.name})
    db.commit()
    return {
        "found": True,
        "repo_url": project.repo_url,
        "checkout": checkout.name,
        "commands": runbook["commands"],
        "readme": runbook["readme"],
        "launch": launch,
    }


@router.get("/repos/{project_external_id}/terminal-script")
def repo_terminal_script(project_external_id: str, db: DbDep, judge: RoleJudge):
    """A downloadable .bat that opens a terminal INSIDE the project checkout.

    Volume-hosted checkouts (the offline container) are reached through
    docker exec; source-checkout deployments cd to the host path directly.
    The detected run commands are echoed first so the judge sees the menu.
    """
    event = _active_event(db)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active event")
    project = db.scalar(
        select(Project).where(Project.external_id == project_external_id,
                              Project.event_id == event.id)
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not in the active event")

    checkout, root = _project_checkout(db, project)
    if checkout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No local checkout for this project yet — run 'AI evaluate' first")
    runbook = code_assist.read_runbook(checkout)
    lines = _terminal_script_lines(
        checkout.name, root, runbook["commands"],
        container=os.environ.get("ISR_CONTAINER_NAME", "isr"),
    )
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", checkout.name) or "repo"
    record(db, actor_id=judge.id, actor_role=judge.role, action="REPO_TERMINAL_OPENED",
           resource_type="project", resource_id=str(project.id),
           metadata={"checkout": checkout.name})
    db.commit()
    return Response(
        content="\r\n".join(lines) + "\r\n",
        media_type="application/x-bat",
        headers={"Content-Disposition": f'attachment; filename="run-{safe}.bat"'},
    )


# --- add a repo by GitHub link (judge's private judging list) ----------------

_GIT_URL = re.compile(
    r"^https?://(www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$"
)


class RepoAddIn(BaseModel):
    # Length-only constraints here; URL shape is validated in the handler so
    # every rejection is a consistent 400 with an actionable message.
    repo_url: str = Field(min_length=1, max_length=512)


@router.post("/repos/add")
def add_repo(body: RepoAddIn, db: DbDep, judge: RoleJudge) -> dict:
    """Add a GitHub repo to this judge's private judging list by link.

    The checkout is cloned shallowly into /repos (best effort — clone errors
    are reported, never fatal) and a Project row is created so the repo
    behaves like any other judged artifact: it appears in the dashboard, can
    be AI-reviewed (Groq when the event has a key) and scored. Re-adding the
    same URL refreshes rather than duplicates.
    """
    url = body.repo_url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if not _GIT_URL.match(url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Enter a GitHub repo link like https://github.com/owner/repo")

    event = _active_event(db)
    if event is None:
        # A just-created event has no projects yet, so _active_event (which
        # joins on projects) finds nothing — fall back to the newest event.
        event = db.scalar(select(Event).order_by(Event.id.desc()).limit(1))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No active event — host one first, then add repos to it")

    parsed = code_assist.parse_repo_url(url)
    repo_name = parsed["repo"] or "repo"
    title = repo_name.replace("-", " ").replace("_", " ").title()

    existing = db.scalar(
        select(Project).where(Project.event_id == event.id, Project.repo_url == url)
    )
    if existing is not None:
        project = existing
        project.title = title  # refresh the title from the current URL
    else:
        # The team marker scopes the row to this judge; external_id derives
        # from the URL slug so re-adds and repeat tests can never collide.
        slug = repo_name.lower().replace("_", "-")[:40]
        team = Team(name=f"judge:{judge.id}",
                    external_id=f"judge_{judge.id}_{slug}_{event.id}",
                    event_id=event.id)
        db.add(team)
        db.flush()
        track = db.scalar(select(Track).where(Track.event_id == event.id).limit(1))
        if track is None:
            track = Track(external_id=f"{event.code or 'evt'}_gen", event_id=event.id,
                          name="General")
            db.add(track)
            db.flush()
        project = Project(
            external_id=f"usr_{team.external_id}",
            event_id=event.id,
            team_id=team.id,
            track_id=track.id,
            title=title,
            summary=f"Added by {judge.name} via GitHub link.",
            repo_url=url,
            submitted_at=utcnow(),
        )
        db.add(project)
    db.flush()

    clone_state = "already-present"
    clone_note = ""
    target = code_assist._repos_roots()[0] / repo_name
    if not target.exists():
        import subprocess

        try:
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url + ".git", str(target)],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                clone_state = "cloned"
            else:
                clone_state = "failed"
                clone_note = (proc.stderr or "clone failed").strip().splitlines()[-1][:200]
        except (OSError, subprocess.TimeoutExpired) as exc:
            clone_state = "failed"
            clone_note = f"git unavailable or timed out: {exc}"[:200]

    record(db, actor_id=judge.id, actor_role=judge.role, action="REPO_ADDED",
           resource_type="project", resource_id=str(project.id),
           after_state={"repo_url": url, "clone": clone_state})
    db.commit()
    return {
        "project": project.external_id,
        "title": project.title,
        "repo_url": url,
        "clone_state": clone_state,
        "clone_note": clone_note,
        "scan_hint": ("Open the repo and run 'AI evaluate' — with the event's Groq "
                      "key configured you get the full LLM judgment."),
    }


class EvaluationIn(BaseModel):
    project: str
    scores: dict[str, int] = Field(min_length=1, description="criterion name -> score")
    comment: str = ""


@router.post("/evaluate", status_code=status.HTTP_201_CREATED)
def submit_evaluation(body: EvaluationIn, db: DbDep, judge: RoleJudge) -> dict:
    """Submit THIS judge's marks for a project. One evaluation per judge/project."""
    event = _active_event(db)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active event")
    project = db.scalar(
        select(Project).where(Project.external_id == body.project, Project.event_id == event.id)
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not in the active event")
    _require_linked(db, judge, event)

    rubric_version = _ensure_default_rubric(db, event)
    criteria = {c.name: c for c in db.scalars(
        select(RubricCriterion).where(RubricCriterion.rubric_version_id == rubric_version.id)
    )}
    invalid = [name for name in body.scores if name not in criteria]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown criteria: {invalid}")
    for name, value in body.scores.items():
        if not isinstance(value, int) or not 0 <= value <= criteria[name].max_score:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"{name} must be an integer 0..{criteria[name].max_score}")

    existing = db.scalar(
        select(Evaluation).where(Evaluation.judge_id == judge.id, Evaluation.project_id == project.id)
    )
    if existing is not None:
        # Re-evaluation: replace the judge's previous marks wholesale (the UI's
        # "Re-evaluate" action). One row per judge/project remains; the audit
        # trail keeps the history via before/after states.
        record(db, actor_id=judge.id, actor_role=judge.role, action="EVALUATION_REVISED",
               resource_type="evaluation", resource_id=str(existing.id),
               before_state={"project": body.project,
                             "scores": {s.criterion.name: s.score for s in existing.scores},
                             "comment": existing.comment})
        existing.scores.clear()
        existing.status = "submitted"
        existing.comment = body.comment
        ev = existing
    else:
        ev = Evaluation(judge_id=judge.id, project_id=project.id,
                        rubric_version_id=rubric_version.id, status="submitted",
                        comment=body.comment)
        db.add(ev)
    db.flush()
    for name, value in body.scores.items():
        db.add(RubricScore(evaluation_id=ev.id, criterion_id=criteria[name].id, score=value))
    record(db, actor_id=judge.id, actor_role=judge.role, action="EVALUATION_SUBMITTED",
           resource_type="evaluation", resource_id=str(ev.id),
           after_state={"project": body.project, "judge": judge.id})
    db.commit()
    return {"evaluation_id": ev.id, "project": body.project, "revised": existing is not None,
            "scores": body.scores, "comment": body.comment}
