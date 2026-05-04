"""Portfolio-aware filtering: don't recommend stocks the user already
holds heavily, or sectors they're already overexposed to.

Inputs:
  - signals: list of positional signal dicts (with nse_symbol)
  - portfolio_holdings: list of {nse_symbol, sector, value} from Mongo

Output: filtered list with `portfolio_warning` annotations where applicable.
Caller decides whether to drop or just flag.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional

# Default thresholds — overridable per-call
DEFAULT_SECTOR_CAP_PCT = 35.0      # warn if sector already >35% of portfolio
DEFAULT_SAME_STOCK_CAP_PCT = 8.0   # warn if user already has >8% in this stock


def _sector_weights(holdings: Iterable[dict]) -> Dict[str, float]:
    total = 0.0
    by_sector: Dict[str, float] = defaultdict(float)
    for h in holdings:
        v = float(h.get("value") or 0.0)
        if v <= 0:
            continue
        total += v
        sec = (h.get("sector") or "Unknown").strip()
        by_sector[sec] += v
    if total == 0:
        return {}
    return {k: v / total * 100.0 for k, v in by_sector.items()}


def _stock_weights(holdings: Iterable[dict]) -> Dict[str, float]:
    total = 0.0
    by_sym: Dict[str, float] = defaultdict(float)
    for h in holdings:
        v = float(h.get("value") or 0.0)
        sym = (h.get("nse_symbol") or h.get("symbol") or "").upper()
        if v <= 0 or not sym:
            continue
        total += v
        by_sym[sym] += v
    if total == 0:
        return {}
    return {k: v / total * 100.0 for k, v in by_sym.items()}


def annotate(signals: List[dict],
             holdings: List[dict],
             *,
             sector_cap_pct: float = DEFAULT_SECTOR_CAP_PCT,
             same_stock_cap_pct: float = DEFAULT_SAME_STOCK_CAP_PCT,
             symbol_to_sector: Optional[Dict[str, str]] = None,
             ) -> List[dict]:
    """Annotate each signal with a portfolio_warning if applicable.
    Does not drop anything — caller decides."""
    sec_w = _sector_weights(holdings)
    stk_w = _stock_weights(holdings)
    sym2sec = symbol_to_sector or {}

    out: List[dict] = []
    for s in signals:
        sym = (s.get("nse_symbol") or s.get("symbol") or "").upper()
        warnings: List[str] = []

        if sym and stk_w.get(sym, 0) >= same_stock_cap_pct:
            warnings.append(
                f"Already {stk_w[sym]:.1f}% in {sym} — consider adding only on dip"
            )

        sec = sym2sec.get(sym)
        if sec and sec_w.get(sec, 0) >= sector_cap_pct:
            warnings.append(
                f"Sector {sec} already {sec_w[sec]:.1f}% of portfolio (>{sector_cap_pct:.0f}%)"
            )

        annotated = dict(s)
        if warnings:
            annotated["portfolio_warning"] = warnings
        out.append(annotated)
    return out


def filter_actionable(signals: List[dict],
                      holdings: List[dict],
                      *,
                      drop_if_overexposed: bool = False,
                      **kw) -> List[dict]:
    annotated = annotate(signals, holdings, **kw)
    if not drop_if_overexposed:
        return annotated
    return [s for s in annotated if "portfolio_warning" not in s]
