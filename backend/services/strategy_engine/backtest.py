"""Strategy backtest runner.

Sweeps a date range, runs the compiled entry rule once per trading
day, simulates entries with the spec's exit plan against forward bars
from nidp.prices_eod_adjusted (Phase 2 — falls back to prices_eod in
Phase 1), and records every simulated trade in strategy_trades.

Design rules:

  • Survivorship-bias-free — universe is point-in-time, gated through
    the same WHERE clause the live runner uses (compiler emits the
    correct in_nifty50/100/500 / index_constituents check).

  • One trade per (symbol, entry_date) — once we open a position we
    don't re-enter on the next bar even if the rule still fires. Live
    semantics (Phase 3) follow the same rule.

  • Costs from day 1 — slippage_pct (default 0.05% per side) +
    flat brokerage (default ₹20 per side) deducted at entry and exit.
    Without these, every backtest paints a rosy picture that won't
    survive contact with reality.

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

from .compiler_stock import compile_stock_query, to_asyncpg
from .dsl import validate_strategy

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

    sql, params = compile_stock_query(spec)
    sql_pg, base_args_template = to_asyncpg(sql, params)
    # `to_asyncpg` will leave `:as_of_date` unmapped because it's not in
    # params; convert manually to the next positional slot.
    next_slot = len(base_args_template) + 1
    sql_pg = sql_pg.replace(":as_of_date", f"${next_slot}")

    open_trades: Dict[str, BacktestTrade] = {}     # symbol → trade
    closed_trades: List[BacktestTrade] = []

    # Iterate every trading date in range. We rely on stock_features_daily
    # only existing on real trading days, so an inexpensive distinct query
    # gives us the calendar.
    async with pool.acquire() as conn:
        date_rows = await conn.fetch(
            "SELECT DISTINCT as_of_date FROM nidp.stock_features_daily "
            "WHERE as_of_date BETWEEN $1 AND $2 ORDER BY as_of_date",
            from_date, to_date,
        )
    trading_dates = [r["as_of_date"] for r in date_rows]
    if not trading_dates:
        logger.warning("backtest window %s..%s has no feature snapshots", from_date, to_date)
        return BacktestResult(metrics={"reason": "no_data"})

    sl_pct = float(spec["exit"].get("stoploss_pct", 5)) / 100.0
    target_rr = float(spec["exit"].get("target_rr", 2.0))
    max_hold = int(spec["exit"].get("max_hold_days", 30))
    trailing_atr_mult = spec["exit"].get("trailing_atr_mult")  # may be None

    equity = starting_capital

    async with pool.acquire() as conn:
        for d in trading_dates:
            # 1) Process exits on currently-open positions first
            if open_trades:
                exit_rows = await _fetch_exit_bars(conn, list(open_trades), d)
                for row in exit_rows:
                    sym = row["symbol"]
                    trade = open_trades.get(sym)
                    if not trade:
                        continue
                    closed = _maybe_close_trade(
                        trade, d, row, sl_pct=sl_pct, target_rr=target_rr,
                        max_hold=max_hold, trailing_atr_mult=trailing_atr_mult,
                        brokerage_inr=brokerage_inr, slippage_pct=slippage_pct,
                    )
                    if closed is not None:
                        equity += closed.pnl_abs or 0.0
                        closed_trades.append(closed)
                        del open_trades[sym]

            # 2) Look for new entries — only if we have capacity
            slots = max_positions - len(open_trades)
            if slots <= 0:
                _record_equity(closed_trades, open_trades, equity, d)
                continue

            args = list(base_args_template) + [d]
            rows = await conn.fetch(sql_pg, *args)
            for r in rows[:slots]:
                sym = r["symbol"]
                if sym in open_trades:
                    continue
                # Entry at next-bar open is more realistic; Phase-1 simplifies
                # to same-bar close + slippage. Document this in the readout.
                entry_price = float(r["close"]) * (1.0 + slippage_pct)
                atr = float(r["atr14"] or 0.0) or (entry_price * 0.02)
                stoploss = entry_price * (1.0 - sl_pct)
                target = entry_price + (entry_price - stoploss) * target_rr

                t = BacktestTrade(
                    symbol=sym,
                    entry_date=d,
                    entry_price=entry_price,
                    score=float(r["accumulation_score"] or 0.0),
                    stoploss_price=stoploss,
                    target_price=target,
                    brokerage=2 * brokerage_inr,
                    slippage_pct=slippage_pct,
                )
                # Stash ATR for trailing stop bookkeeping
                t.__dict__["_atr"] = atr
                t.__dict__["_high_water"] = entry_price
                open_trades[sym] = t

            _record_equity(closed_trades, open_trades, equity, d)

    # Force-close any still-open positions at the last available close
    if open_trades:
        async with pool.acquire() as conn:
            last_bars = await _fetch_exit_bars(conn, list(open_trades), trading_dates[-1])
        last_lookup = {r["symbol"]: r for r in last_bars}
        for sym, trade in open_trades.items():
            row = last_lookup.get(sym)
            if not row:
                continue
            close = float(row["close"])
            trade.exit_date = trading_dates[-1]
            trade.exit_price = close * (1.0 - slippage_pct)
            trade.exit_reason = "BACKTEST_END"
            trade.pnl_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100.0
            trade.pnl_abs = (trade.exit_price - trade.entry_price) - trade.brokerage
            trade.holding_days = (trade.exit_date - trade.entry_date).days
            equity += trade.pnl_abs
            closed_trades.append(trade)
        open_trades.clear()

    metrics = _compute_metrics(closed_trades, starting_capital, equity)
    equity_curve = _build_equity_curve(closed_trades, starting_capital, trading_dates)

    return BacktestResult(trades=closed_trades, equity_curve=equity_curve, metrics=metrics)


# ── Internals ───────────────────────────────────────────────────────
async def _fetch_exit_bars(conn, symbols: List[str], on_date: date) -> List[Any]:
    """Fetch (high, low, close, atr14) for symbols on `on_date`.

    Sources high/low/close from this env's stock_ohlcv; ATR comes from
    the features snapshot. Features may be absent for symbols/dates
    outside the snapshotter run window — we LEFT JOIN so the trade can
    still exit on the OHLC bar (ATR-based trailing stop just won't
    update that day, which is conservative)."""
    return await conn.fetch(
        """
        SELECT o.nse_symbol AS symbol,
               o.close_price AS close,
               o.high_price AS high,
               o.low_price AS low,
               f.atr14
          FROM stock_ohlcv o
          LEFT JOIN nidp.stock_features_daily f
            ON f.symbol = o.nse_symbol AND f.as_of_date = o.bar_date
         WHERE o.nse_symbol = ANY($1::text[])
           AND o.bar_date = $2
        """,
        symbols, on_date,
    )


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
    trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100.0
    trade.pnl_abs = (exit_price - trade.entry_price) - 2 * brokerage_inr
    trade.holding_days = held
    return trade


def _record_equity(closed, open_trades, equity_now, d):
    pass  # Phase-1: equity is tracked off closed trades only; mark-to-market deferred


def _build_equity_curve(closed_trades, starting_capital, trading_dates) -> List[Dict[str, Any]]:
    """Realised-PnL equity curve. One point per trade exit, plus start/end."""
    points = [{"date": str(trading_dates[0]), "equity": starting_capital, "drawdown": 0.0}]
    eq = starting_capital
    peak = starting_capital
    closed_sorted = sorted(closed_trades, key=lambda t: t.exit_date or trading_dates[-1])
    for t in closed_sorted:
        eq += t.pnl_abs or 0.0
        peak = max(peak, eq)
        dd = (eq - peak) / peak * 100.0
        points.append({
            "date": str(t.exit_date),
            "equity": round(eq, 2),
            "drawdown": round(dd, 4),
        })
    return points


def _compute_metrics(trades: List[BacktestTrade], start_cap: float, end_cap: float) -> Dict[str, Any]:
    if not trades:
        return {"trade_count": 0}
    wins = [t for t in trades if (t.pnl_pct or 0) > 0]
    losses = [t for t in trades if (t.pnl_pct or 0) <= 0]
    avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
    total_profit = sum(t.pnl_abs or 0 for t in wins)
    total_loss = abs(sum(t.pnl_abs or 0 for t in losses))
    profit_factor = (total_profit / total_loss) if total_loss > 0 else None

    # Max drawdown — derived from equity curve
    eq = start_cap
    peak = start_cap
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.exit_date or x.entry_date):
        eq += t.pnl_abs or 0
        peak = max(peak, eq)
        max_dd = min(max_dd, (eq - peak) / peak * 100.0)

    return {
        "trade_count":        len(trades),
        "win_rate":           round(len(wins) / len(trades) * 100.0, 2),
        "avg_win_pct":        round(avg_win, 2),
        "avg_loss_pct":       round(avg_loss, 2),
        "profit_factor":      round(profit_factor, 2) if profit_factor else None,
        "max_drawdown_pct":   round(max_dd, 2),
        "total_return_pct":   round((end_cap - start_cap) / start_cap * 100.0, 2),
        "starting_capital":   start_cap,
        "ending_capital":     round(end_cap, 2),
        "avg_holding_days":   round(sum((t.holding_days or 0) for t in trades) / len(trades), 1),
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
                            stoploss_price, target_price,
                            exit_date, exit_price, exit_reason,
                            pnl_pct, pnl_abs, holding_days,
                            brokerage, slippage_pct)
                       VALUES ($1, $2, $3,
                               $4, $5, $6,
                               $7, $8,
                               $9, $10, $11,
                               $12, $13, $14,
                               $15, $16)""",
                    run_id, strategy_id, t.symbol,
                    t.entry_date, t.entry_price, t.score,
                    t.stoploss_price, t.target_price,
                    t.exit_date, t.exit_price, t.exit_reason,
                    t.pnl_pct, t.pnl_abs, t.holding_days,
                    t.brokerage, t.slippage_pct,
                )
    return run_id
