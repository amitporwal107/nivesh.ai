"""Position-sizing tests for the Strategy Builder backtest engine.

Before this suite, `backtest.py` carried no quantity: `pnl_abs` was the profit on
ONE share and that per-share rupee figure was added to an equity series starting at
`starting_capital`, so `total_return_pct` and `max_drawdown_pct` were one-share
rupees expressed as a percentage of a ten-lakh account. Thirty trades of a
5-%-stop strategy moved a Rs 10,00,000 account 0.36 %.

Every number asserted below is computed BY HAND in the comment above it, from a
fixture whose prices, slippage and brokerage are chosen so the arithmetic is exact
(slippage 0, brokerage Rs 20/side). The point is to pin the arithmetic, not to
re-derive the engine's own answer from the engine.

No DB: a fake market-data provider feeds the engine a calendar, per-date screen
rows and per-date adjusted exit bars, injected over `backtest.get_provider`.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from services.strategy_engine import backtest as bt


# ── Fixture plumbing ────────────────────────────────────────────────
D1, D2, D3, D4 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)


class FakeProvider:
    """Mirrors `MarketDataProvider`'s async surface with scripted data."""

    def __init__(self, dates, screens, bars):
        self._dates = list(dates)
        self._screens = screens            # {date: [screen rows]}
        self._bars = bars                  # {date: {symbol: {high, low, close}}}
        self.basis = {"price_basis": "corp_action_adjusted",
                      "universe_basis": "point_in_time"}
        self.screen_calls = []

    async def prepare(self, spec, from_date, to_date):
        return None

    async def trading_dates(self, from_date, to_date):
        return list(self._dates)

    async def latest_date(self):
        return self._dates[-1]

    async def screen(self, spec, as_of):
        self.screen_calls.append(as_of)
        return [dict(r) for r in self._screens.get(as_of, [])]

    async def exit_bars(self, symbols, as_of):
        day = self._bars.get(as_of, {})
        return {s: dict(day[s]) for s in symbols if s in day}


def cand(symbol: str, px: float, score: float = 0.5) -> dict:
    """A screen row shaped like the provider's: adjusted close + raw fallback."""
    return {"symbol": symbol, "close": px, "adj_close": px, "adj_factor": 1.0,
            "atr14": None, "accumulation_score": score}


def bar(high: float, low: float, close: float) -> dict:
    return {"high": high, "low": low, "close": close}


def spec(*, stoploss_pct=5, target_rr=2, max_hold_days=30) -> dict:
    return {
        "version": "1",
        "asset_class": "STOCK",
        "name": "sizing-test",
        "universe": {"type": "index", "ref": "NIFTY500"},
        "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]},
        "exit": {"stoploss_pct": stoploss_pct, "target_rr": target_rr,
                 "max_hold_days": max_hold_days},
        "ranking": {"by": "score", "limit": 20, "order": "desc"},
        "rebalance": "daily",
    }


def run(monkeypatch, provider, *, capital, max_positions, s=None,
        slippage_pct=0.0, brokerage_inr=20.0, cost_model=bt.COST_FLAT):
    # The hand arithmetic in this file is the FLAT model (₹20 a side, nothing else), so it names it: since
    # exit-rules-v1 the engine's default is the desk cost card (desk-cost-v2: brokerage + STT, exchange, SEBI, stamp,
    # GST), whose own arithmetic is pinned in tests/test_backtest_exit_rules.py. These numbers are unchanged.
    monkeypatch.setattr(bt, "get_provider", lambda pool=None: provider)
    return asyncio.run(bt.run_backtest(
        None, s or spec(),
        from_date=provider._dates[0], to_date=provider._dates[-1],
        starting_capital=capital, max_positions=max_positions,
        slippage_pct=slippage_pct, brokerage_inr=brokerage_inr, cost_model=cost_model,
    ))


