"""Chart Analysis v2 — the three backend contracts of test_reports/chart_analysis_v2_TESTCASES.md, cases D1–D4, K1–K2, G1–G2.

    BE-1  GET /api/fno/{symbol}/futures/oi-buildup?daily=N   daily_bars + daily_windows per slot and consolidated
    BE-2  GET /api/fno/{symbol}/chain/consolidated?around=N  the listed expiries summed per strike
    BE-3  POST /api/desk/strategy/payoff                     pre_expiry.scenarios with the position's greeks

No network, no Mongo, no Kite: every bhavcopy row, chain and leg below is MOCK — not real data. The DaaS bodies have the
shape the data platform sends (nidp/services/daas_api/routers/fno.py: /fno/{symbol}/expiries, /history, /chain), so the
routes' own work runs for real. Real figures come from the staging probe (cases S1–S3).
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as payoff_route
from routes import fno as fno_route
from services import fno_oi_windows as ow
from services.strategy_plan import compute_payoff
from tests.test_desk_live_chart import FakeFutService, _fno_client


# ── BE-1 fixtures: a synthetic bhavcopy, MOCK — not real data ────────────────
#
# Monthly futures expiries below; on each weekday from 1 Jul to 28 Oct 2026 the three nearest expiries on or after the
# day are listed (so the new far month appears the day after an expiry, as on NSE). Two weekdays are not in the data:
# 2 Oct (an exchange holiday) and 15 Sep (a day the platform never loaded): both must be absent, never filled.
# Per contract E on the k-th session (k counts every session in the data from 0):
#     close  = CLOSE_BASE[E] + k            volume = VOL_BASE[E] + k            oi = OI_BASE[E] + 10·k
# so a contract's own OI change from one session to the next is always +10, and the jump between two contracts is large.

FUT_EXPIRIES = ["2026-06-30", "2026-07-28", "2026-08-25", "2026-09-29", "2026-10-27", "2026-11-24", "2026-12-29", "2027-01-26"]
CLOSE_BASE = {e: 1000.0 + 20 * i for i, e in enumerate(FUT_EXPIRIES)}
VOL_BASE = {e: 1000 * (i + 1) for i, e in enumerate(FUT_EXPIRIES)}
OI_BASE = {e: 100_000 * (i + 1) for i, e in enumerate(FUT_EXPIRIES)}
NOT_IN_DATA = {"2026-10-02", "2026-09-15"}
# Option-only expiries the expiry list also carries (MOCK): an index-style one in the same month as a futures expiry, AFTER
# it (the NIFTY March 2026 shape: futures on 30 Mar, options alone on 31 Mar), and a weekly one before the monthly.
OPTION_ONLY = ["2026-09-30", "2026-10-20"]
AS_OF = "2026-10-28"


def _sessions() -> List[str]:
    d, out = date(2026, 7, 1), []
    while d.isoformat() <= AS_OF:
        if d.weekday() < 5 and d.isoformat() not in NOT_IN_DATA:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


SESSIONS = _sessions()
K = {d: k for k, d in enumerate(SESSIONS)}


def listed_on(day: str) -> List[str]:
    return [e for e in FUT_EXPIRIES if e >= day][:3]


def close(e: str, d: str) -> float:
    return CLOSE_BASE[e] + K[d]


def vol(e: str, d: str) -> int:
    return VOL_BASE[e] + K[d]


def oi(e: str, d: str) -> int:
    return OI_BASE[e] + 10 * K[d]


def _history_rows(expiry: str, start: str) -> List[Dict[str, Any]]:
    """GET /v1/fno/{symbol}/history?kind=future&expiry=E&start=S rows (row_to_dict of its SELECT). MOCK."""
    return [{"as_of_date": d, "ticker_symbol": "TESTCO", "instrument_type": "STF", "expiry_date": expiry, "strike_price": -1.0,
             "option_type": "FUT", "close_price": close(expiry, d), "settle_price": close(expiry, d), "prev_close_price": None,
             "underlying_price": 999.0, "open_interest": oi(expiry, d), "traded_volume": vol(expiry, d), "new_board_lot_qty": 175}
            for d in SESSIONS if d >= start and expiry in listed_on(d)]


def _expiry_list() -> List[Dict[str, Any]]:
    """GET /v1/fno/{symbol}/expiries: futures_count is 0 for every expiry, as on the live platform (futures are "FUT")."""
    rows = [{"expiry_date": e, "ce_count": 40, "pe_count": 40, "futures_count": 0, "latest_seen": min(e, AS_OF)}
            for e in FUT_EXPIRIES + OPTION_ONLY]
    return sorted(rows, key=lambda r: r["expiry_date"], reverse=True)


def _eod_futures_rows() -> List[Dict[str, Any]]:
    """GET /v1/fno/{symbol}?instrument_type=STF for the latest day (the end-of-day mode's own read). MOCK."""
    return [{"as_of_date": AS_OF, "expiry_date": e, "option_type": "FUT", "close_price": close(e, AS_OF), "settle_price": close(e, AS_OF),
             "prev_close_price": close(e, AS_OF) - 1, "open_interest": oi(e, AS_OF), "change_in_oi": 10, "traded_volume": vol(e, AS_OF),
             "underlying_price": 999.0} for e in listed_on(AS_OF)]


class DaasRecorder:
    def __init__(self, fail_history: bool = False):
        self.calls: List[Tuple[str, Optional[dict]]] = []
        self.fail_history = fail_history

    def __call__(self, path: str, params: Optional[dict]):
        self.calls.append((path, params))
        if path.endswith("/expiries"):
            return 200, {"symbol": "TESTCO", "data": _expiry_list(), "count": 8}
        if path.endswith("/history"):
            if self.fail_history:
                return 500, {"detail": "boom"}
            return 200, {"data": _history_rows(params["expiry"], params["start"]),
                         "pagination": {"limit": params["limit"], "offset": 0, "total": None, "next_offset": None},
                         "symbol": "TESTCO", "kind": "future", "expiry": params["expiry"]}
        if params and params.get("instrument_type") == "STF":
            return 200, {"data": _eod_futures_rows(), "as_of": AS_OF}
        return 200, {"data": [], "as_of": AS_OF}

    def history_expiries(self) -> List[str]:
        return [p["expiry"] for path, p in self.calls if path.endswith("/history")]


def _kite_raw() -> Dict[str, Any]:
    """An intraday Kite answer (contracts current / next / far), MOCK. Only its shape matters here."""
    bar = lambda m, c, o: [f"{AS_OF}T09:{m:02d}:00+05:30", c, c + 1, c - 1, c, 10, o]   # noqa: E731
    return {"availability": "ok", "as_of": f"{AS_OF}T05:45:00+00:00", "source": "Kite intraday, futures with open interest",
            "contracts": [{"expiry": e, "tradingsymbol": e, "lot_size": 175, "bars": [bar(15, 100.0, 1000), bar(30, 101.0, 1010)]}
                          for e in listed_on(AS_OF)]}


def _client(monkeypatch, kite_answer, daas: DaasRecorder) -> TestClient:
    monkeypatch.setattr(fno_route, "_DAILY_CACHE", {})
    return _fno_client(monkeypatch, FakeFutService(kite_answer), daas)


def _get(monkeypatch, url, kite_answer=None, daas: Optional[DaasRecorder] = None):
    daas = daas or DaasRecorder()
    kite_answer = kite_answer if kite_answer is not None else {"availability": "token_missing", "contracts": []}
    r = _client(monkeypatch, kite_answer, daas).get(url)
    return r, daas


# ── D1 per-slot continuous series, expiry per bar, a roll keeps the new contract's own OI change ─────────────────

@pytest.mark.parametrize("kite", [{"availability": "token_missing", "contracts": []}, _kite_raw()], ids=["end_of_day", "intraday"])
def test_d1_daily_bars_per_slot_are_continuous_with_the_contract_named(monkeypatch, kite):
    r, daas = _get(monkeypatch, "/api/fno/testco/futures/oi-buildup?daily=60", kite)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["mode"] == ("intraday" if kite["contracts"] else "end_of_day")
    shown = SESSIONS[-60:]
    for c in b["contracts"]:
        bars = c["daily_bars"]
        assert [x[0] for x in bars] == shown and all(len(x) == 6 for x in bars), c["slot"]
    cur, nxt, far = (c["daily_bars"] for c in b["contracts"])
    by = lambda bars: {x[0]: x for x in bars}   # noqa: E731
    # 27 Oct is the October contract's expiry day: it is still that day's current month
    assert by(cur)["2026-10-27"] == ["2026-10-27", close("2026-10-27", "2026-10-27"), vol("2026-10-27", "2026-10-27"),
                                     oi("2026-10-27", "2026-10-27"), 10, "2026-10-27"]
    # 28 Oct: the roll. Current is now November, and its OI change is November's own (+10), not the jump from October's OI
    assert by(cur)["2026-10-28"] == ["2026-10-28", close("2026-11-24", "2026-10-28"), vol("2026-11-24", "2026-10-28"),
                                     oi("2026-11-24", "2026-10-28"), 10, "2026-11-24"]
    assert oi("2026-11-24", "2026-10-28") - oi("2026-10-27", "2026-10-27") == 100_010      # the jump that must NOT show
    assert by(nxt)["2026-10-28"][4:] == [10, "2026-12-29"] and by(nxt)["2026-10-27"][5] == "2026-11-24"
    # the new far month is listed on 28 Oct: no row the session before, so no OI change (null, never zero or a jump)
    assert by(far)["2026-10-28"] == ["2026-10-28", close("2027-01-26", "2026-10-28"), vol("2027-01-26", "2026-10-28"),
                                     oi("2027-01-26", "2026-10-28"), None, "2027-01-26"]
    # every bar is the slot's contract that day: the 1st / 2nd / 3rd expiry on or after the day
    for slot, bars in enumerate((cur, nxt, far)):
        assert all(x[5] == listed_on(x[0])[slot] for x in bars)
    # the first bar shown has its previous session read too (the baseline), so its OI change is there
    assert cur[0][4] == 10
    # the per-month search: September's options-only 30 Sep is tried first and answers no futures, then 29 Sep;
    # October's latest expiry (27 Oct) has futures, so the weekly 20 Oct is never read
    asked = daas.history_expiries()
    assert asked.index("2026-09-30") < asked.index("2026-09-29") and "2026-10-20" not in asked
    assert b["daily"]["requested"] == 60 and b["daily"]["sessions"] == 60


# ── D2 consolidated: sums over the day's listed expiries; a missing day is absent, never filled ────────────────────

def test_d2_consolidated_daily_sums_and_missing_days_are_absent(monkeypatch):
    r, _ = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup?daily=60")
    b = r.json()
    cons = {x[0]: x for x in b["consolidated"]["daily_bars"]}
    assert list(cons) == SESSIONS[-60:]
    assert not NOT_IN_DATA & set(cons)                                  # 15 Sep and 2 Oct: absent, not filled
    for d in ("2026-10-27", "2026-10-28"):
        listed = listed_on(d)
        prev = SESSIONS[SESSIONS.index(d) - 1]
        total, total_prev = sum(oi(e, d) for e in listed), sum(oi(e, prev) for e in listed_on(prev))
        assert cons[d] == [d, close(listed[0], d), sum(vol(e, d) for e in listed), total, total - total_prev, listed[0]]
    # 28 Oct: October expired (−its OI), January listed (+its OI): the summed change is the real change of the sum
    assert cons["2026-10-28"][4] == (oi("2026-11-24", "2026-10-28") + oi("2026-12-29", "2026-10-28") + oi("2027-01-26", "2026-10-28")
                                     - oi("2026-10-27", "2026-10-27") - oi("2026-11-24", "2026-10-27") - oi("2026-12-29", "2026-10-27"))
    # the day after a missing day compares with the previous day IN THE DATA (1 Oct for 5 Oct; 14 Sep for 16 Sep)
    assert cons["2026-10-05"][4] == sum(oi(e, "2026-10-05") for e in listed_on("2026-10-05")) - sum(oi(e, "2026-10-01") for e in listed_on("2026-10-01"))
    assert b["consolidated"]["daily_bars"][-1][1:2] == [close("2026-11-24", AS_OF)]


def test_d2_a_contract_without_oi_leaves_the_consolidated_oi_null_never_a_partial_sum():
    book = {"2026-10-26": {"2026-10-27": (100.0, 5, 1000), "2026-11-24": (101.0, 3, 500)},
            "2026-10-27": {"2026-10-27": (102.0, 6, 900), "2026-11-24": (103.0, None, None)}}
    s = ow.daily_series(book, 5)
    assert s["consolidated"] == [["2026-10-26", 100.0, 8, 1500, None, "2026-10-27"],
                                 ["2026-10-27", 102.0, None, None, None, "2026-10-27"]]
    assert s["slots"]["next"][1] == ["2026-10-27", 103.0, None, None, None, "2026-11-24"]
    assert s["slots"]["current"][1][4] == -100 and s["slots"]["far"] == []


# ── D3 daily=0 answers exactly as today; daily > 250 is 422 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("kite", [{"availability": "token_missing", "contracts": []}, _kite_raw()], ids=["end_of_day", "intraday"])
def test_d3_daily_zero_is_the_answer_of_today_and_reads_no_history(monkeypatch, kite):
    r0, daas0 = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup", kite)
    r1, daas1 = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup?daily=0", kite)
    b0, b1 = r0.json(), r1.json()
    for b in (b0, b1):
        assert "daily" not in b and "daily_bars" not in b["consolidated"] and "daily_windows" not in b["consolidated"]
        assert all("daily_bars" not in c and "daily_windows" not in c for c in b["contracts"])
    assert daas0.history_expiries() == daas1.history_expiries() == []
    assert b0 == b1


@pytest.mark.parametrize("q", ["daily=251", "daily=-1", "daily=x"])
def test_d3_daily_out_of_range_is_422_before_any_read(monkeypatch, q):
    r, daas = _get(monkeypatch, f"/api/fno/TESTCO/futures/oi-buildup?{q}")
    assert r.status_code == 422 and daas.calls == []


def test_d3_daily_250_is_accepted_and_a_failed_history_read_is_502(monkeypatch):
    r, _ = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup?daily=250")
    assert r.status_code == 200 and len(r.json()["contracts"][0]["daily_bars"]) == len(SESSIONS)   # fewer sessions exist: all sent
    r2, _ = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup?daily=20", daas=DaasRecorder(fail_history=True))
    assert (r2.status_code, r2.json()) == (502, {"detail": "upstream_unavailable"})


# ── D4 daily windows: aligned on the latest session, one contract per window across a roll ──────────────────────

def test_d4_daily_windows_across_a_roll_use_one_contract(monkeypatch):
    r, _ = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup?daily=60&window=4")
    b = r.json()
    shown = SESSIONS[-60:]
    cur = b["contracts"][0]["daily_windows"]
    assert len(cur) == 15 and cur[-1]["end"] == AS_OF and cur[0]["start"] == shown[0]
    assert [w["index"] for w in cur] == list(range(15)) and all(w["complete"] is True for w in cur)
    # the last window: 23, 26, 27, 28 Oct. Its last bar is November's (the roll is on 28 Oct), so every figure is November's,
    # against November's own row on 22 Oct (the session before the window): price +4 (k rises by 4), OI +40
    w = cur[-1]
    assert (w["start"], w["end"], w["day"], w["expiry"]) == ("2026-10-23", AS_OF, AS_OF, "2026-11-24")
    window_days = ["2026-10-23", "2026-10-26", "2026-10-27", AS_OF]
    assert w["close"] == close("2026-11-24", AS_OF) and w["oi"] == oi("2026-11-24", AS_OF)
    assert (w["price_change"], w["oi_change"]) == (4.0, 40)
    assert w["price_change_pct"] == round(4.0 / close("2026-11-24", "2026-10-22") * 100, 2)
    assert w["oi_change_pct"] == round(40 / oi("2026-11-24", "2026-10-22") * 100, 2)
    assert w["label"] == ow.buildup_label(4.0, 40) == "long_buildup"
    assert (w["bars"], w["volume"]) == (4, sum(vol("2026-11-24", d) for d in window_days))
    # the far slot's last window is January's, listed only on 28 Oct: no row before the window, so no changes and no label
    fw = b["contracts"][2]["daily_windows"][-1]
    assert (fw["expiry"], fw["bars"], fw["price_change"], fw["oi_change"], fw["label"]) == ("2027-01-26", 1, None, None, None)
    # consolidated: the current slot's price (November's own change) with the summed OI against the summed OI on 22 Oct
    cw = b["consolidated"]["daily_windows"][-1]
    sum_oi = lambda d: sum(oi(e, d) for e in listed_on(d))   # noqa: E731
    assert (cw["price_change"], cw["oi"], cw["oi_change"]) == (4.0, sum_oi(AS_OF), sum_oi(AS_OF) - sum_oi("2026-10-22"))
    assert cw["label"] == ow.buildup_label(cw["price_change"], cw["oi_change"])
    assert cw["volume"] == sum(sum(vol(e, d) for e in listed_on(d)) for d in window_days)


def test_d4_a_partial_first_window_is_dropped(monkeypatch):
    r, _ = _get(monkeypatch, "/api/fno/TESTCO/futures/oi-buildup?daily=60&window=7")
    w = r.json()["contracts"][0]["daily_windows"]
    shown = SESSIONS[-60:]
    assert len(w) == 8 and w[0]["start"] == shown[4] and w[-1]["end"] == AS_OF   # 60 = 4 dropped + 8 × 7
    assert all(x["bars"] == 7 for x in w)
    assert ow.window_groups(["a", "b", "c"], 4) == []


# ── BE-2 fixtures: three expiries of one underlying on one day, MOCK — not real data ─────────────────────────────
#
#   strike   E1 (27 Oct)                E2 (24 Nov)               E3 (29 Dec)                  summed
#            call oi/Δ/vol  put        call       put            call          put            call            put
#    100     10/1/7     40/4/9         5/1/1      20/2/3         1/0/0         10/1/1         16/2/8          70/7/13
#    110     20/−2/30   30/3/25        10/0/4     10/−1/5        0/null/0      15/1/2         30/−2/34        55/3/32
#    120     50/5/12    5/−1/2         30/3/6     0/0/0          20/2/2        5/0/1          100/10/20       10/−1/3
#    130     —          —              —          —              40/4/null     —              40/4/null       null
#
#   totals   call OI 16+30+100+40 = 186, put OI 70+55+10 = 135, PCR 135/186 = 0.7258
#            call OI change 2−2+10+4 = 14, put OI change 7+3−1 = 9
#   ATM      spot 108 → 110
#   max pain K=100: puts 55×10 + 10×20 = 750;  K=110: calls 16×10 + puts 10×10 = 260;  K=120: calls 16×20 + 30×10 = 620;
#            K=130: calls 16×30 + 30×20 + 100×10 = 2080  → 110
#   walls    put wall = heaviest put OI at or below 108: 100 (70); call wall = heaviest call OI at or above 108: 120 (100)

E1, E2, E3 = "2026-10-27", "2026-11-24", "2026-12-29"
CDAY = "2026-10-26"


def _side(k, side, oi_, d_oi, vol_):
    return {"strike_price": k, "option_type": side, "close_price": 5.0, "settle_price": 5.0, "underlying_price": 108.0,
            "open_interest": oi_, "change_in_oi": d_oi, "traded_volume": vol_, "traded_value": 1.0}


def _chain(expiry, rows, as_of=CDAY):
    return {"symbol": "TESTCO", "as_of": as_of, "expiry": expiry, "strike_count": len(rows),
            "strikes": [{"strike": k, "CE": _side(k, "CE", *c) if c else None, "PE": _side(k, "PE", *p) if p else None} for k, c, p in rows]}


CHAINS = {
    E1: _chain(E1, [(100.0, (10, 1, 7), (40, 4, 9)), (110.0, (20, -2, 30), (30, 3, 25)), (120.0, (50, 5, 12), (5, -1, 2))]),
    E2: _chain(E2, [(100.0, (5, 1, 1), (20, 2, 3)), (110.0, (10, 0, 4), (10, -1, 5)), (120.0, (30, 3, 6), (0, 0, 0))]),
    E3: _chain(E3, [(100.0, (1, 0, 0), (10, 1, 1)), (110.0, (0, None, 0), (15, 1, 2)), (120.0, (20, 2, 2), (5, 0, 1)),
                    (130.0, (40, 4, None), None)]),
}


def _expiries_body(expiries=(E1, E2, E3), options=True):
    return {"symbol": "TESTCO", "data": [{"expiry_date": e, "ce_count": 3 if options else 0, "pe_count": 3 if options else 0,
                                          "futures_count": 0, "latest_seen": CDAY} for e in expiries]}


def _chain_client(monkeypatch, reply):
    calls = []

    async def get_raw(path, params=None, timeout=10.0):
        calls.append((path, params))
        out = reply(path, params)
        if isinstance(out, Exception):
            raise out
        return copy.deepcopy(out)

    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    monkeypatch.setattr(fno_route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(fno_route.daas_client, "is_configured", lambda: True)
    monkeypatch.setattr(fno_route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(fno_route.router)
    return TestClient(app), calls


def _three(path, params, chains=CHAINS, listing=None):
    if path.endswith("/expiries"):
        return 200, listing or _expiries_body()
    if path.endswith("/chain"):
        return 200, chains[params["expiry"]]
    return 404, {"detail": "Not Found"}


# ── K1 sums per strike over three expiries; PCR / max pain / walls over the sums ────────────────────────────────

def test_k1_consolidated_chain_sums_each_strike_and_reads_the_summary_over_the_sums(monkeypatch):
    c, calls = _chain_client(monkeypatch, _three)
    r = c.get("/api/fno/testco/chain/consolidated")
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["symbol"], b["as_of"], b["expiries"], b["spot"]) == ("TESTCO", CDAY, [E1, E2, E3], 108.0)
    assert (b["basis"], b["read_only"]) == ("summed over the listed expiries", True)
    rows = {x["strike"]: x for x in b["strikes"]}
    assert rows[100] == {"strike": 100, "call": {"oi": 16, "change_in_oi": 2, "volume": 8}, "put": {"oi": 70, "change_in_oi": 7, "volume": 13}}
    assert rows[110] == {"strike": 110, "call": {"oi": 30, "change_in_oi": -2, "volume": 34}, "put": {"oi": 55, "change_in_oi": 3, "volume": 32}}
    assert rows[120] == {"strike": 120, "call": {"oi": 100, "change_in_oi": 10, "volume": 20}, "put": {"oi": 10, "change_in_oi": -1, "volume": 3}}
    assert b["summary"] == {"atm_strike": 110, "pcr": 0.7258, "max_pain": 110, "put_wall": {"strike": 100, "oi": 70},
                            "call_wall": {"strike": 120, "oi": 100}, "total_call_oi": 186, "total_put_oi": 135,
                            "total_call_oi_change": 14, "total_put_oi_change": 9}
    # no prices and no Greeks anywhere: they do not add across expiries
    assert all(set(x[side]) == {"oi", "change_in_oi", "volume"} for x in b["strikes"] for side in ("call", "put") if x[side])
    # one chain read per listed expiry, exactly the read /chain makes
    assert sorted(p["expiry"] for path, p in calls if path.endswith("/chain")) == [E1, E2, E3]
    # the window: ±1 strike about the ATM strike (110), the summary still over every strike
    w = c.get("/api/fno/TESTCO/chain/consolidated?around=1").json()
    assert [x["strike"] for x in w["strikes"]] == [100, 110, 120] and w["summary"] == b["summary"]


def test_k1_an_expiry_read_for_another_day_is_dropped_not_summed(monkeypatch):
    stale = {**CHAINS, E3: {**CHAINS[E3], "as_of": "2026-10-23"}}
    c, _ = _chain_client(monkeypatch, lambda p, q: _three(p, q, chains=stale))
    b = c.get("/api/fno/TESTCO/chain/consolidated").json()
    assert b["expiries"] == [E1, E2]
    rows = {x["strike"]: x for x in b["strikes"]}
    assert rows[100]["call"] == {"oi": 15, "change_in_oi": 2, "volume": 8} and 130 not in rows
    assert b["summary"]["total_call_oi"] == 80 + 45


@pytest.mark.parametrize("q", ["around=0", "around=501", "around=x"])
def test_k1_out_of_range_window_is_422(monkeypatch, q):
    c, calls = _chain_client(monkeypatch, _three)
    assert c.get(f"/api/fno/TESTCO/chain/consolidated?{q}").status_code == 422 and calls == []


# ── K2 a strike listed in one expiry still sums what exists; no options → 404 ──────────────────────────────────

def test_k2_a_strike_in_one_expiry_only_and_a_figure_null_everywhere(monkeypatch):
    c, _ = _chain_client(monkeypatch, _three)
    rows = {x["strike"]: x for x in c.get("/api/fno/TESTCO/chain/consolidated").json()["strikes"]}
    # 130 is listed by E3 alone, call side only: its figures are E3's; its volume is null there, so it stays null
    assert rows[130] == {"strike": 130, "call": {"oi": 40, "change_in_oi": 4, "volume": None}, "put": None}
    # 110 call: E3's change in OI is null, the others are summed (−2 + 0), never treated as a missing strike
    assert rows[110]["call"]["change_in_oi"] == -2
    assert fno_route.sum_sides([None, {"oi": None, "change_in_oi": None, "volume": 3}]) == {"oi": None, "change_in_oi": None, "volume": 3}
    assert fno_route.sum_sides([None, None]) is None


def test_k2_no_options_is_404_with_the_plain_sentence(monkeypatch):
    c, calls = _chain_client(monkeypatch, lambda p, q: _three(p, q, listing=_expiries_body(options=False)))
    r = c.get("/api/fno/TESTCO/chain/consolidated")
    assert (r.status_code, r.json()) == (404, {"detail": "No option contracts are listed for TESTCO"})
    assert [p for p, _ in calls] == ["/fno/TESTCO/expiries"]
    c2, _ = _chain_client(monkeypatch, lambda p, q: (200, {"symbol": "NOPE", "data": [], "count": 0}))
    r2 = c2.get("/api/fno/NOPE/chain/consolidated")
    assert (r2.status_code, r2.json()) == (404, {"detail": "No F&O data for NOPE"})


def test_k2_a_failed_chain_read_is_502_never_a_partial_sum(monkeypatch):
    def reply(path, params):
        if path.endswith("/chain") and params["expiry"] == E2:
            return fno_route.daas_client.DaasError("DAAS connectivity error")
        return _three(path, params)
    c, _ = _chain_client(monkeypatch, reply)
    r = c.get("/api/fno/TESTCO/chain/consolidated")
    assert (r.status_code, r.json()) == (502, {"detail": "upstream_unavailable"})


def test_k2_consolidated_chain_needs_a_signed_in_user(monkeypatch):
    calls = []

    async def get_raw(path, params=None, timeout=10.0):
        calls.append(path)
        return 200, {}

    monkeypatch.setattr(fno_route.daas_client, "get_raw", get_raw)
    app = FastAPI()
    app.include_router(fno_route.router)
    r = TestClient(app).get("/api/fno/TESTCO/chain/consolidated")
    assert (r.status_code, calls) == (401, [])


# ── BE-3: pre_expiry.scenarios, MOCK legs (round numbers) ───────────────────────────────────────────────────────

PTODAY = date(2026, 10, 19)
PEXP = "2026-11-26"
PRE = {"date": "2026-10-26", "iv_shift_pct": 0, "rate_pct": 5.75}
REF = 1215.0


def _leg(side, strike, entry, iv=None, ot="call"):
    out = {"kind": "option", "side": side, "quantity": 1, "lot_size": 250, "entry_price": entry, "expiry": PEXP,
           "strike": strike, "option_type": ot}
    if iv is not None:
        out["iv_pct"] = iv
    return out


BULL_CALL = [_leg("buy", 1250.0, 30.0, 25.0), _leg("sell", 1300.0, 14.0, 24.0)]
# what the frontend sends: 11 scenarios from −r % to +r % of the reference price, and a 61-point grid
PCTS = [-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]
SCEN = [{"name": f"{p:+d}%", "underlying_price": round(REF * (1 + p / 100), 2)} for p in PCTS]
GRID61 = {"min": REF * 0.9, "max": REF * 1.1, "points": 61}


def _body(legs=BULL_CALL, scenarios=SCEN, pre=PRE, ref=REF, grid=GRID61):
    b = {"underlying": "TESTCO", "reference_price": ref, "legs": legs, "grid": grid, "as_of": PTODAY.isoformat()}
    if scenarios is not None:
        b["scenarios"] = scenarios
    if pre is not None:
        b["pre_expiry"] = pre
    return b


def _without(d, *path):
    d = copy.deepcopy(d)
    *head, last = path
    tgt = d
    for k in head:
        tgt = tgt[k]
    tgt.pop(last, None)
    return d


# ── G1 per-scenario greeks equal the curve's model at that price ────────────────────────────────────────────────

def test_g1_scenarios_are_priced_and_greeked_by_the_pre_expiry_model():
    r = compute_payoff(_body(), PTODAY)
    pe = r["pre_expiry"]
    assert r["valid"] and pe["unavailable"] == [] and len(pe["scenarios"]) == 11 and len(pe["grid"]) == 61
    by = {s["name"]: s for s in pe["scenarios"]}
    # at the reference price the scenario's greeks ARE the position's greeks
    assert by["+0%"]["underlying_price"] == REF and by["+0%"]["greeks"] == pe["greeks"]
    # the grid's middle point is the reference price: the scenario there has the curve's value
    mid = pe["grid"].index(REF)
    assert (by["+0%"]["gross"], by["+0%"]["net"]) == (pe["gross"][mid], pe["net"][mid])
    # the grid's ends are −10 % / +10 %: same values as the curve at those prices
    assert (by["-10%"]["gross"], by["-10%"]["net"]) == (pe["gross"][0], pe["net"][0])
    assert (by["+10%"]["gross"], by["+10%"]["net"]) == (pe["gross"][-1], pe["net"][-1])
    # at any other price the greeks are what the same model gives with the reference moved there (iv given, so the
    # volatilities do not depend on the reference price)
    for s in pe["scenarios"]:
        moved = compute_payoff(_body(ref=s["underlying_price"], scenarios=None,
                                     grid={"min": s["underlying_price"] * 0.9, "max": s["underlying_price"] * 1.1, "points": 5}), PTODAY)
        assert s["greeks"] == moved["pre_expiry"]["greeks"], s["name"]
        assert set(s) == {"name", "underlying_price", "gross", "net", "greeks"}
    # a bull call spread's delta is largest between the strikes and positive at every scenario
    assert all(s["greeks"]["delta"] > 0 for s in pe["scenarios"])


def test_g1_nothing_else_in_the_answer_changes():
    with_s = compute_payoff(_body(), PTODAY)
    without_s = compute_payoff(_body(scenarios=None), PTODAY)
    assert "scenarios" not in without_s["pre_expiry"]                     # no scenarios asked: the answer of before
    assert _without(with_s, "pre_expiry", "scenarios")["pre_expiry"] == without_s["pre_expiry"]
    assert _without(_without(with_s, "pre_expiry"), "expiry", "scenarios") == _without(_without(without_s, "pre_expiry"), "expiry", "scenarios")
    no_pre = compute_payoff(_body(pre=None), PTODAY)
    assert no_pre["pre_expiry"] is None and len(no_pre["expiry"]["scenarios"]) == 11


def test_g1_route_answers_the_scenarios(monkeypatch):
    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}
    monkeypatch.setattr(payoff_route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(payoff_route.router)
    res = TestClient(app).post("/api/desk/strategy/payoff", json=_body())
    assert res.status_code == 200
    pe = res.json()["pre_expiry"]
    assert [s["name"] for s in pe["scenarios"]] == [s["name"] for s in SCEN]
    assert next(s for s in pe["scenarios"] if s["name"] == "+0%")["greeks"] == pe["greeks"]


# ── G2 an unpriceable leg: scenario figures null, the reason listed, the expiry payoff unchanged ─────────────────

def test_g2_an_unpriceable_leg_nulls_the_scenarios_and_keeps_the_expiry_payoff():
    # a 1000 call bought at 0.5 with the reference at 1215 and no iv_pct: the premium is below intrinsic value, so no
    # Black-76 volatility prices it (the leg is unavailable; no volatility is ever assumed)
    legs = [_leg("buy", 1000.0, 0.5), _leg("sell", 1050.0, 0.2, 20.0)]
    r = compute_payoff(_body(legs=legs), PTODAY)
    pe = r["pre_expiry"]
    assert [u["leg"] for u in pe["unavailable"]] == [0] and "iv_pct" in pe["unavailable"][0]["reason"]
    assert len(pe["scenarios"]) == 11
    assert all((s["gross"], s["net"], s["greeks"]) == (None, None, None) for s in pe["scenarios"])
    assert [s["underlying_price"] for s in pe["scenarios"]] == [s["underlying_price"] for s in SCEN]
    # the expiry view is the same as without the pre-expiry block: values at every scenario price
    plain = compute_payoff(_body(legs=legs, pre=None), PTODAY)
    assert r["expiry"] == plain["expiry"] and all(s["gross"] is not None for s in r["expiry"]["scenarios"])


def test_g2_a_leg_at_expiry_on_the_evaluation_date_prices_but_has_no_greeks():
    r = compute_payoff(_body(pre={**PRE, "date": PEXP}), PTODAY)
    pe = r["pre_expiry"]
    assert pe["greeks"] is None and pe["unavailable"] == []
    assert all(s["greeks"] is None and s["gross"] is not None for s in pe["scenarios"])
    # T = 0: intrinsic value only, the expiry payoff at that price
    assert [s["gross"] for s in pe["scenarios"]] == [s["gross"] for s in r["expiry"]["scenarios"]]
