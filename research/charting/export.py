"""Snapshot exporter — writes the committed chart snapshot that
`backend/services/research_chart.py` reads and `backend/routes/research_chart.py` serves
(research/charting/SNAPSHOT_SCHEMA.md is the contract this module implements).

    python3 -m research.charting.export                    # real data, top-50 display universe
    python3 -m research.charting.export --top-n 100
    python3 -m research.charting.export --fixture           # tiny synthetic snapshot for UI dev

Nothing here is read at request time — this is an offline batch job, run by hand or by CI,
that writes `backend/services/research_chart_snapshot/` (manifest.json + symbols/<SYMBOL>.json.gz).
The API layer never imports this module (research/ is not visible to the running backend image;
SNAPSHOT_SCHEMA.md "Location").

Display universe (real-data mode): the v1 research universe (`research.charting.universe`,
min_bars=250, sealed-ETF-list excluded) narrowed to the top `--top-n` symbols (default 50) by
median daily traded value (close * volume) over each symbol's trailing 250 bars. A full-universe
committed snapshot was estimated at ~180MB; narrowing to the most liquid names keeps the
snapshot small enough to commit. The exact rule actually used is recorded in
`manifest.universe_rule` on every run, not just documented here.

Adjustment status: Kite daily bars have been spot-checked, not exhaustively verified. IRCTC's
2021 1:5 split shows no discontinuity (looks back-adjusted); SIEMENS' and ABFRL's 2025 demergers
both DO show a raw discontinuity (looks NOT adjusted for those). `manifest.source.adjustment_status`
is therefore "ADJUSTED_SPLITS_BONUS_ONLY", never "ADJUSTED" outright, with the evidence restated in
`manifest.source.adjustment_note` so nobody downstream has to rediscover it.

Indicators: the P0 set for the price pane and a separate pane per PRD §8 — sma_20, sma_50, ema_20,
bollinger (all overlay the price pane), rsi_14, macd, atr_14, relative_volume (each gets its own
pane, named after its own indicator id). Warmup bars are omitted from `values` (never written as
NaN/0), matching SNAPSHOT_SCHEMA.md.

Two deliberate additions beyond the literal SNAPSHOT_SCHEMA.md text, both additive (no documented
key is removed or repurposed) and both called out to the orchestrator rather than made silently:

  1. `indicators[id].contract.output_fields` — the schema's only worked example (sma_20) is a
     single-output indicator, so `values` there is `[[date, value], ...]`. bollinger (5 outputs)
     and macd (3 outputs) need a multi-column row `[date, v1, v2, ...]`, and something has to say
     what those extra columns mean. `output_fields` (already part of the indicator contract per
     docs/charting.md §8.7 and already stored per-indicator in `series.INDICATORS`) names them in
     order, positionally aligned to each pandas function's own column order.
  2. `source.adjustment_note` — SNAPSHOT_SCHEMA.md's `source` object doesn't list a free-text
     field, but the task instruction is explicit: record the adjustment status honestly *and say
     so in the manifest*. `sim_lab_snapshot.json` (the precedent this package is told to follow
     closely) already carries a top-level `notes` object for exactly this kind of caveat, so a
     sibling explanatory field under `source` follows that precedent rather than inventing a new
     pattern.

Patterns hook: `pattern_provider`, an optional `Callable[[str, pd.DataFrame], list[dict]]`. When
None (the default — and the only mode this module actually exercises today), every symbol gets
`patterns: []`. `research.charting.patterns` (the detector engine) is being built in parallel by
another agent and is deliberately never imported here; once it lands, re-export by passing its
entry point as `pattern_provider` — no other change needed.

Weekly/monthly display timeframes (docs/charting.md §38.7, §38.12 row W2): each symbol payload
also carries `timeframes.1W` / `timeframes.1M`, built by `research.charting.resample` from the
SAME daily `df` this function already loaded, then run through the SAME `_INDICATOR_SPECS` /
`_compute_indicator_payload` used for the daily series -- no separate calculation path. Pattern
detection stays daily-only (§38.7: "a 120-bar maximum pattern cannot fit in 69 monthly bars") --
`timeframes.*` never gets a `patterns` key.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import math
import pathlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Collection, Optional

# Make `research.charting` importable whether this file is run as `python3 -m
# research.charting.export` (package context already resolves it) or as a bare script
# (`python3 research/charting/export.py`, no package context — relative imports would fail
# at import time before any code of ours gets to run). Mirrors research/charting/tests/conftest.py.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from research.charting import bars, config, indicator_catalogue, resample, series, universe, validate
from research.charting.tests import synth

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_TOP_N = 50
DEFAULT_OUT_DIR = _REPO_ROOT / "backend" / "services" / "research_chart_snapshot"

ADJUSTMENT_STATUS = "ADJUSTED_SPLITS_BONUS_ONLY"
ADJUSTMENT_NOTE = (
    "Evidence so far (not exhaustive): Kite daily bars look back-adjusted for ordinary splits and "
    "bonuses (IRCTC's 2021 1:5 split shows no discontinuity), but NOT for demergers (SIEMENS 2025 "
    "and ABFRL 2025 both show a raw price discontinuity around their demerger dates). Treat this "
    "series as adjusted for splits/bonuses only -- never assume full corporate-action adjustment."
)

PatternProvider = Callable[[str, pd.DataFrame], list]

# Overlay indicators share the "price" pane (drawn on the candles); everything else gets its own
# pane, named after its own indicator id (SNAPSHOT_SCHEMA.md: "price" overlays candles; else its
# own pane -- it doesn't name the non-price panes, so each indicator names its own).


# ---------------------------------------------------------------------------
# JSON-safety helpers
# ---------------------------------------------------------------------------

def _native(x):
    """Recursively convert pandas/numpy scalars to plain JSON-serializable Python values.
    bars.py's numeric columns can land on numpy int64 (e.g. volume) or numpy float64, and
    validate.Finding.date/observed can be a pandas Timestamp -- none of that is JSON-serializable
    as-is."""
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, dict):
        return {k: _native(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_native(v) for v in x]
    return x


def _finding_dict(f: validate.Finding) -> dict:
    return {"date": _native(f.date), "rule_id": f.rule_id, "observed": _native(f.observed),
            "detail": _native(f.detail)}


# ---------------------------------------------------------------------------
# Indicator computation -- P0 set, PRD §8 / §8.7
# ---------------------------------------------------------------------------
# Each spec's `compute` returns a DataFrame whose column order matches
# series.INDICATORS[registry_key]["output_fields"] exactly (verified against series.py's own
# column-construction order for bollinger/macd; single-output indicators are trivially aligned).

# SNAPSHOT_SCHEMA.md `plot_fields`: outputs the chart should draw, in order (absent = all outputs).

# The specs come from the controlled preset catalogue (§38.5, D-3), which is the single source of
# truth for what a chart can draw. They were written out by hand here until the catalogue existed;
# the eight ids that predate it are unchanged, so no stored layout or citation needs migrating.
_INDICATOR_SPECS: tuple[dict, ...] = indicator_catalogue.export_specs()


def _compute_indicator_payload(spec: dict, df: pd.DataFrame, dates: pd.Series) -> dict:
    frame = spec["compute"](df)
    registry_entry = series.INDICATORS[spec["registry_key"]]
    warmup = spec["warmup_period"] if spec["warmup_period"] is not None else registry_entry["warmup_period"]
    values = frame.to_numpy(dtype=float)
    rows = []
    for i in range(len(frame)):
        row = values[i]
        if np.isnan(row).any():          # omit warmup (and any other NaN) rows -- never write NaN/0
            continue
        rows.append([dates.iloc[i], *[float(v) for v in row]])
    contract = {
        "indicator_id": spec["id"],
        "parameters": spec["parameters"],
        "warmup_period": warmup,
        "calculation_version": registry_entry["calculation_version"],
        "missing_data_policy": registry_entry["missing_data_policy"],
        "output_fields": list(registry_entry["output_fields"]),   # additive -- see module docstring
        # Which catalogue entry produced this series (§38.5 "a chart view or research run cites
        # preset ids and the catalogue version, so it can be reproduced exactly").
        "preset_id": spec["preset_id"],
        "catalogue_version": indicator_catalogue.CATALOGUE_VERSION,
    }
    pane = spec["pane"]
    payload = {"contract": contract, "pane": pane, "values": rows}
    # Which outputs the chart draws. Bollinger's width/pos live on a different scale from price and must
    # not be drawn on the price pane; everything else draws all of its outputs.
    plot = indicator_catalogue.PLOT_FIELDS.get(spec["id"])
    if plot is not None:
        payload["plot_fields"] = list(plot)
    return payload


# ---------------------------------------------------------------------------
# Weekly / monthly display timeframes -- docs/charting.md §38.7, §38.12 row W2
# ---------------------------------------------------------------------------

def _build_timeframe_payload(rdf: pd.DataFrame) -> dict:
    """One `timeframes.{1W,1M}` entry from an already-resampled frame (research.charting.resample
    output: BARS_COLUMNS + `incomplete`). `bars` rows are 7-wide -- `[date, o, h, l, c, v,
    incomplete]` -- deliberately one element longer than the daily `bars` rows (6-wide), so the
    two shapes are never confused with each other; `indicators` reuses the exact same
    `_INDICATOR_SPECS` / `_compute_indicator_payload` the daily series uses, run against this
    resampled frame (§38.7: "same series code", never a separate calculation path).
    """
    dates = rdf["date"].dt.strftime("%Y-%m-%d")
    bars_rows = [
        [dates.iloc[i], float(rdf["open"].iloc[i]), float(rdf["high"].iloc[i]),
         float(rdf["low"].iloc[i]), float(rdf["close"].iloc[i]), float(rdf["volume"].iloc[i]),
         bool(rdf["incomplete"].iloc[i])]
        for i in range(len(rdf))
    ]
    indicators = {spec["id"]: _compute_indicator_payload(spec, rdf, dates) for spec in _INDICATOR_SPECS}
    return {"bars": bars_rows, "indicators": indicators}


def _build_timeframes(df: pd.DataFrame) -> dict:
    """`{"1W": {...}, "1M": {...}}` for one symbol's daily `df` -- resample.RESAMPLERS is the
    single place that knows how each timeframe is derived from daily bars."""
    return {tf: _build_timeframe_payload(resampler(df)) for tf, resampler in resample.RESAMPLERS.items()}


# ---------------------------------------------------------------------------
# Per-symbol payload
# ---------------------------------------------------------------------------

def _build_symbol_payload(
    symbol: str,
    df: pd.DataFrame,
    *,
    calendar: Optional[Collection],
    as_of,
    pattern_provider: Optional[PatternProvider],
) -> dict:
    df = df.reset_index(drop=True)
    findings = validate.validate_symbol(df, calendar=calendar)
    status = validate.symbol_status(df, findings, as_of=as_of, adjustment_verified=None)   # PIT_UNVERIFIED --
    # per-symbol corporate-action adjustment has NOT been individually checked (only the 3 spot
    # checks in ADJUSTMENT_NOTE), so no symbol earns PIT_VALIDATED just by being exported here.

    dates = df["date"].dt.strftime("%Y-%m-%d")
    bars_rows = [
        [dates.iloc[i], float(df["open"].iloc[i]), float(df["high"].iloc[i]),
         float(df["low"].iloc[i]), float(df["close"].iloc[i]), float(df["volume"].iloc[i])]
        for i in range(len(df))
    ]
    indicators = {spec["id"]: _compute_indicator_payload(spec, df, dates) for spec in _INDICATOR_SPECS}
    patterns = list(pattern_provider(symbol, df)) if pattern_provider is not None else []
    timeframes = _build_timeframes(df)

    return {
        "symbol": symbol,
        "bars": bars_rows,
        "data_quality_status": status.data_quality_status,
        "pit_status": status.pit_status,
        "findings": [_finding_dict(f) for f in findings],
        "indicators": indicators,
        "patterns": patterns,
        "timeframes": timeframes,
    }


def _write_symbol_file(payload: dict, path: Path) -> str:
    """Write one symbol's gzip JSON, sorted keys, fixed mtime=0 -- so re-running against the same
    input data reproduces the identical file (and therefore the identical sha256). Returns that
    sha256."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    path.write_bytes(gz)
    return hashlib.sha256(gz).hexdigest()


