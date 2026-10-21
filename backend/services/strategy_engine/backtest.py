"""Strategy backtest runner.

Sweeps a date range, runs the compiled entry rule once per trading
day, simulates entries with the spec's exit plan against forward bars,
and records every simulated trade in strategy_trades.

Data basis (Tier-2 / R1 applied — see metrics["price_basis"] /
metrics["universe_basis"] which the run records for audit):

  • Corp-action-adjusted prices. Entry uses nidp.prices_eod_adjusted
    .adj_close (falling back to f.close only where the adjusted row is
    missing); exits use adj_high/adj_low/adj_close from the same table.
    Entry and exit share one adjusted basis, so a split/bonus during the
    hold no longer fabricates a gain/loss. The features-derived ATR is
    rescaled by cumulative_adj_factor onto that basis.

  • Universe membership is point-in-time when nidp.index_constituents is
    populated for the chosen index (survivorship-correct; real Nifty
    50/100/200/500 distinction). When that table is empty for the index
    the runner falls back to the legacy present-day `sm.is_nifty_100`
    set and LOGS it — never silently empty, but that fallback path does
    carry survivorship bias (recorded as universe_basis="present_day_fallback").

  • One trade per (symbol, entry_date) — once we open a position we
    don't re-enter on the next bar even if the rule still fires. Live
    semantics (Phase 3) follow the same rule.

  • Costs from day 1 — slippage_pct (default 0.05% per side) +
    flat brokerage (default ₹20 per side) deducted at entry and exit.
    Without these, every backtest paints a rosy picture that won't
    survive contact with reality.

  • Position sizing — equal-weight slots against a tracked cash balance
    (metrics["sizing_basis"] == "portfolio"). One slot is
    `current_equity / max_positions` and `quantity = floor(slot / entry_price)`,
    so the run compounds: a slot grows as the book grows. Opening a
    position debits `quantity * entry_price + brokerage` from cash and
    closing credits `quantity * exit_price - brokerage`, so cash is a real
    constraint — a candidate the cash cannot afford, or one whose price
    exceeds a whole slot, is SKIPPED and counted in
    metrics["skipped_insufficient_cash"] / ["skipped_min_quantity"],
    never silently dropped. Before this, `pnl_abs` was the profit on ONE
    share and that per-share rupee figure was added to an equity series
    starting at `starting_capital`, so `total_return_pct` and
    `max_drawdown_pct` were one-share rupees as a percentage of a ten-lakh
    account (30 trades of a 5%-stop strategy read as -0.36% in total).

  • Daily mark-to-market equity — one equity point per trading day:
    cash plus `quantity * that day's adjusted close` for every open
    position. A symbol with no bar on a day carries its last observed mark
    forward (never an invented price). `max_drawdown_pct` is taken from
    that series, so it finally includes open-position drawdown, not just
    the realised dips between exits.

  • Pure-async + asyncpg — caller passes a pool; we never open our own
    connection so transaction boundaries stay with the caller.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .dsl import validate_strategy
from .market_data import get_provider
from .backtest_sql import EXIT_BARS_SQL as _EXIT_BARS_SQL  # re-exported for tests

logger = logging.getLogger(__name__)


# ── Cost defaults ───────────────────────────────────────────────────
DEFAULT_SLIPPAGE_PCT = 0.0005       # 5 bps per side
DEFAULT_BROKERAGE_INR = 20.0        # ₹20 flat per side


@dataclass
class BacktestTrade:
    symbol: str
    entry_date: date
    entry_price: float
    score: Optional[float]
    stoploss_price: float
    target_price: float
    quantity: int = 0                   # whole shares held; sized off the equity slot at entry
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_pct: Optional[float] = None
    pnl_abs: Optional[float] = None
    holding_days: Optional[int] = None
    brokerage: float = 2 * DEFAULT_BROKERAGE_INR
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT


@dataclass
class BacktestResult:
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)  # [{date, equity, drawdown}]
    metrics: Dict[str, Any] = field(default_factory=dict)


# ── Public entry ────────────────────────────────────────────────────
async def run_backtest(
    pool,
    spec: Dict[str, Any],
    *,
    from_date: date,
    to_date: date,
    starting_capital: float = 1_000_000.0,
    max_positions: int = 10,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
    brokerage_inr: float = DEFAULT_BROKERAGE_INR,
) -> BacktestResult:
    """Run a backtest of `spec` from from_date..to_date inclusive."""
    errs = validate_strategy(spec)
    if errs:
        raise ValueError("invalid spec: " + "; ".join(str(e) for e in errs))

    # Market data comes through a provider (SQL on co-located dev, NIDP DaaS API
    # on staging/prod). `prepare` prefetches the window; `screen`/`exit_bars`
    # serve per-date candidates and adjusted bars. R1's adjusted-price +
    # point-in-time-membership semantics live in the provider now.
    provider = get_provider(pool)
    await provider.prepare(spec, from_date, to_date)

    open_trades: Dict[str, BacktestTrade] = {}     # symbol → trade
    closed_trades: List[BacktestTrade] = []

    trading_dates = await provider.trading_dates(from_date, to_date)
    if not trading_dates:
        logger.warning("backtest window %s..%s has no feature snapshots", from_date, to_date)
        return BacktestResult(metrics={"reason": "no_data"})

    sl_pct = float(spec["exit"].get("stoploss_pct", 5)) / 100.0
    target_rr = float(spec["exit"].get("target_rr", 2.0))
    max_hold = int(spec["exit"].get("max_hold_days", 30))
    trailing_atr_mult = spec["exit"].get("trailing_atr_mult")  # may be None

    # Cash is the real constraint; equity = cash + mark-to-market of the open book.
    cash = float(starting_capital)
    marks: Dict[str, float] = {}                 # symbol → last OBSERVED close (carried forward)
    equity_points: List[Dict[str, Any]] = []     # one per trading day, mark-to-market
    skipped_cash = 0                             # candidates the cash could not afford
    skipped_min_qty = 0                          # candidates dearer than one whole slot
    stale_mark_closes = 0                        # force-closes that had no bar on the last day

    def _equity_now() -> float:
        return cash + sum(t.quantity * marks.get(sym, t.entry_price)
                          for sym, t in open_trades.items())

    for d in trading_dates:
        # 1) Process exits on currently-open positions first
        if open_trades:
            exit_map = await provider.exit_bars(list(open_trades), d)
            for sym, row in list(exit_map.items()):
                trade = open_trades.get(sym)
                if not trade:
                    continue
                # Mark first: today's close is this symbol's mark whether or not it exits.
                marks[sym] = float(row["close"])
                closed = _maybe_close_trade(
                    trade, d, row, sl_pct=sl_pct, target_rr=target_rr,
                    max_hold=max_hold, trailing_atr_mult=trailing_atr_mult,
                    brokerage_inr=brokerage_inr, slippage_pct=slippage_pct,
                )
                if closed is not None:
                    # Selling returns the proceeds less this side's brokerage; the
                    # other leg was already paid at entry, so cash moves by pnl_abs.
                    cash += closed.quantity * (closed.exit_price or 0.0) - brokerage_inr
                    closed_trades.append(closed)
                    del open_trades[sym]
                    marks.pop(sym, None)

        # 2) Look for new entries — only if we have capacity
        slots = max_positions - len(open_trades)
        if slots <= 0:
            _record_equity(equity_points, d, _equity_now())
            continue

        rows = await provider.screen(spec, d)
        for r in rows[:slots]:
            sym = r["symbol"]
            if sym in open_trades:
                continue
            # Entry at next-bar open is more realistic; Phase-1 simplifies
            # to same-bar close + slippage. Document this in the readout.
            # Trade on the corp-action-adjusted close (R1); fall back to raw
            # close only where the adjusted series is missing.
            adj_close = r.get("adj_close")
            base_px = float(adj_close) if adj_close is not None else float(r["close"])
            entry_price = base_px * (1.0 + slippage_pct)
            # features.atr14 is on a RAW-price basis; rescale to the adjusted
            # basis (adj_close = raw_close / cumulative_adj_factor) so the
            # trailing-stop distance is in the same units as price.
            adj_factor = float(r["adj_factor"]) if r.get("adj_factor") else 1.0
            raw_atr = float(r.get("atr14") or 0.0)
            atr = (raw_atr / adj_factor) if raw_atr else (entry_price * 0.02)
            stoploss = entry_price * (1.0 - sl_pct)
            target = entry_price + (entry_price - stoploss) * target_rr

            # ── Equal-weight slot sizing ──────────────────────────────
            # The slot is a share of CURRENT equity, recomputed per candidate so
            # the run compounds and so the ₹20 already paid on this day's earlier
            # entries is reflected (sizing off a stale once-a-day equity can make
            # the last slot of a day unaffordable by exactly that brokerage).
            slot_value = _equity_now() / max_positions
            quantity = int(slot_value // entry_price)
            if quantity < 1:
                # One whole share costs more than a slot. Skipped, not dropped.
                skipped_min_qty += 1
                logger.info("backtest %s on %s: 1 share (₹%.2f) exceeds the slot "
                            "(₹%.2f) — entry skipped", sym, d, entry_price, slot_value)
                continue
            entry_cost = quantity * entry_price + brokerage_inr
            if entry_cost > cash:
                skipped_cash += 1
                logger.info("backtest %s on %s: entry needs ₹%.2f but cash is ₹%.2f "
                            "— entry skipped", sym, d, entry_cost, cash)
                continue

            t = BacktestTrade(
                symbol=sym,
                entry_date=d,
                entry_price=entry_price,
                score=float(r.get("accumulation_score") or 0.0),
                stoploss_price=stoploss,
                target_price=target,
                quantity=quantity,
                brokerage=2 * brokerage_inr,
                slippage_pct=slippage_pct,
            )
            # Stash ATR for trailing stop bookkeeping
            t.__dict__["_atr"] = atr
            t.__dict__["_high_water"] = entry_price
            open_trades[sym] = t
            cash -= entry_cost
            marks[sym] = base_px          # mark on the day's observed close, not the slipped fill

        _record_equity(equity_points, d, _equity_now())

    # Force-close any still-open positions at the last available close
    if open_trades:
        last_lookup = await provider.exit_bars(list(open_trades), trading_dates[-1])
        for sym, trade in open_trades.items():
            row = last_lookup.get(sym)
            if row:
                close = float(row["close"])
            elif sym in marks:
                # No bar on the final day. Close on the last OBSERVED mark rather
                # than leave the position out of the ledger entirely (the previous
                # `continue` dropped the trade AND its capital silently). No price
                # is invented — this is the last close the feed actually carried.
                close = marks[sym]
                stale_mark_closes += 1
                logger.info("backtest %s: no bar on %s — force-closed on the last "
                            "observed mark ₹%.2f", sym, trading_dates[-1], close)
            else:
                continue
            trade.exit_date = trading_dates[-1]
            trade.exit_price = close * (1.0 - slippage_pct)
            trade.exit_reason = "BACKTEST_END"
            trade.pnl_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100.0
            trade.pnl_abs = (trade.quantity * (trade.exit_price - trade.entry_price)
                             - trade.brokerage)
            trade.holding_days = (trade.exit_date - trade.entry_date).days
            cash += trade.quantity * trade.exit_price - brokerage_inr
            closed_trades.append(trade)
        open_trades.clear()
        marks.clear()
        # The force-close happens ON the last trading day, so restate that day's
        # point instead of appending a second point for the same date.
        if equity_points:
            equity_points[-1]["equity"] = cash

    equity = _equity_now()          # open_trades is empty here → equity == cash
    equity_curve = _build_equity_curve(equity_points, starting_capital)
    metrics = _compute_metrics(
        closed_trades, starting_capital, equity, equity_curve,
        max_positions=max_positions,
        skipped_insufficient_cash=skipped_cash,
        skipped_min_quantity=skipped_min_qty,
        stale_mark_closes=stale_mark_closes,
    )
    # Self-describe the data basis so the readout / AC-7 data test can assert
    # what actually ran rather than trust a static claim (CONTEXT §1). The
    # provider reports the basis it actually used (price + universe membership).
    metrics.update(provider.basis)

    return BacktestResult(trades=closed_trades, equity_curve=equity_curve, metrics=metrics)


# ── Internals ───────────────────────────────────────────────────────
def _maybe_close_trade(trade, on_date, row, *,
                       sl_pct: float, target_rr: float, max_hold: int,
                       trailing_atr_mult: Optional[float],
                       brokerage_inr: float, slippage_pct: float):
    """Decide if `trade` exits on `on_date`'s bar. Returns closed trade or None."""
    high = float(row["high"] or row["close"])
    low = float(row["low"] or row["close"])
    close = float(row["close"])
    held = (on_date - trade.entry_date).days

    # Update high-water for trailing stop
    trade.__dict__["_high_water"] = max(trade.__dict__.get("_high_water", trade.entry_price), high)
    if trailing_atr_mult:
        atr = trade.__dict__.get("_atr", trade.entry_price * 0.02)
        trail = trade.__dict__["_high_water"] - trailing_atr_mult * atr
        if trail > trade.stoploss_price:
            trade.stoploss_price = trail

    exit_reason = None
    exit_price = None
    if low <= trade.stoploss_price:
        exit_reason = "STOPLOSS"
        # Conservative: assume fill at stop (could gap below; ignore for v1)
        exit_price = trade.stoploss_price * (1.0 - slippage_pct)
    elif high >= trade.target_price:
        exit_reason = "TARGET"
        exit_price = trade.target_price * (1.0 - slippage_pct)
    elif held >= max_hold:
        exit_reason = "TIME"
        exit_price = close * (1.0 - slippage_pct)

    if not exit_reason:
        return None

    trade.exit_date = on_date
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason
    # pnl_pct KEEPS its original meaning: the PER-SHARE percentage move between the
    # slipped entry and exit prices, gross of brokerage. Other code and the UI read
    # it as the trade's percentage move, so it is deliberately not re-based onto the
    # portfolio. pnl_abs below is the portfolio-scale rupee figure.
    trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100.0
    # Quantity-aware and net of BOTH brokerage legs. Slippage is already baked into
    # entry_price and exit_price, so it must not be charged a second time here.
    trade.pnl_abs = trade.quantity * (exit_price - trade.entry_price) - trade.brokerage
    trade.holding_days = held
    return trade