# ── 1. Equal-weight slot sizing across two positions ────────────────
def test_two_position_run_sizes_each_entry_to_an_equal_weight_slot(monkeypatch):
    """Rs 1,00,000 / 2 slots, A at Rs 100 and B at Rs 200, both entered on D1.

    BY HAND (slippage 0 so entry_price == adj_close; brokerage Rs 20/side):

      A: equity 1,00,000 → slot 50,000 → qty floor(50,000/100) = 500
         cost 500*100 + 20 = 50,020      → cash 49,980, mark(A) = 100
      B: equity = cash 49,980 + 500*100 = 99,980 → slot 49,990
         qty floor(49,990/200) = 249
         cost 249*200 + 20 = 49,820      → cash 160,  mark(B) = 200
      D1 close equity = 160 + 500*100 + 249*200 = 99,960  (= capital - 2*20 entry fees)

      A plan: stop 100*0.95 = 95, target 100 + (100-95)*2 = 110
      B plan: stop 190,            target 220

      D2: A bar high 110 ≥ target → TARGET at 110
            pnl_abs = 500*(110-100) - 40 = +4,960
            cash = 160 + 500*110 - 20 = 55,140
          B bar low 189 ≤ stop 190  → STOPLOSS at 190
            pnl_abs = 249*(190-200) - 40 = -2,530
            cash = 55,140 + 249*190 - 20 = 1,02,430
      ending capital 1,00,000 + 4,960 - 2,530 = 1,02,430
      total_return_pct = 2,430 / 1,00,000 = +2.43 %
    """
    p = FakeProvider(
        [D1, D2],
        {D1: [cand("A", 100.0, 0.9), cand("B", 200.0, 0.8)], D2: []},
        {D2: {"A": bar(110.0, 99.0, 109.0), "B": bar(201.0, 189.0, 190.0)}},
    )
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2)

    by_sym = {t.symbol: t for t in res.trades}
    assert by_sym["A"].quantity == 500
    assert by_sym["B"].quantity == 249

    assert by_sym["A"].exit_reason == "TARGET"
    assert by_sym["A"].exit_price == pytest.approx(110.0)
    assert by_sym["A"].pnl_abs == pytest.approx(4_960.0)
    # pnl_pct deliberately stays the PER-SHARE percentage move, not a portfolio figure.
    assert by_sym["A"].pnl_pct == pytest.approx(10.0)

    assert by_sym["B"].exit_reason == "STOPLOSS"
    assert by_sym["B"].pnl_abs == pytest.approx(-2_530.0)
    assert by_sym["B"].pnl_pct == pytest.approx(-5.0)

    m = res.metrics
    assert m["sizing_basis"] == "portfolio"
    assert m["max_positions"] == 2
    assert m["ending_capital"] == pytest.approx(102_430.0)
    assert m["total_return_pct"] == pytest.approx(2.43)
    assert m["trade_count"] == 2
    assert m["win_rate"] == pytest.approx(50.0)
    # 4,960 / 2,530 = 1.9605…
    assert m["profit_factor"] == pytest.approx(1.96)
    assert m["skipped_insufficient_cash"] == 0
    assert m["skipped_min_quantity"] == 0
    # Mark-to-market daily series: D1 99,960 (peak seeded at capital) → -0.04 %
    assert [pt["equity"] for pt in res.equity_curve] == [99_960.0, 102_430.0]
    assert res.equity_curve[0]["drawdown"] == pytest.approx(-0.04)
    assert m["max_drawdown_pct"] == pytest.approx(-0.04)


def test_total_return_pct_is_the_real_percentage_move_of_the_account(monkeypatch):
    """The headline metric must be (ending - starting) / starting, from the same
    equity the curve ends on. Under the per-share bug the same fixture printed
    (4,960/500 - 2,530/249) ≈ Rs -0.24 on Rs 1,00,000 = -0.00 %."""
    p = FakeProvider(
        [D1, D2],
        {D1: [cand("A", 100.0, 0.9), cand("B", 200.0, 0.8)], D2: []},
        {D2: {"A": bar(110.0, 99.0, 109.0), "B": bar(201.0, 189.0, 190.0)}},
    )
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2)
    m = res.metrics
    expected = round((m["ending_capital"] - m["starting_capital"])
                     / m["starting_capital"] * 100.0, 2)
    assert m["total_return_pct"] == pytest.approx(expected)
    assert m["total_return_pct"] == pytest.approx(2.43)
    # ending capital is exactly the last point of the mark-to-market curve
    assert res.equity_curve[-1]["equity"] == pytest.approx(m["ending_capital"])
    # The per-share artefact: one share of each trade nets +9.92 and -10.16 → ~0 %.
    per_share = sum(t.pnl_abs / t.quantity for t in res.trades)
    assert abs(round(per_share / 100_000.0 * 100.0, 2)) == pytest.approx(0.0)


