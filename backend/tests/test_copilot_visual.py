"""The Copilot's visual answer (services/copilot_visual; contract docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md).

Covers R-1 … R-17, B-1 … B-26, C-1, F-1 of test_reports/dtc_visual_backend_20261030.md (CH-* are in
tests/test_copilot_visual_chat.py; C-2 checks the REAL staging capture). R-11 … R-17 and B-14 … B-26 are the five
Release-2 intents (owner, 30 Oct: "complete Release 2 and Release 3"); R-18 … R-20 and B-28 … B-39 are Release 3's
daily_review (test_reports/dtc_r3_daily_review_backend_20261031.md).

What is replaced (MOCK — not real data; every symbol, level and figure below is invented): the readers in
services/copilot_visual/readers.py (each existing route / DaaS read) and the freshness window. The resolver, the
builders, the EMA (the feature engine's own), the contract check and the facts block run for real.
"""
from __future__ import annotations

import asyncio
import json
import re
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
    ("Show the FIXCO chart", "trader"),
    ("Tell me about TVSMOTOR", "trader"),
    ("What should I avoid today?", "trader"),             # Q14, not built
    ("How is my portfolio doing?", "trader"),             # the CAS-portfolio_analyst's book, not the paper desk's
    ("How did I do in my portfolio this year?", "trader"),  # the CAS book again, even with review words
    ("What is my overall P&L?", "trader"),
    ("Should I average down on INFY?", "trader"),         # Release 3
    ("Is RELIANCE a buy now?", "investor"),              # buy-now words are a trader's question only
    ("What is the expected move in RELIANCE?", "trader"),  # Release 1: indices only
    ("Top gainers today", None),
    ("Is this stock a buy now?", "trader"),             # no thread stock: nothing to answer about
    ("", None),
])
def test_r9_questions_that_are_not_ours_take_the_usual_path(message, persona):
    assert resolve_intent(message, persona, None) is None


# ── Release 2: the five new intents ──────────────────────────────────────────
@pytest.mark.parametrize("message, persona, expected", [
    ("What are my open trades doing?", "trader", ("open_trades", None)),
    ("my open positions", None, ("open_trades", None)),
    ("How are my trades going today?", "trader", ("open_trades", None)),
    ("Which F&O setups are attractive?", "trader", ("fno_setups", None)),
    ("options trading ideas", None, ("fno_setups", None)),
    ("Is my trade in TCS still valid?", "trader", ("trade_validity", "TCS")),
    ("Has my thesis on INFY weakened?", None, ("trade_validity", "INFY")),
    ("Should I book profits or hold TCS?", "trader", ("exit_options", "TCS")),
    ("Should I trail my stop on RELIANCE?", None, ("exit_options", "RELIANCE")),
    ("How much should I risk?", "trader", ("position_size", None)),
    ("What position size should I take?", None, ("position_size", None)),
    ("How much should I risk in INFY?", "trader", ("position_size", "INFY")),
])
def test_r11_r15_the_five_release_2_intents(message, persona, expected):
    got = resolve_intent(message, persona, None)
    assert got is not None, message
    assert (got.name, got.symbol) == expected


def test_r16_named_r2_patterns_win_over_the_plain_stock_decision_read():
    """"still valid" and "book profits" also contain words TRADE_WORDS/BUY_WORDS would otherwise catch; the more
    specific Release-2 pattern must win, not a generic stock_decision."""
    assert resolve_intent("Is TCS still valid as a setup?", "trader").name == "trade_validity"
    assert resolve_intent("Should I hold or exit INFY?", "trader").name == "exit_options"


def test_r17_thread_symbol_also_resolves_validity_and_exit():
    got = resolve_intent("Is this trade still valid?", "trader", None, last_symbol="TVSMOTOR")
    assert (got.name, got.symbol, got.symbol_from_thread) == ("trade_validity", "TVSMOTOR", True)
    got = resolve_intent("Should I book profits or hold?", "trader", None, last_symbol="INFY")
    assert (got.name, got.symbol, got.symbol_from_thread) == ("exit_options", "INFY", True)
    assert wants_thread_symbol("Is my trade still valid?", "trader")
    assert wants_thread_symbol("Should I book profits?", "trader")


