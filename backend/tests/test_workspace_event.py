"""Workspace event resolution: the judge's last-entered code wins.

Regression for: organizer creates a brand-new (empty) event, a judge logs in
with ITS code — but the evaluator dashboard still showed the OLD event,
because workspace data resolved "newest event that has projects" and ignored
the code the judge had just linked. The workspace must follow the explicit
link, even when the event is still empty.

Uses jdg_01 (tomas.varga@example.org) — a fixture judge no other test module
asserts on — and the session cookie returned by the code-login itself, so the
test never depends on (or pollutes) the shared client cookie jar.
"""
from tests.conftest import _cookie

NEW_EVENT = {
    "name": "Brand New Cup",
    "description": "Created to prove an empty linked event wins the workspace.",
    "judge_count": 2,
    "submissions_close": "2026-12-01T18:00:00Z",
    "tracks": ["Open"],
}

JUDGE_EMAIL = "tomas.varga@example.org"


def _login_with_code(client, email: str, code: str) -> str:
    """Log in with an event code; return the session cookie it issued."""
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": "isr-dev-password", "event_code": code},
    )
    assert r.status_code == 200, r.text
    cookie = r.headers.get("set-cookie", "").split(";")[0]
    assert cookie.startswith("session=")
    return cookie


def test_empty_newly_linked_event_wins_the_workspace(client, organizer_cookie):
    # Organizer creates a fresh, EMPTY event (no projects).
    created = client.post("/api/organizer/events", headers=organizer_cookie,
                          json=NEW_EVENT)
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    assert code, "new events must get a share code"

    cookie = {"Cookie": _login_with_code(client, JUDGE_EMAIL, code)}

    # The whole workspace now points at the new (still empty) event —
    # NOT at the older fixture event that merely has projects.
    ov = client.get("/api/judge/overview", headers=cookie).json()
    assert ov["event"]["code"] == code
    assert ov["totals"]["projects"] == 0 and ov["projects"] == []

    header = client.get("/api/judge/event", headers=cookie).json()
    assert header["event"]["code"] == code
    assert header["via"] == "linked"

    projects = client.get("/api/judge/projects", headers=cookie).json()
    assert projects == []

    # The default rubric materializes for the new event on first open.
    rubric = client.get("/api/judge/rubric", headers=cookie)
    assert rubric.status_code == 200
    assert rubric.json()["criteria"], "default rubric must be usable immediately"

    # Eligibility followed the link: scoring this event is allowed (no
    # read-only 403 on the rubric/overview path used by the dashboard).


def test_judge_without_code_login_still_gets_browse_default(client):
    """A judge who never entered a code keeps the old behavior: newest event
    that actually has projects (the fixture event), not an empty one."""
    ov = client.get("/api/judge/overview", headers=_cookie("judge_a")).json()
    assert ov["event"] is not None
    assert ov["totals"]["projects"] > 0
