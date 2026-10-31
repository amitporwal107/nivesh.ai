"""Trading desk evidence proxy on the app side:

    GET /api/markets/evidence/post-disclosure-study   routes/markets_evidence.py -> DaaS
                                                       /v1/desk/evidence/post-disclosure-study

No network: `daas_client.get_raw` is replaced by a recorder that answers with a fixture body
(MOCK — not real data, in the real contract shape) so this route's own work runs for real: auth,
what is forwarded, the pass-through and the error mapping. The DaaS router's real figures are
tested in nidp/tests/services/test_daas_evidence_validation.py against the real study report.
"""
from __future__ import annotations

import copy
from typing import Any, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import markets_evidence as evidence_route
from services.copilot_tools import daas_client

Calls = List[Tuple[str, Optional[dict]]]

STUDY = {
    "as_of": "2026-10-23", "study_id": "NIDP-SHP-FWD-001",
    "title": "Post-disclosure forward returns by institutional ownership change",
    "stage": "exploratory",
    "preregistration_sha256": "5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071",
    "source": "study/post-disclosure-forward-returns@62443b98",
    "disclosure": "RESEARCH ARTIFACT. NOT A PRODUCT FEATURE. No predictive score, no ranking.",
    "verdict": "INCONCLUSIVE", "verdict_reason": "CI straddles zero; below review floor.",
    "study_period": {"start": "2024-03-31", "end": "2026-06-30"}, "quarters": 10,
    "review_floor_blocks": 12, "primary_horizon_sessions": 20, "secondary_horizons_sessions": [5, 60],
    "hurdle_pp": 1.0, "cost_pct_round_trip_per_leg": 0.4937, "cost_total_pp": 0.9874,
    "eligible_population": 1255, "eligible_primary_estimand_n": 1248,
    "not_yet_eligible": {"quarter": "2026-09-30", "reason": "Not yet eligible for forward-return evaluation."},
    "excluded_quarters": [], "benchmark_note": "No Nifty 500 TRI exists in this warehouse.",
    "robustness_note": "Sign not robust across specifications.", "robustness_20_sessions": [],
    "count": 3, "total": 3,
    "rows": [
        {"sessions": 5, "is_primary": False, "mean_spread_pp": -0.0007, "ci_low_pp": -1.1932,
         "ci_high_pp": 1.1074, "blocks": 10, "positive_quarters": 5, "net_of_cost_pp": -0.9881},
        {"sessions": 20, "is_primary": True, "mean_spread_pp": 1.0749, "ci_low_pp": -0.8673,
         "ci_high_pp": 2.9054, "blocks": 10, "positive_quarters": 6, "net_of_cost_pp": 0.0875},
        {"sessions": 60, "is_primary": False, "mean_spread_pp": -0.7468, "ci_low_pp": -5.6316,
         "ci_high_pp": 3.6992, "blocks": 10, "positive_quarters": 5, "net_of_cost_pp": -1.7342},
    ],
}


def _client(monkeypatch, reply: Any, *, signed_in: bool = True, configured: bool = True) -> Tuple[TestClient, Calls]:
    calls: Calls = []

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, params))
        r = reply(path) if callable(reply) else reply
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(evidence_route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(evidence_route.router)
    return TestClient(app), calls


def test_post_disclosure_study_is_passed_through_unchanged(monkeypatch):
    c, calls = _client(monkeypatch, (200, STUDY))
    r = c.get("/api/markets/evidence/post-disclosure-study")
    assert r.status_code == 200 and r.json() == STUDY
    assert calls == [("/desk/evidence/post-disclosure-study", None)]


def test_verdict_and_rows_survive_the_proxy_unchanged(monkeypatch):
    c, _ = _client(monkeypatch, (200, STUDY))
    body = c.get("/api/markets/evidence/post-disclosure-study").json()
    assert body["verdict"] == "INCONCLUSIVE"
    primary = next(r for r in body["rows"] if r["is_primary"])
    assert primary["sessions"] == 20
    assert primary["mean_spread_pp"] == pytest.approx(1.0749)
    assert primary["ci_low_pp"] == pytest.approx(-0.8673) and primary["ci_high_pp"] == pytest.approx(2.9054)
    assert body["not_yet_eligible"]["quarter"] == "2026-09-30"


FAILURES = [
    pytest.param((503, {"detail": "down"}), id="http-503"),
    pytest.param((404, {"detail": "Not Found"}), id="route-not-deployed"),
    pytest.param((200, {"as_of": "2026-10-23"}), id="200-without-the-rows"),
    pytest.param((200, None), id="200-not-json"),
    pytest.param(daas_client.DaasError("timed out"), id="unreachable"),
]


@pytest.mark.parametrize("reply", FAILURES)
def test_a_failing_data_platform_is_502_never_a_fabricated_study(monkeypatch, reply):
    c, _ = _client(monkeypatch, reply)
    r = c.get("/api/markets/evidence/post-disclosure-study")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_an_unconfigured_data_platform_is_502_and_is_not_called(monkeypatch):
    c, calls = _client(monkeypatch, (200, STUDY), configured=False)
    assert c.get("/api/markets/evidence/post-disclosure-study").status_code == 502 and calls == []


def test_evidence_route_needs_a_signed_in_user(monkeypatch):
    c, calls = _client(monkeypatch, (200, STUDY), signed_in=False)   # the real deps.get_current_user
    r = c.get("/api/markets/evidence/post-disclosure-study")
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})
    assert calls == []