# ── Release 3: daily_review ──────────────────────────────────────────────────
@pytest.mark.parametrize("message, persona, period", [
    ("What did I learn from today's trades?", "trader", "day"),
    ("How did I do today?", None, "day"),
    ("How did I do this week?", "trader", "week"),
    ("What were my mistakes today?", "trader", "day"),
    ("mistakes this week", None, "week"),
    ("Review my trades today", "investor", "day"),
    ("Weekly review of my trading", None, "week"),
    ("How did I do on the TCS trade today?", "trader", "day"),       # a named stock is one row of the day's review
])
def test_r18_daily_review(message, persona, period):
    got = resolve_intent(message, persona, None)
    assert got is not None, message
    assert (got.name, got.symbol, got.params) == ("daily_review", None, {"period": period})
    assert not wants_thread_symbol(message, persona)                 # no thread read for a review


def test_r20_the_earlier_intents_are_unchanged_next_to_the_review():
    assert resolve_intent("How are my trades going today?", "trader").name == "open_trades"
    assert resolve_intent("Review my open trades", "trader").name == "open_trades"
    assert resolve_intent("Is my trade in TCS still valid?", "trader").name == "trade_validity"
    assert resolve_intent("What is the market view today?", "trader").name == "market_view"


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

# ── Release 2 fixture data ────────────────────────────────────────────────────
def ptrade(symbol, qty=10, entry=100.0, last=108.0, stop=92.0, target=120.0, pnl=80.0, status="open"):
    return {"id": f"pt_{symbol}", "symbol": symbol, "quantity": qty, "entry_price": entry, "last_close": last,
           "stop_price": stop, "target_price": target, "unrealized_pnl_rs": pnl, "status": status}


OPEN_TRADES = {"as_of": "2026-10-29", "trades": [ptrade("AAA", pnl=80.0), ptrade("BBB", qty=5, entry=200.0, last=190.0,
              stop=180.0, target=230.0, pnl=-50.0)], "summary": {"open": 2, "unrealized_pnl_rs": 30.0, "entry_pending": 0}}


RISK_PROFILE = {"profile": "owner-default", "stored": False, "capital_basis_text": "paper equity",
                "limits": {"per_trade_risk_pct": 0.5, "max_open_risk_pct": 3, "max_position_pct": 10,
                           "max_sector_pct": 25, "daily_loss_pct": 2, "weekly_loss_pct": 4,
                           "max_drawdown_pct": 10, "min_reward_risk": 1.5}}

RISK_BOOK = {"as_of": "2026-10-29T10:00:00+00:00", "equity": {"equity_rs": 995000.0, "unknown_reasons": []},
            "day": {"pnl_rs": -5000.0, "start_equity_rs": 1000000.0}, "week": {"pnl_rs": -5000.0, "start_equity_rs": 1000000.0},
            "open": {"risk_rs": 20000.0, "positions": 2}}


def stored_plan(pid="tp_old_1", direction="bullish", stop=1780.0, entry=1800.0, created="2026-10-20T10:00:00+00:00"):
    return {"plan_id": pid, "created_at": created, "strategy": {"direction": direction},
           "entry": {"price": entry}, "stop": {"price": stop}, "data_as_of": {"price": "2026-10-20"}}


def tplan(pid="tp_mock_1"):
    return {"plan_id": pid, "strategy": {"direction": "bullish"},
            "entry": {"price": 1840.0, "order_type": "stop_trigger", "valid_for_sessions": 3, "logic": "MOCK: a close above 1,840"},
            "stop": {"price": 1790.0, "method": "structural", "invalidation": "MOCK: a close below the base"},
            "targets": [{"name": "t1", "price": 1940.0, "r_multiple": 2.0, "primary": True}],
            "evidence": {"items": [{"key": "trend", "label": "Trend", "status": "ok", "direction": "supports", "text": "MOCK above the 50-day"},
                                   {"key": "vol", "label": "Volume", "status": "ok", "direction": "conflicts", "text": "MOCK volume light"}]},
            "warnings": [{"key": "event", "label": "Event", "status": "flagged", "text": "MOCK results in 4 sessions"}]}


def fno_idea(sym, view="up", name="Bull call spread", max_loss=-5000.0, max_profit=9000.0, rr=1.8,
            loss_unbounded=False, profit_unbounded=False, fit=0.7, plan_id=None):
    return {"underlying": sym, "view": view, "name": name, "max_loss": max_loss, "max_profit": max_profit,
           "reward_risk": rr, "loss_unbounded": loss_unbounded, "profit_unbounded": profit_unbounded,
           "fit": {"score": fit}, "trade_plan": tplan(plan_id or f"tp_{sym.lower()}")}


