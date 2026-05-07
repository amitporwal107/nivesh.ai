"""Unit tests for nidp.shared.sources.nse_fetcher retry behaviour.

The contract under test:
    • Terminal 4xx (404 etc.) raises _TerminalHttpError immediately
      after the first attempt — no retries, no wasted ~30s of
      exponential backoff.
    • Retryable 5xx / 429 still loop up to HTTP_RETRY_ATTEMPTS.

The 90-day backfill regression: at 10:34 IST today's bhavcopy 404'd,
and the fetcher caught aiohttp.ClientResponseError as a generic
ClientError → 4 wasted attempts per missing date. After the fix,
each missing date fails fast on attempt 1.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Optional
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from nidp.shared.sources import nse_fetcher
from nidp.shared.sources.nse_fetcher import _TerminalHttpError, fetch_bytes


class _FakeResp:
    """Minimal stand-in for aiohttp.ClientResponse usable as an async
    context manager. Returns the configured status + body."""

    def __init__(self, status: int, body: bytes = b"<html>nope</html>"):
        self.status = status
        self._body = body
        self.request_info = None
        self.history = ()

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Tracks .get() call count so the test can assert retry behavior."""

    def __init__(self, status_sequence):
        self._statuses = list(status_sequence)
        self.calls = 0
        self.closed = False
        self.cookie_jar: list = []

    def get(self, url, headers=None):
        self.calls += 1
        # Pop next status; clamp to the last value once exhausted
        idx = min(self.calls - 1, len(self._statuses) - 1)
        return _FakeResp(self._statuses[idx])

    async def close(self):
        self.closed = True


@contextlib.asynccontextmanager
async def _patched_session(status_sequence):
    """Replace nse_fetcher's session with a fake. Also pre-mark the
    NSE host as 'primed' so we skip the cookie-prime GET path."""
    fake = _FakeSession(status_sequence)

    async def _fake_get_session():
        return fake

    with patch.object(nse_fetcher, "_get_session", _fake_get_session):
        with patch.object(nse_fetcher, "_prime_nse", AsyncMock(return_value=None)):
            with patch.object(nse_fetcher, "_force_reprime", AsyncMock(return_value=None)):
                with patch.object(nse_fetcher, "_primed", True):
                    yield fake


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if asyncio.get_event_loop_policy().get_event_loop().is_closed() is False \
        else asyncio.new_event_loop().run_until_complete(coro)


# ── Tests ──────────────────────────────────────────────────────────
def test_terminal_404_raises_immediately_no_retries():
    """The 90-day backfill regression: 404 must NOT loop 4 times."""
    async def go():
        async with _patched_session([404]) as fake:
            with pytest.raises(_TerminalHttpError) as ei:
                await fetch_bytes(
                    "https://nsearchives.nseindia.com/content/cm/missing.csv.zip"
                )
            assert ei.value.status == 404
            return fake.calls
    calls = asyncio.run(go())
    assert calls == 1, f"expected 1 attempt on terminal 404, got {calls}"


def test_terminal_400_raises_immediately():
    async def go():
        async with _patched_session([400]) as fake:
            with pytest.raises(_TerminalHttpError):
                await fetch_bytes("https://nsearchives.nseindia.com/x")
            return fake.calls
    assert asyncio.run(go()) == 1


def test_retryable_503_then_200_succeeds():
    """503 IS retryable. After (configurable) retries, a successful
    200 should still resolve to bytes."""
    async def go():
        async with _patched_session([503, 503, 200]) as fake:
            # Patch sleep to 0 so the test isn't slow
            with patch.object(nse_fetcher.asyncio, "sleep", AsyncMock(return_value=None)):
                body, status = await fetch_bytes("https://nsearchives.nseindia.com/x")
            assert status == 200
            return fake.calls
    assert asyncio.run(go()) == 3


def test_persistent_503_exhausts_retries_and_raises_clienterror():
    async def go():
        async with _patched_session([503, 503, 503, 503]) as fake:
            with patch.object(nse_fetcher.asyncio, "sleep", AsyncMock(return_value=None)):
                with pytest.raises(aiohttp.ClientError) as ei:
                    await fetch_bytes("https://nsearchives.nseindia.com/x")
            # Must NOT be a TerminalHttpError (those are non-retryable)
            assert not isinstance(ei.value, _TerminalHttpError)
            return fake.calls
    # 4 attempts (HTTP_RETRY_ATTEMPTS default)
    assert asyncio.run(go()) == 4


def test_terminal_error_is_aiohttp_clienterror_subclass():
    """Existing ingester `except aiohttp.ClientError` blocks must still
    see the terminal error so failures still flow through job_log."""
    assert issubclass(_TerminalHttpError, aiohttp.ClientError)
