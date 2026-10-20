"""Optional rotating proxy for the BSE announcement fetches.

MOCK — not real data: no network. aiohttp.ClientSession is replaced by a scripted fake, and the
proxy URL below is a made-up placeholder that only stands in for a secret. What is held here:

  * the proxy is used for bseindia.com hosts, only when BSE_PROXY_URL is set, never for NSE;
  * the NSE proxy is never used for BSE (the existing guarantee, from the other side);
  * credentials in the proxy URL appear in no log line and no exception;
  * 403 is retried a bounded number of times on a fresh connection, then fails;
  * a later success wins; non-transient statuses are not retried;
  * unset = the shared-session path, untouched.
"""
from __future__ import annotations

import asyncio
import functools
import logging

import aiohttp
import pytest

import nidp.shared.sources.nse_fetcher as nf

def _sync(fn):
    """Run an async test with asyncio.run (the test image has no pytest-asyncio)."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper


SECRET_USER = "mockuser-7f3a"
SECRET_PASS = "mockpass-9c1d2e"
PROXY = f"http://{SECRET_USER}:{SECRET_PASS}@proxy.mock.invalid:8000"
BSE_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1"
HDRS = {"Origin": "https://www.bseindia.com", "Connection": "close"}


class _Resp:
    def __init__(self, status, body=b"{}"):
        self.status, self._body = status, body

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Script:
    """Scripted outcomes, one per request: an int status, (status, body), or an Exception."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []           # (url, proxy, headers)
        self.sessions = 0
        self.force_close = []

    def install(self, monkeypatch):
        script = self

        class FakeConnector:
            def __init__(self, **kw):
                script.force_close.append(kw.get("force_close"))

        class FakeSession:
            closed = False

            def __init__(self, **kw):
                script.sessions += 1

            def get(self, url, headers=None, proxy=None, **kw):
                script.calls.append((url, proxy, dict(headers or {})))
                o = script.outcomes.pop(0)
                if isinstance(o, Exception):
                    raise o
                st, body = o if isinstance(o, tuple) else (o, b"{}")
                return _Resp(st, body)

            async def close(self):
                self.closed = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        async def shared_session():          # the shared NSE session is not what BSE-via-proxy uses
            return object()

        monkeypatch.setattr(nf, "_get_session", shared_session)
        monkeypatch.setattr(nf.aiohttp, "ClientSession", FakeSession)
        monkeypatch.setattr(nf.aiohttp, "TCPConnector", FakeConnector)
        return self


@pytest.fixture
def slept(monkeypatch):
    out: list[float] = []

    async def fake_sleep(d):
        out.append(d)

    monkeypatch.setattr(nf.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(nf, "BSE_MIN_REQUEST_INTERVAL_S", 0)
    return out


@pytest.fixture
def bse_proxy(monkeypatch):
    monkeypatch.setattr(nf, "BSE_PROXY_URL", PROXY)
    monkeypatch.setattr(nf, "BSE_PROXY_ATTEMPTS", 3)


# ── routing ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
    "https://www.bseindia.com/download/x.CSV",
])
def test_bse_hosts_use_the_bse_proxy_when_set(bse_proxy, url):
    assert nf._bse_proxy_for(url) == PROXY


@pytest.mark.parametrize("url", [
    "https://www.nseindia.com/api/allIndices",
    "https://nsearchives.nseindia.com/products/content/x.csv",
    "https://www.rbi.org.in/x.pdf",
    "https://evilbseindia.com/x",          # suffix lookalike
    "https://example.com/?u=bseindia.com",  # name only in the query
])
def test_bse_proxy_is_never_used_for_other_hosts(bse_proxy, url):
    assert nf._bse_proxy_for(url) is None


def test_bse_proxy_unset_means_direct(monkeypatch):
    monkeypatch.setattr(nf, "BSE_PROXY_URL", "")
    assert nf._bse_proxy_for(BSE_URL) is None


def test_nse_proxy_is_not_used_for_bse_and_bse_proxy_is_not_used_for_nse(monkeypatch):
    monkeypatch.setattr(nf, "NSE_HTTPS_PROXY", "http://nse-proxy.mock.invalid:3128")
    monkeypatch.setattr(nf, "BSE_PROXY_URL", PROXY)
    assert nf._proxy_for(BSE_URL) is None
    assert nf._proxy_for("https://www.nseindia.com/api/x") == "http://nse-proxy.mock.invalid:3128"
    assert nf._bse_proxy_for("https://www.nseindia.com/api/x") is None
    assert nf._bse_proxy_for(BSE_URL) == PROXY


def test_shipped_default_is_unset(monkeypatch):
    import importlib
    import nidp.shared.config as cfg
    monkeypatch.delenv("BSE_PROXY_URL", raising=False)
    reloaded = importlib.reload(cfg)
    try:
        assert reloaded.BSE_PROXY_URL == ""
    finally:
        importlib.reload(cfg)


# ── behaviour with the proxy ────────────────────────────────────────────────

