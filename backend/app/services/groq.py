"""Optional LLM-assisted code judgment via Groq (OpenAI-compatible API).

Policy unchanged: the machine NEVER assigns marks. When the organizer has
configured a Groq key for the event, the analyzer asks the model for a
structured, advisory code review — strengths, risks, and concrete suggestions
— grounded in the same offline static findings plus a sample of real source
files. Without a key (or on any error, or offline) it silently falls back to
the deterministic static analysis, so judging never blocks on the network.

The key lives in the events table (organizer-set, per event), is never logged
and never returned by any API route.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq rotates model availability per account/key; try these in order and
# use the first the key can actually access (ISR_GROQ_MODEL overrides).
MODELS = [
    os.environ.get("ISR_GROQ_MODEL", "openai/gpt-oss-120b"),
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]
# Cloudflare in front of api.groq.com rejects the default Python-urllib
# User-Agent (403 / error 1010) — always send a real one.
HEADERS_BASE = {"Content-Type": "application/json", "User-Agent": "ISR/0.1 (offline-first hackathon portal)"}
TIMEOUT = 45  # seconds; judges are waiting on this
# Free-tier Groq keys allow ~8k tokens per minute, so the whole request must
# stay well under that (payload + completion). Keep the sample tight.
MAX_FILE_BYTES = 1800  # per-file source sample sent to the model
MAX_FILES = 4
MAX_FINDING_ROWS = 8  # per finding category sent to the model

_SYSTEM = (
    "You are a senior hackathon code reviewer assisting a human judge. You may "
    "SUGGEST scores per provided rubric criterion — clearly advisory; the human "
    "judge always decides the final marks. Answer with strict JSON only, no "
    "markdown fences, matching: "
    '{"summary": str, "best_parts": [str], "errors": [{"file": str, "note": str}], '
    '"loopholes": [{"file": str, "note": str}], "suggestions": [{"file": str, "note": str}], '
    '"scores": [{"criterion": str, "suggested": int, "max": int, "reason": str}]}. '
    "Ground every point in the provided code/findings; be concrete and cite files. "
    "Each score reason must explain what justified and what limited the score, "
    "referencing specific evidence."
)


def build_rubric_block(rubric: list[dict] | None) -> str:
    """Human-readable rubric for the model prompt (empty when none)."""
    if not rubric:
        return ""
    rows = "; ".join(
        f"{c['name']} (0-{c['max_score']}, weight {round(float(c['weight']) * 100)}%)"
        for c in rubric
    )
    return f" Scoring rubric: {rows}. Suggest a score per criterion."


def _checkout_for(repo_url: str | None, title: str) -> Path | None:
    """Find the local checkout for a project (same convention as code_assist)."""
    from . import code_assist

    if not repo_url:
        return None
    parsed = code_assist.parse_repo_url(repo_url)
    for candidate in code_assist._local_checkout_candidates(
        repo_url, parsed["owner"], parsed["repo"], title
    ):
        if candidate.is_dir():
            return candidate
    return None


def _source_sample(checkout: Path) -> list[dict[str, str]]:
    """A bounded sample of real source files to ground the model."""
    from . import code_assist

    sample: list[dict[str, str]] = []
    for p in sorted(checkout.rglob("*")):
        if len(sample) >= MAX_FILES:
            break
        rel = str(p.relative_to(checkout)).replace("\\", "/")
        if (
            p.is_file()
            and p.suffix in code_assist.LANG_EXTS
            and "node_modules" not in rel
            and ".venv" not in rel
            and p.stat().st_size < 100_000
        ):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_BYTES]
            except OSError:
                continue
            sample.append({"file": rel, "code": text})
    return sample


def llm_review(
    api_key: str,
    title: str,
    summary: str,
    repo_url: str | None,
    static_findings: dict[str, Any],
    rubric: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Ask Groq for a structured advisory review (with suggested rubric scores
    when a rubric is provided). Returns None on any failure."""
    checkout = _checkout_for(repo_url, title)
    files = _source_sample(checkout) if checkout else []

    user = {
        "project": title,
        "summary": summary[:400],
        "repo_url": repo_url,
        "static_analysis": {
            "files_scanned": static_findings.get("files_scanned", 0),
            "security": static_findings.get("security", [])[:MAX_FINDING_ROWS],
            "errors": static_findings.get("errors", [])[:MAX_FINDING_ROWS],
            "improvements": static_findings.get("improvements", [])[:MAX_FINDING_ROWS],
        },
        "source_files": files,
    }
    rubric_block = build_rubric_block(rubric)
    last_error: Exception | None = None
    for model in MODELS:
        body = json.dumps({
            "model": model,
            "temperature": 0.2,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM + rubric_block},
                {"role": "user", "content": json.dumps(user)},
            ],
        }).encode()

        req = urllib.request.Request(
            GROQ_URL, data=body, method="POST",
            headers={**HEADERS_BASE, "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(_strip_fences(content))
            out = _normalize(parsed)
            out["model"] = model
            return out
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError,
                KeyError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (400, 404):
                break  # auth/quota/server problems: other models won't help
            continue  # model missing for this key -> try the next one
    _ = last_error
    return None  # any failure -> caller falls back to static analysis


def _strip_fences(text: str) -> str:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def _normalize(parsed: dict[str, Any]) -> dict[str, Any]:
    def notes(rows: Any) -> list[dict[str, str]]:
        out = []
        for r in rows or []:
            if isinstance(r, dict) and r.get("note"):
                out.append({"file": str(r.get("file", "-")), "note": str(r["note"])})
            elif isinstance(r, str):
                out.append({"file": "-", "note": r})
        return out

    best = [str(s).strip() for s in parsed.get("best_parts", [])
            if isinstance(s, str) and s.strip()]
    scores = []
    for s in parsed.get("scores", []) or []:
        if not isinstance(s, dict) or not s.get("criterion"):
            continue
        try:
            suggested = int(s.get("suggested", 0))
            max_score = int(s.get("max", 5))
        except (TypeError, ValueError):
            continue
        scores.append({
            "criterion": str(s["criterion"]),
            "suggested": max(0, min(suggested, max_score)),
            "max": max_score,
            "reason": str(s.get("reason", "")).strip(),
        })
    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "best_parts": best[:8],
        "errors": notes(parsed.get("errors"))[:12],
        "loopholes": notes(parsed.get("loopholes"))[:12],
        "suggestions": notes(parsed.get("suggestions"))[:12],
        "scores": scores[:8],
    }


def review_with_optional_llm(
    api_key: str | None,
    title: str,
    summary: str,
    repo_url: str | None,
    rubric: list[dict] | None = None,
) -> dict[str, Any]:
    """The full advisory payload: LLM judgment when a key exists, else static.

    The envelope always carries `advisory: True` and a `mode` field so the UI
    can show where the judgment came from. When a rubric is given, the LLM is
    asked for suggested per-criterion scores WITH reasons — advisory only.
    """
    from . import code_assist

    static = code_assist.review_repo(repo_url, title)
    static["advisory"] = True
    static["mode"] = "static"

    if not api_key:
        return static

    llm = llm_review(api_key, title, summary, repo_url, static["findings"], rubric)
    if llm is None:
        return static  # offline, bad key, rate limit: never block judging

    static["mode"] = "groq"
    static["model"] = llm.get("model", "groq")
    static["llm"] = llm
    static["source"] = f"{static['source']} + Groq {static['model']}"
    return static