FNO_TOP = {"regime": REGIME, "classes": {"index_options": {"ideas": [fno_idea("NIFTY", plan_id="tp_nifty")]},
           "stock_fno": {"ideas": [fno_idea("RELIANCE", view="down", plan_id="tp_reliance")]}}}


# ── Release 3 fixture data (MOCK — not real data) ─────────────────────────────
def closed(symbol, day="2026-10-30", reason="target", entry=100.0, fill=100.0, stop=95.0, target=110.0, out=110.0,
           net=95.0, kind="cash", held=3, flags=None, closed_at=None):
    return {"id": f"ct_{symbol}_{day}", "kind": kind, "symbol": symbol, "status": "closed", "quantity": 10,
            "entry_price": entry, "sim_entry_price": fill, "stop_price": stop, "target_price": target,
            "exit_price": out, "exit_reason": reason, "exit_session": day,
            "closed_at": closed_at or f"{day}T14:30:00+00:00", "realized_pnl_rs": None if net is None else net + 5,
            "net_pnl_rs": net, "held_sessions": held, "flags": flags or []}


def closed_book():
    """Newest close first, as the reader returns them: 2 closed on TODAY (one target, one gapped stop), a not-entered
    one on TODAY, and 2 on earlier sessions for the curve."""
    return [closed("AAA", reason="target", out=110.0, net=95.0),
            closed("BBB", reason="stop", entry=200.0, fill=200.0, stop=190.0, target=230.0, out=187.0, net=-135.0,
                   flags=[{"code": "gap_through_stop", "text": "MOCK gap", "session": "2026-10-30", "price": 187.0}]),
            closed("CCC", reason="entry_not_reached", out=None, net=None, held=None),
            closed("DDD", day="2026-10-28", reason="manual", out=104.0, net=36.0),
            closed("EEE", day="2026-10-20", reason="target", out=110.0, net=95.0)]


def decision(i, outcome, day="2026-10-30", codes=(), severity="block", supersedes=None, hour=5):
    row = {"_id": f"rd{i}", "at": f"{day}T{hour:02d}:00:00+00:00", "outcome": outcome, "symbol": "AAA",
           "reasons": [{"code": c, "severity": severity, "message": f"MOCK {c} message"} for c in codes]}
    if supersedes:
        row["supersedes"] = supersedes
    return row


def decisions():
    return [decision(1, "allowed"), decision(2, "reduced", codes=("position_reduced",), severity="reduce"),
            decision(3, "blocked", codes=("sector_exceeded",)), decision(4, "blocked", codes=("sector_exceeded",)),
            decision(5, "blocked", codes=("plan_levels_mismatch",), severity="reject"),
            decision(6, "blocked", codes=("reservation_refused",), supersedes="rd1"),     # rd1's reservation was refused
            decision(7, "blocked", day="2026-10-27", codes=("duplicate_open_trade",))]


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
                  "delivery": {"as_of_date": "2026-10-28", "deliverable_pct": 45.5}, "bars": bars(300),
                  "open_trades": OPEN_TRADES, "fno_top": FNO_TOP, "risk_profile": RISK_PROFILE, "risk_book": RISK_BOOK,
                  "latest_trade_plan": stored_plan(), "closed_trades": closed_book(), "risk_decisions": decisions()}
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

        async def ti(request, user_id, symbol, message):
            self.calls.append(("trade_idea", (symbol,)))
            if "trade_idea" in self.fail:
                raise RuntimeError("MOCK trade_idea down")
            return SimpleNamespace(plan=splan("plan"), widget=None,
                                   sized={"status": "sized", "quantity": 12, "unit": "shares",
                                          "estimated_risk_rs": {"total": 640.5}, "risk_pct_of_equity": 0.64})
        self.trade_idea = ti                 # tests that call rd.trade_idea opt in: mp.setattr(rd, "trade_idea", src.trade_idea).
        # NOT auto-applied here: test_copilot_visual_chat.py's `world` fixture leaves rd.trade_idea as the real wrapper
        # (readers.trade_idea → services.copilot_trade_idea.build) so ITS OWN patch of copilot_trade_idea.build is
        # reached; stubbing rd.trade_idea here would shadow that and break the stock_decision chat tests.

        async def window():
            return WINDOW
        for name in ("market_snapshot", "sector_returns", "chain", "fii_dii", "buildup", "regime", "watchlist_day",
                     "positional_watchlist", "scan_snapshot", "open_trades", "fno_top", "risk_profile", "risk_book",
                     "latest_trade_plan", "closed_trades", "risk_decisions"):
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


