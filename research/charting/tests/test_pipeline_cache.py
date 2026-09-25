"""Per-symbol extraction cache — the snapshot that makes a long run survive interruption.

Before this, extraction persisted nothing until a whole segment finished (~3 h at full universe),
so a reboot or an OOM kill threw all of it away. That happened three times on 2026-09-24/25.

The cache is only worth having if a resumed run produces EXACTLY what an uninterrupted one would,
so that is what these assert — row for row, in order, because `writer._dump_jsonl` preserves row
order and the §8 kill switch compares the resulting bytes.
"""
from __future__ import annotations

import gzip

import pytest

from research.charting.events import pipeline
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway


def _universe(n=6):
    base = confirmed_rectangle_with_runway(tail_len=40)   # already starts 2021 = pre-sealed
    out = {}
    for i in range(n):
        b = base.copy()
        f = 1.0 + 0.05 * i
        for c in ("open", "high", "low", "close"):
            b[c] = b[c] * f
        out[f"SYM{i:02d}"] = b
    return out


@pytest.mark.parametrize("workers", (1, 3))
def test_the_cached_path_produces_identical_rows_to_the_uncached_one(tmp_path, workers):
    """Same rows, same order. If this drifts, the cache changes the dataset."""
    bbs = _universe()
    plain = pipeline.build_event_dataset(bbs, segment="pre_sealed", max_workers=workers)
    cached = pipeline.build_event_dataset(bbs, segment="pre_sealed", max_workers=workers,
                                          cache_dir=tmp_path / f"c{workers}")
    assert plain["rows"], "no events — this comparison would be vacuous"
    assert len(cached["rows"]) == len(plain["rows"])
    assert cached["rows"] == plain["rows"]


def test_a_resumed_run_reuses_the_cache_and_re_extracts_only_the_rest(tmp_path, monkeypatch):
    """The realistic case: the run died partway. Only the missing symbols may be recomputed."""
    bbs = _universe()
    cache = tmp_path / "c"
    full = pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1)

    # drop two symbols' cache entries, as if the run died before reaching them
    files = sorted(cache.glob("*.pkl.gz"))
    assert len(files) == len(bbs)
    for f in files[:2]:
        f.unlink()

    extracted = []
    real = pipeline.extraction.extract_events

    def counting(bars, symbol, **kw):
        extracted.append(symbol)
        return real(bars, symbol, **kw)

    monkeypatch.setattr(pipeline.extraction, "extract_events", counting)
    resumed = pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1)

    assert len(extracted) == 2, f"re-extracted {len(extracted)} symbols, expected exactly the 2 missing"
    assert resumed["rows"] == full["rows"], "a resumed run produced different rows"


def test_nothing_is_re_extracted_when_the_cache_is_complete(tmp_path, monkeypatch):
    bbs = _universe()
    cache = tmp_path / "c"
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1)

    called = []
    monkeypatch.setattr(pipeline.extraction, "extract_events",
                        lambda *a, **k: called.append(1) or [])
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1)
    assert called == [], "a complete cache still re-extracted"


def test_a_cache_from_a_different_segment_is_not_reused():
    """Pre-sealed and post-sealed rows must never be mixed. Asserted on the key itself rather than
    by running post_sealed over pre_sealed bars, which correctly raises SealedWindowError."""
    from research.charting.config import CONFIG
    assert (pipeline._cache_key("RELIANCE", "pre_sealed", CONFIG)
            != pipeline._cache_key("RELIANCE", "post_sealed", CONFIG))


def test_a_cache_from_a_different_config_is_not_reused(tmp_path):
    """Reusing rows across a config change would silently mix two engines' output."""
    from research.charting.config import CONFIG
    bbs = _universe()
    cache = tmp_path / "c"
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1)
    before = len(list(cache.glob("*.pkl.gz")))

    other = dict(CONFIG)
    other["atr_period"] = CONFIG["atr_period"] + 1
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1, cfg=other)
    assert len(list(cache.glob("*.pkl.gz"))) > before, "the config hash is not part of the key"


def test_a_half_written_cache_entry_is_never_read(tmp_path):
    """Written to a temp name and renamed, so an interrupted write cannot be resumed from."""
    bbs = _universe(2)
    cache = tmp_path / "c"
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1)
    assert not list(cache.glob("*.tmp")), "a temp file was left behind"
    for f in cache.glob("*.pkl.gz"):
        gzip.decompress(f.read_bytes())    # every entry is a complete gzip stream


def test_progress_is_reported_including_what_was_resumed(tmp_path):
    """The run's status file needs to show extraction moving — that was the gap that made a 3 h
    stage look frozen."""
    bbs = _universe()
    cache = tmp_path / "c"
    seen = []
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1,
                                 progress=lambda d, n, u="": seen.append((d, n)))
    assert seen and seen[-1] == (len(bbs), len(bbs))

    seen2 = []
    pipeline.build_event_dataset(bbs, segment="pre_sealed", cache_dir=cache, max_workers=1,
                                 progress=lambda d, n, u="": seen2.append((d, n, u)))
    assert seen2[0] == (len(bbs), len(bbs), "symbols (resumed)"), "a fully resumed run must say so"
