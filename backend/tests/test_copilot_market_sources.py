"""Copilot market answers: event calendar, global/commodity quotes, trend, F&O positioning, AIF/PMS honesty.

Every payload below is MOCK — not real data; expected values are computed from the payload.
"""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

from services.copilot_tools import daas_client, market_research as mr
from services.positional_engine import nse_live
from tests import market_day

# MOCK — not real data
SNAP = {"as_of_date": "2026-10-19", "nifty50_close": 22889.0, "nifty50_pct_change": -1.11,
        "india_vix": 14.77, "advances_count": 665, "declines_count": 2608, "unchanged_count": 50,
        "fii_cash_net_cr": -1148.64, "dii_cash_net_cr": 900.0, "rbi_10y_yield": 7.37,
        "index_as_of": "2026-10-19", "prices_as_of": "2026-10-19",
        "fii_dii_as_of": "2026-10-19", "yields_as_of": "2026-10-16"}
HOLIDAYS = {"data": [{"holiday_date": "2026-10-20", "segment": "CM", "description": "Dussehra"}]}  # MOCK


def _ev(sym, typ, d, name=None):
    return {"symbol": sym, "company_name": name or sym + " Ltd", "event_type": typ, "event_date": d,
            "period": "Q2 FY26", "purpose": "x", "fetched_at": "2026-10-19T15:00:04+00:00"}


EVENTS = {"data": [  # MOCK
    _ev("ABSLAMC", "quarterly_results", "2026-10-21"),
    _ev("RELIANCE", "quarterly_results", "2026-10-22"),   # a Nifty 50 name
    _ev("TCS", "quarterly_results", "2026-10-23"),        # a Nifty 50 name
    _ev("SMALLCO", "quarterly_results", "2026-10-23"),
    _ev("WEALTH", "other", "2026-10-26"),
    _ev("SATCO", "quarterly_results", "2026-10-24"),      # a Saturday: not a session
    _ev("LATE", "quarterly_results", "2026-10-30"),       # after the 5th session: must not appear
]}
NIFTY50 = {"as_of": "2026-10-13", "data": [  # MOCK
    {"symbol": "RELIANCE"}, {"symbol": "TCS"}, {"symbol": "INFY"}]}
NIFTY50_ROW_DATE = "2026-10-13"

RECENT = {"data": [  # MOCK, newest first, 7 sessions
    {"as_of_date": "2026-10-19", "nifty50_close": 22889.0, "india_vix": 14.77, "fii_cash_net_cr": -1148.64,
     "dii_cash_net_cr": 3201.19, "advances_count": 665, "declines_count": 2608},
    {"as_of_date": "2026-10-16", "nifty50_close": 23146.0, "india_vix": 14.06, "fii_cash_net_cr": 1165.92,
     "dii_cash_net_cr": -3661.28, "advances_count": 1884, "declines_count": 1364},
    {"as_of_date": "2026-10-15", "nifty50_close": 22997.0, "india_vix": 14.03, "fii_cash_net_cr": -5285.37,
     "dii_cash_net_cr": 3319.39, "advances_count": 1158, "declines_count": 2102},
    {"as_of_date": "2026-10-14", "nifty50_close": 22620.0, "india_vix": 14.63, "fii_cash_net_cr": -1857.44,
     "dii_cash_net_cr": 2670.44, "advances_count": 1845, "declines_count": 1419},
    {"as_of_date": "2026-10-13", "nifty50_close": 22800.0, "india_vix": 14.12, "fii_cash_net_cr": -1305.13,
     "dii_cash_net_cr": 2439.24, "advances_count": 1905, "declines_count": 1348},
    {"as_of_date": "2026-10-12", "nifty50_close": 22500.0, "india_vix": 15.25, "fii_cash_net_cr": -1708.48,
     "dii_cash_net_cr": 3045.02, "advances_count": 1583, "declines_count": 1686},
    {"as_of_date": "2026-10-09", "nifty50_close": 22400.0, "india_vix": 14.38, "fii_cash_net_cr": -3568.9,
     "dii_cash_net_cr": 4743.26, "advances_count": 1947, "declines_count": 1292}]}
YIELDS = {"data": [{"as_of_date": "2026-10-09", "tenor": "10Y", "yield_pct": 7.37},  # MOCK
                   {"as_of_date": "2026-10-02", "tenor": "10Y", "yield_pct": 7.23}]}

