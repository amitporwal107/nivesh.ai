"""Bridge between the macro intelligence layer and the positional engine.

Three concerns:

  • blocked_sectors_today(state) — PR-3 hard filter. Returns the set of
    SECTOR_MACRO_MAP keys to drop today based on the current macro state
    (e.g. drop PAINT + AVIATION when crude is breaking out + inflation
    is rising). Empty set when no rules trigger.

  • sector_modifiers_for_universe(symbols, scan_date) — Per-symbol macro
    sector tilt. Resolves each symbol → sector → mapped key → cached
    sector_macro_scores row → tilt scalar.

  • position_size_factor(score_payload) — PR-3. Returns the multiplier the
    trade_planner should apply to its base position size. Combines
    macro_state.risk and the per-stock macro contribution.

Kept here (under positional_engine) rather than under services/macro_*
so the macro layer stays unaware of the positional engine — the
direction of dependency is engine → macro, never the reverse.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Set

from services import pg_client

logger = logging.getLogger(__name__)


# ── Hard filters (PRD §11) ─────────────────────────────────────────────
# Each rule: when the condition is true, drop these sector keys.
#
# Rules are intentionally conservative — we only block sectors when both
# the macro signal AND the regime context agree. A breakout in crude
# alone isn't enough to drop PAINT (sometimes paint companies have
# pricing power); we want crude breakout + RISING inflation, which is
# the textbook input-cost-margin-squeeze setup.
async def blocked_sectors_today(state: Dict[str, Any]) -> Set[str]:
    """Returns sectors to drop from the universe today.

    The state dict comes from `macro_engine.latest_state()`. We re-pull
    crude_breakout from macro_features because state doesn't carry it.
    """
    blocked: Set[str] = set()
    inflation = state.get("inflation")
    risk = state.get("risk")
    market = state.get("market")

    # We need crude_breakout from macro_features, which isn't on the
    # state dict directly — fetch it.
    crude_breakout = False
    try:
        pool = await pg_client.get_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT crude_breakout FROM macro_features "
                    "ORDER BY date DESC LIMIT 1",
                )
                if row and row["crude_breakout"] is not None:
                    crude_breakout = bool(row["crude_breakout"])
    except Exception as e:  # noqa: BLE001
        logger.debug("crude_breakout lookup failed: %s", e)

    # Rule 1: crude breakout + inflation rising → input-cost squeeze
    if crude_breakout and inflation == "RISING":
        blocked.update(["PAINT", "AVIATION", "TYRES", "FMCG"])

    # Rule 2: HIGH-risk regime in a BEAR market → defensive bias
    # Drop the most cyclical / leveraged sectors. We don't drop them
    # in a BULL market even on HIGH risk because the engine is then
    # likely to find late-stage breakouts that still work.
    if risk == "HIGH" and market == "BEAR":
        blocked.update(["NBFC", "REALTY", "INFRA"])

    return blocked


# ── Per-symbol sector tilt ────────────────────────────────────────────
async def sector_modifiers_for_universe(
    symbols: List[str], scan_date: Optional[date] = None,
) -> Dict[str, float]:
    """Build {symbol → sector_modifier} for the day. Resolves symbols
    via stock_master.sector + macro_sector._resolve_sector + the day's
    sector_macro_scores row. Symbols whose sector doesn't map get 0.0.
    """
    if not symbols:
        return {}
    pool = await pg_client.get_pool()
    if pool is None:
        return {}

    from services import macro_sector as _ms

    # 1) Bulk-fetch sectors in a single query
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT nse_symbol, sector FROM stock_master "
            "WHERE nse_symbol = ANY($1::text[])",
            symbols,
        )
    raw_sector_by_sym: Dict[str, Optional[str]] = {
        r["nse_symbol"]: r["sector"] for r in rows
    }

    # 2) Map each → SECTOR_MACRO_MAP key
    sector_key_by_sym: Dict[str, Optional[str]] = {
        sym: _ms._resolve_sector(raw_sector_by_sym.get(sym)) for sym in symbols
    }

    # 3) Fetch the tilt for each unique sector key in one query
    keys = sorted({k for k in sector_key_by_sym.values() if k})
    tilt_by_key: Dict[str, float] = {}
    if keys:
        target = scan_date or date.today()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT sector, macro_score FROM sector_macro_scores "
                "WHERE date = $1 AND sector = ANY($2::text[])",
                target, keys,
            )
            tilt_by_key = {
                r["sector"]: float(r["macro_score"]) if r["macro_score"] is not None else 0.0
                for r in rows
            }
            # If today's row is missing for some keys, fall back to most-recent
            missing = [k for k in keys if k not in tilt_by_key]
            if missing:
                rows2 = await conn.fetch(
                    """
                    SELECT DISTINCT ON (sector) sector, macro_score
                    FROM sector_macro_scores
                    WHERE sector = ANY($1::text[])
                    ORDER BY sector, date DESC
                    """,
                    missing,
                )
                for r in rows2:
                    tilt_by_key.setdefault(
                        r["sector"],
                        float(r["macro_score"]) if r["macro_score"] is not None else 0.0,
                    )

    return {
        sym: tilt_by_key.get(sector_key_by_sym.get(sym) or "", 0.0)
        for sym in symbols
    }


# ── Position sizing (PRD §12) ─────────────────────────────────────────
def position_size_factor(
    *,
    risk: Optional[str],
    macro_multiplier: Optional[float] = None,
    sector_modifier: Optional[float] = None,
) -> float:
    """Return the multiplier the trade_planner should apply to its base
    position size.

    PRD §12 table:
      Risk LOW   → 1.2x
      Risk MED   → 1.0x
      Risk HIGH  → 0.6–0.8x  (we use 0.7 as the midpoint; tightened to 0.6
                              when sector_modifier is also negative)
    Soft tweak: when liquidity is TIGHT we already ratchet macro_multiplier
    to 0.8 in the regime engine, so the risk band naturally absorbs that.
    """
    base = {"LOW": 1.2, "MEDIUM": 1.0, "HIGH": 0.7}.get((risk or "MEDIUM").upper(), 1.0)
    # If the sector itself is being penalized, tighten further at HIGH risk
    if base == 0.7 and sector_modifier is not None and sector_modifier < -2.0:
        base = 0.6
    # Sanity: never below 0.3, never above 1.5
    return round(max(0.3, min(1.5, base)), 2)


def explain_position_size(
    *, risk: Optional[str], sector_modifier: Optional[float] = None,
) -> str:
    """Human-readable reason for the chosen multiplier. Used in /why API."""
    factor = position_size_factor(risk=risk, sector_modifier=sector_modifier)
    if factor >= 1.2:
        return f"Low-risk regime → {factor}× base size (lean in)"
    if factor <= 0.7:
        sector_note = (
            " · sector also penalized" if sector_modifier and sector_modifier < -2 else ""
        )
        return f"High-risk regime → {factor}× base size (trim){sector_note}"
    return f"Neutral regime → {factor}× base size"