# ── B-14 / B-15: open_trades ─────────────────────────────────────────────────
def test_b14_open_trades(src):
    p = build("open_trades")
    assert p["as_of"] == "2026-10-29"
    kp = {i["label"]: i["value"] for i in blocks(p, "kpis")[0]["items"]}
    assert kp["Open"] == "2" and kp["Unrealised P&L"] == "₹30.00"
    r = blocks(p, "ranked")[0]
    assert [row["symbol"] for row in r["rows"]] == ["AAA", "BBB"]
    assert r["rows"][0]["cells"] == {"symbol": "AAA", "qty": 10, "entry": 100.0, "last": 108.0, "stop": 92.0,
                                     "target": 120.0, "pnl": 80.0}
    assert r["rows"][0]["ask"] == "Should I book profits or hold AAA?"
    assert p["headline"]["text"] == "2 open paper trades, unrealised ₹30.00."


def test_b15_no_open_trades_says_so(src):
    src.v["open_trades"] = {"as_of": "2026-10-29", "trades": [], "summary": {"open": 0, "unrealized_pnl_rs": None, "entry_pending": 0}}
    p = build("open_trades")
    assert not blocks(p, "ranked") and "No open paper trades right now." in blocks(p, "notice")[0]["text"]
    assert p["headline"]["text"] == "No open paper trades right now."


def test_b15b_the_book_could_not_be_read(src):
    src.fail.add("open_trades")
    p = build("open_trades")
    assert not blocks(p, "kpis") and not blocks(p, "ranked")
    assert "MOCK open_trades down" in p["data_quality"]["missing"][0]


# ── B-16 / B-17: fno_setups ──────────────────────────────────────────────────
def test_b16_fno_setups(src):
    p = build("fno_setups")
    r = blocks(p, "ranked")[0]
    assert [row["symbol"] for row in r["rows"]] == ["NIFTY", "RELIANCE"]
    assert r["rows"][0]["cells"] == {"symbol": "NIFTY", "structure": "Bull call spread", "view": "Bullish",
                                     "maxloss": -5000.0, "maxprofit": 9000.0, "rr": 1.8, "fit": 0.7}
    assert r["rows"][1]["cells"]["view"] == "Bearish"
    assert blocks(p, "trade_plan")[0]["plan_id"] == "tp_nifty"
    assert p["headline"]["text"] == "2 F&O setups fit today's regime (Bullish)."


def test_b17_unbounded_sides_and_an_empty_board(src):
    src.v["fno_top"] = {"regime": REGIME, "classes": {"index_options": {"ideas": [
        fno_idea("NIFTY", loss_unbounded=True, profit_unbounded=False, plan_id="tp_nifty")]}, "stock_fno": {"ideas": []}}}
    p = build("fno_setups")
    assert blocks(p, "ranked")[0]["rows"][0]["cells"]["maxloss"] is None
    src.v["fno_top"] = {"regime": REGIME, "classes": {"index_options": {"ideas": []}, "stock_fno": {"ideas": []}}}
    p = build("fno_setups")
    assert not blocks(p, "ranked") and "a valid payoff" in blocks(p, "notice")[0]["text"]


# ── B-18 / B-19: position_size ───────────────────────────────────────────────
def test_b18_position_size_account_budget(src):
    p = build("position_size")
    kp = {i["label"]: i["value"] for i in blocks(p, "kpis")[0]["items"]}
    assert kp == {"Per trade": "0.5% of equity", "Max open risk": "3%", "One position": "10%", "One sector": "25%",
                 "Min reward:risk": "1.5×"}
    kp2 = {i["label"]: i["value"] for i in blocks(p, "kpis")[1]["items"]}
    assert kp2["Paper equity"] == "₹995,000.00" and kp2["Used of today's loss limit"] == "0.50%"
    assert blocks(p, "kpis")[1]["items"][1].get("tone") != "warn"            # 0.5% of a 2% limit: nowhere near it
    assert p["title"] == "How much to risk"


