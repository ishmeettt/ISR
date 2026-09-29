"""Per-event AI key (organizer-optional Groq integration).

Contract: the organizer may attach a key to their event; the API never
returns it (only an ai_configured flag); judges' AI reviews use it when
present and silently fall back to offline static analysis when absent or
when Groq is unreachable (tests run offline, so the fallback is the
expected path there).
"""
from tests.conftest import _cookie


def _create_event(client, **overrides) -> dict:
    payload = {
        "name": "AI Key Event",
        "submissions_close": "2027-01-01T00:00:00Z",
        "tracks": ["Open"],
        **overrides,
    }
    r = client.post("/api/organizer/events", json=payload, headers=_cookie("organizer"))
    assert r.status_code == 201, r.text
    return r.json()


def test_event_accepts_key_and_never_returns_it(client, db_session):
    created = _create_event(client, ai_api_key="gsk_secret_key_for_testing")
    assert created["ai_configured"] is True
    blob = str(created)
    assert "gsk_secret_key_for_testing" not in blob, "the key must never be returned"

    # ...and the stored value round-trips to the DB.
    from sqlalchemy import select
    from app.models import Event
    ev = db_session.scalar(select(Event).where(Event.id == created["id"]))
    assert ev.ai_api_key == "gsk_secret_key_for_testing"


def test_event_without_key_reports_unconfigured(client):
    created = _create_event(client)
    assert created["ai_configured"] is False


def test_edit_can_set_and_clear_key(client, db_session):
    created = _create_event(client)
    eid = created["id"]

    r = client.patch(f"/api/organizer/events/{eid}", json={"ai_api_key": "gsk_new_key"},
                     headers=_cookie("organizer"))
    assert r.status_code == 200
    assert r.json()["ai_configured"] is True
    db_session.expire_all()
    from sqlalchemy import select
    from app.models import Event
    assert db_session.scalar(select(Event).where(Event.id == eid)).ai_api_key == "gsk_new_key"

    r2 = client.patch(f"/api/organizer/events/{eid}", json={"ai_api_key": ""},
                      headers=_cookie("organizer"))
    assert r2.status_code == 200
    assert r2.json()["ai_configured"] is False
    db_session.expire_all()
    assert db_session.scalar(select(Event).where(Event.id == eid)).ai_api_key is None


def test_ai_review_falls_back_without_key(client):
    """No key configured: reviews still work, offline static mode."""
    r = client.post("/api/judge/ai-review", json={"projects": ["prj_03"]},
                    headers=_cookie("judge_a"))
    assert r.status_code == 200
    body = r.json()
    assert body["advisory"] is True
    stored = client.get("/api/judge/ai-review/prj_03", headers=_cookie("judge_a")).json()
    assert stored["result"]["mode"] == "static"


def test_llm_review_payload_normalization():
    """The Groq response parser accepts real-shaped payloads, drops junk."""
    from app.services.groq import _normalize

    parsed = _normalize({
        "summary": "Solid CRUD app with clean layering.",
        "best_parts": ["Clear module boundaries", 42, None],
        "errors": [{"file": "app.py", "note": "bare except"}, "free-form string"],
        "loopholes": [{"note": "no auth on admin routes"}],
        "suggestions": [],
        "unexpected": "ignored",
    })
    assert parsed["summary"].startswith("Solid")
    assert parsed["best_parts"] == ["Clear module boundaries"]
    assert parsed["errors"][1] == {"file": "-", "note": "free-form string"}
    assert parsed["loopholes"][0]["file"] == "-"
    assert parsed["suggestions"] == []
    assert "unexpected" not in parsed


def test_review_with_optional_llm_falls_back_on_error(monkeypatch):
    """A broken Groq call must never break judging."""
    from app.services import groq

    monkeypatch.setattr(groq, "llm_review", lambda *a, **k: None)
    payload = groq.review_with_optional_llm(
        "gsk_whatever", "Some Project", "summary", "https://example.org/repo/01",
    )
    assert payload["mode"] == "static"
    assert "llm" not in payload
    assert payload["advisory"] is True
