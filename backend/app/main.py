"""ISR backend entrypoint."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import CORS_ORIGINS
from .routers import auth, events, exports, gallery, judge, mission, participant, results, submissions, trust
from .seed import run_seed

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("isr")

app = FastAPI(
    title="ISR — Intelligent Submission & Review",
    version="0.1.0",
    description="RUN → JUDGE → VERIFY → EXPLAIN. Hackathon competition infrastructure.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(gallery.router)
app.include_router(submissions.router)
app.include_router(judge.router)
app.include_router(participant.router)
app.include_router(events.router)
app.include_router(mission.router)
app.include_router(results.router)
app.include_router(trust.router)
app.include_router(exports.router)


@app.on_event("startup")
def startup() -> None:
    try:
        result = run_seed()
        log.info("seed: fixture=%s event=%s projects=%s evaluations=%s",
                 result["fixture"], result.get("event"), result.get("projects"),
                 result.get("evaluations"))
        for role, token in result["tokens"].items():
            log.info("seeded test login %-12s Cookie: session=%s", role + " ", token)
    except Exception:  # noqa: BLE001 — boot must not silently swallow seed errors
        log.exception("seed failed")
        raise


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --- single-container mode: serve the built UI from the API process ---------
# Set ISR_SERVE_UI=1 (as Dockerfile.offline does) and one image runs the whole
# portal: every /api route above matches first; this catch-all sits LAST so it
# only catches what nothing else claimed, serving real files and falling back
# to the SPA shell for client-side routes. Off by default so tests and the
# nginx compose stack behave exactly as before.
import os

if os.environ.get("ISR_SERVE_UI") == "1":
    from pathlib import Path

    from fastapi.responses import FileResponse

    _UI_DIST = Path(os.environ.get("ISR_UI_DIST", "/app/ui/dist")).resolve()
    _INDEX = _UI_DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = (_UI_DIST / full_path).resolve() if full_path else _INDEX
        if candidate.is_file() and _UI_DIST in candidate.parents:
            if candidate == _INDEX:
                # The SPA shell references the hashed bundles; a stale shell
                # points at bundles that no longer exist after an upgrade.
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
            # Hashed asset filenames make long caching safe for real files.
            return FileResponse(candidate)
        return FileResponse(_INDEX, headers={"Cache-Control": "no-cache"})
