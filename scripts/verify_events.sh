#!/usr/bin/env bash
# Event hosting live verification. Run against a seeded ISR portal:
#   bash scripts/verify_events.sh [base_url]
set -euo pipefail

BASE="${1:-http://127.0.0.1:8080}"
JAR=$(mktemp)

for i in 1 2 3 4 5; do
  [ "$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$BASE/api/health")" = "200" ] && break
  sleep 2
done

echo "== Organizer login =="
code=$(curl -s -o /dev/null -w '%{http_code}' -c "$JAR" -X POST -H 'Content-Type: application/json' \
  -d '{"email":"organizer@isr.local","password":"isr-dev-password"}' "$BASE/api/auth/login")
echo "login -> $code"; [ "$code" = "200" ] || { echo "FAIL: login"; exit 1; }

echo
echo "== My events includes the seeded fixture event with its code =="
curl -s -b "$JAR" "$BASE/api/organizer/events" > /tmp/mev.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/mev.json'))
ev = next(e for e in d if e['code'] == 'SAMPLE26')
assert ev['name'] == 'Sample Hack 2026' and ev['project_count'] == 41
assert ev['is_open'] is False, 'fixture event must be closed'
codes = [e['code'] for e in d]
assert len(codes) == len(set(codes)), 'codes must be unique'
print(f"PASS: {len(d)} event(s) hosted; fixture event owned with code SAMPLE26")
PY

echo
echo "== Create: unique code + share link =="
cat > /tmp/new_event.json <<'JSON'
{"name":"Winter Build Weekend","description":"Created by verify_events",
 "judge_count":4,
 "submissions_open":"2026-09-20T09:00:00Z",
 "submissions_close":"2026-12-20T18:00:00Z",
 "judging_close":"2026-12-22T18:00:00Z",
 "tracks":["AI","Web","Hardware"]}
JSON
curl -s -b "$JAR" -X POST -H 'Content-Type: application/json' \
  -d @/tmp/new_event.json "$BASE/api/organizer/events" > /tmp/created.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/created.json'))
assert len(d['code']) == 8 and d['code'].isalnum(), d['code']
assert d['share_link'] == f"/events/{d['code']}"
assert d['is_open'] is True
assert set(d['tracks']) == {'AI', 'Web', 'Hardware'}
open('/tmp/created_id', 'w').write(str(d['id']))
open('/tmp/created_code', 'w').write(d['code'])
print(f"PASS: created '{d['name']}' code={d['code']} link={d['share_link']}")
PY
EID=$(cat /tmp/created_id); CODE=$(cat /tmp/created_code)

echo
echo "== Edit later: judge_count and windows stay editable =="
curl -s -b "$JAR" -X PATCH -H 'Content-Type: application/json' \
  -d '{"judge_count":6,"submissions_close":"2026-12-24T18:00:00Z","judging_close":"2026-12-26T18:00:00Z","description":"Edited live"}' \
  "$BASE/api/organizer/events/$EID" > /tmp/edited.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/edited.json'))
assert d['judge_count'] == 6, d['judge_count']
assert d['submissions_close'].startswith('2026-12-24')
assert d['description'] == 'Edited live'
print("PASS: judge_count -> 6, close moved, description updated")
PY

echo
echo "== Invalid edit refused (close pushed past judging_close), data unchanged =="
c=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -X PATCH -H 'Content-Type: application/json' \
  -d '{"submissions_close":"2026-12-30T18:00:00Z"}' "$BASE/api/organizer/events/$EID")
echo "invalid edit -> $c"; [ "$c" = "400" ] || { echo "FAIL: expected 400"; exit 1; }
curl -s -b "$JAR" "$BASE/api/events/$CODE" > /tmp/pub.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/pub.json'))
assert d['submissions_close'].startswith('2026-12-24'), 'a refused edit must not change data'
assert d['tracks'] == ['AI', 'Web', 'Hardware']
print("PASS: event unchanged after refused edit; public lookup by code works")
PY

echo
echo "== Ownership: a second organizer cannot edit someone else's event =="
TOKEN_HASH=$(python3 -c "import hashlib; print(hashlib.sha256(b'rival-session-token-0001').hexdigest())")
c=$(docker exec -i isr-backend-1 python - "$TOKEN_HASH" "$EID" <<'PY' 2>/dev/null
import datetime as dt, hashlib, json, sys, urllib.request
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Session as DbSession, User, utcnow

with SessionLocal() as db:
    rival = db.scalar(select(User).where(User.email == "rival@isr.local"))
    if rival is None:
        rival = User(email="rival@isr.local", name="Rival Organizer",
                     role="organizer", password_hash=hash_password("isr-dev-password"))
        db.add(rival); db.commit(); db.refresh(rival)
    token_hash = sys.argv[1]
    sess = db.scalar(select(DbSession).where(DbSession.token_hash == token_hash))
    if sess is None:
        db.add(DbSession(token_hash=token_hash, user_id=rival.id,
                         expires_at=utcnow() + dt.timedelta(days=1)))
        db.commit()

eid = sys.argv[2]
req = urllib.request.Request(
    f"http://127.0.0.1:8000/api/organizer/events/{eid}",
    method="PATCH",
    headers={"Cookie": "session=rival-session-token-0001",
             "Content-Type": "application/json"},
    data=json.dumps({"name": "Hijacked"}).encode())
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
PY
)
echo "rival edit -> $c"; [ "$c" = "403" ] || { echo "FAIL: ownership not enforced"; exit 1; }
echo "PASS: ownership enforced (403)"

echo
echo "ALL EVENT CHECKS PASSED"