def test_b19_position_size_with_a_named_stock(src, monkeypatch):
    monkeypatch.setattr(rd, "trade_idea", src.trade_idea)
    p = build("position_size", "TVSMOTOR")
    sized = next(b for b in blocks(p, "kpis") if b["id"] == "sized")
    kp = {i["label"]: i["value"] for i in sized["items"]}
    assert kp == {"Size": "12 shares", "Max loss": "₹640.50"}
    assert p["title"] == "How much to risk in TVSMOTOR"
    assert "TVSMOTOR sizes to 12 shares" in p["headline"]["text"]


def test_b19b_a_stock_that_does_not_size(src, monkeypatch):
    async def ti(request, user_id, symbol, message):
        return SimpleNamespace(plan=splan("plan"), widget=None,
                               sized={"status": "not_sizable", "blocking": [{"message": "MOCK: too large for your budget"}]})
    monkeypatch.setattr(rd, "trade_idea", ti)
    p = build("position_size", "TVSMOTOR")
    assert any("does not size" in n["text"] and "too large for your budget" in n["text"] for n in blocks(p, "notice"))


def test_b19c_equity_unknown_is_shown_not_guessed(src):
    src.v["risk_book"] = {**RISK_BOOK, "equity": {"equity_rs": None, "unknown_reasons": ["MOCK: a position could not be marked"]}}
    p = build("position_size")
    assert len(blocks(p, "kpis")) == 1                                       # only the limits block; no usage figures
    assert any("equity is unknown" in m and "could not be marked" in m for m in p["data_quality"]["missing"])


# ── B-20 … B-23: trade_validity ──────────────────────────────────────────────
def test_b20_setup_still_holds(src, monkeypatch):
    monkeypatch.setattr(rd, "trade_idea", src.trade_idea)
    # Same direction, stop and plan_id as today's fresh plan (tplan(), the trade_idea stub's default): nothing changed.
    src.v["latest_trade_plan"] = stored_plan(pid="tp_mock_1", direction="bullish", stop=1790.0)
    p = build("trade_validity", "TVSMOTOR", message="Is TVSMOTOR still valid?")
    assert p["decision"]["status"] == "setup_ready"
    assert "still holds under today's rules" in p["headline"]["text"]
    texts = [i["text"] for i in blocks(p, "list")[0]["items"]] if blocks(p, "list") else []
    assert not any(t.startswith("Direction changed") or t.startswith("Stop moved") for t in texts)
    assert any("still the one in force today" in t for t in texts)


def test_b21_direction_and_stop_changed_since_it_was_recorded(src, monkeypatch):
    monkeypatch.setattr(rd, "trade_idea", src.trade_idea)
    src.v["latest_trade_plan"] = stored_plan(pid="tp_old_1", direction="bearish", stop=1700.0)
    p = build("trade_validity", "TVSMOTOR", message="Is TVSMOTOR still valid?")
    texts = [i["text"] for i in blocks(p, "list")[0]["items"]]
    assert any("Direction changed: recorded bearish, today" in t for t in texts)
    assert any("Stop moved: recorded ₹1,700.00" in t for t in texts)
    c = blocks(p, "candles")[0]
    assert any(lv["label"].startswith("Recorded entry") for lv in c["levels"])


def test_b22_no_earlier_plan_on_record(src, monkeypatch):
    monkeypatch.setattr(rd, "trade_idea", src.trade_idea)
    src.v["latest_trade_plan"] = None
    p = build("trade_validity", "TVSMOTOR", message="Is TVSMOTOR still valid?")
    assert "no earlier plan is on record" in p["headline"]["text"]
    assert any("no plan is on record" in m for m in p["data_quality"]["missing"])


def test_b23_no_setup_today_though_one_was_recorded(src, monkeypatch):
    async def ti(request, user_id, symbol, message):
        return SimpleNamespace(plan=splan("no_trade"), widget=None, sized=None)
    monkeypatch.setattr(rd, "trade_idea", ti)
    p = build("trade_validity", "TVSMOTOR", message="Is TVSMOTOR still valid?")
    assert p["decision"]["status"] == "avoid"
    assert "no longer there" in p["headline"]["text"]
    texts = [i["text"] for i in blocks(p, "list")[0]["items"]]
    assert any("find no setup today" in t for t in texts)


