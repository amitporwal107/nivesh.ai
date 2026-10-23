"""GET /api/fno/{symbol}/expiries | /chain | /futures — the app's read-only F&O routes (routes/fno.py).

No network and no Mongo: `daas_client.get_raw` is replaced by a recorder that answers with fixture bodies
(MOCK — not real data) in the shape the data platform sends (nidp/services/daas_api/routers/fno.py), so the
route's own work runs for real: symbol validation, the summary maths, shaping, the strike window and the
error mapping. Real figures come from running the routes against staging.

The worked example every summary test uses (one expiry, spot 108):

    strike   call OI   put OI
      100       10        40
      110       20        30
      120       50         5

    totals     calls 10 + 20 + 50 = 80        puts 40 + 30 + 5 = 75
    PCR        75 / 80 = 0.9375
    ATM        distance to 108: 100 → 8, 110 → 2, 120 → 12            → 110
    max pain   intrinsic value of every open option if the underlying settles at K
               K = 100   calls: none in the money                       0
                         puts:  110 → (110−100)×30 = 300
                                120 → (120−100)×5  = 100                400      total 400
               K = 110   calls: 100 → (110−100)×10 = 100                100
                         puts:  120 → (120−110)×5  = 50                  50      total 150
               K = 120   calls: 100 → (120−100)×10 = 200
                                110 → (120−110)×20 = 200                400
                         puts:  none in the money                         0      total 400
               smallest is 150, at K = 110                                       → 110
    heaviest   call OI 50 at 120, put OI 40 at 100
    walls      put wall = heaviest put OI at or below 108 → 100 (40); call wall = heaviest call OI at or above 108 → 120 (50)
    futures    settle 108.75 − spot 108 = +0.75 (premium); settle 107.50 − 108 = −0.50 (discount)

The model example (MODEL_CHAIN below; the pricing itself is tested by hand in tests/test_option_pricing.py).
Data day 12 Oct 2026, expiry 27 Oct 2026: 15 calendar days, T = 15/365 = 0.0410959, r = 5.75%.

    forward    the 27 Oct future settles at 110.00 → forward 110.00, basis "future"
               without that future, from the options (PARITY_CHAIN: the 110 call settles at 1.50, the put at 2.20):
                   F = K + (C − P) × e^(rT) = 110 + (1.50 − 2.20) × 1.0023658 = 110 − 0.70166 = 109.29834 → 109.30,
                   "put-call parity"
               with neither (NO_PAIR_CHAIN: no strike has both sides traded):
                   108 × e^(0.0575 × 15/365) = 108 × 1.0023658 = 108.2555 → 108.26, "carried spot"
    110 strike (ATM, and exactly at the forward), both sides settle at 1.7749:
               √T = 0.2027212     at σ = 20%: σ√T = 0.0405442, d1 = 0.0202721, d2 = −0.0202721
               N(d1) = 0.5080869  φ(d1) = 0.3988603            DF = e^(−0.0023630) = 0.9976398
               price = DF × 110 × (2×0.5080869 − 1) = 0.9976398 × 110 × 0.0161737 = 1.77491   → iv 20.00 for both
               delta   call  DF×N(d1) = 0.5069          put  −DF×N(−d1) = −0.4908
               gamma   DF×φ(d1)/(110×0.0405442) = 0.089222
               vega    DF×110×φ(d1)×√T/100 = 0.0887
               theta   (0.0575×1.77491 − DF×110×φ(d1)×0.20/(2×0.2027212))/365 = (0.10206 − 21.59176)/365 = −0.0589
    ATM iv     (20.00 + 20.00)/2 = 20.00
    straddle   call close 1.70 + put close 1.80 = 3.50 → 3.50/108 = 3.24% of the spot
    100 call   settles at 9.90, below its intrinsic value DF×(110 − 100) = 9.9764 → no implied volatility
    120 call   volume 0 and open interest 0 → skipped
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import fno as route
from services import option_pricing

SPOT = 108.0
DAY = "2026-10-12"
EXPIRY = "2026-10-27"


def _contract(strike: float, side: str, close: float, oi: Optional[int], d_oi: Optional[int], volume: Optional[int],
              spot: Optional[float] = SPOT) -> Dict[str, Any]:
    """One row as DaaS /v1/fno/{symbol}/chain sends it (row_to_dict of its SELECT)."""
    return {"strike_price": strike, "option_type": side, "close_price": close, "settle_price": round(close + 0.05, 2),
            "underlying_price": spot, "open_interest": oi, "change_in_oi": d_oi, "traded_volume": volume,
            "traded_value": 1000.0}


def _strike(k: float, call: Tuple[float, int, int, int], put: Tuple[float, int, int, int]) -> Dict[str, Any]:
    return {"strike": k, "CE": _contract(k, "CE", *call), "PE": _contract(k, "PE", *put)}


# (close, OI, change in OI, volume) per side: the worked example above.
CHAIN: Dict[str, Any] = {
    "symbol": "TESTCO", "as_of": DAY, "expiry": EXPIRY, "strike_count": 3,
    "strikes": [
        _strike(100.0, (9.5, 10, 1, 7), (0.8, 40, 4, 9)),
        _strike(110.0, (2.4, 20, -2, 30), (3.9, 30, 3, 25)),
        _strike(120.0, (0.3, 50, 5, 12), (12.6, 5, -1, 2)),
    ],
}
EXAMPLE = [(100.0, 10.0, 40.0), (110.0, 20.0, 30.0), (120.0, 50.0, 5.0)]

Reply = Union[Tuple[int, Any], Exception]

# What the chain route added to `summary` and to each side with the model estimates and the day change.
MODEL_SUMMARY_KEYS = {"days_to_expiry", "forward", "forward_basis", "rate_pct", "atm_iv", "expected_move", "expected_move_pct"}
MODEL_SIDE_KEYS = {"iv", "iv_price", "delta", "gamma", "theta", "vega", "change", "change_pct", "oi_buildup"}


def _only(d: Dict[str, Any], keys: Any) -> Dict[str, Any]:
    return {k: d[k] for k in keys}


def _chain_calls(calls: List[Tuple[str, Optional[dict]]]) -> List[Tuple[str, Optional[dict]]]:
    """The chain reads among the recorded calls. The route also reads the futures, for the forward."""
    return [c for c in calls if c[0].endswith("/chain")]


def _client(monkeypatch, replies: Union[Reply, Callable[[str, Optional[dict]], Reply]], *, signed_in: bool = True,
            configured: bool = True) -> Tuple[TestClient, List[Tuple[str, Optional[dict]]]]:
    calls: List[Tuple[str, Optional[dict]]] = []

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, params))
        reply = replies(path, params) if callable(replies) else replies
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)

    monkeypatch.setattr(route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(route.daas_client, "is_configured", lambda: configured)
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


# ── summary maths (pure functions) ───────────────────────────────────────────

def test_worked_example_pcr_atm_max_pain_and_heaviest_strikes():
    strikes = route.shape_strikes(CHAIN["strikes"])
    s = route.summarise_chain(strikes, SPOT, DAY, EXPIRY)
    assert (s["total_call_oi"], s["total_put_oi"]) == (80, 75)
    assert s["pcr"] == 0.9375
    assert s["atm_strike"] == 110
    assert s["max_pain"] == 110
    assert s["max_call_oi"] == {"strike": 120, "oi": 50}
    assert s["max_put_oi"] == {"strike": 100, "oi": 40}
    # change in OI: calls +1 −2 +5 = +4, puts +4 +3 −1 = +6
    assert (s["total_call_oi_change"], s["total_put_oi_change"]) == (4, 6)
    assert (s["as_of"], s["expiry"], s["spot"]) == (DAY, EXPIRY, SPOT)


def test_expiry_payout_matches_the_hand_worked_totals():
    assert [route.expiry_payout(EXAMPLE, k) for k in (100.0, 110.0, 120.0)] == [400.0, 150.0, 400.0]


def test_max_pain_tie_goes_to_the_strike_nearer_the_spot_then_the_lower():
    # Two strikes that cost the same: settle at 100 → the 120 put pays (120−100)×10 = 200;
    # settle at 120 → the 100 call pays (120−100)×10 = 200.
    tie = [(100.0, 10.0, 0.0), (120.0, 0.0, 10.0)]
    assert route.expiry_payout(tie, 100.0) == route.expiry_payout(tie, 120.0) == 200.0
    assert route.max_pain(tie, spot=118.0) == 120.0  # 120 is 2 away, 100 is 18 away
    assert route.max_pain(tie, spot=102.0) == 100.0
    assert route.max_pain(tie, spot=110.0) == 100.0  # equally near → the lower strike
    assert route.max_pain(tie) == 100.0              # no spot → the lower strike


def test_max_pain_and_heaviest_strike_are_none_without_open_interest():
    flat = [(100.0, 0.0, 0.0), (110.0, 0.0, 0.0)]
    assert route.max_pain(flat, 105.0) is None
    assert route.top_oi_strike([(100.0, 0.0), (110.0, 0.0)], 105.0) is None
    assert route.max_pain([], 105.0) is None


def test_heaviest_strike_tie_goes_nearer_the_spot():
    assert route.top_oi_strike([(100.0, 7.0), (110.0, 7.0), (120.0, 3.0)], spot=108.0) == {"strike": 110, "oi": 7}
    assert route.top_oi_strike([(100.0, 7.0), (110.0, 7.0)], spot=None) == {"strike": 100, "oi": 7}


def test_atm_strike_nearest_spot_tie_goes_lower_and_none_without_a_spot():
    assert route.atm_strike([100.0, 110.0, 120.0], 108.0) == 110.0
    assert route.atm_strike([100.0, 110.0, 120.0], 105.0) == 100.0  # 5 away from both → the lower
    assert route.atm_strike([100.0, 110.0, 120.0], 500.0) == 120.0
    assert route.atm_strike([100.0, 110.0], None) is None
    assert route.atm_strike([], 108.0) is None


def test_pcr_is_none_when_there_is_no_call_open_interest():
    assert route.put_call_ratio(0, 75) is None
    assert route.put_call_ratio(80, 0) == 0.0
    assert route.put_call_ratio(3, 1) == 0.3333


def test_futures_basis_is_settle_minus_spot():
    assert route.futures_basis(108.75, 108.0) == 0.75   # premium
    assert route.futures_basis(107.5, 108.0) == -0.5    # discount
    assert route.futures_basis(None, 108.0) is None
    assert route.futures_basis(108.75, None) is None
    assert route.futures_basis(0.0, 108.0) is None      # a zero settle is a missing price, not a −108 basis


def test_spot_is_the_first_positive_underlying_price():
    assert route.find_spot([{"underlying_price": None}, {"underlying_price": 0}, None, {"underlying_price": 108.0},
                            {"underlying_price": 999.0}]) == 108.0
    assert route.find_spot([{"underlying_price": None}, {}]) is None


# ── shaping ──────────────────────────────────────────────────────────────────

def test_strike_rows_carry_close_settle_oi_change_and_volume_per_side():
    rows = route.shape_strikes(CHAIN["strikes"])
    assert rows[0] == {
        "strike": 100,
        "call": {"close": 9.5, "settle": 9.55, "oi": 10, "change_in_oi": 1, "volume": 7},
        "put": {"close": 0.8, "settle": 0.85, "oi": 40, "change_in_oi": 4, "volume": 9},
    }
    assert [r["strike"] for r in rows] == [100, 110, 120]


def test_shaping_sorts_strikes_keeps_a_missing_side_as_null_and_drops_rows_it_cannot_place():
    raw = [
        {"strike": 120.0, "CE": _contract(120.0, "CE", 0.3, 50, 5, 12), "PE": None},
        {"strike": 712.5, "CE": None, "PE": _contract(712.5, "PE", 4.0, None, None, None)},
        {"strike": None, "CE": _contract(0, "CE", 1.0, 1, 1, 1), "PE": None},   # no strike
        {"strike": 130.0, "CE": None, "PE": None},                                # no contract on either side
        "junk",
    ]
    rows = route.shape_strikes(raw)
    assert [r["strike"] for r in rows] == [120, 712.5]
    assert rows[0]["put"] is None and rows[0]["call"]["oi"] == 50
    assert rows[1]["call"] is None
    assert rows[1]["put"] == {"close": 4.0, "settle": 4.05, "oi": None, "change_in_oi": None, "volume": None}
    assert route.shape_strikes(None) == [] and route.shape_strikes({}) == []


def test_window_keeps_n_strikes_each_side_of_the_centre():
    rows = [{"strike": k} for k in (90, 100, 110, 120, 130, 140, 150)]
    assert [r["strike"] for r in route.window_around(rows, 120, 1)] == [110, 120, 130]
    assert [r["strike"] for r in route.window_around(rows, 90, 2)] == [90, 100, 110]      # clipped at the low end
    assert [r["strike"] for r in route.window_around(rows, 150, 2)] == [130, 140, 150]    # and at the high end
    assert [r["strike"] for r in route.window_around(rows, None, 1)] == [110, 120, 130]   # no spot → the middle
    assert len(route.window_around(rows, 120, 40)) == 7
    assert route.window_around([], 120, 5) == []


def test_live_expiries_are_the_option_expiries_seen_on_the_latest_day_nearest_first():
    rows = [
        {"expiry_date": "2026-12-29", "ce_count": 900, "pe_count": 900, "futures_count": 60, "latest_seen": DAY},
        {"expiry_date": "2026-10-13", "ce_count": 400, "pe_count": 400, "futures_count": 0, "latest_seen": DAY},
        {"expiry_date": "2026-10-06", "ce_count": 500, "pe_count": 500, "futures_count": 0, "latest_seen": "2026-10-06"},  # expired
        {"expiry_date": "2027-03-30", "ce_count": 0, "pe_count": 0, "futures_count": 12, "latest_seen": DAY},              # futures only
        {"expiry_date": "2026-10-12", "ce_count": 300, "pe_count": 300, "futures_count": 0, "latest_seen": DAY},           # expires on the data's day
        {"expiry_date": "not-a-date", "ce_count": 1, "pe_count": 1, "futures_count": 0, "latest_seen": DAY},
    ]
    as_of, out = route.live_option_expiries(rows)
    assert as_of == DAY
    assert out == [
        {"expiry": "2026-10-12", "days_to_expiry": 0},
        {"expiry": "2026-10-13", "days_to_expiry": 1},
        {"expiry": "2026-12-29", "days_to_expiry": 78},
    ]
    assert route.live_option_expiries([]) == (None, [])
    assert route.live_option_expiries(None) == (None, [])


# ── GET /chain ───────────────────────────────────────────────────────────────

def test_chain_returns_the_summary_and_the_strike_rows(monkeypatch):
    c, calls = _client(monkeypatch, (200, CHAIN))
    r = c.get("/api/fno/testco/chain")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "TESTCO"
    expected_summary = {
        "as_of": DAY, "expiry": EXPIRY, "spot": 108.0, "atm_strike": 110,
        "total_call_oi": 80, "total_put_oi": 75, "total_call_oi_change": 4, "total_put_oi_change": 6,
        "pcr": 0.9375, "max_pain": 110,
        "max_call_oi": {"strike": 120, "oi": 50}, "max_put_oi": {"strike": 100, "oi": 40},
        "put_wall": {"strike": 100, "oi": 40}, "call_wall": {"strike": 120, "oi": 50},       # spot 108: put OI at or below it, call OI at or above it
    }
    # every field the route sent before the model estimates were added is still there, unchanged
    assert _only(body["summary"], expected_summary) == expected_summary
    assert set(body["summary"]) - set(expected_summary) == MODEL_SUMMARY_KEYS
    assert [s["strike"] for s in body["strikes"]] == [100, 110, 120]
    expected_call = {"close": 2.4, "settle": 2.45, "oi": 20, "change_in_oi": -2, "volume": 30}
    assert _only(body["strikes"][1]["call"], expected_call) == expected_call
    assert set(body["strikes"][1]["call"]) - set(expected_call) == MODEL_SIDE_KEYS
    assert (body["strike_count"], body["strikes_returned"]) == (3, 3)
    # the symbol is upper-cased, and no expiry is sent when none was asked for (the data platform picks the nearest)
    assert _chain_calls(calls) == [("/fno/TESTCO/chain", None)]


def test_chain_forwards_the_expiry_asked_for(monkeypatch):
    c, calls = _client(monkeypatch, (200, CHAIN))
    assert c.get("/api/fno/TESTCO/chain", params={"expiry": EXPIRY}).status_code == 200
    assert _chain_calls(calls) == [("/fno/TESTCO/chain", {"expiry": EXPIRY})]


def test_around_limits_the_rows_sent_but_the_summary_covers_the_whole_chain(monkeypatch):
    c, _ = _client(monkeypatch, (200, CHAIN))
    body = c.get("/api/fno/TESTCO/chain", params={"around": 1}).json()
    wide = c.get("/api/fno/TESTCO/chain").json()
    assert body["summary"] == wide["summary"]

    # A longer chain: 7 strikes 80…140, spot 108 → ATM 110; around=1 sends 100, 110, 120 only.
    long_chain = copy.deepcopy(CHAIN)
    long_chain["strikes"] = [_strike(float(k), (1.0, 10, 0, 1), (1.0, 20, 0, 1)) for k in range(80, 150, 10)]
    c2, _ = _client(monkeypatch, (200, long_chain))
    b2 = c2.get("/api/fno/TESTCO/chain", params={"around": 1}).json()
    assert [s["strike"] for s in b2["strikes"]] == [100, 110, 120]
    assert (b2["strike_count"], b2["strikes_returned"]) == (7, 3)
    assert (b2["summary"]["total_call_oi"], b2["summary"]["total_put_oi"]) == (70, 140)  # all 7 strikes, not 3
    assert b2["summary"]["pcr"] == 2.0


@pytest.mark.parametrize("around", ["0", "501", "x"])
def test_chain_rejects_an_out_of_range_window(monkeypatch, around):
    c, calls = _client(monkeypatch, (200, CHAIN))
    assert c.get("/api/fno/TESTCO/chain", params={"around": around}).status_code == 422
    assert calls == []


def test_chain_rejects_a_malformed_expiry_without_calling_the_data_platform(monkeypatch):
    c, calls = _client(monkeypatch, (200, CHAIN))
    assert c.get("/api/fno/TESTCO/chain", params={"expiry": "27-10-2026"}).status_code == 422
    assert calls == []


def test_chain_without_a_spot_still_answers_with_null_atm(monkeypatch):
    no_spot = copy.deepcopy(CHAIN)
    for s in no_spot["strikes"]:
        s["CE"]["underlying_price"] = None
        s["PE"]["underlying_price"] = None
    c, _ = _client(monkeypatch, (200, no_spot))
    body = c.get("/api/fno/TESTCO/chain").json()
    assert body["summary"]["spot"] is None and body["summary"]["atm_strike"] is None
    assert body["summary"]["max_pain"] == 110 and body["summary"]["pcr"] == 0.9375
    assert len(body["strikes"]) == 3


# ── 404: no F&O data ─────────────────────────────────────────────────────────

def test_data_platform_404_comes_back_as_404_with_a_plain_message(monkeypatch):
    c, _ = _client(monkeypatch, (404, {"detail": "no F&O data for ZZZNOPE"}))
    r = c.get("/api/fno/zzznope/chain")
    assert r.status_code == 404
    assert r.json() == {"detail": "No F&O data for ZZZNOPE"}


def test_the_data_platforms_own_error_envelope_is_understood(monkeypatch):
    """Staging's data platform wraps errors as {"error": {"status", "message", "request_id"}} (seen 2026-10-13)."""
    for message, expected in (
        ("no F&O data for ZZZNOPE", "No F&O data for ZZZNOPE"),
        ("no upcoming expiry for ZZZNOPE", "No option contracts are listed for ZZZNOPE"),
    ):
        c, _ = _client(monkeypatch, (404, {"error": {"status": 404, "message": message, "request_id": "r-1"}}))
        r = c.get("/api/fno/zzznope/chain")
        assert (r.status_code, r.json()) == (404, {"detail": expected}), message
    # an error envelope that says something else is still not passed off as "no data"
    c, _ = _client(monkeypatch, (404, {"error": {"status": 404, "message": "Not Found", "request_id": "r-2"}}))
    assert c.get("/api/fno/zzznope/chain").status_code == 502


