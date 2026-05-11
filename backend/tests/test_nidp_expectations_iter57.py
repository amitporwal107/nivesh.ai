"""Iteration 57 - Tests for /api/admin/nidp/quality/expectations endpoint.

Validates GE-style expectations docs endpoint:
- 22 feeds, 116+ expectations
- All required feed names present (amfi_nav, fii_dii, bhavcopy, etc.)
- Each feed has suite_name + expectations[] array
- Each expectation has type + kwargs, type belongs to allowed GE types
- Auth enforced (401 without session cookie)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nidp-backfill-ui.preview.emergentagent.com").rstrip("/")
ADMIN_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"

REQUIRED_FEEDS = [
    "amfi_nav", "fii_dii", "bhavcopy", "index_close", "delivery", "fno_bhavcopy",
    "bulk_deals", "block_deals", "corporate_actions", "rbi_yields", "fred_macro",
    "nse_calendar", "nse_equity_master", "nse_shareholding", "nse_financials",
    "index_constituents", "amfi_circulars", "mf_holdings", "mf_disclosure_snapshot",
    "announcement_classifier", "corporate_announcements_nse", "corporate_announcements_bse",
]

ALLOWED_TYPES = {
    "expect_column_values_to_be_not_null",
    "expect_column_values_to_match_regex",
    "expect_column_values_to_be_in_set",
    "expect_column_values_to_be_between",
    "expect_column_values_to_parse_as_date",
    "expect_column_values_to_be_not_in_future",
    "expect_compound_columns_to_be_unique",
    "expect_column_values_to_be_greater_than_or_equal_to_column",
    "expect_column_values_to_be_less_than_or_equal_to_column",
    "expect_column_pair_diff_equals_column",
    "expect_freshness_max_date_equals",
}


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.cookies.set("session_token", ADMIN_TOKEN)
    return s


@pytest.fixture(scope="module")
def expectations_payload(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/admin/nidp/quality/expectations", timeout=30)
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
    return r.json()


# === Auth ===
def test_expectations_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/nidp/quality/expectations", timeout=30)
    assert r.status_code == 401


# === Top-level shape ===
def test_feeds_total_at_least_20(expectations_payload):
    assert expectations_payload.get("feeds_total", 0) >= 20


def test_expectations_total_at_least_100(expectations_payload):
    assert expectations_payload.get("expectations_total", 0) >= 100


def test_feeds_object_present(expectations_payload):
    feeds = expectations_payload.get("feeds")
    assert isinstance(feeds, dict)
    assert len(feeds) >= 20


# === Required feeds ===
def test_all_required_feeds_present(expectations_payload):
    feeds = expectations_payload["feeds"]
    missing = [f for f in REQUIRED_FEEDS if f not in feeds]
    assert not missing, f"Missing feeds: {missing}"


def test_amfi_nav_min_8_rules(expectations_payload):
    rules = expectations_payload["feeds"]["amfi_nav"]["expectations"]
    assert len(rules) >= 8


def test_fii_dii_min_6_rules(expectations_payload):
    rules = expectations_payload["feeds"]["fii_dii"]["expectations"]
    assert len(rules) >= 6


def test_bhavcopy_min_12_rules(expectations_payload):
    rules = expectations_payload["feeds"]["bhavcopy"]["expectations"]
    assert len(rules) >= 12


# === Per-feed structure ===
def test_each_feed_has_suite_name_and_expectations(expectations_payload):
    feeds = expectations_payload["feeds"]
    for name, fdata in feeds.items():
        assert isinstance(fdata.get("suite_name"), str) and fdata["suite_name"], (
            f"{name} missing suite_name"
        )
        assert isinstance(fdata.get("expectations"), list) and len(fdata["expectations"]) > 0, (
            f"{name} missing expectations[]"
        )


def test_every_expectation_has_type_and_kwargs(expectations_payload):
    feeds = expectations_payload["feeds"]
    for fname, fdata in feeds.items():
        for i, exp in enumerate(fdata["expectations"]):
            assert "type" in exp, f"{fname}[{i}] missing 'type'"
            assert "kwargs" in exp, f"{fname}[{i}] missing 'kwargs'"
            assert isinstance(exp["kwargs"], dict)


def test_all_expectation_types_are_valid_ge_types(expectations_payload):
    feeds = expectations_payload["feeds"]
    bad = []
    for fname, fdata in feeds.items():
        for exp in fdata["expectations"]:
            if exp["type"] not in ALLOWED_TYPES:
                bad.append((fname, exp["type"]))
    assert not bad, f"Invalid GE types: {bad}"


def test_amfi_nav_has_regex_expectation(expectations_payload):
    rules = expectations_payload["feeds"]["amfi_nav"]["expectations"]
    regex_rules = [r for r in rules if r["type"] == "expect_column_values_to_match_regex"]
    assert regex_rules, "amfi_nav should have at least one regex expectation"
    assert "regex" in regex_rules[0]["kwargs"], "regex kwarg missing"
