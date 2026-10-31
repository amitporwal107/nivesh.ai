"""Live chart, comprehensive: the futures per-bar series (contract A) and the options intraday read (contract B) of
test_reports/live_chart_comprehensive_TESTCASES.md, cases A1–A3 and B1–B6.

No network, no Mongo, no Kite: every candle, instrument row and quote below is MOCK — not real data. The candle shape
(date, open, high, low, close, volume, oi) is Kite's historical_data with oi=1 and the instrument rows are Kite's NFO list
shape; behaviour against the real Kite is checked separately on staging (cases S1–S2).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import fno as fno_route
from services import fno_oi_windows as ow
from services import fno_options_intraday as foi
from services.kite_live_feed import intraday as it
from tests.test_desk_live_chart import FakeFutService, _eod_reply, _fno_client, _session, run, t

IST = timezone(timedelta(hours=5, minutes=30))


class TokenException(Exception):
    """Named like kiteconnect's, which classify() maps to an expired login. MOCK."""


# ── A1 / A2 / A3 the futures per-bar series ──────────────────────────────────

def _futures_raw():
    """Three listed months over 23 (the baseline session), 26 and 27 Oct. MOCK."""
    near = _session(23, [100, 101], [1000, 1010]) + _session(26, [102, 103], [1020, 1030]) + _session(27, [104, 105, 106], [1040, 1050, 1060])
    nxt = _session(23, [101], [500], vol=40) + _session(26, [102, 103], [505, 510], vol=40) + _session(27, [104, 105], [515, 520], vol=40)
    far = _session(26, [110], [50], vol=5) + _session(27, [111], [60], vol=5)
    return {"availability": "ok", "as_of": "2026-10-27T05:45:00+00:00", "source": "Kite intraday, futures with open interest",
            "contracts": [{"expiry": "2026-10-27", "tradingsymbol": "A", "lot_size": 550, "bars": near},
                          {"expiry": "2026-11-24", "tradingsymbol": "B", "lot_size": 550, "bars": nxt},
                          {"expiry": "2026-12-29", "tradingsymbol": "C", "lot_size": 550, "bars": far}]}


def test_a1_each_contract_carries_its_bars_with_one_baseline_bar(monkeypatch):
    svc = FakeFutService(_futures_raw())
    b = _fno_client(monkeypatch, svc).get("/api/fno/hdfcbank/futures/oi-buildup?interval=15m&window=4&sessions=2").json()
    assert b["mode"] == "intraday" and svc.asked == [("HDFCBANK", "15m", 3)]
    near, nxt, far = (c["bars"] for c in b["contracts"])
    # near: 5 bars on 26-27 Oct plus the last bar of 23 Oct
    assert len(near) == 5 + 1
    assert near[0] == [t(23, 9, 30), 101.0, 100, 1010]
    assert near[-1] == [t(27, 9, 45), 106.0, 100, 1060]
    assert all(len(r) == 4 for r in near)
    assert len(nxt) == 4 + 1 and nxt[0] == [t(23, 9, 15), 101.0, 40, 500]
    # far month: no candle before 26 Oct, so there is no baseline bar to add
    assert far == [[t(26, 9, 15), 110.0, 5, 50], [t(27, 9, 15), 111.0, 5, 60]]


def test_a2_consolidated_sums_oi_only_where_every_listed_expiry_has_the_time(monkeypatch):
    b = _fno_client(monkeypatch, FakeFutService(_futures_raw())).get("/api/fno/HDFCBANK/futures/oi-buildup?sessions=2").json()
    cons = {r[0]: r for r in b["consolidated"]["bars"]}
    assert list(cons) == [t(23, 9, 30), t(26, 9, 15), t(26, 9, 30), t(27, 9, 15), t(27, 9, 30), t(27, 9, 45)]
    assert cons[t(26, 9, 15)] == [t(26, 9, 15), 102.0, 100 + 40 + 5, 1020 + 505 + 50]
    assert cons[t(27, 9, 15)] == [t(27, 9, 15), 104.0, 145, 1040 + 515 + 60]
    # a time one listed expiry has no candle at: OI null (never a partial sum); volume counts what traded; close = the near month's
    assert cons[t(26, 9, 30)] == [t(26, 9, 30), 103.0, 140, None]
    assert cons[t(27, 9, 45)] == [t(27, 9, 45), 106.0, 100, None]
    assert cons[t(23, 9, 30)][3] is None


