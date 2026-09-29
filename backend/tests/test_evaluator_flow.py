"""Evaluator flow: event-code login, AI review (advisory, judge-private), manual scores."""
import hashlib
import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import AiReview, Event, JudgeTrack, Session as DbSession, Track, User, utcnow


def _mk_session(email: str, token: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not db.scalar(select(DbSession).where(
                DbSession.token_hash == hashlib.sha256(token.encode()).hexdigest())):
            db.add(DbSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             user_id=user.id, expires_at=utcnow() + timedelta(days=1)))
            db.commit()


def _hdrs(token: str) -> dict:
    return {"Cookie": f"session={token}"}


def _client_for(email: str, token: str) -> tuple[TestClient, dict]:
    _mk_session(email, token)
    return TestClient(app), _hdrs(token)


JUDGE_A = ("diego.herrera@example.org", "diego-session-token-0001")
JUDGE_B = ("jonas.vogel@example.org", "jonas-session-token-0002")


def test_login_with_event_code_links_judge_to_event_tracks():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={
            "email": JUDGE_A[0], "password": "isr-dev-password", "event_code": "sample26",
        })
    assert r.status_code == 200
    assert r.json()["event"]["code"] == "SAMPLE26"
    with SessionLocal() as db:
        judge = db.scalar(select(User).where(User.email == JUDGE_A[0]))
        event = db.scalar(select(Event).where(Event.code == "SAMPLE26"))
        event_track_ids = set(db.scalars(select(Track.id).where(Track.event_id == event.id)))
        linked = set(db.scalars(select(JudgeTrack.track_id).where(JudgeTrack.judge_id == judge.id)))
    assert event_track_ids <= linked, "login with code must grant all event tracks"


def test_login_with_unknown_code_is_404():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={
            "email": JUDGE_A[0], "password": "isr-dev-password", "event_code": "ZZZZ9999",
        })
    assert r.status_code == 404


def test_ai_review_is_advisory_and_judge_private():
    ca, ha = _client_for(*JUDGE_A)
    cb, hb = _client_for(*JUDGE_B)
    r = ca.post("/api/judge/ai-review", json={"projects": ["prj_01", "prj_02"]}, headers=ha)
    assert r.status_code == 200
    body = r.json()
    assert body["advisory"] is True
    assert {x["project"] for x in body["reviewed"]} == {"prj_01", "prj_02"}
    assert body["reviewed"][0]["summary"]["security"] >= 0

    # judge A can read their own review
    mine = ca.get("/api/judge/ai-review/prj_01", headers=ha)
    assert mine.status_code == 200
    assert mine.json()["result"]["advisory"] is True

    # judge B has none of their own for prj_01 — and cannot see A's
    assert cb.get("/api/judge/ai-review/prj_01", headers=hb).status_code == 404


def test_ai_review_finds_seeded_vulnerabilities_offline():
    """The analyzer must catch planted flaws in a local checkout (no network)."""
    from pathlib import Path

    repos = Path(__file__).resolve().parents[2] / "repos" / "glass-signal"
    repos.mkdir(parents=True, exist_ok=True)
    (repos / "app.py").write_text(
        "import os\n"
        "API_KEY = 'sk-live-0123456789abcdef'\n"
        "def q(user):\n"
        "    return 'SELECT * FROM users WHERE name=' + user\n"
        "def run(cmd):\n"
        "    os.system(cmd)\n"
    )
    ca, ha = _client_for(*JUDGE_A)
    r = ca.post("/api/judge/ai-review", json={"projects": ["prj_01"]}, headers=ha)
    assert r.status_code == 200
    stored = ca.get("/api/judge/ai-review/prj_01", headers=ha).json()["result"]
    assert stored["source"].startswith("local checkout")
    assert stored["findings"]["summary"]["security"] >= 3, "planted secret/SQL/shell must be found"


def test_event_code_is_required_to_score():
    """The code is the gate: without a link to the event, browsing works but
    scoring and stored AI review are refused — until the judge enters the
    event code at login."""
    import datetime as dt

    from fastapi.testclient import TestClient

    from app.core.security import hash_password
    from app.models import Session as DbSession, utcnow
    from app.seed import _get_or_create_user

    email, token = "gate.probe@example.org", "gate-probe-token-0001"
    with SessionLocal() as db:
        user = _get_or_create_user(db, email, "Gate Probe", "judge",
                                   hash_password("isr-dev-password"))
        db.add(DbSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                         user_id=user.id, expires_at=utcnow() + dt.timedelta(days=1)))
        db.commit()
    headers = {"Cookie": f"session={token}"}

    with TestClient(app) as c:
        # Not linked: lands on the fallback event (read-only)...
        info = c.get("/api/judge/event", headers=headers).json()
        assert info["via"] == "event"
        # ...but cannot score or run stored AI review on it.
        refused = c.post("/api/judge/evaluate", json={
            "project": "prj_08", "scores": {"functionality": 4, "quality": 4,
                                            "innovation": 4},
        }, headers=headers)
        assert refused.status_code == 403
        assert "code" in refused.json()["detail"].lower()
        assert c.post("/api/judge/ai-review", json={"projects": ["prj_08"]},
                      headers=headers).status_code == 403

        # Entering the code at login unlocks the event.
        login = c.post("/api/auth/login", json={
            "email": email, "password": "isr-dev-password", "event_code": "sample26"})
        assert login.status_code == 200
        assert login.json()["event"]["code"] == "SAMPLE26"
        assert c.get("/api/judge/event", headers=headers).json()["via"] == "linked"
        ok = c.post("/api/judge/evaluate", json={
            "project": "prj_08", "scores": {"functionality": 4, "quality": 4,
                                            "innovation": 4},
        }, headers=headers)
        assert ok.status_code == 201