def _record_equity(points: List[Dict[str, Any]], d: date, equity_now: float) -> None:
    """Append one mark-to-market equity point for trading day `d`.

    `equity_now` is cash + Σ(quantity × that symbol's latest observed close), so the
    series moves while positions are still open. Drawdowns are filled in later by
    `_build_equity_curve` (it needs the running peak over the whole series)."""
    points.append({"date": str(d), "equity": round(float(equity_now), 2)})


def _build_equity_curve(points: List[Dict[str, Any]], starting_capital: float) -> List[Dict[str, Any]]:
    """Daily mark-to-market equity curve with drawdown against the running peak.

    One point per trading day (the engine's own calendar), each the close-of-day
    total equity. The peak is seeded at `starting_capital` so a book that is under
    water from day one reports a drawdown rather than a flat 0%."""
    out: List[Dict[str, Any]] = []
    peak = float(starting_capital)
    for p in points:
        eq = float(p["equity"])
        peak = max(peak, eq)
        out.append({
            "date": p["date"],
            "equity": round(eq, 2),
            "drawdown": round((eq - peak) / peak * 100.0, 4) if peak else 0.0,
        })
    return out


def _compute_metrics(trades: List[BacktestTrade], start_cap: float, end_cap: float,
                     equity_curve: Optional[List[Dict[str, Any]]] = None, *,
                     max_positions: int = 0,
                     skipped_insufficient_cash: int = 0,
                     skipped_min_quantity: int = 0,
                     stale_mark_closes: int = 0) -> Dict[str, Any]:
    """Summary metrics for a sized run.

    A WIN means the trade MADE MONEY AFTER COSTS: wins and losses are split on net
    `pnl_abs`, the same figure `profit_factor` divides, so the two metrics can no
    longer disagree (they used to — `win_rate` split on gross `pnl_pct` while
    `profit_factor` used net `pnl_abs`, so a trade whose gross gain was swallowed by
    brokerage counted as a win and as a loss at the same time).

    Averages come in two pairs, and only one of them is coherent:

      • `avg_win_abs` / `avg_loss_abs` (RUPEES) are the mean net `pnl_abs` of the
        same buckets `win_rate` and `profit_factor` use. These three are mutually
        consistent, so THIS is the pair to display.
      • `avg_win_pct` / `avg_loss_pct` are kept unchanged because other code reads
        them, but they are a GROSS PER-SHARE percentage averaged over buckets
        defined by NET RUPEES. `avg_loss_pct` can therefore come back POSITIVE: a
        trade that moved +2 % gross but netted −₹22 after ₹40 of brokerage sits in
        the loss bucket carrying a `pnl_pct` of +2.0. Do not headline that pair.

    `max_drawdown_pct` comes from the DAILY mark-to-market `equity_curve`, so it
    includes open-position drawdown, not only the realised dips between exits.
    """
    sizing = {
        "sizing_basis":              "portfolio",
        "max_positions":             max_positions,
        "skipped_insufficient_cash": skipped_insufficient_cash,
        "skipped_min_quantity":      skipped_min_quantity,
        "skipped_entries":           skipped_insufficient_cash + skipped_min_quantity,
        "stale_mark_closes":         stale_mark_closes,
        "starting_capital":          start_cap,
        "ending_capital":            round(end_cap, 2),
    }
    max_dd = min([p["drawdown"] for p in (equity_curve or [])], default=0.0)
    if not trades:
        return {"trade_count": 0,
                "max_drawdown_pct": round(max_dd, 2),
                "total_return_pct": round((end_cap - start_cap) / start_cap * 100.0, 2),
                **sizing}
    wins = [t for t in trades if (t.pnl_abs or 0) > 0]
    losses = [t for t in trades if (t.pnl_abs or 0) <= 0]
    avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
    total_profit = sum(t.pnl_abs or 0 for t in wins)
    total_loss = abs(sum(t.pnl_abs or 0 for t in losses))
    # The coherent pair: mean net rupees over the same buckets as win_rate /
    # profit_factor. avg_loss_abs keeps pnl_abs's sign, so it is ≤ 0.
    avg_win_abs = (total_profit / len(wins)) if wins else 0.0
    avg_loss_abs = (sum(t.pnl_abs or 0 for t in losses) / len(losses)) if losses else 0.0
    # None means "nothing to divide by" (no losing trade). A profit factor of
    # exactly 0.0 is a real, terrible number and must not be reported as None.
    profit_factor = (total_profit / total_loss) if total_loss > 0 else None

    return {
        "trade_count":        len(trades),
        "win_rate":           round(len(wins) / len(trades) * 100.0, 2),
        "avg_win_pct":        round(avg_win, 2),
        "avg_loss_pct":       round(avg_loss, 2),
        "avg_win_abs":        round(avg_win_abs, 2),
        "avg_loss_abs":       round(avg_loss_abs, 2),
        "profit_factor":      round(profit_factor, 2) if profit_factor is not None else None,
        "max_drawdown_pct":   round(max_dd, 2),
        "total_return_pct":   round((end_cap - start_cap) / start_cap * 100.0, 2),
        "avg_holding_days":   round(sum((t.holding_days or 0) for t in trades) / len(trades), 1),
        "total_quantity":     sum(int(t.quantity or 0) for t in trades),
        **sizing,
    }


