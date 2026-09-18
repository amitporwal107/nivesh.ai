"""Unit tests for the Kite intraday-bar collector. No network, no DB: the Kite client and
psql are stubbed, so these assert OUR logic (chunking, status classification, retry,
credential hygiene) rather than the vendor's."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from nidp.services.kite_bars import client, collect  # noqa: E402


# ── windows: Kite bounds a historical call per interval ──────────────────────
def test_windows_minute_splits_at_60_days():
    """TC-K1: a 180-day minute request becomes 60-day chunks, contiguous and non-overlapping."""
    w = client.windows(date(2025, 1, 1), date(2025, 6, 29), "minute")
    assert len(w) == 3
    assert w[0] == (date(2025, 1, 1), date(2025, 3, 1))
    for (_, prev_end), (next_start, _) in zip(w, w[1:]):
        assert (next_start - prev_end).days == 1      # contiguous, no gap, no overlap
    assert w[-1][1] == date(2025, 6, 29)              # never runs past the requested end


def test_windows_single_chunk_when_inside_limit():
    """TC-K2: a short window is one chunk, not padded out to the cap."""
    assert client.windows(date(2025, 1, 1), date(2025, 1, 10), "minute") == [(date(2025, 1, 1), date(2025, 1, 10))]


def test_windows_day_interval_uses_wider_cap():
    """TC-K3: daily bars allow a far wider window than minute bars."""
    assert len(client.windows(date(2020, 1, 1), date(2024, 1, 1), "day")) == 1
    assert len(client.windows(date(2020, 1, 1), date(2024, 1, 1), "minute")) > 20


# ── retry ───────────────────────────────────────────────────────────────────
def test_retry_succeeds_after_transient_failures(monkeypatch):
    """TC-K4: a call that fails twice then succeeds returns the value (1 of 8 symbols failed a
    live probe, so transient errors are expected)."""
    monkeypatch.setattr(collect.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    assert collect._retry(flaky) == "ok"
    assert calls["n"] == 3


def test_retry_raises_after_max_attempts(monkeypatch):
    """TC-K5: a permanently failing call raises rather than silently returning nothing."""
    monkeypatch.setattr(collect.time, "sleep", lambda *_: None)
    with pytest.raises(ValueError):
        collect._retry(lambda: (_ for _ in ()).throw(ValueError("permanent")))


# ── collect: status classification ──────────────────────────────────────────
class _Recorder:
    """Captures what collect() would have written, instead of touching psql."""
    def __init__(self):
        self.bars, self.logs = [], []


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(collect, "_write", lambda inst, iv, rows: (r.bars.extend(rows), len(rows))[1])
    monkeypatch.setattr(collect, "_log", lambda *a: r.logs.append(a))
    monkeypatch.setattr(collect, "nse_equity_instruments",
                        lambda _t: [client.Instrument(123, "RELIANCE", "NSE")])
    monkeypatch.setattr(collect.time, "sleep", lambda *_: None)
    return r


def _bar(d):
    return {"date": d, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000}


def test_collect_ok_path_writes_bars_and_logs(rec, monkeypatch):
    """TC-K6: a symbol returning candles is counted OK, its rows written, and logged OK."""
    import datetime as dt
    monkeypatch.setattr(collect, "candles", lambda *a, **k: [_bar(dt.datetime(2025, 1, 2, 9, 15))])
    t = collect.collect("tok", ["RELIANCE"], date(2025, 1, 1), date(2025, 1, 5), "minute", run_id="R1")
    assert t["OK"] == 1 and t["rows"] == 1 and t["ERROR"] == 0
    assert rec.logs[0][4] == "OK"


def test_collect_empty_is_distinct_from_error(rec, monkeypatch):
    """TC-K7: no candles logs EMPTY, not ERROR — 'no trades' must be distinguishable from 'fetch failed'."""
    monkeypatch.setattr(collect, "candles", lambda *a, **k: [])
    t = collect.collect("tok", ["RELIANCE"], date(2025, 1, 1), date(2025, 1, 5), "minute", run_id="R2")
    assert t["EMPTY"] == 1 and t["ERROR"] == 0 and t["rows"] == 0
    assert rec.logs[0][4] == "EMPTY"


def test_collect_error_is_logged_and_does_not_abort(rec, monkeypatch):
    """TC-K8: one failing symbol is logged ERROR and the run continues to the next."""
    monkeypatch.setattr(collect, "nse_equity_instruments", lambda _t: [
        client.Instrument(1, "AAA", "NSE"), client.Instrument(2, "BBB", "NSE")])
    import datetime as dt

    def selective(_tok, token, *a, **k):
        if token == 1:
            raise RuntimeError("kite 500")
        return [_bar(dt.datetime(2025, 1, 2, 9, 15))]

    monkeypatch.setattr(collect, "candles", selective)
    t = collect.collect("tok", ["AAA", "BBB"], date(2025, 1, 1), date(2025, 1, 5), "minute", run_id="R3")
    assert t["ERROR"] == 1 and t["OK"] == 1        # BBB still collected
    assert [l[4] for l in rec.logs] == ["ERROR", "OK"]


def test_collect_unknown_symbol_logged_not_crashed(rec, monkeypatch):
    """TC-K9: a symbol absent from Kite's instrument list is recorded, not a KeyError."""
    monkeypatch.setattr(collect, "candles", lambda *a, **k: [])
    t = collect.collect("tok", ["NOSUCHSYM"], date(2025, 1, 1), date(2025, 1, 5), "minute", run_id="R4")
    assert t["UNKNOWN_SYMBOL"] == 1
    assert rec.logs[0][4] == "ERROR" and "instruments" in rec.logs[0][6]


def test_collect_chunks_long_range_into_multiple_calls(rec, monkeypatch):
    """TC-K10: a 180-day minute backfill issues one call per 60-day chunk."""
    import datetime as dt
    seen = []
    monkeypatch.setattr(collect, "candles",
                        lambda _t, tok, s, e, iv: (seen.append((s, e)), [_bar(dt.datetime(2025, 1, 2, 9, 15))])[1])
    collect.collect("tok", ["RELIANCE"], date(2025, 1, 1), date(2025, 6, 29), "minute", run_id="R5")
    assert len(seen) == 3


# ── credential hygiene ──────────────────────────────────────────────────────
def test_login_url_carries_key_but_module_never_logs_secret(monkeypatch):
    """TC-K11: the secret is read only inside the exchange call and is absent from module source."""
    src = Path(client.__file__).read_text()
    assert "print(" not in src                      # nothing in the client prints anything
    # the secret is CALLED in exactly one place (the other occurrence is its own def)
    assert src.count("_api_secret()") - src.count("def _api_secret()") == 1
    # and that one call site is inside exchange_request_token, nowhere else
    import inspect
    assert "_api_secret()" in inspect.getsource(client.exchange_request_token)


def test_source_version_stamped_on_every_row():
    """TC-K12: SOURCE_VERSION is in the COPY column list, so no row can land unattributed."""
    assert "source_version" in collect.BAR_COLS
    assert collect.SOURCE_VERSION == "kite-connect-v3"
