"""RBAC: every /api endpoint must enforce the role matrix on the server.

The inventory test at the bottom fails when someone adds a route without
listing it here — new endpoints must be added to ENDPOINTS explicitly, with
their expected per-role status codes, or the suite refuses to pass.

Note: routers are included lazily, so app.routes contains _IncludedRouter
wrappers that carry no path/methods themselves; the walk must descend into
original_router.routes (this guard was once vacuous because of that).
"""
from sqlalchemy import select

from app.main import app

ROLES = ("anon", "participant", "judge", "organizer")

# method, full path template, expected status per role, path args resolver.
# Path args are resolved lazily (ids depend on seeded data).
# matrix=False documents the route without walking it in the shared matrix
# (logout deletes sessions, so it gets a dedicated client below).
ENDPOINTS: list[dict] = []


def ep(method: str, template: str, expected: dict[str, int], args=None, matrix: bool = True):
    ENDPOINTS.append({"method": method, "template": template, "expected": expected,
                      "args": args, "matrix": matrix})


# --- auth: login is anonymous by design; everything else requires a session ---
# With no body, login fails validation (422) for every role uniformly; login
# success/failure semantics get dedicated tests below.
ep("POST", "/api/auth/login", {"anon": 422, "participant": 422, "judge": 422,
                               "organizer": 422})
ep("GET", "/api/auth/me", {"anon": 401, "participant": 200, "judge": 200, "organizer": 200})
ep("POST", "/api/auth/logout", {"anon": 401, "participant": 200, "judge": 200,
                                "organizer": 200}, matrix=False)

# --- gallery: behind login since the welcome screen landed; all signed-in roles read it ---
ep("GET", "/api/gallery", {"anon": 401, "participant": 200, "judge": 200, "organizer": 200})

# --- signup: anonymous by design; validation failures are 422 for everyone ---
ep("POST", "/api/auth/signup", {"anon": 422, "participant": 422, "judge": 422,
                                 "organizer": 422})

# --- submissions: any authenticated user may attempt; closed event refuses 403 ---
ep("POST", "/api/projects", {"anon": 401, "participant": 403, "judge": 403, "organizer": 403})

# --- judge workspace + evaluator flow: judge-only, all judge-scoped ---
ep("GET", "/api/judge/event", {"anon": 401, "participant": 403, "judge": 200, "organizer": 403})
ep("GET", "/api/judge/scores", {"anon": 401, "participant": 403, "judge": 200, "organizer": 403})
ep("GET", "/api/judge/assignments", {"anon": 401, "participant": 403, "judge": 200,
                                     "organizer": 403})
ep("GET", "/api/judge/rubric", {"anon": 401, "participant": 403, "judge": 200, "organizer": 403})
ep("GET", "/api/judge/projects", {"anon": 401, "participant": 403, "judge": 200,
                                  "organizer": 403})
ep("GET", "/api/judge/overview", {"anon": 401, "participant": 403, "judge": 200,
                                   "organizer": 403})
# GET before POST on purpose: prj_04 is reviewed by another judge, so judge_a
# has no AI review of their own for it (404 proves the review is judge-private).
# prj_04 is reviewed by another judge (never by judge_a in any test), so
# judge_a having no AI review of their own for it (404) proves privacy.
ep("GET", "/api/judge/ai-review/{project_external_id}", {"anon": 401, "participant": 403,
                                                         "judge": 404, "organizer": 403},
   args=lambda db: {"project_external_id": "prj_04"})
ep("POST", "/api/judge/ai-review", {"anon": 401, "participant": 403, "judge": 200,
                                    "organizer": 403})
# Ephemeral paste-a-link review: judge-only, never persisted.
ep("POST", "/api/judge/ai-review/preview", {"anon": 401, "participant": 403, "judge": 200,
                                    "organizer": 403})
# Handler validation (non-GitHub URL) is a 400 for every role that reaches it.
# (No body at all would be a 422 for everyone, like the other POSTs.)
ep("POST", "/api/judge/repos/add", {"anon": 401, "participant": 403, "judge": 400,
                                     "organizer": 403})
