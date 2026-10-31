"""The Copilot's visual answer (services/copilot_visual; contract docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md).

Covers R-1 … R-10, B-1 … B-13, C-1, F-1 of test_reports/dtc_visual_backend_20261030.md (CH-* are in
tests/test_copilot_visual_chat.py; C-2 checks the REAL staging capture).

What is replaced (MOCK — not real data; every symbol, level and figure below is invented): the readers in
services/copilot_visual/readers.py (each existing route / DaaS read) and the freshness window. The resolver, the
builders, the EMA (the feature engine's own), the contract check and the facts block run for real.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import market_freshness
from services.copilot_visual import builders, readers as rd
from services.copilot_visual.intents import Intent, last_symbol_from, resolve_intent, stock_in, wants_thread_symbol
from services.copilot_visual.payload import facts, validate

TODAY, FLOOR = date(2026, 10, 30), date(2026, 10, 29)
WINDOW = market_freshness.Window(today=TODAY, floor=FLOOR, calendar_checked=True)


# ── R-1 … R-9: the resolver ──────────────────────────────────────────────────
@pytest.mark.parametrize("message, persona, expected", [
    ("What is the market view today?", "trader", ("market_view", None)),
    ("Is the market trending?", None, ("market_view", None)),
    ("What is the Nifty and Bank Nifty view for today?", "trader", ("market_view", None)),
    ("Where is smart money moving?", "trader", ("smart_money", None)),
    ("FII DII flows this week", None, ("smart_money", None)),
    ("Which F&O stocks show long build-up today?", "trader", ("smart_money", None)),
    ("Which are today's top 5 opportunities?", "trader", ("top_opportunities", None)),
    ("Top 10 trade ideas today", None, ("top_opportunities", None)),
    ("Which breakouts are confirmed?", "trader", ("breakouts", None)),
    ("Stocks breaking out today", None, ("breakouts", None)),
    ("Which stocks have unusual volume?", "trader", ("unusual_volume", None)),
    ("volume spike stocks", None, ("unusual_volume", None)),
    ("Is RELIANCE a buy now?", "trader", ("stock_decision", "RELIANCE")),
    ("What is the entry, target and stop-loss for INFY?", None, ("stock_decision", "INFY")),
    ("entry and SL for infy", "investor", ("stock_decision", "INFY")),
    ("Trade plan for TVSMOTOR", None, ("stock_decision", "TVSMOTOR")),
    ("Is the TCS breakout confirmed?", None, ("stock_decision", "TCS")),
    ("What is the expected move in Nifty?", "trader", ("expected_move", "NIFTY")),
    ("Bank Nifty expected move this week", None, ("expected_move", "BANKNIFTY")),
    ("NIFTY PCR and max pain", "trader", ("expected_move", "NIFTY")),
    ("What is the PCR?", "trader", ("expected_move", "NIFTY")),
])
def test_r1_r8_the_seven_intents(message, persona, expected):
    got = resolve_intent(message, persona, None)
    assert got is not None, message
    assert (got.name, got.symbol) == expected


def test_r3_top_n_is_read_and_capped():
    assert resolve_intent("Today's top 5 opportunities").params == {"n": 5}
    assert resolve_intent("top 10 trade ideas today").params == {"n": 10}
    assert resolve_intent("top 25 stocks today").params == {"n": 10}
    assert resolve_intent("best trading opportunities today").params == {"n": 5}


@pytest.mark.parametrize("message, persona", [
    ("What are my open trades doing?", "trader"),
    ("Which F&O setups are attractive?", "trader"),
    ("Should I book profits or hold TCS?", "trader"),
    ("Show the FIXCO chart", "trader"),
    ("Tell me about TVSMOTOR", "trader"),
    ("How much should I risk?", "trader"),
    ("What should I avoid today?", "trader"),
    ("What did I learn from today's trades?", "trader"),
    ("Is RELIANCE a buy now?", "investor"),              # buy-now words are a trader's question only
    ("What is the expected move in RELIANCE?", "trader"),  # Release 1: indices only
    ("Top gainers today", None),
    ("Is this stock a buy now?", "trader"),             # no thread stock: nothing to answer about
    ("", None),
])
def test_r9_questions_that_are_not_ours_take_the_usual_path(message, persona):
    assert resolve_intent(message, persona, None) is None


@pytest.mark.parametrize("message", ["What is the PCR of F&O?", "P&L of GIFT", "ATM IV and OI", "VIX entry", "NIFTY target",
                                     "BANKNIFTY stop-loss", "SENSEX entry"])
def test_r9_market_and_fo_words_are_never_a_stock(message):
    assert stock_in(message) is None
    got = resolve_intent(message, "trader", None)
    assert got is None or got.name != "stock_decision"


def test_r7_this_stock_uses_the_threads_stock():
    assert wants_thread_symbol("Is this stock a buy now?", "trader")
    assert wants_thread_symbol("What is the entry, target and stop-loss?", None)
    assert not wants_thread_symbol("Is RELIANCE a buy now?", "trader")
    assert not wants_thread_symbol("Which breakouts are confirmed?", "trader")
    got = resolve_intent("Is this stock a buy now?", "trader", None, last_symbol="TVSMOTOR")
    assert (got.name, got.symbol, got.symbol_from_thread) == ("stock_decision", "TVSMOTOR", True)
    got = resolve_intent("What is the entry, target and stop-loss?", None, None, last_symbol="INFY")
    assert (got.name, got.symbol) == ("stock_decision", "INFY")
    assert resolve_intent("Which breakouts are confirmed?", "trader", None, last_symbol="INFY").name == "breakouts"
    assert resolve_intent("Is this stock a buy now?", "trader", None, last_symbol="NIFTY") is None


def test_r10_last_symbol_from_the_thread():
    msgs = [  # newest first
        {"role": "assistant", "content": "…", "widget": {"widget_type": "visual_answer", "data": {
            "intent": "stock_decision", "blocks": [{"type": "kpis"}, {"type": "candles", "symbol": "TVSMOTOR"}]}}},
        {"role": "user", "content": "Is RELIANCE a buy now?"},
    ]
    assert last_symbol_from(msgs) == "TVSMOTOR"
    assert last_symbol_from([{"role": "assistant", "widget": {"widget_type": "trade_plan", "data": {"symbol": "SBIN"}}}]) == "SBIN"
    assert last_symbol_from([{"role": "assistant", "content": "x"}, {"role": "user", "content": "Trade plan for INFY"}]) == "INFY"
    assert last_symbol_from([{"role": "user", "content": "What is the market view today?"}]) is None
    assert last_symbol_from([]) is None


# ── MOCK sources ─────────────────────────────────────────────────────────────
def sessions(n, end=FLOOR):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def index_rows(n, start=20000.0, end=FLOOR):
    rows = []
    for i, d in enumerate(sessions(n, end)):
        c = start + i * 5
        rows.append({"as_of_date": d.isoformat(), "open_price": c - 3, "high_price": c + 10, "low_price": c - 12,
                     "close_price": c, "pct_change": 0.5 if i % 2 else -0.25})
    return rows


def bars(n, start=1000.0, end=FLOOR):
    return [[d.isoformat(), start + i - 1, start + i + 4, start + i - 5, start + i, 100000 + i] for i, d in enumerate(sessions(n, end))]


CHAIN = {"summary": {"as_of": "2026-10-29", "expiry": "2026-11-04", "days_to_expiry": 6, "spot": 21300.0, "atm_strike": 21300,
                     "atm_iv": 13.4, "expected_move": 310.5, "expected_move_pct": 1.46, "pcr": 0.97, "max_pain": 21200,
                     "call_wall": {"strike": 21500, "oi": 9}, "put_wall": {"strike": 21000, "oi": 8}}}
SNAP = {"as_of_date": "2026-10-29", "prices_as_of": "2026-10-29", "advances_count": 2000, "declines_count": 1100,
        "unchanged_count": 100, "fii_cash_net_cr": -943.6, "dii_cash_net_cr": 1924.41, "fii_dii_as_of": "2026-10-29"}
SECTORS = {"as_of": "2026-10-29", "sectors": [{"sector": "IT", "index": "Nifty IT", "ret_1d_pct": 1.2, "ret_1w_pct": 2.5, "ret_1m_pct": -1},
                                              {"sector": "Bank", "index": "Nifty Bank", "ret_1d_pct": -0.4, "ret_1w_pct": 0.3, "ret_1m_pct": 4}]}
FLOWS = {"as_of": "2026-10-29", "daily": [{"date": d.isoformat(), "fii_net": -100.0 - i, "dii_net": 200.0 + i}
                                          for i, d in enumerate(reversed(sessions(12)))]}
BUILDUP = {"as_of": "2026-10-29", "universe": 3, "counts": {"long_buildup": 1, "short_buildup": 1, "short_covering": 1, "long_unwinding": 0},
           "rows": [{"symbol": "AAA", "label": "long_buildup", "price_chg_pct": 2.0, "oi_chg_pct": 9.0},
                    {"symbol": "BBB", "label": "short_buildup", "price_chg_pct": -1.0, "oi_chg_pct": 5.0},
                    {"symbol": "CCC", "label": "short_covering", "price_chg_pct": 3.0, "oi_chg_pct": -4.0},
                    {"symbol": "DDD", "label": None, "price_chg_pct": None, "oi_chg_pct": 1.0}],
           "indices": [{"symbol": "NIFTY", "label": "long_buildup", "price_chg_pct": 1.0, "oi_chg_pct": 2.0}]}
REGIME = {"key": "bullish", "label": "Bullish", "date": "2026-10-29", "rule": {"version": "desk-regime-v1"}}


def tplan(pid="tp_mock_1"):
    return {"plan_id": pid, "entry": {"price": 1840.0, "order_type": "stop_trigger", "valid_for_sessions": 3, "logic": "MOCK: a close above 1,840"},
            "stop": {"price": 1790.0, "method": "structural", "invalidation": "MOCK: a close below the base"},
            "targets": [{"name": "t1", "price": 1940.0, "r_multiple": 2.0, "primary": True}],
            "evidence": {"items": [{"key": "trend", "label": "Trend", "status": "ok", "direction": "supports", "text": "MOCK above the 50-day"},
                                   {"key": "vol", "label": "Volume", "status": "ok", "direction": "conflicts", "text": "MOCK volume light"}]},
            "warnings": [{"key": "event", "label": "Event", "status": "flagged", "text": "MOCK results in 4 sessions"}]}


def splan(status, with_tp=True):
    return {"status": status, "preferred": "c1" if status == "plan" else None,
            "status_reasons": [] if status == "plan" else [{"code": "x", "message": f"MOCK reason {status}"}],
            "would_change_if": [] if status == "plan" else ["MOCK: a close above 1,840 on 1.5× volume"],
            "data_as_of": {"price": "2026-10-29"},
            "candidates": [{"id": "c1", "status": "candidate", "trade_plan": tplan() if with_tp else None}]}


WATCH_DAY = {"list_date": "2026-10-29", "notes": {"cash_ranking": "MOCK: a rules score, not a probability."},
             "cash": [{"rank": i, "symbol": f"S{i}", "trade_plan_id": f"tp_s{i}", "trade_plan": tplan(f"tp_s{i}"),
                       "plan_status": "plan" if i % 2 else "wait", "scanner": {"bucket": "breakout_confirmed", "score": 0.8 - i / 100}}
                      for i in range(1, 11)]}
WATCHLIST = {"as_of_date": "2026-10-29", "buckets": {"breakout_confirmed": [
    {"nse_symbol": "LT", "trigger_price": 1050.0, "close_price": 1060.0, "stop_price": 1020.0, "price_basis": "raw",
     "signals": {"volume_spike_3v20": 2.1, "dist_breakout_pct": 0.95}}]}}


def scan_row(sym, z, rvol, close=100.0, prev=95.0, day="2026-10-29"):
    return {"symbol": sym, "as_of_date": day, "price_date": day, "close": close, "close_price": close, "prev_close": prev,
            "vol_z20": z, "rvol20": rvol, "traded_value_cr_20d": 50.0, "series": "EQ", "has_reference": True, "price_band_pct": 20.0,
            "high_price": close + 5, "low_price": close - 5, "is_etf": False, "atr_pct": 2.5, "fno_eligible": False}


class Src:
    """Every reader, replaced. `fail` names readers that raise; values replace their answers."""

    def __init__(self, mp):
        self.fail = set()
        self.v = {"market_snapshot": SNAP, "nifty": index_rows(260), "bank": index_rows(2, 50000), "vix": index_rows(2, 15),
                  "sector_returns": SECTORS, "chain": CHAIN, "fii_dii": FLOWS, "buildup": BUILDUP, "regime": REGIME,
                  "watchlist_day": WATCH_DAY, "positional_watchlist": WATCHLIST,
                  "scan_snapshot": {"as_of": "2026-10-29", "rows": [scan_row("UV1", 4.0, 3.2), scan_row("UV2", 2.5, 2.1, 90, 92),
                                                                    scan_row("LOW", 1.0, 1.1)]},
                  "delivery": {"as_of_date": "2026-10-28", "deliverable_pct": 45.5}, "bars": bars(300)}
        self.calls = []

        def make(name, key=None):
            async def f(*a, **k):
                self.calls.append((name, a))
                if name in self.fail:
                    raise RuntimeError(f"MOCK {name} down")
                return self.v[key or name]
            return f

        async def idx(name, limit):
            self.calls.append(("index_rows", (name,)))
            key = {"Nifty 50": "nifty", "Nifty Bank": "bank", "India VIX": "vix"}[name]
            if key in self.fail:
                raise RuntimeError(f"MOCK {name} down")
            return self.v[key]

        async def window():
            return WINDOW
        for name in ("market_snapshot", "sector_returns", "chain", "fii_dii", "buildup", "regime", "watchlist_day",
                     "positional_watchlist", "scan_snapshot"):
            mp.setattr(rd, name, make(name))
        mp.setattr(rd, "delivery_latest", make("delivery_latest", "delivery"))
        mp.setattr(rd, "stock_bars", make("stock_bars", "bars"))
        mp.setattr(rd, "index_rows", idx)
        mp.setattr(rd, "window", window)


@pytest.fixture
def src(monkeypatch):
    return Src(monkeypatch)


def build(name, symbol=None, params=None, **kw):
    p = asyncio.run(builders.build(Intent(name, symbol=symbol, params=params or {}), {"user_id": "u1"}, request="REQ", **kw))
    assert validate(p) == [], validate(p)                                                   # C-1, every payload
    return p


def blocks(p, t):
    return [b for b in p["blocks"] if b["type"] == t]


# ── B-1 / B-2: market_view ───────────────────────────────────────────────────
def test_b1_market_view_from_fresh_sources(src):
    p = build("market_view")
    assert p["as_of"] == "2026-10-29" and p["mode"] == "eod" and p["decision"] is None
    labels = [i["label"] for i in blocks(p, "kpis")[0]["items"]]
    assert labels == ["Nifty 50", "Bank Nifty", "India VIX", "Breadth", "FII cash", "DII cash", "Regime"]
    fii = next(i for i in blocks(p, "kpis")[0]["items"] if i["label"] == "FII cash")
    assert fii["value"] == "−₹943.60 Cr" and fii["tone"] == "down"
    c = blocks(p, "candles")[0]
    assert c["symbol"] == "NIFTY" and len(c["bars"]) == 60 and len(c["overlays"]["ema20"]) == 60
    assert {lv["kind"] for lv in c["levels"]} == {"wall_call", "wall_put", "max_pain"}
    assert c["band"] == {"low": 20989.5, "high": 21610.5, "label": "Expected move to 4 Nov 2026 (ATM straddle ±310.50)"}
    assert [x["label"] for x in blocks(p, "heatmap")[0]["cells"]] == ["IT", "Bank"]
    assert "62% of stocks advanced" in p["headline"]["text"]        # 2000 / 3200
    assert p["data_quality"]["stale"] is False and p["data_quality"]["missing"] == [] and not blocks(p, "notice")
    assert p["caveat"].startswith("Built from end-of-day data of 29 Oct 2026.")


def test_b2_market_view_missing_chain_and_stale_sectors(src):
    src.fail.add("chain")
    src.v["sector_returns"] = {**SECTORS, "as_of": "2026-10-27"}
    p = build("market_view")
    c = blocks(p, "candles")[0]
    assert c["levels"] == [] and c["band"] is None                                          # nothing invented
    assert any("option chain" in m for m in p["data_quality"]["missing"])
    assert p["data_quality"]["stale"] is True
    texts = [n["text"] for n in blocks(p, "notice")]
    assert any("27 Oct 2026, older than the previous session (29 Oct 2026)" in t for t in texts)
    assert any("not available" in t for t in texts)
    assert p["blocks"][0]["type"] == "notice"                                               # the reader sees it first


# ── B-3 / B-4: smart_money ───────────────────────────────────────────────────
def test_b3_smart_money(src):
    p = build("smart_money")
    fii, dii = [b for b in blocks(p, "bars")]
    assert fii["id"] == "fii" and len(fii["items"]) == 10 and fii["items"][-1]["label"] == "29 Oct"
    assert fii["items"][-1]["value"] == -100.0 and dii["items"][-1]["value"] == 200.0      # newest last, as the rows say
    q = blocks(p, "quadrant")[0]
    assert [pt["label"] for pt in q["points"]] == ["AAA", "BBB", "CCC"]                     # a row without a label is left out
    r = blocks(p, "ranked")[0]
    assert [row["symbol"] for row in r["rows"]] == ["AAA", "CCC"] and r["rows"][0]["ask"] == "Trade plan for AAA"
    assert blocks(p, "heatmap")[0]["cells"][0]["label"] == "IT"
    assert "FIIs sold a net ₹100.00 Cr" in p["headline"]["text"]


def test_b4_smart_money_missing_flows_and_refused_buildup(src, monkeypatch):
    from fastapi import HTTPException

    async def stale():
        raise HTTPException(status_code=404, detail="No current data for the F&O build-up scan")
    src.fail.add("fii_dii")
    monkeypatch.setattr(rd, "buildup", stale)
    p = build("smart_money")
    assert not blocks(p, "bars") and not blocks(p, "quadrant")
    assert len(p["data_quality"]["missing"]) == 2 and blocks(p, "heatmap")


# ── B-5 / B-6: top_opportunities ─────────────────────────────────────────────
def test_b5_top_opportunities(src):
    p = build("top_opportunities", params={"n": 5})
    r = blocks(p, "ranked")[0]
    assert [row["symbol"] for row in r["rows"]] == ["S1", "S2", "S3", "S4", "S5"]
    assert [row["plan_id"] for row in r["rows"]][:2] == ["tp_s1", "tp_s2"]
    assert r["rows"][0]["cells"] == {"rank": 1, "symbol": "S1", "setup": "Breakout", "status": "Setup ready", "entry": 1840.0,
                                     "stop": 1790.0, "target": 1940.0, "rr": 2.0, "score": 0.79}
    assert blocks(p, "trade_plan")[0]["plan_id"] == "tp_s1"
    assert p["headline"]["text"] == "3 of the scanner's top 5 on 29 Oct have a setup with levels; 2 wait for confirmation."


def test_b6_no_stored_list_and_a_stale_list(src):
    src.v["watchlist_day"] = None
    p = build("top_opportunities", params={"n": 5})
    assert not blocks(p, "ranked") and "no list is stored yet" in p["data_quality"]["missing"][0]
    src.v["watchlist_day"] = {**WATCH_DAY, "list_date": "2026-10-26"}
    p = build("top_opportunities", params={"n": 3})
    assert p["data_quality"]["stale"] is True and len(blocks(p, "ranked")[0]["rows"]) == 3


# ── B-7 / B-8: breakouts ─────────────────────────────────────────────────────
def test_b7_breakouts(src):
    p = build("breakouts")
    r = blocks(p, "ranked")[0]
    assert r["rows"][0]["cells"] == {"symbol": "LT", "level": 1050.0, "close": 1060.0, "above": 0.95, "volx": 2.1, "stop": 1020.0}
    c = blocks(p, "candles")[0]
    assert c["symbol"] == "LT" and [lv["kind"] for lv in c["levels"]] == ["resistance", "stop"]
    assert blocks(p, "bars")[0]["items"] == [{"label": "LT", "value": 2.1, "tone": "up", "sub": None}]
    assert p["follow_ups"][0]["query"] == "Entry, target and stop-loss for LT"


def test_b8_empty_bucket_says_so(src):
    src.v["positional_watchlist"] = {"as_of_date": "2026-10-29", "buckets": {"breakout_confirmed": []}}
    p = build("breakouts")
    assert not blocks(p, "ranked") and "No stock met the confirmed-breakout rule on 29 Oct 2026" in blocks(p, "notice")[0]["text"]
    assert p["headline"] is None


# ── B-9: unusual_volume ──────────────────────────────────────────────────────
def test_b9_unusual_volume(src):
    p = build("unusual_volume")
    b = blocks(p, "bars")[0]
    assert [i["label"] for i in b["items"]] == ["UV1", "UV2"] and b["items"][0]["value"] == 3.2   # LOW (z 1.0) is not unusual
    r = blocks(p, "ranked")[0]
    assert r["rows"][0]["cells"] == {"symbol": "UV1", "close": 100.0, "chg": 5.26, "rvol": 3.2, "deliv": "45.50%"}
    assert r["columns"][-1]["label"] == "Delivery % (28 Oct)"
    dq = {s["name"]: s["status"] for s in p["data_quality"]["sources"]}
    assert dq["NSE delivery (nidp.delivery_data)"] == "stale" and p["data_quality"]["stale"] is True


# ── B-10 / B-11: stock_decision ──────────────────────────────────────────────
@pytest.mark.parametrize("status, decided, label", [("plan", "setup_ready", "Setup ready"), ("wait", "wait", "Wait"),
                                                    ("no_trade", "avoid", "Avoid"), ("insufficient_data", "no_setup", "No setup yet")])
def test_b10_stock_decision_status_comes_from_the_plan(src, status, decided, label):
    idea = SimpleNamespace(plan=splan(status), widget=None,
                           sized={"status": "sized", "quantity": 12, "unit": "shares", "estimated_risk_rs": {"total": 640.5},
                                  "risk_pct_of_equity": 0.64})
    p = build("stock_decision", "TVSMOTOR", message="Is TVSMOTOR a buy now?", trade_idea=idea)
    d = p["decision"]
    assert (d["status"], d["label"]) == (decided, label)
    if decided in ("setup_ready", "wait"):
        assert d["plan_id"] == "tp_mock_1" and blocks(p, "trade_plan")[0]["plan_id"] == "tp_mock_1"
        c = blocks(p, "candles")[0]
        assert [lv["kind"] for lv in c["levels"]] == ["entry", "stop", "target"] and set(c["overlays"]) == {"ema20", "ema50", "ema200"}
        k = {i["label"]: i["value"] for i in blocks(p, "kpis")[0]["items"]}
        assert k == {"Entry": "₹1,840.00", "Stop": "₹1,790.00", "First target": "₹1,940.00",
                     "Reward:risk": "2.0×", "Size": "12 shares", "Max loss": "₹640.50"}
        assert d["invalidation"] == "MOCK: a close below the base (₹1,790.00)"
        assert {"text": "Trend: MOCK above the 50-day", "met": True} in d["conditions"]
    else:
        assert d["plan_id"] is None and not blocks(p, "trade_plan") and not blocks(p, "candles")[0]["levels"]
        assert f"MOCK reason {status}" in d["reason"]
    assert not any(n["id"] == "assumed" for n in blocks(p, "notice"))                         # "buy" states the side


def test_b10_the_plan_is_built_once_when_not_handed_over(src, monkeypatch):
    calls = []

    async def ti(request, user_id, symbol, message):
        calls.append((user_id, symbol))
        return SimpleNamespace(plan=splan("wait"), widget=None, sized=None)
    monkeypatch.setattr(rd, "trade_idea", ti)
    p = build("stock_decision", "TVSMOTOR", message="Trade plan for TVSMOTOR")
    assert calls == [("u1", "TVSMOTOR")] and p["decision"]["status"] == "wait"
    assert any(n["id"] == "assumed" for n in blocks(p, "notice"))                             # direction not said


def test_b10_an_option_plan_shows_its_net_premium_and_no_entry_line(src):
    plan = splan("plan")
    tp = plan["candidates"][0]["trade_plan"]
    tp["entry"] = {"price": None, "net_premium_rs": 12617.5, "order_type": "at_premium", "order_text": "MOCK every leg at its close",
                   "logic": "MOCK recorded at the legs' premiums"}
    tp["stop"] = {"price": 842.95, "method": "underlying", "invalidation": "MOCK the thesis is wrong beyond this level"}
    tp["strategy"] = {"segment": "options", "label": "Covered call (MOCK)"}
    plan["would_change_if"] = ["MOCK: about another candidate"]
    p = build("stock_decision", "PNB", message="Is PNB a buy now?",
              trade_idea=SimpleNamespace(plan=plan, widget=None, sized={"status": "not_sizable"}))
    d = p["decision"]
    assert d["reason"] == "Covered call (MOCK): net premium ₹12,617.50, stop ₹842.95 (underlying)."
    assert all("another candidate" not in c["text"] for c in d["conditions"])          # a setup is not "waiting" on them
    assert "entry None" not in p["headline"]["text"] and "net premium ₹12,617.50" in p["headline"]["text"]
    k = {i["label"]: i["value"] for i in blocks(p, "kpis")[0]["items"]}
    assert k["Net premium"] == "₹12,617.50" and "Entry" not in k and k["Strategy"] == "Covered call (MOCK)"
    assert [lv["kind"] for lv in blocks(p, "candles")[0]["levels"]] == ["stop", "target"]
    assert "Account sizing: the risk service would refuse this plan on your account (not_sizable)" in p["data_quality"]["missing"]
    # The refusal is shown where the decision is read: an unmet condition and a notice pointing to the plan card.
    assert d["conditions"][-1] == {"text": "Fits your risk limits", "met": False}
    n = blocks(p, "notice")
    assert n and n[0]["tone"] == "warn" and n[0]["text"].startswith("Your risk limits would not allow this plan on your account.")


def test_b10b_the_limits_message_is_carried_into_the_decision(src):
    plan = splan("plan")
    p = build("stock_decision", "PNB", message="Is PNB a buy now?",
              trade_idea=SimpleNamespace(plan=plan, widget=None, sized={"status": "not_sizable", "blocking": [{"code": "min_qty_exceeds_budget", "message": "MOCK: one share risks more than your limit"}]}))
    assert p["decision"]["conditions"][-1] == {"text": "Fits your risk limits: MOCK: one share risks more than your limit", "met": False}
    assert "(MOCK: one share risks more than your limit)" in blocks(p, "notice")[0]["text"]


def test_b11_plan_not_built(src):
    p = build("stock_decision", "TVSMOTOR", message="trade TVSMOTOR", trade_idea=SimpleNamespace(plan=None, widget=None, sized=None))
    assert p["decision"] is None and blocks(p, "candles") and not blocks(p, "trade_plan")
    assert any("could not be built" in m for m in p["data_quality"]["missing"])


# ── B-12 / B-13: expected_move ───────────────────────────────────────────────
def test_b12_expected_move(src):
    p = build("expected_move", "NIFTY")
    k = {i["label"]: i["value"] for i in blocks(p, "kpis")[0]["items"]}
    assert k == {"Expected move": "±310.50 pts", "ATM IV": "13.40%", "PCR": "0.97", "Max pain": "21,200.00",
                 "Expiry": "4 Nov 2026", "Spot": "21,300.00"}
    c = blocks(p, "candles")[0]
    assert c["band"]["low"] == 20989.5 and len(c["levels"]) == 3
    assert p["headline"]["text"].startswith("The Nifty options price a move of about ±310.50 points (±1.46%)")


def test_b13_stale_chain_is_refused_not_shown(src, monkeypatch):
    from fastapi import HTTPException

    async def stale(request, symbol):
        raise HTTPException(status_code=404, detail="No current data for NIFTY")
    monkeypatch.setattr(rd, "chain", stale)
    p = build("expected_move", "BANKNIFTY")
    assert not blocks(p, "kpis") and p["headline"] is None and blocks(p, "candles")[0]["band"] is None
    assert p["title"] == "Expected move in Bank Nifty" and "HTTP 404" in p["data_quality"]["missing"][0]


# ── C-1: the contract check catches what the frontend would drop ─────────────
def test_c1_validate_catches_a_bad_payload(src):
    p = build("market_view")
    bad = json.loads(json.dumps(p))
    bad["decision"] = {"status": "setup_ready", "label": "Buy"}
    bad["blocks"].append({"type": "candles", "symbol": "X", "bars": []})
    bad["blocks"].append({"type": "chart3d"})
    problems = validate(bad)
    assert any("decision" in x for x in problems) and any("candles" in x for x in problems) and any("chart3d" in x for x in problems)


# ── F-1: the facts block ─────────────────────────────────────────────────────
def test_f1_facts_carry_the_figures_and_the_stock_comes_first(src):
    from services.copilot_tools.symbol_resolver import resolve_symbol
    from services.llm_safety import wrap_external_data
    p = build("market_view")
    f = facts(p)
    assert f.startswith("VISUAL_ANSWER (market_view)") and "FII cash −₹943.60 Cr" in f and "Nifty 50 · 60 sessions" in f
    idea = SimpleNamespace(plan=splan("plan"), widget=None, sized=None)
    s = build("stock_decision", "TVSMOTOR", message="Is this stock a buy now?", trade_idea=idea)
    told = "Is this stock a buy now?\n\n" + wrap_external_data(facts(s, subject="TVSMOTOR"), source="visual_answer")
    assert resolve_symbol(told).symbol == "TVSMOTOR"                                         # what the stock node will analyse
    assert "Decision (the desk plan's own status, not the model's): Setup ready" in told


# ── C-2: the REAL staging capture the frontend renders ───────────────────────
CAPTURE = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures" / "contract-visual-answer.json"


@pytest.mark.skipif(not CAPTURE.exists(), reason="the staging capture is not in this checkout")
def test_c2_the_staging_capture_matches_the_contract():
    doc = json.loads(CAPTURE.read_text(encoding="utf-8"))
    assert "REAL staging capture" in doc["about"]
    assert set(doc["payloads"]) == set(builders.BUILDERS)
    for intent, p in doc["payloads"].items():
        assert p["intent"] == intent and validate(p) == [], (intent, validate(p))
