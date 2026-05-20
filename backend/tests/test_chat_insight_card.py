"""Chat → insight_card envelope wiring tests.

User-visible failure modes guarded:

  1. A `stress test` chat message produces a widget envelope with
     kind=insight_card and severity tracking the projected drawdown.
  2. An `overlap` chat message produces a widget envelope when the
     user has holdings, and None when they don't.
  3. A `tax harvest` chat message produces an envelope with the LTCG
     limit/used/remaining KPIs and the candidates as findings.
  4. A `rebalance` chat message produces an envelope with at least one
     action when allocation drifts.
  5. Intents with no widget mapping return None — chat falls back to
     prose as today, no crash.
  6. Builder failures (DB unreachable) return None instead of raising.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from services.copilot_rag.intent_router import Intent
from services.copilot_rag.orchestrator import _intent_to_envelope


class _FakeCursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = list(rows)

    def __aiter__(self):
        async def gen():
            for r in self._rows:
                yield r
        return gen()


class _FakeCollection:
    def __init__(self, rows: List[Dict[str, Any]] | None = None,
                  one: Dict[str, Any] | None = None):
        self._rows = rows or []
        self._one = one

    def find(self, *_args, **_kwargs):
        return _FakeCursor(self._rows)

    async def find_one(self, *_args, **_kwargs):
        return self._one


@pytest.fixture
def fake_holdings() -> List[Dict[str, Any]]:
    return [
        {"fund_name": "Axis Bluechip", "scheme_code": "AXISBC",
          "current_value": 200000, "asset_class": "equity",
          "unrealised_gain": 12000, "days_held": 500,
          "invested_value": 180000, "plan_type": "Direct"},
        {"fund_name": "ICICI Liquid", "scheme_code": "ICILQ",
          "current_value": 100000, "asset_class": "debt",
          "unrealised_gain": 4000, "days_held": 400,
          "invested_value": 96000, "plan_type": "Direct"},
        {"fund_name": "HDFC Mid-Cap", "scheme_code": "HDMID",
          "current_value": 150000, "asset_class": "equity",
          "unrealised_gain": 18000, "days_held": 800,
          "invested_value": 132000, "plan_type": "Regular"},
    ]


@pytest.fixture
def fake_db(monkeypatch, fake_holdings):
    """Patch deps.db with collections that yield fake_holdings.
    Used everywhere the builders touch Mongo."""
    fake = type("DB", (), {})()
    fake.holdings = _FakeCollection(rows=fake_holdings)
    fake.portfolio_holdings = _FakeCollection(rows=[])  # never falls through
    fake.capital_gains_summary = _FakeCollection(one={"ltcg_booked_rs": 20000})
    # mf_master.find_one returns one doc per scheme_code lookup
    by_code = {
        "AXISBC": {"scheme_name": "Axis Bluechip Direct",
                    "top_holdings": [{"stock_name": "HDFC Bank"},
                                       {"stock_name": "ICICI Bank"},
                                       {"stock_name": "Infosys"}]},
        "ICILQ":  {"scheme_name": "ICICI Liquid Direct",
                    "top_holdings": []},
        "HDMID":  {"scheme_name": "HDFC Mid-Cap Opp",
                    "top_holdings": [{"stock_name": "HDFC Bank"},
                                       {"stock_name": "Reliance"}]},
    }

    class _MFMaster:
        async def find_one(self, query, _proj):
            or_clauses = query.get("$or", [])
            for cl in or_clauses:
                code = cl.get("scheme_code") or cl.get("isin")
                if code in by_code:
                    return by_code[code]
            return None

    fake.mf_master = _MFMaster()

    import services.copilot_tools.widget_builders as WB
    monkeypatch.setattr(WB, "db", fake, raising=True)
    return fake


# ── 1. Stress test ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stress_intent_produces_insight_card(fake_db):
    intent = Intent(name="stress_test", raw="stress test covid",
                     extras={"scenario": "covid_2020"})
    env = await _intent_to_envelope(intent, "u1")
    assert env is not None
    assert env["kind"] == "insight_card"
    assert env["data"]["hero"]["severity"] in ("medium", "high", "critical")
    # Hero headline contains the projected drawdown
    assert "%" in env["data"]["hero"]["headline"]


@pytest.mark.asyncio
async def test_stress_custom_drop_propagates(fake_db):
    intent = Intent(name="stress_test", raw="what if market falls 20%",
                     extras={"scenario": "custom", "custom_equity_drop": -20.0})
    env = await _intent_to_envelope(intent, "u1")
    assert env is not None
    assert "Custom" in env["title"]


# ── 2. Overlap ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overlap_intent_with_holdings(fake_db):
    intent = Intent(name="overlap", raw="check overlap")
    env = await _intent_to_envelope(intent, "u1")
    assert env is not None
    assert env["kind"] == "insight_card"
    # 3 funds resolved → matrix mode (not pairwise pct), but card is
    # well-formed: hero headline present + funds count surfaced as KPI.
    assert env["data"]["hero"]["headline"]
    fund_kpi = next((k for k in env["data"]["kpis"] if k["label"] == "Funds analysed"), None)
    assert fund_kpi is not None
    assert int(fund_kpi["value"]) == 3


@pytest.mark.asyncio
async def test_overlap_intent_with_no_funds_returns_none(monkeypatch, fake_db):
    # Wipe the holdings collections so the builder finds no codes
    import services.copilot_tools.widget_builders as WB
    empty = type("DB", (), {})()
    empty.holdings = _FakeCollection(rows=[])
    empty.portfolio_holdings = _FakeCollection(rows=[])
    empty.mf_master = type("M", (), {"find_one": staticmethod(
        lambda *_a, **_k: (_ for _ in ()).throw(StopIteration))})()
    async def _no_doc(*_a, **_k):
        return None
    empty.mf_master = type("M", (), {"find_one": _no_doc})()
    monkeypatch.setattr(WB, "db", empty, raising=True)

    intent = Intent(name="overlap", raw="check overlap")
    env = await _intent_to_envelope(intent, "u1")
    assert env is None


# ── 3. Tax ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tax_intent_produces_card_with_ltcg_kpis(fake_db):
    intent = Intent(name="tax", raw="ltcg harvest")
    env = await _intent_to_envelope(intent, "u1")
    assert env is not None
    labels = {k["label"] for k in env["data"]["kpis"]}
    assert {"LTCG limit", "Used this FY", "Remaining", "Candidates"} <= labels
    # Education block always present on tax cards
    assert env["data"]["education"] is not None


# ── 4. Rebalance ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_intent_produces_rebalance_card(fake_db):
    intent = Intent(name="plan", raw="what should I do")
    env = await _intent_to_envelope(intent, "u1")
    assert env is not None
    assert env["data"]["hero"]["headline"]
    # At least one action chip
    assert env["data"]["actions"]


@pytest.mark.asyncio
async def test_drift_intent_routes_same_as_plan(fake_db):
    intent = Intent(name="drift", raw="am I on target?")
    env = await _intent_to_envelope(intent, "u1")
    assert env is not None
    assert env["title"] == "Rebalance Plan"


# ── 5. Unmapped intent falls back to None ───────────────────────


@pytest.mark.asyncio
async def test_unmapped_intent_returns_none(fake_db):
    intent = Intent(name="generic", raw="hello")
    env = await _intent_to_envelope(intent, "u1")
    assert env is None


# ── 6. Builder failure must not raise ───────────────────────────


@pytest.mark.asyncio
async def test_builder_failure_returns_none(monkeypatch, fake_db):
    """A DB failure inside the builder must not bubble up — chat must
    still return prose."""
    import services.copilot_tools.widget_builders as WB

    async def _boom(*_a, **_k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(WB, "build_stress_test_data", _boom, raising=True)
    intent = Intent(name="stress_test", raw="stress test", extras={"scenario": "covid_2020"})
    env = await _intent_to_envelope(intent, "u1")
    assert env is None
