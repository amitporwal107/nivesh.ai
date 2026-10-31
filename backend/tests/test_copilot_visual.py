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

# What fno_board.margin_calculators reports when nothing can calculate margin.
NO_LOGIN = {"platform_login": False, "zerodha_connected": 0, "zerodha_live": 0, "others": []}
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
# readers.market_state: the state the risk service sizes new paper trades with, and its freshness (MOCK values).
MARKET_STATE = {"vix": 15.3, "regime": "BEAR", "as_of": "2026-10-29", "key": "bearish", "source": "MOCK market state", "error": None,
                "freshness": {"ok": True, "age_sessions": 0, "budget": 2, "reason": None}}

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
                  "sector_returns": SECTORS, "chain": CHAIN, "fii_dii": FLOWS, "buildup": BUILDUP, "regime": REGIME, "market_state": MARKET_STATE,
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
        for name in ("market_snapshot", "sector_returns", "chain", "fii_dii", "buildup", "regime", "market_state", "watchlist_day",
                     "positional_watchlist", "scan_snapshot", "open_trades", "fno_top", "risk_profile", "risk_book",
                     "latest_trade_plan", "closed_trades", "risk_decisions"):
            mp.setattr(rd, name, make(name))
        mp.setattr(rd, "delivery_latest", make("delivery_latest", "delivery"))
        mp.setattr(rd, "stock_bars", make("stock_bars", "bars"))
        mp.setattr(rd, "index_rows", idx)
        mp.setattr(rd, "window", window)

        async def open_book(request, user_id, use_cache=False):         # the broker book (open trades): none connected by default
            self.calls.append(("open_book", ()))
            if "open_book" in self.fail:
                raise RuntimeError("MOCK open_book down")
            return self.v["open_book"]
        self.v["open_book"] = {"hub": "on", "accounts": [], "groups": []}
        mp.setattr(rd, "open_book", open_book)

        # The F&O board's live and margin readers (owner, 31 Oct 2026). Default: market closed, no Kite login, no broker.
        self.in_session = False
        self.v.update({"fno_live_quotes": {"available": False, "reason": "MOCK: no Kite login today", "quotes": {}, "unresolved": []},
                       "live_spots": {}, "margin_calculators": ([], dict(NO_LOGIN)), "margin_estimates": None})
        self.v["sector_members"] = {}                    # {index name: DaaS /desk/sector-constituents body}; an index not here raises

        async def sector_constituents(index):
            self.calls.append(("sector_constituents", (index,)))
            if index not in self.v["sector_members"]:
                raise RuntimeError(f"MOCK constituents of {index} down")
            return self.v["sector_members"][index]
        mp.setattr(rd, "sector_constituents", sector_constituents)
        mp.setattr(rd, "in_session", lambda now=None: self.in_session)
        for name in ("fno_live_quotes", "live_spots", "margin_calculators"):
            mp.setattr(rd, name, make(name))

        async def fno_margins(calcs, items):
            self.calls.append(("fno_margins", tuple(k for k, _, _ in items)))
            est = self.v["margin_estimates"]
            if est is None or not calcs:
                return {}
            return {k: est(k, u, legs) for k, u, legs in items}
        mp.setattr(rd, "fno_margins", fno_margins)


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
    # The order is the desk's Market regime card: the day's tiles, the regime, the flows, the sector moves, then the charts.
    assert [(b["type"], b["id"]) for b in p["blocks"]] == [("kpis", "day"), ("kpis", "regime"), ("bars", "flows"),
                                                              ("bars", "sector_moves"), ("candles", "nifty"), ("heatmap", "sectors")]
    day = blocks(p, "kpis")[0]["items"]
    assert [i["label"] for i in day] == ["Nifty 50", "Bank Nifty", "India VIX", "Breadth"]
    regime = {i["label"]: i for i in blocks(p, "kpis")[1]["items"]}
    assert regime["Regime"]["value"] == "BEAR" and regime["Regime"]["tone"] == "down"
    assert regime["Regime"]["sub"] == "as of 29 Oct · India VIX 15.30"
    assert regime["New-trade size limits"]["value"] == "Halved" and regime["New-trade size limits"]["sub"] == "New-trade size limits are halved in BEAR."
    assert regime["Market state"]["value"] == "0 of 2 sessions old" and "tone" not in regime["Market state"]
    flows = next(b for b in blocks(p, "bars") if b["id"] == "flows")
    assert [(i["label"], i["value"], i["tone"]) for i in flows["items"]] == [("FII", -943.6, "down"), ("DII", 1924.41, "up")]
    assert flows["unit"] == "₹ Cr" and flows["orientation"] == "h"
    moves = next(b for b in blocks(p, "bars") if b["id"] == "sector_moves")
    assert [(i["label"], i["tone"]) for i in moves["items"]] == [("IT", "up"), ("Bank", "down")]       # SECTORS has two: one each
    assert "the market regime reads BEAR" in p["headline"]["text"]
    c = blocks(p, "candles")[0]
    assert c["symbol"] == "NIFTY" and len(c["bars"]) == 60 and len(c["overlays"]["ema20"]) == 60
    assert {lv["kind"] for lv in c["levels"]} == {"wall_call", "wall_put", "max_pain"}
    assert c["band"] == {"low": 20989.5, "high": 21610.5, "label": "Expected move to 4 Nov 2026 (ATM straddle ±310.50)"}
    assert [x["label"] for x in blocks(p, "heatmap")[0]["cells"]] == ["IT", "Bank"]
    assert "62% of stocks advanced" in p["headline"]["text"]        # 2000 / 3200
    assert p["data_quality"]["stale"] is False and p["data_quality"]["missing"] == [] and not blocks(p, "notice")
    assert p["caveat"].startswith("Built from end-of-day data of 29 Oct 2026.")


