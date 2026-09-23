"""The controlled indicator preset catalogue — docs/charting.md §38.5 and decision D-3 (2026-09-22).

D-3: "Users choose from a controlled preset catalogue and cannot enter arbitrary parameters." That
decision is what makes the chart API's Sim Lab rule hold: every preset is precomputed at export, so
`backend/services/research_chart.py` still only reads the snapshot and computes nothing. There is no
on-demand compute endpoint and no free parameters, by design.

This module is the single source of truth for that catalogue. `research/charting/export.py` derives
its indicator specs from here, so a preset cannot exist in one place and not the other, and the
backend serves the same structure to the indicator dialog.

**Ids are frozen.** The eight series that were already in the snapshot keep their exact ids and
panes (`sma_20`, `sma_50`, `ema_20`, `bollinger`, `rsi_14`, `macd`, `atr_14`, `relative_volume`), so
an existing saved layout, a stored research citation or a running screen never has to be migrated.
New presets take the natural `<key>_<period>` form. A preset's `series_id` is the key it occupies in
a symbol payload's `indicators` map.

**Versioning.** `CATALOGUE_VERSION` is the human-readable version; `catalogue_hash()` is a content
hash over the normalised catalogue, written into the snapshot manifest at export. A chart view or a
research run cites preset ids plus that version, so it can be reproduced exactly (§38.5). Adding a
preset means a new version and a re-export — it is never a runtime change.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Iterator

import pandas as pd

from research.charting import series

CATALOGUE_VERSION = "1.0.0"

# §8.1–§8.4, the four groups the dialog shows.
CATEGORIES = ("trend", "momentum", "volatility", "volume")

# The price pane overlays. Everything else opens in its own pane (§38.5 "a non-overlay indicator
# opens in its own pane"); its pane id is its series id.
_OVERLAY = "price"


def _ma_preset(key: str, period: int, series_id: str) -> dict:
    """One moving-average preset. `series_id` is passed rather than derived because the two periods
    that predate this catalogue (`sma_20`, `sma_50`, `ema_20`) must keep the ids they already have."""
    fn = series.sma if key == "sma" else series.ema
    return {
        "preset_id": f"{key}_{period}",
        "name": f"{key.upper()} {period}",
        "series_id": series_id,
        "parameters": {"period": period},
        "warmup_period": period,
        "compute": lambda df, _fn=fn, _p=period: _fn(df, _p).to_frame(key),
    }


def _rsi_preset(period: int, series_id: str) -> dict:
    return {
        "preset_id": f"rsi_{period}",
        "name": f"RSI {period}",
        "series_id": series_id,
        "parameters": {"period": period},
        "warmup_period": None,
        "compute": lambda df, _p=period: series.rsi(df, _p).to_frame("rsi"),
    }


INDICATORS: tuple[dict[str, Any], ...] = (
    {
        "indicator_id": "sma",
        "name": "Simple moving average",
        "category": "trend",
        "registry_key": "sma",
        "default_pane": _OVERLAY,
        "presets": tuple(
            _ma_preset("sma", p, f"sma_{p}") for p in (10, 20, 50, 100, 200)
        ),
    },
    {
        "indicator_id": "ema",
        "name": "Exponential moving average",
        "category": "trend",
        "registry_key": "ema",
        "default_pane": _OVERLAY,
        "presets": tuple(
            _ma_preset("ema", p, f"ema_{p}") for p in (10, 20, 50, 100, 200)
        ),
    },
    {
        "indicator_id": "rsi",
        "name": "Relative strength index",
        "category": "momentum",
        "registry_key": "rsi",
        "default_pane": None,          # own pane
        # §38.5 "reference bands appear where the indicator defines them (e.g. RSI 30/70 with
        # shaded fill)". The bands are part of the catalogue, not a number the browser invents.
        "reference_bands": ({"value": 30.0, "label": "oversold"}, {"value": 70.0, "label": "overbought"}),
        "band_fill": {"from": 30.0, "to": 70.0},
        "presets": tuple(_rsi_preset(p, f"rsi_{p}") for p in (7, 14, 21)),
    },
    {
        "indicator_id": "macd",
        "name": "MACD",
        "category": "momentum",
        "registry_key": "macd",
        "default_pane": None,
        "reference_bands": ({"value": 0.0, "label": "zero"},),
        "presets": (
            {
                "preset_id": "macd_12_26_9",
                "name": "MACD 12/26/9",
                "series_id": "macd",
                "parameters": {"fast": 12, "slow": 26, "signal": 9},
                "warmup_period": None,
                "compute": lambda df: series.macd(df),
            },
        ),
    },
    {
        "indicator_id": "bollinger",
        "name": "Bollinger bands",
        "category": "volatility",
        "registry_key": "bollinger",
        "default_pane": _OVERLAY,
        "presets": (
            {
                "preset_id": "bollinger_20_2",
                "name": "Bollinger 20 × 2",
                "series_id": "bollinger",
                "parameters": {"period": 20, "n_std": 2.0},
                "warmup_period": None,
                "compute": lambda df: series.bollinger(df),
            },
        ),
    },
    {
        "indicator_id": "atr",
        "name": "Average true range",
        "category": "volatility",
        "registry_key": "atr",
        "default_pane": None,
        "presets": (
            {
                "preset_id": "atr_14",
                "name": "ATR 14",
                "series_id": "atr_14",
                "parameters": {"period": 14},
                "warmup_period": None,
                "compute": lambda df: series.atr(df, 14).to_frame("atr"),
            },
        ),
    },
    {
        "indicator_id": "relative_volume",
        "name": "Relative volume",
        "category": "volume",
        "registry_key": "relative_volume",
        "default_pane": None,
        "presets": (
            {
                "preset_id": "relative_volume_20",
                "name": "Relative volume 20",
                "series_id": "relative_volume",
                "parameters": {"n": 20},
                "warmup_period": None,
                "compute": lambda df: series.relative_volume(df, 20).to_frame("relative_volume_20"),
            },
        ),
    },
)

# Which outputs the chart draws when a preset has more than it should plot. Bollinger's width/pos
# live on a different scale from price and must never be drawn on the price pane.
PLOT_FIELDS: dict[str, tuple[str, ...]] = {
    "bollinger": ("bb_mid", "bb_upper", "bb_lower"),
    "macd": ("macd", "signal", "hist"),
}


def iter_presets() -> Iterator[tuple[dict, dict]]:
    """(indicator, preset) for every preset in the catalogue, in catalogue order."""
    for ind in INDICATORS:
        for preset in ind["presets"]:
            yield ind, preset


def pane_for(indicator: dict, preset: dict) -> str:
    """The pane a preset's series occupies: the shared price pane for overlays, else its own."""
    return _OVERLAY if indicator["default_pane"] == _OVERLAY else preset["series_id"]


