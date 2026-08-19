"""Egress-routing tests for the shared NSE fetcher.

NSE blocks by SOURCE IP. Measured 2026-08-19, the identical request with the
identical headers from two VMs in the same region and project:

    nidp-stack-vm  34.93.60.254  -> 403     (the ingestion host)
    nivesh-app-vm  34.47.250.214 -> 200

So the fix is a different egress, not different headers. What these tests hold is
the blast radius of that fix: the proxy must reach NSE and *only* NSE, because the
BSE fallbacks are what keep prices and delivery flowing while NSE is blocked.

No network.
"""
from __future__ import annotations

import importlib

import pytest

import nidp.shared.config as cfg
import nidp.shared.sources.nse_fetcher as nf


@pytest.fixture
def proxied(monkeypatch):
    """Reload the fetcher with a proxy configured."""
    monkeypatch.setattr(cfg, "NSE_HTTPS_PROXY", "http://10.160.0.5:3128")
    mod = importlib.reload(nf)
    monkeypatch.setattr(mod, "NSE_HTTPS_PROXY", "http://10.160.0.5:3128")
    yield mod
    importlib.reload(nf)


# ── scope: NSE only ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://www.nseindia.com/api/allIndices",
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_18082026.csv",
    "https://archives.nseindia.com/content/historical/EQUITIES/x.csv",
])
def test_nse_hosts_go_through_the_proxy(proxied, url):
    assert proxied._proxy_for(url) == "http://10.160.0.5:3128"


@pytest.mark.parametrize("url", [
    "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20260818_F_0000.CSV",
    "https://www.bseindia.com/BSEDATA/gross/2026/SCBSEALL1808.zip",
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w",
])
def test_bse_never_goes_through_the_proxy(proxied, url):
    """BSE is reachable directly from the ingestion host and is the fallback that
    survives NSE being blocked. Routing it through the proxy would put a single
    point of failure in front of the escape hatch."""
    assert proxied._proxy_for(url) is None


@pytest.mark.parametrize("url", [
    "https://www.rbi.org.in/x.pdf",
    "https://portal.amfiindia.com/spages/NAVAll.txt",
    "https://fpi.nsdl.co.in/web/Reports/Archive.aspx",
])
def test_other_sources_are_untouched(proxied, url):
    assert proxied._proxy_for(url) is None


# ── unset = direct, no behaviour change ─────────────────────────────────────

def test_no_proxy_configured_means_direct_for_everything(monkeypatch):
    """The default must be a no-op: this landed while feeds were already broken,
    and it must not become a second way for them to break."""
    monkeypatch.setattr(nf, "NSE_HTTPS_PROXY", "")
    assert nf._proxy_for("https://www.nseindia.com/api/allIndices") is None
    assert nf._proxy_for("https://www.bseindia.com/x") is None


def test_shipped_default_is_unset(monkeypatch):
    """Read the env the way config does, with nothing set."""
    monkeypatch.delenv("NSE_HTTPS_PROXY", raising=False)
    reloaded = importlib.reload(cfg)
    try:
        assert reloaded.NSE_HTTPS_PROXY == ""
    finally:
        importlib.reload(cfg)


# ── pacing ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pace_spaces_consecutive_nse_requests(monkeypatch):
    """An IP block is earned. Moving to a fresh egress without slowing down
    burns the fresh address the same way, so pacing travels with the proxy."""
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(nf.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(nf, "NSE_MIN_REQUEST_INTERVAL_S", 0.5)
    monkeypatch.setattr(nf, "_last_nse_request_at", 0.0)

    await nf._pace()          # first call: nothing to wait for
    await nf._pace()          # second call: must wait out the interval
    assert any(s > 0 for s in slept), "second consecutive request was not paced"


@pytest.mark.asyncio
async def test_pacing_can_be_disabled(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(nf.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(nf, "NSE_MIN_REQUEST_INTERVAL_S", 0)
    await nf._pace()
    await nf._pace()
    assert slept == []


# ── config default ──────────────────────────────────────────────────────────

def test_default_interval_is_polite_but_not_crippling():
    """~3 req/s. A full bhavcopy day is a handful of requests, so this costs
    nothing real, while a runaway loop is throttled at the source."""
    assert 0 < cfg.NSE_MIN_REQUEST_INTERVAL_S <= 1.0