# ── 2. Cash runs out ────────────────────────────────────────────────
def _cash_exhaustion_provider() -> FakeProvider:
    """D1 buys A at Rs 100 with half the book; by D2 A has run to Rs 190, so the
    slot the compounding equity implies is bigger than the cash left."""
    return FakeProvider(
        [D1, D2],
        {D1: [cand("A", 100.0, 0.9)], D2: [cand("B", 1_000.0, 0.8)]},
        {D2: {"A": bar(190.0, 180.0, 190.0)}},
    )


def test_an_entry_the_cash_cannot_afford_is_skipped_and_counted(monkeypatch):
    """BY HAND (capital 1,00,000, 2 slots, stop 5 %, target_rr 20 so A never exits):

      D1  A at 100: slot 50,000 → qty 500, cost 50,020 → cash 49,980
          A plan: stop 95, target 100 + 5*20 = 200 (unreachable in this fixture)
          D1 close equity = 49,980 + 500*100 = 99,980
      D2  A bar 180/190: no stop (180 > 95), no target (190 < 200), held 1 < 30
          mark(A) = 190 → equity = 49,980 + 500*190 = 1,44,980 → slot 72,490
          B at 1,000: qty floor(72,490/1,000) = 72, cost 72*1,000 + 20 = 72,020
          72,020 > cash 49,980 → SKIPPED (insufficient cash), counted, not dropped
          D2 close equity = 1,44,980
      force-close A on D2 at close 190:
          pnl_abs = 500*(190-100) - 40 = +44,960
          cash = 49,980 + 500*190 - 20 = 1,44,960 = ending capital
          total_return_pct = +44.96 %  (the per-share bug printed +0.05 %)
    """
    p = _cash_exhaustion_provider()
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2,
              s=spec(stoploss_pct=5, target_rr=20))
    m = res.metrics

    assert [t.symbol for t in res.trades] == ["A"]
    assert res.trades[0].quantity == 500
    assert res.trades[0].exit_reason == "BACKTEST_END"
    assert res.trades[0].pnl_abs == pytest.approx(44_960.0)
    assert m["skipped_insufficient_cash"] == 1
    assert m["skipped_min_quantity"] == 0
    assert m["skipped_entries"] == 1
    assert m["ending_capital"] == pytest.approx(144_960.0)
    assert m["total_return_pct"] == pytest.approx(44.96)
    # Under the per-share bug this run printed (190-100-40)/1,00,000 = +0.05 %.
    assert m["total_return_pct"] != pytest.approx(0.05)
    # The last curve point is restated after the force-close, so curve == ending capital.
    assert res.equity_curve[-1]["equity"] == pytest.approx(144_960.0)


# ── 3. A share too expensive for one whole slot ─────────────────────
def test_a_candidate_too_expensive_for_one_share_of_a_slot_is_skipped_and_counted(monkeypatch):
    """Capital 1,00,000 over 10 slots = Rs 10,000 a slot; the share costs Rs 12,000.
    floor(10,000 / 12,000) = 0 → no position, counted as skipped_min_quantity,
    and the run still reports its sizing basis so a reader knows why nothing traded."""
    p = FakeProvider([D1, D2], {D1: [cand("X", 12_000.0)], D2: []}, {})
    res = run(monkeypatch, p, capital=100_000.0, max_positions=10)
    m = res.metrics

    assert res.trades == []
    assert m["trade_count"] == 0
    assert m["skipped_min_quantity"] == 1
    assert m["skipped_insufficient_cash"] == 0
    assert m["sizing_basis"] == "portfolio"
    assert m["max_positions"] == 10
    assert m["ending_capital"] == pytest.approx(100_000.0)
    # Flat book, flat curve: one point per trading day, no invented drawdown.
    assert [pt["equity"] for pt in res.equity_curve] == [100_000.0, 100_000.0]


