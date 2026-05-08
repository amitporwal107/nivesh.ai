"""Company IR page scraper.

Fetches quarterly result PDFs / press releases from company investor
relations pages. Tries the company's own website first (fastest, often
ahead of NSE XBRL processing) then falls back to NSE XBRL.

Returns raw text content for the LLM extractor to parse.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _get_text(url: str) -> Optional[str]:
    try:
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
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
