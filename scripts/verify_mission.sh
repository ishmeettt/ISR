#!/usr/bin/env bash
# Mission Control live verification. Run against a seeded ISR portal:
#   bash scripts/verify_mission.sh [base_url]
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

echo "== RBAC: mission control is organizer-only =="
c=$(code "$BASE/api/mission-control"); echo "no-auth     GET -> $c"; [ "$c" = "401" ] || fail "should require auth"
c=$(code -H "$PRT" "$BASE/api/mission-control"); echo "participant GET -> $c"; [ "$c" = "403" ] || fail "participant must not read"

echo
echo "== Payload sanity + fixture-known numbers =="
curl -s --retry 3 -H "$ORG" "$BASE/api/mission-control" > /tmp/mc.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/mc.json'))
p, j, t = d['participation'], d['judging'], d['trust']

assert p['projects'] == 41, f"expected 41 projects, got {p['projects']}"
assert p['teams'] == 40, f"expected 40 teams, got {p['teams']}"
assert j['completed'] == 126, f"expected 126 evaluations, got {j['completed']}"
assert j['judges'] == 30, f"expected 30 judges, got {j['judges']}"
assert j['assigned'] == j['completed'] == 126 and j['pending'] == 0
assert j['completion_percent'] == 100.0, f"completion {j['completion_percent']}"
assert len(d['workload']) == 30, f"workload rows {len(d['workload'])}"
top = d['workload'][0]
assert top['completed'] == 11, f"busiest judge should have 11, got {top['completed']} ({top['judge']})"
assert len(d['coverage_gaps']) == 8, f"expected 8 coverage gaps, got {len(d['coverage_gaps'])}"
assert all(g['reviews'] == 2 and g['modal'] == 3 for g in d['coverage_gaps'])
assert t['by_status']['resolved'] >= 0 and 'open' in t['by_status']
assert d['leader'] is not None and d['leader']['final_score'] > 0
assert d['event']['name'] == 'Sample Hack 2026'
print(f"projects={p['projects']} teams={p['teams']} judges={j['judges']} reviews={j['completed']}/{j['assigned']} ({j['completion_percent']}%)")
print(f"busiest judge: {top['judge']} ({top['completed']} reviews)")
print(f"coverage gaps: {len(d['coverage_gaps'])} projects at 2/3 reviews")
print(f"trust open={t['by_status']['open']} resolved={t['by_status']['resolved']}")
print(f"leader: {d['leader']['title']} ({d['leader']['final_score']})")
print(f"runs listed: {len(d['runs'])}")
print("PASS: all numbers match fixture ground truth")
PY

echo
echo "== Cross-checks: workload/gaps agree with FairScore + Trust =="
python3 - <<'PY'
import json, urllib.request

def get(path):
    req = urllib.request.Request('http://127.0.0.1:8000' + path,
                                 headers={'Cookie': 'session=91e0d703c0dcdda4b06db2bf97998b59'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)

mc = json.load(open('/tmp/mc.json'))
ranking = get('/api/results')['ranking']
flags = get('/api/trust/flags?flag_status=open')['flags']

leader = mc['leader']
top_row = ranking[0]
# Mission displays the score rounded to 4dp; the ranking endpoint to 6dp —
# so compare within display rounding, but require the same project and run.
assert top_row['project'] == leader['project'] and abs(top_row['final_score'] - leader['final_score']) < 5e-5, \
    'mission leader disagrees with FairScore ranking'
assert top_row['rank'] == 1

gap_titles = {g['project'] for g in mc['coverage_gaps']}
low_cov_flags = {f['title'].split(' has ')[0] for f in flags if f['detector'] == 'low_coverage'}
assert gap_titles == low_cov_flags, f'gap mismatch: {gap_titles ^ low_cov_flags}'

print('PASS: leader matches FairScore #1; gaps match low_coverage flags exactly')
PY

echo
echo "ALL MISSION CONTROL CHECKS PASSED"
