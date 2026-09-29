"""Event hosting: create (code + link), edit later, ownership, public lookup."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models import Event, User


def _organizer_email(db) -> str:
    return db.scalar(select(User.email).where(User.email == "organizer@isr.local"))


def test_seed_organizer_owns_fixture_event(client, organizer_cookie, db_session):
    rows = client.get("/api/organizer/events", headers=organizer_cookie).json()
    # Other tests may have created more events for this organizer; the fixture
    # event must be among them, owned and correctly described.
    ev = next(e for e in rows if e["code"] == "SAMPLE26")
    assert ev["name"] == "Sample Hack 2026"
    assert ev["project_count"] == 41
    assert ev["is_open"] is False, "fixture deadline is in the past"
    codes = [e["code"] for e in rows]
    assert len(codes) == len(set(codes)), "share codes must be unique per event"


def test_create_event_returns_unique_code_and_link(client, organizer_cookie, db_session):
    r = client.post("/api/organizer/events", headers=organizer_cookie, json={
        "name": "Test Hack Weekend",
        "description": "Created by the test suite",
        "judge_count": 5,
        # window straddles the real current date so is_open is True
        "submissions_open": "2026-09-01T09:00:00Z",
        "submissions_close": "2026-12-03T18:00:00Z",
        "judging_close": "2026-12-04T18:00:00Z",
        "tracks": ["AI", "Web"],
    })
    assert r.status_code == 201
    ev = r.json()
    assert len(ev["code"]) == 8 and ev["code"].isalnum()
    assert ev["share_link"] == f"/events/{ev['code']}"
    assert ev["judge_count"] == 5
    assert sorted(ev["tracks"]) == ["AI", "Web"]
    assert ev["is_open"] is True, "open in the past, close in the future -> open"

    # code is globally unique
    with SessionLocal() as db:
        codes = db.scalars(select(Event.code)).all()
    assert codes.count(ev["code"]) == 1


def test_create_event_rejects_inconsistent_windows(client, organizer_cookie):
    r = client.post("/api/organizer/events", headers=organizer_cookie, json={
        "name": "Backwards Event",
        "submissions_open": "2026-10-05T09:00:00Z",
        "submissions_close": "2026-10-01T18:00:00Z",
    })
    assert r.status_code == 400
    assert "before" in r.json()["detail"]


def test_edit_event_updates_windows_and_judge_count(client, organizer_cookie):
    created = client.post("/api/organizer/events", headers=organizer_cookie, json={
        "name": "Editable Hack",
        "submissions_close": "2026-11-01T18:00:00Z",
        "judge_count": 3,
    }).json()

    r = client.patch(f"/api/organizer/events/{created['id']}", headers=organizer_cookie, json={
        "judge_count": 7,
        "submissions_close": "2026-11-15T18:00:00Z",
        "description": "Edited after creation",
    })
    assert r.status_code == 200
    ev = r.json()
    assert ev["judge_count"] == 7
    assert ev["submissions_close"].startswith("2026-11-15")
    assert ev["description"] == "Edited after creation"

    # invalid edit (close pushed past judging_close) is refused and unchanged
    client.patch(f"/api/organizer/events/{created['id']}", headers=organizer_cookie,
                 json={"judging_close": "2026-12-10T18:00:00Z"})
    bad = client.patch(f"/api/organizer/events/{created['id']}", headers=organizer_cookie, json={
        "submissions_close": "2026-12-20T18:00:00Z",  # after judging_close
    })
    assert bad.status_code == 400
    again = client.get(f"/api/events/{created['code']}", headers=organizer_cookie).json()
    assert again["submissions_close"].startswith("2026-11-15")


def test_public_event_lookup_by_code(client, organizer_cookie):
    r = client.get("/api/events/SAMPLE26", headers=organizer_cookie)
    assert r.status_code == 200
    pub = r.json()
    assert pub["name"] == "Sample Hack 2026"
    assert pub["team_count"] == 40
    assert pub["code"] == "SAMPLE26"
    assert client.get("/api/events/ZZZZ9999", headers=organizer_cookie).status_code == 404


def test_second_organizer_cannot_edit_someone_elses_event(client, db_session):
    """Ownership matters: another organizer gets 403, not just a hidden button."""
    from fastapi.testclient import TestClient

    from app.core.security import hash_password
    from app.seed import _get_or_create_user, _seed_token
    from app.models import Session as DbSession, utcnow
    import datetime as dt
    import hashlib

    with SessionLocal() as db:
        rival = _get_or_create_user(db, "rival@isr.local", "Rival Organizer",
                                    "organizer", hash_password("isr-dev-password"))
        token = "rival-session-token-0001"
        db.add(DbSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                         user_id=rival.id, expires_at=utcnow() + dt.timedelta(days=1)))
        db.commit()

    fixture_event_id = db_session.scalar(select(Event.id).where(Event.external_id == "evt_01"))
    with TestClient(app) as c:
        r = c.patch(f"/api/organizer/events/{fixture_event_id}",
                    headers={"Cookie": f"session={token}"},
                    json={"name": "Hijacked Event"})
    assert r.status_code == 403