def test_b1b_the_regime_row_follows_the_risk_governors_rule(src):
    def tiles(**over):
        src.v["market_state"] = {**MARKET_STATE, **over}
        return {i["label"]: i for i in blocks(build("market_view"), "kpis")[1]["items"]}
    bull = tiles(regime="BULL", vix=14.0)
    assert bull["Regime"]["tone"] == "up" and bull["New-trade size limits"]["value"] == "Not cut"
    assert "tone" not in bull["New-trade size limits"]
    assert tiles(regime="SIDEWAYS", vix=26.0)["New-trade size limits"]["sub"] == "India VIX at 25 or above halves them."
    assert tiles(regime="BULL", vix=36.0)["New-trade size limits"]["value"] == "Deferred"
    stale = tiles(freshness={"ok": False, "age_sessions": 4, "budget": 2, "reason": "old"})
    assert stale["Market state"]["value"] == "4 of 2 sessions old" and stale["Market state"]["tone"] == "warn"


def test_b1c_a_missing_market_state_is_said_not_guessed(src):
    src.fail.add("market_state")
    p = build("market_view")
    assert not any(b["id"] == "regime" for b in p["blocks"])
    assert any("Market state the risk service uses" in m for m in p["data_quality"]["missing"])
    assert "regime" not in p["headline"]["text"]


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
    assert not blocks(p, "ranked") and any("No open paper trades right now." in n["text"] for n in blocks(p, "notice"))
    assert p["headline"]["text"] == "No open paper trades right now."


def test_b15b_the_book_could_not_be_read(src):
    src.fail.add("open_trades")
    p = build("open_trades")
    assert not blocks(p, "kpis") and not blocks(p, "ranked")
    assert "MOCK open_trades down" in p["data_quality"]["missing"][0]


# ── B-16 / B-17: fno_setups — see the F&O board section (FB-1 … FB-15) at the end of this file ──


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
    assert f.startswith("VISUAL_ANSWER (market_view)") and "FII -943.60" in f and "Market regime: Regime BEAR" in f and "Nifty 50 · 60 sessions" in f
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


# ═════ F&O board (owner, 31 Oct 2026): two sections, lots, margin, profit that is a target, live premiums ═════
# FB-1 … FB-15 of test_reports/copilot_fno_board_20261031.md. MOCK — not real data: every symbol, strike and figure is invented.
from services.copilot_visual import fno_board as fb                                   # noqa: E402
from services.strategy_plan.regime_fit import metrics_for                              # noqa: E402


def bleg(side, strike, otype, px, lot=30, expiry="2026-11-25"):
    return {"kind": "option", "side": side, "quantity": 1, "lot_size": lot, "entry_price": px, "expiry": expiry,
            "strike": strike, "option_type": otype}


def bidea(sym, structure="bear_put_spread", name=None, view="down", legs=None, lot=30, max_loss=-14406.0, max_profit=33594.0,
          profit_unbounded=False, net_at_move=4000.0, rr=2.31, fit=92.5, alts=(), chain_day="2026-10-29"):
    legs = legs if legs is not None else [bleg("buy", 54700, "put", 700.0, lot), bleg("sell", 53100, "put", 220.0, lot)]
    return {"underlying": sym, "structure": structure, "name": name or f"{structure} {sym}", "view": view, "legs": legs,
            "max_loss": max_loss, "max_profit": max_profit, "loss_unbounded": False, "profit_unbounded": profit_unbounded,
            "net_at_expected_move": net_at_move, "reward_risk": rr, "fit": {"score": fit}, "trade_plan": tplan(f"tp_{sym.lower()}_{structure}"),
            "data_as_of": {"chain": chain_day, "regime": "2026-10-29"}, "alternatives": list(alts)}


def board(index=(), stock=(), stock_unavailable=None):
    ctx = [{"underlying": "BANKNIFTY", "spot": 54686.95, "expected_move": 900.0},
           {"underlying": "NIFTY", "spot": 23053.1, "expected_move": 380.0},
           {"underlying": "RELIANCE", "spot": 1400.0, "expected_move": 45.0}, {"underlying": "TCS", "spot": 3000.0, "expected_move": 90.0}]
    return {"regime": {**REGIME, "label": "Bearish"},
            "classes": {"index_options": {"ideas": list(index), "underlyings": ctx[:2], "unavailable": []},
                        "stock_fno": {"ideas": list(stock), "underlyings": ctx[2:], "universe": {"skipped": []},
                                      "unavailable": stock_unavailable or []}}}