def test_a2_consolidated_close_is_null_when_the_near_month_has_no_candle():
    near = _session(27, [100], [1000])
    nxt = _session(27, [101, 102], [500, 510])
    rows = ow.consolidated_bars([near, nxt], ["2026-10-27"])
    assert rows == [[t(27, 9, 15), 100.0, 200, 1500], [t(27, 9, 30), None, 100, None]]


def test_a3_end_of_day_answer_has_empty_bars(monkeypatch):
    b = _fno_client(monkeypatch, FakeFutService({"availability": "token_missing", "contracts": []}), _eod_reply).get(
        "/api/fno/HDFCBANK/futures/oi-buildup").json()
    assert b["mode"] == "end_of_day"
    assert [c["bars"] for c in b["contracts"]] == [[], [], []] and b["consolidated"]["bars"] == []


# ── the options fakes ────────────────────────────────────────────────────────

EXPIRIES = (date(2026, 10, 27), date(2026, 11, 24), date(2026, 9, 29))


class OptKite:
    """Kite NFO / NSE lists and candles for ADANIPORTS options. MOCK — not real data.

    Candles: 23 Oct 15:15 (the baseline session's last), then 26 and 27 Oct at 09:15 and 09:30. A contract's OI is
    1000 + strike/10 for a CE (2000 + strike/10 for a PE) plus 10 per candle; volume 7 (CE) / 9 (PE)."""

    def __init__(self, strikes=range(1500, 2201, 20), fail=None, skip=(), no_bars=()):
        self.calls, self.fail, self.skip, self.no_bars = [], fail, set(skip), set(no_bars)
        self.meta = {}
        for e, exp in enumerate(EXPIRIES):
            for k in strikes:
                for ty in ("CE", "PE"):
                    tok = 10_000_000 * (e + 1) + k * 10 + (1 if ty == "CE" else 2)
                    self.meta[tok] = {"expiry": exp, "strike": float(k), "type": ty,
                                      "tradingsymbol": f"ADANIPORTS{exp:%y%b}{k}{ty}".upper()}

    def instruments(self, ex):
        self.calls.append(("instruments", ex))
        if ex == "NSE":
            return [{"segment": "NSE", "tradingsymbol": "ADANIPORTS", "instrument_token": 3861249, "instrument_type": "EQ"}]
        rows = [{"instrument_type": m["type"], "name": "ADANIPORTS", "expiry": m["expiry"], "strike": m["strike"],
                 "instrument_token": tok, "tradingsymbol": m["tradingsymbol"], "lot_size": 475} for tok, m in self.meta.items()]
        rows.append({"instrument_type": "FUT", "name": "ADANIPORTS", "expiry": date(2026, 11, 24), "strike": 0.0,
                     "instrument_token": 5, "tradingsymbol": "ADANIPORTS26NOVFUT", "lot_size": 475})
        return rows

    def historical_data_oi(self, token, f, to, interval):
        self.calls.append(("hist_oi", token))
        if self.fail:
            raise self.fail
        m = self.meta[token]
        if m["tradingsymbol"] in self.no_bars:
            return []
        base = (1000 if m["type"] == "CE" else 2000) + m["strike"] / 10
        vol = 7 if m["type"] == "CE" else 9
        stamps = [(23, 15, 15), (26, 9, 15), (26, 9, 30), (27, 9, 15), (27, 9, 30)]
        out = []
        for i, (d, h, mi) in enumerate(stamps):
            if (m["tradingsymbol"], (d, h, mi)) in self.skip:
                continue
            out.append({"date": datetime(2026, 10, d, h, mi, tzinfo=IST), "open": 10, "high": 11, "low": 9, "close": 10.5,
                        "volume": vol, "oi": base + 10 * i})
        return out

    def historical_data(self, token, f, to, interval):
        self.calls.append(("hist", token))
        return [{"date": datetime(2026, 10, 27, 9, 15, tzinfo=IST), "open": 1866, "high": 1874, "low": 1860, "close": 1871.0, "volume": 1000}]