def test_chain_sends_the_lot_size_when_the_data_platform_does(monkeypatch):
    with_lot = {**CHAIN, "strikes": [
        {**s, "CE": {**s["CE"], "new_board_lot_qty": 65}, "PE": {**s["PE"], "new_board_lot_qty": 65}} for s in CHAIN["strikes"]
    ]}
    c, _ = _client(monkeypatch, (200, with_lot))
    assert c.get("/api/fno/TESTCO/chain").json()["lot_size"] == 65
    # until the data platform sends the column there is no lot size, and none is guessed
    c, _ = _client(monkeypatch, (200, CHAIN))
    assert c.get("/api/fno/TESTCO/chain").json()["lot_size"] is None


def test_no_upcoming_expiry_is_404_saying_no_option_contracts(monkeypatch):
    c, _ = _client(monkeypatch, (404, {"detail": "no upcoming expiry for TESTCO"}))
    r = c.get("/api/fno/TESTCO/chain")
    assert (r.status_code, r.json()) == (404, {"detail": "No option contracts are listed for TESTCO"})


def test_an_expiry_with_no_contracts_is_404_not_an_empty_chain(monkeypatch):
    empty = {"symbol": "TESTCO", "as_of": DAY, "expiry": "2026-11-24", "strikes": [], "strike_count": 0}
    c, _ = _client(monkeypatch, (200, empty))
    r = c.get("/api/fno/TESTCO/chain", params={"expiry": "2026-11-24"})
    assert (r.status_code, r.json()) == (404, {"detail": "No option contracts for TESTCO expiring 2026-11-24"})