# ---------------------------------------------------------------------------
# Display-universe selection (real-data mode)
# ---------------------------------------------------------------------------

def _select_display_universe(bars_by_symbol: dict, top_n: int) -> tuple[list, "universe.UniverseResult"]:
    base = universe.build_universe(bars_by_symbol.items(), min_bars=universe.MIN_BARS_DEFAULT)
    scored = []
    for symbol in base.included:
        df = bars_by_symbol[symbol]
        dollar_volume = (df["close"].astype(float) * df["volume"].astype(float)).tail(250)
        scored.append((symbol, float(dollar_volume.median())))
    scored.sort(key=lambda t: t[1], reverse=True)
    return [s for s, _ in scored[:top_n]], base


# ---------------------------------------------------------------------------
# Fixture-mode universe (synthetic development data)
# ---------------------------------------------------------------------------

def _fixture_universe() -> tuple[list, dict, str, dict]:
    syn1 = synth.rect1()                                          # SYN1: 20 bars, RECT-1 base fixture
    closes = [100.0 + 15.0 * math.sin(i / 12.0) + i * 0.05 for i in range(300)]   # deterministic, no RNG
    syn2 = synth.bars_from_closes(closes, start_date="2024-01-02")    # SYN2: 300 bars, indicators fully warm
    bars_by_symbol = {"SYN1": syn1, "SYN2": syn2}
    universe_rule = (
        "fixture snapshot: synthetic development data from research.charting.tests.synth "
        "(SYN1 = rect1(), the RECT-1 base fixture, 20 bars; SYN2 = bars_from_closes() over a "
        "deterministic sine-wave close path, 300 bars, long enough for every P0 indicator to be "
        "fully warm). Not a real universe selection -- see manifest.fixture."
    )
    last_bar_date = max(df["date"].max() for df in bars_by_symbol.values())
    source = {
        "provider": "synthetic",
        "series": "daily",
        "adjustment_status": "UNVERIFIED",
        "adjustment_note": "Fixture data -- no real corporate action ever occurred, so adjustment status doesn't apply.",
        "files": [],
        "last_bar_date": last_bar_date.strftime("%Y-%m-%d"),
    }
    return sorted(bars_by_symbol), bars_by_symbol, universe_rule, source


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_snapshot(
    *,
    fixture: bool = False,
    top_n: int = DEFAULT_TOP_N,
    source_dir: Optional[str] = None,
    out_dir=DEFAULT_OUT_DIR,
    pattern_provider: Optional[PatternProvider] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build and write the snapshot to `out_dir`. Returns the manifest dict actually written.

    `pattern_provider(symbol, bars_df) -> list[dict]` is the hook for the pattern-detector engine
    once it lands (research.charting.patterns, built in parallel); left None, every symbol's
    `patterns` is `[]`, which is the only mode this module exercises today.
    """
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    now = now or datetime.now(timezone.utc)
    out_dir = Path(out_dir)
    symbols_dir = out_dir / "symbols"
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols_dir.mkdir(parents=True, exist_ok=True)
    for stale in symbols_dir.glob("*.json.gz"):     # a fresh run replaces the whole symbol set --
        stale.unlink()                                # never leaves an orphaned file from a prior top-N

    run_id = f"chart_{now.strftime('%Y%m%dT%H%M%SZ')}"
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    if fixture:
        display_symbols, bars_by_symbol, universe_rule, source = _fixture_universe()
        calendar = None       # MISSING_CANDLE needs a whole-universe calendar; skip it for a 2-symbol fixture
        as_of = None
    else:
        bars_by_symbol = dict(bars.load_all(source_dir))
        display_symbols, base = _select_display_universe(bars_by_symbol, top_n)
        prov = bars.provenance(source_dir)
        last_bar_date = max(df["date"].max() for df in bars_by_symbol.values() if not df.empty)
        source = {
            "provider": "kite",
            "series": "daily",
            "adjustment_status": ADJUSTMENT_STATUS,
            "adjustment_note": ADJUSTMENT_NOTE,
            "files": [{"name": Path(f.path).name, "sha256": f.sha256} for f in prov.files],
            "last_bar_date": last_bar_date.strftime("%Y-%m-%d"),
        }
        universe_rule = (
            f"v1 research universe (research.charting.universe.build_universe: min_bars="
            f"{universe.MIN_BARS_DEFAULT}, sealed ETF list excluded) narrowed to the top {top_n} "
            f"symbols by median daily traded value (close * volume) over each symbol's trailing "
            f"250 bars. {len(base.included)} symbols passed the base gates out of "
            f"{len(bars_by_symbol)} seen in the source directory; {len(base.excluded_symbols())} "
            f"were excluded (ETF and/or insufficient bars)."
        )
        # The trading calendar for MISSING_CANDLE is the union of dates across the WHOLE loaded
        # directory (not just the narrowed display set) -- research.charting.validate's own
        # documented rationale (build_trading_calendar docstring): a thin display universe alone
        # would make a poor stand-in calendar.
        calendar = validate.build_trading_calendar(bars_by_symbol.values())
        as_of = source["last_bar_date"]

    symbol_entries = []
    for symbol in display_symbols:
        df = bars_by_symbol[symbol]
        payload = _build_symbol_payload(symbol, df, calendar=calendar, as_of=as_of, pattern_provider=pattern_provider)
        file_rel = f"symbols/{symbol}.json.gz"
        sha256 = _write_symbol_file(payload, out_dir / file_rel)
        symbol_entries.append({
            "symbol": symbol,
            "n_bars": len(df),
            "first_date": df["date"].min().strftime("%Y-%m-%d"),
            "last_date": df["date"].max().strftime("%Y-%m-%d"),
            "data_quality_status": payload["data_quality_status"],
            "pit_status": payload["pit_status"],
            "file": file_rel,
            "sha256": sha256,
            "n_patterns": len(payload["patterns"]),
        })
    symbol_entries.sort(key=lambda e: e["symbol"])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "fixture": bool(fixture),
        "run_id": run_id,
        "generated_at": generated_at,
        "engine_version": config.ENGINE_VERSION,
        "profile": config.PROFILE_NAME,
        "config_hash": config.config_hash(),
        "source": source,
        "universe_rule": universe_rule,
        # §38.5: "the catalogue is versioned and hashed with the snapshot". The whole catalogue is
        # written here, not just its version, so the API can serve the dialog straight from the
        # snapshot and never describe a preset the series in this snapshot were not built from.
        "indicator_catalogue": indicator_catalogue.serialisable(),
        "indicator_catalogue_hash": indicator_catalogue.catalogue_hash(),
        "symbols": symbol_entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def detector_pattern_provider() -> PatternProvider:
    """Patterns known at each symbol's LAST bar, from research.charting.patterns (imported lazily so the
    exporter still runs if the detector module is absent). detect_as_of reads bars[0..t] only."""
    from research.charting.patterns import detect_as_of

    def provider(symbol: str, df: pd.DataFrame) -> list[dict]:
        return [p.to_dict() for p in detect_as_of(df, len(df) - 1, symbol=symbol)]

    return provider


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Export the research chart snapshot.")
    parser.add_argument("--fixture", action="store_true",
                        help="Write a tiny synthetic snapshot (fixture: true) for UI development, instead of real Kite data.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help=f"Display-universe size, real-data mode only (default {DEFAULT_TOP_N}).")
    parser.add_argument("--source-dir", default=None,
                        help="Override the Kite daily-bars directory (default: research.charting.bars.source_dir()).")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Snapshot output directory.")
    parser.add_argument("--with-patterns", action="store_true",
                        help="Run the P0 detectors (research.charting.patterns) at each symbol's last bar.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    provider = detector_pattern_provider() if args.with_patterns else None
    manifest = build_snapshot(fixture=args.fixture, top_n=args.top_n, source_dir=args.source_dir, out_dir=args.out_dir,
                              pattern_provider=provider)

    out_dir = Path(args.out_dir)
    total_bytes = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"snapshot written to {out_dir}")
    print(f"  fixture={manifest['fixture']}  run_id={manifest['run_id']}  config_hash={manifest['config_hash']}")
    print(f"  symbols exported: {len(manifest['symbols'])}")
    print(f"  total size on disk: {total_bytes / (1024 * 1024):.2f} MB")
    print(f"  patterns: {sum(s.get('n_patterns', 0) for s in manifest['symbols'])} across {len(manifest['symbols'])} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
