"""Company IR page scraper.

Fetches quarterly result PDFs / press releases from company investor
relations pages. Tries the company's own website first (fastest, often
ahead of NSE XBRL processing) then falls back to NSE XBRL.

Returns raw text content for the LLM extractor to parse.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Screener.in uses its own slugs — most match NSE symbols, exceptions listed here.
# Covers all current Nifty 500 constituents (May 2026).
#
# Rules:
#  - Symbols with '&' in the NSE ticker MUST have a slug override (URL-safe)
#  - Holding companies with no quarterly P&L section on Screener.in are kept here
#    as a record; fetch_screener_quarters will return None for them (expected)
#  - Rebranded companies: Screener.in keeps the OLD slug after rename
_SCREENER_SLUG_MAP: dict[str, str] = {
    "M&M": "M-AND-M",
    "BAJAJFINSV": "BAJAJ-FINSERV",  # holding co — page exists but no id="quarters" section
    "TATAMOTORS": "TMCV",           # Tata Motors; Screener.in uses TMCV (CV division page)
    "GVT&D": "GE-TD",              # GE Vernova T&D India; NSE '&' breaks URL — slug is GE-TD
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _screener_session_cookie() -> Optional[str]:
    """Return the Screener.in session cookie from env if configured.

    Set SCREENER_SESSION_COOKIE in the environment to the value of the
    'sessionid' cookie obtained after logging in to screener.in.
    Without this, Screener.in returns a login-wall for financial data pages.
    """
    return os.environ.get("SCREENER_SESSION_COOKIE")


async def _get_text(url: str) -> Optional[str]:
    headers = dict(_HEADERS)
    cookie = _screener_session_cookie()
    if cookie and "screener.in" in url:
        headers["Cookie"] = f"sessionid={cookie}"
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=_TIMEOUT) as s:
            async with s.get(url, allow_redirects=True) as r:
                if r.status != 200:
                    return None
                ct = r.headers.get("Content-Type", "")
                if "pdf" in ct:
                    return await _extract_pdf_text(await r.read())
                return await r.text(errors="replace")
    except Exception as e:
        logger.debug("_get_text(%s) failed: %s", url, e)
        return None


async def _extract_pdf_text(data: bytes) -> Optional[str]:
    """Extract text from PDF bytes using pdfminer if available."""
    try:
        import io
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        buf = io.BytesIO()
        extract_text_to_fp(io.BytesIO(data), buf, laparams=LAParams(), output_type="text", codec="utf-8")
        return buf.getvalue().decode("utf-8", errors="replace")[:40_000]
    except ImportError:
        # pdfminer not installed — return first 2KB as fallback
        return data[:2000].decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("PDF extraction failed: %s", e)
        return None


def _find_result_links(html: str, base_url: str) -> list[str]:
    """Find links in the IR page that look like quarterly result docs."""
    keywords = ["quarter", "result", "financial", "q1", "q2", "q3", "q4",
                "half year", "annual", "investor", "earnings"]
    urls = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        if any(k in href.lower() for k in ["q1", "q2", "q3", "q4", "result", "financial"]):
            if href.startswith("http"):
                urls.append(href)
            elif href.startswith("/"):
                from urllib.parse import urlparse
                p = urlparse(base_url)
                urls.append(f"{p.scheme}://{p.netloc}{href}")
    # Also scan link text
    for text, href in re.findall(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', html, re.IGNORECASE):
        if any(k in text.lower() for k in keywords):
            if href.startswith("http"):
                urls.append(href)
    return list(dict.fromkeys(urls))[:5]  # dedupe, top 5


async def scrape_ir_page(symbol: str, ir_url: str, results_url: Optional[str] = None) -> Optional[str]:
    """Scrape the company IR page and return text of the latest result doc."""
    target = results_url or ir_url

    # Try the direct results URL first
    html = await _get_text(target)
    if not html:
        return None

    # If it's a PDF directly, return it
    if len(html) > 100 and "%" in html[:4]:  # PDF magic bytes as text
        return html

    # If it's an XBRL XML file, return it directly for parse_nse_integrated_xbrl
    if html.lstrip().startswith("<?xml"):
        logger.info("ir_scraper: got XBRL XML for %s from %s", symbol, target)
        return html

    # Find result document links on the page
    links = _find_result_links(html, target)
    for link in links:
        content = await _get_text(link)
        if content and len(content) > 500:
            logger.info("ir_scraper: found result doc for %s at %s", symbol, link)
            return content[:40_000]

    # Return the page HTML itself if no doc found — LLM can still parse tables
    if len(html) > 200:
        return html[:40_000]
    return None


async def fetch_nse_integrated_filing(symbol: str) -> Optional[str]:
    """Find and fetch the latest NSE Integrated XBRL filing (_WEB.xml) for a symbol.

    Uses the NSE corporate-announcements API (which lists all filings with attachment
    URLs) and picks the most recent _WEB.xml attachment from nsearchives.nseindia.com.
    Returns raw XML text, or None if not found.
    """
    from datetime import date, timedelta
    today = date.today()
    from_date = (today - timedelta(days=90)).strftime("%d-%m-%Y")
    to_date = today.strftime("%d-%m-%Y")

    url = (
        f"https://www.nseindia.com/api/corporate-announcements"
        f"?index=equities&symbol={symbol}&from_date={from_date}&to_date={to_date}"
    )
    try:
        from nidp.shared.sources.nse_fetcher import fetch_text
        text, status = await fetch_text(
            url,
            referer="https://www.nseindia.com/companies-listing/corporate-integrated-filing"
                    f"?symbol={symbol}&tabIndex=equity",
        )
        if status != 200 or not text:
            return None

        import json as _json
        items = _json.loads(text)
        if not isinstance(items, list):
            return None

        # Find announcements whose attachment is an integrated XBRL WEB.xml
        xbrl_url = None
        for item in items:
            attach = item.get("attchmntFile", "") or ""
            if "nsearchives" in attach and "_WEB.xml" in attach and "INTEGRATED_FILING" in attach:
                xbrl_url = attach
                break  # items are sorted newest-first

        if not xbrl_url:
            logger.debug("fetch_nse_integrated_filing: no _WEB.xml found for %s", symbol)
            return None

        logger.info("fetch_nse_integrated_filing: found XBRL for %s → %s", symbol, xbrl_url)
        xml_text = await _get_text(xbrl_url)
        return xml_text

    except Exception as e:
        logger.debug("fetch_nse_integrated_filing(%s) failed: %s", symbol, e)
        return None


def _screener_is_rate_limited(html: Optional[str]) -> bool:
    """Return True if Screener.in returned a hard rate-limit / captcha / auth wall.

    NOTE: Screener.in always includes a "Log In" link in the page navigation, so
    the word "login" appears in every page HTML — authenticated or not.  We check
    only for signals that indicate the page itself is a blocking wall, NOT the
    mere presence of a login nav-link.

    This function should be called ONLY when id="quarters" is absent from the page
    (i.e. the financial data section didn't load), because an authenticated page
    with financial data cannot be rate-limited by definition.
    """
    if not html:
        return False
    lower = html.lower()
    # High-confidence block signals — these appear in actual blocking responses, not nav links
    if any(k in lower for k in ("captcha", "rate limit", "too many requests",
                                 "sign in to continue", "please verify")):
        return True
    # "Login" in the page title (not just nav) indicates a login-wall redirect
    if "<title>" in lower:
        title_start = lower.index("<title>")
        title_end = lower.find("</title>", title_start)
        if title_end > title_start:
            title = lower[title_start:title_end]
            if "login" in title or "sign in" in title:
                return True
    return False


async def fetch_screener_quarters(symbol: str) -> Optional[tuple[str, bool]]:
    """Fetch Screener.in company page for the given NSE symbol.

    Tries consolidated first, then standalone. Returns (html, is_consolidated)
    or None if the company is not found on Screener.in.

    Raises RuntimeError if Screener.in signals rate-limiting so callers can
    detect the difference between "symbol doesn't exist" and "we're blocked".

    Detection order:
      1. If id="quarters" is in the HTML → valid authenticated page, return it.
      2. Else if the page signals a hard block (captcha/rate-limit/login wall) →
         raise RuntimeError so the caller can halt the run.
      3. Else → company not found / no financial data, return None.
    """
    slug = _SCREENER_SLUG_MAP.get(symbol, symbol)
    for consolidated in (True, False):  # consolidated first — matches NSE XBRL backfill rows
        path = "consolidated/" if consolidated else ""
        url = f"https://www.screener.in/company/{slug}/{path}"
        html = await _get_text(url)
        # Check for valid financial data section FIRST — if present, the session is
        # authenticated and functional regardless of nav-bar login links.
        if html and len(html) > 1000 and 'id="quarters"' in html:
            # Verify that the quarterly table has actual column data.
            # On consolidated pages for large established companies, Screener.in
            # renders the row labels server-side but leaves columns empty (JavaScript
            # lazy-loads the values in a browser). The standalone page always has
            # server-rendered data. We detect this by checking for data-date-key=
            # within the first 6 KB after the quarters section start.
            q_start = html.find('id="quarters"')
            # Scope the check to the quarters section only (end at next </section>
            # to avoid false-positives from annual P&L which immediately follows
            # and also contains data-date-key attributes).
            q_end = html.find('</section>', q_start)
            q_chunk = html[q_start: q_end if q_end != -1 else q_start + 6000]
            # Check for recent data: at least one data-date-key within the last 4 years.
            # Some consolidated pages have data-date-key but only for old historical
            # periods (e.g. 2012-2015); prefer standalone page for recent data.
            recent_dates = re.findall(r'data-date-key="(20(?:2[2-9]|3\d)-\d{2}-\d{2})"', q_chunk)
            if recent_dates:
                logger.info("fetch_screener_quarters: found %s on Screener.in (consolidated=%s)", symbol, consolidated)
                return html, consolidated
            logger.debug(
                "fetch_screener_quarters: %s quarters section present but no recent data "
                "(consolidated=%s) — trying next URL",
                symbol, consolidated,
            )
        # Financial data absent — now check if it's a hard block or just not found.
        if _screener_is_rate_limited(html):
            raise RuntimeError(f"Screener.in rate-limit detected for {symbol}")
    logger.debug("fetch_screener_quarters: %s not found on Screener.in", symbol)
    return None


async def fetch_nse_xbrl(symbol: str, period: Optional[str] = None) -> Optional[str]:
    """Fetch structured financial data from NSE XBRL API."""
    url = (
        f"https://www.nseindia.com/api/results-comparator"
        f"?params={symbol}&period=Quarterly&type=Standalone"
    )
    try:
        from nidp.shared.sources.nse_fetcher import fetch_text
        text, status = await fetch_text(
            url,
            referer="https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
        )
        if status == 200:
            return text
    except Exception as e:
        logger.debug("NSE XBRL fetch for %s failed: %s", symbol, e)
    return None
