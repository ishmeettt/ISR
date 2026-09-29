#!/usr/bin/env bash
# Trust engine live verification. Run against a seeded ISR portal:
#   bash scripts/verify_trust.sh [base_url]
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
ORG="Cookie: session=91e0d703c0dcdda4b06db2bf97998b59"
PRT="Cookie: session=69e6a774b2c036ca34e758c4e8261867"

code() { curl -s -m 10 -o /dev/null -w '%{http_code}' "$@"; }
fail() { echo "FAIL: $1"; exit 1; }

for i in 1 2 3 4 5; do
  [ "$(code "$BASE/api/health")" = "200" ] && break
  sleep 1
done

echo "== RBAC: trust endpoints are organizer-only =="
c=$(code "$BASE/api/trust/flags");                    echo "no-auth     GET /api/trust/flags -> $c"; [ "$c" = "401" ] || fail "flags should require auth"
c=$(code -X POST -H "$PRT" "$BASE/api/trust/scan");   echo "participant POST /api/trust/scan  -> $c"; [ "$c" = "403" ] || fail "participant must not scan"
c=$(code -H "$PRT" "$BASE/api/trust/flags");          echo "participant GET /api/trust/flags -> $c"; [ "$c" = "403" ] || fail "participant must not read flags"

echo
echo "== Scan #1 =="
curl -s -m 60 --retry 3 --retry-connrefused -X POST -H "$ORG" "$BASE/api/trust/scan" > /tmp/scan1.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/scan1.json'))
print(f"created={d['created']} updated={d['updated']} open={d['open']}")
PY

echo
echo "== Scan #2 must be idempotent (no new flags) =="
curl -s -m 60 --retry 3 -X POST -H "$ORG" "$BASE/api/trust/scan" > /tmp/scan2.json
python3 - <<'PY'
import json
d1 = json.load(open('/tmp/scan1.json'))
d2 = json.load(open('/tmp/scan2.json'))
assert d2['created'] == 0, f"second scan created {d2['created']} new flags — keys are not stable"
print(f"PASS: idempotent scan (created={d2['created']}, updated={d2['updated']}, open={d2['open']})")
PY

echo
echo "== Expected fixture findings =="
curl -s -H "$ORG" "$BASE/api/trust/flags" > /tmp/flags.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/flags.json'))
flags = d['flags']
by_det = {}
for f in flags:
    by_det.setdefault(f['detector'], []).append(f)
print("counts by detector:", {k: len(v) for k, v in sorted(by_det.items())})
print("status counts:", d['counts'])

uni = by_det.get('uniform_judge', [])
dup = by_det.get('duplicate_submission', [])
oot = by_det.get('out_of_track', [])
cov = by_det.get('low_coverage', [])
assert not oot, 'fixture scores are fully in-track; an out-of-track flag here would be a false positive'
assert any('Iva Petrova' in f['title'] for f in uni), 'expected Iva Petrova (jdg_07) uniform-judge flag'
assert any('prj_41' in f['detail'] and 'prj_07' in f['detail'] for f in dup), 'expected prj_41/prj_07 duplicate flag'
assert cov, 'expected low-coverage flags'
print('PASS: uniform judge, duplicate submission and coverage flags present; zero false-positive out-of-track flags')
PY

echo
echo "== Out-of-track detector: inject a real violation, flag it, clean up =="
docker exec -i isr-backend-1 python - <<'PY'
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models import Evaluation, Project, RubricScore, RubricCriterion, User, Track, utcnow
with SessionLocal() as db:
    judge = db.scalar(select(User).where(User.email == 'tomas.varga@example.org'))  # trk_03 only
    project = db.scalar(select(Project).where(Project.external_id == 'prj_01'))     # trk_04
    rv_id = db.scalar(select(RubricCriterion.rubric_version_id).limit(1))
    ev = Evaluation(judge_id=judge.id, project_id=project.id, rubric_version_id=rv_id,
                    status='submitted', comment='trust-injection-test', submitted_at=utcnow())
    db.add(ev); db.flush()
    for c in db.scalars(select(RubricCriterion)).all():
        db.add(RubricScore(evaluation_id=ev.id, criterion_id=c.id, score=4))
    db.commit()
    print('injected evaluation', ev.id)