# ── B-24 … B-26: exit_options ────────────────────────────────────────────────
def test_b24_an_open_trade_shows_its_own_levels_and_pnl(src):
    p = build("exit_options", "AAA", message="Should I book profits or hold AAA?")
    kp = {i["label"]: i["value"] for i in blocks(p, "kpis")[0]["items"]}
    assert kp["Entry"] == "₹100.00" and kp["Unrealised P&L"] == "₹80.00"
    assert "Distance to stop" in kp and "Distance to target" in kp
    assert "unrealised ₹80.00" in p["headline"]["text"]
    assert any("does not tell you to exit or hold" in n["text"] for n in blocks(p, "notice"))
    c = blocks(p, "candles")[0]
    assert {lv["kind"] for lv in c["levels"]} == {"stop", "target"}


def test_b25_no_open_trade_in_that_symbol(src):
    p = build("exit_options", "ZZZ", message="Should I book profits or hold ZZZ?")
    assert any("No open paper trade in ZZZ" in n["text"] for n in blocks(p, "notice"))
    assert blocks(p, "kpis") == []


def test_b26_the_book_could_not_be_read(src):
    src.fail.add("open_trades")
    p = build("exit_options", "AAA", message="Should I book profits or hold AAA?")
    assert "MOCK open_trades down" in p["data_quality"]["missing"][0]


# ── B-27: readers.fno_top stores the plans it builds ─────────────────────────
def test_b27_fno_top_stores_its_trade_plans_like_the_route_does(monkeypatch):
    """regime_fit.build_top alone does not store anything — only POST /top's route handler does, right after calling
    it. readers.fno_top must do the same, or the fno_setups card's plan_id is never openable (GET
    /api/desk/trade-plans/{id} 404s). Found on the staging capture of 30 Oct: 0 of 5 plan ids were stored."""
    from routes import strategy_plan as sp

    top = {"classes": {"index_options": {"ideas": [{"trade_plan": {"plan_id": "tp_a"}}]},
                       "stock_fno": {"ideas": [{"trade_plan": {"plan_id": "tp_b"}}]}}}

    async def fake_build_top(request, user_id, *, limit, classes, expiry=None, distinct=False):
        assert classes == ["index_options", "stock_fno"] and distinct is True
        return top
    stored = []

    async def fake_store(plans, owner):
        stored.append((owner, [p.get("plan_id") for p in plans if p]))
    from services.strategy_plan import regime_fit
    monkeypatch.setattr(regime_fit, "build_top", fake_build_top)
    monkeypatch.setattr(sp, "store_trade_plans", fake_store)
    out = asyncio.run(rd.fno_top("REQ", "u1", limit=5))
    assert out is top
    assert stored == [("u1", ["tp_a", "tp_b"])]


# ── B-28 … B-39: daily_review (Release 3, Q15) ───────────────────────────────
def review(period="day", **kw):
    return build("daily_review", params={"period": period}, **kw)


def kp(p, bid="record"):
    return {i["label"]: i for i in next(b for b in blocks(p, "kpis") if b["id"] == bid)["items"]}


def listed(p, bid):
    return [i["text"] for i in next(b for b in blocks(p, "list") if b["id"] == bid)["items"]]


def test_b28_the_days_record(src):
    p = review()
    assert p["as_of"] == "2026-10-30" and p["title"] == "Your trading review · 30 Oct 2026"
    k = kp(p)
    assert (k["Closed"]["value"], k["Closed"]["sub"]) == ("2", "1 not entered")                 # B-36
    assert k["Wins / losses"]["value"] == "1 / 1" and k["Win rate"]["value"] == "50%"
    assert k["Realised P&L"]["value"] == "−₹40.00" and k["Realised P&L"]["tone"] == "down"      # 95 − 135
    assert k["Average R"]["value"] == "+0.35R"                                                   # (2.00 − 1.30) / 2
    rows = blocks(p, "ranked")[0]["rows"]
    assert [r["symbol"] for r in rows] == ["AAA", "BBB", "CCC"]
    assert rows[0]["cells"]["r"] == "+2.00R" and rows[1]["cells"]["r"] == "−1.30R"
    assert rows[1]["cells"]["exit"] == "Stop" and rows[2]["cells"]["exit"] == "Entry not reached"
    assert rows[2]["cells"]["pnl"] is None and rows[0].get("ask") is None
    exits = listed(p, "exits")
    assert exits[0] == "2 of 2 exits came from the plan's own rules (1 stop, 1 target); 0 were closed by you."
    assert any(t.startswith("1 stop exit filled below the stop (BBB)") for t in exits)
    assert "Largest result: AAA +₹95.00; smallest: BBB −₹135.00." in exits
    assert any("closed without an entry" in t for t in exits)
    curve = next(b for b in blocks(p, "bars") if b["id"] == "curve")
    assert curve["unit"] == "₹" and curve["orientation"] == "v"
    assert [(i["label"], i["value"]) for i in curve["items"]] == [("20 Oct", 95.0), ("28 Oct", 131.0), ("30 Oct", 91.0)]
    assert any(n["id"] == "hit-rate" and "no live hit-rate" in n["text"] for n in blocks(p, "notice"))
    assert p["headline"]["text"] == "2 paper trades closed on 30 Oct 2026: 1 win, 1 loss, net −₹40.00."
    assert [(s["status"], s["as_of"]) for s in p["data_quality"]["sources"]] == [("fresh", "2026-10-30")] * 2


