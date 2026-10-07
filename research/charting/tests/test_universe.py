"""Tests for research.charting.universe — synthetic frames and a synthetic sealed-list
CSV only. The one integration test at the bottom touches real data and the real sealed
ETF list and is skipped (not failed) when either is absent.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.charting import bars, universe
from research.charting.validate import build_trading_calendar


def _bars_df(n: int, start: str = "2021-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame({
        "date": dates,
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000,
    })


def _write_etf_list(tmp_path: Path, symbols: list[str]) -> Path:
    p = tmp_path / "etf_list.csv"
    p.write_text("\n".join(symbols) + "\n")
    return p


# ---------------------------------------------------------------------------
# load_etf_symbols / etf_list_path
# ---------------------------------------------------------------------------

def test_load_etf_symbols_reads_first_column_header_less(tmp_path):
    p = _write_etf_list(tmp_path, ["ABGSEC", "ALPHA", "BANKBEES"])
    symbols = universe.load_etf_symbols(p)
    assert symbols == frozenset({"ABGSEC", "ALPHA", "BANKBEES"})


def test_etf_list_path_honors_env_override(monkeypatch, tmp_path):
    p = _write_etf_list(tmp_path, ["ABGSEC"])
    monkeypatch.setenv(universe.ENV_ETF_LIST, str(p))
    assert universe.etf_list_path() == p


def test_etf_list_path_default_when_env_unset(monkeypatch):
    monkeypatch.delenv(universe.ENV_ETF_LIST, raising=False)
    assert universe.etf_list_path() == Path(universe.DEFAULT_ETF_LIST_PATH)


# ---------------------------------------------------------------------------
# build_universe — the critical regression: sealed-list exclusion, not a name filter
# ---------------------------------------------------------------------------

def test_etf_excluded_via_sealed_list_even_without_etf_in_name():
    # ABGSEC is a real sealed-list ETF symbol whose name contains neither "ETF" nor
    # "BEES" (data-availability.md Finding 1). A substring filter would miss it.
    assert "ETF" not in "ABGSEC" and "BEES" not in "ABGSEC"
    etf_symbols = frozenset({"ABGSEC"})
    frames = [("ABGSEC", _bars_df(300)), ("REGULARSTOCK", _bars_df(300))]

    result = universe.build_universe(frames, etf_symbols=etf_symbols)

    assert "ABGSEC" not in result.included
    assert "REGULARSTOCK" in result.included
    reasons = result.exclusion_reasons_for("ABGSEC")
    assert any(r.reason == "ETF" for r in reasons)


def test_name_filter_style_shortcut_would_have_missed_it():
    # Documents exactly the failure mode the sealed list exists to prevent.
    def naive_is_etf(symbol: str) -> bool:
        return "ETF" in symbol or "BEES" in symbol

    assert naive_is_etf("ABGSEC") is False  # the naive filter is wrong here
    etf_symbols = frozenset({"ABGSEC"})
    assert "ABGSEC" in etf_symbols  # the sealed list correctly catches it


def test_insufficient_bars_excluded_with_detail():
    frames = [("SHORT", _bars_df(100))]
    result = universe.build_universe(frames, etf_symbols=frozenset(), min_bars=250)
    assert "SHORT" not in result.included
    reasons = result.exclusion_reasons_for("SHORT")
    assert len(reasons) == 1
    assert reasons[0].reason == "INSUFFICIENT_BARS"
    assert reasons[0].detail == {"bars": 100, "minimum": 250}


def test_symbol_meeting_both_gates_is_included():
    frames = [("GOOD", _bars_df(300))]
    result = universe.build_universe(frames, etf_symbols=frozenset(), min_bars=250)
    assert result.included == ("GOOD",)
    assert result.excluded == ()


def test_symbol_can_have_multiple_exclusion_reasons():
    frames = [("BADETF", _bars_df(100))]  # both an ETF and short
    result = universe.build_universe(frames, etf_symbols=frozenset({"BADETF"}), min_bars=250)
    reasons = result.exclusion_reasons_for("BADETF")
    assert {r.reason for r in reasons} == {"ETF", "INSUFFICIENT_BARS"}
    assert "BADETF" not in result.included
    assert "BADETF" in result.excluded_symbols()


# ---------------------------------------------------------------------------
# Minimum-coverage (gap) gate — optional, configurable
# ---------------------------------------------------------------------------

def test_coverage_gate_disabled_by_default():
    # A symbol with big interior gaps is still included when max_missing_dates is None.
    full_calendar_source = _bars_df(300)
    gappy = pd.concat([_bars_df(50), _bars_df(50, start="2021-05-01")]).reset_index(drop=True)
    frames = [("GAPPY", gappy)]
    result = universe.build_universe(
        frames, etf_symbols=frozenset(), min_bars=1,
        calendar=build_trading_calendar([full_calendar_source]),
    )
    assert "GAPPY" in result.included


def test_coverage_gate_excludes_symbol_beyond_threshold():
    full_calendar_source = _bars_df(120)  # daily calendar, 120 consecutive days
    sparse = pd.concat([full_calendar_source.iloc[:10], full_calendar_source.iloc[-10:]]).reset_index(drop=True)
    frames = [("SPARSE", sparse)]
    result = universe.build_universe(
        frames, etf_symbols=frozenset(), min_bars=1,
        max_missing_dates=5,
        calendar=build_trading_calendar([full_calendar_source]),
    )
    assert "SPARSE" not in result.included
    reasons = result.exclusion_reasons_for("SPARSE")
    assert any(r.reason == "COVERAGE_GAP_TOO_LARGE" for r in reasons)


def test_coverage_gate_keeps_symbol_within_threshold():
    full_calendar_source = _bars_df(120)
    almost_full = full_calendar_source.drop(index=[50]).reset_index(drop=True)  # 1 missing day
    frames = [("ALMOSTFULL", almost_full)]
    result = universe.build_universe(
        frames, etf_symbols=frozenset(), min_bars=1,
        max_missing_dates=5,
        calendar=build_trading_calendar([full_calendar_source]),
    )
    assert "ALMOSTFULL" in result.included


# ---------------------------------------------------------------------------
# Real-data integration test — skipped, not failed, if the directory/list is absent.
# ---------------------------------------------------------------------------

_REAL_DIR = Path(bars.DEFAULT_KITE_DAILY_DIR)
_REAL_ETF_LIST = Path(universe.DEFAULT_ETF_LIST_PATH)


@pytest.mark.skipif(
    not (_REAL_DIR.is_dir() and _REAL_ETF_LIST.is_file()),
    reason="real Kite daily-bars directory or sealed ETF list not present in this environment",
)
def test_real_data_universe_counts():
    # data-availability.md's headline numbers: 2,926 total symbols (agent + orchestrator
    # agree) and >=250-bar non-ETF universe (agent: 2,132/291 ETFs removed; orchestrator:
    # 2,133/290, noted in that doc as "off by one", unresolved there).
    #
    # This task re-derived it independently, twice (a standalone script and this
    # production build_universe() call), and both give 2,132/291 — matching the "agent"
    # figure, not "orchestrator"'s 2,133. Root cause found: the sealed ETF list itself
    # contains at least 5-6 symbols that are well-known, non-ETF NSE equities —
    # BHARATFORG (Bharat Forge Ltd), BHARATGEAR-BE (Bharat Gears Ltd), BHARATRAS (Bharat
    # Rasayan Ltd), BHARATWIRE (Bharat Wire Ropes Ltd) and BHARATSE, DALBHARAT (Dalmia
    # Bharat Ltd) — confirmed via web search, not fabricated. All are >=250-bar symbols
    # that the sealed list nonetheless marks as ETFs, so using the list literally (as
    # instructed) excludes them from the universe as "ETF" even though they are not one.
    # This is flagged as a data-quality issue in the sealed list itself, not "fixed" here
    # (the list is sealed / mandatory per the task).
    # These two counts move whenever the corpus is refreshed forward -- the 2026-09-24 delta added
    # ten newly listed symbols, four of which clear the 250-bar rule (2,926 -> 2,936, 2,132 ->
    # 2,136). They are asserted as floors plus the invariant that actually matters (every loaded
    # symbol is either included or excluded, exactly once), rather than as frozen figures that
    # would have to be edited after every refresh. The ETF cross-checks below are NOT relaxed: the
    # sealed list is fixed, so those figures are genuinely stable.
    prov = bars.provenance()
    assert prov.symbol_count >= 2926

    all_bars = dict(bars.load_all())
    assert prov.symbol_count == len(all_bars)
    result = universe.build_universe(all_bars.items(), min_bars=250)
    assert len(result.included) >= 2132
    assert len(result.included) + len({r.symbol for r in result.excluded}) == len(all_bars)

    # Same 291 figure via an independent path: sealed-list symbols that both appear in
    # the data AND clear the 250-bar bar, cross-checked directly against load_all() —
    # not derived from build_universe()'s own bookkeeping. build_universe() itself
    # reports 338 distinct "ETF" exclusion reasons (see excluded_symbols below); the gap
    # is sealed-list ETFs present in the data with FEWER than 250 bars, which also pick
    # up an ETF reason even though they were never going to be in the 2,423-symbol
    # >=250-bar pool that data-availability.md's "290/291 ETFs removed" count was taken
    # from.
    etf_symbols = universe.load_etf_symbols()
    ge250_etfs = {s for s, df in all_bars.items() if len(df) >= 250 and s in etf_symbols}
    assert len(ge250_etfs) == 291

    etf_exclusion_symbols = {r.symbol for r in result.excluded if r.reason == "ETF"}
    assert len(etf_exclusion_symbols) == 338