@_sync
async def test_request_goes_through_proxy_on_a_fresh_closing_connection(monkeypatch, bse_proxy, slept):
    s = _Script([(200, b'{"Table":[1]}')]).install(monkeypatch)
    body, status = await nf.fetch_bytes(BSE_URL, referer="https://www.bseindia.com/", extra_headers=HDRS)
    assert (body, status) == (b'{"Table":[1]}', 200)
    url, proxy, headers = s.calls[0]
    assert proxy == PROXY and headers["Connection"] == "close"
    assert s.force_close == [True]


@_sync
async def test_403_is_retried_then_fails_bounded(monkeypatch, bse_proxy, slept):
    s = _Script([403, 403, 403, 200]).install(monkeypatch)
    with pytest.raises(aiohttp.ClientError):
        await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    assert len(s.calls) == 3                      # BSE_PROXY_ATTEMPTS, not more
    assert s.sessions == 3 and s.force_close == [True] * 3   # a new connection per attempt
    assert len(slept) == 2 and all(0 < d <= 5 for d in slept)  # short backoff between tries


@_sync
async def test_retry_succeeds_on_a_later_attempt(monkeypatch, bse_proxy, slept):
    s = _Script([403, 429, (200, b"ok-body")]).install(monkeypatch)
    body, status = await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    assert (body, status) == (b"ok-body", 200)
    assert len(s.calls) == 3


@_sync
async def test_connection_error_and_5xx_are_retried(monkeypatch, bse_proxy, slept):
    s = _Script([aiohttp.ClientConnectionError("boom"), 502, 200]).install(monkeypatch)
    _, status = await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    assert status == 200 and len(s.calls) == 3


@_sync
async def test_404_is_terminal_not_retried(monkeypatch, bse_proxy, slept):
    s = _Script([404, 200]).install(monkeypatch)
    with pytest.raises(nf._TerminalHttpError):
        await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    assert len(s.calls) == 1


@_sync
async def test_a_200_with_unparseable_body_is_returned_once_not_refetched(monkeypatch, bse_proxy, slept):
    """Parse errors happen after the fetch; the fetch layer must not loop on a 200."""
    s = _Script([(200, b"<html>not json</html>"), 200]).install(monkeypatch)
    body, status = await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    assert status == 200 and body.startswith(b"<html>") and len(s.calls) == 1


@_sync
async def test_unsupported_scheme_fails_without_echoing_the_url(monkeypatch, slept):
    monkeypatch.setattr(nf, "BSE_PROXY_URL", f"socks5://{SECRET_USER}:{SECRET_PASS}@h.mock.invalid:1080")
    _Script([200]).install(monkeypatch)
    with pytest.raises(aiohttp.ClientError) as ei:
        await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    assert SECRET_PASS not in str(ei.value) and SECRET_USER not in str(ei.value)


# ── secrecy ─────────────────────────────────────────────────────────────────

@_sync
async def test_credentials_are_in_no_log_line_and_no_exception(monkeypatch, bse_proxy, slept, caplog):
    leaky = aiohttp.ClientConnectionError(
        f"cannot connect to {PROXY} as {SECRET_USER}:{SECRET_PASS}")
    _Script([leaky, 403, 403]).install(monkeypatch)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(aiohttp.ClientError) as ei:
        await nf.fetch_bytes(BSE_URL, extra_headers=HDRS)
    blob = caplog.text + str(ei.value) + repr(ei.value)
    for secret in (SECRET_USER, SECRET_PASS, PROXY, "proxy.mock.invalid:8000"):
        assert secret not in blob, f"leaked {secret!r}"
    assert "BSE" in caplog.text            # we do log the retries, just redacted


def test_redact_handles_url_user_and_password_forms():
    nf_proxy = PROXY
    import nidp.shared.sources.nse_fetcher as m
    m_BSE = m.BSE_PROXY_URL
    try:
        m.BSE_PROXY_URL = nf_proxy
        out = m._redact(f"x {PROXY} y {SECRET_USER}:{SECRET_PASS} z {SECRET_PASS}")
        assert SECRET_PASS not in out and SECRET_USER not in out
    finally:
        m.BSE_PROXY_URL = m_BSE


# ── unset = untouched ───────────────────────────────────────────────────────

@_sync
async def test_unset_uses_the_shared_session_path(monkeypatch, slept):
    monkeypatch.setattr(nf, "BSE_PROXY_URL", "")
    called = []

    async def boom(*a, **k):
        called.append(1)
        raise AssertionError("proxy path used with no proxy set")

    monkeypatch.setattr(nf, "_fetch_bse_via_proxy", boom)

    class Sess:
        closed = False

        def get(self, url, headers=None, proxy=None, **kw):
            assert proxy is None
            return _Resp(200, b"direct")

    async def get_session():
        return Sess()

    monkeypatch.setattr(nf, "_get_session", get_session)
    assert await nf.fetch_bytes(BSE_URL, extra_headers=HDRS) == (b"direct", 200)
    assert not called