def test_expiries_and_futures_are_404_for_an_underlying_with_no_rows(monkeypatch):
    def replies(path, params):
        if path.endswith("/expiries"):
            return 200, {"symbol": "ZZZNOPE", "data": [], "count": 0}
        return 200, {"data": [], "count": 0, "pagination": {}, "symbol": "ZZZNOPE", "as_of": None}
    c, _ = _client(monkeypatch, replies)
    for path in ("/api/fno/ZZZNOPE/expiries", "/api/fno/ZZZNOPE/futures"):
        r = c.get(path)
        assert (r.status_code, r.json()) == (404, {"detail": "No F&O data for ZZZNOPE"}), path


# ── 502: the data platform did not answer ────────────────────────────────────

PATHS = ["/api/fno/TESTCO/chain", "/api/fno/TESTCO/expiries", "/api/fno/TESTCO/futures"]


@pytest.mark.parametrize("path", PATHS)
def test_unreachable_data_platform_is_502_upstream_unavailable(monkeypatch, path):
    c, _ = _client(monkeypatch, route.daas_client.DaasError("DAAS connectivity error"))
    r = c.get(path)
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


@pytest.mark.parametrize("path", PATHS)
def test_unconfigured_data_platform_is_502_and_is_not_called(monkeypatch, path):
    c, calls = _client(monkeypatch, (200, CHAIN), configured=False)
    r = c.get(path)
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})
    assert calls == []


@pytest.mark.parametrize("reply", [
    (500, {"detail": "boom"}),
    (503, None),
    (200, None),                        # 200 without a JSON object
    (200, ["not", "an", "object"]),
    (404, {"detail": "Not Found"}),     # the route itself is missing upstream: says nothing about the underlying
    (404, None),
])
def test_upstream_failures_are_502_never_an_empty_success(monkeypatch, reply):
    c, _ = _client(monkeypatch, reply)
    for path in PATHS:
        r = c.get(path)
        assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"}), (path, reply)


def test_chain_body_without_a_day_or_expiry_is_502(monkeypatch):
    c, _ = _client(monkeypatch, (200, {}))
    assert c.get("/api/fno/TESTCO/chain").status_code == 502
    stamped = {**copy.deepcopy(CHAIN), "as_of": "2026-10-12T18:30:00Z"}  # a timestamp is not a trading day
    c2, _ = _client(monkeypatch, (200, stamped))
    assert c2.get("/api/fno/TESTCO/chain").status_code == 502


# ── symbol validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol", ["NIFTY", "banknifty", "M&M", "BAJAJ-AUTO", "360ONE", "A" * 20])
def test_index_and_stock_symbols_are_accepted_and_upper_cased(monkeypatch, symbol):
    c, calls = _client(monkeypatch, (200, CHAIN))
    assert c.get(f"/api/fno/{symbol}/chain").status_code == 200
    assert _chain_calls(calls) == [(f"/fno/{symbol.upper()}/chain", None)]


@pytest.mark.parametrize("symbol", ["NIFTY$", "NIF TY", "NIFTY.NS", "A" * 21, "NIFTY;DROP", "नि", "..%2Fadmin"])
def test_bad_symbols_are_rejected_before_any_upstream_call(monkeypatch, symbol):
    c, calls = _client(monkeypatch, (200, CHAIN))
    for tail in ("chain", "expiries", "futures"):
        assert c.get(f"/api/fno/{symbol}/{tail}").status_code in (404, 422), (symbol, tail)
    assert calls == []


# ── authentication ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PATHS)
def test_unauthenticated_requests_are_401_and_reach_nothing(monkeypatch, path):
    c, calls = _client(monkeypatch, (200, CHAIN), signed_in=False)  # the real deps.get_current_user
    r = c.get(path)
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})
    assert calls == []


def test_the_router_is_read_only():
    methods = {m for r in route.router.routes for m in r.methods}
    assert methods == {"GET"}
    assert sorted(r.path for r in route.router.routes) == [
        "/api/fno/forward-test", "/api/fno/scan/buildup", "/api/fno/scan/candidates", "/api/fno/{symbol}/chain", "/api/fno/{symbol}/expiries", "/api/fno/{symbol}/futures",
        "/api/fno/{symbol}/positioning-history"]


# ── GET /expiries ────────────────────────────────────────────────────────────

def test_expiries_route_lists_live_option_expiries_nearest_first(monkeypatch):
    upstream = {"symbol": "NIFTY", "count": 3, "data": [
        {"expiry_date": "2026-10-27", "ce_count": 9000, "pe_count": 9000, "futures_count": 60, "latest_seen": DAY},
        {"expiry_date": "2026-10-13", "ce_count": 700, "pe_count": 700, "futures_count": 0, "latest_seen": DAY},
        {"expiry_date": "2026-09-29", "ce_count": 9000, "pe_count": 9000, "futures_count": 60, "latest_seen": "2026-09-29"},
    ]}
    c, calls = _client(monkeypatch, (200, upstream))
    r = c.get("/api/fno/nifty/expiries")
    assert r.status_code == 200
    assert r.json() == {"symbol": "NIFTY", "as_of": DAY, "count": 2, "expiries": [
        {"expiry": "2026-10-13", "days_to_expiry": 1}, {"expiry": "2026-10-27", "days_to_expiry": 15}]}
    assert calls == [("/fno/NIFTY/expiries", None)]


def test_expiries_route_with_futures_only_answers_an_empty_list_with_the_day(monkeypatch):
    upstream = {"symbol": "TESTCO", "count": 1, "data": [
        {"expiry_date": "2026-10-27", "ce_count": 0, "pe_count": 0, "futures_count": 60, "latest_seen": DAY}]}
    c, _ = _client(monkeypatch, (200, upstream))
    assert c.get("/api/fno/TESTCO/expiries").json() == {"symbol": "TESTCO", "as_of": DAY, "count": 0, "expiries": []}


# ── GET /futures ─────────────────────────────────────────────────────────────

def _future(kind: str, expiry: str, close: float, settle: Optional[float], oi: int, d_oi: int, volume: int,
            as_of: str = DAY) -> Dict[str, Any]:
    """One row as DaaS /v1/fno/{symbol} sends it."""
    return {"as_of_date": as_of, "ticker_symbol": "TESTCO", "instrument_type": kind, "expiry_date": expiry,
            "strike_price": None, "option_type": None, "open_price": close, "high_price": close, "low_price": close,
            "close_price": close, "settle_price": settle, "underlying_price": SPOT, "open_interest": oi,
            "change_in_oi": d_oi, "traded_volume": volume, "traded_value": 1.0, "num_trades": 3}


def _envelope(rows: List[Dict[str, Any]], as_of: Optional[str] = DAY) -> Dict[str, Any]:
    return {"data": rows, "count": len(rows), "pagination": {"limit": 50, "offset": 0, "total": None, "next_offset": None},
            "symbol": "TESTCO", "as_of": as_of}