def export_specs() -> tuple[dict, ...]:
    """The catalogue as `export.py` consumes it — one spec per preset, in catalogue order.

    Deliberately the same shape the export used before this catalogue existed, so
    `_compute_indicator_payload` did not have to change: id, registry_key, pane, parameters,
    warmup_period, compute.
    """
    specs: list[dict] = []
    for ind, preset in iter_presets():
        specs.append({
            "id": preset["series_id"],
            "registry_key": ind["registry_key"],
            "pane": pane_for(ind, preset),
            "parameters": dict(preset["parameters"]),
            "warmup_period": preset["warmup_period"],
            "compute": preset["compute"],
            "preset_id": preset["preset_id"],
            "indicator_id": ind["indicator_id"],
        })
    return tuple(specs)


def serialisable() -> dict:
    """The catalogue as the API serves it and the manifest records it: no callables, ordered, and
    stable enough to hash. `output_fields` and `calculation_version` come from the same
    `series.INDICATORS` registry the computation uses, so the dialog can never describe a preset
    differently from the series that was actually written."""
    out_indicators = []
    for ind in INDICATORS:
        registry = series.INDICATORS[ind["registry_key"]]
        entry = {
            "indicator_id": ind["indicator_id"],
            "name": ind["name"],
            "category": ind["category"],
            "default_pane": ind["default_pane"] or "own",
            "output_fields": list(registry["output_fields"]),
            "calculation_version": registry["calculation_version"],
            "missing_data_policy": registry["missing_data_policy"],
            "presets": [
                {
                    "preset_id": p["preset_id"],
                    "name": p["name"],
                    "series_id": p["series_id"],
                    "parameters": dict(p["parameters"]),
                    "pane": pane_for(ind, p),
                    "plot_fields": list(PLOT_FIELDS[p["series_id"]]) if p["series_id"] in PLOT_FIELDS else None,
                }
                for p in ind["presets"]
            ],
        }
        if ind.get("reference_bands"):
            entry["reference_bands"] = [dict(b) for b in ind["reference_bands"]]
        if ind.get("band_fill"):
            entry["band_fill"] = dict(ind["band_fill"])
        out_indicators.append(entry)
    return {"version": CATALOGUE_VERSION, "categories": list(CATEGORIES), "indicators": out_indicators}


def catalogue_hash() -> str:
    """sha256 over the serialised catalogue with sorted keys — the value written into the manifest,
    so a snapshot always says exactly which catalogue produced its series."""
    blob = json.dumps(serialisable(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()
