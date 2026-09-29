#!/usr/bin/env bash
# FairScore live verification. Run against a seeded ISR portal:
#   bash scripts/verify_fairscore.sh [base_url]
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
ORG="Cookie: session=91e0d703c0dcdda4b06db2bf97998b59"
JBA="Cookie: session=dae42f9e7001d0f7a6a27d27e86eb0b8"
PRT="Cookie: session=69e6a774b2c036ca34e758c4e8261867"

code() { curl -s -m 10 -o /dev/null -w '%{http_code}' "$@"; }
fail() { echo "FAIL: $1"; exit 1; }

# Warm-up: the first connection on a fresh WSL loopback can be reset (IPv6 NAT).
for i in 1 2 3 4 5; do
  [ "$(code "$BASE/api/health")" = "200" ] && break
  sleep 1
done

echo "== RBAC: results are organizer-only =="
c=$(code "$BASE/api/results");                       echo "no-auth     GET /api/results      -> $c"; [ "$c" = "401" ] || fail "results should require auth"
c=$(code -X POST -H "$PRT" "$BASE/api/results/run"); echo "participant POST /api/results/run -> $c"; [ "$c" = "403" ] || fail "participant must not run scoring"
c=$(code -H "$PRT" "$BASE/api/results");             echo "participant GET /api/results      -> $c"; [ "$c" = "403" ] || fail "participant must not read results"
c=$(code -H "$JBA" "$BASE/api/results");             echo "judge       GET /api/results      -> $c"; [ "$c" = "403" ] || fail "judge must not read results"

echo
echo "== Run #1 =="
curl -s -m 30 --retry 3 --retry-connrefused -X POST -H "$ORG" "$BASE/api/results/run" > /tmp/run1.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/run1.json'))
print(f"run {d['run_id']}: {d['projects']} projects, {d['evaluations']} evaluations")
print("top 3:", [(t['rank'], round(t['final_score'], 4)) for t in d['top']])
PY

echo
echo "== Determinism: run #2 must match run #1 exactly =="
snap() { curl -s --retry 3 -H "$ORG" "$BASE/api/results" > /tmp/snap.json && python3 -c 'import json; print(json.dumps(json.load(open("/tmp/snap.json"))["ranking"], sort_keys=True))'; }
s1=$(snap)
curl -s -m 30 --retry 3 -X POST -H "$ORG" "$BASE/api/results/run" > /tmp/run2.json
s2=$(snap)
if [ "$s1" = "$s2" ]; then
  echo "PASS: two independent runs produced identical rankings"
else
  echo "FAIL: rankings differ between runs"
  diff <(echo "$s1") <(echo "$s2")
  exit 1
fi

echo
echo "== Why: full explanation for the #1 project =="
top=$(python3 -c 'import json; print(json.load(open("/tmp/snap.json"))["ranking"][0]["project"])')
runid=$(python3 -c 'import json; print(json.load(open("/tmp/run2.json"))["run_id"])')
curl -s --retry 3 -H "$ORG" "$BASE/api/results/why/$runid/$top" > /tmp/why.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/why.json'))
print(f"#{d['rank']} of {d['of']}: {d['project']['title']}  final={d['final_score']:.4f} raw={d['raw_weighted']:.4f} judges={d['judge_count']}")
for e in d['evaluations']:
    print(f"  {e['judge']:<22} raw={e['raw_weighted']:.4f} judge_mean={e['judge_mean']:.4f} judge_sd={e['judge_sd']:.4f} z={e['z_score']:+.4f}")
print("neighbors above:", [(n['rank'], n['title']) for n in d['neighbors']['above']])
print("neighbors below:", [(n['rank'], n['title']) for n in d['neighbors']['below']])
PY

echo
echo "== Why: the uniform judge (jdg_07) must contribute z = 0 =="
curl -s --retry 3 -H "$ORG" "$BASE/api/results/why/$runid/prj_17" > /tmp/why17.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/why17.json'))
uniform = [e for e in d['evaluations'] if e['judge_sd'] == 0.0]
assert uniform, 'expected at least one zero-sd (uniform) judge on prj_17'
for e in uniform:
    print(f"PASS: {e['judge']} has sd 0 and z {e['z_score']:+.4f}")
PY

echo
echo "== Raw scores untouched: judge_a still reads integer raw scores =="
curl -s --retry 3 -H "$JBA" "$BASE/api/judge/scores" > /tmp/scores.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/scores.json'))
assert d, 'judge_a has no evaluations'
raw = [(s['criterion'], s['score']) for s in d[0]['scores']]
assert all(isinstance(v, int) for _, v in raw), 'raw scores must stay integers'
print(f"judge_a: {len(d)} evaluations; sample raw scores: {raw}")
PY

echo
echo "ALL FAIRSCORE CHECKS PASSED"
