"""The DSL backtest on the shared exit step (services/exit_rules.py, exit-rules-v1) and its new diagnostics.

Test cases TC-20 .. TC-26 (test_reports/p2_exits_backtest_TESTCASES.md). Every number is worked out by hand in the test.
No database: a scripted provider feeds the engine (MOCK — not real data)."""
from __future__ import annotations

import asyncio
import json
import math
import statistics
from datetime import date

import pytest

from services import desk_cost_card as cost_card
from services.strategy_engine import backtest as bt

D1, D2, D3, D4, D5 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)


class Provider:
    def __init__(self, dates, screens, bars, latest=None):
        self._dates, self._screens, self._bars = list(dates), screens, bars
        self._latest = latest
        self.basis = {"price_basis": "corp_action_adjusted", "universe_basis": "point_in_time"}

    async def prepare(self, spec, f, t):
        return None

    async def trading_dates(self, f, t):
        return list(self._dates)

    async def latest_date(self):
        if isinstance(self._latest, Exception):
            raise self._latest
        return self._latest or self._dates[-1]

    async def screen(self, spec, as_of):
        return [dict(r) for r in self._screens.get(as_of, [])]

    async def exit_bars(self, symbols, as_of):
        day = self._bars.get(as_of, {})
        return {s: dict(day[s]) for s in symbols if s in day}


def cand(sym, px, atr=None):
    return {"symbol": sym, "close": px, "adj_close": px, "adj_factor": 1.0, "atr14": atr, "accumulation_score": 0.5}


def ob(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def spec(**exit_):
    e = {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 30, **exit_}
    return {"version": "1", "asset_class": "STOCK", "name": "exit-test", "universe": {"type": "index", "ref": "NIFTY500"},
            "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]}, "exit": e,
            "ranking": {"by": "score", "limit": 20, "order": "desc"}, "rebalance": "daily"}


def run(monkeypatch, p, *, s=None, capital=10_000.0, positions=1, slippage=0.0, brokerage=0.0, cost=bt.COST_FLAT, **kw):
    monkeypatch.setattr(bt, "get_provider", lambda pool=None: p)
    return asyncio.run(bt.run_backtest(None, s or spec(), from_date=p._dates[0], to_date=p._dates[-1],
                                       starting_capital=capital, max_positions=positions, slippage_pct=slippage,
                                       brokerage_inr=brokerage, cost_model=cost, **kw))


# ── TC-20: a gap through the stop fills at the open ────────────────────────────────────────────────────────
def test_tc20_gap_through_the_stop_fills_at_the_open_not_the_stop(monkeypatch):
    # A at 100 → qty 100, stop 95. D2 opens at 90: the old engine booked 95 (−₹500); the open is 90 (−₹1,000).
    p = Provider([D1, D2], {D1: [cand("A", 100.0)]}, {D2: {"A": ob(90, 92, 88, 91)}})
    t = run(monkeypatch, p).trades[0]
    assert (t.exit_reason, t.exit_price, t.exit_fill, t.pnl_abs) == ("STOPLOSS", 90.0, "gap_open", -1000.0)


def test_tc20_a_bar_without_an_open_keeps_the_stop_fill(monkeypatch):
    p = Provider([D1, D2], {D1: [cand("A", 100.0)]}, {D2: {"A": {"high": 92, "low": 88, "close": 91}}})
    t = run(monkeypatch, p).trades[0]
    assert (t.exit_reason, t.exit_price, t.exit_fill) == ("STOPLOSS", 95.0, "level")


# ── TC-21: the trail, its reason, and the same-bar case ────────────────────────────────────────────────────
def test_tc21_a_trailed_exit_is_trailing_stop_and_the_trail_is_set_after_the_bar(monkeypatch):
    # entry 100, stop 95, target 115 (rr 3), ATR seed 2, k 2.
    # D2 O100 H110 L100 C109: TR = max(10, 10, 0) = 10 → ATR = (2·13 + 10)/14 = 2.5714; stop → 110 − 5.14 = 104.86.
    # D3 O106 H107 L104 C105: low 104 ≤ 104.86 → TRAILING_STOP at 104.86; pnl 100 × 4.86 = 486.
    s = spec(target_rr=3, trailing_atr_mult=2)
    p = Provider([D1, D2, D3], {D1: [cand("A", 100.0, atr=2.0)]}, {D2: {"A": ob(100, 110, 100, 109)}, D3: {"A": ob(106, 107, 104, 105)}})
    res = run(monkeypatch, p, s=s)
    t = res.trades[0]
    assert t.exit_reason == "TRAILING_STOP" and t.exit_price == pytest.approx(104.86) and t.exit_date == D3
    assert t.pnl_abs == pytest.approx(486.0)
    assert [h["reason"] for h in t.stop_history] == ["initial", "trailing_atr"]
    assert t.initial_stop == 95.0 and t.stoploss_price == pytest.approx(104.86)
    assert res.metrics["exit_reasons"] == {"TRAILING_STOP": 1}


def test_tc21_same_bar_high_then_low_does_not_exit_at_the_raised_stop(monkeypatch):
    # D2 H110 L96: the old engine raised the stop to 104.86 with the high and stopped out at it on the SAME bar.
    # Now the stop in force for D2 is 95; 96 > 95, no exit. D3 opens 101 below the new 104.86 → gap fill at 101.
    s = spec(target_rr=3, trailing_atr_mult=2)
    p = Provider([D1, D2, D3], {D1: [cand("A", 100.0, atr=2.0)]}, {D2: {"A": ob(100, 110, 96, 109)}, D3: {"A": ob(101, 103, 100, 102)}})
    t = run(monkeypatch, p, s=s).trades[0]
    assert t.exit_date == D3 and t.exit_reason == "TRAILING_STOP" and t.exit_price == 101.0 and t.exit_fill == "gap_open"


def test_tc21_a_missing_atr_is_not_replaced_by_two_percent(monkeypatch):
    s = spec(target_rr=3, trailing_atr_mult=2)
    p = Provider([D1, D2, D3], {D1: [cand("A", 100.0, atr=None)]}, {D2: {"A": ob(100, 110, 100, 109)}, D3: {"A": ob(106, 107, 104, 105)}})
    res = run(monkeypatch, p, s=s)
    t = res.trades[0]
    # The old engine trailed with 2 % of 100 = 2 → stop 106 and exited D3 at 106. Now the trail waits for 14 bars.
    assert t.exit_reason == "BACKTEST_END" and t.stop_history == [{"session": "2026-01-05", "stop": 95.0, "reason": "initial", "version": 1}]
    assert res.metrics["atr_unseeded_entries"] == 1


# ── TC-22: time is counted in sessions ─────────────────────────────────────────────────────────────────────
def test_tc22_time_exit_counts_sessions_not_calendar_days(monkeypatch):
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 12), date(2026, 1, 13)]
    bars = {d: {"A": ob(100, 101, 99, 100 + i)} for i, d in enumerate(days[1:], 1)}
    p = Provider(days, {days[0]: [cand("A", 100.0)]}, bars)
    t = run(monkeypatch, p, s=spec(max_hold_days=3)).trades[0]
    # Calendar days would have closed it on 12 Jan (7 days ≥ 3); three sessions held is 13 Jan, at its close 103.
    assert (t.exit_reason, t.exit_date, t.exit_price, t.holding_sessions, t.holding_days) == ("TIME", days[3], 103.0, 3, 8)