# ── 4. Open drawdown deeper than the closed loss ────────────────────
def _open_drawdown_provider() -> FakeProvider:
    return FakeProvider(
        [D1, D2, D3, D4],
        {D1: [cand("A", 100.0, 0.9)], D2: [], D3: [], D4: []},
        {
            D2: {"A": bar(100.0, 60.0, 60.0)},   # deep dip, above the 50 % stop
            # D3: NO bar for A — last known mark (60) must carry forward
            D4: {"A": bar(98.0, 95.0, 98.0)},    # recovers to a small net loss
        },
    )


def test_mark_to_market_drawdown_sees_the_dip_a_closed_trade_series_cannot(monkeypatch):
    """BY HAND (capital 1,00,000, 2 slots, stop 50 %, target_rr 2 → target 200):

      D1  A at 100: slot 50,000 → qty 500, cost 50,020 → cash 49,980
          D1 equity = 49,980 + 500*100 = 99,980   → dd vs peak 1,00,000 = -0.02 %
          (only ONE entry fee of Rs 20 was paid, unlike the two-position fixture)
      D2  bar 100/60/60: low 60 > stop 50, high 100 < 200, held 1 < 30 → still open
          mark 60 → equity = 49,980 + 500*60 = 79,980 → dd = -20.02 %
      D3  no bar at all → carry mark 60 forward (never invent a price)
          equity = 79,980 → dd = -20.02 %
      D4  bar 98/95/98: still open, mark 98 → equity = 49,980 + 500*98 = 98,980
      force-close on D4 at 98: pnl_abs = 500*(98-100) - 40 = -1,040
          cash = 49,980 + 500*98 - 20 = 98,960 = ending capital

      max_drawdown_pct = -20.02 %.  A closed-trade-only series (what the engine
      used to build) only ever sees the final -1,040, i.e. -1.04 %.
    """
    p = _open_drawdown_provider()
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2,
              s=spec(stoploss_pct=50, target_rr=2))
    m = res.metrics

    assert res.trades[0].quantity == 500
    assert res.trades[0].pnl_abs == pytest.approx(-1_040.0)
    assert m["ending_capital"] == pytest.approx(98_960.0)

    equities = [pt["equity"] for pt in res.equity_curve]
    assert equities == [99_980.0, 79_980.0, 79_980.0, 98_960.0]
    assert res.equity_curve[2]["date"] == str(D3)      # carried-forward mark

    assert m["max_drawdown_pct"] == pytest.approx(-20.02)
    closed_only_dd = round((100_000.0 - 1_040.0 - 100_000.0) / 100_000.0 * 100.0, 2)
    assert closed_only_dd == pytest.approx(-1.04)
    assert m["max_drawdown_pct"] < closed_only_dd      # the open dip is now visible


def test_a_day_with_no_bar_carries_the_last_mark_and_does_not_close_the_trade(monkeypatch):
    """D3 has no bar for A: the position stays open, its mark is the last real
    close, and no exit is manufactured out of a missing price."""
    p = _open_drawdown_provider()
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2,
              s=spec(stoploss_pct=50, target_rr=2))
    assert len(res.trades) == 1
    assert res.trades[0].exit_date == D4
    assert res.trades[0].exit_reason == "BACKTEST_END"
    d3 = next(pt for pt in res.equity_curve if pt["date"] == str(D3))
    d2 = next(pt for pt in res.equity_curve if pt["date"] == str(D2))
    assert d3["equity"] == pytest.approx(d2["equity"])


