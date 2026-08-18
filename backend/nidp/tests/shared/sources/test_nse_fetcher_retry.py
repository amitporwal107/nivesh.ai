"""Regression tests for the NSE fetcher's 401/403 handling.

Background:
    NSE fronts every host with Akamai, which 403s an egress IP whose
    reputation has dipped. That block is transient — the same VM that
    403s at 06:30 often succeeds at 19:00. The original loop retried a
    403 exactly once, immediately (no backoff), and only on attempt 0;
    every later 403 fell through to `_TerminalHttpError`. That turned a
    recoverable edge block into a hard feed failure and left holes in
    fii_dii / bhavcopy / delivery / nse_shareholding.

These tests pin the fixed behaviour.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nidp.shared.config import HTTP_RETRY_ATTEMPTS
from nidp.shared.sources import nse_fetcher


class _FakeResp:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeJar:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1

    def __len__(self) -> int:
        return 3


class _FakeSession:
    """Serves `statuses` in order for the *target* URL, then 200 forever.

    The cookie re-prime fetches NSE's home page through the same session,
    so those requests are tracked separately (`primes`) and always answer
    200 — otherwise they would consume the scripted status queue.
    """

    def __init__(self, statuses: list[int]) -> None:
        self.statuses = list(statuses)
        self.requested: list[str] = []   # target-URL fetches only
        self.primes: list[str] = []      # cookie-prime fetches
        self.cookie_jar = _FakeJar()
        self.closed = False

    def get(self, url: str, **kw):
        if url.rstrip("/") == nse_fetcher.NSE_WWW.rstrip("/"):
            self.primes.append(url)
            return _FakeResp(200, b"<html>home</html>")
        self.requested.append(url)
        status = self.statuses.pop(0) if self.statuses else 200
        return _FakeResp(status, b"OK" if status == 200 else b"<H1>Access Denied</H1>")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Keep the backoff logic exercised but instant."""
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(nse_fetcher.asyncio, "sleep", fake_sleep)
    return slept


def _install(monkeypatch, session):
    async def _get_session():
        return session

    monkeypatch.setattr(nse_fetcher, "_get_session", _get_session)
    monkeypatch.setattr(nse_fetcher, "_primed", True, raising=False)


URL = "https://www.nseindia.com/api/fiidiiTradeReact"


def test_403_recovers_after_several_attempts(monkeypatch, _no_sleep):
    """Three 403s then a 200 must return the body, not raise.

    The old code raised _TerminalHttpError on the second 403.
    """
    session = _FakeSession([403, 403, 403])
    _install(monkeypatch, session)

    body, status = asyncio.run(nse_fetcher.fetch_bytes(URL))

    assert status == 200
    assert body == b"OK"
    assert len(session.requested) == 4   # 3 blocked + 1 that got through


def test_403_backs_off_between_attempts(monkeypatch, _no_sleep):
    """A 403 must sleep before retrying — an instant retry re-trips Akamai."""
    session = _FakeSession([403, 403])
    _install(monkeypatch, session)

    asyncio.run(nse_fetcher.fetch_bytes(URL))

    assert _no_sleep, "403 retry slept 0 times; backoff was skipped"
    assert _no_sleep == sorted(_no_sleep), "backoff must be non-decreasing"


def test_403_clears_cookie_jar_before_repriming(monkeypatch, _no_sleep):
    """Akamai flags the existing _abck/bm_sv pair; re-priming must drop it."""
    session = _FakeSession([403])
    _install(monkeypatch, session)

    asyncio.run(nse_fetcher.fetch_bytes(URL))

    assert session.cookie_jar.clear_calls >= 1, "cookie jar was not cleared on re-prime"
    assert session.primes, "re-prime never re-fetched the NSE home page"


def test_403_is_bounded_and_still_fails_loudly(monkeypatch, _no_sleep):
    """Retrying is bounded — a persistent block must still raise, not hang."""
    session = _FakeSession([403] * (HTTP_RETRY_ATTEMPTS + 5))
    _install(monkeypatch, session)

    with pytest.raises(Exception) as ei:
        asyncio.run(nse_fetcher.fetch_bytes(URL))

    assert len(session.requested) == HTTP_RETRY_ATTEMPTS
    assert "403" in str(ei.value)


def test_404_is_still_terminal(monkeypatch, _no_sleep):
    """A genuinely terminal 4xx (bhavcopy not published yet) must NOT retry."""
    session = _FakeSession([404])
    _install(monkeypatch, session)

    with pytest.raises(nse_fetcher._TerminalHttpError) as ei:
        asyncio.run(nse_fetcher.fetch_bytes(URL))

    assert ei.value.status == 404
    assert len(session.requested) == 1, "404 must not be retried"


def test_non_nse_403_is_still_terminal(monkeypatch, _no_sleep):
    """The lenient path is NSE-only; other hosts keep fail-fast semantics."""
    session = _FakeSession([403])
    _install(monkeypatch, session)

    with pytest.raises(nse_fetcher._TerminalHttpError):
        asyncio.run(nse_fetcher.fetch_bytes("https://example.org/thing.csv"))

    assert len(session.requested) == 1
