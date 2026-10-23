"""Paper-portfolio equity, its peak, and the drawdown the governor halts on.

WHY THIS EXISTS
`risk_governor.py:118-119` halts on `portfolio.drawdown_pct` and has always been able to. Nothing
ever computed one: `_portfolio()`'s own docstring said "the desk keeps no equity curve either, so
drawdown is None", and the governor duly reported DRAWDOWN_UNKNOWN on every evaluation. The system
therefore advertised a 15% drawdown limit it never once checked — a limit that is displayed and not
enforced is worse than no limit, because it buys false confidence.

WHAT EQUITY MEANS HERE
    equity = capital + net realised P&L + net unrealised P&L
Both P&L figures are NET of the desk's own cost model, because a drawdown measured on gross P&L
would be smaller than the one the account actually suffered.

WHEN IT IS UNKNOWN, IT SAYS SO
If any open position cannot be marked, equity is None and so is the drawdown — never a partial sum.
`desk_trading.portfolio_summary` already takes this position (`whole = bool(held) and not unmarked`)
and this follows it. The governor then reports DRAWDOWN_UNKNOWN, which is the truth: the halt could
not be checked. That is deliberately NOT the same as "no drawdown".

PEAK, AND WHY IT IS STORED
Drawdown is peak-to-trough, so it needs the high-water mark. Recomputing it from history is not
possible — the desk keeps no equity series, only current positions — so the peak is carried forward
in `risk_equity_peaks`, raised whenever equity exceeds it and never lowered. A peak that reset would
make a drawdown disappear the moment it mattered most.

The daily loss limit is NOT here: `risk_governor` already enforces it from `realized_pnl_today`,
which `_portfolio()` sums over trades closed today in IST, so it resets with the session already.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PEAKS = "risk_equity_peaks"

BASIS = ("equity = capital + net realised P&L + net unrealised P&L, both net of the desk cost model; "
         "drawdown is measured from the highest equity seen, which is carried forward and never lowered")


def equity_from(capital: float, net_realized: Optional[float], net_unrealized: Optional[float],
                unmarked_open: int) -> Optional[float]:
    """Equity, or None when it cannot be known.

    None when an open position has no mark: a sum of marked and unmarked positions is a number that
    belongs to no portfolio, and a drawdown computed from it would understate the real one."""
    if capital is None or capital <= 0:
        return None
    if unmarked_open:
        return None
    return round(float(capital) + float(net_realized or 0.0) + float(net_unrealized or 0.0), 2)


def drawdown_pct(equity: Optional[float], peak: Optional[float]) -> Optional[float]:
    """How far below the high-water mark, in percent. None when either side is unknown.

    A positive number means a loss from the peak; at or above the peak it is 0.0, never negative,
    because "drawdown" is not a measure of gains."""
    if equity is None or peak is None or peak <= 0:
        return None
    if equity >= peak:
        return 0.0
    return round((peak - equity) / peak * 100.0, 4)


async def read_peak(db, user_id: str) -> Optional[float]:
    doc = await db[PEAKS].find_one({"user_id": user_id})
    if not doc:
        return None
    value = doc.get("peak_equity")
    return float(value) if value is not None else None


async def observe(db, user_id: str, equity: Optional[float],
                  now: Optional[datetime] = None) -> Optional[float]:
    """Record this equity and return the high-water mark including it.

    Raised only, never lowered. An unknown equity does not touch the peak: a session where the marks
    were missing must not quietly reset the mark a real drawdown is measured against."""
    stored = await read_peak(db, user_id)
    if equity is None:
        return stored
    if stored is not None and stored >= equity:
        return stored
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    await db[PEAKS].update_one(
        {"user_id": user_id},
        {"$set": {"peak_equity": float(equity), "peak_at": moment},
         "$setOnInsert": {"user_id": user_id}},
        upsert=True,
    )
    return float(equity)


async def snapshot(db, user_id: str, capital: float, summary: Dict[str, Any],
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    """Equity, peak and drawdown from a `desk_trading.portfolio_summary`-shaped dict.

    Takes the summary rather than reading trades itself so there is ONE definition of realised and
    unrealised P&L in the product, the desk's own."""
    unmarked = int(summary.get("unmarked_open") or 0)
    equity = equity_from(capital, summary.get("net_realized_pnl_rs"),
                         summary.get("net_unrealized_pnl_rs"), unmarked)
    peak = await observe(db, user_id, equity, now)
    dd = drawdown_pct(equity, peak)
    out = {
        "equity": equity,
        "peak_equity": peak,
        "drawdown_pct": dd,
        "capital": capital,
        "net_realized_pnl_rs": summary.get("net_realized_pnl_rs"),
        "net_unrealized_pnl_rs": summary.get("net_unrealized_pnl_rs"),
        "unmarked_open": unmarked,
        "basis": BASIS,
    }
    if equity is None:
        out["unknown_reason"] = (
            f"{unmarked} open position(s) could not be marked, so equity and the drawdown are unknown"
            if unmarked else "capital is not a positive number, so equity cannot be computed")
    return out
