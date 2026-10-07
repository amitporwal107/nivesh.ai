"""research/charting/export.py's §38.7/§38.12 (W2) wiring: each symbol payload's
`timeframes.1W` / `timeframes.1M` are built from resample.py + the SAME `_INDICATOR_SPECS` /
`_compute_indicator_payload` the daily series uses. Not a re-test of resample.py's own OHLCV math
(test_resample.py owns that) -- this file is about the export PLUMBING: the right frame reaches
the right resampler, the right indicator code runs on it, and the result round-trips through the
gzip snapshot file. TC-129..TC-131 in test_reports/charting_w2_weekly_monthly.md.
"""
from __future__ import annotations

import gzip
import json
import math

import pandas as pd
import pytest

from research.charting import export, resample, series


# ---------------------------------------------------------------------------
# TC-129 — fixture-mode export: every symbol carries both timeframes, correctly shaped
# ---------------------------------------------------------------------------

def test_tc129_fixture_export_every_symbol_has_both_timeframes_correctly_shaped(tmp_path):
    manifest = export.build_snapshot(fixture=True, out_dir=tmp_path)
    for entry in manifest["symbols"]:
        payload = json.loads(gzip.decompress((tmp_path / entry["file"]).read_bytes()))
        assert set(payload["timeframes"]) == {"1W", "1M"}
        for tf in ("1W", "1M"):
            tf_payload = payload["timeframes"][tf]
            assert isinstance(tf_payload["bars"], list)
            for row in tf_payload["bars"]:
                assert len(row) == 7 and isinstance(row[6], bool)     # date,o,h,l,c,v,incomplete
            assert set(tf_payload["indicators"]) == set(payload["indicators"])   # same 8 series ids


# ---------------------------------------------------------------------------
# TC-130 — the weekly/monthly bars written by export.py for a real symbol are exactly
# resample.py's own output for that symbol's daily df (the plumbing doesn't reorder/relabel)
# ---------------------------------------------------------------------------

def test_tc130_exported_weekly_monthly_bars_match_resample_module_directly(tmp_path):
    manifest = export.build_snapshot(top_n=1, out_dir=tmp_path)
    entry = manifest["symbols"][0]
    payload = json.loads(gzip.decompress((tmp_path / entry["file"]).read_bytes()))

    from research.charting import bars as bars_mod
    df = bars_mod.load_symbol(entry["symbol"])

    for tf, resampler in resample.RESAMPLERS.items():
        expected = resampler(df)
        got = payload["timeframes"][tf]["bars"]
        assert len(got) == len(expected)
        for row, (_, erow) in zip(got, expected.iterrows()):
            assert row[0] == erow["date"].strftime("%Y-%m-%d")
            assert row[1:6] == [float(erow["open"]), float(erow["high"]), float(erow["low"]),
                                float(erow["close"]), float(erow["volume"])]
            assert row[6] == bool(erow["incomplete"])


# ---------------------------------------------------------------------------
# TC-131 — indicators on the weekly timeframe are the SAME series code as the daily ones,
# independently recomputed from the served weekly bars (not copied/relabeled from daily)
# ---------------------------------------------------------------------------

def test_tc131_weekly_indicators_are_independently_recomputed_series_code_not_copied_from_daily(tmp_path):
    manifest = export.build_snapshot(fixture=True, out_dir=tmp_path)
    entry = next(e for e in manifest["symbols"] if e["symbol"] == "SYN2")   # 300 bars -- fully warm
    payload = json.loads(gzip.decompress((tmp_path / entry["file"]).read_bytes()))

    weekly_bars = payload["timeframes"]["1W"]["bars"]
    wdf = pd.DataFrame([[r[0], r[1], r[2], r[3], r[4], r[5]] for r in weekly_bars],
                        columns=["date", "open", "high", "low", "close", "volume"])
    wdf["date"] = pd.to_datetime(wdf["date"])

    served = payload["timeframes"]["1W"]["indicators"]["sma_20"]["values"]
    expected = series.sma(wdf, 20)
    recomputed = {d.strftime("%Y-%m-%d"): v for d, v in zip(wdf["date"], expected) if not math.isnan(v)}
    served_map = {row[0]: row[1] for row in served}
    assert served_map.keys() == recomputed.keys()
    for d in served_map:
        assert abs(served_map[d] - recomputed[d]) < 1e-9

    # Sanity: the weekly series is NOT just the daily series relabeled -- different bar count and
    # (for this fixture) a different sma_20 value set entirely.
    daily_sma20 = {row[0] for row in payload["indicators"]["sma_20"]["values"]}
    weekly_sma20 = set(served_map)
    assert daily_sma20 != weekly_sma20
    assert len(weekly_bars) != len(payload["bars"])


# ---------------------------------------------------------------------------
# TC-98-style guard (W2 own, distinct symbol) — determinism: two exports of the same fixture
# input reproduce byte-identical timeframes content too, not just the daily bars.
# ---------------------------------------------------------------------------

def test_export_timeframes_are_deterministic_across_runs(tmp_path):
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    m1 = export.build_snapshot(fixture=True, out_dir=out1)
    m2 = export.build_snapshot(fixture=True, out_dir=out2)
    for e1, e2 in zip(m1["symbols"], m2["symbols"]):
        p1 = json.loads(gzip.decompress((out1 / e1["file"]).read_bytes()))
        p2 = json.loads(gzip.decompress((out2 / e2["file"]).read_bytes()))
        assert p1["timeframes"] == p2["timeframes"]


# ── --include-ni3 is an export-selection switch, not enablement ──────────────────────────────────
def test_include_ni3_provider_does_not_consult_or_change_the_registry():
    """The flag must never be a back door to enablement. Asserted structurally: the provider's own
    source imports the four detector modules and nothing else."""
    import ast
    import inspect

    from research.charting import export, pattern_registry

    tree = ast.parse(inspect.getsource(export.ni3_pattern_provider).lstrip())
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert modules == {
        "research.charting.patterns", "research.charting.patterns_ni3",
        "research.charting.patterns_p1", "research.charting.patterns_p2",
    }
    assert not any("registry" in m for m in modules)

    before = pattern_registry.registry_hash()
    export.ni3_pattern_provider()
    assert pattern_registry.registry_hash() == before
    assert len(pattern_registry.enabled_families()) == 3


def test_the_two_export_modes_are_distinguishable_in_provenance():
    from research.charting import export, ni3_config

    assert export._detector_families(False) == ["SUPPORT_RESISTANCE", "RECTANGLE", "HH_HL"]
    assert len(export._detector_families(True)) == 19
    assert export._ni3_fingerprint() == ni3_config.NI3_FINGERPRINT
    assert export._ni3_version() == "1.0"