NO_DAY = {"prev_close": None, "change": None, "change_pct": None, "oi_buildup": None}


def test_futures_carry_their_day_change_and_build_up_once_the_previous_close_is_sent(monkeypatch):
    """Index futures build-up (PRD §10.4): copied from the staging warehouse 2026-10-14 (nidp.fno_bhavcopy, IDF NIFTY
    near month): close 22,648.50 vs previous close 22,834.80 → −186.30 = −0.82 %; OI change +3,900 → short build-up."""
    rows = [{**_future("IDF", "2026-10-27", 22648.5, 22648.5, 18451355, 3900, 53505), "option_type": "FUT",
             "prev_close_price": 22834.8, "underlying_price": 22622.7},
            {**_future("IDF", "2026-11-24", 22756.0, 22756.0, 2574910, 117780, 5237), "option_type": "FUT",
             "prev_close_price": None, "underlying_price": 22622.7}]
    c, _ = _client(monkeypatch, lambda path, params: (200, _envelope(rows if params["instrument_type"] == "IDF" else [])))
    near, nxt = c.get("/api/fno/NIFTY/futures").json()["futures"]
    assert (near["prev_close"], near["change"], near["change_pct"], near["oi_buildup"]) == (22834.8, -186.3, -0.82, "short build-up")
    assert (nxt["prev_close"], nxt["change"], nxt["oi_buildup"]) == (None, None, None)


def test_futures_route_returns_each_contract_with_its_basis_nearest_first(monkeypatch):
    stock_rows = [
        _future("FUTSTK", "2026-11-24", 107.6, 107.5, 900, -30, 400),
        _future("FUTSTK", "2026-10-27", 108.7, 108.75, 5000, 120, 2500),
        _future("FUTSTK", "2026-12-29", 109.0, None, 10, 0, 0),
    ]

    def replies(path, params):
        return 200, _envelope(stock_rows if params["instrument_type"] == "FUTSTK" else [])
    c, calls = _client(monkeypatch, replies)
    r = c.get("/api/fno/testco/futures")
    assert r.status_code == 200
    assert r.json() == {"symbol": "TESTCO", "as_of": DAY, "spot": 108.0, "lot_size": None, "count": 3, "futures": [
        # 108.75 − 108 = +0.75; no previous close sent → no day change (null, never 0)
        {"expiry": "2026-10-27", "close": 108.7, "settle": 108.75, "oi": 5000, "change_in_oi": 120, "volume": 2500, "basis": 0.75, **NO_DAY},
        # 107.50 − 108 = −0.50
        {"expiry": "2026-11-24", "close": 107.6, "settle": 107.5, "oi": 900, "change_in_oi": -30, "volume": 400, "basis": -0.5, **NO_DAY},
        # no settle price → no basis, never close − spot in its place
        {"expiry": "2026-12-29", "close": 109.0, "settle": None, "oi": 10, "change_in_oi": 0, "volume": 0, "basis": None, **NO_DAY},
    ]}
    # every futures kind is asked for, in both of the exchange's naming vintages: the route cannot know index
    # from stock, or which vintage the day's rows use, without a read
    assert sorted(calls, key=lambda t: t[1]["instrument_type"]) == [
        ("/fno/TESTCO", {"instrument_type": "FUTIDX", "limit": 50}),
        ("/fno/TESTCO", {"instrument_type": "FUTSTK", "limit": 50}),
        ("/fno/TESTCO", {"instrument_type": "IDF", "limit": 50}),
        ("/fno/TESTCO", {"instrument_type": "STF", "limit": 50}),
    ]


def test_futures_in_the_exchanges_current_format_are_read(monkeypatch):
    """The shape staging really sends (seen 2026-10-13): stock futures are instrument_type "STF" with
    option_type "FUT", not "FUTSTK" with no option_type, and each row carries the contract's lot size."""
    rows = [
        {**_future("STF", "2026-10-27", 108.7, 108.75, 5000, 120, 2500), "option_type": "FUT", "new_board_lot_qty": 500},
        {**_future("STF", "2026-11-24", 107.6, 107.5, 900, -30, 400), "option_type": "FUT", "new_board_lot_qty": 500},
    ]
    c, _ = _client(monkeypatch, lambda path, params: (200, _envelope(rows if params["instrument_type"] == "STF" else [])))
    body = c.get("/api/fno/TESTCO/futures").json()
    assert [(f["expiry"], f["settle"], f["basis"]) for f in body["futures"]] == [("2026-10-27", 108.75, 0.75), ("2026-11-24", 107.5, -0.5)]
    assert body["count"] == 2 and body["spot"] == 108.0 and body["lot_size"] == 500


def test_futures_route_ignores_option_rows_and_rows_from_an_older_day(monkeypatch):
    rows = [
        _future("FUTIDX", "2026-10-27", 108.7, 108.75, 5000, 120, 2500),
        _future("FUTIDX", "2026-10-27", 100.0, 100.0, 1, 1, 1, as_of="2026-10-09"),
        {**_future("OPTIDX", "2026-10-27", 2.4, 2.4, 20, -2, 30), "option_type": "CE", "strike_price": 110.0},
    ]
    c, _ = _client(monkeypatch, lambda path, params: (200, _envelope(rows if params["instrument_type"] == "FUTIDX" else [])))
    body = c.get("/api/fno/TESTCO/futures").json()
    assert [(f["expiry"], f["settle"], f["basis"]) for f in body["futures"]] == [("2026-10-27", 108.75, 0.75)]


def test_futures_route_with_a_day_but_no_futures_answers_an_empty_list(monkeypatch):
    c, _ = _client(monkeypatch, (200, _envelope([])))
    assert c.get("/api/fno/TESTCO/futures").json() == {"symbol": "TESTCO", "as_of": DAY, "spot": None, "lot_size": None, "count": 0, "futures": []}


def test_futures_route_is_502_when_one_of_the_two_reads_fails(monkeypatch):
    def replies(path, params):
        if params["instrument_type"] == "FUTIDX":
            return route.daas_client.DaasError("timed out")
        return 200, _envelope([_future("FUTSTK", "2026-10-27", 108.7, 108.75, 5000, 120, 2500)])
    c, _ = _client(monkeypatch, replies)
    r = c.get("/api/fno/TESTCO/futures")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


# ── model estimates on the chain (Black-76; the example is worked in the module docstring) ───────────────────

def _priced(strike: float, side: str, close: float, settle: Optional[float], oi: Optional[int], volume: Optional[int]) -> Dict[str, Any]:
    return {**_contract(strike, side, close, oi, 0, volume), "settle_price": settle}


# (close, settle, OI, volume) per side.
MODEL_CHAIN: Dict[str, Any] = {
    "symbol": "TESTCO", "as_of": DAY, "expiry": EXPIRY, "strike_count": 3,
    "strikes": [
        {"strike": 100.0, "CE": _priced(100.0, "CE", 9.9, 9.9, 10, 7), "PE": _priced(100.0, "PE", 0.05, 0.05, 40, 9)},
        {"strike": 110.0, "CE": _priced(110.0, "CE", 1.7, 1.7749, 20, 30), "PE": _priced(110.0, "PE", 1.8, 1.7749, 30, 25)},
        {"strike": 120.0, "CE": _priced(120.0, "CE", 0.05, 0.05, 0, 0), "PE": _priced(120.0, "PE", 10.4, 10.4, 5, 2)},
    ],
}
NO_MODEL = {"iv": None, "iv_price": None, "delta": None, "gamma": None, "theta": None, "vega": None}


def _untraded_puts(chain: Dict[str, Any]) -> Dict[str, Any]:
    """The chain with no put traded that day (each still held: open interest stays). No strike then has a
    call and a put that both traded, so the options imply no forward."""
    out = copy.deepcopy(chain)
    for row in out["strikes"]:
        row["PE"]["traded_volume"] = 0
    return out


NO_PAIR_CHAIN = _untraded_puts(MODEL_CHAIN)
# The 110 strike priced off a forward that is not a strike: call settle 1.50, put settle 2.20 → F = 109.30.
PARITY_CHAIN = copy.deepcopy(MODEL_CHAIN)
PARITY_CHAIN["strikes"][1]["CE"]["settle_price"] = 1.5
PARITY_CHAIN["strikes"][1]["PE"]["settle_price"] = 2.2


def _with_futures(chain: Dict[str, Any], futures: Union[List[Dict[str, Any]], Exception]) -> Callable[[str, Optional[dict]], Reply]:
    """Answers the chain read with `chain` and the futures reads with `futures` (stock rows) or an error."""
    def replies(path: str, params: Optional[dict]) -> Reply:
        if path.endswith("/chain"):
            return 200, chain
        if isinstance(futures, Exception):
            return futures
        return 200, _envelope(futures if params["instrument_type"] == "STF" else [])
    return replies


def _stf(expiry: str, settle: Optional[float]) -> Dict[str, Any]:
    return {**_future("STF", expiry, 110.0, settle, 5000, 120, 2500), "option_type": "FUT", "strike_price": -1.0}


SAME_EXPIRY = [_stf(EXPIRY, 110.0), _stf("2026-11-24", 111.0)]


def _model(body: Dict[str, Any], strike: int, side: str) -> Dict[str, Any]:
    row = next(r for r in body["strikes"] if r["strike"] == strike)
    return _only(row[side], NO_MODEL)