def test_b34_risk_checks_counted_once_with_the_top_refusal(src):
    p = review()
    checks = listed(p, "risk_checks")
    # rd1 was superseded by rd6 (its reservation refused): 5 requests, not 6.
    assert checks[0] == "5 entry requests checked: 0 allowed, 1 reduced, 4 refused."
    assert checks[1] == "Refused for sector exceeded (2×): MOCK sector_exceeded message"
    assert "Refused for plan levels mismatch (1×): MOCK plan_levels_mismatch message" in checks
    since = next(a for n, a in src.calls if n == "risk_decisions")[1]
    assert since == "2026-07-01T18:30:00+00:00"                     # IST midnight, 120 days before 30 Oct, in UTC


def test_b29_nothing_today_falls_back_to_the_latest_session_with_its_date(src):
    src.v["closed_trades"] = [t for t in closed_book() if t["exit_session"] < "2026-10-30"]
    src.v["risk_decisions"] = [d for d in decisions() if d["at"] < "2026-10-30"]
    p = review()
    assert p["as_of"] == "2026-10-28" and p["title"] == "Your trading review · 28 Oct 2026"
    assert p["headline"]["text"] == ("Nothing was recorded on 30 Oct 2026; the latest session with activity is 28 Oct 2026. "
                                     "1 paper trade closed: 1 win, 0 losses, net +₹36.00.")
    assert p["data_quality"]["stale"] is True                       # older than the previous session: said, not hidden
    assert any("28 Oct 2026, older than the previous session" in n["text"] for n in blocks(p, "notice"))
    assert any(n["text"] == "No entry request was checked by the risk rules on 28 Oct 2026." for n in blocks(p, "notice"))


def test_b30_the_week(src):
    p = review("week")
    assert p["title"] == "Your trading review · 26 Oct – 30 Oct 2026" and p["as_of"] == "2026-10-30"
    assert p["headline"]["text"] == "3 paper trades closed this week: 2 wins, 1 loss, net −₹4.00."
    assert listed(p, "risk_checks")[0] == "6 entry requests checked: 0 allowed, 1 reduced, 5 refused."
    assert p["follow_ups"][0]["query"] == "What did I learn from today's trades?"


def test_b31_nothing_on_record(src):
    src.v["closed_trades"], src.v["risk_decisions"] = [], []
    p = review()
    assert p["headline"]["text"] == "No closed paper trades or risk checks are on record yet, so there is nothing to review."
    assert not blocks(p, "kpis") and not blocks(p, "ranked") and not blocks(p, "bars")       # nothing invented
    texts = [n["text"] for n in blocks(p, "notice")]
    assert "No closed paper trades are on record yet." in texts
    assert "No entry request was checked by the risk rules on 30 Oct 2026." in texts
    assert p["as_of"] == "2026-10-30" and p["headline"]["tone"] == "neutral"


def test_b32_the_trades_read_fails(src):
    src.fail.add("closed_trades")
    p = review()
    assert any("MOCK closed_trades down" in m for m in p["data_quality"]["missing"])
    assert not blocks(p, "kpis") and not blocks(p, "ranked") and not blocks(p, "bars")
    assert listed(p, "risk_checks")[0].startswith("5 entry requests checked")
    assert p["headline"]["text"] == ("Your closed paper trades could not be read; the risk checks refused 4 of 5 entry "
                                     "requests on 30 Oct 2026.")