BUILDUP = {"as_of": "2026-10-19", "counts": {"long_buildup": 15, "short_buildup": 131, "short_covering": 18,  # MOCK
                                             "long_unwinding": 48, "neutral": 1, "no_data": 0},
           "universe": 213,
           "indices": [{"symbol": "BANKNIFTY", "label": "long_unwinding", "price_chg_pct": -0.61, "oi_chg_pct": -1.29,
                        "near_expiry": "2026-10-27"},
                       {"symbol": "NIFTY", "label": "short_buildup", "price_chg_pct": -1.11, "oi_chg_pct": 2.5,
                        "near_expiry": "2026-10-27"}]}
EXPIRIES = {"symbol": "NIFTY", "data": [  # MOCK: the first expires on the data's own day, so the chain uses the next
    {"expiry_date": "2026-10-19", "ce_count": 5, "pe_count": 5, "futures_count": 0, "latest_seen": "2026-10-19"},
    {"expiry_date": "2026-10-27", "ce_count": 5, "pe_count": 5, "futures_count": 0, "latest_seen": "2026-10-19"}]}


def _opt(k, oi, spot=22889.0):
    return {"strike_price": k, "close_price": 10.0, "underlying_price": spot, "open_interest": oi,
            "change_in_oi": 0, "traded_volume": 1}


CHAIN = {"symbol": "NIFTY", "as_of": "2026-10-19", "expiry": "2026-10-27", "strikes": [  # MOCK
    {"strike": 22800.0, "CE": _opt(22800.0, 1000), "PE": _opt(22800.0, 3000)},
    {"strike": 22900.0, "CE": _opt(22900.0, 4000), "PE": _opt(22900.0, 2000)},
    {"strike": 23000.0, "CE": _opt(23000.0, 5000), "PE": _opt(23000.0, 500)}]}

GLOBAL = {"fetched_at": "2026-10-19T23:59:31+05:30",  # MOCK
          "global_cues": [{"name": "USD / INR", "value": 94.92, "change_pct": 0.41},
                          {"name": "US 10Y Treasury", "value": 5.14, "change_pct": 0.82}],
          "global_indices": {"us": [{"name": "S&P 500", "value": 7697.04, "change_pct": 0.49}],
                             "europe": [{"name": "DAX", "value": 25319.77, "change_pct": -1.18}],
                             "asia": [{"name": "Nikkei 225", "value": 65324.29, "change_pct": None}]},
          "commodities": [{"name": "Brent Crude", "value": 109.83, "change_pct": None, "unit": "$/bbl"},
                          {"name": "Gold", "value": 4167.3, "change_pct": None, "unit": "$/oz"}]}


def _routes():
    return {"/snapshots/market": {"data": SNAP}, "/holidays": HOLIDAYS, "/events/calendar": EVENTS,
            "/indices/Nifty 50/constituents": NIFTY50, "/snapshots/market/recent": RECENT,
            "/macro/rbi-yields": YIELDS, "/desk/fno-buildup": BUILDUP,
            "/fno/NIFTY/expiries": EXPIRIES, "/fno/NIFTY/chain": CHAIN,
            "/fno/BANKNIFTY/expiries": EXPIRIES, "/fno/BANKNIFTY/chain": CHAIN}


def _run(monkeypatch, routes, glob=GLOBAL):
    async def fake_get(path, params=None, **kw):
        v = routes.get(path)
        if isinstance(v, Exception):
            raise v
        return v

    async def fake_global():
        if isinstance(glob, Exception):
            raise glob
        return glob
    monkeypatch.setattr(daas_client, "_get", fake_get)
    monkeypatch.setattr(nse_live, "get_global_snapshot", fake_global)
    market_day.pin(monkeypatch, "2026-10-19", "2026-10-16")   # the fixtures' Monday; the previous session is Friday
    return asyncio.run(mr.get_market_research())


# ── event calendar ──────────────────────────────────────────────────────────────

def test_next_sessions_skip_holiday_and_weekend():
    # 2026-10-19 is a Monday; the 20th is the holiday; 24-25 are the weekend.
    sessions = mr.next_sessions("2026-10-19", {"2026-10-20"}, 5)
    assert sessions == ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"]
    assert date.fromisoformat(sessions[0]) - date.fromisoformat("2026-10-19") == timedelta(days=2)


