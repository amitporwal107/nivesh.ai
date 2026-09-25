"""Study driver -- CHARTING_PREREGISTRATION_V1 §3 ("Data, universe and windows") and §9
("Capability status at freeze"). BUILD ONLY in this session (task hard rule: "No results on
real data") -- every function here is written and tested against synthetic fixtures; nothing
in this module is invoked over the real Kite universe except the one-off, artifact-deleted
smoke run described in this package's own final report (schema/manifest/hash/kill-switch
checks ONLY -- never a hit rate, return, AUC or other performance number).

Assembles, in order:
  1. the v1 universe rule (`research.charting.universe.build_universe` -- >=250 bars, the
     sealed ETF list read without a header, §3's own "2,132 symbols, 291 ETFs removed");
  2. the §3/§37.5 demerger regimes (`apply_demerger_regimes`): each symbol split at every
     demerger by the `segmenter` hook (`research.corporate_actions.regime.regime_segments`) and
     the T-5..T+5 sessions trimmed by the `exclusion_mask` hook (`regime_break_mask`) -- the
     hooks are passed in, this module never imports `research.corporate_actions`;
  3. the two development segments (§3: pre-sealed 2021-01-01..2022-12-30, post-sealed
     2024-08-01..2026-09-18) via `events.pipeline.build_event_dataset`, which itself refuses
     any bar outside the requested segment's bound;
  4. the §3 "data quality" exclusion, per EVENT (`data_quality_event_exclusions`): an event whose
     own window holds a hard OHLCV defect is excluded and counted by rule; no symbol is dropped.
     (Review 2026-09-22 replaced a first version that dropped every non-VALID symbol and deleted
     demerger sessions without splitting, which spliced pre- and post-demerger bars.)
  5. an optional context join (`events.context_join`);
  6. a hashed run-folder write (`events.writer.write_run`) whose manifest is EXTENDED with
     every §2 field: the detector `config_hash` (checked against the prereg's frozen value
     FIRST, before anything else runs -- `assert_frozen_config_hash`), the `FEATURE_CONFIG`
     hash, the events schema/dataset version (already in `write_run`'s own manifest), cost/tax
     rule versions (already in `write_run`'s own manifest), the universe/data-quality/demerger
     exclusion accounting, and the prereg's own sha256 (computed from the file, not
     pre-stated -- §2's own instruction).
"""
from __future__ import annotations

import gc
import logging

import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research.charting import bars as bars_mod
from research.charting import regime, universe as universe_mod, validate
from research.charting.config import CONFIG, config_hash
from research.charting.events import context_join, costs_bridge, pipeline, schema, writer

# §2: "If the detector config_hash at run time differs from the value above, the run is
# invalid under this document."

logger = logging.getLogger(__name__)

FROZEN_CONFIG_HASH = "05167d3ae57f18602b8761ee21de311f5ffb96c428a16df5c119678a748514cf"

PREREG_PATH = Path(__file__).resolve().parents[3] / "docs" / "ai_research" / "CHARTING_PREREGISTRATION_V1.md"

# §3's own concrete calendar windows.
PRE_SEALED_START = pd.Timestamp("2021-01-01")
PRE_SEALED_END = pd.Timestamp("2022-12-30")
POST_SEALED_START = pd.Timestamp("2024-08-01")
POST_SEALED_END = pd.Timestamp("2026-09-18")


class ConfigHashMismatch(RuntimeError):
    """§2: the detector `config_hash` at run time differs from the prereg's frozen value --
    the run is invalid under CHARTING_PREREGISTRATION_V1 and must stop, not proceed."""


def assert_frozen_config_hash(cfg: dict = CONFIG) -> str:
    h = config_hash(cfg)
    if h != FROZEN_CONFIG_HASH:
        raise ConfigHashMismatch(
            f"detector config_hash {h} != frozen {FROZEN_CONFIG_HASH} -- "
            "run is invalid under CHARTING_PREREGISTRATION_V1 §2"
        )
    return h