def _opt_svc(kite, token="tok-SECRET", now=datetime(2026, 10, 27, 11, 0, tzinfo=IST)):
    async def nosleep(s):
        return None
    clock = {"now": now}
    svc = it.IntradayService(token_getter=lambda: token, key_getter=lambda: "key", kite_factory=lambda k, tk: kite,
                             clock=lambda: clock["now"], sleep=nosleep)
    svc.test_clock = clock
    return svc


def _ref(price, source="kite_live"):
    async def get(spot):
        get.asked.append(spot)
        return {"price": price, "source": source, "at": "2026-10-27T10:59:58+05:30"}
    get.asked = []
    return get


# ── B1 ATM and strikes ───────────────────────────────────────────────────────

def test_b1_atm_from_the_reference_price_and_five_listed_strikes_each_side():
    k = OptKite()
    ref = _ref(1868.0)
    r = run(_opt_svc(k).options_intraday("adaniports", "15m", 2, 5, ref_getter=ref))
    assert r["availability"] == "ok" and ref.asked == ["ADANIPORTS"]
    assert r["atm"] == 1860.0
    assert r["strikes"] == [1760.0 + 20 * i for i in range(11)]
    assert r["ref"] == {"price": 1868.0, "source": "kite_live", "at": "2026-10-27T10:59:58+05:30"}
    assert len(r["contracts"]) == 22
    assert [(c["strike"], c["type"]) for c in r["contracts"][:4]] == [(1760.0, "CE"), (1760.0, "PE"), (1780.0, "CE"), (1780.0, "PE")]
    assert r["contracts"][0]["tradingsymbol"] == "ADANIPORTS26OCT1760CE"
    assert (r["mode"], r["source"], r["read_only"], r["missing"]) == ("intraday", "Kite intraday (historical, oi)", True, [])
    assert len([c for c in k.calls if c[0] == "hist_oi"]) == 22


def test_b1_an_exact_tie_goes_to_the_lower_strike_and_fewer_listed_strikes_are_said():
    assert foi.pick_strikes([1860, 1880, 1840], 1870.0, 1) == (1860.0, [1840.0, 1860.0, 1880.0])
    k = OptKite(strikes=range(1500, 1901, 20))
    r = run(_opt_svc(k).options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1890.0)))
    assert r["atm"] == 1880.0 and r["strikes"] == [1780.0, 1800.0, 1820.0, 1840.0, 1860.0, 1880.0, 1900.0]
    assert len(r["contracts"]) == 14
    assert "5 strike(s) below and 1 above the ATM strike 1880" in r["note"] and "asked for 5 each side" in r["note"]


def test_b1_without_a_quote_the_last_cash_candle_is_the_reference():
    k = OptKite()

    async def no_quote(spot):
        return None
    r = run(_opt_svc(k).options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=no_quote))
    assert r["ref"] == {"price": 1871.0, "source": "candle", "at": t(27, 9, 15)}
    assert r["atm"] == 1880.0
    assert ("hist", 3861249) in k.calls


# ── B2 the series ────────────────────────────────────────────────────────────

def _c(sym, strike, ty, rows):
    return {"tradingsymbol": sym, "strike": strike, "type": ty,
            "bars": [[ts, 10.0, 11.0, 9.0, 10.5, v, oi] for ts, v, oi in rows]}


