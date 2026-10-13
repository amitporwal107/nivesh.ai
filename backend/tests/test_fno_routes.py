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
    futures    settle 108.75 − spot 108 = +0.75 (premium); settle 107.50 − 108 = −0.50 (discount)
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import fno as route

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
    assert body["summary"] == {
        "as_of": DAY, "expiry": EXPIRY, "spot": 108.0, "atm_strike": 110,
        "total_call_oi": 80, "total_put_oi": 75, "total_call_oi_change": 4, "total_put_oi_change": 6,
        "pcr": 0.9375, "max_pain": 110,
        "max_call_oi": {"strike": 120, "oi": 50}, "max_put_oi": {"strike": 100, "oi": 40},
    }
    assert [s["strike"] for s in body["strikes"]] == [100, 110, 120]
    assert body["strikes"][1]["call"] == {"close": 2.4, "settle": 2.45, "oi": 20, "change_in_oi": -2, "volume": 30}
    assert (body["strike_count"], body["strikes_returned"]) == (3, 3)
    # the symbol is upper-cased, and no expiry is sent when none was asked for (the data platform picks the nearest)
    assert calls == [("/fno/TESTCO/chain", None)]


def test_chain_forwards_the_expiry_asked_for(monkeypatch):
    c, calls = _client(monkeypatch, (200, CHAIN))
    assert c.get("/api/fno/TESTCO/chain", params={"expiry": EXPIRY}).status_code == 200
    assert calls == [("/fno/TESTCO/chain", {"expiry": EXPIRY})]


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
    assert calls == [(f"/fno/{symbol.upper()}/chain", None)]


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
        "/api/fno/{symbol}/chain", "/api/fno/{symbol}/expiries", "/api/fno/{symbol}/futures"]


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
        # 108.75 − 108 = +0.75
        {"expiry": "2026-10-27", "close": 108.7, "settle": 108.75, "oi": 5000, "change_in_oi": 120, "volume": 2500, "basis": 0.75},
        # 107.50 − 108 = −0.50
        {"expiry": "2026-11-24", "close": 107.6, "settle": 107.5, "oi": 900, "change_in_oi": -30, "volume": 400, "basis": -0.5},
        # no settle price → no basis, never close − spot in its place
        {"expiry": "2026-12-29", "close": 109.0, "settle": None, "oi": 10, "change_in_oi": 0, "volume": 0, "basis": None},
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