# ── TC-23: next-open entry is an option; the default is labelled ───────────────────────────────────────────
def test_tc23_next_open_entry_and_the_default_label(monkeypatch):
    p = Provider([D1, D2, D3], {D1: [cand("A", 100.0)], D3: [cand("B", 50.0)]},
                 {D2: {"A": ob(102, 105, 101, 104)}, D3: {"A": ob(104, 108, 103, 107)}})
    res = run(monkeypatch, p, entry_timing="next_open", positions=2)
    t = res.trades[0]
    # Entered at D2's open 102 (not D1's close 100); stop 102 × 0.95 = 96.9; B, signalled on the last day, never fills.
    assert (t.entry_date, t.entry_price, t.initial_stop) == (D2, 102.0, pytest.approx(96.9))
    assert res.metrics["entry_timing"] == "next_open" and res.metrics["entries_lapsed_no_open"] == 1
    assert run(monkeypatch, Provider([D1, D2], {D1: [cand("A", 100.0)]}, {D2: {"A": ob(100, 101, 99, 100)}})).metrics["entry_timing"] == "signal_close"


def test_tc23_a_next_open_order_with_no_open_lapses(monkeypatch):
    p = Provider([D1, D2, D3], {D1: [cand("A", 100.0)]}, {D2: {"A": {"high": 101, "low": 99, "close": 100}}})
    res = run(monkeypatch, p, entry_timing="next_open")
    assert res.trades == [] and res.metrics["entries_lapsed_no_open"] == 1 and res.metrics["signals_taken"] == 0


# ── TC-24: the new diagnostics on a hand-computed run ──────────────────────────────────────────────────────
def _two_trade_run(monkeypatch, **kw):
    # Capital 10,000, one slot, no costs. D1 A at 100 → 100 sh, stop 95, target 110. D2 C is a signal with no slot.
    # D3 A hits 110 (TARGET, +1,000, R +2.0, 2 sessions); B at 50 → 220 sh (11,000 / 50), stop 47.5.
    # D4 B opens at 46 (gap): STOPLOSS at 46, −880, R −880 / (220 × 2.5) = −1.6, 1 session.
    p = Provider([D1, D2, D3, D4], {D1: [cand("A", 100.0)], D2: [cand("C", 10.0)], D3: [cand("B", 50.0)], D4: []},
                 {D2: {"A": ob(101, 104, 99, 103)}, D3: {"A": ob(104, 111, 103, 110)}, D4: {"B": ob(46, 47, 45, 46)}})
    return run(monkeypatch, p, **kw)


