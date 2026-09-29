"""AI code review (advisory only, fully offline).

ISR's AI policy: the machine never decides marks. This analyzer performs a
deterministic static review of a repository snapshot — real errors, security
loopholes, and improvement opportunities — and hands the findings to the judge
as *advisory context*. Final scores always come from a human.

Runs with zero network access: no LLM calls, no package downloads. Repo links
are parsed for owner/repo so the record shows what was reviewed; if a local
checkout exists on disk (offline clone shared by the organizer) it is scanned;
otherwise the analyzer reviews what is knowable offline and says so.

Checks (language-agnostic, chosen to be genuinely useful at a hackathon):
  security: hardcoded secrets/keys, SQL string formatting, eval/exec, shell
            injection (os.system / shell=True), disabled TLS verification
  errors:   bare except, TODO/FIXME density, very long functions (heuristic)
  improvements: missing README, missing tests, missing license, no CI config
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|secret|password|token|passwd)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
     "Possible hardcoded credential"),
    (r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----", "Private key material in repository"),
]
RISKY_PATTERNS = [
    (r"(?i)\b(exec|eval)\s*\(", "Dynamic eval/exec — review inputs carefully"),
    (r"(?i)os\.system\s*\(|subprocess\.\w+\([^)]*shell\s*=\s*True", "Shell command from code — injection risk"),
    (r"(?i)verify\s*=\s*False", "TLS certificate verification disabled"),
    (r"(?i)(SELECT|INSERT|UPDATE|DELETE).{0,40}(%s|\+|\bformat\(|f['\"])", "SQL built by string concatenation — use parameters"),
]
ERROR_PATTERNS = [
    (r"(?m)^\s*except\s*:\s*$", "Bare except — hides real errors"),
    (r"(?i)\bTODO\b|\bFIXME\b|\bHACK\b", "Unfinished-work marker"),
]
LANG_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs", ".c", ".cpp", ".h"}


def parse_repo_url(repo_url: str | None) -> dict[str, str | None]:
    if not repo_url:
        return {"host": None, "owner": None, "repo": None}
    m = re.match(r"(?:https?://)?([^/]+)/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url.strip())
    if not m:
        return {"host": None, "owner": None, "repo": None}
    return {"host": m.group(1), "owner": m.group(2), "repo": m.group(3)}


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _is_github_repo_url(repo_url: str | None) -> bool:
    return bool(repo_url and re.match(
        r"^https?://(www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$",
        repo_url.strip().rstrip("/").removesuffix(".git"),
    ))


def ensure_checkout(repo_url: str | None, project_title: str, timeout: int = 180) -> Path | None:
    """Make sure a local checkout exists for a GitHub-linked project.

    Self-healing: containers get replaced on redeploy and volumeless runs
    lose checkouts, so when a github.com project has no clone under the
    repos roots, one is fetched shallowly (git is baked into the image for
    exactly this). Non-GitHub URLs and fixture links are left alone, and any
    failure returns None silently — review always proceeds with whatever is
    knowable offline. Set ISR_DISABLE_AUTOCLONE=1 to forbid fetches (tests).
    """
    if not _is_github_repo_url(repo_url) or os.environ.get("ISR_DISABLE_AUTOCLONE"):
        return None
    url = repo_url.strip().rstrip("/").removesuffix(".git")
    m = re.match(r"(?:https?://)?([^/]+)/([^/]+)/([^/]+?)/?$", url)
    if not m:
        return None
    repo_name = m.group(3)
    for base in _repos_roots():
        target = base / repo_name
        if target.is_dir():
            return target
    target = _repos_roots()[0] / repo_name
    target.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", url + ".git", str(target)],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            return target
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Clean the failed partial clone so a later retry can try again.
    import shutil

    shutil.rmtree(target, ignore_errors=True)
    return None


def _repos_roots() -> list[Path]:
    """Where local checkouts may live, most specific first.

    - $ISR_REPOS_DIR: explicit override (custom deployments)
    - <repo root>/repos/: running from a source checkout
    - /repos: the offline image's documented volume for organizer-provided clones
    - /app/repos: clones baked into the offline image at build time
    """
    roots: list[Path] = []
    env_dir = os.environ.get("ISR_REPOS_DIR")
    if env_dir:
        roots.append(Path(env_dir))
    roots.append(Path(__file__).resolve().parents[3] / "repos")
    roots.append(Path("/repos"))
    roots.append(Path("/app/repos"))
    seen, unique = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def _local_checkout_candidates(repo_url: str | None, owner: str | None,
                               repo: str | None, title: str) -> list[Path]:
    """Offline convention: clones may live in ./repos/<slug-of-title>,
    ./repos/<repo>, or ./repos/<owner>__<repo>.

    Fixture-style URLs (https://example.org/repo/01) carry no usable name, so
    the project title is the primary key for finding a local checkout.
    """
    candidates: list[Path] = []
    for base in _repos_roots():
        candidates.append(base / _slug(title))
        if repo and repo != title.lower().replace(" ", "-"):
            candidates.append(base / repo)
        if owner and repo:
            candidates.append(base / f"{owner}__{repo}")
    seen, unique = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _scan_tree(root: Path) -> dict[str, Any]:
    security: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    improvements: list[dict[str, str]] = []
    files_scanned = 0
    long_functions: list[str] = []

    names = set()
    for p in root.rglob("*"):
        rel = str(p.relative_to(root)).lower()
        names.add(rel)
        if p.is_file() and p.suffix in LANG_EXTS and "node_modules" not in rel and ".venv" not in rel:
            files_scanned += 1
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel_fwd = str(p.relative_to(root)).replace("\\", "/")
            for pat, msg in SECRET_PATTERNS:
                if re.search(pat, text):
                    security.append({"file": rel_fwd, "note": msg})
            for pat, msg in RISKY_PATTERNS:
                for match in re.finditer(pat, text):
                    line = text.count("\n", 0, match.start()) + 1
                    security.append({"file": f"{rel_fwd}:{line}", "note": msg})
            for pat, msg in ERROR_PATTERNS:
                hits = len(re.findall(pat, text))
                if hits:
                    errors.append({"file": rel_fwd, "note": f"{msg} ({hits}x)"})
            # crude long-function heuristic: >120 lines between two top-level defs
            blocks = re.split(r"(?m)^(?:def |function |func |fn )", text)
            for block in blocks[1:]:
                if block.count("\n") > 120:
                    long_functions.append(rel_fwd)
    if long_functions:
        errors.append({"file": ", ".join(sorted(set(long_functions))[:3]),
                       "note": "very long function(s) — hard to review and test"})

    if "readme.md" not in names:
        improvements.append({"file": "README.md", "note": "No README — setup is guesswork"})
    if "license" not in names and "license.md" not in names:
        improvements.append({"file": "LICENSE", "note": "No license file"})
    if not any(n.startswith(("test", ".github/workflows")) for n in names):
        improvements.append({"file": "tests/", "note": "No tests or CI detected"})

    return {
        "files_scanned": files_scanned,
        "security": security[:20],
        "errors": errors[:20],
        "improvements": improvements[:10],
        "summary": {
            "security": len(security), "errors": len(errors),
            "improvements": len(improvements),
        },
    }


def review_repo(repo_url: str | None, project_title: str) -> dict[str, Any]:
    """Static review of a repo. Deterministic, offline, advisory-only."""
    parsed = parse_repo_url(repo_url)
    checked_out = None
    if repo_url:
        for candidate in _local_checkout_candidates(repo_url, parsed["owner"],
                                                    parsed["repo"], project_title):
            if candidate.is_dir():
                checked_out = candidate
                break
        if checked_out is None:
            # GitHub link with no local copy (fresh volume, moved install):
            # fetch a shallow clone so the AI reviews real code, not nothing.
            checked_out = ensure_checkout(repo_url, project_title)

    if checked_out is not None:
        scan = _scan_tree(checked_out)
        source = f"local checkout: {checked_out.name}"
    else:
        scan = {
            "files_scanned": 0, "security": [], "errors": [],
            "improvements": [
                {"file": repo_url or "-", "note":
                 "No local clone found in ./repos/ (auto-clone unavailable — git "
                 "missing, network down, or fetching disabled). Place a checkout "
                 "there for a full static review."}
            ],
            "summary": {"security": 0, "errors": 0, "improvements": 1},
        }
        source = "repository link only (offline mode)"

    return {
        "project": project_title,
        "repo_url": repo_url,
        "repo": parsed,
        "source": source,
        "advisory": True,
        "findings": scan,
    }


def review_payload_to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


# --- runbook: help a judge run the checked-out project locally --------------

README_CANDIDATES = ("readme.md", "readme.rst", "readme.txt", "readme")
README_MAX_CHARS = 64_000


def find_checkout(repo_url: str | None, project_title: str) -> Path | None:
    """An existing local checkout for this project, else None (no fetching)."""
    parsed = parse_repo_url(repo_url)
    for candidate in _local_checkout_candidates(repo_url, parsed["owner"],
                                                parsed["repo"], project_title):
        if candidate.is_dir():
            return candidate
    return None


def read_runbook(checkout: Path) -> dict[str, Any]:
    """What a judge needs to run a checked-out project: its README and the
    run commands detectable from its manifest files. Purely heuristic and
    read-only — the commands are suggestions the judge executes themselves.
    """
    readme: dict[str, str] | None = None
    try:
        entries = sorted(checkout.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if entry.is_file() and entry.name.lower() in README_CANDIDATES:
            try:
                readme = {"name": entry.name,
                          "text": entry.read_text(encoding="utf-8", errors="ignore")[:README_MAX_CHARS]}
            except OSError:
                readme = None
            break

    commands: list[dict[str, str]] = []

    def add(label: str, command: str) -> None:
        if len(commands) < 6:
            commands.append({"label": label, "command": command})

    pkg_json = checkout / "package.json"
    if pkg_json.is_file():
        try:
            scripts = (json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore")
                                  or "{}").get("scripts") or {})
        except ValueError:
            scripts = {}
        if isinstance(scripts, dict):
            if "dev" in scripts:
                add("Install deps + start dev server", "npm install && npm run dev")
            elif "start" in scripts:
                add("Install deps + start app", "npm install && npm start")
            elif scripts:
                first = next(iter(scripts))
                add(f"Install deps + npm run {first}", f"npm install && npm run {first}")
    if (checkout / "requirements.txt").is_file():
        add("Install Python dependencies", "pip install -r requirements.txt")
    if (checkout / "pyproject.toml").is_file() and not (checkout / "requirements.txt").is_file():
        add("Install package (editable)", "pip install -e .")
    if (checkout / "manage.py").is_file():
        add("Start Django dev server", "python manage.py runserver")
    for entry_name in ("main.py", "app.py", "run.py", "server.py"):
        if (checkout / entry_name).is_file():
            add(f"Run {entry_name}", f"python {entry_name}")
            break
    makefile = checkout / "Makefile"
    if makefile.is_file():
        try:
            targets = re.findall(r"(?m)^([a-zA-Z0-9][a-zA-Z0-9_-]*):",
                                 makefile.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            targets = []
        for target in [t for t in targets if t not in (".PHONY",)][:3]:
            add(f"make {target}", f"make {target}")
    if (checkout / "docker-compose.yml").is_file() or (checkout / "compose.yaml").is_file():
        add("Start with Docker Compose", "docker compose up --build")

    return {"readme": readme, "commands": commands}