def test_calendar_block_lists_window_nifty50_and_holiday(monkeypatch):
    res = _run(monkeypatch, _routes())
    cal = res.widget["calendar"]
    assert cal["sessions"] == ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"]
    assert cal["holidays"] == [{"date": "2026-10-20", "description": "Dussehra"}]
    s = res.summary
    assert "event calendar" in s and "2026-10-21, 2026-10-22, 2026-10-23, 2026-10-26, 2026-10-27" in s
    assert "2026-10-20 Dussehra is an NSE holiday" in s
    assert "[scheduled, as of 2026-10-19]" in s
    # Nifty 50 names reporting, with their dates and the membership list's own date
    assert "Nifty 50 companies reporting: RELIANCE 2026-10-22, TCS 2026-10-23" in s
    assert f"Nifty 50 list dated {NIFTY50_ROW_DATE}" in s
    # per-session result counts computed from the payload
    assert "2026-10-23: 2 results" in s
    # the 24th is a Saturday: named as a non-session date, not counted as a session
    assert "2026-10-24 (not a session): 1 results" in s
    assert "LATE" not in s and "2026-10-30" not in s


def test_calendar_without_holiday_list_is_unavailable_not_weekdays(monkeypatch):
    r = _routes()
    r["/holidays"] = daas_client.DaasError("DAAS /holidays returned HTTP 500")
    res = _run(monkeypatch, r)
    assert "event calendar unavailable: NSE holiday list: DAAS /holidays returned HTTP 500" in res.summary
    assert "2026-10-21" not in res.widget["calendar"].get("sessions", [])


def test_calendar_events_failure_is_explicit(monkeypatch):
    r = _routes()
    r["/events/calendar"] = daas_client.DaasError("DAAS /events/calendar returned HTTP 500")
    res = _run(monkeypatch, r)
    assert "event calendar unavailable: DAAS /events/calendar returned HTTP 500" in res.summary


def test_nifty50_list_failure_keeps_calendar_and_says_so(monkeypatch):
    r = _routes()
    r["/indices/Nifty 50/constituents"] = None
    res = _run(monkeypatch, r)
    assert "2026-10-23: 2 results" in res.summary
    assert "Nifty 50 membership unavailable" in res.summary


# ── global markets, currency, commodities ───────────────────────────────────────

def test_global_block_has_quotes_and_vendor_label(monkeypatch):
    s = _run(monkeypatch, _routes()).summary
    assert "S&P 500 7,697 (+0.49%)" in s and "DAX 25,320 (-1.18%)" in s
    assert "Nikkei 225 65,324 (change n/a)" in s
    assert "USD/INR 94.92 (+0.41%)" in s and "US 10Y Treasury 5.14% (+0.82%)" in s
    assert "Brent Crude 109.83 $/bbl" in s and "Gold 4,167.30 $/oz" in s
    assert "[vendor quote (Yahoo Finance), last daily close, fetched 2026-10-19]" in s


def test_global_block_names_missing_assets(monkeypatch):
    g = dict(GLOBAL, commodities=[GLOBAL["commodities"][0]])
    s = _run(monkeypatch, _routes(), glob=g).summary
    assert "not in the vendor feed: Gold" in s


def test_global_failure_is_explicit(monkeypatch):
    s = _run(monkeypatch, _routes(), glob=RuntimeError("yahoo down")).summary
    assert "global markets unavailable: yahoo down" in s
    s2 = _run(monkeypatch, _routes(), glob=None).summary
    assert "global markets unavailable: the vendor quote fetch returned nothing" in s2


# ── trend ───────────────────────────────────────────────────────────────────────

def test_trend_five_session_change_from_history(monkeypatch):
    res = _run(monkeypatch, _routes())
    s = res.summary
    old, new = RECENT["data"][5], RECENT["data"][0]       # 5 sessions earlier vs latest
    last5 = RECENT["data"][:5]
    fii = sum(r["fii_cash_net_cr"] for r in last5)
    assert "5-session trend" in s and "2026-10-12 to 2026-10-19" in s
    assert f"India VIX {old['india_vix']} to {new['india_vix']}" in s
    assert f"advances {old['advances_count']} to {new['advances_count']}" in s
    assert f"FII net over the 5 sessions ₹{fii:,.0f}cr" in s
    assert "Nifty 50 +1.7%" in s  # 22889 / 22500 - 1
    # the 10Y comes from its own (weekly) series, with its dates, not a 5-session claim
    assert "10Y G-Sec 7.37% (2026-10-09) vs 7.23% (2026-10-02), change +0.14 pts" in s