# Run-it-locally helpers: judge-only reads. The runbook answers 200 with
# found:false when the probe project has no local checkout; the terminal
# script is a hard 404 in that case.
ep("GET", "/api/judge/repos/{project_external_id}/runbook",
   {"anon": 401, "participant": 403, "judge": 200, "organizer": 403},
   args=lambda db: {"project_external_id": "prj_04"})
ep("GET", "/api/judge/repos/{project_external_id}/terminal-script",
   {"anon": 401, "participant": 403, "judge": 404, "organizer": 403},
   args=lambda db: {"project_external_id": "prj_04"})
# prj_03 carries no evaluation from any test, so the matrix POST is the 201 path.
ep("POST", "/api/judge/evaluate", {"anon": 401, "participant": 403, "judge": 201,
                                   "organizer": 403})

# --- participant dashboard: participant-only ---
ep("GET", "/api/participant/dashboard", {"anon": 401, "participant": 200, "judge": 403,
                                         "organizer": 403})

# --- results: organizer-only ---
ep("POST", "/api/results/run", {"anon": 401, "participant": 403, "judge": 403, "organizer": 201})
ep("GET", "/api/results", {"anon": 401, "participant": 403, "judge": 403, "organizer": 200})
ep("GET", "/api/results/runs", {"anon": 401, "participant": 403, "judge": 403, "organizer": 200})
ep("GET", "/api/results/why/{run_id}/{project_external_id}", {"anon": 401, "participant": 403,
                                                              "judge": 403, "organizer": 200},
   args=lambda db: {"run_id": _latest_run_id(db), "project_external_id": "prj_01"})

# --- trust: organizer-only ---
ep("GET", "/api/trust/flags", {"anon": 401, "participant": 403, "judge": 403, "organizer": 200})
ep("POST", "/api/trust/scan", {"anon": 401, "participant": 403, "judge": 403, "organizer": 201})
ep("POST", "/api/trust/flags/{flag_id}/{disposition}", {"anon": 401, "participant": 403,
                                                        "judge": 403, "organizer": 200},
   args=lambda db: {"flag_id": _open_flag_id(db), "disposition": "dismissed"})

# --- events: organizer management + signed-in public lookup ---
ep("GET", "/api/organizer/events", {"anon": 401, "participant": 403, "judge": 403,
                                    "organizer": 200})
ep("POST", "/api/organizer/events", {"anon": 401, "participant": 403, "judge": 403,
                                     "organizer": 400})
# No-op edit (same judge_count): proves the organizer reaches the handler.
ep("PATCH", "/api/organizer/events/{event_id}", {"anon": 401, "participant": 403,
                                                 "judge": 403, "organizer": 200},
   args=lambda db: {"event_id": _fixture_event_id(db)})
ep("GET", "/api/events/{code}", {"anon": 401, "participant": 200, "judge": 200,
                                 "organizer": 200},
   args=lambda db: {"code": "SAMPLE26"})

# --- mission control: organizer-only ---
ep("GET", "/api/mission-control", {"anon": 401, "participant": 403, "judge": 403,
                                   "organizer": 200})

# --- exports: organizer-only ---
ep("GET", "/api/export.csv", {"anon": 401, "participant": 403, "judge": 403, "organizer": 200})

# --- health: public ---
ep("GET", "/api/health", {"anon": 200, "participant": 200, "judge": 200, "organizer": 200})


def _latest_run_id(db) -> int:
    from app.models import NormalizationRun

    return db.scalar(select(NormalizationRun.id).order_by(NormalizationRun.id.desc()))


def _fixture_event_id(db) -> int:
    from app.models import Event

    return db.scalar(select(Event.id).where(Event.external_id == "evt_01"))


def _open_flag_id(db) -> int:
    """Trust flags only exist after a scan; materialize them for the matrix."""
    from app.models import TrustFlag
    from app.services.trust import scan

    if db.scalar(select(TrustFlag.id).where(TrustFlag.status == "open")) is None:
        scan(db)
        db.commit()
    return db.scalar(select(TrustFlag.id).where(TrustFlag.status == "open"))


def _api_routes():
    """Yield (method, path) for every /api route, including sub-routes hidden
    inside lazy _IncludedRouter wrappers (they carry no path/methods of their
    own — only original_router.routes does)."""
    for route in app.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _routes_of(original.routes)
        else:
            yield from _routes_of([route])


