# ISR — Intelligent Submission & Review

**RUN → JUDGE → VERIFY → EXPLAIN.** Self-hosted hackathon competition infrastructure:
teams submit projects, judges review and score them with AI-assisted static analysis,
a deterministic engine (FairScore) ranks the results, and every action lands in an
append-only audit trail. The whole portal — API, UI, and database — runs in **one
container, fully offline**.

---

## 🔑 Demo accounts (try it in 30 seconds)

Open the app, pick a card, and sign in — **password for every account:
`isr-dev-password`**.

| Role | Email | What you'll see |
|---|---|---|
| **Organizer** | `organizer@isr.local` | My Events, Mission Control, Results, Trust Center |
| **Evaluator (judge A)** | `diego.herrera@example.org` | Evaluator dashboard |
| **Evaluator (judge B)** | `jonas.vogel@example.org` | Evaluator dashboard |
| **Participant** | `priya1@example.org` | Public gallery (participant dashboards were removed) |
| **Admin** | `admin@isr.local` | Same powers as organizer |

**Two demo events are on the instance right now** — enter the code on the
Evaluator card at login to open that event's workspace:

| Event code | Event | State |
|---|---|---|
| **`SAMPLE26`** | Sample Hack 2026 | **Ships with the fixture** — 41 seeded projects and 126 evaluations; submissions closed (good for browsing scores, results, Trust Center, exports) |
| **`KYF5ES5P`** | DogFood | **Empty event created live on the demo instance** (not in the fixture — a fresh install won't have it). On your own instance, create an event and use *its* code |

Tip: judges can switch the event they land in by logging in again with the other
code. Sign-ups create participant accounts (created → then back to the login page
→ sign in).

---

## How the app works

ISR has three roles and one flow:

```
        RUN                    JUDGE                     VERIFY                EXPLAIN
Organizer hosts  →  Teams submit projects   →  Judges review & score  →  FairScore ranks,
an event            (deadline enforced         (offline AI analysis       Trust Center audits,
                    server-side)               + human marks)             every step is logged
```

| Piece | What it is |
|---|---|
| **Backend** | FastAPI + SQLAlchemy 2 (SQLite in the offline image, Postgres under compose). Serves the API *and* the UI from one process. |
| **Frontend** | React + TypeScript + Vite, prebuilt into `frontend/dist` and baked into the image — no node/npm needed to run. |
| **Database** | SQLite at `/data/isr.db` inside the `isr_data` volume. All users, events, projects, evaluations, audits. |
| **Auth** | Email + password (PBKDF2), HttpOnly session cookie, 7-day sessions. |
| **AI review** | Deterministic static analyzer (always works, fully offline) + optional Groq LLM judgment when the organizer sets a per-event key. The machine **never** assigns marks — AI output is advisory only. |
| **Results** | FairScore: per-judge z-score normalization, immutable reproducible runs, a `Why this rank?` endpoint that re-derives every number. |
| **Trust Center** | Anomaly detectors (uniform-score judges, low coverage, out-of-track reviews, duplicates) that flag findings for organizer disposition. Flags never alter scores. |

---

## Quick start (Windows — desktop app)

One-time setup: run the two `docker build` steps from *Building from source*
below (a plain clone is enough — no Node.js needed). Then ISR runs like any
normal Windows program:

1. **Double-click the `ISR` shortcut on the Desktop** (or `desktop\Start ISR.bat`).
2. The launcher starts Docker inside WSL Ubuntu, boots the `isr` container, waits
   for the engine to answer, and opens ISR in its own app window (no browser
   chrome, own taskbar icon).
3. Log in with a demo account (table at the top) or **Create account**.
4. **`desktop\Stop ISR.bat`** stops the engine when you're done.

The launcher also installs the **ISR Keepalive** scheduled task automatically
(no admin rights): a hidden watchdog that keeps the WSL2 VM and the container
up, so `localhost:8080` survives app and machine restarts (box below).

Data persists across restarts in the `isr_data` / `isr_repos` volumes. Launcher
problems? Read `%LOCALAPPDATA%\ISR\launcher.log`.

### "Hmmm… can't reach this page" — why it happened, and the permanent fix

The portal lives in a Docker container inside WSL2. WSL shuts the whole Linux VM
down ~60 s after its last client exits, and **every restart of the Freebuff app
(or any other launcher) killed the hidden "WSL pin" that kept the VM open** —
taking the `localhost:8080` port-forward with it. The container and all data
were always fine; nothing was ever booted to bring the VM back, so the browser
showed `ERR_CONNECTION_REFUSED` again and again.

The permanent fix is the **ISR Keepalive** watchdog, owned by Windows Task
Scheduler (installed automatically, no admin rights):

- starts hidden at every **logon**, re-launches every 5 min if killed, and is
  restarted by Windows if it crashes — it belongs to the OS, so restarting
  Freebuff or any other app cannot take it down with them;
- every 30 s it re-pins WSL, ensures the `isr` container is running (boots
  Docker inside WSL if needed), and probes `http://127.0.0.1:8080/api/health`;
- a full `wsl --shutdown`-grade outage self-heals in **about a minute**
  (verified: DOWN → UP 200 in 62 s).

Reinstall/repair it any time: `powershell -File desktop\isr-keepalive-install.ps1`.
Activity log: `%LOCALAPPDATA%\ISR\keepalive.log`. `desktop\Stop ISR.bat`
suspends the watchdog (flag file) until the next Start ISR.

## Start from a fresh clone (any OS with Docker)

Four commands, no Node.js needed (the prebuilt UI ships in the repo):

```bash
git clone <this-repo>
cd isr                # the folder git just created (any name works)

# build (two images; the first installs all Python deps)
docker build -f backend/Dockerfile -t isr-backend:latest .
docker build -f Dockerfile.offline -t isr-offline:latest .

# run — with the demo data (Sample Hack 2026 + accounts from the table at the top)
docker run -d --name isr -p 8080:8000 \
  -v isr_data:/data -v isr_repos:/repos \
  -v "$PWD/fixtures.json:/app/fixtures.json:ro" \
  -e SEED_DEMO=1 --restart unless-stopped isr-offline:latest
```

(PowerShell: use `${PWD}\fixtures.json` in the mount.)

Then open **http://localhost:8080** (interactive API docs at `/docs`) and sign
in with any account from the table at the top — password `isr-dev-password`.
First boot seeds the database; every later boot reuses the `isr_data` volume.

- **No demo data?** Drop the `fixtures.json` mount and the `SEED_DEMO=1` line —
  the portal boots with the starter accounts only and the organizer hosts
  their own events.
- Judge-added repo clones live in the `isr_repos` volume; both volumes survive
  container replacement.
- Prefer the classic three-container stack (nginx :8080 → backend :8000 →
  Postgres)? `docker compose up --build`.
- On Windows you can skip all of this and use the desktop launcher above —
  it does the same thing inside WSL and adds a self-healing watchdog.

## Building from source

```bash
# 0. optional: rebuild the UI bundle (needs Node once). A clone already ships
#    the prebuilt bundle in frontend/dist, so you can skip this step.
cd frontend && npm install && npm run build && cd ..

# 1. build the backend base, then the offline image (no registry access needed)
docker build -f backend/Dockerfile -t isr-backend:latest .
docker build -f Dockerfile.offline -t isr-offline:latest .

# 2. run — copy the docker run command from "Start from a fresh clone" above
#    (it includes the demo-data flags) — or on Windows, double-click the ISR shortcut
```

---

## Demo accounts

**Password for every account: `isr-dev-password`** (override with `SEED_PASSWORD`).

| Role | Email | Who they are |
|---|---|---|
| **Organizer** | `organizer@isr.local` | Hosts events, runs results, works Trust Center & Mission Control, exports CSV |
| **Judge A** | `diego.herrera@example.org` | Diego Herrera — judge for Developer tools & Education tracks |
| **Judge B** | `jonas.vogel@example.org` | Jonas Vogel — judge for Accessibility & Developer tools tracks |
| **Participant** | `priya1@example.org` | Priya One — member of team NorthKiln |
| **Admin** | `admin@isr.local` | Same powers as organizer |

New accounts created via **Create account** always join as **participants**;
judges and organizers are provisioned by seeding/`docker exec`, not by signup.

### Demo data (Sample Hack 2026)

Run the portal with the DOGFOOD 2026 fixture seeded by adding `SEED_DEMO=1`
and mounting `fixtures.json` at `/app/fixtures.json` — exactly what the
"Start from a fresh clone" quick start does:

- Event **Sample Hack 2026**, share code **`SAMPLE26`**, 8 tracks, 40 teams,
  **41 projects**, 126 seeded evaluations (submissions closed 2026-03-01 —
  new submissions are refused server-side, which is the intended demo state).
- Judges can pass the event code at login (`SAMPLE26`) to link themselves to the event.
- The backend also prints deterministic session cookies at boot (they match
  `.dogfood.toml` and survive restarts) — handy for API testing.

Without `SEED_DEMO=1` the same accounts exist but the portal starts empty.

---

## Step-by-step guide

### 1. Log in
Open the app → sign in with email + password (`isr-dev-password`). Judges: pick the
**Evaluator** card to also enter the event code. Or **Sign up** to create a
participant account — signup creates the account in the database and returns you
to the login page to sign in. Signed-in users land on their workspace (or the
public **Gallery**, searchable by everyone).

### 2. Organizer — host an event
Log in as the organizer → **My Events** → create an event with name, description,
tracks, and submission windows. ISR assigns a unique **share code** automatically.
Judges enter that code at login to link themselves; participants submit while the
event is open. When submissions close, the deadline is enforced by the backend
(late POSTs get 403), not hidden in the UI.

### 3. Judge — review and score
Log in as a judge → **My Reviews**:
1. **Assignments** — the projects you're eligible for (by track).
2. **AI evaluate** — runs the offline static analyzer over the repo (real errors,
   security loopholes, improvements, run hints). With the event's Groq key
   configured you additionally get full LLM judgment — strengths, risks,
   suggestions, and *advisory* suggested scores.
3. **Score** — rubric: `functionality` (40%), `quality` (35%), `innovation` (25%),
   each 0–5, plus a comment. Submitting again **revises** your evaluation (upsert,
   audited as `EVALUATION_REVISED`).
4. Judge isolation is server-side: `/api/judge/scores` only ever returns *your*
   evaluations; cross-judge reads are rejected with 403.

### 4. Organizer — results, trust, exports
- **Results** → *Run FairScore*: deterministic z-score normalization over all
  submitted evaluations; immutable run history; per-project **Why this rank?**
  explanation. Ranking is blind to judge identity (fairness by construction).
- **Trust Center** → scan for anomalies → resolve or dismiss flags (every
  disposition is audited; flags never change scores).
- **Mission Control** → one dashboard: event health, judging progress, judge
  workload, coverage gaps, trust summary, run history.
- **Export** → CSV of all evaluations.

### 5. Participant — submit and watch
While an event is open, participants submit title, summary, repo link, and track.
After close, everything is browsable in the **Gallery** with review counts.

### 6. What needs the internet?
Almost nothing. The portal works **fully offline** — signup, logins, submissions,
judging, AI static analysis, results, exports. The only optional network features:

| Feature | Offline behavior |
|---|---|
| Groq LLM judging | Skipped automatically — falls back to the offline static analyzer |
| *Add repo by GitHub link* (judge) | Clone fails gracefully with a note; use a local checkout or the baked-in probe repos instead |

To re-verify the guarantee any time:

```bash
bash scripts/verify_offline.sh   # boots a throwaway --network none container
                                 # and walks every API route: must pass 31/31
```

---

## Configuration reference

| Env var | Default | Purpose |
|---|---|---|
| `SEED_DEMO` | unset | `1` seeds the Sample Hack 2026 fixture (needs `fixtures.json`) |
| `SEED_PASSWORD` | `isr-dev-password` | Shared password of the seeded accounts |
| `SEED_SESSION_SECRET` | `isr-dogfood-2026` | Deterministic boot-time session cookies |
| `DATABASE_URL` | SQLite `/data/isr.db` in the offline image | Any SQLAlchemy URL (compose uses Postgres) |
| `ISR_GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model for LLM judgment (per-event key set via the API) |
| `ISR_SERVE_UI` | `1` in the offline image | Serve `frontend/dist` from the API process |

## Verification & testing

```bash
bash scripts/smoke_offline.sh http://localhost:8080   # end-to-end API smoke test
bash scripts/verify_offline.sh                        # zero-network guarantee (network-none container)
python3 run.py .dogfood.toml > acceptance-report.txt  # T1/T2 acceptance checks vs a running portal
cd backend && python -m pytest                        # unit/API tests (demo-mode fixtures)
```

## Data & persistence

- `isr_data` volume → SQLite DB (`/data/isr.db`): users, events, evaluations, audits.
- `isr_repos` volume → judge-added repo checkouts (`/repos`).
- Backup: `docker exec isr tar -c -C /data isr.db > backup.tar` (WSL: `wsl docker exec ...`).
- The container restarts automatically with the Docker engine (`--restart unless-stopped`).

## Project layout

- `backend/` — FastAPI app: `app/models/` (schema), `app/routers/` (API),
  `app/core/` (config/db/security/audit), `app/services/` (fairscore, trust,
  static AI analyzer, Groq client), `app/seed.py` (bootstrap + fixture loader), `tests/`.
- `frontend/` — React + TypeScript + Vite source; `frontend/dist` is the prebuilt
  bundle the offline image serves.
- `desktop/` — Windows launcher (`start-isr.ps1`, `Start ISR.bat`, `Stop ISR.bat`,
  shortcut/icon assets).
- `scripts/` — smoke, offline-guarantee, and feature verification scripts.
- `fixtures.json` + `run.py` + `.dogfood.toml` — demo fixture and acceptance checker.
- `docs/` — `SPEC.md` (competition spec), `JUDGING.md` (rubric + normalization plan).
