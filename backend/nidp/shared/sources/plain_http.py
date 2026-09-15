"""Plain HTTP fetch with bounded exponential-backoff retry.

For sources that are ordinary web servers — NSDL, BSE — as opposed to
NSE, whose Akamai edge needs the cookie-prime / re-prime dance in
`nse_fetcher`. Keeping them apart means a BSE or NSDL request never
inherits NSE's bot-mitigation retry semantics (and vice versa).
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
)

logger = logging.getLogger(__name__)


async def fetch_bytes(url: str, *, referer: Optional[str] = None,
                      label: str = "http") -> Tuple[bytes, int]:
    """GET `url`, retrying transient failures. Returns (body, status).

    Raises aiohttp.ClientError once retries are exhausted so the caller's
    job_log records a real failure rather than an empty success.
    """
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    if referer:
        headers["Referer"] = referer
    last_err: Optional[str] = None
    last_status = 0
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(HTTP_RETRY_ATTEMPTS):
            try:
                async with session.get(url, headers=headers,
                                       allow_redirects=True) as resp:
                    last_status = resp.status
                    if resp.status == 200:
                        return await resp.read(), 200
                    last_err = f"HTTP {resp.status}"
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
            if attempt < HTTP_RETRY_ATTEMPTS - 1:
                delay = HTTP_RETRY_BACKOFF_S * (2 ** attempt)
                logger.info("%s retry %d/%d for %s in %.1fs (%s)",
                            label, attempt + 2, HTTP_RETRY_ATTEMPTS,
                            url, delay, last_err)
                await asyncio.sleep(delay)
    raise aiohttp.ClientError(
        f"{label} fetch failed after {HTTP_RETRY_ATTEMPTS} attempts "
        f"(last status {last_status}, last err {last_err}): {url}"
    )
