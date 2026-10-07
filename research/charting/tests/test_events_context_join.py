"""events/context_join.py: CHARTING_PREREGISTRATION_V1 §6 "Context at t" -- a `context` block
(`regime.features_at`) and a `research` block (`enrich.enrich_pattern`) attached to an event
row, both evaluated at the row's own signal date. Point-in-time is the whole point of this
module (it hands `regime.py`/`enrich.py` the FULL bars frame rather than pre-truncating), so
this file's poisoned-future-probe + peeking-control tests are the load-bearing ones --
everything else is shape/wiring."""
from __future__ import annotations

import gc
import math

import pandas as pd
import pytest

from research.charting.events import context_join, controls, extraction
from research.charting.tests import synth
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

_BREADTH_COLUMNS = (
    "advancers", "decliners", "unchanged", "advance_decline_ratio",
    "pct_above_sma50", "pct_above_sma200", "new_52w_highs", "new_52w_lows", "names_contributing",
)


def _bench(bars: pd.DataFrame, *, extra_bars: int = 40, slope: float = 0.4) -> pd.DataFrame:
    """A synthetic NIFTY 500-shaped bullish benchmark spanning (and a bit past) `bars`' own
    date range -- same convention `test_regime_market.py` already uses for `regime.py`
    (synthetic benchmark, not the real committed index CSV, so this file's assertions do not
    depend on real-data date coverage)."""
    n = len(bars) + extra_bars
    closes = [100.0 + slope * i for i in range(n)]
    return synth.bars_from_closes(closes, start_date=str(bars["date"].iloc[0].date()), wick=0.2)


def _vix(bars: pd.DataFrame, *, extra_bars: int = 40) -> pd.DataFrame:
    n = len(bars) + extra_bars
    closes = [14.0 + 0.01 * (i % 30) for i in range(n)]
    df = synth.bars_from_closes(closes, start_date=str(bars["date"].iloc[0].date()), wick=0.05)
    df["source"] = "SYNTHETIC"  # context.market_value_at requires a `source` column
    return df


def _breadth(bars: pd.DataFrame, *, extra_bars: int = 40) -> pd.DataFrame:
    n = len(bars) + extra_bars
    dates = pd.bdate_range(start=bars["date"].iloc[0], periods=n)
    rows = []
    for i, d in enumerate(dates):
        rows.append((d, 900 + i, 500 - (i % 5), 50, 1.5, 55.0, 60.0, 10, 5, 1450))
    return pd.DataFrame(rows, columns=("date", *_BREADTH_COLUMNS))


def _event_row_and_bars(tail_len: int = 40):
    bars = confirmed_rectangle_with_runway(tail_len=tail_len)
    events = extraction.extract_events(bars, "SYN1")
    assert len(events) == 1
    return events[0], bars


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


# ── Shape: context + research on a real pattern event row ───────────────────────────────


def test_attach_to_event_row_pattern_event_has_context_and_research():
    row, bars = _event_row_and_bars()
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)
    pattern_dict = context_join.pattern_dict_for_event(bars, row)
    assert pattern_dict is not None
    assert pattern_dict["pattern_id"] == row["pattern_id"]
    assert pattern_dict["status"] == "PRICE_CONFIRMED"

    enriched = context_join.attach_to_event_row(row, bars, pattern_dict, benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)

    assert set(enriched.keys()) == set(row.keys()) | {"context", "research"}
    ctx = enriched["context"]
    for key in ("rs_5", "rs_20", "rs_50", "rs_100", "trend_close", "trend_sma_20",
                "regime_regime", "trend_class_class", "market_trend_class_class",
                "india_vix_close", "breadth_advancers"):
        assert key in ctx, key
    assert ctx["symbol"] == row["symbol"]

    research = enriched["research"]
    assert research["pattern_id"] == row["pattern_id"]
    assert research["as_of_date"] == row["signal_date"]
    assert "research_state" in research
    assert "stock_trend_class_class" in research
    assert "market_trend_class_class" in research
    assert research["breakout_level"] is not None  # this fixture's own confirming bar broke a level