def owner_board():
    """The owner's screenshot: both index leads each carry two alternatives (so a flattened first-5 is all index)."""
    bn_alts = [bidea("BANKNIFTY", "long_put", "Long put 54700", legs=[bleg("buy", 54700, "put", 760.45)], max_loss=-22813.5,
                     max_profit=1618186.5, net_at_move=26235.0, rr=1.15),
               bidea("BANKNIFTY", "long_put", "Long put 54600", legs=[bleg("buy", 54600, "put", 719.8)], max_loss=-21594.0,
                     max_profit=1616406.0, net_at_move=24400.0, rr=1.13)]
    n_alts = [bidea("NIFTY", "long_put", "Long put 23050", lot=65, legs=[bleg("buy", 23050, "put", 127.30, 65)], max_loss=-8274.5,
                    max_profit=1489975.5, net_at_move=13000.0, rr=0.78)]
    return board(
        index=[bidea("BANKNIFTY", name="Bear put spread 53100/54700", alts=bn_alts),
               bidea("NIFTY", name="Bear put spread 22800/23050", lot=65, max_loss=-5450.25, max_profit=10799.75, rr=1.7,
                     legs=[bleg("buy", 23050, "put", 127.3, 65), bleg("sell", 22800, "put", 43.5, 65)], alts=n_alts)],
        stock=[bidea("RELIANCE", name="Bear put spread 1380/1400", lot=500, max_loss=-6000.0, max_profit=14000.0, rr=1.9, fit=80.0,
                     legs=[bleg("buy", 1400, "put", 30.0, 500), bleg("sell", 1380, "put", 18.0, 500)]),
               bidea("TCS", name="Bull call spread 3000/3060", view="up", structure="bull_call_spread", lot=175, max_loss=-9000.0,
                     max_profit=21000.0, rr=1.5, fit=78.0,
                     legs=[bleg("buy", 3000, "call", 80.0, 175), bleg("sell", 3060, "call", 40.0, 175)])])


def row_of(p, block_id, sym):
    return next(r for r in next(b for b in blocks(p, "ranked") if b["id"] == block_id)["rows"] if r["symbol"] == sym)


def test_fb1_two_sections_one_row_per_underlying_alternatives_folded(src):
    """The reported bug: a flattened first-5 of [index leads + their alternatives] held no stock at all."""
    src.v["fno_top"] = owner_board()
    p = build("fno_setups")
    ids = [b["id"] for b in blocks(p, "ranked")]
    assert ids == ["fno_index", "fno_stock"]
    index, stock = blocks(p, "ranked")
    assert index["title"].startswith("Index options") and stock["title"].startswith("Stock F&O")
    assert [r["symbol"] for r in index["rows"]] == ["BANKNIFTY", "NIFTY"]
    assert [r["symbol"] for r in stock["rows"]] == ["RELIANCE", "TCS"]
    assert [len(r["alternatives"]) for r in index["rows"]] == [2, 1] and "alternatives" not in stock["rows"][0] or not stock["rows"][0].get("alternatives")
    assert all(a["symbol"] == r["symbol"] and "alternatives" not in a for r in index["rows"] for a in r["alternatives"])
    assert "2 index" in p["headline"]["text"] and "2 stock" in p["headline"]["text"]
    assert blocks(p, "trade_plan")[0]["plan_id"] == "tp_banknifty_bear_put_spread"


def test_fb2_no_stock_setup_says_why(src):
    src.v["fno_top"] = board(index=owner_board()["classes"]["index_options"]["ideas"],
                             stock_unavailable=[{"underlying": None, "reason": "the scanner returned no setups"}])
    p = build("fno_setups")
    assert [b["id"] for b in blocks(p, "ranked")] == ["fno_index"]
    n = next(b for b in blocks(p, "notice") if b["id"] == "fno_stock-empty")
    assert "Stock F&O" in n["text"] and "the scanner returned no setups" in n["text"]


def test_fb3_a_bought_put_is_not_capped_in_practice(src):
    src.v["fno_top"] = owner_board()
    p = build("fno_setups")
    alt = row_of(p, "fno_index", "BANKNIFTY")["alternatives"][0]                       # Long put 54700
    assert alt["cells"]["maxprofit"] == "Not capped"
    assert alt["cells"]["atmove"] == 26235.0 and alt["cells"]["maxloss"] == -22813.5
    assert "1,618,186.50" in alt["tips"]["maxprofit"] and "zero" in alt["tips"]["maxprofit"]
    assert 1618186.5 not in alt["cells"].values()                                      # the to-zero figure is a tooltip only
    spread = row_of(p, "fno_index", "BANKNIFTY")
    assert spread["cells"]["maxprofit"] == 33594.0 and "tips" not in spread           # a spread's maximum is a real maximum


def test_fb4_a_bought_call_is_not_capped(src):
    call = bidea("NIFTY", "long_call", "Long call 23100", view="up", lot=65, legs=[bleg("buy", 23100, "call", 90.0, 65)],
                 max_loss=-5850.0, max_profit=None, profit_unbounded=True, net_at_move=9000.0, rr=1.5)
    src.v["fno_top"] = board(index=[call])
    r = row_of(build("fno_setups"), "fno_index", "NIFTY")
    assert r["cells"]["maxprofit"] == "Not capped" and r["cells"]["atmove"] == 9000.0 and r["cells"]["maxloss"] == -5850.0


def test_fb5_lots(src):
    src.v["fno_top"] = owner_board()
    p = build("fno_setups")
    assert row_of(p, "fno_index", "BANKNIFTY")["cells"]["lots"] == "1 lot × 30"
    assert row_of(p, "fno_index", "NIFTY")["cells"]["lots"] == "1 lot × 65"
    assert row_of(p, "fno_stock", "TCS")["cells"]["lots"] == "1 lot × 175"
    assert fb.lots_text([bleg("buy", 1, "call", 1.0, 30), bleg("sell", 2, "call", 1.0, 50)]) is None      # never a guess
    assert fb.lots_text([]) is None


