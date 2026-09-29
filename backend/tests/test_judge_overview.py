"""Evaluator dashboard overview: one call, judge-scoped, with pending state
and the judge's own ranking context. Re-evaluation semantics are covered in
test_evaluator_flow; here we verify the overview contract."""
from tests.conftest import _cookie


def test_overview_shape_and_privacy(client):
    r = client.get("/api/judge/overview", headers=_cookie("judge_a"))
    assert r.status_code == 200
    body = r.json()

    assert body["judge"]["name"], "judge name must be present for the dashboard header"
    assert body["event"] and body["event"]["code"]
    assert body["totals"]["projects"] == len(body["projects"]) > 0

    for row in body["projects"]:
        # Every project row carries what the dashboard renders.
        for key in ("external_id", "title", "summary", "repo_url", "track", "team",
                    "evaluated", "has_ai_review", "my_weighted", "my_rank", "ranked_count"):
            assert key in row, f"missing {key}"
        # Rank context only exists for projects this judge has evaluated.
        if not row["evaluated"]:
            assert row["my_rank"] is None and row["my_weighted"] is None

    assert body["totals"]["evaluated"] + body["totals"]["pending"] == body["totals"]["projects"]


def test_overview_is_judge_scoped(client):
    """Two judges looking at the same event see their own evaluated flags."""
    a = client.get("/api/judge/overview", headers=_cookie("judge_a")).json()
    b = client.get("/api/judge/overview", headers=_cookie("judge_b")).json()
    assert a["judge"]["email"] != b["judge"]["email"]

    def by_id(rows):
        return {r["external_id"]: r for r in rows}

    ra, rb = by_id(a["projects"]), by_id(b["projects"])
    # prj_05: judge_a evaluated (see test_evaluator_flow), judge_b may not have.
    a_evaluated = {ext for ext, r in ra.items() if r["evaluated"]}
    b_evaluated = {ext for ext, r in rb.items() if r["evaluated"]}
    assert "prj_05" in a_evaluated
    assert a_evaluated != b_evaluated or b_evaluated == set(), \
        "each judge must see only their own evaluation state"


def test_overview_requires_judge(client, participant_cookie, organizer_cookie):
    for cookie in (participant_cookie, organizer_cookie):
        r = client.get("/api/judge/overview", headers=cookie)
        assert r.status_code == 403
    assert client.get("/api/judge/overview").status_code == 401