def test_chain_prices_each_contract_on_the_future_that_expires_with_it(monkeypatch):
    c, calls = _client(monkeypatch, _with_futures(MODEL_CHAIN, SAME_EXPIRY))
    body = c.get("/api/fno/TESTCO/chain").json()
    s = body["summary"]
    # the future wins even though the options would imply a forward of their own
    assert (s["days_to_expiry"], s["forward"], s["forward_basis"], s["rate_pct"]) == (15, 110.0, "future", 5.75)
    # the ATM strike is the forward itself, and both sides settle at the price 20% gives
    # (gamma is sent to 8 places; a settle price quoted to 4 places pins it to about 6)
    gamma = pytest.approx(0.089222, abs=2e-6)
    assert _model(body, 110, "call") == {"iv": 20.0, "iv_price": "settle", "delta": 0.5069, "gamma": gamma, "theta": -0.0589, "vega": 0.0887}
    assert _model(body, 110, "put") == {"iv": 20.0, "iv_price": "settle", "delta": -0.4908, "gamma": gamma, "theta": -0.0589, "vega": 0.0887}
    assert s["atm_iv"] == 20.0
    # the straddle is the two closes (1.70 + 1.80), not the settle prices the volatility was read from
    assert (s["expected_move"], s["expected_move_pct"]) == (3.5, 3.24)
    # the futures are read alongside the chain, every kind in both naming vintages, as on /futures
    assert sorted(calls, key=lambda t: (t[0], (t[1] or {}).get("instrument_type", ""))) == [
        ("/fno/TESTCO", {"instrument_type": "FUTIDX", "limit": 50}),
        ("/fno/TESTCO", {"instrument_type": "FUTSTK", "limit": 50}),
        ("/fno/TESTCO", {"instrument_type": "IDF", "limit": 50}),
        ("/fno/TESTCO", {"instrument_type": "STF", "limit": 50}),
        ("/fno/TESTCO/chain", None),
    ]


def test_a_price_at_or_below_intrinsic_value_has_no_implied_volatility(monkeypatch):
    c, _ = _client(monkeypatch, _with_futures(MODEL_CHAIN, SAME_EXPIRY))
    body = c.get("/api/fno/TESTCO/chain").json()
    # the 100 call settles at 9.90; on a forward of 110 it cannot be worth less than 0.99764 × 10 = 9.9764
    assert _model(body, 100, "call") == NO_MODEL
    # the 100 put (0.05, ten points out of the money) does have one
    put = _model(body, 100, "put")
    assert put["iv"] is not None and 20.0 < put["iv"] < 60.0 and -0.05 < put["delta"] < 0.0


def test_a_contract_with_no_volume_and_no_open_interest_is_skipped(monkeypatch):
    c, _ = _client(monkeypatch, _with_futures(MODEL_CHAIN, SAME_EXPIRY))
    body = c.get("/api/fno/TESTCO/chain").json()
    assert _model(body, 120, "call") == NO_MODEL                    # volume 0 and open interest 0
    # with open interest but no trade that day it is priced, from the exchange's settle price
    held = copy.deepcopy(MODEL_CHAIN)
    held["strikes"][2]["CE"].update(open_interest=15, traded_volume=0)
    c2, _ = _client(monkeypatch, _with_futures(held, SAME_EXPIRY))
    priced = _model(c2.get("/api/fno/TESTCO/chain").json(), 120, "call")
    assert priced["iv"] is not None and priced["iv_price"] == "settle"
    # and a contract whose volume and open interest are not sent at all is not assumed to be live
    unknown = copy.deepcopy(MODEL_CHAIN)
    unknown["strikes"][1]["CE"].update(open_interest=None, traded_volume=None)
    c3, _ = _client(monkeypatch, _with_futures(unknown, SAME_EXPIRY))
    b3 = c3.get("/api/fno/TESTCO/chain").json()
    assert _model(b3, 110, "call") == NO_MODEL
    assert b3["summary"]["atm_iv"] == 20.0                           # the put alone


def test_implied_volatility_falls_back_to_the_close_when_there_is_no_settle_price(monkeypatch):
    no_settle = copy.deepcopy(MODEL_CHAIN)
    no_settle["strikes"][1]["CE"].update(settle_price=None, close_price=1.7749)
    no_settle["strikes"][1]["PE"].update(settle_price=0.0, close_price=1.7749)   # a zero settle is a missing price
    c, _ = _client(monkeypatch, _with_futures(no_settle, SAME_EXPIRY))
    body = c.get("/api/fno/TESTCO/chain").json()
    assert _only(_model(body, 110, "call"), ("iv", "iv_price")) == {"iv": 20.0, "iv_price": "close"}
    assert _only(_model(body, 110, "put"), ("iv", "iv_price")) == {"iv": 20.0, "iv_price": "close"}
    assert body["summary"]["expected_move"] == 3.55                  # 1.7749 + 1.7749, rounded to paise


def test_without_a_same_expiry_future_the_forward_is_the_one_the_options_imply(monkeypatch):
    other_month = [_stf("2026-11-24", 111.0)]
    c, _ = _client(monkeypatch, _with_futures(PARITY_CHAIN, other_month))
    body = c.get("/api/fno/TESTCO/chain").json()
    s = body["summary"]
    # the 110 strike is where the call (1.50) and the put (2.20) are closest: 110 + (1.50 − 2.20) × 1.0023658 = 109.2983
    assert (s["forward"], s["forward_basis"], s["rate_pct"]) == (109.3, "put-call parity", 5.75)
    # on the forward they imply, the call and the put at that strike imply one volatility
    # (0.02 apart at most: the forward is sent, and used, to 2 decimals)
    call, put = _model(body, 110, "call"), _model(body, 110, "put")
    assert call["iv"] == pytest.approx(put["iv"], abs=0.02) and 19.0 < call["iv"] < 23.0
    assert s["atm_iv"] == pytest.approx(call["iv"], abs=0.02)
    # a future with no settle price, or one from an older day, is not a forward: the options' own is used
    for rows in ([_stf(EXPIRY, None)], [{**_stf(EXPIRY, 110.0), "as_of_date": "2026-10-09"}], []):
        c2, _ = _client(monkeypatch, _with_futures(PARITY_CHAIN, rows))
        assert c2.get("/api/fno/TESTCO/chain").json()["summary"]["forward_basis"] == "put-call parity"


def test_the_parity_forward_is_read_only_from_a_strike_whose_call_and_put_both_traded(monkeypatch):
    # The 110 put is held (open interest 30) but did not trade: its settle price is the exchange's own
    # theoretical figure, so that strike is passed over. The 100 strike traded on both sides:
    # 100 + (9.90 − 0.05) × 1.0023658 = 109.8733
    held_put = copy.deepcopy(PARITY_CHAIN)
    held_put["strikes"][1]["PE"]["traded_volume"] = 0
    c, _ = _client(monkeypatch, _with_futures(held_put, []))
    s = c.get("/api/fno/TESTCO/chain").json()["summary"]
    assert (s["forward"], s["forward_basis"]) == (109.87, "put-call parity")
    assert route.parity_pairs(route.shape_strikes(held_put["strikes"])) == [(100.0, 9.9, 0.05)]
    assert route.parity_pairs(route.shape_strikes(PARITY_CHAIN["strikes"])) == [(100.0, 9.9, 0.05), (110.0, 1.5, 2.2)]
    assert route.parity_pairs(route.shape_strikes(NO_PAIR_CHAIN["strikes"])) == []
    # a strike with one side missing, or a side with no price, is no pair
    assert route.parity_pairs([{"strike": 100, "call": {"settle": 5.0, "close": 5.0, "volume": 9, "oi": 1}, "put": None},
                               {"strike": 110, "call": {"settle": None, "close": 0.0, "volume": 9, "oi": 1},
                                "put": {"settle": 3.0, "close": 3.0, "volume": 9, "oi": 1}}]) == []


def test_with_no_future_and_no_traded_pair_the_spot_is_carried_at_the_rate(monkeypatch):
    c, _ = _client(monkeypatch, _with_futures(NO_PAIR_CHAIN, [_stf("2026-11-24", 111.0)]))
    body = c.get("/api/fno/TESTCO/chain").json()
    s = body["summary"]
    # 108 × e^(0.0575 × 15/365) = 108.2555
    assert (s["forward"], s["forward_basis"], s["rate_pct"]) == (108.26, "carried spot", 5.75)
    # the same two prices on a forward 1.74 lower than the one they were struck on: the call now needs more
    # volatility than the put (the put is still priced: it is held, from its settle price)
    call, put = _model(body, 110, "call"), _model(body, 110, "put")
    assert call["iv"] > 20.0 > put["iv"] and put["iv_price"] == "settle"
    assert s["atm_iv"] == round((call["iv"] + put["iv"]) / 2, 2)


def test_no_forward_without_a_future_a_traded_pair_and_a_spot(monkeypatch):
    no_spot = copy.deepcopy(NO_PAIR_CHAIN)
    for row in no_spot["strikes"]:
        row["CE"]["underlying_price"] = row["PE"]["underlying_price"] = None
    c, _ = _client(monkeypatch, _with_futures(no_spot, []))
    body = c.get("/api/fno/TESTCO/chain").json()
    s = body["summary"]
    assert (s["forward"], s["forward_basis"], s["atm_iv"], s["expected_move"], s["expected_move_pct"]) == (None, None, None, None, None)
    assert (s["days_to_expiry"], s["rate_pct"]) == (15, 5.75)
    assert all(_model(body, k, side) == NO_MODEL for k in (100, 110, 120) for side in ("call", "put"))
    # with the future but no spot, contracts are priced; there is no ATM strike to name an ATM figure for
    c2, _ = _client(monkeypatch, _with_futures(no_spot, SAME_EXPIRY))
    b2 = c2.get("/api/fno/TESTCO/chain").json()
    assert (b2["summary"]["forward"], b2["summary"]["forward_basis"]) == (110.0, "future")
    assert _model(b2, 110, "call")["iv"] == 20.0
    assert (b2["summary"]["atm_strike"], b2["summary"]["atm_iv"], b2["summary"]["expected_move"]) == (None, None, None)
    # the options' own forward needs no spot either
    traded_no_spot = copy.deepcopy(PARITY_CHAIN)
    for row in traded_no_spot["strikes"]:
        row["CE"]["underlying_price"] = row["PE"]["underlying_price"] = None
    c3, _ = _client(monkeypatch, _with_futures(traded_no_spot, []))
    assert _only(c3.get("/api/fno/TESTCO/chain").json()["summary"], ("forward", "forward_basis")) == {"forward": 109.3, "forward_basis": "put-call parity"}