def margin_stub(k, u, legs):
    return {"estimate": 60000.0 if len(legs) == 2 else 25000.0, "reason": None, "source": fb.LABEL_PLATFORM}


def test_fb6_margin_from_a_calculator(src):
    src.v["fno_top"] = owner_board()
    src.v["margin_calculators"] = ([(fb.LABEL_PLATFORM, object())], {**NO_LOGIN, "platform_login": True})
    src.v["margin_estimates"] = margin_stub
    p = build("fno_setups")
    assert row_of(p, "fno_index", "BANKNIFTY")["cells"]["margin"] == 60000.0
    assert row_of(p, "fno_index", "BANKNIFTY")["alternatives"][0]["cells"]["margin"] == 25000.0       # a single bought put
    assert not [b for b in blocks(p, "notice") if b.get("actions")]
    assert any(s["name"] == fb.LABEL_PLATFORM and s["status"] == "fresh" for s in p["data_quality"]["sources"])


def test_fb7_no_calculator_asks_for_a_login(src):
    src.v["fno_top"] = owner_board()
    src.v["margin_calculators"] = ([], {**NO_LOGIN, "others": ["icici_direct"]})
    p = build("fno_setups")
    assert row_of(p, "fno_index", "BANKNIFTY")["cells"]["margin"] == "Needs login"
    n = next(b for b in blocks(p, "notice") if b.get("actions"))
    assert {a["kind"] for a in n["actions"]} == {"kite_login", "connect_broker"}
    assert n["text"].startswith("Margin needs a Kite login:") and "connect your own Zerodha account" in n["text"]
    assert "Icici Direct has no margin calculator wired" in n["text"]


def test_fb8_the_users_zerodha_session_has_ended(src):
    src.v["fno_top"] = owner_board()
    src.v["margin_calculators"] = ([], {**NO_LOGIN, "zerodha_connected": 1})
    n = next(b for b in blocks(build("fno_setups"), "notice") if b.get("actions"))
    assert "sign in to your Zerodha account again" in n["text"] and "connect your own" not in n["text"]


def test_fb9_the_users_own_zerodha_is_the_fallback(src):
    src.v["fno_top"] = owner_board()
    src.v["margin_calculators"] = ([(fb.LABEL_OWN, object())], {**NO_LOGIN, "zerodha_connected": 1, "zerodha_live": 1})
    src.v["margin_estimates"] = lambda k, u, legs: {"estimate": 41000.0, "reason": None, "source": fb.LABEL_OWN}
    p = build("fno_setups")
    assert row_of(p, "fno_stock", "TCS")["cells"]["margin"] == 41000.0
    assert any(s["name"] == fb.LABEL_OWN for s in p["data_quality"]["sources"])


def test_fb10_one_structure_whose_margin_fails_shows_no_figure(src):
    src.v["fno_top"] = owner_board()
    src.v["margin_calculators"] = ([(fb.LABEL_PLATFORM, object())], {**NO_LOGIN, "platform_login": True})
    src.v["margin_estimates"] = lambda k, u, legs: ({"estimate": None, "reason": "the calculator failed (ReadTimeout)", "source": fb.LABEL_PLATFORM}
                                                    if u == "TCS" else margin_stub(k, u, legs))
    p = build("fno_setups")
    assert row_of(p, "fno_stock", "TCS")["cells"]["margin"] is None
    assert row_of(p, "fno_stock", "RELIANCE")["cells"]["margin"] == 60000.0
    assert any("TCS" in m and "ReadTimeout" in m for m in p["data_quality"]["missing"])


def live_answer(prices, available=True):
    """prices: {flat index: last_price} → the reader's answer (string keys, as the route sends them)."""
    return {"available": available, "reason": None, "quotes": {str(i): {"key": f"NFO:X{i}", "last_price": px} for i, px in prices.items()},
            "unresolved": [], "as_of": "2026-10-30T05:30:00+00:00", "source": fb.SRC_LIVE}


def test_fb11_live_in_session_reprices_by_the_board_engine(src):
    """Premiums live, ranking untouched, mode mixed; an idea with one leg unpriced keeps its end-of-day figures."""
    src.in_session = True
    top = owner_board()
    src.v["fno_top"] = top
    ideas = [top["classes"]["index_options"]["ideas"][0]] + top["classes"]["index_options"]["ideas"][0]["alternatives"] \
        + [top["classes"]["index_options"]["ideas"][1]] + top["classes"]["index_options"]["ideas"][1]["alternatives"] \
        + top["classes"]["stock_fno"]["ideas"]
    flat, at = fb.leg_requests(ideas)
    prices = {at[(0, 0)]: 650.0, at[(0, 1)]: 190.0}                              # BANKNIFTY spread: both legs live; nothing else
    src.v["fno_live_quotes"] = live_answer(prices)
    src.v["live_spots"] = {"BANKNIFTY": 54500.0}
    p = build("fno_setups")
    r = row_of(p, "fno_index", "BANKNIFTY")
    legs = [{**l, "entry_price": px} for l, px in zip(ideas[0]["legs"], (650.0, 190.0))]
    oracle = metrics_for("BANKNIFTY", legs, 54500.0, "2026-10-30", scenario_price=54500.0 - 900.0)
    assert r["badge"] == "Live" and oracle["ok"]
    assert r["cells"]["maxloss"] == round(oracle["max_loss"], 2) and r["cells"]["maxprofit"] == round(oracle["max_profit"], 2)
    assert r["cells"]["atmove"] == round(oracle["net_at_expected_move"], 2) and r["cells"]["rr"] == oracle["reward_risk_at_expected_move"]
    assert r["cells"]["maxloss"] != -14406.0                                       # not the end-of-day figure
    assert row_of(p, "fno_index", "NIFTY")["badge"] == "29 Oct close"              # no live leg: stays end of day, said so
    assert row_of(p, "fno_index", "NIFTY")["cells"]["maxloss"] == -5450.25
    assert [x["symbol"] for x in blocks(p, "ranked")[0]["rows"]] == ["BANKNIFTY", "NIFTY"]            # the ranking is not recomputed
    assert p["mode"] == "mixed" and "live" in p["caveat"].lower() and "29 Oct" in p["caveat"]
    assert any(s["name"] == fb.SRC_LIVE for s in p["data_quality"]["sources"])
    assert ("fno_live_quotes", (flat,)) in src.calls


