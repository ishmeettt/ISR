"""Lightweight additive migrations for existing databases.

`Base.metadata.create_all` creates new *tables* but never alters existing ones,
so a long-lived volume (like the docker volume) misses columns added later.
ISR's startup runs `ensure_schema` before seeding: each statement is additive
and idempotent, guarded by a catalog check.
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("isr.migrate")

# (table, column, DDL) — keep append-only; never remove entries.
ADD_COLUMNS: list[tuple[str, str, str]] = [
    ("events", "code", "VARCHAR(12)"),
    ("events", "created_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
    ("events", "judge_count", "INTEGER NOT NULL DEFAULT 3"),
    ("events", "submissions_open", "TIMESTAMPTZ"),
    ("events", "judging_close", "TIMESTAMPTZ"),
    ("events", "ai_api_key", "VARCHAR(255)"),
]

CREATE_INDEXES: list[tuple[str, str]] = [
    ("idx_events_code", "CREATE INDEX IF NOT EXISTS idx_events_code ON events (code)"),
    ("idx_events_created_by", "CREATE INDEX IF NOT EXISTS idx_events_created_by ON events (created_by)"),
    ("idx_tracks_event", "CREATE INDEX IF NOT EXISTS idx_tracks_event ON tracks (event_id)"),
]


def _existing_columns(conn, table: str) -> set[str]:
    if conn.dialect.name == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})"))
        return {r[1] for r in rows}
    rows = conn.execute(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_name = :t AND table_schema = 'public'"),
        {"t": table},
    )
    return {r[0] for r in rows}


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for table, column, ddl in ADD_COLUMNS:
            if column not in _existing_columns(conn, table):
                # SQLite cannot add a referenced-column FK in one step; the
                # tests run on fresh SQLite DBs where create_all already
                # made the full table, so the FK variant is Postgres-only.
                if conn.dialect.name == "sqlite" and "REFERENCES" in ddl.upper():
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                log.info("schema: added %s.%s", table, column)
        if conn.dialect.name != "sqlite":
            for name, ddl in CREATE_INDEXES:
                conn.execute(text(ddl))