def test_no_model_estimates_on_the_expiry_day(monkeypatch):
    expiring = {**copy.deepcopy(MODEL_CHAIN), "expiry": DAY}
    c, _ = _client(monkeypatch, _with_futures(expiring, [_stf(DAY, 110.0)]))
    body = c.get("/api/fno/TESTCO/chain").json()
    s = body["summary"]
    assert s["days_to_expiry"] == 0
    assert (s["forward"], s["forward_basis"], s["atm_iv"], s["expected_move"], s["expected_move_pct"]) == (None, None, None, None, None)
    assert all(_model(body, k, side) == NO_MODEL for k in (100, 110, 120) for side in ("call", "put"))
    # the exchange's figures are still sent
    assert body["strikes"][1]["call"]["close"] == 1.7 and s["pcr"] == 2.5       # put OI 75 ÷ call OI 30


def test_a_failed_futures_read_leaves_the_model_out_but_still_answers_the_chain(monkeypatch):
    c, _ = _client(monkeypatch, _with_futures(MODEL_CHAIN, route.daas_client.DaasError("timed out")))
    r = c.get("/api/fno/TESTCO/chain")
    assert r.status_code == 200
    body = r.json()
    s = body["summary"]
    # not "carried spot": the route cannot tell whether a future expires with the options
    assert (s["forward"], s["forward_basis"], s["atm_iv"]) == (None, None, None)
    assert all(_model(body, k, side) == NO_MODEL for k in (100, 110, 120) for side in ("call", "put"))
    # everything that does not need a forward is unchanged
    assert (s["days_to_expiry"], s["expected_move"], s["pcr"], s["max_pain"]) == (15, 3.5, 2.5, 110)   # put OI 75 ÷ call OI 30
    assert body["strikes"][1]["put"]["close"] == 1.8


def test_only_the_strikes_sent_are_priced_and_the_atm_figures_do_not_depend_on_the_window(monkeypatch):
    c, _ = _client(monkeypatch, _with_futures(MODEL_CHAIN, SAME_EXPIRY))
    narrow = c.get("/api/fno/TESTCO/chain", params={"around": 1}).json()
    wide = c.get("/api/fno/TESTCO/chain").json()
    assert narrow["summary"] == wide["summary"]


def test_atm_iv_is_the_mean_of_the_two_sides_or_the_one_that_exists():
    assert route.atm_iv({"call": {"iv": 15.91}, "put": {"iv": 10.81}}) == 13.36
    assert route.atm_iv({"call": {"iv": 15.91}, "put": {"iv": None}}) == 15.91
    assert route.atm_iv({"call": None, "put": {"iv": 10.81}}) == 10.81
    assert route.atm_iv({"call": {"iv": None}, "put": None}) is None
    assert route.atm_iv(None) is None


def test_straddle_needs_both_closes():
    assert route.straddle({"call": {"close": 207.2}, "put": {"close": 105.05}}) == 312.25
    assert route.straddle({"call": {"close": 207.2}, "put": {"close": 0.0}}) is None
    assert route.straddle({"call": {"close": 207.2}, "put": None}) is None
    assert route.expected_move({"call": {"close": 207.2}, "put": {"close": 105.05}}, 22721.95, 6) == (312.25, 1.37)   # 312.25/22721.95
    assert route.expected_move({"call": {"close": 207.2}, "put": {"close": 105.05}}, None, 6) == (312.25, None)
    assert route.expected_move({"call": {"close": 207.2}, "put": {"close": 105.05}}, 22721.95, 0) == (None, None)


# ── day change and open-interest build-up ────────────────────────────────────

def test_day_change_is_close_minus_previous_close_with_a_build_up_label():
    side = lambda close, d_oi: {"close": close, "change_in_oi": d_oi}  # noqa: E731
    # 2.40 − 2.00 = +0.40 = +20%; open interest up → long build-up
    assert route.day_change({"prev_close_price": 2.0}, side(2.4, 5)) == {"change": 0.4, "change_pct": 20.0, "oi_buildup": "long build-up"}
    assert route.day_change({"prev_close_price": 2.0}, side(2.4, -5))["oi_buildup"] == "short covering"
    # 1.50 − 2.00 = −0.50 = −25%
    assert route.day_change({"prev_close_price": 2.0}, side(1.5, 5)) == {"change": -0.5, "change_pct": -25.0, "oi_buildup": "short build-up"}
    assert route.day_change({"prev_close_price": 2.0}, side(1.5, -5))["oi_buildup"] == "long unwinding"
    # a flat price or flat open interest is not a build-up
    assert route.day_change({"prev_close_price": 2.0}, side(2.0, 5)) == {"change": 0.0, "change_pct": 0.0, "oi_buildup": None}
    assert route.day_change({"prev_close_price": 2.0}, side(2.4, 0))["oi_buildup"] is None
    assert route.day_change({"prev_close_price": 2.0}, side(2.4, None))["oi_buildup"] is None
    # no previous close (the data platform does not send it yet), or no close: nothing is worked out
    nothing = {"change": None, "change_pct": None, "oi_buildup": None}
    assert route.day_change({}, side(2.4, 5)) == nothing
    assert route.day_change({"prev_close_price": 0.0}, side(2.4, 5)) == nothing
    assert route.day_change({"prev_close_price": 2.0}, side(None, 5)) == nothing
    assert route.day_change(None, side(2.4, 5)) == nothing


def test_chain_sends_the_day_change_when_the_data_platform_sends_the_previous_close(monkeypatch):
    with_prev = copy.deepcopy(CHAIN)
    with_prev["strikes"][1]["CE"]["prev_close_price"] = 2.0     # close 2.40, change in OI −2
    with_prev["strikes"][1]["PE"]["prev_close_price"] = 4.0     # close 3.90, change in OI +3
    c, _ = _client(monkeypatch, (200, with_prev))
    row = c.get("/api/fno/TESTCO/chain").json()["strikes"][1]
    assert _only(row["call"], ("change", "change_pct", "oi_buildup")) == {"change": 0.4, "change_pct": 20.0, "oi_buildup": "short covering"}
    # 3.90 − 4.00 = −0.10 = −2.5%; open interest up → short build-up
    assert _only(row["put"], ("change", "change_pct", "oi_buildup")) == {"change": -0.1, "change_pct": -2.5, "oi_buildup": "short build-up"}
    # until the data platform is redeployed the column is absent, and the three fields are null
    c2, _ = _client(monkeypatch, (200, CHAIN))
    plain = c2.get("/api/fno/TESTCO/chain").json()["strikes"][1]["call"]
    assert _only(plain, ("change", "change_pct", "oi_buildup")) == {"change": None, "change_pct": None, "oi_buildup": None}


# ── the frontend's fixtures carry this model's figures ───────────────────────

FRONTEND_FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"


@pytest.mark.parametrize("name", ["copilot-options-chain.json", "copilot-options-chain-parity.json", "copilot-options-chain-carried.json"])
def test_the_options_lab_fixtures_are_what_this_model_gives(name):
    """frontend-v5/e2e/tests/copilot-app-options.spec.ts asserts on figures in these synthetic chains
    (MOCK — not market data). Every contract is re-priced here from its own prices and the chain's forward,
    so a change to the model cannot leave the screen tests agreeing with stale numbers."""
    path = FRONTEND_FIXTURES / name
    if not path.exists():
        pytest.skip("the frontend fixtures are not part of this checkout")
    body = json.loads(path.read_text(encoding="utf-8"))
    s = body["summary"]
    t = option_pricing.year_fraction(s["days_to_expiry"])
    bare = [
        {"strike": r["strike"], **{name_: None if r[name_] is None else {k: v for k, v in r[name_].items() if k not in NO_MODEL}
                                   for name_ in ("call", "put")}}
        for r in body["strikes"]
    ]
    assert route.add_model(bare, s["forward"], t) == body["strikes"]
    atm_row = next(r for r in body["strikes"] if r["strike"] == s["atm_strike"])
    assert route.atm_iv(atm_row) == s["atm_iv"]
    assert route.expected_move(atm_row, s["spot"], s["days_to_expiry"]) == (s["expected_move"], s["expected_move_pct"])
    assert sum(1 for r in body["strikes"] for side in ("call", "put") if r[side]["iv"] is not None) >= 6
    assert s["rate_pct"] == round(option_pricing.RISK_FREE_RATE * 100, 4)
    # the forward itself: what the three-step rule gives for a chain with these strikes (the fixtures hold every
    # strike of their made-up expiry). A fixture priced on a future says so and is taken at its word.
    if s["forward_basis"] != "future":
        chosen = option_pricing.choose_forward(None, s["spot"], t, pairs=route.parity_pairs(body["strikes"]))
        assert (round(chosen[0], 2), chosen[1]) == (s["forward"], s["forward_basis"])


