"""Integrity checks -- CHARTING_PREREGISTRATION_V1 §8 "Integrity rules the run must pass
before any number is reported", built as callable functions + their own tests (task item 5),
not as one-off scripts: a formalisation of the ad hoc TC-40-style checks a prior session ran
by hand (`test_reports/charting_events_regime_quality.md` TC-40) into reusable code.

  - `kill_switch_check`   -- §8 "two runs with the same inputs produce identical pattern_id
    sets and identical event files (sha256)".
  - `assert_no_sealed_rows_in_dataset` -- §8 "the run manifest shows no input or output row
    dated 2023-01-01..2024-07-31", re-checked at the STUDY level across every row (pattern AND
    comparison-group) a caller built, independent of `extraction.py`'s own internal check.
  - `recompute_row_independently` / `recompute_sample` -- §8 "a sample of rows (entry, exits,
    returns, MFE/MAE, net return) is recomputed from raw bars and the cost engine by separate
    code, with zero mismatches."

This module never builds a dataset itself -- it only checks one already built (by
`events.pipeline`/`events.controls`/`study.run`, or a test's own synthetic rows).
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Mapping, Optional, Sequence

import pandas as pd

from research.charting.config import CONFIG
from research.charting.events import costs_bridge, writer
from research.charting.research_window import assert_no_sealed_rows, is_sealed_gap


# ── Kill switch (§8, bullet 1) ────────────────────────────────────────────────────────────


def kill_switch_check(rows_a: Sequence[dict], rows_b: Sequence[dict]) -> dict:
    """§8: "two runs with the same inputs produce identical pattern_id sets and identical
    event files (sha256)." `rows_a`/`rows_b` are the outputs of two SEPARATE calls to the
    same builder (e.g. `events.pipeline.build_event_dataset(...)["rows"]`, called twice over
    identical inputs) -- this function only compares them, it never runs the build itself
    (the caller decides what "the same inputs" means for whatever it is building).

    "Identical event files (sha256)" is checked via the CANONICAL serialisation
    `events.writer` itself uses (`writer._dump_jsonl`, the exact bytes `writer.write_run`
    would write to `events.jsonl`) -- not a re-derived hash of some other representation,
    so this check is really asking "would `write_run` produce byte-identical output," the
    literal §8 wording.
    """
    ids_a = {r["pattern_id"] for r in rows_a}
    ids_b = {r["pattern_id"] for r in rows_b}
    sha_a = hashlib.sha256(writer._dump_jsonl(rows_a)).hexdigest()
    sha_b = hashlib.sha256(writer._dump_jsonl(rows_b)).hexdigest()
    pattern_ids_match = ids_a == ids_b
    files_match = sha_a == sha_b
    return {
        "passed": pattern_ids_match and files_match,
        "pattern_id_sets_match": pattern_ids_match,
        "event_file_sha256_match": files_match,
        "sha256_a": sha_a,
        "sha256_b": sha_b,
        "pattern_id_set_symmetric_difference": sorted(ids_a ^ ids_b),
        "n_rows_a": len(rows_a),
        "n_rows_b": len(rows_b),
    }


class RunDigest:
    """§8 kill-switch evidence, accumulated a chunk at a time instead of over a whole dataset.

    WHY
    ---
    `kill_switch_check` takes two fully-materialised row lists, so proving a run reproducible
    costs TWICE the dataset in memory — on top of the copy the report is using. At ~200 KB live
    per pattern row that is what made the v2 run's peak unsurvivable, and it is the last thing
    standing between the columnar report path and a run that finishes.

    Both pieces of §8's evidence stream. The sha256 is over `writer._dump_jsonl`, which emits
    `"\n".join(lines) + "\n"`, so the bytes for a whole list are exactly the concatenation of the
    bytes for its chunks — fed in the same order. The pattern-id set is strings, which are small.

    ORDER IS PART OF THE ANSWER. "Identical event files (sha256)" is a claim about the bytes
    `writer.write_run` would produce, and those follow the caller's own generation order. Feed
    chunks in the order the run assembles them (symbols sorted, rows within a symbol as extracted)
    or the digest is of a different file — which would read as a reproducibility FAILURE rather
    than as the usage error it is. `tests/test_study_integrity.py` pins the chunked digest against
    the whole-list hash.
    """

    __slots__ = ("_h", "pattern_ids", "n_rows")

    def __init__(self) -> None:
        self._h = hashlib.sha256()
        self.pattern_ids: set = set()
        self.n_rows = 0

    def update(self, rows: Sequence[dict]) -> "RunDigest":
        """Add one chunk — typically one symbol's rows — in run order."""
        if not rows:
            return self                         # `_dump_jsonl([])` is b"", so this is a no-op
        self._h.update(writer._dump_jsonl(rows))
        self.pattern_ids.update(r["pattern_id"] for r in rows)
        self.n_rows += len(rows)
        return self

    def hexdigest(self) -> str:
        return self._h.hexdigest()


