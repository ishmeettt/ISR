# JUDGING — rubric, normalization, isolation

## Rubric

Fixture scores (loaded from the repo-root `fixtures.json`) carry three criteria. ISR stores
them with these weights (`backend/app/seed.py`, `RUBRIC_WEIGHTS`):

| criterion     | weight |
|---------------|--------|
| functionality | 40%    |
| quality       | 35%    |
| innovation    | 25%    |

Each criterion is scored 0–5 (`max_score=5`). The weighted final score of an evaluation is
`Σ (score / max_score) × weight` — raw scores are never mutated; normalization writes new
values alongside them (see below).

## Import decisions forced by the fixtures

1. **Out-of-track score records exist** (e.g. a trk_07 judge scoring trk_03 projects).
   Historical seeded scores are imported as-is — deleting them would falsify the record.
   Live judging instead checks `judge_tracks` eligibility before allowing a new evaluation.
2. **A duplicate submission exists** (same team, same repo, resubmitted minutes before close).
   Both rows are kept; dedup/flagging is a later trust-engine concern, not a seed concern.
3. **Some projects have only 2 reviews.** Coverage gaps are reported, not papered over.

## Judge isolation contract

`GET /api/judge/scores` resolves the judge **from the session cookie only**. A `judge_email`
query parameter is permitted solely when it matches the caller (used by the acceptance
suite's `peer_scores` route); any other value is a 403 before any data is read. A judge's
evaluation list is `WHERE evaluations.judge_id = <session judge>` — there is no code path
that returns one judge's scores to another principal.

## Normalization — FairScore (implemented)

Raw scores are never modified. Each **run** (organizer: `POST /api/results/run`) is an
immutable `normalization_runs` row with its method and parameters, and persists every
intermediate in `normalized_scores` (per evaluation: raw composite, judge mean, judge sd,
z) and `ranking_results` (per project: rank, final score, raw mean, judge count, coverage).

```
RAW COMPOSITE  Σ (score / max) × weight          ∈ [0, 1]
NORMALIZATION  z = (raw − judge_mean) / judge_sd   (population sd; z = 0 when sd = 0)
FINAL          mean z per project; ties → lower project id
```

Judge B's generosity is neutralized per judge, and a judge who gives every project the
same composite (the fixture's uniform judge) contributes z = 0 — separation without
punishing consistent-but-uninformative reviewers.

### Explanation endpoint

`GET /api/results/why/{run_id}/{project}` re-derives the full chain from persisted
intermediates: each judge's raw composite against that judge's own mean/sd, the z that
evaluation contributed, the final mean z, coverage, and the two ranked neighbours above
and below. No opaque step — the same rows recomputed always produce the same answer.

## Trust engine

Detectors run on demand (`POST /api/trust/scan`, organizer-only) and upsert findings into
`trust_flags` with a stable key per (detector, subject), so re-scans refresh evidence
without duplicating or re-opening flags an organizer already resolved or dismissed.

| detector             | severity | what it finds |
|----------------------|----------|---------------|
| `uniform_judge`      | medium   | one judge giving the identical raw score vector to ≥ 3 projects |
| `low_coverage`       | info     | projects with fewer reviews than the modal review count |
| `out_of_track`       | medium   | reviews of projects outside the judge's eligible tracks |
| `duplicate_submission` | high   | same team + title + repo submitted more than once |

Flags **surface anomalies, never convict**: they do not alter scores, assignment, or
rankings. Disposition (resolve/dismiss) is an organizer decision, audited via
`TRUST_FLAG_DISPOSITION`. On the fixture data the scan finds the uniform judge (jdg_07),
the duplicate submission (prj_41 re-submitting prj_07) and the low-coverage projects;
the fixture's score records are all in-track, so `out_of_track` correctly reports nothing
(the detector is exercised by injection in `scripts/verify_trust.sh`).
