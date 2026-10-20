"""Turns the data platform's reversal snapshot (DaaS GET /v1/features/reversal-snapshot) into reversal_rules input rows.

Pure: no network, no database. The route (routes/positional.py GET /api/positional/reversal-candidates) fetches the
snapshot and calls `build()`. Nothing here fills a gap with a neutral value: a benchmark close missing on any of the
last 21 bars makes relative strength unknown, an industry the platform does not classify has no sector context, and a
stock with no classified announcement in the window has an unknown catalyst.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Mapping, Optional

from services.positional_engine import reversal_rules as rr
from services.positional_engine import setup_rules

FUND_KEYS = ("roe_pct", "debt_to_equity", "interest_cover", "promoter_pledged_pct", "pe_ttm", "revenue_growth_yoy_pct",
             "pat_growth_yoy_pct", "operating_margin_pct", "cfo_cr")

DATA_LIMITS = [
    "Sector context exists only for stocks the platform classifies by NSE industry (index constituents); others show an unknown sector.",
    "Fundamentals come from the latest stored quarterly filings and ratios; cash flow and some ratios are empty on staging, so the fundamental component is often unknown.",
    "Catalyst evidence uses announcements the platform has classified; no classified announcement in 30 days is unknown, not neutral.",
    "The score is rule-based with untuned hypothesis weights. It is not a probability and has not been validated out of sample.",
]


def _bars(raw: List[List[Any]]) -> List[Dict[str, Any]]:
    return [{"d": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in raw
            if r[2] is not None and r[3] is not None and r[4] is not None]


def _index_for(bars: List[Dict[str, Any]], bench: Mapping[str, float]) -> Optional[List[float]]:
    """Benchmark closes on the stock's dates, or None when any is missing (relative strength is then unknown)."""
    out = [bench.get(b["d"]) for b in bars]
    return None if not out or any(v is None for v in out) else out  # type: ignore[return-value]


def build(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    bench = {x["d"]: x["c"] for x in snapshot.get("benchmark_closes", []) if x.get("c") is not None}
    sectors = snapshot.get("sectors") or {}
    rows: List[Dict[str, Any]] = []
    for r in snapshot.get("rows", []):
        bars = _bars(r.get("bars") or [])
        if not bars:
            continue
        ctx = sectors.get(r.get("industry") or "")
        sector_ctx = None
        if ctx:
            sector_ctx = {"industry": ctx["industry"], "stocks": ctx.get("stocks"),
                          "rs_20d": ctx.get("rs_20d"), "rs_change": ctx.get("rs_change"),
                          "breadth_above_50dma_pct": ctx.get("breadth_above_50dma_pct"),
                          "quadrant": rr.quadrant(ctx.get("rs_20d"), ctx.get("rs_change"))}
        scanner = {"close": bars[-1]["c"], "prev_close": bars[-2]["c"] if len(bars) > 1 else None,
                   "traded_value_cr_20d": r.get("traded_value_cr_20d"), "has_reference": r.get("has_reference"),
                   "series": r.get("series"), "is_etf": r.get("is_etf"), "price_band_pct": r.get("price_band_pct")}
        excl = setup_rules.exclusion(scanner)
        rows.append({
            "symbol": r["symbol"], "sector": r.get("sector"), "industry": r.get("industry"), "bars": bars,
            "index_closes": _index_for(bars, bench),
            "traded_value_cr_20d": r.get("traded_value_cr_20d"),
            "eligible": excl is None or excl == "illiquid", "exclusion": excl,
            "fundamentals": {k: r.get(k) for k in FUND_KEYS},
            "announcements": r.get("announcements") or [], "next_results_date": r.get("next_results_date"),
            "sector_ctx": sector_ctx, "latest_quarter_end": r.get("latest_quarter_end"),
        })
    return rows


def run(snapshot: Mapping[str, Any], near_pct: float, view: str = "candidates", limit: int = 100) -> Dict[str, Any]:
    as_of = date.fromisoformat(str(snapshot["as_of"])[:10])
    ev = rr.evaluate(build(snapshot), as_of, near_pct=near_pct)
    keep = {"candidates": ("confirmed", "trigger_ready", "early_reversal", "watchlist"),
            "all": rr.STATUSES}[view]
    listed = [x for x in ev["rows"] if x["status"] in keep]
    excluded_rows = [x for x in ev["rows"] if x["status"] == "excluded"] if view == "candidates" else []
    sectors = sorted(({**c, "quadrant": rr.quadrant(c.get("rs_20d"), c.get("rs_change"))}
                      for c in (snapshot.get("sectors") or {}).values()),
                     key=lambda c: (c["rs_20d"] is None, -(c["rs_20d"] or 0)))
    return {
        "as_of": ev["as_of"], "near_low_pct": ev["near_low_pct"], "view": view,
        "rules": rr.public_rules(), "universe": ev["universe"], "prefilter": snapshot.get("prefilter"),
        "benchmark": snapshot.get("benchmark"), "source": snapshot.get("source"), "data_limits": DATA_LIMITS,
        "sectors": sectors, "rows": listed[:limit], "excluded": excluded_rows[:limit],
        "truncated": len(listed) > limit,
    }