def kill_switch_check_digests(digest_a: "RunDigest", digest_b: "RunDigest") -> dict:
    """`kill_switch_check`'s verdict from two `RunDigest`s — identical output, without either
    dataset ever being held whole."""
    pattern_ids_match = digest_a.pattern_ids == digest_b.pattern_ids
    sha_a, sha_b = digest_a.hexdigest(), digest_b.hexdigest()
    files_match = sha_a == sha_b
    return {
        "passed": pattern_ids_match and files_match,
        "pattern_id_sets_match": pattern_ids_match,
        "event_file_sha256_match": files_match,
        "sha256_a": sha_a,
        "sha256_b": sha_b,
        "pattern_id_set_symmetric_difference": sorted(digest_a.pattern_ids ^ digest_b.pattern_ids),
        "n_rows_a": digest_a.n_rows,
        "n_rows_b": digest_b.n_rows,
    }


# ── Sealed-window absence (§8, bullet 3) ─────────────────────────────────────────────────


def assert_no_sealed_rows_in_dataset(rows: Sequence[Mapping]) -> None:
    """§8: "the run manifest shows no input or output row dated 2023-01-01..2024-07-31" --
    re-checked here across EVERY row in a fully-assembled dataset (pattern rows AND every
    comparison-group row a caller built), as a final belt-and-braces gate before a report is
    built from `rows` -- independent of `extraction.extract_events`'s own internal check on
    its transition log (defense in depth, same discipline `research_window.py`'s own module
    docstring documents for `assert_no_sealed_rows`). Raises `SealedWindowError` naming the
    first offending date; never silently drops or filters."""
    assert_no_sealed_rows(r["signal_date"] for r in rows)


# ── Independent recomputation (§8, bullet 4 / TC-40) ─────────────────────────────────────


def _independent_adv(bars: pd.DataFrame, t_idx: int, n: int) -> Optional[float]:
    """20-day average traded value, hand-rolled directly from `bars` (NOT calling
    `events.outcomes.adv_inr_at`) -- an off-by-one in THAT function's own window would
    otherwise never be caught by "recomputing from raw bars ... by separate code"."""
    start = t_idx - n + 1
    if start < 0 or t_idx >= len(bars):
        return None
    window = bars.iloc[start : t_idx + 1]
    closes = window["close"].to_numpy(dtype=float)
    vols = window["volume"].to_numpy(dtype=float)
    if not (all(map(math.isfinite, closes)) and all(map(math.isfinite, vols))):
        return None
    return float((closes * vols).mean())