def test_b2_sums_changes_pcr_and_a_missing_candle_nulls_that_time():
    t0, t1, t2, t3 = t(26, 15, 15), t(27, 9, 15), t(27, 9, 30), t(27, 9, 45)
    contracts = [
        _c("A100CE", 100.0, "CE", [(t0, 1, 90), (t1, 10, 100), (t2, 5, 110), (t3, 1, 120)]),
        _c("A100PE", 100.0, "PE", [(t0, 1, 210), (t1, 20, 200), (t2, 5, 190), (t3, 2, 230)]),
        _c("B120CE", 120.0, "CE", [(t0, 1, 50), (t1, 3, 50), (t3, 4, 60)]),                      # no candle at t2
        _c("B120PE", 120.0, "PE", [(t0, 1, 70), (t1, 4, 80), (t2, 1, 85), (t3, 1, 90)]),
    ]
    series, days = foi.build_series(contracts, 1)
    assert days == ["2026-10-27"] and [r["t"] for r in series] == [t1, t2, t3]
    r1, r2, r3 = series
    assert r1 == {"t": t1, "ce_oi": 150, "pe_oi": 280, "ce_oi_change": 150 - (90 + 50), "pe_oi_change": 280 - (210 + 70),
                  "ce_volume": 13, "pe_volume": 24, "pcr": round(280 / 150, 4)}
    assert all(r2[k] is None for k in ("ce_oi", "pe_oi", "ce_oi_change", "pe_oi_change", "ce_volume", "pe_volume", "pcr"))
    # the previous row had no sums, so the change after the gap is null too
    assert (r3["ce_oi"], r3["pe_oi"], r3["ce_oi_change"], r3["pe_oi_change"], r3["pcr"]) == (180, 320, None, None, round(320 / 180, 4))


def test_b2_first_row_without_a_baseline_has_null_changes_and_zero_call_oi_has_null_pcr():
    t1 = t(27, 9, 15)
    series, _ = foi.build_series([_c("X", 100.0, "CE", [(t1, 1, 0)]), _c("Y", 100.0, "PE", [(t1, 1, 40)])], 2)
    assert series == [{"t": t1, "ce_oi": 0, "pe_oi": 40, "ce_oi_change": None, "pe_oi_change": None, "ce_volume": 1,
                       "pe_volume": 1, "pcr": None}]


def test_b2_service_series_matches_the_candles_and_lists_missing_contracts():
    k = OptKite(skip={("ADANIPORTS26OCT1860PE", (26, 9, 30))})
    r = run(_opt_svc(k).options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1868.0)))
    s = {row["t"]: row for row in r["series"]}
    assert list(s) == [t(26, 9, 15), t(26, 9, 30), t(27, 9, 15), t(27, 9, 30)]
    strikes = [1760 + 20 * i for i in range(11)]
    ce = lambda i: sum(1000 + k_ / 10 + 10 * i for k_ in strikes)   # noqa: E731
    pe = lambda i: sum(2000 + k_ / 10 + 10 * i for k_ in strikes)   # noqa: E731
    assert s[t(26, 9, 15)]["ce_oi"] == int(ce(1)) and s[t(26, 9, 15)]["ce_oi_change"] == 110   # vs 23 Oct 15:15
    assert s[t(26, 9, 15)]["pcr"] == round(pe(1) / ce(1), 4) and s[t(26, 9, 15)]["ce_volume"] == 77
    assert s[t(26, 9, 30)]["ce_oi"] is None and s[t(26, 9, 30)]["pcr"] is None
    assert s[t(27, 9, 30)]["pe_oi_change"] == 110
    # the contracts carry only the sessions sent
    assert {b[0][:10] for c in r["contracts"] for b in c["bars"]} == {"2026-10-26", "2026-10-27"}
    k2 = OptKite(no_bars={"ADANIPORTS26OCT1960CE"})
    r2 = run(_opt_svc(k2).options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1868.0)))
    assert r2["missing"] == ["ADANIPORTS26OCT1960CE"] and r2["availability"] == "ok"
    assert all(row["ce_oi"] is None for row in r2["series"]) and "1 of 22 contracts" in r2["note"]