def _routes_of(routes):
    for route in routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        for method in getattr(route, "methods", {"GET"}):
            if method in ("HEAD", "OPTIONS"):
                continue
            yield method, path


COOKIES = {}


def test_inventory_is_complete(client):
    """Every registered /api route must appear in the RBAC inventory."""
    documented = {(e["method"], e["template"]) for e in ENDPOINTS}
    registered = set(_api_routes())
    registered.discard(("GET", "/api/health"))  # trivially public, documented too
    missing = registered - documented
    assert not missing, f"routes missing from the RBAC inventory: {sorted(missing)}"


def test_login_rejects_wrong_credentials():
    # A dedicated client: a real login would plant a cookie in the shared
    # client's jar and override the explicit per-request Cookie headers used
    # by the matrix below.
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.post("/api/auth/login",
                   json={"email": "organizer@isr.local", "password": "definitely-wrong"})
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


def test_login_accepts_correct_credentials_and_sets_cookie():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        r = c.post("/api/auth/login",
                   json={"email": "organizer@isr.local", "password": "isr-dev-password"})
    assert r.status_code == 200
    assert r.json()["role"] == "organizer"
    assert "session=" in r.headers["set-cookie"]


def test_logout_end_to_end():
    """Logout must delete the server-side session, not just the cookie.

    Runs on a dedicated client with a real login. Uses the seeded ADMIN:
    logout deletes every session of that user, so it must not be a role whose
    seed session the shared RBAC matrix depends on (that bit us with the
    participant). Each TestClient creation re-runs the (idempotent) seed.
    """
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={
            "email": "admin@isr.local", "password": "isr-dev-password",
        }).status_code == 200
        assert c.get("/api/auth/me").status_code == 200
        assert c.post("/api/auth/logout").status_code == 200
        assert c.get("/api/auth/me").status_code == 401, "session must be dead server-side"


def _request(client, cookies, method, path):
    client.cookies.clear()  # never let a jar shadow the explicit role header
    headers = dict(cookies) if cookies else {}
    json = None
    if (method, path) == ("POST", "/api/projects"):
        json = {"title": "rbac-probe", "summary": "probe"}
    elif (method, path) == ("POST", "/api/organizer/events"):
        # deliberately inconsistent windows so the organizer row exercises the
        # business-logic 400 rather than a validation 422
        json = {"name": "RBAC Probe Event",
                "submissions_open": "2026-06-01T00:00:00Z",
                "submissions_close": "2026-01-01T00:00:00Z"}
    elif method == "PATCH" and path.startswith("/api/organizer/events/"):
        json = {"judge_count": 3}  # no-op edit: reach the handler, change nothing
    elif (method, path) == ("POST", "/api/judge/ai-review"):
        json = {"projects": ["prj_03"]}
    elif (method, path) == ("POST", "/api/judge/ai-review/preview"):
        json = {"repo_url": "https://github.com/example/rbac-probe"}
    elif (method, path) == ("POST", "/api/judge/repos/add"):
        json = {"repo_url": "https://gitlab.com/not-github/probe"}  # reaches handler -> 400
    elif (method, path) == ("POST", "/api/judge/evaluate"):
        json = {"project": "prj_03", "scores": {"functionality": 4, "quality": 4,
                                                "innovation": 4},
                "comment": "rbac probe"}
    return client.request(method, path, headers=headers, json=json)


def test_role_matrix(client, participant_cookie, judge_a_cookie, judge_b_cookie,
                     organizer_cookie, db_session):
    """Walk the full matrix: every endpoint x every role must match expectation."""
    COOKIES.update({
        "anon": None,
        "participant": participant_cookie,
        "judge": judge_a_cookie,
        "organizer": organizer_cookie,
    })
    mismatches = []
    for e in ENDPOINTS:
        if not e["matrix"]:
            continue
        path = e["template"]
        if e["args"]:
            path = path.format(**e["args"](db_session))
        for role in ROLES:
            got = _request(client, COOKIES[role], e["method"], path).status_code
            want = e["expected"][role]
            if got != want:
                mismatches.append(f"{e['method']} {path} as {role}: got {got}, want {want}")
    assert not mismatches, "RBAC violations:\n" + "\n".join(mismatches)
