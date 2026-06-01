"""ATM put hedge cost lookup via NIDP DaaS F&O API.

For each basket stock, finds the nearest-expiry ATM put option from
nidp.fno_bhavcopy (exposed at GET /v1/fno/{symbol}/chain). Returns the
hedge cost dict or None on any failure — callers degrade gracefully.

Hedge cost = ATM put close_price × lot_size
Hedge cost % = hedge_cost_rs / (entry_price × lot_size) × 100

If the stock has no F&O data (e.g. not in F&O segment), falls back to
a Nifty-delta-scaled index put proxy using the NIFTY chain.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Nifty lot size post-2024 revision
_NIFTY_LOT = 75

# Minimum open interest to treat a strike as liquid (in contracts)
_MIN_OI = 500


def _find_atm_strike(chain: list[Dict[str, Any]], target_price: float) -> Optional[Dict[str, Any]]:
    """Return the chain row whose strike is closest to target_price.

    `chain` is the list returned by the DaaS /chain endpoint — each row
    has at minimum {strike_price, option_type, close_price, open_interest,
    lot_size, expiry_date}. We only consider PE rows with OI >= _MIN_OI.
    """
    pe_rows = [
        r for r in chain
        if (r.get("option_type") or "").upper() == "PE"
        and float(r.get("open_interest") or 0) >= _MIN_OI
        and float(r.get("close_price") or 0) > 0
    ]
    if not pe_rows:
        return None
    return min(pe_rows, key=lambda r: abs(float(r.get("strike_price") or 0) - target_price))


async def get_atm_put_cost(
    symbol: str,
    entry_price: float,
) -> Optional[Dict[str, Any]]:
    """Return hedge metadata for a single basket position.

    Calls DaaS GET /v1/fno/{symbol}/chain (nearest expiry) and finds the
    ATM put. Returns a dict with:
        put_strike       float
        expiry           str   (YYYY-MM-DD)
        put_close        float (EOD premium per share)
        lot_size         int
        cost_rs          float (put_close × lot_size — cost of 1 hedge lot)
        cost_pct         float (cost_rs / (entry_price × lot_size) × 100)
        hedge_type       "ATM_PUT" | "NIFTY_PE_PROXY"

    Returns None when the stock has no liquid F&O options and the Nifty
    proxy also fails. Never raises.
    """
    try:
        from services.copilot_tools.daas_client import _get, DaasError
        data = await _get(f"/fno/{symbol}/chain")
        chain = (data or {}).get("chain") or (data or {}).get("data") or []
        if not isinstance(chain, list):
            chain = []
    except Exception as e:  # noqa: BLE001
        logger.debug("hedge_planner: DaaS /fno/%s/chain failed (%s)", symbol, e)
        chain = []

    row = _find_atm_strike(chain, entry_price) if chain else None

    if row is not None:
        put_close = float(row.get("close_price") or 0)
        lot_size = int(row.get("lot_size") or row.get("new_board_lot_qty") or 1)
        strike = float(row.get("strike_price") or entry_price)
        expiry = str(row.get("expiry_date") or "")
        if put_close > 0 and lot_size > 0:
            cost_rs = round(put_close * lot_size, 2)
            cost_pct = round(cost_rs / (entry_price * lot_size) * 100, 2) if entry_price > 0 else 0.0
            return {
                "put_strike": strike,
                "expiry": expiry,
                "put_close": put_close,
                "lot_size": lot_size,
                "cost_rs": cost_rs,
                "cost_pct": cost_pct,
                "hedge_type": "ATM_PUT",
            }

    # Fallback: Nifty PE proxy — use Nifty ATM put as a portfolio hedge proxy.
    # Cost scaled by beta proxy (1.0 = assume beta ≈ 1; caller can multiply by
    # stock beta if available). This is a coarse hedge, not a stock-specific one.
    logger.debug("hedge_planner: no liquid %s options — falling back to NIFTY_PE_PROXY", symbol)
    try:
        from services.copilot_tools.daas_client import _get
        nifty_data = await _get("/fno/NIFTY/chain")
        nifty_chain = (nifty_data or {}).get("chain") or (nifty_data or {}).get("data") or []
        if not isinstance(nifty_chain, list):
            nifty_chain = []
        # Nifty underlying price from any row
        underlying = next(
            (float(r.get("underlying_price") or 0) for r in nifty_chain if r.get("underlying_price")),
            0.0,
        )
        if underlying <= 0:
            return None
        nifty_row = _find_atm_strike(nifty_chain, underlying)
        if nifty_row is None:
            return None
        put_close = float(nifty_row.get("close_price") or 0)
        if put_close <= 0:
            return None
        lot_size = _NIFTY_LOT
        strike = float(nifty_row.get("strike_price") or underlying)
        expiry = str(nifty_row.get("expiry_date") or "")
        cost_rs = round(put_close * lot_size, 2)
        cost_pct = round(cost_rs / (underlying * lot_size) * 100, 2)
        return {
            "put_strike": strike,
            "expiry": expiry,
            "put_close": put_close,
            "lot_size": lot_size,
            "cost_rs": cost_rs,
            "cost_pct": cost_pct,
            "hedge_type": "NIFTY_PE_PROXY",
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("hedge_planner: NIFTY_PE_PROXY fallback failed (%s)", e)
        return None
