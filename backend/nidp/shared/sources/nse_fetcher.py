"""Shared NSE HTTP fetcher with cookie session pooling.

Why this exists:
    NSE's archive hosts (archives.nseindia.com, nsearchives.nseindia.com,
    www.nseindia.com) silently 403 / 401 / hang on requests that look
    like bots — i.e. anything missing a real browser User-Agent, the
    `nseappid` cookie, or a same-origin Referer. Every NSE-consuming
    service in the existing codebase re-debugs this dance separately;
    NIDP centralises it once.

What it does:
    1. Maintains a singleton aiohttp.ClientSession with a populated
       cookie jar. The session is "primed" by visiting nseindia.com
       once per process — that GET sets `bm_sv`, `nseappid`, and any
       Akamai bot-mgmt cookies.
    2. All subsequent fetches reuse the cookie jar + supply a
       sensible Referer (NSE archives reject requests with bogus
       referrers).
    3. Exponential-backoff retry on 429 / 5xx / connection errors.
    4. Returns raw bytes so callers can hash + archive before parsing.

Public API:
    await fetch_bytes(url, *, referer=None) -> tuple[bytes, int]
    await fetch_text(url, *, referer=None)  -> tuple[str, int]
    await close()

Notes:
    - This module does not import from existing backend services.
    - aiohttp is already a dependency (see groww_stock_scraper).
    - We intentionally avoid mounting a global retry adapter because
      we want per-call retry decisions (some endpoints — e.g. holiday
      master — should fail fast on 4xx).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

import aiohttp

from nidp.shared.config import (
    DEFAULT_UA,
    HTTP_RETRY_ATTEMPTS,
    HTTP_RETRY_BACKOFF_S,
    HTTP_TIMEOUT_S,
    NSE_WWW,
)

logger = logging.getLogger(__name__)

_session: Optional[aiohttp.ClientSession] = None
_session_lock = asyncio.Lock()
_primed = False

# Hosts that need the cookie-prime dance.
_NSE_HOSTS = (
    "nseindia.com",
    "www.nseindia.com",
    "archives.nseindia.com",
    "nsearchives.nseindia.com",
)


def _is_nse_host(url: str) -> bool:
    return any(host in url for host in _NSE_HOSTS)


async def _get_session() -> aiohttp.ClientSession:
    """Lazily build a single shared session."""
    global _session
    if _session is None or _session.closed:
        async with _session_lock:
            if _session is None or _session.closed:
                jar = aiohttp.CookieJar(unsafe=True)
                connector = aiohttp.TCPConnector(
                    limit=20,
                    ttl_dns_cache=600,
                )
                _session = aiohttp.ClientSession(
                    cookie_jar=jar,
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                    headers={
                        "User-Agent": DEFAULT_UA,
                        "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                    },
                )
    return _session


async def _prime_nse() -> None:
    """One-time cookie prime: GET nseindia.com home to populate
    `nseappid`, `bm_sv`, and Akamai bot-mgmt cookies before any
    archive fetch. Idempotent — second call is a no-op.

    NSE rotates these cookies daily. We re-prime if a request returns
    401/403 (handled in fetch_bytes).
    """
    global _primed
    if _primed:
        return
    session = await _get_session()
    try:
        async with session.get(NSE_WWW + "/", allow_redirects=True) as resp:
            await resp.read()
            logger.info(
                "NSE session primed: %s, %d cookies",
                resp.status,
                len(session.cookie_jar),
            )
            _primed = True
    except Exception as e:  # noqa: BLE001
        logger.warning("NSE prime failed (continuing without cookies): %s", e)


async def _force_reprime() -> None:
    global _primed
    _primed = False
    await _prime_nse()


async def fetch_bytes(
    url: str,
    *,
    referer: Optional[str] = None,
    extra_headers: Optional[dict] = None,
) -> Tuple[bytes, int]:
    """Fetch raw bytes with retry and (for NSE hosts) cookie-prime.

    Returns: (body, http_status). Raises aiohttp.ClientError on
    terminal failure after all retries.
    """
    if _is_nse_host(url):
        await _prime_nse()

    session = await _get_session()
    headers: dict = {}
    if referer:
        headers["Referer"] = referer
    elif _is_nse_host(url):
        # Default referer = NSE home; archives reject blank/foreign refs.
        headers["Referer"] = NSE_WWW + "/"
    if extra_headers:
        headers.update(extra_headers)

    last_status = 0
    last_err: Optional[str] = None
    for attempt in range(HTTP_RETRY_ATTEMPTS):
        try:
            async with session.get(url, headers=headers) as resp:
                last_status = resp.status
                if resp.status == 200:
                    return await resp.read(), 200
                if resp.status in (401, 403) and _is_nse_host(url) and attempt == 0:
                    # Cookies likely expired — re-prime once and retry
                    logger.info("NSE %s on %s — re-priming cookies", resp.status, url)
                    await _force_reprime()
                    continue
                if resp.status in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {resp.status}"
                else:
                    body_preview = (await resp.read())[:200]
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"HTTP {resp.status}: {body_preview!r}",
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = type(e).__name__ + ": " + str(e)[:120]

        if attempt < HTTP_RETRY_ATTEMPTS - 1:
            delay = HTTP_RETRY_BACKOFF_S * (2 ** attempt)
            logger.info(
                "Retry %d/%d for %s in %.1fs (%s)",
                attempt + 2, HTTP_RETRY_ATTEMPTS, url, delay, last_err,
            )
            await asyncio.sleep(delay)

    raise aiohttp.ClientError(
        f"fetch failed after {HTTP_RETRY_ATTEMPTS} attempts "
        f"(last status {last_status}, last err {last_err}): {url}"
    )


async def fetch_text(
    url: str,
    *,
    referer: Optional[str] = None,
    encoding: str = "utf-8",
    extra_headers: Optional[dict] = None,
) -> Tuple[str, int]:
    body, status = await fetch_bytes(url, referer=referer, extra_headers=extra_headers)
    try:
        return body.decode(encoding, errors="replace"), status
    except Exception:  # noqa: BLE001
        return body.decode("latin-1", errors="replace"), status


async def close() -> None:
    """Tear down the shared session. Call from process shutdown."""
    global _session, _primed
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
    _primed = False
