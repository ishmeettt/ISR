"""Seed idempotency: rebooting the portal must never duplicate or mutate data."""
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Assignment, Evaluation, Event, Project, Team, User
from app.seed import _seed_token, load_and_seed


def _counts():
    with SessionLocal() as db:
        return {
            "events": db.scalar(select(func.count(Event.id))),
            "teams": db.scalar(select(func.count(Team.id))),
            "projects": db.scalar(select(func.count(Project.id))),
            "users": db.scalar(select(func.count(User.id))),
            "evaluations": db.scalar(select(func.count(Evaluation.id))),
            "assignments": db.scalar(select(func.count(Assignment.id))),
        }


def test_reseed_is_a_no_op():
    """Running the seed again on a seeded DB must not create anything.

    Exact event counts are asserted elsewhere; here the invariant is the
    DELTA: whatever exists before the reseed must be identical after.
    """
    before = _counts()
    # Demo mode seeds 41 fixture projects; other tests may have added more
    # (e.g. judge-added repos), so the floor is what we assert here — the
    # invariant under test is the before/after delta, not the absolute count.
    assert before["events"] >= 1 and before["projects"] >= 41

    with SessionLocal() as db:
        result = load_and_seed(db)
    assert result["seeded"] is False, "second seed must take the idempotent path"

    after = _counts()
    assert after == before, f"reseed mutated data: {before} -> {after}"


def test_seed_tokens_are_deterministic():
    """The four printed cookies must be stable across processes and restarts."""
    expected = {
        "organizer": "91e0d703c0dcdda4b06db2bf97998b59",
        "judge_a": "dae42f9e7001d0f7a6a27d27e86eb0b8",
        "judge_b": "225960e58b0bd011a87e787be5f9e2bf",
        "participant": "69e6a774b2c036ca34e758c4e8261867",
    }
    for role, token in expected.items():
        assert _seed_token(role) == token, f"token drift for {role}"


def test_seed_sessions_exist_and_resolve(client, db_session):
    """Every printed cookie must authenticate as the right role."""
    import hashlib

    expected_roles = {"organizer": "organizer", "judge_a": "judge", "judge_b": "judge",
                      "participant": "participant"}
    for role, role_name in expected_roles.items():
        token = _seed_token(role)
        row = db_session.query(DbSession := __import__("app.models", fromlist=["Session"]).Session) \
            .filter(DbSession.token_hash == hashlib.sha256(token.encode()).hexdigest()).one()
        assert row.user.role == role_name