# ── 5. win_rate and profit_factor share one (net) basis ─────────────
def test_a_gross_gain_swallowed_by_costs_counts_as_a_loss_for_both_metrics(monkeypatch):
    """BY HAND (capital Rs 1,000, 1 slot, stop 1 %, target_rr 2):

      D1  A at 900: slot 1,000 → qty floor(1,000/900) = 1
          cost 900 + 20 = 920 → cash 80; D1 equity = 80 + 900 = 980
          plan: stop 891, target 900 + 9*2 = 918
      D2  bar high 918 ≥ target → TARGET at 918
          pnl_pct = (918-900)/900 = +2.00 %   (gross, per share — unchanged meaning)
          pnl_abs = 1*(918-900) - 40 = -22    (net of both brokerage legs)
          cash = 80 + 918 - 20 = 978 = ending capital → total_return -2.2 %

      The old split called this a WIN (pnl_pct > 0) while profit_factor read the
      same trade as a loss (pnl_abs < 0): win_rate 100 % with profit_factor 0.
      Both now read net pnl_abs → win_rate 0 %, profit_factor 0.0.
    """
    p = FakeProvider([D1, D2], {D1: [cand("A", 900.0)], D2: []},
                     {D2: {"A": bar(918.0, 900.0, 918.0)}})
    res = run(monkeypatch, p, capital=1_000.0, max_positions=1,
              s=spec(stoploss_pct=1, target_rr=2))
    t, m = res.trades[0], res.metrics

    assert t.quantity == 1
    assert t.pnl_pct == pytest.approx(2.0)
    assert t.pnl_abs == pytest.approx(-22.0)
    assert m["trade_count"] == 1
    assert m["win_rate"] == pytest.approx(0.0)        # was 100.0 on the pnl_pct split
    assert m["profit_factor"] == pytest.approx(0.0)   # 0 profit / 22 loss, not None
    assert m["ending_capital"] == pytest.approx(978.0)
    assert m["total_return_pct"] == pytest.approx(-2.2)

    # The incoherent pair, PINNED so nobody rediscovers it as a bug: avg_loss_pct is
    # a GROSS PER-SHARE percentage averaged over a bucket defined by NET RUPEES, so
    # here it is POSITIVE (+2.0 %) on a trade that lost money. This is why the rupee
    # pair below is the one to display.
    assert m["avg_loss_pct"] == pytest.approx(2.0)
    assert m["avg_win_pct"] == pytest.approx(0.0)      # no net winners to average
    # The coherent pair, in rupees, over the same buckets as win_rate/profit_factor.
    assert m["avg_loss_abs"] == pytest.approx(-22.0)
    assert m["avg_win_abs"] == pytest.approx(0.0)


def test_the_rupee_averages_agree_with_win_rate_and_profit_factor(monkeypatch):
    """avg_win_abs / avg_loss_abs are the mean net pnl_abs of the SAME buckets that
    win_rate counts and profit_factor divides, so the three cannot disagree.

    BY HAND (capital 1,00,000, 2 slots, stop 5 %, target_rr 2 → +10 % targets):
      D1 A@100 → qty 500 (slot 50,000);  B@200 → qty 249 (slot 49,990), cash 160
      D2 A TARGET@110 → +500*10 - 40 = +4,960 ;  B STOPLOSS@190 → -249*10 - 40 = -2,530
         cash = 160 + 55,000 - 20 + 47,310 - 20 = 1,02,430
      D3 C@100: equity 1,02,430 → slot 51,215 → qty 512, cost 51,220 → cash 51,210
      D4 C TARGET@110 → +512*10 - 40 = +5,080
         cash = 51,210 + 56,320 - 20 = 1,07,510 = ending capital (+7.51 %)

      wins {4,960, 5,080} → avg_win_abs = 10,040/2 = +5,020
      losses {-2,530}     → avg_loss_abs = -2,530
      win_rate = 2/3 = 66.67 %;  profit_factor = 10,040/2,530 = 3.97
      avg_win_pct = 10.0 and avg_loss_pct = -5.0 (per-share, unchanged meaning)
    """
    p = FakeProvider(
        [D1, D2, D3, D4],
        {D1: [cand("A", 100.0, 0.9), cand("B", 200.0, 0.8)], D2: [],
         D3: [cand("C", 100.0, 0.7)], D4: []},
        {D2: {"A": bar(110.0, 99.0, 109.0), "B": bar(201.0, 189.0, 190.0)},
         D4: {"C": bar(110.0, 99.0, 109.0)}},
    )
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2)
    m = res.metrics

    assert {t.symbol: t.quantity for t in res.trades} == {"A": 500, "B": 249, "C": 512}
    assert m["trade_count"] == 3
    assert m["win_rate"] == pytest.approx(66.67)
    assert m["avg_win_abs"] == pytest.approx(5_020.0)
    assert m["avg_loss_abs"] == pytest.approx(-2_530.0)
    assert m["profit_factor"] == pytest.approx(3.97)
    assert m["ending_capital"] == pytest.approx(107_510.0)
    assert m["total_return_pct"] == pytest.approx(7.51)
    # The percentage pair keeps its per-share meaning and is NOT the rupee pair.
    assert m["avg_win_pct"] == pytest.approx(10.0)
    assert m["avg_loss_pct"] == pytest.approx(-5.0)

    # Mutual consistency: win_rate's bucket sizes times the rupee averages must
    # reproduce profit_factor.
    n_wins = round(m["win_rate"] / 100.0 * m["trade_count"])
    n_losses = m["trade_count"] - n_wins
    assert (n_wins, n_losses) == (2, 1)
    assert (m["avg_win_abs"] * n_wins) / abs(m["avg_loss_abs"] * n_losses) \
        == pytest.approx(m["profit_factor"], abs=0.01)


