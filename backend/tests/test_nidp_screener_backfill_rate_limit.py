"""One Screener page that trips the block-wall check must not halt a whole historical backfill."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials import backfill_screener_historical as B  # noqa: E402


class _Conn:
    pass


class _Pool:
    def acquire(self):
        class _Acq:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *_):
                return False

        return _Acq()


@pytest.fixture
def fake(monkeypatch):
    blocked: set[str] = set()
    fetched: list[str] = []

    async def fetch(symbol):
        fetched.append(symbol)
        if symbol in blocked:
            raise RuntimeError(f"Screener.in rate-limit detected for {symbol}")
        return None   # "not found" is a normal response

    async def pool():
        return _Pool()

    async def no(*_a, **_k):
        return False

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(B, "fetch_screener_quarters", fetch)
    monkeypatch.setattr(B, "get_pool", pool)
    monkeypatch.setattr(B, "_already_ingested", no)
    monkeypatch.setattr(B, "_report_failure", nothing)
    monkeypatch.setattr(B, "_write_job_log", nothing)
    monkeypatch.setattr(B, "_rate_limited", False)
    monkeypatch.setattr(B, "_blocked_streak", 0)
    return blocked, fetched


def _run(symbols):
    async def go():
        sem = asyncio.Semaphore(1)
        return [await B._process_one(4, s, "2023-09-14", sem, 0, False, False) for s in symbols]
    return [r["outcome"] for r in asyncio.run(go())]


def test_one_blocked_page_is_skipped_and_the_run_continues(fake):
    blocked, fetched = fake
    blocked.add("CMPDI")
    outcomes = _run(["CENTURYPLY", "CMPDI", "COFORGE", "CRISIL"])
    assert outcomes == ["not_found", "blocked_page", "not_found", "not_found"]
    assert fetched == ["CENTURYPLY", "CMPDI", "COFORGE", "CRISIL"]


def test_consecutive_blocked_pages_halt_the_run(fake):
    blocked, fetched = fake
    blocked.update({"A", "B", "C", "D"})
    outcomes = _run(["A", "B", "C", "D", "E"])
    assert outcomes == ["blocked_page", "blocked_page", "rate_limited", "rate_limited", "rate_limited"]
    assert fetched == ["A", "B", "C"]   # nothing fetched after the halt


def test_a_normal_response_resets_the_streak(fake):
    blocked, _ = fake
    blocked.update({"A", "B", "D", "E"})
    outcomes = _run(["A", "B", "OK1", "D", "E", "OK2"])
    assert "rate_limited" not in outcomes
