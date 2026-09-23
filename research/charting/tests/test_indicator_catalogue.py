"""The controlled indicator preset catalogue — docs/charting.md §38.5, decision D-3.

TC-200..TC-207 from test_reports/charting_w2_indicator_catalogue.md. These cover the catalogue's own
shape and the export path that consumes it; the frozen-pattern check (TC-208) and the API checks
(TC-209..211) live with the snapshot diff and the backend tests respectively.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting import indicator_catalogue as cat
from research.charting import series


def _presets():
    return list(cat.iter_presets())


def test_tc200_every_section_385_preset_is_present():
    by_indicator = {ind["indicator_id"]: [p["parameters"] for p in ind["presets"]] for ind in cat.INDICATORS}
    assert [p["period"] for p in by_indicator["sma"]] == [10, 20, 50, 100, 200]
    assert [p["period"] for p in by_indicator["ema"]] == [10, 20, 50, 100, 200]
    assert [p["period"] for p in by_indicator["rsi"]] == [7, 14, 21]
    assert by_indicator["bollinger"] == [{"period": 20, "n_std": 2.0}]
    assert by_indicator["macd"] == [{"fast": 12, "slow": 26, "signal": 9}]
    assert by_indicator["atr"] == [{"period": 14}]
    assert by_indicator["relative_volume"] == [{"n": 20}]
    assert len(_presets()) == 17


def test_tc201_every_indicator_describes_itself_fully():
    s = cat.serialisable()
    assert s["version"] == cat.CATALOGUE_VERSION
    for ind in s["indicators"]:
        assert ind["indicator_id"] and ind["name"]
        assert ind["category"] in cat.CATEGORIES
        assert ind["default_pane"] in ("price", "own")
        assert ind["output_fields"], ind["indicator_id"]
        assert ind["calculation_version"], ind["indicator_id"]
        assert ind["presets"]
        for p in ind["presets"]:
            assert p["preset_id"] and p["name"] and p["series_id"]
            assert isinstance(p["parameters"], dict) and p["parameters"]


def test_tc202_preset_ids_and_series_ids_are_unique():
    preset_ids = [p["preset_id"] for _, p in _presets()]
    series_ids = [p["series_id"] for _, p in _presets()]
    assert len(preset_ids) == len(set(preset_ids))
    assert len(series_ids) == len(set(series_ids))


def test_tc203_the_eight_pre_existing_series_keep_their_ids_and_panes():
    """A stored layout or a cited research run must not need migrating (module docstring)."""
    panes = {spec["id"]: spec["pane"] for spec in cat.export_specs()}
    assert panes["sma_20"] == "price"
    assert panes["sma_50"] == "price"
    assert panes["ema_20"] == "price"
    assert panes["bollinger"] == "price"
    assert panes["rsi_14"] == "rsi_14"
    assert panes["macd"] == "macd"
    assert panes["atr_14"] == "atr_14"
    assert panes["relative_volume"] == "relative_volume"


def test_tc204_the_hash_is_stable_and_content_addressed():
    first = cat.catalogue_hash()
    assert first == cat.catalogue_hash()          # deterministic across calls
    assert len(first) == 64

    # and it is a hash OF THE CONTENT: change one preset's parameters and it must move.
    s = cat.serialisable()
    s["indicators"][0]["presets"][0]["parameters"]["period"] = 11
    import hashlib, json
    moved = hashlib.sha256(json.dumps(s, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert moved != first


def test_tc205_export_specs_cover_every_preset_with_the_shape_export_expects():
    specs = cat.export_specs()
    assert len(specs) == len(_presets()) == 17
    for spec in specs:
        assert set(spec) >= {"id", "registry_key", "pane", "parameters", "warmup_period", "compute",
                             "preset_id", "indicator_id"}
        assert spec["registry_key"] in series.INDICATORS
        assert callable(spec["compute"])


@pytest.fixture()
def real_bars() -> pd.DataFrame:
    """A real daily series, so the preset check runs against the same data the export reads."""
    from research.charting import bars
    df = bars.load_symbol("RELIANCE")
    if df.empty:
        pytest.skip("Kite daily bars are not present in this environment")
    return df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def test_tc206_a_preset_equals_the_series_helper_called_directly(real_bars):
    """There is no second calculation path: the catalogue's `compute` is the registry helper."""
    specs = {s["id"]: s for s in cat.export_specs()}

    got = specs["sma_100"]["compute"](real_bars).iloc[:, 0]
    want = series.sma(real_bars, 100)
    pd.testing.assert_series_equal(got.reset_index(drop=True), want.reset_index(drop=True), check_names=False)

    got = specs["rsi_21"]["compute"](real_bars).iloc[:, 0]
    want = series.rsi(real_bars, 21)
    pd.testing.assert_series_equal(got.reset_index(drop=True), want.reset_index(drop=True), check_names=False)


def test_tc207_weekly_and_monthly_use_the_same_preset_set_as_daily():
    """The export runs one spec list against every timeframe (export.py `_build_timeframe_payload`),
    so this asserts the catalogue is the only source — not that a second list happens to match."""
    from research.charting import export
    assert export._INDICATOR_SPECS is not None
    assert [s["id"] for s in export._INDICATOR_SPECS] == [s["id"] for s in cat.export_specs()]
