"""Adding repos by GitHub link to the judge's list.

Clone execution is mocked at the subprocess level (tests must not touch the
network); we verify validation, row semantics, and refresh-on-re-add.
"""
import subprocess

from tests.conftest import _cookie


def _add(client, url="https://github.com/octocat/Hello-World"):
    return client.post("/api/judge/repos/add", json={"repo_url": url},
                       headers=_cookie("judge_a"))


def test_rejects_non_github_links(client):
    for bad in ("ftp://example.com/x/y", "https://gitlab.com/o/r",
                "https://github.com/onlyowner", "not a url"):
        r = client.post("/api/judge/repos/add", json={"repo_url": bad},
                        headers=_cookie("judge_a"))
        assert r.status_code == 400, bad


def test_add_creates_project_row(client):
    r = _add(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["title"] == "Hello World"
    assert body["clone_state"] in ("cloned", "failed", "already-present")
    # The row shows up in the judge's overview immediately.
    ov = client.get("/api/judge/overview", headers=_cookie("judge_a")).json()
    assert any(p["repo_url"] == body["repo_url"] for p in ov["projects"])


def test_readd_refreshes_instead_of_duplicating(client):
    first = _add(client).json()
    before = client.get("/api/judge/overview", headers=_cookie("judge_a")).json()["totals"]["projects"]
    second = _add(client).json()
    assert second["project"] == first["project"]
    after = client.get("/api/judge/overview", headers=_cookie("judge_a")).json()["totals"]["projects"]
    assert after == before


def test_clone_failure_is_reported_not_fatal(client, monkeypatch):
    def boom(*a, **k):
        return subprocess.CompletedProcess(a[0], 128, stderr="fatal: repository not found\n")
    monkeypatch.setattr(subprocess, "run", boom)
    r = client.post("/api/judge/repos/add",
                    json={"repo_url": "https://github.com/octocat/does-not-exist-xyz"},
                    headers=_cookie("judge_a"))
    assert r.status_code == 200
    body = r.json()
    assert body["clone_state"] == "failed"
    assert "not found" in body["clone_note"]


def test_trailing_git_suffix_is_normalized(client):
    r = _add(client, "https://github.com/octocat/Hello-World.git")
    assert r.status_code == 200
    assert r.json()["repo_url"] == "https://github.com/octocat/Hello-World"