def test_trend_with_too_little_history_says_so(monkeypatch):
    r = _routes()
    r["/snapshots/market/recent"] = {"data": RECENT["data"][:3]}
    s = _run(monkeypatch, r).summary
    assert "trend unavailable: only 3 sessions of history" in s


def test_trend_failure_is_explicit(monkeypatch):
    r = _routes()
    r["/snapshots/market/recent"] = daas_client.DaasError("DAAS /snapshots/market/recent returned HTTP 500")
    assert "trend unavailable: DAAS /snapshots/market/recent returned HTTP 500" in _run(monkeypatch, r).summary


# ── F&O ─────────────────────────────────────────────────────────────────────────

def test_fno_block_index_futures_pcr_max_pain(monkeypatch):
    res = _run(monkeypatch, _routes())
    s = res.summary
    call, put = 1000 + 4000 + 5000, 3000 + 2000 + 500
    assert "F&O positioning [end of day, as of 2026-10-19]" in s
    assert "NIFTY futures short_buildup (price -1.11%, OI +2.50%)" in s
    assert "BANKNIFTY futures long_unwinding (price -0.61%, OI -1.29%)" in s
    assert "stock futures build-up over 213 underlyings: short_buildup 131" in s
    assert f"NIFTY options expiry 2026-10-27: PCR {put / call:.2f}" in s
    # max pain by hand: payout(K) = sum c*max(K-k,0) + p*max(k-K,0); K=22900 is the minimum of the three strikes
    assert "max pain 22900" in s
    assert res.widget["fno"]["options"]["NIFTY"]["expiry"] == "2026-10-27"


def test_fno_option_failure_keeps_futures_and_says_so(monkeypatch):
    r = _routes()
    r["/fno/NIFTY/chain"] = daas_client.DaasError("DAAS /fno/NIFTY/chain returned HTTP 500")
    s = _run(monkeypatch, r).summary
    assert "NIFTY futures short_buildup" in s
    assert "NIFTY option OI/PCR unavailable: DAAS /fno/NIFTY/chain returned HTTP 500" in s


def test_fno_buildup_failure_is_explicit(monkeypatch):
    r = _routes()
    r["/desk/fno-buildup"] = None
    assert "F&O futures build-up unavailable: the fno-buildup route was not found (HTTP 404)" in _run(monkeypatch, r).summary


# ── AIF / PMS ───────────────────────────────────────────────────────────────────

def test_aif_pms_is_stated_not_invented(monkeypatch):
    res = _run(monkeypatch, _routes())
    assert "AIF/PMS data: not available (no AIF or PMS source exists in the data platform)" in res.summary
    assert res.widget["aif_pms"]["available"] is False


# ── prompt ──────────────────────────────────────────────────────────────────────

def test_prompt_contains_new_blocks_and_rules(monkeypatch):
    from nidp.services.copilot_agent.nodes import market as node
    from nidp.services.copilot_agent import _stream
    captured = {}

    class FakeLLM:
        async def ainvoke(self, msgs):
            captured["system"] = msgs[0]["content"]
            return SimpleNamespace(content="ok")

    async def noop(*a, **k):
        return None

    async def fake_get(path, params=None, **kw):
        return _routes().get(path)

    async def fake_global():
        return GLOBAL
    monkeypatch.setattr(daas_client, "_get", fake_get)
    monkeypatch.setattr(nse_live, "get_global_snapshot", fake_global)
    market_day.pin(monkeypatch, "2026-10-19", "2026-10-16")
    monkeypatch.setattr(node, "make_chat_llm", lambda t: FakeLLM())
    monkeypatch.setattr(_stream, "emit_widget", noop)
    state = SimpleNamespace(messages=[SimpleNamespace(type="human", content="Key market risks this week?")],
                            persona=None, desk_persona="trader")
    asyncio.run(node.market_node(state))
    sp = captured["system"]
    for needle in ("event calendar", "Nifty 50 companies reporting", "global markets", "USD/INR",
                   "5-session trend", "F&O positioning", "AIF/PMS data: not available"):
        assert needle in sp
    # the instructions
    assert "calendar entries are facts" in sp and "your read of risk is interpretation" in sp
    assert "which blocks are missing" in sp
    assert "never invent" in sp.lower() or "do not invent" in sp.lower()
    # the old blanket claim that global markets / commodities are missing is gone
    assert "(e.g. global markets, commodities)" not in sp
