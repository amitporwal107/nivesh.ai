"""Top-level orchestration for the historical pattern event dataset -- docs/charting.md S35.2
"Historical event dataset" and the task brief's own segment split: "The dataset is built
separately for the two development segments: pre-sealed (bars <= 2022-12-31) and post-sealed
(bars >= 2024-08-01, fresh history -- do not feed sealed bars as lookback)."

`build_event_dataset` is the entry point a caller should use rather than calling
`extraction.extract_events` directly per symbol, because it ALSO enforces the segment bound on
every symbol's bars frame before extraction runs at all (not merely relying on
`replay.replay`'s own sealed-window guard, which only refuses a window that OVERLAPS the sealed
block -- a frame that ends on, say, 2023-06-01 would pass that guard by itself while still
violating "the dataset is built separately for the two segments", since post-sealed rows must
never be built from a frame containing pre-sealed history as lookback either). This is this
module's OWN, additional guard, on top of (not instead of) `research_window`'s.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

import pandas as pd

from research.charting.config import CONFIG
from research.charting.events import costs_bridge, extraction, schema, writer
from research.charting.research_window import SealedWindowError


def assert_segment_bounds(bars: pd.DataFrame, segment: str, *, symbol: str = "UNKNOWN") -> None:
    """Raise `SealedWindowError` unless every bar in `bars` falls inside `segment`'s own bound
    (task item 6). `segment` must be one of `schema.SEGMENTS`."""
    if segment not in schema.SEGMENTS:
        raise ValueError(f"unknown segment {segment!r}; expected one of {schema.SEGMENTS}")
    if bars.empty:
        return
    min_d, max_d = pd.Timestamp(bars["date"].min()), pd.Timestamp(bars["date"].max())
    max_allowed = schema.SEGMENT_MAX_DATE.get(segment)
    min_allowed = schema.SEGMENT_MIN_DATE.get(segment)
    if max_allowed is not None and max_d > max_allowed:
        raise SealedWindowError(
            f"{symbol}: segment={segment!r} requires every bar <= {max_allowed.date()}, "
            f"but the frame's last bar is {max_d.date()}"
        )
    if min_allowed is not None and min_d < min_allowed:
        raise SealedWindowError(
            f"{symbol}: segment={segment!r} requires every bar >= {min_allowed.date()}, "
            f"but the frame's first bar is {min_d.date()}"
        )


def build_event_dataset(
    bars_by_symbol: dict, *, segment: str, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, out_dir=None, now: Optional[datetime] = None,
) -> dict:
    """Extract events for every symbol in `bars_by_symbol` (sorted order), enforcing the S35
    segment bound per symbol BEFORE any extraction runs (so a single mis-scoped symbol's frame
    fails loudly rather than silently narrowing the run). Optionally writes the run via
    `writer.write_run` when `out_dir` is given. Returns
    `{"rows", "segment", "symbols", "manifest"}` ("manifest" is `None` when `out_dir` is `None`).
    """
    rows: list[dict] = []
    for symbol in sorted(bars_by_symbol):
        bars = bars_by_symbol[symbol]
        assert_segment_bounds(bars, segment, symbol=symbol)
        rows.extend(extraction.extract_events(bars, symbol, cfg=cfg, cost_cfg=cost_cfg))

    manifest = None
    if out_dir is not None:
        cost_versions = {r["versioning"]["cost_rule_version"] for r in rows if r["versioning"]["cost_rule_version"]}
        tax_versions = {r["versioning"]["tax_rule_version"] for r in rows if r["versioning"]["tax_rule_version"]}
        manifest = writer.write_run(
            rows, out_dir, segment=segment, symbols=list(bars_by_symbol.keys()), cfg=cfg,
            cost_rule_versions=cost_versions, tax_rule_versions=tax_versions, now=now,
        )
    return {"rows": rows, "segment": segment, "symbols": sorted(bars_by_symbol), "manifest": manifest}
