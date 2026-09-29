"""Run-it-locally runbook: README + detected commands + terminal launcher.

The generated .bat is exercised through the pure builder, so both branches
(container docker-exec and host cd) are testable regardless of where the
suite runs; no docker is ever invoked.
"""
import io
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from app.routers.judge import _terminal_script_lines
from app.core.db import SessionLocal
from app.models import Project
from tests.conftest import _cookie

REPOS = Path(__file__).resolve().parents[2] / "repos"


def _ext_by_title(title: str) -> str:
    with SessionLocal() as db:
        p = db.query(Project).filter_by(title=title).first()
        return p.external_id if p else ""


def test_terminal_script_container_branch():
    lines = _terminal_script_lines(
        "glass-signal", "/repos",
        [{"label": "Run app", "command": "python app.py"}], container="isr")
    text = "\r\n".join(lines)
    assert lines[0] == "@echo off"
    assert "docker exec -it isr" in text
    assert "cd /repos/glass-signal" in text
    assert "exec sh" in text
    for line in lines:
        assert not line.strip().startswith("&"), line


def test_terminal_script_escapes_cmd_metacharacters():
    """A command like 'npm install && npm run dev' must be echoed literally,
    never executed by cmd (an unescaped && would chain host commands)."""
    lines = _terminal_script_lines(
        "x", "/repos",
        [{"label": "Dev", "command": "npm install && npm run dev"}])
    echo_line = [ln for ln in lines if ln.startswith("echo   ")][0]
    assert echo_line == "echo   npm install ^&^& npm run dev"


def test_terminal_script_host_branch():
    # The .bat is generated for cmd.exe, so the host path must be expressed
    # Windows-truthfully on every OS the suite runs on: a plain Path() renders
    # 'C:\\checkouts' with one separator on Windows but two on POSIX, which is
    # what broke this test depending on where pytest ran.
    lines = _terminal_script_lines(
        "widget", PureWindowsPath(r"C:\checkouts"),
        [{"label": "Dev", "command": "npm install && npm run dev"}])
    text = "\r\n".join(lines)
    assert text.startswith("@echo off")
    assert 'cd /d "C:\\checkouts\\widget"' in text
    assert lines[-1] == "cmd /k"


def test_runbook_requires_auth(client):
    assert client.get("/api/judge/repos/nope/runbook").status_code == 401


def test_runbook_unknown_project_is_404(client, judge_a_cookie):
    r = client.get("/api/judge/repos/definitely-not-here/runbook", headers=judge_a_cookie)
    assert r.status_code == 404


@pytest.fixture()
def glass_checkout():
    """A minimal realistic checkout under the source-tree repos/ root.

    Lives only for the test; the module directory is removed afterwards so
    other modules (and the AI-review tests that count files) are unaffected.
    """
    root = REPOS / "glass-signal"
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "# Glass Signal\n\nRun with `python app.py` after `pip install -r requirements.txt`.\n",
        encoding="utf-8")
    (root / "app.py").write_text("print('glass signal probe')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    (root / "package.json").write_text(
        '{"name":"glass-signal","scripts":{"dev":"vite"}}', encoding="utf-8")
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_runbook_for_checked_out_repo(client, judge_a_cookie, glass_checkout):
    ext = _ext_by_title("Glass Signal")
    assert ext, "fixture project missing"
    r = client.get(f"/api/judge/repos/{ext}/runbook", headers=judge_a_cookie)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["checkout"] == "glass-signal"
    assert body["readme"] is not None and "Glass Signal" in body["readme"]["text"]
    commands = [c["command"] for c in body["commands"]]
    assert "npm install && npm run dev" in commands
    assert "pip install -r requirements.txt" in commands
    assert "python app.py" in commands
    assert body["launch"]


def test_terminal_script_download_host_checkout(client, judge_a_cookie, glass_checkout):
    ext = _ext_by_title("Glass Signal")
    r = client.get(f"/api/judge/repos/{ext}/terminal-script", headers=judge_a_cookie)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-bat")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode()
    assert text.startswith("@echo off")
    assert f"cd /d \"{glass_checkout.resolve()}\"" in text
    assert "cmd /k" in text


def test_runbook_for_link_only_repo_reports_missing(client, judge_a_cookie):
    """widget-pro (acme) was never cloned and tests forbid network fetches."""
    ext = _ext_by_title("Widget Pro")
    if not ext:
        pytest.skip("fixture variant without that project")
    r = client.get(f"/api/judge/repos/{ext}/runbook", headers=judge_a_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["commands"] == []
    assert "auto-clone" in body["note"]
