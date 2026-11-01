"""Run a stock screen on the day's feature rows — the one implementation behind POST /api/screeners/run and the Copilot chat.

Moved out of routes/screeners.py (2026-11-01, docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W2) so the chat's
`screen_stocks` answer runs exactly the screen the Screener page runs, not a copy of it. The move changed no behaviour:
tests/test_screeners_run.py is the proof and was not edited.

Read-only and market data only: this module never touches the database and never writes. Authentication is the caller's job
(the route's `get_current_user`; the chat builder runs inside an authenticated chat turn).

`run_screen(request)` returns the route's response body:
    {"ok", "as_of_date", "widget", "coverage", "matched", "universe_complete"}
with `ok: False` (never "0 matches") when the data platform did not answer.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from services.copilot_tools import daas_client, stock_intelligence

logger = logging.getLogger(__name__)

# The data platform's read is paged; one call reads the whole day up to this many stocks.
DAY_READ_LIMIT = 5000
# Request bucket → nidp.stock_features_daily.market_cap_bucket.
CAP_BUCKETS = {"large": "LARGE_CAP", "mid": "MID_CAP", "small": "SMALL_CAP"}


# Mutual-fund evidence per stock, from the smart-money scanner (nidp.mf_holdings_deltas). The scanner
# covers one index universe (Nifty 500), so a stock outside it has no value for these metrics and fails a
# rule on them, exactly like any other metric the day does not carry. widget key → (scanner field, label).
MF_UNIVERSE = "nifty500"
MF_METRICS = {
    "mfChange":   ("mf_shares_pct_chg", "MF holding change"),
    "amcsUp":     ("amcs_up",           "Fund houses raising"),
    "amcsDn":     ("amcs_dn",           "Fund houses cutting"),
    "amcsHolding": ("amcs_holding",     "Fund houses holding"),
}


class UnknownMetric(ValueError):
    """A rule names a metric the screener does not carry. The route answers it with 422."""


class ScreenRunCondition(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    op: Literal["over", "under"] = "over"
    value: float = Field(allow_inf_nan=False)      # "20" (the saved shape) or 20


class ScreenRunRequest(BaseModel):
    conditions: List[ScreenRunCondition] = Field(default_factory=list, max_length=50)
    bucket: Optional[Literal["", "large", "mid", "small"]] = None
    sector: Optional[str] = Field(default=None, max_length=60)
    limit: int = Field(default=200, ge=1, le=500)   # matching stocks sent back
    # Add the mutual-fund columns to the rows even when no rule uses them (they are read anyway when one does).
    include_funds: bool = False

    @model_validator(mode="after")
    def _something_to_screen_on(self) -> "ScreenRunRequest":
        if not self.conditions and not self.bucket and not (self.sector or "").strip():
            raise ValueError("a screen needs at least one rule, a size bucket or a sector")
        return self


def number(value: Any) -> Optional[float]:
    """A metric value as a number; None when the stock has no value for it."""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) else parsed


def passes(row: Dict[str, Any], filters: Dict[str, float]) -> bool:
    """The rule the stock_screener widget applies to its rows: bounds are
    inclusive, and a stock with no value for a metric fails a rule on it."""
    for filter_key, bound in filters.items():
        value = number(row.get(filter_key[:-4]))
        if value is None:
            return False
        if filter_key.endswith("_min") and value < bound:
            return False
        if filter_key.endswith("_max") and value > bound:
            return False
    return True


def _filled(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    return {"filled": sum(1 for r in rows if r.get(key) not in (None, "")), "total": len(rows)}


async def mf_by_symbol() -> Optional[Dict[str, Dict[str, Any]]]:
    """Scanner rows keyed by symbol, shaped as widget keys. None when the scanner did not answer:
    that is a gap in the evidence, never "no fund activity"."""
    if not daas_client.is_configured():
        return None
    try:
        status, body = await daas_client.get_raw(
            "/desk/smart-money/scanner", {"window": "3M", "universe": MF_UNIVERSE, "limit": 500})
    except Exception as exc:  # noqa: BLE001
        logger.warning("screeners.run: the smart-money scanner read failed: %r", exc)
        return None
    rows = body.get("rows") if status == 200 and isinstance(body, dict) else None
    if not isinstance(rows, list):
        logger.warning("screeners.run: the smart-money scanner answered HTTP %s", status)
        return None
    return {
        str(r["symbol"]).upper(): {k: number(r.get(src)) for k, (src, _label) in MF_METRICS.items()}
        for r in rows if isinstance(r, dict) and r.get("symbol")
    }


def filters_of(conditions: List[ScreenRunCondition]) -> Dict[str, float]:
    """"over" → <key>_min, "under" → <key>_max: the filter keys the widget reads.
    Two rules on the same side of one metric keep the stricter bound (they are ANDed)."""
    filters: Dict[str, float] = {}
    for c in conditions:
        if c.op == "over":
            filters[f"{c.key}_min"] = max(filters.get(f"{c.key}_min", c.value), c.value)
        else:
            filters[f"{c.key}_max"] = min(filters.get(f"{c.key}_max", c.value), c.value)
    return filters


def metric_catalog() -> Dict[str, Any]:
    """The widget's own label map and columns: every metric a row carries."""
    return stock_intelligence.build_stock_screener_widget([])


