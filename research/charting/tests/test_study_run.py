"""study/run.py: the §3/§9 study driver. Built and unit-tested against small synthetic
multi-symbol universes -- never run over the real Kite universe in this test file (that is
this package's own one-off, artifact-deleted smoke run, documented separately)."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.charting import context, regime
from research.charting.config import CONFIG
from research.charting.config import BARS_COLUMNS
from research.charting.events import schema
from research.charting.study import run as study_run
from research.charting.tests._events_helpers import (
    confirmed_hh_hl_with_runway,
    confirmed_rectangle_with_runway,
    confirmed_support_resistance_with_runway,
)


def _rebase_dates_pre_sealed(bars: pd.DataFrame, *, start: str = "2021-01-04") -> pd.DataFrame:
    """Re-date `bars` onto a fresh, guaranteed-unique business-day sequence -- works around a
    latent leap-day collision in `_events_helpers.shift_outside_sealed_window`
    (`date - DateOffset(years=3)` maps BOTH 2024-02-28 and 2024-02-29 onto 2021-02-28,
    producing a DUPLICATE_TIMESTAMP finding) that only a long enough fixture (>= ~250 bars,
    i.e. exactly what this file's >=250-bar universe tests need) crosses. Row order/values are
    untouched; only the date labels are replaced, so this is safe regardless of whether the
    input already collided."""
    out = bars.copy()
    out["date"] = pd.bdate_range(start=start, periods=len(out))
    return out


def _universe(tail_len: int = 260) -> dict:
    return {
        "SYN1": _rebase_dates_pre_sealed(confirmed_rectangle_with_runway(tail_len=tail_len)),
        "SYN2": _rebase_dates_pre_sealed(confirmed_support_resistance_with_runway(tail_len=tail_len)),
        "ZZ": _rebase_dates_pre_sealed(confirmed_hh_hl_with_runway(tail_len=tail_len)),
    }


# ── assert_frozen_config_hash / prereg_sha256 ────────────────────────────────────────────


def test_assert_frozen_config_hash_passes_for_the_real_config():
    assert study_run.assert_frozen_config_hash(CONFIG) == study_run.FROZEN_CONFIG_HASH


def test_assert_frozen_config_hash_raises_for_a_tampered_config():
    tampered = copy.deepcopy(CONFIG)
    tampered["atr_period"] = 999
    with pytest.raises(study_run.ConfigHashMismatch):
        study_run.assert_frozen_config_hash(tampered)


def test_prereg_sha256_matches_a_direct_hash_of_the_real_committed_file():
    import hashlib
    expected = hashlib.sha256(study_run.PREREG_PATH.read_bytes()).hexdigest()
    assert study_run.prereg_sha256() == expected
    assert len(study_run.prereg_sha256()) == 64


def test_prereg_sha256_changes_for_different_content(tmp_path):
    p = tmp_path / "fake_prereg.md"
    p.write_text("version 1")
    h1 = study_run.prereg_sha256(p)
    p.write_text("version 2")
    h2 = study_run.prereg_sha256(p)
    assert h1 != h2


# ── no_exclusions / apply_demerger_exclusion ─────────────────────────────────────────────


def test_no_exclusions_is_all_false_and_length_matched():
    dates = pd.bdate_range("2021-01-01", periods=10)
    mask = study_run.no_exclusions("ANY", dates)
    assert mask.shape == (10,)
    assert not mask.any()


def _dated_bars(n: int = 60, start: str = "2021-01-04") -> pd.DataFrame:
    closes = [100.0 + (i % 7) * 0.5 + i * 0.1 for i in range(n)]
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"date": dates, "open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes, "volume": [1e5] * n})


def _split_at(ex_date):
    def segmenter(symbol, bars):
        cut = bars["date"] >= pd.Timestamp(ex_date)
        return [bars.loc[~cut].reset_index(drop=True), bars.loc[cut].reset_index(drop=True)]
    return segmenter


def _mask_around(ex_date, sessions=5):
    def mask(symbol, dates):
        d = pd.DatetimeIndex(pd.to_datetime(list(dates)))
        ex = pd.Timestamp(ex_date)
        # T-5..T+5 in trading sessions of this frame: the 5 sessions before ex and ex + 5 after
        before = d[d < ex][-sessions:]
        after = d[d >= ex][: sessions + 1]
        return np.isin(d, before.append(after))
    return mask


def test_apply_demerger_regimes_default_changes_nothing():
    bars = confirmed_rectangle_with_runway(tail_len=10)
    out, report = study_run.apply_demerger_regimes({"SYN1": bars})
    pd.testing.assert_frame_equal(out["SYN1"], bars)
    assert report == {"SYN1": {"regimes": 1, "sessions_excluded": 0}}


def test_apply_demerger_regimes_splits_into_separate_regimes_and_trims_the_edges():
    bars = _dated_bars(60)
    ex = bars["date"].iloc[30]
    out, report = study_run.apply_demerger_regimes({"DMG": bars}, exclusion_mask=_mask_around(ex), segmenter=_split_at(ex))
    assert set(out) == {"DMG~r1", "DMG~r2"}  # two frames: nothing can span the demerger
    assert out["DMG~r1"]["date"].max() < bars["date"].iloc[25]  # T-5..T-1 trimmed from the pre regime
    assert out["DMG~r2"]["date"].min() > bars["date"].iloc[35]  # T..T+5 trimmed from the post regime
    assert report["DMG"] == {"regimes": 2, "sessions_excluded": 11}
    assert study_run.base_symbol("DMG~r2") == "DMG"


def test_a_mask_without_the_matching_split_raises_rather_than_splicing():
    bars = _dated_bars(60)
    ex = bars["date"].iloc[30]
    with pytest.raises(ValueError, match="splice"):
        study_run.apply_demerger_regimes({"DMG": bars}, exclusion_mask=_mask_around(ex))


def test_apply_demerger_regimes_mismatched_mask_length_raises():
    bars = confirmed_rectangle_with_runway(tail_len=10)
    with pytest.raises(ValueError):
        study_run.apply_demerger_regimes({"SYN1": bars}, exclusion_mask=lambda s, d: np.zeros(3, dtype=bool))


# ── data quality: per event, never whole symbols ──────────────────────────────────────────


def test_an_event_is_excluded_only_when_a_hard_defect_is_inside_its_own_window():
    bars = _dated_bars(200)
    bars.loc[20, "high"] = bars.loc[20, "close"] - 5  # HIGH_BELOW_BODY on bar 20
    findings = study_run.data_quality_findings({"X": bars})
    assert findings["X"]["hard"] and findings["X"]["status"] == "INVALID"
    near = {"symbol": "X", "confirmation_bar_index": 40}   # window [t-30, t+21] holds bar 20
    far = {"symbol": "X", "confirmation_bar_index": 150}   # window starts at bar 120
    kept, report = study_run.data_quality_event_exclusions([near, far], {"X": bars}, findings,
                                                           lookback_bars=30, forward_bars=21)
    assert kept == [far]  # the symbol is not dropped: its clean event survives
    assert report["events_excluded_by_rule"] == {"HIGH_BELOW_BODY": 1}
    assert report["frame_status_counts"] == {"INVALID": 1}


def test_an_empty_frame_contributes_no_events_and_is_reported():
    empty = pd.DataFrame(columns=list(BARS_COLUMNS))
    findings = study_run.data_quality_findings({"EMPTY": empty})
    assert findings["EMPTY"]["status"] == "BLOCKED"


# ── apply_universe_rule ───────────────────────────────────────────────────────────────────


def test_apply_universe_rule_excludes_short_frames_and_etfs():
    long_bars = confirmed_rectangle_with_runway(tail_len=260)  # >=250 bars
    short_bars = confirmed_rectangle_with_runway(tail_len=5)  # far fewer than 250
    result = study_run.apply_universe_rule(
        {"LONG": long_bars, "SHORT": short_bars, "AN_ETF": long_bars},
        etf_symbols=frozenset({"AN_ETF"}),
    )
    assert "LONG" in result.included
    assert "SHORT" not in result.included
    assert "AN_ETF" not in result.included
    assert any(e.symbol == "SHORT" and e.reason == "INSUFFICIENT_BARS" for e in result.excluded)
    assert any(e.symbol == "AN_ETF" and e.reason == "ETF" for e in result.excluded)


# ── build_segment: end to end on a small synthetic universe ─────────────────────────────


def test_build_segment_end_to_end_without_out_dir():
    bars_by_symbol = _universe()
    result = study_run.build_segment(bars_by_symbol, segment=schema.SEGMENT_PRE_SEALED)
    assert result["manifest"] is None
    assert len(result["rows"]) >= 2  # at least one confirmed event per clean symbol
    # bars_by_symbol in the result is the EXACT frame each row's confirmation_bar_index
    # indexes into (post universe/data-quality/demerger filtering) -- SYN2 was excluded at
    # the data-quality stage, so it must not appear here even though it was a valid input.
    # no symbol is dropped for data quality -- SYN2 stays; only events whose own window holds its defect go
    assert set(result["bars_by_symbol"].keys()) == {"SYN1", "SYN2", "ZZ"}
    assert set(result["universe"].included) == {"SYN1", "SYN2", "ZZ"}  # universe rule alone (bars/ETF) -- all 3 pass
    # SYN2's hand-crafted OHLC table (`_events_helpers._SR_RESISTANCE_ROWS`) genuinely has one
    # HIGH_BELOW_BODY bar -- a real defect; the events that depend on that bar are excluded and counted.
    dq = result["data_quality_exclusions"]
    assert dq["events_excluded_by_rule"].get("HIGH_BELOW_BODY", 0) >= 1
    assert dq["frame_status_counts"].get("INVALID") == 1
    assert all(r["base_symbol"] == r["symbol"] for r in result["rows"])  # no demerger split by default


def test_build_segment_writes_extended_manifest(tmp_path):
    bars_by_symbol = _universe()
    result = study_run.build_segment(bars_by_symbol, segment=schema.SEGMENT_PRE_SEALED, out_dir=tmp_path)
    manifest = result["manifest"]
    assert manifest is not None
    assert (tmp_path / "events.jsonl").exists()
    assert manifest["config_hash"] == study_run.FROZEN_CONFIG_HASH
    assert manifest["feature_config_hash"] == regime.feature_config_hash()
    assert manifest["prereg_sha256"] == study_run.prereg_sha256()
    assert manifest["demerger_exclusion"] == "NOT_APPLIED"  # default hook -- recorded loudly
    assert manifest["demerger_regimes"] == {s: {"regimes": 1, "sessions_excluded": 0} for s in ("SYN1", "SYN2", "ZZ")}
    assert manifest["input_file_hashes"] == "NOT_COMPUTED"  # never silently omitted
    assert set(manifest["universe"]["included"]) == {"SYN1", "SYN2", "ZZ"}
    assert manifest["data_quality_exclusions"]["events_excluded_by_rule"].get("HIGH_BELOW_BODY", 0) >= 1
    # manifest.json on disk matches the returned dict exactly (re-persisted after extension)
    import json
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest


def test_build_segment_records_demerger_applied_when_a_real_mask_is_plugged_in(tmp_path):
    bars_by_symbol = _universe()

    def exclude_none_by_signature(symbol, dates):  # mimics regime_break_mask's own signature
        return np.zeros(len(list(dates)), dtype=bool)

    result = study_run.build_segment(
        bars_by_symbol, segment=schema.SEGMENT_PRE_SEALED, out_dir=tmp_path,
        exclusion_mask=exclude_none_by_signature, exclusion_mask_is_default=False,
    )
    assert result["manifest"]["demerger_exclusion"] == "APPLIED"


def test_build_segment_passes_through_input_file_hashes_when_supplied(tmp_path):
    bars_by_symbol = _universe()
    hashes = [{"path": "fake.parquet", "sha256": "deadbeef", "row_count": 100}]
    result = study_run.build_segment(bars_by_symbol, segment=schema.SEGMENT_PRE_SEALED, out_dir=tmp_path, input_file_hashes=hashes)
    assert result["manifest"]["input_file_hashes"] == hashes


def test_build_segment_raises_on_a_tampered_config():
    bars_by_symbol = _universe()
    tampered = copy.deepcopy(CONFIG)
    tampered["atr_period"] = 999
    with pytest.raises(study_run.ConfigHashMismatch):
        study_run.build_segment(bars_by_symbol, segment=schema.SEGMENT_PRE_SEALED, cfg=tampered)


def test_build_segment_attach_context_adds_context_and_research_blocks():
    """Real committed index_history CSVs are used here (default-loading path), the same
    convention test_regime_market.py already uses for india_vix/breadth -- this is a
    technical-indicator plumbing check (shape only), never a pattern-performance result."""
    real_dir = Path(context.DEFAULT_INDEX_HISTORY_DIR)
    if not (real_dir / "NIFTY_500.csv").is_file():
        pytest.skip("real index_history CSVs not present")
    # tail_len=260 (not 40): the universe rule's own >=250-bar gate would otherwise exclude
    # this single symbol before extraction ever runs.
    bars_by_symbol = {"SYN1": _rebase_dates_pre_sealed(confirmed_rectangle_with_runway(tail_len=260))}
    result = study_run.build_segment(bars_by_symbol, segment=schema.SEGMENT_PRE_SEALED, attach_context=True)
    assert len(result["rows"]) >= 1
    for row in result["rows"]:
        assert "context" in row
        assert "research" in row
        assert row["research"]["pattern_id"] == row["pattern_id"]


# ── build_pre_sealed_segment / build_post_sealed_segment / build_study ──────────────────


def test_build_pre_sealed_segment_windows_out_of_range_bars_before_building():
    bars = confirmed_rectangle_with_runway(tail_len=260)  # entirely inside 2021 -- within window
    # Extend the frame far into the future (past 2022-12-30) -- build_pre_sealed_segment must
    # window it back down before build_event_dataset's own segment-bound guard ever sees it.
    from research.charting.tests._events_helpers import extend_with_closes
    last_close = float(bars["close"].iloc[-1])
    far_future = extend_with_closes(bars, [last_close + 0.1 * i for i in range(600)])  # runs past 2022-12-30
    assert far_future["date"].max() > study_run.PRE_SEALED_END

    result = study_run.build_pre_sealed_segment({"SYN1": far_future})  # must not raise
    assert result["segment"] == schema.SEGMENT_PRE_SEALED


def test_build_post_sealed_segment_windows_to_the_post_sealed_span():
    bars = confirmed_rectangle_with_runway(tail_len=260)
    shifted = bars.copy()
    shifted["date"] = shifted["date"] + pd.DateOffset(years=4)  # ~2025, inside post-sealed span
    assert shifted["date"].min() >= study_run.POST_SEALED_START - pd.Timedelta(days=400)

    result = study_run.build_post_sealed_segment({"SYN1": shifted})  # must not raise
    assert result["segment"] == schema.SEGMENT_POST_SEALED


def test_build_study_builds_both_segments():
    bars_by_symbol = _universe()
    out = study_run.build_study(bars_by_symbol)
    assert set(out.keys()) == {"pre_sealed", "post_sealed"}
    assert out["pre_sealed"]["segment"] == schema.SEGMENT_PRE_SEALED
    assert out["post_sealed"]["segment"] == schema.SEGMENT_POST_SEALED