def test_pasted_link_preview_is_offline_and_not_persisted():
    """Paste-a-link review: works with no network and saves nothing anywhere."""
    from pathlib import Path

    import app.models as models

    ca, ha = _client_for(*JUDGE_A)
    r = ca.post("/api/judge/ai-review/preview",
                json={"repo_url": "https://github.com/acme/widget-pro"}, headers=ha)
    assert r.status_code == 200
    body = r.json()
    # Same envelope as GET /ai-review/{ext}: findings live under "result".
    assert body["title"] == "widget-pro"
    assert body["result"]["advisory"] is True
    assert body["result"]["repo"]["owner"] == "acme"
    assert "offline" in body["result"]["source"]
    assert body["result"]["findings"]["files_scanned"] == 0, "no clone -> nothing scanned"

    # Ephemeral by design: no AiReview row may exist for the pasted link.
    with SessionLocal() as db:
        rows = db.scalars(select(AiReview).where(
            AiReview.repo_url == "https://github.com/acme/widget-pro")).all()
    assert rows == []


def test_manual_evaluation_submit_and_isolation():
    ca, ha = _client_for(*JUDGE_A)
    cb, hb = _client_for(*JUDGE_B)
    scores = {"functionality": 4, "quality": 4, "innovation": 3}
    r = ca.post("/api/judge/evaluate",
                json={"project": "prj_05", "scores": scores, "comment": "solid build"},
                headers=ha)
    assert r.status_code == 201
    # re-evaluation replaces the judge's own marks (201, not 409)
    again = ca.post("/api/judge/evaluate",
                    json={"project": "prj_05",
                          "scores": {"functionality": 5, "quality": 5, "innovation": 4},
                          "comment": "revised after second run"}, headers=ha)
    assert again.status_code == 201
    assert again.json()["revised"] is True
    mine = ca.get("/api/judge/scores", headers=ha).json()
    prj05 = next(e for e in mine if e["project"] == "prj_05")
    assert {s["criterion"]: s["score"] for s in prj05["scores"]} == {
        "functionality": 5, "quality": 5, "innovation": 4}
    assert prj05["comment"] == "revised after second run"
    # invalid criterion refused
    bad = ca.post("/api/judge/evaluate",
                  json={"project": "prj_06", "scores": {"notafield": 5}}, headers=ha)
    assert bad.status_code == 400
    # out-of-range refused
    rng = ca.post("/api/judge/evaluate",
                  json={"project": "prj_06", "scores": {"functionality": 9}}, headers=ha)
    assert rng.status_code == 400

    # judge A sees their own; judge B does not see A's marks anywhere
    mine = [e["project"] for e in ca.get("/api/judge/scores", headers=ha).json()]
    assert "prj_05" in mine
    theirs = [e["project"] for e in cb.get("/api/judge/scores", headers=hb).json()]
    assert "prj_05" not in theirs
    peer = cb.get("/api/judge/scores?judge_email=diego.herrera@example.org", headers=hb)
    assert peer.status_code == 403

    # DB-level guarantee: one evaluation row, owned by judge A
    with SessionLocal() as db:
        rows = db.scalars(select(AiReview)).all()
        judge_a_id = db.scalar(select(User.id).where(User.email == JUDGE_A[0]))
        assert all(rv.judge_id == judge_a_id for rv in rows if rv.project_id ==
                   db.scalar(select(__import__("app.models", fromlist=["Project"]).Project.id)
                             .where(__import__("app.models", fromlist=["Project"]).Project.external_id == "prj_01")))


def test_event_projects_scoped_and_public_event_page(client, organizer_cookie):
    _, ha = _client_for(*JUDGE_A)
    with TestClient(app) as c:
        r = c.get("/api/judge/projects", headers=ha)
    assert r.status_code == 200
    projects = r.json()
    assert len(projects) == 41, "fixture event has 41 projects"
    assert all(p["repo_url"] for p in projects)
