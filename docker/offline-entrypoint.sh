#!/bin/sh
# ISR offline entrypoint: one process serves API + UI; SQLite lives in /data
# so a mounted volume survives container replacement.
set -e
mkdir -p /data
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