def test_fb12_no_live_premium_without_a_live_spot(src):
    """A live premium over a stale spot would put the expected-move scenario at a price that belongs to no moment."""
    src.in_session = True
    top = owner_board()
    src.v["fno_top"] = top
    idea0 = top["classes"]["index_options"]["ideas"][0]
    _, at = fb.leg_requests([idea0])
    src.v["fno_live_quotes"] = live_answer({at[(0, 0)]: 650.0, at[(0, 1)]: 190.0})
    src.v["live_spots"] = {}
    r = row_of(build("fno_setups"), "fno_index", "BANKNIFTY")
    assert r["badge"] == "29 Oct close" and r["cells"]["maxloss"] == -14406.0


def test_fb13_market_closed_makes_no_live_read(src):
    src.v["fno_top"] = owner_board()
    p = build("fno_setups")
    assert not [c for c in src.calls if c[0] in ("fno_live_quotes", "live_spots")]
    assert p["mode"] == "eod" and row_of(p, "fno_index", "BANKNIFTY")["badge"] == "29 Oct close"


def test_fb14_live_unavailable_says_why_and_asks_for_the_login(src):
    src.in_session = True
    src.v["fno_top"] = owner_board()                                                # default fno_live_quotes: no Kite login today
    p = build("fno_setups")
    assert p["mode"] == "eod" and row_of(p, "fno_index", "BANKNIFTY")["cells"]["maxloss"] == -14406.0
    assert any("no Kite login today" in m for m in p["data_quality"]["missing"])
    n = next(b for b in blocks(p, "notice") if b.get("actions"))
    assert "Margin and live premiums need a Kite login" in n["text"]


def test_fb15_the_contract_check_covers_the_new_fields(src):
    src.v["fno_top"] = owner_board()
    p = build("fno_setups")
    good = validate(p)
    assert good == []
    bad = json.loads(json.dumps(p))
    next(b for b in bad["blocks"] if b["type"] == "ranked")["rows"][0]["alternatives"] = [{"cells": "not a dict"}]
    assert any("alternatives" in x for x in validate(bad))
    bad2 = json.loads(json.dumps(p))
    bad2["blocks"].append({"type": "notice", "id": "n", "title": None, "note": None, "tone": "warn", "text": "x",
                           "actions": [{"kind": "wire_money", "label": "x"}]})
    assert any("action" in x for x in validate(bad2))


# ── fno_board against fake Kite objects (no mocks of the logic under test) ───────────────────────────────────
class FakeCalc:
    """The Calculator surface (fno_margin.Calculator): the NFO list and the basket calculation."""
    def __init__(self, refuse=False):
        self.refuse, self.calls = refuse, []

    def instruments(self):
        return [{"name": "BANKNIFTY", "expiry": date(2026, 11, 25), "strike": k, "instrument_type": "PE", "lot_size": 30,
                 "tradingsymbol": f"BANKNIFTY26NOV{int(k)}PE"} for k in (53100.0, 54700.0)]

    def basket_margins(self, params):
        self.calls.append(params)
        if self.refuse:
            class TokenException(Exception):
                pass
            raise TokenException("Incorrect `api_key` or `access_token`.")
        return {"final": {"total": 77000.0}, "initial": {"total": 90000.0}, "orders": []}


def _reset_margin_state():
    from services import fno_margin
    fno_margin._INSTRUMENTS.update(day=None, rows=None)
    fb._CACHE.clear()


def test_fb16_margin_is_one_basket_call_in_lots_times_lot_size_and_is_cached():
    _reset_margin_state()
    calc = FakeCalc()
    legs = [bleg("buy", 54700, "put", 700.0), bleg("sell", 53100, "put", 220.0)]
    out = asyncio.run(fb.margins([(fb.LABEL_PLATFORM, calc)], [("a", "BANKNIFTY", legs)]))
    assert out["a"] == {"estimate": 77000.0, "reason": None, "source": fb.LABEL_PLATFORM}
    assert len(calc.calls) == 1 and [x["quantity"] for x in calc.calls[0]] == [30, 30]               # no per-leg hedge calls
    assert [x["transaction_type"] for x in calc.calls[0]] == ["BUY", "SELL"]
    asyncio.run(fb.margins([(fb.LABEL_PLATFORM, calc)], [("b", "BANKNIFTY", legs)]))
    assert len(calc.calls) == 1                                                                     # cached for two minutes


