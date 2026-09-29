"""No-demo mode: a fresh install seeds accounts only — zero events/projects.

Runs the seed in a subprocess with its own temp database so the shared test
session's demo data (and env) are untouched.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
import json, os, sys
sys.path.insert(0, {backend!r})
from app.core.db import SessionLocal, engine
from app.models import Base, Event, Project, Team, User
from app.seed import load_and_seed

Base.metadata.create_all(engine)
with SessionLocal() as db:
    result = load_and_seed(db)
with SessionLocal() as db:
    from sqlalchemy import func, select
    counts = {{
        "events": db.scalar(select(func.count(Event.id))),
        "projects": db.scalar(select(func.count(Project.id))),
        "teams": db.scalar(select(func.count(Team.id))),
        "users": db.scalar(select(func.count(User.id))),
    }}
    org = db.scalar(select(User).where(User.email == "organizer@isr.local"))
    from app.core.security import verify_password
    counts["login_ok"] = bool(org and verify_password("isr-dev-password", org.password_hash))
print(json.dumps({{"result": result, "counts": counts}}))
""".format(backend=str(BACKEND_ROOT))


def _run_nodemo_seed() -> tuple[dict, dict]:
    tmp = tempfile.mkdtemp(prefix="isr-nodemo-")
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp}/isr_nodemo.db"
    env["SEED_DEMO"] = ""
    env.pop("SEED_FIXTURES", None)
    proc = subprocess.run([sys.executable, "-c", SCRIPT], env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    import json
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return payload["result"], payload["counts"]


def test_nodemo_reports_demo_disabled():
    result, _ = _run_nodemo_seed()
    assert result["seeded"] is False and result["demo"] is False


def test_nodemo_db_has_zero_events_but_all_accounts():
    _, counts = _run_nodemo_seed()
    assert counts["events"] == 0
    assert counts["projects"] == 0
    assert counts["teams"] == 0
    assert counts["users"] == 5  # organizer, judge_a, judge_b, participant, admin
    assert counts["login_ok"] is True
