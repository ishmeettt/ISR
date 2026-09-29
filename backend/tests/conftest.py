"""Test harness: a fresh, fully seeded database per test *session*.

Each test module shares one seeded in-memory-style SQLite file via the
`client` and role-cookie fixtures. Tests that mutate state (deadline refusal
writes an audit event, seed idempotency reseeds) must not break the security
assertions of other modules: RBAC and isolation tests are read-only by nature,
and the two mutating tests assert on their own side effects only.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ["SEED_SESSION_SECRET"] = "isr-dogfood-2026"  # deterministic tokens
os.environ["SEED_DEMO"] = "1"  # tests exercise the fixture (demo) data path
os.environ["ISR_DISABLE_AUTOCLONE"] = "1"  # tests stay offline: never git clone

_tmp = tempfile.mkdtemp(prefix="isr-tests-")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_tmp}/isr_test.db"
os.environ["SEED_FIXTURES"] = str(BACKEND_ROOT.parent / "fixtures.json")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import load_and_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    from app.models import Base

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        load_and_seed(db)
    yield


@pytest.fixture(scope="session")
def client(seeded_database):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def db_session(seeded_database):
    """A session-scoped DB session for direct data assertions."""
    with SessionLocal() as db:
        yield db


def _cookie(role: str) -> dict[str, str]:
    from app.seed import _seed_token

    return {"Cookie": f"session={_seed_token(role)}"}


@pytest.fixture(scope="session")
def organizer_cookie():
    return _cookie("organizer")


@pytest.fixture(scope="session")
def judge_a_cookie():
    return _cookie("judge_a")


@pytest.fixture(scope="session")
def judge_b_cookie():
    return _cookie("judge_b")


@pytest.fixture(scope="session")
def participant_cookie():
    return _cookie("participant")
