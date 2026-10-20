"""Reversal candidates: services/positional_engine/reversal_service.py on REAL staging rows, and the route
GET /api/positional/reversal-candidates.

Fixture tests/fixtures/reversal_snapshot_20261019.json holds 13 stocks copied unedited from the output of the data
platform's GET /v1/features/reversal-snapshot for the 2026-10-19 session (see its "captured" note). Statuses pinned
below are what reversal-rules.v1 produced on those rows when the fixture was captured: a regression guard for the
rules, NOT a claim that any stock is a good trade. No database and no network; daas_client.get_raw is replaced.

Cases follow test_reports/reversal_engine_20261020.md (RV-5, RV-8, RV-10, RV-13, RV-15, RV-18).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, List, Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.positional as route
from services.positional_engine import reversal_rules as rr
from services.positional_engine import reversal_service as svc

SNAP = json.loads((Path(__file__).parent / "fixtures" / "reversal_snapshot_20261019.json").read_text())


def _client(monkeypatch, *, body: Any = None, status: int = 200, error: Optional[Exception] = None, configured=True):
    calls: List[tuple] = []

    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    async def get_raw(path, params=None, timeout=10.0):
        calls.append((path, params))
        if error:
            raise error
        return status, copy.deepcopy(SNAP if body is None else body)

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(route.daas_client, "is_configured", lambda: configured)
    route._reversal_cache.clear()
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def _by_symbol(out):
    return {r["symbol"]: r for r in out["rows"] + out["excluded"]}


# ── service on real rows ──────────────────────────────────────────────────────

def test_real_rows_pinned_statuses_and_exclusions():
    out = svc.run(SNAP, 15.0, view="all")
    rows = _by_symbol(out)
    assert rows["MSUMI"]["status"] == "trigger_ready"
    assert rows["BHARTIARTL"]["status"] == "early_reversal"
    assert rows["BANKBEES"]["exclusion"] == "scanner_etf"
    assert rows["BHARATCOAL"]["exclusion"] == "insufficient_history"
    assert rows["AFCONS"]["exclusion"] == "high_pledge"
    assert rows["PACEDIGITK"]["exclusion"] == "setup_invalidated"
    assert rows["PNBGILTS"]["exclusion"] == "financial_distress"
    assert rows["CROMPTON"]["status"] == "near_low_no_evidence" and rows["CROMPTON"]["evidence"]["core_true"] < 3


def test_every_listed_row_obeys_the_contract():
    out = svc.run(SNAP, 15.0, view="candidates")
    assert out["rows"], "fixture must hold candidates"
    for r in out["rows"]:
        assert r["distance"]["distance_from_52w_low_pct"] <= 15.0
        assert r["evidence"]["core_true"] >= rr.CANDIDATE["min_core_true"]
        assert set(r["components"]) == set(rr.WEIGHTS)
        for name, c in r["components"].items():
            assert c["known"] == (c["score"] is not None)
            assert (name in r["score"]["unknown_components"]) == (not c["known"])
        assert r["score"]["coverage_pct"] == round(sum(c["weight"] for c in r["components"].values() if c["known"]), 1)
        assert r["levels"]["hypothetical"] is True
        assert set(r["explanation"]) == {"why_this_stock", "why_now", "confirms", "uncertain", "invalidates", "entry_trigger"}
    totals = [r["score"]["total"] for r in out["rows"]]
    order = {s: i for i, s in enumerate(reversed(rr.STATUSES))}
    assert [order[r["status"]] for r in out["rows"]] == sorted(order[r["status"]] for r in out["rows"])
    assert out["data_limits"] and out["rules"]["version"] == rr.RULES_VERSION and totals


def test_threshold_sensitivity_pool_grows_with_threshold():
    sizes = []
    for pct in rr.NEAR_LOW["sensitivity_pcts"]:
        out = svc.run(SNAP, pct, view="all")
        sizes.append(out["universe"]["listed"])
        assert out["near_low_pct"] == pct
        assert all(r["distance"]["distance_from_52w_low_pct"] <= pct for r in out["rows"] if "distance" in r)
    assert sizes == sorted(sizes)


def test_unclassified_industry_has_unknown_sector_not_neutral():
    snap = copy.deepcopy(SNAP)
    for r in snap["rows"]:
        r["industry"] = None
    out = svc.run(snap, 15.0, view="all")
    cands = [r for r in out["rows"] if r["status"] in ("early_reversal", "trigger_ready")]
    assert cands
    for r in cands:
        assert r["components"]["sector"]["score"] is None and "sector" in r["score"]["unknown_components"]
        assert r["sector_context"] is None


def test_missing_benchmark_close_makes_relative_strength_unknown():
    snap = copy.deepcopy(SNAP)
    snap["benchmark_closes"] = snap["benchmark_closes"][:-1]          # drop the last day
    out = svc.run(snap, 15.0, view="all")
    r = _by_symbol(out)["BHARTIARTL"]
    assert r["signals"]["rs_vs_index"]["state"] == "unknown"
    assert "rs_vs_index" not in [k for k, v in r["signals"].items() if v["state"] == "true"]


def test_announcement_after_as_of_is_ignored():
    snap = copy.deepcopy(SNAP)
    row = next(r for r in snap["rows"] if r["symbol"] == "BHARTIARTL")
    row["announcements"] = [{"filed_at": "2026-10-21T09:00:00+00:00", "impact_score": "high",
                             "sentiment": "positive", "subject": "after the session"}]
    r = _by_symbol(svc.run(snap, 15.0, view="all"))["BHARTIARTL"]
    assert r["components"]["catalyst"]["score"] is None


def test_service_does_not_mutate_the_snapshot():
    snap = copy.deepcopy(SNAP)
    svc.run(snap, 15.0, view="all")
    assert snap == SNAP


# ── route ─────────────────────────────────────────────────────────────────────

def test_route_returns_contract_and_asks_daas_for_the_widest_pool(monkeypatch):
    client, calls = _client(monkeypatch)
    r = client.get("/api/positional/reversal-candidates")
    assert r.status_code == 200
    j = r.json()
    assert calls == [("/features/reversal-snapshot", {"max_dist_pct": 25.0})]
    assert j["near_low_pct"] == 15.0 and j["mode"] == "eod" and "no order is sent" in j["scope"]
    assert j["as_of"] == "2026-10-19" and j["rules"]["version"] == rr.RULES_VERSION
    assert j["prefilter"]["returned"] == 407 and j["benchmark"] == "Nifty 500"
    assert {"sectors", "universe", "rows", "excluded", "data_limits", "source"} <= set(j)
    assert any(x["symbol"] == "MSUMI" for x in j["rows"]) and any(x["exclusion"] == "high_pledge" for x in j["excluded"])
    assert all(x["status"] != "near_low_no_evidence" for x in j["rows"])


def test_route_threshold_and_view_params(monkeypatch):
    client, _ = _client(monkeypatch)
    wide = client.get("/api/positional/reversal-candidates?near_pct=20&view=all").json()
    narrow = client.get("/api/positional/reversal-candidates?near_pct=10&view=all").json()
    assert wide["near_low_pct"] == 20.0 and narrow["near_low_pct"] == 10.0
    assert len(wide["rows"]) >= len(narrow["rows"])
    assert any(x["status"] == "near_low_no_evidence" for x in wide["rows"])
    assert client.get("/api/positional/reversal-candidates?limit=2").json()["rows"].__len__() <= 2


@pytest.mark.parametrize("q", ["near_pct=4.9", "near_pct=25.1", "near_pct=abc", "view=bogus", "limit=0", "limit=301"])
def test_route_rejects_bad_params(monkeypatch, q):
    client, calls = _client(monkeypatch)
    assert client.get(f"/api/positional/reversal-candidates?{q}").status_code == 422
    assert calls == []


def test_route_upstream_failure_is_502_never_an_empty_list(monkeypatch):
    for kw in ({"error": route.daas_client.DaasError("down")}, {"status": 500}, {"body": {"rows": []}},
               {"body": {"as_of": "2026-10-19", "rows": "x"}}, {"configured": False}):
        client, _ = _client(monkeypatch, **kw)
        r = client.get("/api/positional/reversal-candidates")
        assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable", kw


def test_route_malformed_snapshot_is_502(monkeypatch):
    bad = copy.deepcopy(SNAP)
    bad["rows"][0]["bars"] = [["2026-10-19"]]
    client, _ = _client(monkeypatch, body=bad)
    assert client.get("/api/positional/reversal-candidates").status_code == 502


def test_route_caches_one_read(monkeypatch):
    client, calls = _client(monkeypatch)
    client.get("/api/positional/reversal-candidates")
    client.get("/api/positional/reversal-candidates?near_pct=20")
    assert len(calls) == 1
