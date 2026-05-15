"""Admin endpoint to verify NIDP stock primitives completeness.

GET /api/admin/nidp/stock-primitives/completeness
  Optional query param: ?include_universe=1  → also compute overlap with
  the live Nivesh equity universe (slower; ~3-5s SSH roundtrip).
"""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
import logging

from deps import db, get_current_user
from services.stock_primitives_completeness import run_completeness_check

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp/stock-primitives", tags=["admin-nidp"])


async def _nivesh_equity_universe(limit: int = 800) -> list[str]:
    """Return distinct equity tickers (ISINs) currently held by any
    Nivesh user. NIDP stock_features_daily is keyed by symbol (e.g.
    'RELIANCE') — until the identity bridge lands we lookup by the
    holding's `name` cleaned to upper-case first-word. For ISIN-only
    holdings we currently can't map, so this returns BOTH the raw
    ticker (ISIN) AND derived NSE-style symbols. The completeness
    check tolerates non-matches as `missing_sample`."""
    seen: set[str] = set()
    out: list[str] = []
    async for h in db.holdings.find(
        {"asset_type": "equity"},
        {"_id": 0, "name": 1, "ticker": 1},
    ).limit(limit * 4):
        # NIDP joins on `symbol` which is the NSE-style code, not ISIN.
        # Best-effort: take the first word of `name` upper-cased.
        nm = (h.get("name") or "").strip().upper()
        first_word = nm.split(" ")[0] if nm else None
        if first_word and first_word not in seen:
            seen.add(first_word)
            out.append(first_word)
            if len(out) >= limit:
                break
    return out


@router.get("/completeness")
async def completeness(request: Request, include_universe: int = 1) -> dict:
    """Run the full completeness check on the NIDP VM and return a JSON envelope."""
    user = await get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    universe: list[str] = []
    if include_universe:
        try:
            universe = await _nivesh_equity_universe()
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load Nivesh equity universe: %s", e)

    try:
        result = await run_completeness_check(nivesh_symbols=universe)
    except Exception as e:  # noqa: BLE001
        logger.exception("Stock primitives completeness check failed")
        raise HTTPException(status_code=502, detail=f"VM query failed: {e}") from e
    result["queried_nivesh_universe_sample"] = universe[:10] if universe else []
    return result
