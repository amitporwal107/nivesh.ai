"""Tests for Phase 1 Groww MF Data Fetcher.

Covers:
  - scheme_name_to_slug deterministic mapping
  - parse_page with a cached real-world HTML sample
  - Off-hours gating logic
  - resolver key derivation (with/without pg)
"""
from __future__ import annotations
import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import groww_client  # noqa: E402
from services import fund_data_resolver as resolver  # noqa: E402


SAMPLE_PATH = Path("/tmp/groww_sample.html")


def test_slug_basic():
    assert groww_client.scheme_name_to_slug(
        "Nippon India Multi Cap Fund - Direct - Growth"
    ) == "nippon-india-multi-cap-fund-direct-growth"


def test_slug_strips_plan_and_parens():
    # "Direct" inside parens gets stripped along with the parens; the fetch
    # layer's search-API fallback recovers in that case.
    out = groww_client.scheme_name_to_slug(
        "HDFC Flexi Cap Fund (IDCW Direct Plan) - Growth"
    )
    assert out == "hdfc-flexi-cap-fund-growth"


@pytest.mark.skipif(not SAMPLE_PATH.exists(), reason="sample HTML not present")
def test_parse_sample():
    html = SAMPLE_PATH.read_text()
    parsed = groww_client.parse_page(html)
    assert parsed is not None
    assert len(parsed["holdings"]) >= 10
    # holdings percent sum is realistic
    tot = sum(h["pct"] for h in parsed["holdings"])
    assert 70 <= tot <= 115, f"total % = {tot}"
    # first holding has name + slug + sector
    h0 = parsed["holdings"][0]
    assert h0["name"] and h0["stock_slug"]
    assert h0["sector"]
    # metadata extracted
    assert parsed["metadata"]["aum_cr"] is not None
    assert parsed["metadata"]["nav"] is not None
    # sector aggregate
    assert parsed["sectors"] and parsed["sectors"][0]["pct"] > 0


def test_off_hours_weekend():
    # Saturday 10:00 IST = Saturday 04:30 UTC
    sat_10_ist = datetime(2026, 4, 18, 4, 30, tzinfo=timezone.utc)
    assert resolver._is_off_hours(sat_10_ist) is True


def test_off_hours_weekday_market_open():
    # Wednesday 11:00 IST = 05:30 UTC
    wed_11 = datetime(2026, 4, 15, 5, 30, tzinfo=timezone.utc)
    assert resolver._is_off_hours(wed_11) is False


def test_off_hours_weekday_after_close():
    # Wednesday 17:00 IST = 11:30 UTC
    wed_17 = datetime(2026, 4, 15, 11, 30, tzinfo=timezone.utc)
    assert resolver._is_off_hours(wed_17) is True


def test_resolve_instrument_no_pg(monkeypatch):
    """When Postgres is unconfigured, fallback to name-based key."""
    async def run():
        return await resolver.resolve_instrument("Sample Fund", scheme_code=None)
    out = asyncio.run(run())
    assert out["scheme_name"] == "Sample Fund"
    assert out["instrument_key"].startswith("NAME:")


def test_resolve_instrument_with_scheme_code_no_pg():
    async def run():
        return await resolver.resolve_instrument("X Fund", scheme_code="125497")
    out = asyncio.run(run())
    # Falls back to SCHEME: key when pg returns nothing
    assert out["instrument_key"] == "SCHEME:125497"