# ── 6. Costs and compounding ────────────────────────────────────────
def test_brokerage_is_flat_per_side_not_per_share(monkeypatch):
    """500 shares still pay Rs 40 round-trip, not Rs 20,000."""
    p = FakeProvider([D1, D2], {D1: [cand("A", 100.0)], D2: []},
                     {D2: {"A": bar(110.0, 99.0, 109.0)}})
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2)
    t = res.trades[0]
    assert t.quantity == 500
    assert t.brokerage == pytest.approx(40.0)
    # gross 500*(110-100) = 5,000; net must be exactly 5,000 - 40
    assert t.pnl_abs == pytest.approx(5_000.0 - 40.0)


def test_slot_size_compounds_off_current_equity_not_starting_capital(monkeypatch):
    """After D2 banks a gain the next slot is larger, because the slot is a share
    of CURRENT equity.

    BY HAND (capital 1,00,000, 2 slots, stop 5 %, target_rr 2):
      D1 A at 100 → qty 500, cash 49,980
      D2 A targets at 110 → cash 49,980 + 55,000 - 20 = 1,04,960, book flat
         then B at 100: equity 1,04,960 → slot 52,480 → qty 524
         (starting-capital sizing would have bought floor(50,000/100) = 500)
    """
    p = FakeProvider(
        [D1, D2, D3],
        {D1: [cand("A", 100.0)], D2: [cand("B", 100.0)], D3: []},
        {D2: {"A": bar(110.0, 99.0, 109.0)}, D3: {"B": bar(101.0, 99.0, 100.0)}},
    )
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2)
    by_sym = {t.symbol: t for t in res.trades}
    assert by_sym["A"].quantity == 500
    assert by_sym["B"].quantity == 524


def test_slippage_is_not_applied_twice_to_pnl(monkeypatch):
    """With slippage on, pnl_abs is quantity * (exit_price - entry_price) - brokerage
    using the already-slipped prices — no second haircut.

    BY HAND (capital 1,00,000, 2 slots, 10 bps slippage, A at 100):
      entry_price = 100 * 1.001 = 100.1 → slot 50,000 → qty floor(50,000/100.1) = 499
      target = 100.1 + (100.1 - 95.095)*2 = 110.11; D2 high 120 ≥ target
      exit_price = 110.11 * 0.999 = 110.0 (110.000 - rounding aside)
      pnl_abs = 499 * (exit_price - 100.1) - 40
    """
    p = FakeProvider([D1, D2], {D1: [cand("A", 100.0)], D2: []},
                     {D2: {"A": bar(120.0, 99.0, 119.0)}})
    res = run(monkeypatch, p, capital=100_000.0, max_positions=2, slippage_pct=0.001)
    t = res.trades[0]
    assert t.entry_price == pytest.approx(100.1)
    assert t.quantity == 499
    assert t.pnl_abs == pytest.approx(499 * (t.exit_price - t.entry_price) - 40.0)


def test_no_data_window_still_reports_the_no_data_reason(monkeypatch):
    """The AI Trader gates key off metrics["reason"] == "no_data"; sizing must not
    change that early return."""
    p = FakeProvider([], {}, {})
    monkeypatch.setattr(bt, "get_provider", lambda pool=None: p)
    res = asyncio.run(bt.run_backtest(None, spec(), from_date=D1, to_date=D2))
    assert res.metrics == {"reason": "no_data"}
    assert res.trades == []