def test_attach_to_event_row_never_mutates_row_bars_or_pattern_dict():
    row, bars = _event_row_and_bars()
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)
    pattern_dict = context_join.pattern_dict_for_event(bars, row)

    row_before = {**row}
    bars_before = bars.copy()
    pattern_dict_before = dict(pattern_dict)

    context_join.attach_to_event_row(row, bars, pattern_dict, benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)

    assert row == row_before
    pd.testing.assert_frame_equal(bars, bars_before)
    assert pattern_dict == pattern_dict_before


# ── A control row has context but never a research block ────────────────────────────────


def test_attach_to_event_row_control_row_has_context_but_no_research():
    row, bars = _event_row_and_bars()
    eligible = [("SYN1", i) for i in range(20, 35)]
    control = controls.random_control_rows({"SYN1": bars}, eligible, n=1, seed=1)[0]
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)

    enriched = context_join.attach_to_event_row(control, bars, None, benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    assert enriched["research"] is None
    assert enriched["context"] is not None
    assert enriched["context"]["symbol"] == "SYN1"


def test_attach_to_control_rows_batch_wires_research_none_for_every_row():
    row, bars = _event_row_and_bars()
    eligible = [("SYN1", i) for i in range(20, 35)]
    control_rows = controls.random_control_rows({"SYN1": bars}, eligible, n=3, seed=1)
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)

    enriched = context_join.attach_to_control_rows(control_rows, {"SYN1": bars}, benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    assert len(enriched) == len(control_rows)
    assert all(r["research"] is None for r in enriched)
    assert all(r["context"] is not None for r in enriched)


def test_attach_to_event_rows_for_symbol_attaches_research_for_every_real_event():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    events = extraction.extract_events(bars, "SYN1")
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)

    enriched = context_join.attach_to_event_rows_for_symbol(events, bars, benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    assert len(enriched) == len(events)
    for ev, en in zip(events, enriched):
        assert en["research"]["pattern_id"] == ev["pattern_id"]


# ── pattern_dict_for_event: recovery matches the row it came from ───────────────────────


def test_pattern_dict_for_event_returns_none_for_a_nonexistent_pattern_id():
    row, bars = _event_row_and_bars()
    fake_row = {**row, "pattern_id": "SYN1:RECTANGLE:not-a-real-id"}
    assert context_join.pattern_dict_for_event(bars, fake_row) is None


# ── Point-in-time: poisoned-future probe + peeking control ──────────────────────────────


def test_context_join_poisoned_future_probe_stock_leg():
    """Multiplying every STOCK bar strictly AFTER the confirmation bar must not move a single
    OK context or research field computed at the confirmation bar's own signal_date."""
    row, bars = _event_row_and_bars(tail_len=40)
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)
    pattern_dict = context_join.pattern_dict_for_event(bars, row)

    t_idx = row["confirmation_bar_index"]
    poisoned = bars.copy()
    future_mask = poisoned.index > t_idx
    assert future_mask.sum() > 0  # sanity: there really is a poisonable future
    for c in ("open", "high", "low", "close"):
        poisoned.loc[future_mask, c] = poisoned.loc[future_mask, c] * 1000.0

    clean_ctx = context_join.context_block_at(bars, row["signal_date"], symbol="SYN1", benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    dirty_ctx = context_join.context_block_at(poisoned, row["signal_date"], symbol="SYN1", benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    moved = [k for k in clean_ctx if not _same(clean_ctx[k], dirty_ctx[k])]
    assert moved == []

    clean_research = context_join.research_block_for(pattern_dict, bars, row["signal_date"], benchmark_df=benchmark)
    dirty_research = context_join.research_block_for(pattern_dict, poisoned, row["signal_date"], benchmark_df=benchmark)
    moved_r = [k for k in clean_research if not _same(clean_research[k], dirty_research[k])]
    assert moved_r == []


def test_context_join_poisoned_future_probe_benchmark_leg():
    """Same probe, applied to the NIFTY 500 benchmark's own future bars -- the RS/regime/
    market-trend-class legs read from `benchmark_df`, not just from the stock's own bars."""
    row, bars = _event_row_and_bars(tail_len=40)
    benchmark = _bench(bars)
    vix, breadth = _vix(bars), _breadth(bars)

    t = pd.Timestamp(row["signal_date"])
    poisoned_bench = benchmark.copy()
    future_mask = poisoned_bench["date"] > t
    assert future_mask.sum() > 0
    for c in ("open", "high", "low", "close"):
        poisoned_bench.loc[future_mask, c] = poisoned_bench.loc[future_mask, c] * 1000.0

    clean_ctx = context_join.context_block_at(bars, row["signal_date"], symbol="SYN1", benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    dirty_ctx = context_join.context_block_at(bars, row["signal_date"], symbol="SYN1", benchmark_df=poisoned_bench, vix_df=vix, breadth_df=breadth)
    moved = [k for k in clean_ctx if not _same(clean_ctx[k], dirty_ctx[k])]
    assert moved == []


def test_negative_control_poisoning_the_stock_leg_does_move_a_naive_whole_frame_computation():
    """Proves the poison in the two probes above is real (not a no-op fixture): a naive
    whole-frame indicator (no point-in-time windowing at all) computed over the SAME poisoned
    frame at the SAME position visibly changes -- so the "moved == []" assertions above are
    actually testing something, not vacuously true."""
    from research.charting import series

    row, bars = _event_row_and_bars(tail_len=40)
    t_idx = row["confirmation_bar_index"]
    poisoned = bars.copy()
    future_mask = poisoned.index > t_idx
    for c in ("open", "high", "low", "close"):
        poisoned.loc[future_mask, c] = poisoned.loc[future_mask, c] * 1000.0

    # A forward-looking (non-PIT) SMA centered/trailing computation over the WHOLE poisoned
    # frame, read back at t_idx, is unaffected by poisoning bars AFTER t_idx only if the
    # indicator itself never looks ahead -- SMA doesn't either. Use `.max()` over the whole
    # column instead, which trivially "looks ahead" by construction, to prove the poison
    # exists and is large enough to matter.
    assert poisoned["close"].max() > bars["close"].max() * 100


def test_context_join_peeking_control_a_later_date_genuinely_differs():
    """Proves `context_block_at` is actually sensitive to `t` at all (so the poisoned-future
    equality checks above are meaningful, not just "nothing here ever changes"): evaluating
    the SAME clean frame at a later date inside its own runway gives a different RS_5."""
    row, bars = _event_row_and_bars(tail_len=40)
    benchmark, vix, breadth = _bench(bars), _vix(bars), _breadth(bars)
    t0 = row["signal_date"]
    t_idx = row["confirmation_bar_index"]
    later_date = bars["date"].iloc[t_idx + 20].date().isoformat()

    ctx_t0 = context_join.context_block_at(bars, t0, symbol="SYN1", benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    ctx_later = context_join.context_block_at(bars, later_date, symbol="SYN1", benchmark_df=benchmark, vix_df=vix, breadth_df=breadth)
    assert not _same(ctx_t0["trend_close"], ctx_later["trend_close"])


# ── the join must not accumulate — the failure 1,441 correctness tests never caught ─────────────
#
# Every other test in this package checks that the OUTPUT is right. None checked that memory stays
# BOUNDED, which is the only thing that has ever actually broken: the join built the whole enriched
# set before returning, so originals and replacements coexisted (25.5 GB + 27.9 GB at 133,743 rows)
# and the run was OOM-killed on a 62 GB host. A green suite told us nothing about that.


def _join_universe(n=5):
    from research.charting.events import extraction
    from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

    base = confirmed_rectangle_with_runway(tail_len=40)
    bars_by_symbol, rows_by_symbol = {}, {}
    for i in range(n):
        scaled = base.copy()
        for c in ("open", "high", "low", "close"):
            scaled[c] = scaled[c] * (1.0 + 0.05 * i)
        sym = f"SYM{i:02d}"
        bars_by_symbol[sym] = scaled
        rows = extraction.extract_events(scaled, sym)
        if rows:
            rows_by_symbol[sym] = rows
    assert len(rows_by_symbol) > 1, "need >1 symbol or 'accumulates nothing' is trivially true"
    return bars_by_symbol, rows_by_symbol


@pytest.mark.parametrize("workers", [1, 2])
def test_the_streaming_join_retains_nothing(workers):
    """The structural assertion: with `on_symbol`, the returned dict must be EMPTY and every symbol
    must still have been delivered exactly once. If this ever returns a populated dict again, the
    parent is holding the enriched set and the 62 GB host is back in play."""
    bars_by_symbol, rows_by_symbol = _join_universe()
    expected_syms = set(rows_by_symbol)

    seen: list = []
    returned = context_join.attach_to_event_rows_by_symbol(
        dict(rows_by_symbol), bars_by_symbol, max_workers=workers, consume=True,
        on_symbol=lambda s, r: seen.append((s, r)),
    )

    assert returned == {}, "the join retained rows despite a sink — this is the OOM"
    assert {s for s, _ in seen} == expected_syms
    assert len(seen) == len(expected_syms), "a symbol was delivered twice"


@pytest.mark.parametrize("workers", [1, 2])
def test_the_join_holds_no_reference_to_what_it_streamed(workers):
    """Delivery alone is not enough. If the join kept its own reference, the rows would stay alive
    after the caller let go and memory would still grow with the dataset — which is precisely the
    bug: `results[symbol] = enriched` delivered nothing but retained everything.

    `gc.get_referrers` is the direct question ("who is still holding this?"), rather than a proxy
    like a size check, which would pass on an object the join was still pinning.
    """
    bars_by_symbol, rows_by_symbol = _join_universe()

    held: dict = {}

    def sink(symbol, rows):
        held.setdefault("first", rows)        # one strong ref, ours and traceable

    context_join.attach_to_event_rows_by_symbol(
        dict(rows_by_symbol), bars_by_symbol, max_workers=workers, consume=True, on_symbol=sink,
    )
    gc.collect()

    referrers = [r for r in gc.get_referrers(held["first"]) if r is not held]
    assert not referrers, (
        f"{len(referrers)} object(s) still reference a streamed symbol's rows — the join is "
        f"retaining them: {[type(r).__name__ for r in referrers[:3]]}")


def test_a_retaining_join_would_fail_this_gate():
    """The gate has to be able to FAIL, or it is decoration. The batch path deliberately retains
    (that is its contract), so it must trip exactly the check above."""
    bars_by_symbol, rows_by_symbol = _join_universe()

    batch = context_join.attach_to_event_rows_by_symbol(
        dict(rows_by_symbol), bars_by_symbol, max_workers=2)
    gc.collect()
    sample = next(iter(batch.values()))

    referrers = [r for r in gc.get_referrers(sample) if r is not batch]
    assert batch is not None
    assert any(r is batch for r in gc.get_referrers(sample)), (
        "the batch path did not retain — then the streaming gate proves nothing by contrast")


def test_streaming_and_non_streaming_produce_the_same_rows():
    """Bounded memory is worthless if it changes the answer. Completion order differs from sorted
    order, so this compares per symbol, which is the contract the caller relies on."""
    bars_by_symbol, rows_by_symbol = _join_universe()

    batch = context_join.attach_to_event_rows_by_symbol(
        dict(rows_by_symbol), bars_by_symbol, max_workers=2)
    streamed: dict = {}
    context_join.attach_to_event_rows_by_symbol(
        dict(rows_by_symbol), bars_by_symbol, max_workers=2,
        on_symbol=lambda s, r: streamed.__setitem__(s, r))

    assert set(streamed) == set(batch)
    for symbol in batch:
        assert streamed[symbol] == batch[symbol], symbol
    assert any(batch.values()), "no enriched rows — vacuous"


def test_the_consumed_originals_are_dropped_as_the_join_proceeds():
    """`consume=True` is what lets the ORIGINALS drain while the join runs. If it stopped popping,
    peak would be originals + everything already streamed."""
    bars_by_symbol, rows_by_symbol = _join_universe()
    source = dict(rows_by_symbol)

    context_join.attach_to_event_rows_by_symbol(
        source, bars_by_symbol, max_workers=2, consume=True, on_symbol=lambda s, r: None)
    assert source == {}, "consume=True left the originals in place"

    keep = dict(rows_by_symbol)
    context_join.attach_to_event_rows_by_symbol(
        keep, bars_by_symbol, max_workers=2, consume=False, on_symbol=lambda s, r: None)
    assert set(keep) == set(rows_by_symbol), "consume=False must not mutate the caller's dict"
