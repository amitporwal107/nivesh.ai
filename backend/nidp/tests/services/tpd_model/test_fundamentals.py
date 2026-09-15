"""v3 fundamentals block (PRD §17-18, 21-22, 25): every value comes from a filing whose exchange timestamp is at
or before 15:30 IST on the prediction day T. A filing with no timestamp is unusable (NaN), never proxied."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import ist

T = date(2026, 9, 10)


def _quarters(symbol="ACME", n=8, pat=None, revenue=None, broadcast_lag_days=30, last_end=date(2026, 6, 30)):
    """n quarterly rows ending at last_end, each broadcast `broadcast_lag_days` after its period end."""
    ends = [pd.Timestamp(last_end) - pd.DateOffset(months=3 * k) + pd.offsets.QuarterEnd(0) for k in range(n)][::-1]
    pat = pat or [100 + 10 * k for k in range(n)]
    revenue = revenue or [1000 + 50 * k for k in range(n)]
    rows = []
    for k, e in enumerate(ends):
        rows.append({"symbol": symbol, "period_end": e, "period_type": "quarterly", "consolidated": True,
                     "revenue_from_ops_cr": float(revenue[k]), "ebitda_cr": 0.2 * revenue[k], "pat_cr": float(pat[k]),
                     "eps_basic": pat[k] / 10, "total_equity_cr": 2000.0 + 50 * k, "long_term_debt_cr": 300.0,
                     "short_term_debt_cr": 100.0, "finance_costs_cr": 8.0, "pbt_cr": 1.3 * pat[k],
                     "current_assets_cr": 900.0, "current_liabilities_cr": 600.0, "equity_share_capital_cr": 100.0,
                     "face_value": 10.0, "broadcast_at": ist((e + pd.Timedelta(days=broadcast_lag_days)).date(), 18, 0)})
    return pd.DataFrame(rows)


def test_only_filings_broadcast_by_the_cutoff_on_T_are_known():
    from nidp.services.tpd_model.fundamentals import pit_fundamentals

    q = _quarters()
    f = pit_fundamentals(q, ["ACME"], T, close={"ACME": 500.0})
    assert f.loc["ACME", "latest_period_end"] == pd.Timestamp("2026-06-30")   # broadcast 2026-07-30 < T
    late = q.copy()
    late.loc[late["period_end"] == pd.Timestamp("2026-06-30"), "broadcast_at"] = ist(T, 15, 30, 1)
    f2 = pit_fundamentals(late, ["ACME"], T, close={"ACME": 500.0})
    assert f2.loc["ACME", "latest_period_end"] == pd.Timestamp("2026-03-31")  # one second late -> previous quarter


def test_unstamped_filings_are_never_used_as_a_proxy():
    from nidp.services.tpd_model.fundamentals import pit_fundamentals

    q = _quarters()
    q["broadcast_at"] = pd.NaT
    f = pit_fundamentals(q, ["ACME"], T, close={"ACME": 500.0})
    assert np.isnan(f.loc["ACME", "pat_yoy"]) and f.loc["ACME", "fund_missing"] == 1.0


def test_growth_acceleration_and_ratios_are_computed_from_known_quarters():
    from nidp.services.tpd_model.fundamentals import pit_fundamentals

    # PAT accelerating: YoY growth rising quarter on quarter
    q = _quarters(pat=[100, 100, 100, 100, 110, 125, 148, 180])
    f = pit_fundamentals(q, ["ACME"], T, close={"ACME": 500.0}).loc["ACME"]
    assert f["pat_yoy"] == pytest.approx(0.80)          # 180 vs 100
    assert f["pat_qoq"] == pytest.approx(180 / 148 - 1)
    assert f["pat_accel"] == pytest.approx(0.80 - 0.48)  # this quarter's YoY minus last quarter's YoY
    assert f["pat_margin"] == pytest.approx(180 / 1350)
    assert f["de_ratio"] == pytest.approx(400 / 2350)
    assert f["interest_cover"] == pytest.approx((1.3 * 180 + 8) / 8)
    assert f["current_ratio"] == pytest.approx(1.5)
    ttm_eps = sum(p / 10 for p in [110, 125, 148, 180])
    assert f["pe_ttm"] == pytest.approx(500 / ttm_eps)
    assert f["days_since_results"] == (pd.Timestamp(T) - pd.Timestamp("2026-07-30")).days
    assert f["fund_missing"] == 0.0


def test_fewer_than_five_known_quarters_gives_nan_growth_not_zero():
    from nidp.services.tpd_model.fundamentals import pit_fundamentals

    f = pit_fundamentals(_quarters(n=3), ["ACME"], T, close={"ACME": 500.0}).loc["ACME"]
    assert np.isnan(f["pat_yoy"]) and np.isnan(f["pat_accel"]) and not np.isnan(f["pat_qoq"])


def test_symbol_without_any_filing_is_present_with_nans_and_flag():
    from nidp.services.tpd_model.fundamentals import FUNDAMENTAL_FEATURES, pit_fundamentals

    f = pit_fundamentals(_quarters(), ["ACME", "NOFILE"], T, close={"ACME": 500.0, "NOFILE": 20.0})
    assert set(f.index) == {"ACME", "NOFILE"} and f.loc["NOFILE", "fund_missing"] == 1.0
    assert all(np.isnan(f.loc["NOFILE", c]) for c in FUNDAMENTAL_FEATURES if c != "fund_missing")


def test_future_filings_do_not_change_T():
    from nidp.services.tpd_model.fundamentals import pit_fundamentals

    q = _quarters()
    from nidp.services.tpd_model.fundamentals import FUNDAMENTAL_FEATURES
    cols = list(FUNDAMENTAL_FEATURES)
    base = pit_fundamentals(q, ["ACME"], T, close={"ACME": 500.0})[cols]
    future = pd.concat([q, _quarters(n=1, last_end=date(2026, 9, 30), pat=[999]).assign(broadcast_at=ist(date(2026, 10, 25), 18, 0))])
    again = pit_fundamentals(future, ["ACME"], T, close={"ACME": 500.0})[cols]
    x, y = base.to_numpy(np.float64), again.to_numpy(np.float64)
    assert ((x.view(np.uint64) == y.view(np.uint64)) | (np.isnan(x) & np.isnan(y))).all()


def test_ownership_uses_the_latest_stamped_filing_and_reports_qoq_change():
    from nidp.services.tpd_model.fundamentals import pit_ownership

    shp = pd.DataFrame([
        {"symbol": "ACME", "period_end": pd.Timestamp("2026-03-31"), "promoter_pct": 60.0, "promoter_pledged_pct": 5.0,
         "fii_pct": 10.0, "dii_pct": 8.0, "mf_pct": 4.0, "broadcast_at": ist(date(2026, 4, 20), 17, 0)},
        {"symbol": "ACME", "period_end": pd.Timestamp("2026-06-30"), "promoter_pct": 58.0, "promoter_pledged_pct": 2.0,
         "fii_pct": 12.0, "dii_pct": 8.5, "mf_pct": 4.5, "broadcast_at": ist(date(2026, 7, 18), 17, 0)},
        {"symbol": "ACME", "period_end": pd.Timestamp("2026-09-30"), "promoter_pct": 55.0, "promoter_pledged_pct": 0.0,
         "fii_pct": 15.0, "dii_pct": 9.0, "mf_pct": 5.0, "broadcast_at": pd.NaT},
    ])
    o = pit_ownership(shp, ["ACME", "NOFILE"], T).loc["ACME"]
    assert o["promoter_pct"] == 58.0 and o["pledge_pct"] == 2.0 and o["fii_pct"] == 12.0
    assert o["promoter_chg_qoq"] == pytest.approx(-2.0) and o["pledge_chg_qoq"] == pytest.approx(-3.0)
    assert o["fii_chg_qoq"] == pytest.approx(2.0) and o["own_missing"] == 0.0
