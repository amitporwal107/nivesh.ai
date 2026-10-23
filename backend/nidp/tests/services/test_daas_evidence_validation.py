"""DaaS /v1/desk/evidence/post-disclosure-study — the frozen post-disclosure forward-returns study
(nidp/services/daas_api/routers/evidence_validation.py).

No live Postgres and no mock DB: this router serves a FROZEN snapshot of an already-run,
hash-guarded research study, so there is nothing to query. These tests assert the DISPLAYED
contract and result fields against the real numbers in the study's own report
(test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md, branch
study/post-disclosure-forward-returns @ 62443b98) — not merely that the endpoint returns 200.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}


@pytest.fixture
def client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import evidence_validation

    rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t",
                         owner_email="t@nivesh", plan="internal", rate_limit_rpm=1500, daily_quota=None,
                         status="active", expires_at=None)

    async def _resolve(_t):
        return rec
    monkeypatch.setattr(auth, "_resolve", _resolve)

    async def _consume(key_id, *, limit_rpm, daily_quota):
        return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1,
                                       reset_seconds=60, daily_quota=daily_quota, daily_used=1,
                                       daily_remaining=None, reason=None)
    monkeypatch.setattr(ratelimit, "consume", _consume)

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def _validation(_request, exc):
        return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

    app.include_router(evidence_validation.router, prefix="/v1")
    return TestClient(app)


def _get(client):
    r = client.get("/v1/desk/evidence/post-disclosure-study", headers=H)
    assert r.status_code == 200
    return r.json()


# ── the headline: INCONCLUSIVE, loud, top-level ──────────────────────────────

def test_verdict_is_inconclusive_and_is_top_level(client):
    body = _get(client)
    assert body["verdict"] == "INCONCLUSIVE"
    assert "verdict_reason" in body and body["verdict_reason"]


def test_disclosure_names_no_score_no_rank_no_buy_sell(client):
    body = _get(client)
    d = body["disclosure"].lower()
    assert "research artifact" in d and "not a product feature" in d
    assert "no predictive score" in d and "no ranking" in d


# ── study contract fields, exact per the pre-registered study ───────────────

def test_study_period_and_quarters(client):
    body = _get(client)
    assert body["study_period"] == {"start": "2024-03-31", "end": "2026-06-30"}
    assert body["quarters"] == 10
    assert body["review_floor_blocks"] == 12


def test_primary_horizon_is_20_secondary_are_5_and_60(client):
    body = _get(client)
    assert body["primary_horizon_sessions"] == 20
    assert sorted(body["secondary_horizons_sessions"]) == [5, 60]


def test_eligible_population_matches_the_real_study_output(client):
    body = _get(client)
    # "Eligible after screens : 1255" — test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md §4
    assert body["eligible_population"] == 1255


def test_preregistration_sha256_is_recorded_for_provenance(client):
    body = _get(client)
    assert body["preregistration_sha256"] == "5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071"


# ── the mean spread + CI + blocks + positive-quarters, not just a point estimate ─

def test_primary_horizon_row_carries_spread_ci_blocks_and_positive_quarters(client):
    body = _get(client)
    rows = {r["sessions"]: r for r in body["rows"]}
    primary = rows[20]
    assert primary["is_primary"] is True
    # "mean spread +1.0749 pp | 95% CI [-0.8673, +2.9054] pp | blocks 10 | positive quarters 6/10"
    assert primary["mean_spread_pp"] == pytest.approx(1.0749)
    assert primary["ci_low_pp"] == pytest.approx(-0.8673)
    assert primary["ci_high_pp"] == pytest.approx(2.9054)
    assert primary["blocks"] == 10
    assert primary["positive_quarters"] == 6


def test_secondary_horizons_are_present_with_their_own_ci(client):
    body = _get(client)
    rows = {r["sessions"]: r for r in body["rows"]}
    assert rows[5]["mean_spread_pp"] == pytest.approx(-0.0007)
    assert rows[5]["ci_low_pp"] == pytest.approx(-1.1932)
    assert rows[5]["ci_high_pp"] == pytest.approx(1.1074)
    assert rows[60]["mean_spread_pp"] == pytest.approx(-0.7468)
    assert rows[60]["ci_low_pp"] == pytest.approx(-5.6316)
    assert rows[60]["ci_high_pp"] == pytest.approx(3.6992)


def test_only_one_row_is_marked_primary(client):
    body = _get(client)
    primaries = [r for r in body["rows"] if r["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["sessions"] == 20


# ── the cost-adjusted figure, shown explicitly, never hidden ─────────────────

def test_cost_adjusted_figure_is_explicit(client):
    body = _get(client)
    assert body["cost_total_pp"] == pytest.approx(0.9874)
    primary = next(r for r in body["rows"] if r["sessions"] == 20)
    # "net of 0.9874 pp costs +0.0875 pp"
    assert primary["net_of_cost_pp"] == pytest.approx(0.0875)


# ── September 2026: its own explicit field, never silently omitted ──────────

def test_sep_2026_not_yet_eligible_is_its_own_field(client):
    body = _get(client)
    nye = body["not_yet_eligible"]
    assert nye["quarter"] == "2026-09-30"
    assert "not yet eligible" in nye["reason"].lower()
    assert "forward" in nye["reason"].lower()
    # it must not appear as a scored/eligible horizon row
    assert all(r["sessions"] != "2026-09-30" for r in body["rows"])


def test_sep_2026_is_not_rendered_as_zero_or_positive(client):
    """The absent quarter must never surface as a 0 spread or a positive figure anywhere."""
    body = _get(client)
    assert "2026-09-30" not in {r.get("mean_spread_pp") for r in body["rows"]}
    # Confirm it is not folded into the quarters count (10 means it is excluded, not padded to 11).
    assert body["quarters"] == 10


# ── no Nifty 500 TRI row, anywhere ───────────────────────────────────────────

def test_no_tri_benchmark_row_anywhere_in_the_payload(client):
    """The disclosure text is allowed to SAY no TRI exists (that is the honest, required framing,
    matching ownership.py's house style) — what must never appear is a TRI used AS a benchmark:
    no row or top-level field may carry a benchmark/TRI/excess-return VALUE."""
    body = _get(client)
    for key in ("benchmark", "benchmark_return_pp", "tri_return_pp", "excess_return_pp", "vs_nifty"):
        for r in body["rows"]:
            assert key not in r
        assert key not in body


def test_benchmark_note_explains_there_is_no_tri(client):
    body = _get(client)
    note = body["benchmark_note"].lower()
    assert "no" in note and ("total-return" in note or "total return" in note)
    assert "price index" in note


# ── no score, no rank, no signal anywhere in the shape ───────────────────────

def test_no_score_rank_or_signal_fields_anywhere(client):
    body = _get(client)
    import json
    blob = json.loads(json.dumps(body))

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                lk = k.lower()
                assert lk not in ("score", "rank", "signal", "buy", "sell", "recommendation")
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(blob)


def test_count_and_total_describe_the_horizon_rows(client):
    body = _get(client)
    assert body["count"] == 3 and body["total"] == 3 and len(body["rows"]) == 3