def test_b33_the_decisions_read_fails(src):
    src.fail.add("risk_decisions")
    p = review()
    assert any("MOCK risk_decisions down" in m for m in p["data_quality"]["missing"])
    assert not any(b["id"] == "risk_checks" for b in blocks(p, "list"))
    assert kp(p)["Closed"]["value"] == "2" and p["headline"]["text"].startswith("2 paper trades closed on 30 Oct 2026")


def test_b35_no_stop_to_measure_against(src):
    src.v["closed_trades"] = [
        closed("AAA"),
        {**closed("NIFTY", kind="strategy", out=None, net=50.0), "family_name": "Bull call spread", "stop_price": None,
         "target_price": None, "entry_price": None, "sim_entry_price": None, "stop_underlying": 22800.0,
         "target_underlying": 23400.0},
        closed("ZZZ", stop=101.0, fill=100.0, out=99.0, net=-12.0)]
    p = review()
    k = kp(p)
    assert k["Average R"]["value"] == "+2.00R" and k["Average R"]["sub"] == "1 of 3 had a stop to measure against, before costs"
    rows = {r["symbol"]: r["cells"] for r in blocks(p, "ranked")[0]["rows"]}
    assert rows["NIFTY"]["r"] is None and rows["ZZZ"]["r"] is None
    assert rows["NIFTY"]["exit"] == "Target · Bull call spread" and rows["NIFTY"]["stop"] == 22800.0
    assert rows["NIFTY"]["planned"] is None and rows["NIFTY"]["out"] is None


def test_b35b_no_stop_at_all(src):
    src.v["closed_trades"] = [closed("ZZZ", stop=None, out=99.0, net=-12.0)]
    k = kp(review())
    assert k["Average R"]["value"] is None and k["Average R"]["sub"] == "no trade had a stop to measure against"


def test_b37_wording_and_follow_ups(src):
    from services.copilot_visual.intents import resolve_intent as ri
    for p in (review(), review("week")):
        text = json.dumps(p, ensure_ascii=False)
        assert not re.search(r"\b(buy now|strong buy|recommended|pick|you should)\b", text, re.I)   # the frontend's own check
        for f in p["follow_ups"]:
            got = ri(f["query"], "trader")
            assert got is not None and got.name in builders.BUILDERS, f["query"]


def test_b38_facts_carry_the_review(src):
    f = facts(review())
    assert f.startswith("VISUAL_ANSWER (daily_review)")
    assert "The record · 30 Oct 2026: Closed 2 (1 not entered)" in f
    assert "Plan vs actual · 3 closed (columns: Stock, Exit, Planned entry, Fill, Stop, Target, Exit price, R, Net P&L)" in f
    assert "Equity curve: cumulative realised P&L [₹]: 20 Oct 95.00; 28 Oct 131.00; 30 Oct 91.00" in f
    assert "What the risk checks said: 5 entry requests checked" in f


def test_b39_the_readers_are_plain_reads(monkeypatch):
    import deps
    from routes import desk_trading

    class Cursor:
        def __init__(self, docs):
            self.docs, self.order = docs, None

        def sort(self, *a):
            self.order = a
            return self

        async def to_list(self, n):
            return self.docs[:n]

    class Coll:
        def __init__(self, docs):
            self.docs, self.seen = docs, []

        def find(self, flt, proj=None):
            self.seen.append((flt, proj))
            return Cursor(self.docs)

    trades, decs = Coll([{"_id": "t1", "status": "closed"}]), Coll([{"_id": "rd1"}])
    monkeypatch.setattr(deps, "db", {"desk_paper_trades": trades, "risk_decisions": decs})
    monkeypatch.setattr(desk_trading, "_public", lambda d: {"shaped": d["_id"]})

    async def never(*a, **k):
        raise AssertionError("the review must not call the GET route: it runs the exit rule (a write)")
    monkeypatch.setattr(desk_trading, "list_paper_trades", never)
    assert asyncio.run(rd.closed_trades("u1", 5)) == [{"shaped": "t1"}]
    assert trades.seen[0][0] == {"user_id": "u1", "status": "closed"}
    assert asyncio.run(rd.risk_decisions("u1", "2026-10-01T00:00:00+00:00")) == [{"_id": "rd1"}]
    flt, proj = decs.seen[0]
    assert flt == {"user_id": "u1", "at": {"$gte": "2026-10-01T00:00:00+00:00"}} and "snapshot" not in proj


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