def test_fb17_a_refused_session_falls_to_the_next_calculator_and_an_unlisted_contract_is_reported():
    _reset_margin_state()
    dead, live = FakeCalc(refuse=True), FakeCalc()
    legs = [bleg("buy", 54700, "put", 700.0)]
    out = asyncio.run(fb.margins([(fb.LABEL_PLATFORM, dead), (fb.LABEL_OWN, live)], [("a", "BANKNIFTY", legs)]))
    assert out["a"]["estimate"] == 77000.0 and out["a"]["source"] == fb.LABEL_OWN and len(dead.calls) == 1
    gone = asyncio.run(fb.margins([(fb.LABEL_OWN, live)], [("z", "BANKNIFTY", [bleg("buy", 99999, "put", 1.0)])]))
    assert gone["z"]["estimate"] is None and "not listed" in gone["z"]["reason"]
    fb._CACHE.clear()                                                              # a cached figure is good for two minutes
    none = asyncio.run(fb.margins([], [("n", "BANKNIFTY", legs)]))
    assert none["n"]["estimate"] is None and none["n"]["source"] is None


def test_fb18_read_live_legs_prices_only_contracts_that_traded_today(monkeypatch):
    from services.kite_live_feed import config as cfg, gateway as gw, platform_token as pt
    from services.kite_live_feed import feed as feed_mod

    class K:
        def instruments(self, ex):
            return [{"name": "BANKNIFTY", "expiry": date(2026, 11, 25), "strike": k, "instrument_type": "PE", "tradingsymbol": f"BN{int(k)}PE"}
                    for k in (53100.0, 54700.0)]

        def quote(self, keys):
            return {"NFO:BN54700PE": {"last_price": 650.0, "last_trade_time": "2026-10-30T10:15:00+05:30", "ohlc": {"close": 700.0}},
                    "NFO:BN53100PE": {"last_price": 200.0, "last_trade_time": "2026-10-29T15:20:00+05:30"}}      # yesterday's price

    async def refresh(db):
        return None

    async def status(db):
        return {"stored": True, "expired": False}

    monkeypatch.setattr(cfg, "enabled", lambda: True)
    monkeypatch.setattr(cfg, "get_api_key", lambda: "k")
    monkeypatch.setattr(cfg, "get_token", lambda: "t")
    monkeypatch.setattr(gw, "default_kite_factory", lambda k, t: K())
    monkeypatch.setattr(pt, "refresh_cache", refresh)
    monkeypatch.setattr(pt, "token_status", status)
    monkeypatch.setattr(feed_mod, "get_feed", lambda: SimpleNamespace(db=None))

    async def window():
        return WINDOW
    monkeypatch.setattr(market_freshness, "window", window)
    legs = [{"underlying": "BANKNIFTY", "kind": "option", "expiry": "2026-11-25", "strike": 54700, "option_type": "put"},
            {"underlying": "BANKNIFTY", "kind": "option", "expiry": "2026-11-25", "strike": 53100, "option_type": "put"},
            {"underlying": "BANKNIFTY", "kind": "option", "expiry": "2026-11-25", "strike": 11111, "option_type": "put"}]
    got = asyncio.run(fb.read_live_legs(legs))
    assert got["available"] and list(got["quotes"]) == ["0"] and got["quotes"]["0"]["last_price"] == 650.0
    assert [u["index"] for u in got["unresolved"]] == [2]                                           # unlisted: named, not priced
    monkeypatch.setattr(pt, "token_status", lambda db: _async({"stored": True, "expired": True}))
    off = asyncio.run(fb.read_live_legs(legs))
    assert off["available"] is False and off["quotes"] == {} and "no Kite login today" in off["reason"]


async def _async(v):
    return v


def test_fb19_the_real_regime_carries_as_of_not_date_and_the_board_is_not_stale(src):
    """Found on staging data: regime_fit.read_regime sends `as_of`; reading `date` made every answer 'stale, unknown date'."""
    top = owner_board()
    top["regime"] = {"available": True, "key": "bearish", "label": "Bearish", "as_of": "2026-10-29"}        # the real shape: no `date`
    src.v["fno_top"] = top
    p = build("fno_setups")
    assert p["as_of"] == "2026-10-29" and p["data_quality"]["stale"] is False
    assert not [n for n in blocks(p, "notice") if "unknown date" in n["text"]]


def test_fb20_calculators_that_all_refuse_their_session_ask_for_a_login_once(src):
    """Found on staging: the platform calculator object exists but Kite refuses its expired token. One login notice, no per-row noise."""
    src.v["fno_top"] = owner_board()
    src.v["margin_calculators"] = ([(fb.LABEL_PLATFORM, object())], {**NO_LOGIN, "platform_login": True})
    src.v["margin_estimates"] = lambda k, u, legs: {"estimate": None, "reason": fb.NO_CALCULATOR, "source": None}
    p = build("fno_setups")
    assert row_of(p, "fno_index", "BANKNIFTY")["cells"]["margin"] == "Needs login"
    assert len([n for n in blocks(p, "notice") if n.get("actions")]) == 1
    assert not [m for m in p["data_quality"]["missing"] if m.startswith("Margin for")]
    assert any("session was refused" in m for m in p["data_quality"]["missing"])