def recompute_row_independently(
    bars: pd.DataFrame, row: Mapping, *, horizon: int = 5, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> dict:
    """Recompute one row's entry, horizon-`h` exit, close_return, MFE, MAE, and base-scenario
    net_before_tax DIRECTLY from `bars` (hand-rolled arithmetic, not calling
    `events.outcomes`/`events.extraction`) plus the cost ENGINE (`costs_bridge
    .compute_cost_block`, the same "separate code, cost engine" split §8/TC-40 describes),
    and compares each figure to the row's own value. Returns
    `{"event_id", "checks": {field: bool}}` -- `True` means "independent recomputation
    matches the row" (or "both sides correctly agree the figure is unavailable" -- an
    unavailable/unavailable pair is a MATCH, not skipped and not a mismatch, since the row
    correctly reporting "unavailable" IS the thing being verified in that case).

    A BEARISH row (§37.4: no trade priced) only gets one check, `bearish_flagged` -- "no
    stop/target block and `costs.short_side_costs == 'NOT_MODELLED'`", the very fact TC-40's
    own "bearish rows flagged" line checks.
    """
    cost_cfg = cost_cfg or costs_bridge.CostConfig()
    t_idx = row["confirmation_bar_index"]
    n = len(bars)
    checks: dict = {}

    sd = pd.Timestamp(row["signal_date"]).normalize()
    in_range = 0 <= t_idx < n and pd.Timestamp(bars["date"].iloc[t_idx]).normalize() == sd
    checks["signal_date_valid"] = bool(in_range and not is_sealed_gap(sd))

    if row.get("direction") == "BEARISH":
        flagged = (row.get("targets") is None) and ((row.get("costs") or {}).get("short_side_costs") == "NOT_MODELLED")
        checks["bearish_flagged"] = bool(flagged)
        return {"event_id": row.get("event_id"), "checks": checks}

    entry_idx = t_idx + 1
    row_primary = (row.get("entry") or {}).get("primary")
    if entry_idx >= n:
        checks["entry"] = row_primary is None
        return {"event_id": row.get("event_id"), "checks": checks}

    indep_entry = float(bars["open"].iloc[entry_idx])
    row_entry = row_primary["price"] if row_primary else None
    checks["entry"] = row_entry is not None and math.isclose(indep_entry, row_entry, rel_tol=1e-9)

    exit_idx = entry_idx + horizon
    fwd = (((row.get("outcomes") or {}).get("forward_returns")) or {}).get(horizon)
    if exit_idx >= n:
        checks["exit_close"] = fwd is None or fwd.get("available") is False
        return {"event_id": row.get("event_id"), "checks": checks}

    indep_exit_close = float(bars["close"].iloc[exit_idx])
    indep_close_return = (indep_exit_close - indep_entry) / indep_entry
    window_hi = bars["high"].iloc[entry_idx : exit_idx + 1].to_numpy(dtype=float)
    window_lo = bars["low"].iloc[entry_idx : exit_idx + 1].to_numpy(dtype=float)
    indep_mfe = (float(window_hi.max()) - indep_entry) / indep_entry
    indep_mae = (float(window_lo.min()) - indep_entry) / indep_entry

    available = bool(fwd and fwd.get("available"))
    checks["exit_close"] = available and math.isclose(indep_exit_close, fwd["exit_close"], rel_tol=1e-9)
    checks["close_return"] = available and math.isclose(indep_close_return, fwd["close_return"], rel_tol=1e-9)
    checks["mfe"] = available and math.isclose(indep_mfe, fwd["mfe"], rel_tol=1e-9)
    checks["mae"] = available and math.isclose(indep_mae, fwd["mae"], rel_tol=1e-9)

    qty = costs_bridge.qty_for_notional(indep_entry, cost_cfg.notional_inr)
    adv = _independent_adv(bars, t_idx, cfg["volume_baseline_bars"])
    entry_date = pd.Timestamp(bars["date"].iloc[entry_idx]).date()
    exit_date = pd.Timestamp(bars["date"].iloc[exit_idx]).date()
    cost_block = costs_bridge.compute_cost_block(
        entry_date=entry_date, entry_price=indep_entry, exit_date=exit_date, exit_price=indep_exit_close,
        qty=qty, adv_inr=adv, cfg=cost_cfg,
    )
    row_cost_block = (((row.get("costs") or {}).get("by_horizon")) or {}).get(horizon)
    row_net = None
    if row_cost_block and row_cost_block.get("available"):
        row_net = row_cost_block["scenarios"]["base"]["net_before_tax"]
    indep_net = cost_block["scenarios"]["base"]["net_before_tax"] if cost_block.get("available") else None
    if indep_net is None or row_net is None:
        checks["net_before_tax"] = indep_net is None and row_net is None
    else:
        checks["net_before_tax"] = math.isclose(indep_net, row_net, rel_tol=1e-6, abs_tol=1e-6)

    return {"event_id": row.get("event_id"), "checks": checks}


def recompute_sample(
    bars_by_symbol: Mapping[str, pd.DataFrame], rows: Sequence[Mapping], *, horizon: int = 5,
    sample_size: Optional[int] = None, seed: int = 0, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> dict:
    """§8 / TC-40: `recompute_row_independently` over a (optionally seeded-sampled) subset of
    `rows`, tallied per field -- the same `match`/`mismatch` shape TC-40's own real-data table
    used. `passed` is `True` iff every tallied field has zero mismatches across the sample."""
    ordered = sorted(rows, key=lambda r: r.get("event_id") or "")
    if sample_size is not None and sample_size < len(ordered):
        rng = random.Random(seed)
        ordered = sorted(rng.sample(ordered, k=sample_size), key=lambda r: r.get("event_id") or "")

    tally: dict = {}
    mismatched_event_ids: list = []
    for row in ordered:
        bars = bars_by_symbol[row["symbol"]]
        result = recompute_row_independently(bars, row, horizon=horizon, cfg=cfg, cost_cfg=cost_cfg)
        row_mismatch = False
        for field, ok in result["checks"].items():
            entry = tally.setdefault(field, {"match": 0, "mismatch": 0})
            if ok:
                entry["match"] += 1
            else:
                entry["mismatch"] += 1
                row_mismatch = True
        if row_mismatch:
            mismatched_event_ids.append(row.get("event_id"))

    total_mismatches = sum(v["mismatch"] for v in tally.values())
    return {
        "n_rows": len(ordered), "horizon": horizon, "fields": tally,
        "mismatched_event_ids": mismatched_event_ids, "passed": total_mismatches == 0,
    }
