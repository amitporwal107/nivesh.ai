"""
Iteration 40 regression tests:
- Portfolio totals.xirr_pct must be realistic (value-weighted; was 367%, now clamped to -50..+50 for priyanka)
- coverage_pct should reflect (scored MF + scored EQ) / (total MF + total EQ); for priyanka ~56%
- Per-holding xirr_pct clamped to -80..+150
- Per-holding payload exposes xirr_source, cagr_1y_pct, cagr_3y_pct, cagr_5y_pct
- At least 1 mutual_fund falls back to cagr_3y (Groww primitives)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-pro-985.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com


@pytest.fixture(scope="module")
def enriched():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    r = s.get(f"{BASE_URL}/api/portfolio/holdings-enriched", timeout=90)
    assert r.status_code == 200, r.text
    return r.json()


# --- totals.xirr_pct realistic ---
def test_totals_xirr_realistic(enriched):
    xirr = enriched["totals"].get("xirr_pct")
    assert xirr is not None, "totals.xirr_pct missing"
    assert -50 <= xirr <= 50, f"portfolio xirr_pct should be within [-50, 50], got {xirr}"
    # spec expects ~15% for priyanka
    assert 5 <= xirr <= 30, f"expected ~15% for priyanka, got {xirr}"


# --- coverage_pct reflects MF + equities ---
def test_coverage_at_least_55(enriched):
    cov = enriched.get("coverage_pct")
    assert cov is not None, "coverage_pct missing from response"
    assert cov >= 55, f"coverage_pct expected >= 55, got {cov}"


# --- per-holding xirr clamping ---
def test_per_holding_xirr_clamped(enriched):
    violating = []
    for h in enriched["holdings"]:
        x = h.get("xirr_pct")
        if x is None:
            continue
        if x > 150 or x < -80:
            violating.append((h.get("holding_id"), h.get("name"), x))
    assert not violating, f"holdings violating xirr clamp [-80, 150]: {violating}"


# --- new fields exist on payload ---
def test_new_xirr_source_and_cagr_fields(enriched):
    allowed_sources = {"personal", "cagr_1y", "cagr_3y", "cagr_5y", None}
    missing_field_counts = {"xirr_source": 0, "cagr_1y_pct": 0, "cagr_3y_pct": 0, "cagr_5y_pct": 0}
    for h in enriched["holdings"]:
        # key must be present (value may be None)
        for k in missing_field_counts:
            if k not in h:
                missing_field_counts[k] += 1
        assert h.get("xirr_source") in allowed_sources, \
            f"invalid xirr_source={h.get('xirr_source')} on {h.get('holding_id')}"
    # Allow missing on some rows but the majority of MF holdings should have these fields
    mf_holdings = [h for h in enriched["holdings"] if h.get("asset_type") == "mutual_fund"]
    assert mf_holdings, "no mutual_fund holdings found"
    mf_with_source_field = sum(1 for h in mf_holdings if "xirr_source" in h)
    assert mf_with_source_field == len(mf_holdings), \
        f"xirr_source missing on {len(mf_holdings)-mf_with_source_field}/{len(mf_holdings)} MF holdings"


# --- at least one MF falls back to cagr_3y ---
def test_mf_cagr_3y_fallback_used(enriched):
    mf_cagr_3y = [h for h in enriched["holdings"]
                  if h.get("asset_type") == "mutual_fund" and h.get("xirr_source") == "cagr_3y"]
    assert len(mf_cagr_3y) >= 1, \
        f"expected >=1 mutual_fund with xirr_source=cagr_3y; got {len(mf_cagr_3y)}"


# --- xirr_source distribution sanity ---
def test_xirr_source_distribution(enriched):
    sources = {}
    for h in enriched["holdings"]:
        src = h.get("xirr_source")
        sources[src] = sources.get(src, 0) + 1
    # Should have at least personal + cagr_* mix (not all None)
    non_null = sum(v for k, v in sources.items() if k is not None)
    assert non_null >= 1, f"all holdings have xirr_source=None; distribution={sources}"
    print(f"xirr_source distribution: {sources}")