def test_tc24_expectancy_payoff_exposure_turnover_capital_and_signals(monkeypatch):
    res = _two_trade_run(monkeypatch)
    m = res.metrics
    assert [(t.symbol, t.exit_reason, t.pnl_abs, t.r_multiple, t.holding_sessions) for t in res.trades] == [
        ("A", "TARGET", 1000.0, 2.0, 2), ("B", "STOPLOSS", -880.0, -1.6, 1)]
    assert m["expectancy_rs"] == 60.0                       # (1,000 − 880) / 2
    assert m["expectancy_r"] == pytest.approx(0.2)          # (2.0 − 1.6) / 2
    assert m["expectancy_rs_per_session"] == 40.0           # 120 / 3 sessions
    assert m["expectancy_r_per_session"] == pytest.approx(0.1333, abs=1e-4)
    assert m["payoff_ratio"] == 1.14 and m["profit_factor"] == 1.14 and m["win_rate"] == 50.0
    # Daily equity 10,000 · 10,300 · 11,000 · 10,120; exposure 10,000 · 10,300 · 11,000 · 0.
    assert [p["equity"] for p in res.equity_curve] == [10_000.0, 10_300.0, 11_000.0, 10_120.0]
    assert (m["days"], m["days_invested_pct"], m["avg_gross_exposure_pct"], m["max_gross_exposure_pct"]) == (4, 75.0, 75.0, 100.0)
    # Deployed (quantity × entry): 10,000 · 10,000 · 11,000 · 0 → avg 7,750, max 11,000; as % of equity (1 + 0.9709 + 1 + 0)/4.
    assert (m["avg_capital_deployed_rs"], m["max_capital_deployed_rs"], m["avg_capital_deployed_pct"]) == (7750.0, 11000.0, 74.27)
    # Traded value 100 × (100 + 110) + 220 × (50 + 46) = 42,120; mean equity 10,355 → 4.068×.
    assert (m["traded_value_rs"], m["turnover_x"]) == (42120.0, 4.068)
    assert m["turnover_x_annualised"] == round(42120 / 10355 * 252 / 4, 3)
    # Signals: A, C, B seen; A and B taken; C had no slot.
    assert (m["signals_seen"], m["signals_taken"], m["signals_dropped_no_slot"], m["signals_already_held"]) == (3, 2, 1, 0)
    assert m["signals_taken_pct"] == 66.67


def test_tc24_sharpe_and_sortino_from_the_daily_curve(monkeypatch):
    m = _two_trade_run(monkeypatch).metrics
    rets = [0.0, 0.03, 11_000 / 10_300 - 1, 10_120 / 11_000 - 1]
    mean, sd = statistics.fmean(rets), statistics.stdev(rets)
    down = math.sqrt(sum(min(r, 0) ** 2 for r in rets) / 4)
    assert m["sharpe"] == round(mean / sd * math.sqrt(252), 3)
    assert m["sortino"] == round(mean / down * math.sqrt(252), 3)
    assert m["daily_returns"] == 4


def test_tc24_slippage_sweep_reprices_the_same_trades(monkeypatch):
    sw = _two_trade_run(monkeypatch).metrics["slippage_sweep"]
    assert list(sw["by_bps"]) == ["0", "5", "10", "20"]
    assert sw["by_bps"]["0"]["net_pnl_rs"] == 120.0
    # 10 bps: A 100 × (110 × 0.999 − 100 × 1.001) = 979; B 220 × (46 × 0.999 − 50 × 1.001) = −901.12 → 77.88
    assert sw["by_bps"]["10"]["net_pnl_rs"] == 77.88
    assert sw["by_bps"]["20"]["net_pnl_rs"] < sw["by_bps"]["10"]["net_pnl_rs"] < sw["by_bps"]["5"]["net_pnl_rs"] < 120.0


