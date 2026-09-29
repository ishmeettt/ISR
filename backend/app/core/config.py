"""ISR configuration. Environment-driven; docker-compose sets production values."""
import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://isr:isr@localhost:5433/isr"
)
SEED_FIXTURES: str = os.environ.get("SEED_FIXTURES", "fixtures.json")
# Offline-first: all seeded users share this dev password unless overridden.
SEED_PASSWORD: str = os.environ.get("SEED_PASSWORD", "isr-dev-password")
# Deterministic seed-session tokens (so printed cookies survive restarts).
SEED_SESSION_SECRET: str = os.environ.get("SEED_SESSION_SECRET", "isr-dogfood-2026")
SESSION_COOKIE_NAME: str = os.environ.get("SESSION_COOKIE_NAME", "session")
SESSION_MAX_AGE_SECONDS: int = int(os.environ.get("SESSION_MAX_AGE_SECONDS", str(7 * 24 * 3600)))
CORS_ORIGINS: list[str] = [
    o for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080"
    ).split(",") if o
]

DB_ARGS: dict = dict(pool_pre_ping=True, pool_recycle=1800)
