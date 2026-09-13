"""The daily results feed must retry quarters that did not land, a few symbols at a time.

In the Jun-2026 results season it wrote ~15 quarters: it only looked at events dated today,
fired every symbol at Screener.in at once, and never retried. 177 of the Nifty 500 + next 500
filed on NSE and were never ingested.
"""
import asyncio
from datetime import date

from nidp.services.nse_financials import service as svc


def test_july_announcements_are_june_quarter_results():
    assert svc._infer_period_end(date(2026, 7, 24)) == date(2026, 6, 30)   # ACC filed 24-Jul-2026
    assert svc._infer_period_end(date(2026, 8, 14)) == date(2026, 6, 30)
    assert svc._infer_period_end(date(2026, 5, 20)) == date(2026, 3, 31)
    assert svc._infer_period_end(date(2026, 6, 28)) == date(2026, 3, 31)
    assert svc._infer_period_end(date(2026, 11, 5)) == date(2026, 9, 30)
    assert svc._infer_period_end(date(2027, 2, 10)) == date(2026, 12, 31)


def test_pending_keeps_only_quarters_without_a_row():
    events = [
        {"symbol": "ACC", "event_date": date(2026, 7, 24)},
        {"symbol": "TCS", "event_date": date(2026, 7, 10)},
    ]
    got = svc.pending_results(events, {("TCS", date(2026, 6, 30))})
    assert [e["symbol"] for e in got] == ["ACC"]


def test_pending_uses_the_latest_event_per_symbol():
    events = [
        {"symbol": "ACC", "event_date": date(2026, 5, 2)},    # Mar quarter, already ingested
        {"symbol": "ACC", "event_date": date(2026, 7, 24)},   # Jun quarter, missing
    ]
    got = svc.pending_results(events, {("ACC", date(2026, 3, 31))})
    assert got == [{"symbol": "ACC", "event_date": date(2026, 7, 24)}]


def _due(n):
    return [{"symbol": f"S{i}", "event_date": date(2026, 8, 1)} for i in range(n)]


def test_symbols_are_processed_a_few_at_a_time(monkeypatch):
    live, peak = 0, 0

    async def process(symbol, *_):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return 1

    monkeypatch.setattr(svc, "_process_symbol", process)
    monkeypatch.setattr(svc, "_DELAY_S", 0)
    results = asyncio.run(svc._process_all(_due(10), date(2026, 8, 1)))
    assert results == [1] * 10
    assert peak == svc._CONCURRENCY


def test_a_screener_block_stops_the_remaining_symbols(monkeypatch):
    called = []

    async def process(symbol, *_):
        called.append(symbol)
        if symbol == "S1":
            raise RuntimeError("Screener.in rate-limit detected for S1")
        return 1

    monkeypatch.setattr(svc, "_process_symbol", process)
    monkeypatch.setattr(svc, "_DELAY_S", 0)
    monkeypatch.setattr(svc, "_CONCURRENCY", 1)
    results = asyncio.run(svc._process_all(_due(5), date(2026, 8, 1)))
    assert called == ["S0", "S1"]
    assert results[0] == 1 and isinstance(results[1], RuntimeError)
    assert results[2:] == [None, None, None]