# ── B3 no session / Kite failure ─────────────────────────────────────────────

def test_b3_token_missing_reads_nothing():
    k = OptKite()
    r = run(_opt_svc(k, token="").options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1868.0)))
    assert r["availability"] == "token_missing" and k.calls == [] and r["series"] == [] and r["contracts"] == []


@pytest.mark.parametrize("exc,reason", [(TokenException("Incorrect `api_key` or `access_token` tok-SECRET"), "token_expired"),
                                        (RuntimeError("HTTPSConnectionPool host=api.kite.trade tok-SECRET"), "upstream_unavailable")])
def test_b3_kite_failure_says_why_without_the_exception_text(exc, reason):
    svc = _opt_svc(OptKite(fail=exc))
    r = run(svc.options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1868.0)))
    assert r["availability"] == reason and r["series"] == [] and r["read_only"] is True
    text = json.dumps(r)
    assert "tok-SECRET" not in text and "api.kite.trade" not in text and "access_token" not in text
    # a failure is not cached: the next read asks Kite again
    k = OptKite()
    svc.kite_factory = lambda key, tok: k
    assert run(svc.options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1868.0)))["availability"] == "ok"


def test_b3_no_options_listed():
    r = run(_opt_svc(OptKite()).options_intraday("HDFCBANK", "15m", 2, 5, ref_getter=_ref(1868.0)))
    assert r["availability"] == "no_options" and r["contracts"] == [] and r["note"]


# ── B4 nearest unexpired expiry ──────────────────────────────────────────────

def test_b4_expiry_day_after_the_close_still_reads_that_days_contracts_and_the_next_day_moves_on():
    k = OptKite()
    svc = _opt_svc(k, now=datetime(2026, 10, 27, 16, 5, tzinfo=IST))
    r = run(svc.options_intraday("ADANIPORTS", "15m", 2, 5, ref_getter=_ref(1868.0)))
    assert r["expiry"] == "2026-10-27" and r["contracts"][0]["tradingsymbol"].startswith("ADANIPORTS26OCT")
    svc.test_clock["now"] = datetime(2026, 10, 28, 9, 20, tzinfo=IST)
    r = run(svc.options_intraday("ADANIPORTS", "15m", 1, 5, ref_getter=_ref(1868.0)))
    assert r["expiry"] == "2026-11-24" and r["contracts"][0]["tradingsymbol"].startswith("ADANIPORTS26NOV")
    assert [c for c in k.calls if c[0] == "instruments"] == [("instruments", "NFO"), ("instruments", "NFO")]   # re-read on the new day


# ── B5 / B6 the route ────────────────────────────────────────────────────────

def _opt_client(monkeypatch, service, events):
    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    async def refresh():
        events.append("refresh")

    async def ref(spot):
        events.append(f"ref:{spot}")
        return {"price": 1868.0, "source": "kite_close", "at": "2026-10-27T15:29:59+05:30"}

    class Feed:
        async def read_status(self):
            return {"session": "open"}

    import routes.research_chart_intraday as rci
    import services.kite_live_feed.feed as feed_mod
    monkeypatch.setattr(fno_route, "get_current_user", fake_user)
    monkeypatch.setattr(fno_route, "_refresh_platform_token", refresh)
    monkeypatch.setattr(fno_route, "_option_ref", ref)
    monkeypatch.setattr(rci, "get_service", lambda: service)
    monkeypatch.setattr(feed_mod, "get_feed", lambda: Feed())
    app = FastAPI()
    app.include_router(fno_route.router)
    return TestClient(app)


