"""Judge score isolation: the security property the acceptance suite checks hardest."""
import hashlib

from app.core.db import SessionLocal
from app.models import Session as DbSession
from app.seed import _seed_token


def test_judge_reads_only_own_scores(client, judge_a_cookie, db_session):
    """Every evaluation returned to judge_a must belong to judge_a."""
    rows = client.get("/api/judge/scores", headers=judge_a_cookie).json()
    assert rows, "judge_a should have seeded evaluations"
    from sqlalchemy import select
    from app.models import Evaluation, Project, User

    with SessionLocal() as db:
        judge_id = db.scalar(select(User.id).where(User.email == "diego.herrera@example.org"))
        own_projects = set(db.scalars(
            select(Project.external_id).where(Project.id.in_(
                select(Evaluation.project_id).where(Evaluation.judge_id == judge_id)))
        ))
    returned = {r["project"] for r in rows}
    assert returned <= own_projects, f"leaked other judges' projects: {returned - own_projects}"
    assert {"prj_06", "prj_12", "prj_14", "prj_40"} <= returned, "judge_a's seeded projects must be present"


def test_cross_judge_probe_is_403(client, judge_b_cookie):
    """The exact acceptance-suite probe: judge_b asking for judge_a's identity."""
    r = client.get("/api/judge/scores?judge_email=diego.herrera@example.org",
                   headers=judge_b_cookie)
    assert r.status_code == 403


def test_judge_may_self_identify(client, judge_a_cookie):
    """Passing your own identity is allowed (the acceptance suite relies on this)."""
    r = client.get("/api/judge/scores?judge_email=diego.herrera@example.org",
                   headers=judge_a_cookie)
    assert r.status_code == 200
    assert r.json()


def test_assignments_are_own_only(client, judge_a_cookie, judge_b_cookie):
    a = {row["project"] for row in client.get("/api/judge/assignments", headers=judge_a_cookie).json()}
    b = {row["project"] for row in client.get("/api/judge/assignments", headers=judge_b_cookie).json()}
    assert a and b and a != b, "different judges must see different assignment sets"


def _make_session(db, user_email: str, token: str) -> None:
    """Forge a session row with a known token (simulates a stolen/guessed cookie)."""
    from app.models import User, utcnow
    import datetime as dt

    user = db.query(User).filter(User.email == user_email).one()
    db.add(DbSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                     user_id=user.id, expires_at=utcnow() + dt.timedelta(days=1)))
    db.commit()


def test_tampered_session_token_is_rejected(client, judge_a_cookie, db_session):
    """A valid-looking token that is not in the sessions table must 401."""
    import uuid

    forged = uuid.uuid4().hex
    _make_session(db_session, "diego.herrera@example.org", forged)  # exists but wrong hash used below
    r = client.get("/api/judge/scores", headers={"Cookie": f"session={forged}x"})
    assert r.status_code == 401


def test_expired_session_is_rejected(client, db_session):
    from app.models import User, utcnow
    import datetime as dt
    import uuid

    token = uuid.uuid4().hex
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "diego.herrera@example.org").one()
        db.add(DbSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                         user_id=user.id, expires_at=utcnow() - dt.timedelta(seconds=1)))
        db.commit()
    r = client.get("/api/judge/scores", headers={"Cookie": f"session={token}"})
    assert r.status_code == 401


def test_deterministic_seed_tokens_match_printed_cookies():
    """The printed cookies in .dogfood.toml come from _seed_token — keep them stable."""
    expected_organizer = "91e0d703c0dcdda4b06db2bf97998b59"
    assert _seed_token("organizer") == expected_organizer