# ── real figures: the NIFTY weekly chain of 13 Oct 2026 ──────────────────────

def _real(strike: float, call: Tuple[float, int, int], put: Tuple[float, int, int]) -> Dict[str, Any]:
    """One strike as the data platform sends it. (close = settle, open interest, volume) per side."""
    side = lambda kind, px, oi, vol: {  # noqa: E731
        "strike_price": strike, "option_type": kind, "close_price": px, "settle_price": px, "underlying_price": 22721.95,
        "open_interest": oi, "change_in_oi": 0, "traded_volume": vol, "traded_value": 1.0, "new_board_lot_qty": 65}
    return {"strike": strike, "CE": side("CE", *call), "PE": side("PE", *put)}


# Public end-of-day market data, NOT a mock: the seven strikes around the money of the NIFTY 19 Oct 2026 expiry
# in the NSE F&O bhavcopy of 13 Oct 2026, as staging's GET /api/fno/NIFTY/chain?expiry=2026-10-19 served them
# (close, open interest, volume; settle equals close on all fourteen contracts). Spot 22,721.95. No NIFTY
# future expires on 19 Oct; the futures that day settle at 22,834.80 (27 Oct), 22,937.50 (23 Nov), 23,074.50 (29 Dec).
NIFTY_WEEKLY: Dict[str, Any] = {
    "symbol": "NIFTY", "as_of": "2026-10-13", "expiry": "2026-10-19", "strike_count": 7,
    "strikes": [
        _real(22550.0, (320.65, 550680, 202722), (63.65, 1897610, 232134)),
        _real(22600.0, (280.9, 2798315, 494449), (75.25, 4665440, 453726)),
        _real(22650.0, (243.15, 810420, 174676), (89.1, 1224925, 118534)),
        _real(22700.0, (207.2, 3922620, 496918), (105.05, 4154865, 248760)),
        _real(22750.0, (178.25, 959400, 180229), (121.95, 1313130, 63217)),
        _real(22800.0, (150.8, 3710070, 420590), (142.0, 2173470, 113098)),
        _real(22850.0, (126.45, 918515, 175669), (163.8, 547820, 18437)),
    ],
}
NIFTY_FUTURES = [
    {**_future("IDF", expiry, settle, settle, 1, 0, 1, as_of="2026-10-13"), "option_type": "FUT", "strike_price": -1.0, "underlying_price": 22721.95}
    for expiry, settle in (("2026-10-27", 22834.8), ("2026-11-23", 22937.5), ("2026-12-29", 23074.5))
]


def test_real_nifty_weekly_chain_is_priced_on_the_forward_its_own_options_imply(monkeypatch):
    """The case that made the parity rule necessary. Each of these seven strikes puts the forward
    (K + (C − P)·e^(rT)) between 22,802 and 22,813; the spot carried at the rate gives 22,743.44, 60 points
    lower, which read the 22,700 call at 15.91% and the put at 10.81%.

    Tolerances, and why:
      forward within 10 points of 22,805   the strikes themselves disagree by ±5.5 points (tick size, and closes
                                           not struck at one instant); 10 points of forward is under half a
                                           volatility point at the money (delta 0.5 × 10 ÷ vega 11.5 a point)
      call/put IV gap ≤ 1.0 point at each  that ±5.5-point disagreement is about 0.25 of a point on each side,
      strike, median ≤ 0.5                 0.5 on the gap; 1.0 leaves room for one more tick. Measured: largest
                                           0.59, median 0.29. The carried spot gave 5.09 at the money."""
    def replies(path: str, params: Optional[dict]) -> Reply:
        if path.endswith("/chain"):
            return 200, NIFTY_WEEKLY
        rows = NIFTY_FUTURES if params["instrument_type"] == "IDF" else []
        return 200, {"data": rows, "count": len(rows), "pagination": {}, "symbol": "NIFTY", "as_of": "2026-10-13"}
    c, _ = _client(monkeypatch, replies)
    body = c.get("/api/fno/NIFTY/chain", params={"expiry": "2026-10-19"}).json()
    s = body["summary"]
    assert (s["days_to_expiry"], s["atm_strike"], s["forward_basis"]) == (6, 22700, "put-call parity")
    # read at 22,800, where the call (150.80) and the put (142.00) are closest:
    # 22,800 + 8.80 × e^(0.0575 × 6/365) = 22,800 + 8.80 × 1.0009457 = 22,808.81
    assert s["forward"] == 22808.81
    assert abs(s["forward"] - 22805.0) <= 10.0
    gaps = sorted(abs(r["call"]["iv"] - r["put"]["iv"]) for r in body["strikes"])
    assert len(gaps) == 7 and gaps[-1] <= 1.0 and gaps[3] <= 0.5, gaps
    atm = next(r for r in body["strikes"] if r["strike"] == 22700)
    assert (atm["call"]["iv"], atm["put"]["iv"], s["atm_iv"]) == (12.6, 13.19, 12.89)   # 12.895 → 12.89 (round-half-even)
    assert all(r[side]["iv_price"] == "settle" for r in body["strikes"] for side in ("call", "put"))
    # the same rows on the carried spot, for the record: this is the split the parity rule removes
    carried = option_pricing.choose_forward(None, 22721.95, 6 / 365)
    assert (round(carried[0], 2), carried[1]) == (22743.44, "carried spot")
    split = route.add_model(route.shape_strikes(NIFTY_WEEKLY["strikes"]), round(carried[0], 2), 6 / 365)[3]
    assert (split["call"]["iv"], split["put"]["iv"]) == (15.91, 10.81)


@pytest.mark.parametrize("close,d_oi", [(110.0, 50), (90.0, 50), (110.0, -50), (90.0, -50)])
def test_futures_build_up_label_is_the_scan_rule(close, d_oi):
    """PRD 17.2 #8: the futures route reads price change x OI change with the same rule as the build-up scan
    (nidp desk_market.buildup_label: close vs prev_close_price, sign of change_in_oi). MOCK - not real data."""
    from nidp.services.daas_api.routers.desk_market import buildup_label
    fut = route.shape_futures([{**_future("IDF", "2026-10-27", close, close, 1000, d_oi, 10), "option_type": "FUT", "prev_close_price": 100.0}], None)[0]
    assert fut["oi_buildup"].replace("-", "").replace(" ", "_") == buildup_label(close - 100.0, d_oi)
    assert fut["change"] == round(close - 100.0, 2) and fut["change_pct"] == round(close - 100.0, 2)


def test_futures_without_a_previous_close_keep_the_change_null_never_zero():
    fut = route.shape_futures([{**_future("IDF", "2026-10-27", 100.0, 100.0, 1000, 5, 10), "option_type": "FUT"}], None)[0]
    assert (fut["prev_close"], fut["change"], fut["change_pct"], fut["oi_buildup"]) == (None, None, None, None)


# ── Greeks validated against an independent Black-76 (PRD 17.2 #4) ───────────

