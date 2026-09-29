"""Participant dashboard: own data only, never judge identities or scores."""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import User


def _as(client, email):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        from app.seed import _seed_token
        # The seed tokens are per-role, not per-user; priya1 is the participant seed.
        assert email == "priya1@example.org", "participant seed session belongs to priya1"
        return {"Cookie": f"session={_seed_token('participant')}"}


def test_participant_dashboard_shows_own_team_and_project(client):
    r = client.get("/api/participant/dashboard", headers=_as(client, "priya1@example.org"))
    assert r.status_code == 200
    d = r.json()
    assert d["user"]["email"] == "priya1@example.org"
    assert d["totals"]["teams"] == 1 and d["totals"]["projects"] >= 1

    team = d["teams"][0]
    assert team["event"]["name"] == "Sample Hack 2026"
    assert team["event"]["closed"] is True, "fixture deadline is in the past"
    assert team["name"] == "NorthKiln"
    member_emails = {m["email"] for m in team["members"]}
    assert "priya1@example.org" in member_emails
    project = team["projects"][0]
    assert project["external_id"] == "prj_01" and project["title"] == "Glass Signal"
    assert project["track"] == "Security"
    assert project["review_count"] >= 1, "prj_01 has three seeded reviews"


def test_dashboard_never_exposes_judge_data(client):
    """The payload must not contain judge names, emails, scores, or comments."""
    r = client.get("/api/participant/dashboard", headers=_as(client, "priya1@example.org"))
    raw = r.text.lower()
    for banned in ('"judge', "z_score", "raw_weighted", "comment", "diego.herrera"):
        assert banned not in raw, f"judge-related data leaked into participant payload: {banned}"


def test_dashboard_rejects_judge_and_organizer(client, judge_a_cookie, organizer_cookie):
    assert client.get("/api/participant/dashboard", headers=judge_a_cookie).status_code == 403
    assert client.get("/api/participant/dashboard", headers=organizer_cookie).status_code == 403
