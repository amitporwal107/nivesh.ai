"""Regression tests for the equity DQ suites — each asserts the suite CATCHES the exact
bad-data pattern found during the 2026-06-23 validation, and passes on clean data."""
from nidp.services.quality_gate.great_expectations_suites import (
    mf_holdings_suite, nse_financials_suite, prices_eod_suite,
    nse_shareholding_suite, stock_fundamentals_latest_suite, v3_stock_scores_suite,
)


def _ok(suite, rows):
    return suite.run(rows).success


def test_mf_holdings_catches_subtotal_corruption():
    base = [{"scheme_code": "X", "as_of_month": "2026-03-01", "security_name": n,
             "security_isin": i, "weight_pct": w, "source": "NIPPON"}
            for n, i, w in [("BSE Ltd", "INE118H01025", 40), ("Reliance", "INE002A01018", 35),
                            ("HDFC Bank", "INE040A01034", 25)]]
    corrupt = base + [{"scheme_code": "X", "as_of_month": "2026-03-01", "security_name": t,
                       "security_isin": "", "weight_pct": 100, "source": "NIPPON"}
                      for t in ("Sub Total", "Grand Total")]
    assert not _ok(mf_holdings_suite(), corrupt)   # 240% -> caught
    assert _ok(mf_holdings_suite(), base)           # 100% -> clean


def test_nse_financials_catches_sign_mismatch():
    bad = [{"symbol": "RPSGVENT", "period_end": "2026-03-31", "period_type": "QUARTERLY",
            "consolidated": True, "pat_cr": 76.0, "eps_basic": -66.0, "revenue_from_ops_cr": 1000.0}]
    ok = [{"symbol": "TCS", "period_end": "2026-03-31", "period_type": "QUARTERLY",
           "consolidated": True, "pat_cr": 120.0, "eps_basic": 12.0, "revenue_from_ops_cr": 600.0}]
    assert not _ok(nse_financials_suite(), bad)
    assert _ok(nse_financials_suite(), ok)


def test_prices_eod_catches_ohlc_violation():
    bad = [{"symbol": "X", "as_of_date": "2026-06-22", "series": "EQ", "open_price": 100,
            "high_price": 90, "low_price": 110, "close_price": 105, "volume": 1000, "deliv_pct": 40}]
    ok = [{"symbol": "X", "as_of_date": "2026-06-22", "series": "EQ", "open_price": 100,
           "high_price": 110, "low_price": 95, "close_price": 105, "volume": 1000, "deliv_pct": 40}]
    assert not _ok(prices_eod_suite(), bad)
    assert _ok(prices_eod_suite(), ok)


def test_shareholding_catches_duplicate_period():
    dup = [{"symbol": "HDFCBANK", "period_end": "2026-03-31", "promoter_pct": 25, "public_pct": 75,
            "dii_pct": 10, "fii_pct": 20, "promoter_pledged_pct": 0},
           {"symbol": "HDFCBANK", "period_end": "2026-03-31", "promoter_pct": 26, "public_pct": 74,
            "dii_pct": 11, "fii_pct": 19, "promoter_pledged_pct": 0}]
    assert not _ok(nse_shareholding_suite(), dup)