# ═════ Sector rotation (owner, 31 Oct 2026): "its a sector rotation intent so load the sector rotation heatmap" ═════
# SR-1 … SR-9 of test_reports/copilot_sector_rotation_20261031.md. MOCK — not real data.
@pytest.mark.parametrize("message, expected", [
    ("Which sectors are leading and lagging?", "sector_rotation"),
    ("Show sector rotation today", "sector_rotation"),
    ("Sector heatmap", "sector_rotation"),
    ("Which sector is strongest this week?", "sector_rotation"),
    ("best performing sectors", "sector_rotation"),
    ("are banks lagging other sectors?", "sector_rotation"),
    ("Where is smart money moving?", "smart_money"),
    ("FII DII flows this week", "smart_money"),
    ("Which F&O stocks show long build-up today?", "smart_money"),
    ("What is the market view today?", "market_view"),
])
def test_sr1_the_resolver_sends_sector_questions_to_the_sector_answer(message, expected):
    got = resolve_intent(message, "trader", None)
    assert got is not None and got.name == expected, message


def test_sr2_the_new_intent_is_wired_in_everywhere():
    from services import copilot_visual as cv
    assert "sector_rotation" in cv.INTENTS and "sector_rotation" in cv.BUILDERS and cv.AGENT_FOR["sector_rotation"] == "market_analyst"


def crow(sym, chg, w=5.0):
    return {"symbol": sym, "company_name": sym.title(), "industry": "X", "weight_pct": w, "close": 100.0,
            "prev_close": None if chg is None else round(100.0 / (1 + chg / 100), 2), "change_pct": chg,
            "move": None if chg is None else ("advance" if chg > 0 else "decline" if chg < 0 else "unchanged")}


def cons(rows, day="2026-10-29"):
    return {"index": "x", "sector": "x", "available": True, "reason": None, "list_date": "2026-09-30", "date": day,
            "count": len(rows), "breadth": {}, "rows": rows}


def three_sectors():
    return {"as_of": "2026-10-29", "sectors": [
        {"sector": "IT", "index": "Nifty IT", "date": "2026-10-29", "ret_1d_pct": 1.2, "ret_1w_pct": 2.5, "ret_1m_pct": -1.0},
        {"sector": "Pharma", "index": "Nifty Pharma", "date": "2026-10-29", "ret_1d_pct": 0.3, "ret_1w_pct": 7.1, "ret_1m_pct": 0.7},
        {"sector": "Cement", "index": "Nifty Cement", "date": "2026-10-29", "ret_1d_pct": -1.3, "ret_1w_pct": -1.8, "ret_1m_pct": -3.3},
        {"sector": "Realty", "index": "Nifty Realty", "date": "2026-10-29", "ret_1d_pct": 0.1, "ret_1w_pct": None, "ret_1m_pct": None}]}


def members_for(n=7):
    return [crow(f"S{i}", 3.0 - i * 0.7, w=10.0 - i) for i in range(n)] + [crow("NOPRICE", None, 1.0)]


def test_sr3_the_heatmap_first_leaders_first_and_each_sector_carries_its_five_strongest(src):
    src.v["sector_returns"] = three_sectors()
    src.v["sector_members"] = {"Nifty IT": cons(members_for()), "Nifty Pharma": cons(members_for(3)), "Nifty Cement": cons(members_for())}
    p = build("sector_rotation")
    assert p["title"] == "Sector rotation" and p["as_of"] == "2026-10-29" and p["mode"] == "eod"
    assert [(b["type"], b["id"]) for b in p["blocks"]] == [("kpis", "summary"), ("heatmap", "rotation")]
    cells = blocks(p, "heatmap")[0]["cells"]
    assert [c["label"] for c in cells] == ["Pharma", "IT", "Cement"]                 # 1-week return, best first; Realty has none: left out
    assert [c["value"] for c in cells] == [7.1, 2.5, -1.8]
    assert cells[1]["sub"] == "1d +1.20% · 1m −1.00%"
    it = cells[1]["members"]
    assert [m["label"] for m in it] == ["S0", "S1", "S2", "S3", "S4"]                # five, strongest on the day first; NOPRICE excluded
    assert [m["value"] for m in it] == [3.0, 2.3, 1.6, 0.9, 0.2] and it[0]["sub"] == "weight 10.00%"
    assert it[0]["ask"] == "Trade plan for S0"
    assert len(cells[0]["members"]) == 3                                              # fewer than five priced: what exists, no padding
    kp = {i["label"]: i for i in blocks(p, "kpis")[0]["items"]}
    assert kp["Leading"]["value"] == "Pharma" and kp["Leading"]["sub"] == "+7.10% over 1 week"
    assert kp["Lagging"]["value"] == "Cement" and kp["Sectors up today"]["value"] == "2 of 3"
    assert p["headline"]["text"] == "Pharma leads the week (+7.10%) and Cement lags (−1.80%)."
    assert "top 5 stocks" in blocks(p, "heatmap")[0]["note"] and "day's move" in blocks(p, "heatmap")[0]["note"]


def test_sr4_a_sector_whose_members_cannot_be_read_still_shows_its_tile(src):
    src.v["sector_returns"] = three_sectors()
    src.v["sector_members"] = {"Nifty IT": cons(members_for())}                       # Pharma and Cement raise
    p = build("sector_rotation")
    cells = {c["label"]: c for c in blocks(p, "heatmap")[0]["cells"]}
    assert "members" not in cells["Pharma"] and len(cells["IT"]["members"]) == 5
    assert any("Nifty Pharma" in m for m in p["data_quality"]["missing"])


def test_sr5_no_sector_data_is_said_and_nothing_is_drawn(src):
    src.fail.add("sector_returns")
    p = build("sector_rotation")
    assert not blocks(p, "heatmap") and "MOCK sector_returns down" in p["data_quality"]["missing"][0]