PY
curl -s -m 60 --retry 3 -X POST -H "$ORG" "$BASE/api/trust/scan" > /tmp/scan_inject.json
python3 - <<'PY'
import json
scan = json.load(open('/tmp/scan_inject.json'))
flags = json.load(open('/tmp/flags.json'))  # stale; refetch below
assert scan['created'] >= 1, f"injected violation produced no new flag: {scan}"
print(f"PASS: injected out-of-track review flagged (created={scan['created']})")
PY
curl -s -H "$ORG" "$BASE/api/trust/flags?detector=out_of_track" > /tmp/oot.json
docker exec -i isr-backend-1 python - <<'PY'
from sqlalchemy import delete, select
from app.core.db import SessionLocal
from app.models import Evaluation, RubricScore, TrustFlag
with SessionLocal() as db:
    ev = db.scalar(select(Evaluation).where(Evaluation.comment == 'trust-injection-test'))
    db.execute(delete(RubricScore).where(RubricScore.evaluation_id == ev.id))
    db.delete(ev)
    db.execute(delete(TrustFlag).where(TrustFlag.detector == 'out_of_track'))
    db.commit()
print('injection cleaned up')
PY
curl -s -m 60 --retry 3 -X POST -H "$ORG" "$BASE/api/trust/scan" > /tmp/scan_clean.json
python3 - <<'PY'
import json
scan = json.load(open('/tmp/scan_clean.json'))
assert scan['created'] == 0, f'cleanup left findings behind: {scan}'
print(f"PASS: state restored after cleanup (created={scan['created']}, open={scan['open']})")
PY
curl -s -H "$ORG" "$BASE/api/trust/flags?flag_status=open" > /tmp/flags_open.json
FLAG_ID=$(python3 -c 'import json; d=json.load(open("/tmp/flags_open.json")); flags=[f["id"] for f in d["flags"] if f["status"]=="open"]; assert flags, "no open flags available"; print(flags[0])')
curl -s -X POST -H "$ORG" "$BASE/api/trust/flags/$FLAG_ID/resolved" > /tmp/flag.json
python3 - <<'PY'
import json
f = json.load(open('/tmp/flag.json'))
assert f['status'] == 'resolved', f"flag {f['id']} not resolved: {f['status']}"
print(f"resolved flag {f['id']}: {f['title']}")
PY
curl -s -m 60 --retry 3 -X POST -H "$ORG" "$BASE/api/trust/scan" > /tmp/scan3.json
curl -s -H "$ORG" "$BASE/api/trust/flags?flag_status=resolved" > /tmp/resolved.json
python3 - <<'PY'
import json
d3 = json.load(open('/tmp/scan3.json'))
assert d3['created'] == 0, 'rescan re-created resolved flag under a new key'
resolved = json.load(open('/tmp/resolved.json'))
match = [f for f in resolved['flags'] if f['id'] == json.load(open('/tmp/flag.json'))['id']]
assert match and match[0]['status'] == 'resolved', 'resolved flag was re-opened by rescan'
print(f"PASS: disposition persisted across rescan (scan created={d3['created']}, open={d3['open']})")
PY
# Reset the disposition so this script is re-runnable.
docker exec -i isr-backend-1 python - "$FLAG_ID" <<'PY'
import sys
from app.core.db import SessionLocal
from app.models import TrustFlag
with SessionLocal() as db:
    flag = db.get(TrustFlag, int(sys.argv[1]))
    flag.status = 'open'
    flag.resolved_by = None
    flag.resolved_at = None
    db.commit()
print('disposition reset for re-runs')
PY

echo
echo "ALL TRUST CHECKS PASSED"
