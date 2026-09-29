"""Scoreable-without-rubric guarantee.

Every event must be judgeable: when the organizer never defined a rubric
(bare event, repos added by link), GET /api/judge/rubric materializes the
default criteria and POST /api/judge/evaluate accepts marks against them.
The bare event lives only inside these tests and is fully cleaned up, so
other modules sharing the session DB are unaffected.
"""
import pytest

from app.core.db import SessionLocal
from app.models import (
    AuditEvent, Evaluation, Event, JudgeTrack, Project, Rubric,
    RubricCriterion, RubricScore, RubricVersion, Team, Track, User, utcnow,
)
from tests.conftest import _cookie

DEFAULT_NAMES = ["Functionality", "Code Quality", "Security", "Testing", "Documentation"]


@pytest.fixture()
def bare_event(db_session):
    """A brand-new event with a track, a project, and judge_b linked — no rubric."""
    with SessionLocal() as db:
        judge = db.query(User).filter_by(email="jonas.vogel@example.org").one()
        event = Event(external_id="evt_bare_probe", code="BARE26", name="Bare Probe Event",
                      submissions_close=utcnow(), judge_count=1)
        db.add(event)
        db.flush()
        track = Track(external_id="evt_bare_probe_gen", event_id=event.id, name="Open")
        db.add(track)
        db.flush()
        team = Team(name="bare-team", external_id=f"bare_team_{event.id}", event_id=event.id)
        db.add(team)
        db.flush()
        project = Project(external_id=f"usr_bare_probe_{event.id}", event_id=event.id,
                          team_id=team.id, track_id=track.id, title="Bare Probe",
                          summary="probe project", submitted_at=utcnow())
        db.add(project)
        db.add(JudgeTrack(judge_id=judge.id, track_id=track.id))
        db.commit()
        ids = (event.id, track.id, team.id, project.id, judge.id)
    yield ids

    # Teardown: explicit, dependency-ordered deletes (audit rows included).
    event_id, track_id, team_id, project_id, judge_id = ids
    with SessionLocal() as db:
        eval_ids = db.query(Evaluation.id).filter_by(project_id=project_id).all()
        for (ev_id,) in eval_ids:
            db.query(AuditEvent).filter_by(resource_type="evaluation",
                                           resource_id=str(ev_id)).delete()
        db.query(RubricScore).filter(
            RubricScore.evaluation_id.in_(
                db.query(Evaluation.id).filter_by(project_id=project_id))).delete(
            synchronize_session=False)
        db.query(Evaluation).filter_by(project_id=project_id).delete()
        db.query(Project).filter_by(id=project_id).delete()
        db.query(Team).filter_by(id=team_id).delete()
        version_ids = [v for (v,) in db.query(RubricVersion.id).filter(
            RubricVersion.rubric_id.in_(
                db.query(Rubric.id).filter_by(event_id=event_id))).all()]
        db.query(RubricCriterion).filter(
            RubricCriterion.rubric_version_id.in_(version_ids)).delete(
            synchronize_session=False)
        db.query(RubricVersion).filter(RubricVersion.id.in_(version_ids)).delete(
            synchronize_session=False)
        db.query(Rubric).filter_by(event_id=event_id).delete()
        db.query(JudgeTrack).filter_by(track_id=track_id).delete()
        db.query(Track).filter_by(id=track_id).delete()
        db.query(Event).filter_by(id=event_id).delete()
        db.commit()


def test_bare_event_gets_default_rubric_and_is_scoreable(client, bare_event):
    event_id, _track_id, _team_id, project_id, _judge_id = bare_event
    with SessionLocal() as db:
        ext = db.get(Project, project_id).external_id

    # 1. Reading the rubric materializes the default criteria.
    r = client.get("/api/judge/rubric", headers=_cookie("judge_b"))
    assert r.status_code == 200
    criteria = r.json()["criteria"]
    assert [c["name"] for c in criteria] == DEFAULT_NAMES
    assert all(c["max_score"] == 10 for c in criteria)
    assert pytest.approx(sum(c["weight"] for c in criteria), abs=1e-6) == 1.0

    # 2. Judges can submit marks against them.
    scores = {name: i + 1 for i, name in enumerate(DEFAULT_NAMES)}
    r = client.post("/api/judge/evaluate",
                    json={"project": ext, "scores": scores, "comment": "solid probe"},
                    headers=_cookie("judge_b"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["revised"] is False
    eval_id = body["evaluation_id"]

    # 3. Validation still applies: unknown criterion and out-of-range score.
    r = client.post("/api/judge/evaluate",
                    json={"project": ext, "scores": {"Bogus": 5}},
                    headers=_cookie("judge_b"))
    assert r.status_code == 400 and "Unknown criteria" in r.json()["detail"]
    r = client.post("/api/judge/evaluate",
                    json={"project": ext, "scores": {"Functionality": 99}},
                    headers=_cookie("judge_b"))
    assert r.status_code == 400 and "Functionality" in r.json()["detail"]

    # 4. Re-evaluation replaces the judge's marks (one row per judge/project).
    scores[DEFAULT_NAMES[0]] = 9
    r = client.post("/api/judge/evaluate",
                    json={"project": ext, "scores": scores, "comment": "revised"},
                    headers=_cookie("judge_b"))
    assert r.status_code == 201 and r.json()["revised"] is True
    assert r.json()["evaluation_id"] == eval_id

    # 5. Idempotent: re-reading the rubric never duplicates criteria.
    r = client.get("/api/judge/rubric", headers=_cookie("judge_b"))
    assert [c["name"] for c in r.json()["criteria"]] == DEFAULT_NAMES
    with SessionLocal() as db:
        versions = [v for (v,) in db.query(RubricVersion.id).filter(
            RubricVersion.rubric_id.in_(
                db.query(Rubric.id).filter_by(event_id=event_id))).all()]
        assert len(versions) == 1


def test_preexisting_rubric_is_never_replaced(client, bare_event):
    """An event that already has a rubric keeps it — the default is lazy-only."""
    event_id, _track_id, _team_id, project_id, _judge_id = bare_event
    with SessionLocal() as db:
        rubric = Rubric(event_id=event_id, name="Custom rubric")
        db.add(rubric)
        db.flush()
        rv = RubricVersion(rubric_id=rubric.id, version=1)
        db.add(rv)
        db.flush()
        db.add(RubricCriterion(rubric_version_id=rv.id, name="Vibes",
                               weight=1.0, max_score=5))
        db.commit()
        rv_id = rv.id

    r = client.get("/api/judge/rubric", headers=_cookie("judge_b"))
    assert r.status_code == 200
    criteria = r.json()["criteria"]
    assert [c["name"] for c in criteria] == ["Vibes"]
    assert criteria[0]["max_score"] == 5

    # Marks submit against the custom rubric, not the default.
    with SessionLocal() as db:
        ext = db.get(Project, project_id).external_id
    r = client.post("/api/judge/evaluate",
                    json={"project": ext, "scores": {"Vibes": 4}},
                    headers=_cookie("judge_b"))
    assert r.status_code == 201, r.text

    # Extra cleanup for this test's own rubric (fixture handles the rest).
    with SessionLocal() as db:
        db.query(RubricCriterion).filter_by(rubric_version_id=rv_id).delete()
        db.query(RubricVersion).filter_by(id=rv_id).delete()
        db.query(Rubric).filter_by(event_id=event_id).delete()
        db.commit()