def check_metrics(conditions: List[ScreenRunCondition], catalog: Optional[Dict[str, Any]] = None) -> None:
    """Raise UnknownMetric when a rule names a metric the screener does not carry."""
    cat = catalog or metric_catalog()
    unknown = sorted({c.key for c in conditions} - set(cat["filter_labels"]) - set(MF_METRICS))
    if unknown:
        raise UnknownMetric(f"Unknown screening metric: {', '.join(unknown)}")


async def run_screen(payload: ScreenRunRequest) -> Dict[str, Any]:
    catalog = metric_catalog()
    check_metrics(payload.conditions, catalog)
    filters = filters_of(payload.conditions)

    try:
        fetched = await stock_intelligence.nidp_stock_screener(sort_by="market_cap_cr", limit=DAY_READ_LIMIT)
    except Exception as exc:  # noqa: BLE001
        logger.error("screeners.run: the stock feature read failed: %r", exc)
        fetched = {"rows": [], "as_of_date": None, "ok": False}
    if not fetched.get("ok", True):
        # Same signal the chat screener gets: the source did not answer. Not a zero-match result.
        return {
            "ok": False, "as_of_date": None,
            "widget": stock_intelligence.build_stock_screener_widget([], initial_filters=filters),
            "coverage": {}, "matched": None, "universe_complete": False,
        }

    raw_rows: List[Dict[str, Any]] = fetched.get("rows") or []
    as_of = fetched.get("as_of_date")
    # Widget-keyed rows, one per raw row and in the same order.
    day = stock_intelligence.build_stock_screener_widget(raw_rows)["universe"]

    wants_funds = payload.include_funds or any(c.key in MF_METRICS for c in payload.conditions)
    if wants_funds:
        mf = await mf_by_symbol()
        for row in day:
            found = (mf or {}).get(str(row.get("ticker") or "").upper(), {})
            row.update({k: found.get(k) for k in MF_METRICS})

    coverage_keys = [col["key"] for col in catalog["columns"]] + [c.key for c in payload.conditions]
    if wants_funds:
        coverage_keys += list(MF_METRICS)
    coverage = {key: _filled(day, key) for key in dict.fromkeys(coverage_keys)}
    cap_bucket = CAP_BUCKETS.get(payload.bucket or "")
    if cap_bucket:
        coverage["bucket"] = _filled(raw_rows, "market_cap_bucket")

    sector = (payload.sector or "").strip().lower()
    matched = [
        i for i, row in enumerate(day)
        if (not cap_bucket or raw_rows[i].get("market_cap_bucket") == cap_bucket)
        and (not sector or sector in str(row.get("sector") or "").lower())
        and passes(row, filters)
    ]

    # Largest companies first (the widget's default order), then ticker, so the
    # cut at `limit` keeps the same stocks on every run even when market cap is empty.
    def _largest_first(i: int):
        mcap = number(day[i].get("mcap"))
        return (mcap is None, -(mcap or 0.0), str(day[i].get("ticker") or ""))

    matched.sort(key=_largest_first)
    widget = stock_intelligence.build_stock_screener_widget(
        [raw_rows[i] for i in matched[:payload.limit]], initial_filters=filters, as_of_date=as_of,
    )
    if wants_funds:
        # The widget builder only knows the feature-store columns; carry the fund metrics across.
        for row, i in zip(widget["universe"], matched[:payload.limit]):
            row.update({k: day[i].get(k) for k in MF_METRICS})
    return {
        "ok": True,
        "as_of_date": as_of,
        "widget": widget,
        "coverage": coverage,
        "matched": len(matched),
        # False when the read filled the data platform's page: later stocks were not screened.
        "universe_complete": len(raw_rows) < DAY_READ_LIMIT,
    }
