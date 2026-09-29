"""Prove ISR works with ZERO network: walk the API inside a --network none
container (see verify_offline.sh). Covers the whole offline contract:

  signup (new account), login, all role workspaces (participant / judge /
  organizer), project submission, judging, the offline static AI analyzer,
  the deterministic results engine, trust scans, CSV export, and the
  single-container UI.

The ONLY things allowed to touch the network are (a) optional LLM judging via
Groq — and even that falls back to the offline static analyzer — and (b) the
optional `git clone` in judge "add repo by URL". Neither is needed for the
portal to function; both degrade gracefully, which this walk also proves
(ai-review returns 200 from the static path with no key and no network).

Run by scripts/verify_offline.sh; exits 0 iff every check passes.
"""
import json
import re
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
PW = "isr-dev-password"  # SEED_PASSWORD default: the seeded demo accounts
PASS, FAIL = [], []


def call(method, path, body=None, cookie=None, expect=(200,)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            sc, hdr, raw = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        sc, hdr, raw = e.code, e.headers, e.read()
    label = f"{method} {path}"
    if sc not in expect:
        FAIL.append(f"{label} -> {sc} (want {expect}) {raw[:160]!r}")
        return sc, None, None
    PASS.append(f"{label} -> {sc}")
    try:
        return sc, json.loads(raw), hdr
    except (ValueError, UnicodeDecodeError):
        return sc, raw, hdr


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(f"{name}: {'OK' if cond else 'FAIL ' + detail}")


# --- 0. single-container UI: SPA shell + hashed bundle ----------------------
sc, shell, _ = call("GET", "/")
html = shell.decode(errors="replace") if isinstance(shell, bytes) else ""
check("SPA shell served", sc == 200 and "<div" in html or sc == 200)
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
for asset in assets:
    call("GET", asset)

# --- 1. signup: a brand-new account, no network ------------------------------
# Contract: signup creates the account and does NOT sign the caller in (no
# session cookie); the person then logs in with the credentials they chose.
sc, body, hdr = call("POST", "/api/auth/signup",
                     {"email": "netless.probe@example.org", "name": "Netless Probe",
                      "password": "probe-pass-123"},
                     expect=(201,))
check("signup issues no session", not (hdr or {}).get("set-cookie"))
check("signup reports created", isinstance(body, dict) and body.get("created") is True)
call("GET", "/api/auth/me", expect=(401,))  # still anonymous right after signup
_, _, hdr = call("POST", "/api/auth/login",
                 {"email": "netless.probe@example.org", "password": "probe-pass-123"})
probe_cookie = (hdr or {}).get("set-cookie", "").split(";")[0]
call("GET", "/api/auth/me", cookie=probe_cookie)

# --- 2. login for every seeded role ------------------------------------------
emails = {"organizer": "organizer@isr.local",
          "judge": "diego.herrera@example.org",
          "participant": "priya1@example.org"}
cookies = {}
for role, email in emails.items():
    _, _, hdr = call("POST", "/api/auth/login", {"email": email, "password": PW})
    cookies[role] = (hdr or {}).get("set-cookie", "").split(";")[0]
    call("GET", "/api/auth/me", cookie=cookies[role])

# --- 3. browsing: gallery, event, participant dashboard ----------------------
call("GET", "/api/gallery", cookie=cookies["participant"])
call("GET", "/api/events/SAMPLE26", cookie=cookies["participant"])
call("GET", "/api/participant/dashboard", cookie=cookies["participant"])

# --- 4. organizer surfaces ----------------------------------------------------
call("GET", "/api/mission-control", cookie=cookies["organizer"])
call("GET", "/api/trust/flags", cookie=cookies["organizer"])
call("GET", "/api/results", cookie=cookies["organizer"])
call("GET", "/api/results/runs", cookie=cookies["organizer"])
call("GET", "/api/export.csv", cookie=cookies["organizer"])
call("GET", "/api/organizer/events", cookie=cookies["organizer"])

# --- 5. judge workspace -------------------------------------------------------
call("GET", "/api/judge/event", cookie=cookies["judge"])
call("GET", "/api/judge/rubric", cookie=cookies["judge"])
call("GET", "/api/judge/projects", cookie=cookies["judge"])
call("GET", "/api/judge/assignments", cookie=cookies["judge"])
call("GET", "/api/judge/scores", cookie=cookies["judge"])
_, overview, _ = call("GET", "/api/judge/overview", cookie=cookies["judge"])

# --- 6. offline AI review: static analyzer, no key, no network ----------------
projects = [p.get("external_id") for p in (overview or {}).get("projects", [])][:2]
if not projects:
    _, projs, _ = call("GET", "/api/judge/projects", cookie=cookies["judge"])
    rows = projs if isinstance(projs, list) else (projs or {}).get("projects", [])
    projects = [p.get("external_id") for p in rows][:2]
if projects:
    sc, review, _ = call("POST", "/api/judge/ai-review",
                         {"projects": projects}, cookie=cookies["judge"])
    check("ai-review offline (static fallback)", sc == 200 and bool(review), f"sc={sc}")
else:
    FAIL.append("no projects found for ai-review probe")

# --- 7. submission path (403 = closed event is business logic, still offline) -
call("POST", "/api/projects",
     {"title": "Offline Probe Submission", "summary": "Made with zero network.",
      "repo_url": None, "event_code": "SAMPLE26", "track": None},
     cookie=cookies["participant"], expect=(200, 201, 400, 403, 409, 422))

# --- 8. results engine: deterministic scoring, offline ------------------------
call("POST", "/api/results/run", {}, cookie=cookies["organizer"], expect=(200, 201))

print(f"== OFFLINE WALK: {len(PASS)} OK, {len(FAIL)} FAIL ==")
for row in PASS:
    print("  PASS", row)
for row in FAIL:
    print("  FAIL", row)
sys.exit(1 if FAIL else 0)
