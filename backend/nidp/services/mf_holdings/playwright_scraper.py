"""Playwright-based portfolio scraper for AMCs that require browser interaction.

Used for AMCs whose monthly portfolio pages are SPAs (lazy-loaded via JS):
  - AXIS MF     — accordion-based SPA; file links appear after user click
  - ICICI PRU   — React SPA; portfolio tab must be clicked to load links
  - KOTAK MF    — hCaptcha-protected; requires stealth browser fingerprint

Architecture:
  - Single shared Chromium browser instance (lazy-started per scraper run)
  - Route interception captures xlsx/zip bytes in-flight — no temp file needed
  - Returns (bytes, url) same contract as _try_download() in amc_dispatch.py
  - Automatically tears down the browser after the scrape completes

Requires playwright browsers installed in the container:
    playwright install chromium
This is done in Dockerfile.backend.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Timeout for a full single-AMC scrape (seconds). Long SPAs like Axis can take 30s.
_SCRAPE_TIMEOUT_S = 90

# File patterns we intercept from the browser
_DOWNLOAD_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_DOWNLOAD_EXTENSIONS = (".xlsx", ".xls", ".zip")


async def scrape_portfolio(
    amc_id: str,
    as_of_month: date,
    headless: bool = True,
    stealth: bool = False,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Navigate to an AMC's portfolio page, interact as a human would,
    intercept the monthly xlsx/zip download, and return (bytes, url).

    Returns (None, None) if no download was captured.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed — run: playwright install chromium")
        return None, None

    recipe = _RECIPES.get(amc_id)
    if not recipe:
        logger.warning("playwright_scraper: no recipe for amc_id=%s", amc_id)
        return None, None

    captured_bytes: Optional[bytes] = None
    captured_url:   Optional[str]   = None

    month_long  = as_of_month.strftime("%B")    # "April"
    month_short = as_of_month.strftime("%b")    # "Apr"
    year_full   = as_of_month.strftime("%Y")    # "2026"

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = await browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            if stealth:
                # playwright-stealth spoofs canvas, WebGL, navigator.webdriver, etc.
                # Helps bypass hCaptcha and basic bot-detection fingerprinting.
                try:
                    from playwright_stealth import stealth_async
                    page = await ctx.new_page()
                    await stealth_async(page)
                except ImportError:
                    logger.warning("playwright_scraper: playwright-stealth not installed; skipping")
                    page = await ctx.new_page()
            else:
                page = await ctx.new_page()

            # Intercept xlsx/zip responses and capture the bytes
            async def _on_response(response):
                nonlocal captured_bytes, captured_url
                if captured_bytes is not None:
                    return  # already got what we need
                url = response.url
                ct = (response.headers.get("content-type") or "").lower().split(";")[0].strip()
                is_download = (
                    ct in _DOWNLOAD_MIME_TYPES
                    or any(url.lower().endswith(ext) or f"{ext}?" in url.lower()
                           for ext in _DOWNLOAD_EXTENSIONS)
                )
                if not is_download:
                    return
                # Filter by target month — skip files that don't match
                url_lower = url.lower()
                month_match = (
                    month_long.lower() in url_lower
                    or month_short.lower() in url_lower
                    or as_of_month.strftime("%m") in url_lower
                )
                year_match = year_full in url_lower
                if not (month_match and year_match):
                    logger.debug(
                        "playwright_scraper[%s]: intercepted file but month/year mismatch: %s",
                        amc_id, url[-80:],
                    )
                    return
                try:
                    body = await response.body()
                    if len(body) > 1024:
                        captured_bytes = body
                        captured_url = url
                        logger.info(
                            "playwright_scraper[%s]: captured %d bytes from %s",
                            amc_id, len(body), url[-80:],
                        )
                except Exception as e:
                    logger.debug("playwright_scraper[%s]: body() failed for %s: %s", amc_id, url[-60:], e)

            page.on("response", lambda r: asyncio.ensure_future(_on_response(r)))

            # Also listen for download events (some AMCs trigger file-save dialogs)
            async def _on_download(download):
                nonlocal captured_bytes, captured_url
                if captured_bytes is not None:
                    return
                try:
                    path = await download.path()
                    if path:
                        with open(path, "rb") as f:
                            body = f.read()
                        if len(body) > 1024:
                            captured_bytes = body
                            captured_url = download.url
                            logger.info(
                                "playwright_scraper[%s]: captured download %d bytes: %s",
                                amc_id, len(body), download.url[-60:],
                            )
                except Exception as e:
                    logger.debug("playwright_scraper[%s]: download path() failed: %s", amc_id, e)

            page.on("download", lambda d: asyncio.ensure_future(_on_download(d)))

            # Navigate and interact
            logger.info("playwright_scraper[%s]: navigating to %s", amc_id, recipe["url"])
            await page.goto(recipe["url"], wait_until="domcontentloaded", timeout=30_000)

            # Run the interaction recipe in a thread-executor (it uses sync Playwright API)
            await asyncio.wait_for(
                _run_recipe(page, recipe, month_long, month_short, year_full),
                timeout=_SCRAPE_TIMEOUT_S,
            )

            # Brief settle — some AMCs trigger downloads slightly after the click
            await page.wait_for_timeout(3000)

            await browser.close()

    except asyncio.TimeoutError:
        logger.warning("playwright_scraper[%s]: timed out after %ds", amc_id, _SCRAPE_TIMEOUT_S)
    except Exception as e:
        logger.warning("playwright_scraper[%s]: scrape failed: %s", amc_id, e)

    if captured_bytes is None:
        logger.warning(
            "playwright_scraper[%s]: no xlsx/zip captured for %s %s",
            amc_id, month_long, year_full,
        )
    return captured_bytes, captured_url


# ── Async interaction recipes ────────────────────────────────────────────────

async def _run_recipe(page, recipe: dict, month_long: str, month_short: str, year: str):
    """Run the AMC-specific interaction sequence."""
    interact = recipe.get("interact")
    if interact:
        await interact(page, month_long, month_short, year)


async def _click(page, text: str, timeout: int = 5000) -> bool:
    try:
        loc = page.get_by_text(text, exact=False).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click()
        logger.debug("playwright_scraper: clicked %r", text)
        return True
    except Exception:
        return False


async def _idle(page, ms: int = 2000):
    try:
        await page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        await page.wait_for_timeout(ms)


async def _expand_all(page, selector: str):
    try:
        await page.eval_on_selector_all(
            selector,
            "els => els.forEach(e => { if (e.offsetParent) e.click(); })"
        )
    except Exception:
        pass


# ── Per-AMC interaction recipes (async) ─────────────────────────────────────

async def _interact_axis(page, month_long: str, month_short: str, year: str):
    """Axis statutory-disclosures page — accordion SPA."""
    await _idle(page, 3000)
    await _click(page, "Portfolio Disclosure")
    await _idle(page, 2000)
    await _click(page, "Monthly Portfolio")
    await _idle(page, 3000)
    # Click the consolidated all-schemes file for the target month
    for text in (
        f"All Schemes",
        f"Consolidated",
        f"{month_long[:3]} {year[-2:]}",          # "Apr 26"
        f"30 {month_short}",                       # "30 Apr"
        f"30-{month_long[:3].lower()}",            # "30-apr"
    ):
        if await _click(page, text, timeout=3000):
            await _idle(page, 4000)
            break
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await _idle(page, 2000)


async def _interact_icici(page, month_long: str, month_short: str, year: str):
    """ICICI Pru portfolio-disclosure page — React SPA."""
    await _idle(page, 6000)   # WAF challenge needs time; longer wait helps
    await _click(page, "Monthly Portfolio Disclosure")
    await _idle(page, 2000)
    # Find and click the target month entry
    for text in (month_long, month_short, f"{month_short} {year}"):
        if await _click(page, text, timeout=3000):
            await _idle(page, 3000)
            break
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await _idle(page, 2000)


async def _interact_kotak(page, month_long: str, month_short: str, year: str):
    """Kotak statutory-disclosure page — hCaptcha protected, stealth recommended."""
    await _idle(page, 6000)   # Wait for hCaptcha + page bootstrap
    # Check if hCaptcha challenge frame is present — if so, we can't solve it
    try:
        captcha_frame = page.frame_locator("iframe[src*='hcaptcha']")
        if await captcha_frame.locator("body").count() > 0:
            logger.warning(
                "playwright_scraper[kotak]: hCaptcha challenge detected. "
                "Continuing anyway — may fail. Consider playwright-stealth or manual cookie injection."
            )
    except Exception:
        pass
    await _click(page, "Portfolio Disclosure")
    await _idle(page, 2000)
    await _click(page, "Monthly Portfolio")
    await _idle(page, 2000)
    for text in (month_long, month_short, f"{month_short} {year}"):
        if await _click(page, text, timeout=3000):
            await _idle(page, 3000)
            break
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await _idle(page, 2000)


# ── Recipe registry ──────────────────────────────────────────────────────────

_RECIPES: dict[str, dict] = {
    "axis": {
        "url":      "https://www.axismf.com/statutory-disclosures",
        "interact": _interact_axis,
        "stealth":  False,
    },
    "icici_pru": {
        "url":      "https://www.icicipruamc.com/portfolio-disclosure",
        "interact": _interact_icici,
        "stealth":  False,
    },
    "kotak": {
        "url":      "https://www.kotakmf.com/forms-and-downloads/portfolio-disclosure",
        "interact": _interact_kotak,
        "stealth":  True,   # hCaptcha — stealth mode improves pass rate
    },
}
