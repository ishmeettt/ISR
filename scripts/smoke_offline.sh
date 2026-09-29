#!/usr/bin/env bash
# Smoke-test a running ISR offline container end to end.
# Usage: bash scripts/smoke_offline.sh [BASE_URL]   (default http://localhost:8081)
set -u
BASE="${1:-http://localhost:8081}"
PASS=0; FAIL=0

ok()   { echo "PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL  $1"; FAIL=$((FAIL+1)); }
check() { # check <label> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1 ($3)"; else bad "$1 (expected $2, got $3)"; fi
}

JAR=/tmp/isr_smoke_judge.jar
ORG=/tmp/isr_smoke_org.jar
rm -f "$JAR" "$ORG"

# 1. Health
check "health" '{"status":"ok"}' "$(curl -s "$BASE/api/health")"

# 2. SPA root serves HTML
ctype=$(curl -s -o /dev/null -w '%{content_type}' "$BASE/")
case "$ctype" in text/html*) ok "SPA root ($ctype)";; *) bad "SPA root ($ctype)";; esac

# 3. Judge logs in WITH the event code (fresh session, links all event tracks)
login=$(curl -s -c "$JAR" -X POST -H 'Content-Type: application/json' \
  -d '{"email":"diego.herrera@example.org","password":"isr-dev-password","event_code":"SAMPLE26"}' \
  "$BASE/api/auth/login")
echo "$login" | grep -q '"code":"SAMPLE26"' && ok "judge login links event code" || bad "judge login links event code ($login)"

# 4. Judge sees the event's projects
projects=$(curl -s -b "$JAR" "$BASE/api/judge/projects")
n=$(echo "$projects" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')
check "judge projects visible" 41 "$n"

# 5. Rubric endpoint
rubric=$(curl -s -b "$JAR" "$BASE/api/judge/rubric")
echo "$rubric" | grep -q 'functionality' && ok "rubric served" || bad "rubric served ($rubric)"

# 6. AI review of a fixture project finds the embedded local checkout
rev=$(curl -s -b "$JAR" -X POST -H 'Content-Type: application/json' \
  -d '{"projects":["prj_01"]}' "$BASE/api/judge/ai-review")
src=$(echo "$rev" | python3 -c 'import sys,json;print(json.load(sys.stdin)["reviewed"][0]["source"])')
case "$src" in "local checkout: glass-signal") ok "ai-review uses local checkout ($src)";; *) bad "ai-review source ($src)";; esac

# 7. Ephemeral preview of a pasted link
prev=$(curl -s -b "$JAR" -X POST -H 'Content-Type: application/json' \
  -d '{"repo_url":"https://git.example.org/dogfood/glass-signal"}' \
  "$BASE/api/judge/ai-review/preview")
psrc=$(echo "$prev" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["source"])')
case "$psrc" in "local checkout: glass-signal") ok "preview uses local checkout ($psrc)";; *) bad "preview source ($psrc)";; esac

# 8. Judge submits an evaluation for an unscored project
code=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"project":"prj_41","scores":{"functionality":5,"quality":4,"innovation":3},"comment":"smoke test evaluation"}' \
  "$BASE/api/judge/evaluate")
check "evaluate prj_41" 201 "$code"

# 9. Resubmitting revises the evaluation (upsert, audited) — not a duplicate 409
code=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"project":"prj_41","scores":{"functionality":3,"quality":3,"innovation":3}}' \
  "$BASE/api/judge/evaluate")
check "revise evaluation 201" 201 "$code"

# 10. Event-code gate: a judge with NO track links cannot evaluate until they
#     log in with the event's code. Prerequisite: fresh.judge@example.org,
#     role=judge with no event links — created/reset here so the script is
#     idempotent on any machine (re-runs included).
docker exec -i "${CONTAINER:-isr}" python3 - <<'PYEOF'
from app.core.db import SessionLocal
from app.models import User
from app.models.audit import AuditEvent
from app.models.judging import JudgeTrack
from app.core.security import hash_password

with SessionLocal() as db:
    u = db.query(User).filter(User.email == 'fresh.judge@example.org').first()
    if u is None:
        db.add(User(email='fresh.judge@example.org', name='Fresh Judge',
                    role='judge', password_hash=hash_password('isr-dev-password')))
        db.commit()
    else:
        # Re-runs: strip both link kinds — audit rows (last-entered code) AND
        # JudgeTrack rows (created by the earlier code-login in check 3) —
        # otherwise the unlinked-judge gate test is not actually unlinked.
        db.query(AuditEvent).filter(
            AuditEvent.actor_id == u.id,
            AuditEvent.action.in_(['JUDGE_EVENT_LINKED', 'JUDGE_EVENT_KNOWN'])).delete()
        db.query(JudgeTrack).filter(JudgeTrack.judge_id == u.id).delete()
        db.commit()
PYEOF
JAR2=/tmp/isr_smoke_fresh.jar; rm -f "$JAR2"

curl -s -c "$JAR2" -X POST -H 'Content-Type: application/json' \
  -d '{"email":"fresh.judge@example.org","password":"isr-dev-password"}' \
  "$BASE/api/auth/login" > /dev/null
code=$(curl -s -b "$JAR2" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"project":"prj_41","scores":{"functionality":1,"quality":1,"innovation":1}}' \
  "$BASE/api/judge/evaluate")
check "unlinked judge evaluate 403" 403 "$code"

# 10b. Logging in WITH the event code links the judge; scoring unlocks.
curl -s -c "$JAR2" -X POST -H 'Content-Type: application/json' \
  -d '{"email":"fresh.judge@example.org","password":"isr-dev-password","event_code":"SAMPLE26"}' \
  "$BASE/api/auth/login" | grep -q '"code":"SAMPLE26"' \
  && ok "fresh judge login with code" || bad "fresh judge login with code"
code=$(curl -s -b "$JAR2" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"project":"prj_41","scores":{"functionality":4,"quality":4,"innovation":4}}' \
  "$BASE/api/judge/evaluate")
check "post-code evaluate 201" 201 "$code"

# 10c. The link persists: next login WITHOUT the code can still score (and
#      the one-evaluation-per-project guard now returns 409).
curl -s -c "$JAR2" -X POST -H 'Content-Type: application/json' \
  -d '{"email":"fresh.judge@example.org","password":"isr-dev-password"}' \
  "$BASE/api/auth/login" > /dev/null
code=$(curl -s -b "$JAR2" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"project":"prj_41","scores":{"functionality":2,"quality":2,"innovation":2}}' \
  "$BASE/api/judge/evaluate")
check "relogin still linked (201 revise)" 201 "$code"
rm -f "$JAR2"

# 11. Organizer runs a FairScore normalization run
curl -s -c "$ORG" -X POST -H 'Content-Type: application/json' \
  -d '{"email":"organizer@isr.local","password":"isr-dev-password"}' \
  "$BASE/api/auth/login" > /dev/null
code=$(curl -s -b "$ORG" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/results/run")
check "results/run" 201 "$code"

# 12. Persistence across a container restart is verified OUTSIDE this script
#     (docker restart + re-evaluate 201), since we may not own the container.

echo
echo "smoke: $PASS passed, $FAIL failed  ($BASE)"
[ "$FAIL" -eq 0 ]
