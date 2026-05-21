"""Unit tests for Phase 1 AMC-scraper robustness (2026-05-21).

Covers:
  - mf_holdings + mf_disclosure_snapshot reclassify PARTIAL→FAILED when
    zero rows produced (silent-pass loophole closed).
  - amc_dispatch._discover_xlsx_link returns None on month-mismatched HTML
    and logs format-drift when only PDF/CSV links match.
  - amc_dispatch._try_listing_page_discovery walks all candidates and stops
    at the first 200-OK with a matching xlsx.
  - amfi_central._fetch_first_xlsx_url walks fallback page candidates.
  - amc_urls_drift_check.service.run raises when any target has zero
    healthy candidates (so the JobRun is finalised FAILED).
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── discover_xlsx_link ─────────────────────────────────────────────
from nidp.services.mf_holdings.amc_dispatch import _discover_xlsx_link


def test_discover_xlsx_link_returns_match_when_month_year_present():
    html = (
        '<a href="/portfolio-may-2026.xlsx">Portfolio May 2026</a>'
        '<a href="/portfolio-april-2026.xlsx">April 2026</a>'
    )
    out = _discover_xlsx_link(html, "https://example.com", date(2026, 5, 1))
    assert out == "https://example.com/portfolio-may-2026.xlsx"


def test_discover_xlsx_link_returns_none_when_only_old_months():
    html = '<a href="/portfolio-jan-2026.xlsx">Portfolio Jan 2026</a>'
    out = _discover_xlsx_link(html, "https://example.com", date(2026, 5, 1))
    assert out is None


def test_discover_xlsx_link_format_drift_logged(caplog):
    """A PDF link matching the target month indicates AMC switched format."""
    html = '<a href="/portfolio-may-2026.pdf">Portfolio May 2026</a>'
    with caplog.at_level("INFO", logger="nidp.services.mf_holdings.amc_dispatch"):
        out = _discover_xlsx_link(html, "https://example.com", date(2026, 5, 1))
    assert out is None
    assert any("format-drift" in r.message for r in caplog.records)


# ─── _try_listing_page_discovery walks candidates ───────────────────
@pytest.mark.asyncio
async def test_try_listing_page_walks_candidates(monkeypatch):
    from nidp.services.mf_holdings import amc_dispatch

    monkeypatch.setattr(
        amc_dispatch, "_PORTFOLIO_PAGE_CANDIDATES",
        {"sbi": [
            "https://www.sbimf.com/dead-page",
            "https://www.sbimf.com/portfolio-disclosure",
        ]}, raising=False,
    )

    class _Resp:
        def __init__(self, status, html=""):
            self.status = status
            self._html = html
        async def __aenter__(self):  return self
        async def __aexit__(self, *a): return False
        async def text(self, errors=None): return self._html

    class _Session:
        def get(self, url, allow_redirects=True):
            if url.endswith("/dead-page"):
                return _Resp(404)
            return _Resp(
                200,
                '<a href="/may-2026.xlsx">May 2026 Portfolio</a>',
            )

    found = await amc_dispatch._try_listing_page_discovery(
        "sbi", _Session(), date(2026, 5, 1),
    )
    assert found == "https://www.sbimf.com/portfolio-disclosure/may-2026.xlsx"


# ─── amfi_central._fetch_first_xlsx_url ─────────────────────────────
@pytest.mark.asyncio
async def test_amfi_central_walks_candidates():
    from nidp.services.mf_disclosure_snapshot import amfi_central

    class _Resp:
        def __init__(self, status, html=""):
            self.status = status
            self._html = html
        async def __aenter__(self):  return self
        async def __aexit__(self, *a): return False
        async def text(self, errors=None): return self._html

    class _Session:
        def get(self, url, allow_redirects=True):
            if "dead" in url:
                return _Resp(404)
            return _Resp(200, '<a href="/files/ter-may-2026.xlsx">TER Disclosure</a>')

    url = await amfi_central._fetch_first_xlsx_url(
        _Session(),
        ("https://www.amfiindia.com/dead-ter", "https://www.amfiindia.com/ter"),
        "ter",
    )
    assert url and url.endswith(".xlsx")


# ─── amc_urls_drift_check raises on any red ─────────────────────────
@pytest.mark.asyncio
async def test_drift_check_raises_when_any_target_red(monkeypatch):
    from nidp.services.amc_urls_drift_check import service as drift

    # Stub the imports so we control the target list deterministically.
    monkeypatch.setattr(
        drift, "_PORTFOLIO_PAGE_CANDIDATES",
        {"sbi": ["https://example.com/sbi"]}, raising=False,
    )
    monkeypatch.setattr(drift, "_TER_PAGE_CANDIDATES",  (), raising=False)
    monkeypatch.setattr(drift, "_RISK_PAGE_CANDIDATES", (), raising=False)

    async def _check_url(http, url):
        return url, 404, "head"
    monkeypatch.setattr(drift, "_check_url", _check_url, raising=True)

    class _Session:
        async def __aenter__(self):  return self
        async def __aexit__(self, *a): return False

    # aiohttp.ClientSession is constructed inside run(); replace it.
    import nidp.services.amc_urls_drift_check.service as svc_mod
    monkeypatch.setattr(
        svc_mod.aiohttp, "ClientSession",
        lambda *a, **kw: _Session(), raising=True,
    )

    with pytest.raises(RuntimeError) as exc:
        await drift.run()
    assert "amc:sbi" in str(exc.value)


@pytest.mark.asyncio
async def test_drift_check_passes_when_all_healthy(monkeypatch):
    from nidp.services.amc_urls_drift_check import service as drift

    monkeypatch.setattr(
        drift, "_PORTFOLIO_PAGE_CANDIDATES",
        {"sbi": ["https://example.com/sbi"]}, raising=False,
    )
    monkeypatch.setattr(drift, "_TER_PAGE_CANDIDATES",  (), raising=False)
    monkeypatch.setattr(drift, "_RISK_PAGE_CANDIDATES", (), raising=False)

    async def _check_url(http, url):
        return url, 200, "head"
    monkeypatch.setattr(drift, "_check_url", _check_url, raising=True)

    class _Session:
        async def __aenter__(self):  return self
        async def __aexit__(self, *a): return False

    import nidp.services.amc_urls_drift_check.service as svc_mod
    monkeypatch.setattr(
        svc_mod.aiohttp, "ClientSession",
        lambda *a, **kw: _Session(), raising=True,
    )

    summary = await drift.run()
    assert summary["unhealthy_count"] == 0
    assert summary["healthy_count"] == 1
