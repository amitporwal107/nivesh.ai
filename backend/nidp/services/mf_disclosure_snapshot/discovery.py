"""Universal AMC Disclosure Discovery Engine — Phase 1 (static HTML).

Architecture from docs/NIDP_FEEDS/AMC_DISCLOSURES_AND_TER_REPORTS_STARTEGY.md:

  Phase 1 — Static HTML parse (this module; covers T1/T2 AMCs)
  Phase 2 — Playwright headless render (T3, deferred)
  Phase 3 — XHR/network interception (T3 ICICI/ABSL/Kotak, deferred)
  Phase 4 — Recursive crawl (T4 Mirae, deferred)

KEY PRINCIPLE: store `discovery_url + strategy + regex`, NOT final file URLs.
Final URLs change monthly; discovery pages are stable for 1-2 years.

Contract for callers:
    discovered = await discover_latest_file(
        discovery_url = "https://www.hdfcfund.com/statutory-disclosure/total-expense-ratio-of-mutual-fund-schemes",
        regex_pattern = r".*(expense.ratio|ter|total.expense).*\.(pdf|xlsx)",
        http          = session,
        label         = "hdfc_ter",
    )
    # → "https://www.hdfcfund.com/...TER-disclosure-May-2026.xlsx" or None
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# File extensions we consider valid disclosure files
_FILE_EXTS = re.compile(r"\.(pdf|xlsx|xls|csv)(\?|$)", re.IGNORECASE)


def _absolute(href: str, base_url: str) -> str:
    """Resolve relative href against the page's base URL."""
    if href.startswith("http"):
        return href
    return urljoin(base_url, href)


def _score_link(href: str, text: str, pattern: re.Pattern) -> int:
    """Score a link candidate — higher is better.

    Scoring criteria:
      +3  matches the caller's regex (content-type hint)
      +2  href/text contains current year (4-digit or 2-digit) or 'latest'
      +1  href ends with .xlsx (preferred over .xls/.pdf for machine parsing)
    """
    import datetime as _dt
    score = 0
    target = (href + " " + text).lower()
    if pattern.search(target):
        score += 3
    # Year matching: check both "2026" and "26" (AMCs often use 2-digit years)
    today = _dt.date.today()
    year4 = str(today.year)         # "2026"
    year2 = year4[2:]               # "26"
    if year4 in target or (year2 in target and "latest" not in target) or "latest" in target:
        score += 2
    if href.lower().endswith(".xlsx") or ".xlsx?" in href.lower():
        score += 1
    return score


async def _fetch_html(
    http: aiohttp.ClientSession,
    url: str,
    label: str,
) -> Optional[str]:
    """GET url, return text. Returns None on non-200 or connection error."""
    try:
        async with http.get(
            url,
            allow_redirects=True,
            headers={"User-Agent": _DEFAULT_UA},
        ) as resp:
            if resp.status != 200:
                logger.debug("discovery[%s]: %s → status=%d", label, url, resp.status)
                return None
            return await resp.text(errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.debug("discovery[%s]: %s → %s: %s", label, url, type(e).__name__, e)
        return None


def _extract_file_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return list of (absolute_href, link_text) for all file links on page."""
    soup = BeautifulSoup(html, "lxml")
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        if not _FILE_EXTS.search(href):
            continue
        abs_href = _absolute(href, base_url)
        text = a.get_text(" ", strip=True)
        results.append((abs_href, text))
    return results


async def discover_latest_file(
    discovery_url: str,
    regex_pattern: str,
    http: aiohttp.ClientSession,
    label: str = "",
    *,
    prefer_xlsx: bool = True,
) -> Optional[str]:
    """Phase 1: static HTML discovery.

    Fetches `discovery_url`, finds all PDF/XLSX links, scores them against
    `regex_pattern`, and returns the highest-scoring match.

    Returns None if no matching link is found — caller should log and skip.
    """
    html = await _fetch_html(http, discovery_url, label or discovery_url[-40:])
    if not html:
        logger.warning("discovery[%s]: failed to fetch %s", label, discovery_url)
        return None

    links = _extract_file_links(html, discovery_url)
    if not links:
        logger.warning("discovery[%s]: no file links found on %s", label, discovery_url)
        return None

    try:
        pattern = re.compile(regex_pattern, re.IGNORECASE)
    except re.error as exc:
        logger.error("discovery[%s]: bad regex %r — %s", label, regex_pattern, exc)
        pattern = re.compile(r".", re.IGNORECASE)  # match everything as fallback

    scored = [
        (_score_link(href, text, pattern), href, text)
        for href, text in links
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    logger.debug(
        "discovery[%s]: %d file links found; top candidates: %s",
        label,
        len(links),
        [(s, h[-60:]) for s, h, _ in scored[:3]],
    )

    # Return highest-scoring link; must score > 0 (i.e. regex matched somewhere)
    for score, href, text in scored:
        if score > 0:
            logger.info(
                "discovery[%s]: selected %s (score=%d, text=%r)",
                label, href[-70:], score, text[:60],
            )
            return href

    logger.warning(
        "discovery[%s]: %d links found but none matched regex %r on %s",
        label, len(links), regex_pattern, discovery_url,
    )
    return None


async def discover_latest_file_multi(
    discovery_urls: list[str],
    regex_pattern: str,
    http: aiohttp.ClientSession,
    label: str = "",
) -> Optional[str]:
    """Try multiple discovery URLs in order; return first match.

    Used when an AMC has separate pages for TER vs portfolio vs factsheet.
    """
    for url in discovery_urls:
        result = await discover_latest_file(url, regex_pattern, http, label=label)
        if result:
            return result
    logger.warning("discovery[%s]: no file found across %d URLs", label, len(discovery_urls))
    return None