def _b76_price(call: bool, f: float, k: float, t: float, sigma: float, r: float) -> float:
    """Black-76 price written out here from statistics.NormalDist, sharing no code with services/option_pricing."""
    from statistics import NormalDist
    n = NormalDist()
    d1 = (math.log(f / k) + 0.5 * sigma * sigma * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    df = math.exp(-r * t)
    return df * (f * n.cdf(d1) - k * n.cdf(d2)) if call else df * (k * n.cdf(-d2) - f * n.cdf(-d1))


def _b76_closed_form(call: bool, f: float, k: float, t: float, sigma: float, r: float) -> Dict[str, float]:
    from statistics import NormalDist
    n = NormalDist()
    d1 = (math.log(f / k) + 0.5 * sigma * sigma * t) / (sigma * math.sqrt(t))
    df, pdf = math.exp(-r * t), n.pdf(d1)
    value = _b76_price(call, f, k, t, sigma, r)
    return {
        "delta": df * n.cdf(d1) if call else -df * n.cdf(-d1),
        "gamma": df * pdf / (f * sigma * math.sqrt(t)),
        "vega": df * f * pdf * math.sqrt(t) / 100.0,                                     # per volatility point
        "theta": (r * value - df * f * pdf * sigma / (2 * math.sqrt(t))) / 365.0,        # per calendar day
    }


def test_chain_greeks_match_an_independent_black_76(monkeypatch):
    """Every priced contract of the fixture chain: forward 110 (the future), 15 days, rate 5.75 %. The route's
    delta (per 1 point of the forward), gamma, theta (per CALENDAR day) and vega (per 1 VOLATILITY POINT) are
    compared with (a) closed-form Black-76 at the route's own implied volatility and (b) central finite
    differences of an independently written price. MOCK - not real data (the fixture is synthetic)."""
    c, _ = _client(monkeypatch, _with_futures(MODEL_CHAIN, SAME_EXPIRY))
    body = c.get("/api/fno/TESTCO/chain").json()
    f, t, r = body["summary"]["forward"], 15 / 365, body["summary"]["rate_pct"] / 100
    checked = 0
    for row in body["strikes"]:
        for name, call in (("call", True), ("put", False)):
            side = row[name]
            if not side or side["iv"] is None:
                continue
            k, sigma = float(row["strike"]), side["iv"] / 100
            want = _b76_closed_form(call, f, k, t, sigma, r)
            assert side["delta"] == pytest.approx(want["delta"], abs=2e-4)
            assert side["gamma"] == pytest.approx(want["gamma"], rel=2e-3, abs=2e-6)
            assert side["theta"] == pytest.approx(want["theta"], abs=2e-4)
            assert side["vega"] == pytest.approx(want["vega"], abs=2e-4)
            h, dv, dt = 0.01, 0.0001, 1 / 365
            fd_delta = (_b76_price(call, f + h, k, t, sigma, r) - _b76_price(call, f - h, k, t, sigma, r)) / (2 * h)
            fd_gamma = (_b76_price(call, f + h, k, t, sigma, r) - 2 * _b76_price(call, f, k, t, sigma, r) + _b76_price(call, f - h, k, t, sigma, r)) / h ** 2
            fd_vega = (_b76_price(call, f, k, t, sigma + dv, r) - _b76_price(call, f, k, t, sigma - dv, r)) / (2 * dv) / 100
            fd_theta = (_b76_price(call, f, k, t - dt, sigma, r) - _b76_price(call, f, k, t + dt, sigma, r)) / (2 * dt) / 365
            assert side["delta"] == pytest.approx(fd_delta, abs=2e-4)
            assert side["gamma"] == pytest.approx(fd_gamma, rel=3e-3, abs=2e-6)
            assert side["vega"] == pytest.approx(fd_vega, abs=2e-4)
            assert side["theta"] == pytest.approx(fd_theta, abs=2e-4)
            checked += 1
    assert checked >= 4


# ── put wall and call wall: OTM-only heaviest strikes (test_reports/fix_oi_range_otm_walls_TESTCASES.md) ──────────

def _strikes(rows):
    return [{"strike": k, "call": {"oi": c, "change_in_oi": 0}, "put": {"oi": p, "change_in_oi": 0}} for k, c, p in rows]


def test_walls_are_the_heaviest_put_at_or_below_spot_and_the_heaviest_call_at_or_above():
    s = route.summarise_chain(_strikes([(90, 5, 100), (100, 50, 60), (110, 80, 10), (120, 300, 5)]), 100.0, "2026-10-23", "2026-10-27")
    assert s["put_wall"]["strike"] == 90 and s["put_wall"]["oi"] == 100          # 90 holds the most put OI at or below 100
    assert s["call_wall"] == {"strike": 120, "oi": 300}
    assert s["max_put_oi"]["strike"] == 90 and s["max_call_oi"]["strike"] == 120


def test_a_deep_in_the_money_put_peak_is_not_the_wall():
    # GODFRYPHLP, 23 Oct 2026 (shape): spot 1669, put OI peaks at the in-the-money 1900, call OI at 2100.
    rows = [(1600, 10, 31350), (1650, 15, 12000), (1700, 20, 32725), (1800, 45100, 31075), (1900, 66275, 36575), (2000, 67100, 500), (2100, 76450, 100)]
    s = route.summarise_chain(_strikes(rows), 1669.12, "2026-10-23", "2026-10-27")
    assert s["max_put_oi"]["strike"] == 1900                                       # the raw heaviest, unchanged
    assert s["put_wall"] == {"strike": 1600, "oi": 31350}                           # the heaviest at or below the price
    assert s["call_wall"] == {"strike": 2100, "oi": 76450}


def test_a_side_with_no_strike_has_no_wall_and_no_spot_means_no_walls():
    s = route.summarise_chain(_strikes([(100, 5, 5), (110, 6, 6)]), 120.0, "2026-10-23", "2026-10-27")
    assert s["call_wall"] is None and s["put_wall"]["strike"] in (100, 110)
    s = route.summarise_chain(_strikes([(100, 5, 5)]), None, "2026-10-23", "2026-10-27")
    assert s["put_wall"] is None and s["call_wall"] is None and s["max_call_oi"] is not None


# ── GET /forward-test (test_reports/fno_forward_test_TESTCASES.md TC-6) ────────────────────────────────────────

class _FwdCursor:
    def __init__(self, docs): self.docs = docs
    def sort(self, *_a, **_k): return self
    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield dict(d)
        return gen()


class _FwdDb:
    def __init__(self, docs, fail=False): self.docs, self.fail = docs, fail
    def __getitem__(self, name):
        db = self
        class C:
            def find(self, *_a, **_k):
                if db.fail:
                    raise RuntimeError("mongo down")
                return _FwdCursor(db.docs)
        return C()


def test_forward_test_with_nothing_recorded_reads_no_prices(monkeypatch):
    import deps
    monkeypatch.setattr(deps, "db", _FwdDb([]))
    c, calls = _client(monkeypatch, (404, {}))
    body = c.get("/api/fno/forward-test").json()
    assert body["started"] is False and body["recorded_sessions"] == 0 and body["settings"] == {} and "underperforms" in body["hypothesis"]
    assert body["settings_recorded"] == ["production_floors", "no_threshold"] and "Inconclusive" in body["past_result"] and calls == []


def test_forward_test_with_records_returns_counts_and_no_result_before_30_sessions(monkeypatch):
    import deps
    days = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    syms = [f"S{k}" for k in range(12)]
    docs = [{"as_of": days[0], "universe_symbols": syms, "settings": {"production_floors": [{"symbol": "S1", "p": -1, "o": 4}], "no_threshold": []}}]

    async def bulk(symbols, start=None, end=None, timeout=30.0):
        return {s: [{"as_of_date": d, "adj_open": 100.0, "adj_close": 100.0 + i * (0.5 if s == "S1" else -0.1)} for i, d in enumerate(days)] for s in symbols}

    monkeypatch.setattr(deps, "db", _FwdDb(docs))
    monkeypatch.setattr(route.daas_client, "get_adjusted_prices_bulk", bulk)
    route._FORWARD_CACHE.update({"ts": 0.0, "key": None, "bars": None})
    c, _ = _client(monkeypatch, (404, {}))
    body = c.get("/api/fno/forward-test").json()
    pf = body["settings"]["production_floors"]
    assert body["started"] is True and body["recorded_sessions"] == 1 and body["last_recorded"] == days[0] and body["prices_available"] is True
    assert pf["recorded_sessions"] == 1 and pf["signals_recorded"] == 1 and pf["judged_sessions"] == 1 and pf["mean_pct"] is None and pf["sessions_needed"] == 29


def test_forward_test_read_failure_is_502(monkeypatch):
    import deps
    monkeypatch.setattr(deps, "db", _FwdDb([], fail=True))
    c, _ = _client(monkeypatch, (404, {}))
    assert c.get("/api/fno/forward-test").status_code == 502


# ── positioning history (test_reports/fno_lab_index_history_TESTCASES.md) ─────────────────────────────────────

def _scan(day, label="short_build_up".replace("_build_up", "_buildup"), price=-0.5, oi=1.0, symbol="NIFTY", key="indices", asof=None):
    return (200, {"as_of": asof or day, key: [{"symbol": symbol, "label": label, "price_chg_pct": price, "oi_chg_pct": oi, "cash_confirmation": "confirms"}], "rows": []})


def _history_client(monkeypatch, answer):
    monkeypatch.setattr(route, "_today", lambda: route.date(2026, 10, 23))
    return _client(monkeypatch, lambda path, params: answer(params["date"]) if path == "/desk/fno-buildup" else (404, {}))


def test_history_returns_the_newest_sessions_oldest_first_and_skips_days_the_scan_does_not_answer_for(monkeypatch):
    good = {"2026-10-23": "long_buildup", "2026-10-22": "short_buildup", "2026-10-21": "short_buildup", "2026-10-19": "short_covering", "2026-10-16": "long_unwinding", "2026-10-15": "long_buildup"}

    def answer(d):
        if d in good:
            return _scan(d, label=good[d])
        if d == "2026-10-20":
            return _scan(d, asof="2026-10-19")           # a holiday: the platform answered with another day
        return (404, {"detail": "no data"})

    c, _ = _history_client(monkeypatch, answer)
    body = c.get("/api/fno/NIFTY/positioning-history?sessions=5").json()
    assert [r["date"] for r in body["sessions"]] == ["2026-10-16", "2026-10-19", "2026-10-21", "2026-10-22", "2026-10-23"]
    assert [r["label"] for r in body["sessions"]] == ["long_unwinding", "short_covering", "short_buildup", "short_buildup", "long_buildup"]
    assert body["sessions"][0]["cash_confirmation"] == "confirms" and body["read_only"] is True
    assert body["missing"] == 16 - 6 and body["requested"] == 5


def test_history_finds_a_stock_in_the_stock_rows_and_leaves_an_absent_symbol_without_a_state(monkeypatch):
    def answer(d):
        if d == "2026-10-23":
            return (200, {"as_of": d, "indices": [], "rows": [{"symbol": "TCS", "label": "short_buildup", "price_chg_pct": -1.2, "oi_chg_pct": 4.0}]})
        if d == "2026-10-22":
            return (200, {"as_of": d, "indices": [], "rows": []})
        return (404, {"detail": "no data"})

    c, _ = _history_client(monkeypatch, answer)
    rows = c.get("/api/fno/TCS/positioning-history?sessions=2").json()["sessions"]
    assert rows[1] == {"date": "2026-10-23", "label": "short_buildup", "price_chg_pct": -1.2, "oi_chg_pct": 4.0, "cash_confirmation": None}
    assert rows[0] == {"date": "2026-10-22", "label": None, "price_chg_pct": None, "oi_chg_pct": None, "cash_confirmation": None}


def test_history_with_every_day_failing_is_502_and_a_bad_session_count_is_422(monkeypatch):
    c, _ = _history_client(monkeypatch, lambda d: (502, {}))
    assert c.get("/api/fno/NIFTY/positioning-history").status_code == 502
    assert c.get("/api/fno/NIFTY/positioning-history?sessions=1").status_code == 422
    assert c.get("/api/fno/NIFTY/positioning-history?sessions=11").status_code == 422
