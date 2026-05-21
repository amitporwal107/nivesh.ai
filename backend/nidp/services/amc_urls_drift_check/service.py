"""AMC + AMFI listing-page health check.

For each (target, candidate URL) tuple imported from the live ingesters,
issue a HEAD (then GET fallback) and record whether the URL is alive.
An AMC counts as `healthy` if AT LEAST ONE of its candidates is 200-OK.

The run is finalised FAILED when any AMC ends up with zero healthy
candidates — that's the exact failure shape we want to alert on, because
the next monthly portfolio scrape will silently produce zero rows.

This script makes outbound HTTPS calls only. It does not touch any
database table beyond the JobRun audit row.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Tuple

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.services.mf_holdings.amc_dispatch import _PORTFOLIO_PAGE_CANDIDATES
from nidp.services.mf_disclosure_snapshot.amfi_central import (
    _TER_PAGE_CANDIDATES, _RISK_PAGE_CANDIDATES,
)

logger = logging.getLogger(__name__)

_CONCURRENCY = 8


async def _check_url(http: aiohttp.ClientSession, url: str) -> Tuple[str, int, str]:
    """Returns (url, status, note). Status 0 means transport error."""
    try:
        async with http.head(url, allow_redirects=True) as r:
            # Some servers 405 HEAD; fall back to GET (range-limited).
            if r.status in (405, 501):
                async with http.get(url, allow_redirects=True,
                                    headers={"Range": "bytes=0-512"}) as r2:
                    return url, r2.status, "via-get"
            return url, r.status, "head"
    except Exception as e:  # noqa: BLE001
        return url, 0, f"{type(e).__name__}: {e}"[:200]


async def _check_target(
    http: aiohttp.ClientSession, sem: asyncio.Semaphore,
    target: str, urls: List[str],
) -> Dict[str, object]:
    """Walk all candidate URLs for one target (AMC or AMFI page).
    Healthy = at least one 200-OK."""
    results: List[Dict[str, object]] = []

    async def _bound(url: str):
        async with sem:
            return await _check_url(http, url)

    for url, status, note in await asyncio.gather(*[_bound(u) for u in urls]):
        results.append({"url": url, "status": status, "note": note})

    healthy = any(r["status"] == 200 for r in results)
    return {
        "target":         target,
        "healthy":        healthy,
        "candidate_count": len(urls),
        "ok_count":       sum(1 for r in results if r["status"] == 200),
        "candidates":     results,
    }


async def run() -> Dict[str, object]:
    """Ping every AMC + AMFI listing page. Raise on red flags so JobRun
    captures status=FAILED (alert-worthy)."""
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
    headers = {"User-Agent": DEFAULT_UA}
    sem = asyncio.Semaphore(_CONCURRENCY)

    targets: Dict[str, List[str]] = {}
    for amc_id, urls in _PORTFOLIO_PAGE_CANDIDATES.items():
        if urls:
            targets[f"amc:{amc_id}"] = list(urls)
    if _TER_PAGE_CANDIDATES:
        targets["amfi:ter"]  = list(_TER_PAGE_CANDIDATES)
    if _RISK_PAGE_CANDIDATES:
        targets["amfi:risk"] = list(_RISK_PAGE_CANDIDATES)

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as http:
        per_target = await asyncio.gather(*[
            _check_target(http, sem, t, urls) for t, urls in targets.items()
        ])

    red_targets = [t for t in per_target if not t["healthy"]]
    healthy_count = sum(1 for t in per_target if t["healthy"])

    summary = {
        "total_targets":    len(per_target),
        "healthy_count":    healthy_count,
        "unhealthy_count":  len(red_targets),
        "unhealthy_targets": [t["target"] for t in red_targets],
        "details":          per_target,
    }

    if red_targets:
        names = ", ".join(t["target"] for t in red_targets)
        # Re-raise so JobRun finalises status=FAILED. Downstream alert
        # pipeline picks this up automatically.
        logger.error(
            "amc_urls_drift_check: %d unhealthy target(s) — %s",
            len(red_targets), names,
        )
        raise RuntimeError(
            f"AMC URL drift detected — {len(red_targets)} target(s) have zero "
            f"healthy candidates: {names}"
        )

    logger.info(
        "amc_urls_drift_check: all %d targets healthy",
        len(per_target),
    )
    return summary