def prereg_sha256(path: Optional[Path] = None) -> str:
    """§2: "the sha256 of every input file" / "the sha256 of the prereg" -- COMPUTED from the
    file here, never pre-stated as a literal (the one thing §2 explicitly says NOT to hardcode,
    unlike `FROZEN_CONFIG_HASH` above, which the prereg DOES pre-state and freeze)."""
    p = path or PREREG_PATH
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bars_within(bars: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    mask = (bars["date"] >= start) & (bars["date"] <= end)
    return bars.loc[mask].reset_index(drop=True)


# ── The §37.5 demerger-exclusion hook ────────────────────────────────────────────────────


def no_exclusions(symbol: str, dates, **_ignored) -> np.ndarray:
    """Default `exclusion_mask`: an all-False array (no demerger exclusion applied). Its
    signature deliberately matches `research.corporate_actions.regime.regime_break_mask(
    symbol, dates, *, events=None, config=None) -> np.ndarray` positionally (this module never
    imports that function -- another agent is building it right now -- but a caller can plug
    it straight in later: `study.run.build_segment(..., exclusion_mask=regime_break_mask,
    exclusion_mask_is_default=False)`, since `regime_break_mask`'s own extra keyword-only
    arguments all have defaults). Whenever THIS default is the one actually used, the caller
    (`build_segment`) records `demerger_exclusion: "NOT_APPLIED"` in the manifest loudly --
    never silently omitted, per the task brief's own instruction.
    """
    n = len(list(dates))
    return np.zeros(n, dtype=bool)


REGIME_KEY_SEPARATOR = "~r"


def no_segments(symbol: str, bars: pd.DataFrame) -> list:
    """Default `segmenter`: one regime, the frame unchanged (no demerger split applied)."""
    return [bars]


def apply_demerger_regimes(
    bars_by_symbol: Mapping[str, pd.DataFrame], *, exclusion_mask: Callable = no_exclusions,
    segmenter: Callable = no_segments, calendars: Optional[Mapping[str, Sequence]] = None,
) -> tuple:
    """§3 / §37.5: demergers are regime breaks -- pre- and post-demerger histories are separate
    regimes, never spliced, and sessions T-5..T+5 are excluded. So each symbol is first SPLIT into
    regimes (`segmenter(symbol, bars)`, e.g. `research.corporate_actions.regime.regime_segments`),
    and only then are the excluded sessions (`exclusion_mask(symbol, dates)`, e.g.
    `regime_break_mask`) removed. Because the split falls at the ex-date, the excluded sessions
    sit at the edges of each regime; removing them trims a regime, it never joins two.

    An excluded session INSIDE a regime (a mask without the matching split) would splice the
    bars on either side of it into one series, so it raises instead.

    A symbol with one regime keeps its own key; a symbol with several becomes
    `SYMBOL~r1`, `SYMBOL~r2`, ... -- separate frames, so no pattern, feature or outcome window can
    span a demerger. Returns `(bars_by_key, report_by_symbol)` with the regime count and the
    number of sessions excluded per symbol.

    `calendars` (symbol -> the symbol's full trading dates) is passed to the mask as `calendar=` so
    T-5..T+5 is counted on the whole history, not on a segment-windowed frame (a window that starts
    after an ex-date would otherwise have its first sessions treated as T..T+5).
    """
    out: dict = {}
    report: dict = {}
    for symbol, bars in bars_by_symbol.items():
        kept: list = []
        excluded = 0
        for seg in segmenter(symbol, bars):
            if calendars is not None and symbol in calendars:
                mask = np.asarray(exclusion_mask(symbol, seg["date"], calendar=calendars[symbol]), dtype=bool)
            else:
                mask = np.asarray(exclusion_mask(symbol, seg["date"]), dtype=bool)
            if len(mask) != len(seg):
                raise ValueError(f"{symbol}: exclusion_mask returned {len(mask)} values for {len(seg)} bars")
            keep = np.flatnonzero(~mask)
            if len(keep) and keep[-1] - keep[0] + 1 != len(keep):
                raise ValueError(
                    f"{symbol}: excluded sessions fall inside a regime, not at its edges -- removing them would "
                    "splice the bars on either side; pass the matching segmenter (regime_segments) with the mask"
                )
            excluded += int(mask.sum())
            seg = seg.loc[~mask].reset_index(drop=True)
            if len(seg):
                kept.append(seg)
        if len(kept) == 1:
            out[symbol] = kept[0]
        else:
            for k, seg in enumerate(kept, start=1):
                out[f"{symbol}{REGIME_KEY_SEPARATOR}{k}"] = seg
        report[symbol] = {"regimes": len(kept), "sessions_excluded": excluded}
    return out, report


def base_symbol(key: str) -> str:
    return key.split(REGIME_KEY_SEPARATOR, 1)[0]


# ── §3 universe rule + data-quality exclusion ────────────────────────────────────────────


def apply_universe_rule(
    bars_by_symbol: Mapping[str, pd.DataFrame], *, min_bars: int = universe_mod.MIN_BARS_DEFAULT,
    etf_symbols=None, calendar=None, max_missing_dates: Optional[int] = None,
):
    """§3: ">= 250 bars, minus the sealed ETF list ... read without a header" --
    `universe.build_universe`, called here rather than duplicated."""
    return universe_mod.build_universe(
        bars_by_symbol.items(), etf_symbols=etf_symbols, min_bars=min_bars,
        max_missing_dates=max_missing_dates, calendar=calendar,
    )


def data_quality_findings(bars_by_key: Mapping[str, pd.DataFrame], *, calendar=None) -> dict:
    """Per frame: the dates of hard OHLCV defects (`validate.HARD_INVALID_RULE_IDS`) and the
    frame's overall `validate.symbol_status`, for disclosure. Soft findings (missing or
    incomplete candles) are counted, never used to exclude."""
    out: dict = {}
    for key, bars in bars_by_key.items():
        findings = validate.validate_symbol(bars, calendar=calendar)
        status = validate.symbol_status(bars, findings)
        hard = sorted({(pd.Timestamp(f.date).normalize(), f.rule_id) for f in findings
                       if f.rule_id in validate.HARD_INVALID_RULE_IDS and f.date is not None})
        soft = sum(1 for f in findings if f.rule_id in validate.SOFT_RULE_IDS)
        out[key] = {"hard": hard, "soft_findings": soft, "status": status.data_quality_status}
    return out


def data_quality_event_exclusions(
    rows: Sequence[dict], bars_by_key: Mapping[str, pd.DataFrame], findings: Mapping[str, dict], *,
    lookback_bars: int, forward_bars: int,
) -> tuple:
    """§3: "events whose data_quality_status is FAIL are excluded and counted by reason." There is
    no per-event FAIL value (validate.py rates a whole frame; patterns.py records every pattern as
    VALID), so an event FAILS when a hard OHLCV defect is dated inside the bars it depends on:
    `lookback_bars` before its confirmation bar t (the detector's maximum pattern length) through
    `forward_bars` after t (entry plus the longest horizon). Symbols are never dropped wholesale --
    one bad candle must not delete years of clean history, and dropping symbols that stopped
    trading would add survivorship bias. Returns `(kept_rows, report)`; each excluded event is
    counted once, under the first defect rule found in its window."""
    kept: list = []
    by_rule: dict = {}
    for row in rows:
        f = findings.get(row["symbol"])
        bars = bars_by_key.get(row["symbol"])
        if not f or not f["hard"] or bars is None:
            kept.append(row)
            continue
        t = int(row["confirmation_bar_index"])
        lo = pd.Timestamp(bars["date"].iloc[max(t - lookback_bars, 0)]).normalize()
        hi = pd.Timestamp(bars["date"].iloc[min(t + forward_bars, len(bars) - 1)]).normalize()
        hit = next((rule for d, rule in f["hard"] if lo <= d <= hi), None)
        if hit is None:
            kept.append(row)
        else:
            by_rule[hit] = by_rule.get(hit, 0) + 1
    status_counts: dict = {}
    for f in findings.values():
        status_counts[f["status"]] = status_counts.get(f["status"], 0) + 1
    report = {
        "rule": (f"event excluded when a hard OHLCV defect ({', '.join(sorted(validate.HARD_INVALID_RULE_IDS))}) is "
                 f"dated within [t - {lookback_bars}, t + {forward_bars}] bars of its own frame; no symbol dropped"),
        "events_excluded": sum(by_rule.values()),
        "events_excluded_by_rule": by_rule,
        "frames_with_soft_findings": sum(1 for f in findings.values() if f["soft_findings"]),
        "frame_status_counts": status_counts,
    }
    return kept, report


# ── Segment build ─────────────────────────────────────────────────────────────────────────


def build_segment(
    bars_by_symbol: Mapping[str, pd.DataFrame], *, segment: str, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, etf_symbols=None, calendar=None,
    exclusion_mask: Callable = no_exclusions, segmenter: Callable = no_segments,
    calendars: Optional[Mapping[str, Sequence]] = None, exclusion_mask_is_default: Optional[bool] = None,
    attach_context: bool = False, out_dir=None, now=None,
    input_file_hashes: Optional[Sequence[dict]] = None, max_workers: int = 1,
    compress_events: bool = False, extraction_cache_dir=None, progress=None,
    join_max_workers: Optional[int] = None,
) -> dict:
    """One segment's full §3 pipeline: universe rule -> data-quality exclusion -> demerger
    hook -> `events.pipeline.build_event_dataset` (own segment-bound guard) -> optional
    context join -> hashed run-folder write with the extended §2 manifest.

    `max_workers` (PERFORMANCE ONLY, default 1 = serial, byte-identical output for any value --
    PERF-PARALLEL performance work): forwarded to `events.pipeline.build_event_dataset` (per-
    symbol extraction) and, when `attach_context=True`, to `events.context_join
    .attach_to_event_rows_by_symbol` (per-symbol context join) -- see each function's own
    docstring. Universe/data-quality/demerger and the final manifest write stay single-process
    (not this package's own perf target; see the PERF-PARALLEL task brief).

    `input_file_hashes`: pre-computed `[{"path":.., "sha256":.., "row_count":..}, ...]` (e.g.
    from `research.charting.bars.provenance().files`) -- accepted rather than computed
    internally, since hashing the FULL real Kite history directory on every call (2,926
    symbols' worth of part files) would make this function far too slow to unit-test with
    small synthetic fixtures; when omitted, the manifest records
    `"input_file_hashes": "NOT_COMPUTED"` loudly rather than silently leaving the key out.

    `exclusion_mask_is_default`: explicit override for the manifest's own
    `demerger_exclusion` field. Defaults to an identity check
    (`exclusion_mask is no_exclusions`) -- a caller plugging in
    `research.corporate_actions.regime.regime_break_mask` (possibly wrapped in
    `functools.partial` to pin its own `config=`) should pass `False` explicitly, since a
    partial/wrapped callable is never `is no_exclusions` even when it legitimately IS a real
    exclusion function.
    """
    assert_frozen_config_hash(cfg)

    universe = apply_universe_rule(bars_by_symbol, etf_symbols=etf_symbols, calendar=calendar)
    included_bars = {s: bars_by_symbol[s] for s in universe.included}

    filtered_bars, demerger_report = apply_demerger_regimes(
        included_bars, exclusion_mask=exclusion_mask, segmenter=segmenter, calendars=calendars,
    )
    is_default = exclusion_mask_is_default if exclusion_mask_is_default is not None else (
        exclusion_mask is no_exclusions and segmenter is no_segments
    )

    result = pipeline.build_event_dataset(
        filtered_bars, segment=segment, cfg=cfg, cost_cfg=cost_cfg, max_workers=max_workers,
        cache_dir=extraction_cache_dir, progress=progress,
    )
    findings = data_quality_findings(filtered_bars, calendar=calendar)
    rows, dq = data_quality_event_exclusions(
        result["rows"], filtered_bars, findings,
        lookback_bars=cfg["maximum_pattern_length"], forward_bars=1 + max(schema.HORIZONS),
    )
    # `result["rows"]` is not needed again, and holding it doubles peak memory through the context
    # join below: the join runs in forked workers that PICKLE ENRICHED COPIES BACK, so the original
    # and enriched sets coexist. Measured 2026-09-25: the run peaked at 50 GB and was OOM-killed
    # twice on a 62 GB host. Dropping the reference here lets the originals be collected as the
    # enriched rows arrive. `rows` still holds everything that survived the exclusion filter.
    result["rows"] = None
    n_rows_in = len(rows)

    for row in rows:
        row["base_symbol"] = base_symbol(row["symbol"])

    if attach_context:
        logger.info("context join: %d rows across %d symbols, %d workers",
                    n_rows_in, len({r["symbol"] for r in rows}), max_workers)
        rows_by_symbol: dict = {}
        for r in rows:
            rows_by_symbol.setdefault(r["symbol"], []).append(r)
        # `rows` and `rows_by_symbol` hold the SAME objects, so dropping the flat list alone frees
        # nothing. `consume=True` makes the join pop each symbol as its enriched replacement
        # arrives, which is the only point at which an original can actually be released.
        del rows
        # FEWER WORKERS THAN EXTRACTION, DELIBERATELY. Extraction is CPU-bound on small inputs and
        # scales with cores; the context join carries the whole enriched row set through forked
        # workers, whose private copy-on-write pages all count against the cgroup. Measured
        # 2026-09-25: at 8 workers the unit climbed ~2 GB/min past 37 GB with no plateau, having
        # already been OOM-killed twice at 50 GB. Memory here is bounded by worker count, not by
        # core count, so this is capped independently.
        join_workers = max(1, min(join_max_workers or max(1, max_workers // 3), max_workers))
        logger.info("context join: %d symbols, %d workers (extraction used %d)",
                    len(rows_by_symbol), join_workers, max_workers)
        enriched_by_symbol = context_join.attach_to_event_rows_by_symbol(
            rows_by_symbol, filtered_bars, cfg=cfg, max_workers=join_workers, consume=True,
        )
        del rows_by_symbol                      # emptied by the join; this drops the husk
        rows = [r for symbol in sorted(enriched_by_symbol) for r in enriched_by_symbol[symbol]]
        del enriched_by_symbol                  # `rows` now owns them; this is references only
        gc.collect()
        logger.info("context join complete: %d rows", len(rows))

    manifest = None
    if out_dir is not None:
        cost_versions = {r["versioning"]["cost_rule_version"] for r in rows if r["versioning"].get("cost_rule_version")}
        tax_versions = {r["versioning"]["tax_rule_version"] for r in rows if r["versioning"].get("tax_rule_version")}
        manifest = writer.write_run(
            rows, out_dir, segment=segment, symbols=sorted(filtered_bars), cfg=cfg,
            cost_rule_versions=cost_versions, tax_rule_versions=tax_versions, now=now,
            compress=compress_events,
        )
        manifest["feature_config_hash"] = regime.feature_config_hash()
        manifest["prereg_sha256"] = prereg_sha256()
        manifest["universe"] = {
            "included": list(universe.included),
            "excluded": [{"symbol": e.symbol, "reason": e.reason, "detail": e.detail} for e in universe.excluded],
        }
        manifest["data_quality_exclusions"] = dq
        manifest["demerger_exclusion"] = "NOT_APPLIED" if is_default else "APPLIED"
        manifest["demerger_regimes"] = demerger_report
        manifest["input_file_hashes"] = list(input_file_hashes) if input_file_hashes is not None else "NOT_COMPUTED"
        (Path(out_dir) / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    return {
        "rows": rows, "segment": segment, "universe": universe, "data_quality_exclusions": dq,
        "demerger_regimes": demerger_report, "manifest": manifest,
        # The EXACT bars each row in `rows` was actually built from (post universe/data-quality/
        # demerger filtering, and -- via build_pre_sealed_segment/build_post_sealed_segment --
        # already windowed to the segment's own date span). A caller running
        # `study.integrity.recompute_sample` against this segment's own `rows` MUST use these
        # bars, not whatever raw `bars_by_symbol` it originally passed in -- `confirmation_bar_index`
        # is an offset into THIS frame, not into a longer, unwindowed/unfiltered one.
        "bars_by_symbol": filtered_bars,
    }


def build_pre_sealed_segment(bars_by_symbol: Mapping[str, pd.DataFrame], **kwargs) -> dict:
    """§3: "Pre-sealed: 2021-01-01 -> 2022-12-30." Each symbol's frame is windowed to this
    span BEFORE `build_segment` runs (so a symbol whose real history runs well past 2022 is
    never accidentally fed post-sealed bars for this segment)."""
    windowed = {s: bars_within(b, PRE_SEALED_START, PRE_SEALED_END) for s, b in bars_by_symbol.items()}
    calendars = {s: b["date"] for s, b in bars_by_symbol.items()}  # full trading dates, for demerger session counting
    return build_segment(windowed, segment=schema.SEGMENT_PRE_SEALED, calendars=calendars, **kwargs)


def build_post_sealed_segment(bars_by_symbol: Mapping[str, pd.DataFrame], **kwargs) -> dict:
    """§3: "Post-sealed: 2024-08-01 -> 2026-09-18, with its own fresh history: no sealed bar
    is used as lookback, as input to any feature, or as a forward bar." Windowing each
    symbol's frame to `[POST_SEALED_START, POST_SEALED_END]` (which itself starts strictly
    after the sealed gap ends) is what makes this guarantee structural, not just asserted --
    `build_event_dataset`'s own `assert_segment_bounds` then re-checks it independently."""
    windowed = {s: bars_within(b, POST_SEALED_START, POST_SEALED_END) for s, b in bars_by_symbol.items()}
    calendars = {s: b["date"] for s, b in bars_by_symbol.items()}  # full trading dates (dates only, no prices)
    return build_segment(windowed, segment=schema.SEGMENT_POST_SEALED, calendars=calendars, **kwargs)


def build_study(
    bars_by_symbol: Mapping[str, pd.DataFrame], *, out_dir_pre=None, out_dir_post=None, **kwargs,
) -> dict:
    """Task item 4: "builds both segments." One call, two independent segment builds (each
    with its own universe/data-quality/demerger pass over the SAME `bars_by_symbol`, since a
    symbol's data-quality status and demerger exclusions can legitimately differ once its
    frame is windowed down to each segment's own span)."""
    pre = build_pre_sealed_segment(bars_by_symbol, out_dir=out_dir_pre, **kwargs)
    post = build_post_sealed_segment(bars_by_symbol, out_dir=out_dir_post, **kwargs)
    return {"pre_sealed": pre, "post_sealed": post}