# ── Persistence helper ──────────────────────────────────────────────
async def persist_run(pool, *, strategy_id, version_id, spec, result: BacktestResult,
                       from_date, to_date, triggered_by) -> str:
    """Write a strategy_runs row + per-trade strategy_trades rows. Returns run_id."""
    run_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO strategy_runs
                       (id, strategy_id, version_id, run_type, status,
                        backtest_from, backtest_to,
                        metrics, equity_curve, trade_count,
                        triggered_by, finished_at, duration_ms)
                   VALUES ($1, $2, $3, 'BACKTEST', 'OK',
                           $4, $5, $6::jsonb, $7::jsonb, $8,
                           $9, NOW(), NULL)""",
                run_id, strategy_id, version_id,
                from_date, to_date,
                json.dumps(result.metrics),
                json.dumps(result.equity_curve),
                len(result.trades),
                triggered_by,
            )
            for t in result.trades:
                await conn.execute(
                    """INSERT INTO strategy_trades
                           (run_id, strategy_id, symbol,
                            entry_date, entry_price, score,
                            stoploss_price, target_price, qty,
                            exit_date, exit_price, exit_reason,
                            pnl_pct, pnl_abs, holding_days,
                            brokerage, slippage_pct)
                       VALUES ($1, $2, $3,
                               $4, $5, $6,
                               $7, $8, $9,
                               $10, $11, $12,
                               $13, $14, $15,
                               $16, $17)""",
                    run_id, strategy_id, t.symbol,
                    t.entry_date, t.entry_price, t.score,
                    t.stoploss_price, t.target_price, int(t.quantity or 0),
                    t.exit_date, t.exit_price, t.exit_reason,
                    t.pnl_pct, t.pnl_abs, t.holding_days,
                    t.brokerage, t.slippage_pct,
                )
    return run_id