# ── TC-25: the desk cost card; the flat model stays selectable ─────────────────────────────────────────────
def test_tc25_desk_cost_card_charges_both_sides_without_double_slippage(monkeypatch):
    p = Provider([D1, D2], {D1: [cand("A", 100.0)]}, {D2: {"A": ob(104, 111, 103, 110)}})
    res = run(monkeypatch, p, cost=bt.COST_CARD, brokerage=20.0, slippage=0.0005)
    t = res.trades[0]
    no_slip = {**cost_card.SNAPSHOT, "slippage_pct_per_side": 0.0}
    buy = cost_card.order_side("equity_delivery", "BUY", t.quantity * t.entry_price, no_slip)
    sell = cost_card.order_side("equity_delivery", "SELL", t.quantity * t.exit_price, no_slip)
    assert buy["slippage"] == 0.0 and buy["stt"] > 0 and buy["stamp"] > 0
    assert t.entry_charges == buy["total"] and t.exit_charges == sell["total"]
    assert t.pnl_abs == pytest.approx(t.quantity * (t.exit_price - t.entry_price) - buy["total"] - sell["total"])
    # Pinned: 99 sh at 100.05 (10,000 / 100.05 = 99.95 → 99), target 100.05 + 2 × 5.0025 = 110.055 → exit 110.055 × 0.9995 = 109.99997
    assert (t.quantity, round(t.entry_price, 4), round(t.exit_price, 4)) == (99, 100.05, 110.0)
    # Buy 99 × 100.05 = 9,904.95: brokerage 20 + STT 0.1 % 9.90 + exchange 0.30 + SEBI 0.01 + stamp 0.015 % 1.49 + GST 18 % of
    # (20 + 0.30 + 0.01) 3.66 = 35.36. Sell 10,889.997: 20 + STT 10.89 + 0.33 + 0.01 + GST 3.66 = 34.89 (no stamp on a sale).
    assert (t.entry_charges, t.exit_charges) == (35.36, 34.89)
    assert res.metrics["cost_model"] == "desk-cost-v2"
    flat = run(monkeypatch, Provider([D1, D2], {D1: [cand("A", 100.0)]}, {D2: {"A": ob(104, 111, 103, 110)}}),
               cost=bt.COST_FLAT, brokerage=20.0, slippage=0.0005).trades[0]
    assert (flat.entry_charges, flat.exit_charges, flat.brokerage) == (20.0, 20.0, 40.0)


def test_tc25_unknown_cost_model_or_entry_timing_is_refused(monkeypatch):
    p = Provider([D1], {}, {})
    with pytest.raises(ValueError, match="cost_model"):
        run(monkeypatch, p, cost="zerodha")
    with pytest.raises(ValueError, match="entry_timing"):
        run(monkeypatch, p, entry_timing="vwap")


# ── TC-26: provenance written by persist_run; old runs stay readable ───────────────────────────────────────
class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    def transaction(self):
        conn = self

        class _T:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _T()


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        conn = self.conn

        class _A:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _A()


def test_tc26_persist_run_writes_the_watermark_code_version_and_trade_detail(monkeypatch):
    res = _two_trade_run(monkeypatch)
    assert res.metrics["data_watermark"] == {"latest_session_available": "2026-01-08", "window_last_session": "2026-01-08"}
    cv = res.metrics["code_version"]
    assert len(cv["engine_sha256"]) == 64 and cv["exit_rules_version"] == "exit-rules-v1"
    assert cv["git_sha_source"] in ("env", "git", None)
    pool = _Pool()
    asyncio.run(bt.persist_run(pool, strategy_id="s", version_id="v", spec=spec(), result=res, from_date=D1, to_date=D4,
                               triggered_by=None))
    run_sql, run_args = pool.conn.calls[0]
    assert "snapshot_as_of" in run_sql and run_args[-1] == D4
    stored = json.loads(run_args[5])
    assert stored["code_version"] == cv and stored["time_basis"] == "sessions" and stored["gap_fill"] == "open"
    trade_sql, trade_args = pool.conn.calls[1]
    meta = json.loads(trade_args[-1])
    assert meta["holding_sessions"] == 2 and meta["r_multiple"] == 2.0 and meta["stop_history"][0]["reason"] == "initial"


def test_tc26_a_watermark_read_failure_is_recorded_not_guessed(monkeypatch):
    p = Provider([D1, D2], {D1: [cand("A", 100.0)]}, {D2: {"A": ob(100, 101, 99, 100)}}, latest=RuntimeError("daas down"))
    res = run(monkeypatch, p)
    assert res.metrics["data_watermark"]["latest_session_available"] is None
    assert "daas down" in res.metrics["data_watermark"]["error"]
    pool = _Pool()
    asyncio.run(bt.persist_run(pool, strategy_id="s", version_id="v", spec=spec(), result=res, from_date=D1, to_date=D2,
                               triggered_by=None))
    assert pool.conn.calls[0][1][-1] is None


def test_tc26_an_old_metrics_dict_still_computes(monkeypatch):
    # The pre-exit-rules call shape (no daily curve, no counters) keeps returning the old keys only.
    m = bt._compute_metrics([], 100.0, 100.0, [])
    assert m["trade_count"] == 0 and "signals_seen" not in m and "slippage_sweep" not in m