class EventKite(OptKite):
    def __init__(self, events, **kw):
        super().__init__(**kw)
        self.events = events

    def instruments(self, ex):
        self.events.append(f"kite:instruments:{ex}")
        return super().instruments(ex)

    def historical_data_oi(self, token, f, to, interval):
        self.events.append("kite:hist_oi")
        return super().historical_data_oi(token, f, to, interval)


def test_b5_login_reloaded_before_the_kite_read_and_a_cache_hit_reads_nothing(monkeypatch):
    events = []
    svc = _opt_svc(EventKite(events))
    c = _opt_client(monkeypatch, svc, events)
    r = c.get("/api/fno/adaniports/options/intraday?interval=15m&sessions=2&strikes=5")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["availability"] == "ok" and b["ref"]["source"] == "kite_close" and b["expiry"] == "2026-10-27"
    assert events[0] == "refresh" and events[1] == "kite:instruments:NFO" and events.count("kite:hist_oi") == 22
    assert "ref:ADANIPORTS" in events
    n = len(events)
    r2 = c.get("/api/fno/ADANIPORTS/options/intraday?interval=15m&sessions=2&strikes=5")
    assert r2.json() == b
    assert events[n:] == ["refresh"]                                    # reloaded again, no Kite call, no quote read
    c.get("/api/fno/ADANIPORTS/options/intraday?interval=15m&sessions=2&strikes=3")   # another key is its own read
    assert events.count("kite:hist_oi") == 22 + 14


def test_b5_the_cache_expires_after_its_ttl():
    import time as _time
    k = OptKite()
    svc = _opt_svc(k)
    run(svc.options_intraday("ADANIPORTS", "15m", 2, 5, session_open=True, ref_getter=_ref(1868.0)))
    key = ("ADANIPORTS", "15m", 2, "options", 5)
    stamp, body = svc._cache[key]
    svc._cache[key] = (_time.monotonic() - it.CACHE_OPEN_SECONDS - 1, body)
    run(svc.options_intraday("ADANIPORTS", "15m", 2, 5, session_open=True, ref_getter=_ref(1868.0)))
    assert len([c for c in k.calls if c[0] == "hist_oi"]) == 44


def test_b6_bad_interval_400_strikes_out_of_range_422_and_get_only(monkeypatch):
    events = []
    c = _opt_client(monkeypatch, _opt_svc(OptKite()), events)
    assert c.get("/api/fno/ADANIPORTS/options/intraday?interval=1m").status_code == 400
    assert c.get("/api/fno/ADANIPORTS/options/intraday?strikes=9").status_code == 422
    assert c.get("/api/fno/ADANIPORTS/options/intraday?strikes=0").status_code == 422
    assert c.get("/api/fno/ADANIPORTS/options/intraday?sessions=6").status_code == 422
    assert c.post("/api/fno/ADANIPORTS/options/intraday").status_code == 405
    assert events == []                                                  # nothing read for a refused request


def test_option_ref_reads_todays_kite_quote(monkeypatch):
    from services.kite_live_feed import day_quote

    async def dq(symbols, **kw):
        assert symbols == ["NIFTY 50"]
        return {"source": "kite_live", "day": "2026-10-27", "as_of": "2026-10-27T05:30:00+00:00",
                "quotes": {"NIFTY 50": {"ltp": 25871.5, "exchange_ts": "2026-10-27T10:59:58+05:30"}}, "why": None}
    monkeypatch.setattr(day_quote, "day_quotes", dq)
    assert run(fno_route._option_ref("NIFTY 50")) == {"price": 25871.5, "source": "kite_live", "at": "2026-10-27T10:59:58+05:30"}

    async def none(symbols, **kw):
        return {"source": None, "day": "2026-10-27", "as_of": None, "quotes": {}, "why": "feed_not_live"}
    monkeypatch.setattr(day_quote, "day_quotes", none)
    assert run(fno_route._option_ref("ADANIPORTS")) is None
