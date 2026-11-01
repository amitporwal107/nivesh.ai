"""Quick Hedge service (services/quick_hedge/service.py) with the three reads replaced by fakes: the answer's shape, the
tolerance conversion, and that a missing input says what is missing instead of producing a hedge."""
import asyncio

import pytest

from services import desk_cost_card as card
from services.quick_hedge import service

SPOT = 23_000.0


def _puts():
    p = {float(k): round(120 * 4 ** (-((SPOT - k) / 50 - 23) / 46), 2) for k in range(19_000, 23_001, 50)}
    p[21_850.0], p[19_550.0] = 120.0, 30.0
    return p


def _pf(**kw):
    base = {"portfolio_value_rs": 2_500_000.0, "hedgeable_value_rs": 2_000_000.0, "beta": 1.0, "beta_coverage": 1.0,
            "excluded_rs": {"hybrid": 300_000.0, "debt": 0.0, "gold": 200_000.0, "other": 0.0, "unclassified": 0.0},
            "holdings": [{"key": "A", "value_rs": 1_200_000.0}, {"key": "B", "value_rs": 800_000.0}], "reasons": [], "as_of": "2026-10-30"}
    base.update(kw)
    return base


MARKET = {"ok": True, "as_of": "2026-10-30", "spot": SPOT, "lot": 65, "expiry": "2026-12-01", "days_to_expiry": 32, "tenor": "1m",
          "expiries": ["2026-11-03", "2026-12-01"], "puts": None, "source": "NSE F&O bhavcopy via the data platform (end of day)"}
FIT = {"r2": 0.83, "correlation": 0.91, "regression_beta": 1.02, "observations": 252, "coverage": 0.95, "series_used": 2,
       "window_start": "2025-10-31", "window_end": "2026-10-30", "reason": None}


class Fake:
    def __init__(self, pf=None, market=None, fit=None):
        self._pf, self._market, self._fit, self.fit_calls = pf or _pf(), market or {**MARKET, "puts": _puts()}, fit or FIT, 0

    async def portfolio(self, db, uid):
        return self._pf

    async def market(self, tenor):
        return self._market

    async def fit(self, pf):
        self.fit_calls += 1
        return self._fit


def _run(readers=None, **kw):
    args = dict(expected_fall_pct=15.0, tenor="1m", tolerance_rs=100_000.0)
    args.update(kw)
    return asyncio.run(service.run(None, "u1", readers=readers or Fake(), **args))


def test_a_complete_answer_has_modes_data_dates_and_what_was_left_out():
    res = _run()
    assert res["status"] == "ok" and [m["mode"] for m in res["modes"]] == ["maximum", "balanced", "lowest_cost"]
    bal = next(m for m in res["modes"] if m["mode"] == "balanced")
    assert bal["legs"][0]["strike"] == 21_850.0 and bal["place_allowed"] is True
    assert bal["cost"]["charges_included"] is True
    assert bal["cost"]["charges_rs"] == pytest.approx(card.order_side("options", "BUY", 7_800.0)["total"])
    d = res["data"]
    assert d["portfolio"]["excluded_rs"]["gold"] == 200_000.0 and d["portfolio"]["as_of"] == "2026-10-30"
    assert d["market"]["as_of"] == "2026-10-30" and d["market"]["expiry"] == "2026-12-01" and d["market"]["puts_traded"] == len(_puts())
    assert d["fit"]["r2"] == 0.83 and d["fit"]["window_end"] == "2026-10-30"
    assert res["tenor"] == "1m" and res["disclosures"]


def test_a_percentage_tolerance_is_a_share_of_the_hedgeable_value():
    res = _run(tolerance_rs=None, tolerance_pct=5.0)                        # 5% of 20,00,000 = 1,00,000
    assert res["inputs"]["tolerance_rs"] == pytest.approx(100_000.0)
    assert next(m for m in res["modes"] if m["mode"] == "balanced")["legs"][0]["strike"] == 21_850.0


def test_no_tolerance_is_incomplete_not_a_default():
    res = _run(tolerance_rs=None, tolerance_pct=None)
    assert res["status"] == "incomplete" and res["modes"] == [] and res["reasons"][0]["code"] == "bad_inputs"


def test_market_data_down_says_so_first_and_shows_no_hedge():
    down = {"ok": False, "reason": {"code": "market_data_unavailable", "message": "The data platform is unavailable."}}
    res = _run(Fake(market=down))
    assert res["status"] == "incomplete" and res["modes"] == []
    assert [r["code"] for r in res["reasons"]] == ["market_data_unavailable"]          # not also "missing spot": that is its consequence


def test_no_beta_stops_before_the_fit_is_even_measured():
    pf = _pf(beta=None, beta_coverage=0.5, reasons=[{"code": "beta_coverage_low", "message": "Beta is known for only 50%."}])
    fake = Fake(pf=pf)
    res = _run(fake)
    assert res["status"] == "incomplete" and res["reasons"][0]["code"] == "beta_coverage_low" and fake.fit_calls == 0


def test_an_unmeasurable_fit_shows_scenarios_but_blocks_placing_and_says_why():
    nofit = {**FIT, "r2": None, "correlation": None, "reason": {"code": "fit_coverage_low", "message": "Price history covers only 40%."}}
    res = _run(Fake(fit=nofit))
    assert res["status"] == "ok" and res["modes"]
    assert all(m["place_allowed"] is False for m in res["modes"] if m["available"])
    assert any(r["code"] == "fit_coverage_low" for r in res["reasons"])


def test_small_portfolio_gets_the_too_small_message_with_its_data_block():
    pf = _pf(portfolio_value_rs=1_100_000.0, hedgeable_value_rs=1_000_000.0)
    res = _run(Fake(pf=pf))
    assert res["status"] == "not_hedgeable" and res["reasons"][0]["code"] == "smaller_than_one_lot"
    assert res["data"]["portfolio"]["hedgeable_value_rs"] == 1_000_000.0