def test_sr6_members_older_than_the_previous_session_are_flagged_stale(src):
    src.v["sector_returns"] = three_sectors()
    src.v["sector_members"] = {"Nifty IT": cons(members_for(), day="2026-10-20")}
    p = build("sector_rotation")
    assert p["data_quality"]["stale"] is True and any("2026-10-20" in n["text"] or "20 Oct" in n["text"] for n in blocks(p, "notice"))


def test_sr7_the_contract_check_covers_members(src):
    src.v["sector_returns"] = three_sectors()
    src.v["sector_members"] = {"Nifty IT": cons(members_for())}
    p = build("sector_rotation")
    assert validate(p) == []
    bad = json.loads(json.dumps(p))
    blocks(bad, "heatmap")[0]["cells"][0]["members"] = [{"label": "X", "value": "not a number"}]
    assert any("members" in x for x in validate(bad))


def test_sr8_the_reader_asks_daas_for_one_index(monkeypatch):
    seen = {}

    async def fake(path, params=None):
        seen["call"] = (path, params)
        return {"available": True, "rows": [crow("A", 1.0)], "date": "2026-10-29"}
    monkeypatch.setattr(rd, "_daas", fake)
    got = asyncio.run(rd.sector_constituents("Nifty Bank"))
    assert seen["call"] == ("/desk/sector-constituents", {"index": "Nifty Bank"}) and got["rows"][0]["symbol"] == "A"
    async def unavailable(path, params=None):
        return {"available": False, "reason": "no constituent list for Nifty Bank", "rows": []}
    monkeypatch.setattr(rd, "_daas", unavailable)
    with pytest.raises(RuntimeError, match="no constituent list"):
        asyncio.run(rd.sector_constituents("Nifty Bank"))


# ═════ How much should I risk? (owner, 31 Oct 2026): a saved setting is not market data; capture the profile when none exists ═════
# PS-1 … PS-4 of test_reports/copilot_batch2_20261031.md. MOCK — not real data.
def test_ps1_no_saved_profile_says_so_asks_for_one_and_shows_no_stale_warning(src):
    """The owner's screenshot: the defaults were shown as 'Your risk profile (date unknown)', flagged stale."""
    p = build("position_size")                                                   # RISK_PROFILE: stored False
    assert p["data_quality"]["stale"] is False
    assert not [n for n in blocks(p, "notice") if "older than" in n["text"] or "unknown date" in n["text"]]
    n = next(b for b in blocks(p, "notice") if b.get("actions"))
    assert [a["kind"] for a in n["actions"]] == ["set_risk_profile"] and n["actions"][0]["label"] == "Set up your risk profile"
    assert "have not set a risk profile" in n["text"]
    limits = blocks(p, "kpis")[0]
    assert limits["title"] == "Default risk limits" and "platform defaults" in limits["note"].lower() and "not saved" in limits["note"].lower()
    assert p["headline"]["text"].startswith("You have no saved risk profile")
    row = next(r for r in p["data_quality"]["sources"] if r["name"] == "Your risk profile (risk_profiles)")
    assert row["status"] == "fresh" and row["as_of"] is None and "no profile saved" in row["note"]
    assert [b["type"] for b in p["blocks"]][:2] == ["notice", "kpis"]            # the ask comes before the figures


def test_ps2_a_saved_profile_is_not_stale_however_old_it_is(src):
    src.v["risk_profile"] = {**RISK_PROFILE, "stored": True, "profile": "balanced", "set_at": "2026-07-15T09:30:00+00:00"}
    p = build("position_size")
    assert p["data_quality"]["stale"] is False and not [n for n in blocks(p, "notice") if n.get("actions")]
    limits = blocks(p, "kpis")[0]
    assert limits["title"] == "Your risk limits" and limits["note"] == "balanced profile, set 15 Jul 2026"
    row = next(r for r in p["data_quality"]["sources"] if r["name"] == "Your risk profile (risk_profiles)")
    assert row["status"] == "fresh" and row["as_of"] == "2026-07-15"
    assert p["headline"]["text"] == "Your risk budget and today's usage."


def test_ps3_the_contract_check_knows_the_new_action(src):
    p = build("position_size")
    assert validate(p) == []
    bad = json.loads(json.dumps(p))
    next(b for b in bad["blocks"] if b.get("actions"))["actions"][0]["kind"] = "wire_money"
    assert any("action" in x for x in validate(bad))


def test_ps4_a_profile_that_cannot_be_read_is_missing_not_defaulted(src):
    src.fail.add("risk_profile")
    p = build("position_size")
    assert any("MOCK risk_profile down" in m for m in p["data_quality"]["missing"])
    assert not [n for n in blocks(p, "notice") if n.get("actions")]              # an unreadable profile is not "no profile"


# ═════ F&O build-up detail (owner, 31 Oct 2026): a build-up row or point opens the stock's option chain and futures ═════
def test_bd1_the_buildup_blocks_ask_for_the_fno_detail(src):
    p = build("smart_money")
    q = next(b for b in blocks(p, "quadrant") if b["id"] == "buildup")
    r = next(b for b in blocks(p, "ranked") if b["id"] == "strongest")
    assert q["detail"] == "fno" and r["detail"] == "fno"
    assert all(row["symbol"] for row in r["rows"])                                    # every row names the stock the detail opens
    assert not [b for b in p["blocks"] if b["type"] in ("heatmap", "kpis", "bars") and b.get("detail")]    # only the stock lists open it
    assert validate(p) == []
