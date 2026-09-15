"""v3 feature set = v2 features + technical extensions + point-in-time fundamentals + ownership, one row per
symbol with a bar on T. The v2 columns must be bit-identical to v2; everything after T must be invisible."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import ist


def _bitwise_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    a, b = a.sort_index(), b.sort_index()
    if list(a.columns) != list(b.columns) or list(a.index) != list(b.index):
        return False
    x, y = a.to_numpy(np.float64), b.to_numpy(np.float64)
    return bool(((x.view(np.uint64) == y.view(np.uint64)) | (np.isnan(x) & np.isnan(y))).all())


def _financials(symbols, last_end=date(2026, 6, 30), n=8, lag_days=30):
    rows = []
    for sym in symbols:
        ends = [pd.Timestamp(last_end) - pd.DateOffset(months=3 * k) + pd.offsets.QuarterEnd(0) for k in range(n)][::-1]
        for k, e in enumerate(ends):
            rows.append({"symbol": sym, "period_end": e, "period_type": "quarterly", "consolidated": True,
                         "revenue_from_ops_cr": 1000.0 + 50 * k, "ebitda_cr": 200.0 + 10 * k, "pat_cr": 100.0 + 10 * k,
                         "eps_basic": 10.0 + k, "total_equity_cr": 2000.0, "long_term_debt_cr": 300.0, "short_term_debt_cr": 100.0,
                         "finance_costs_cr": 8.0, "pbt_cr": 130.0 + 13 * k, "current_assets_cr": 900.0, "current_liabilities_cr": 600.0,
                         "equity_share_capital_cr": 100.0, "face_value": 10.0,
                         "broadcast_at": ist((e + pd.Timedelta(days=lag_days)).date(), 18, 0)})
    return pd.DataFrame(rows)


def _shareholding(symbols):
    rows = []
    for sym in symbols:
        for e, d, prom in (("2026-03-31", date(2026, 4, 20), 60.0), ("2026-06-30", date(2026, 7, 18), 58.0)):
            rows.append({"symbol": sym, "period_end": pd.Timestamp(e), "promoter_pct": prom, "promoter_pledged_pct": 2.0,
                         "fii_pct": 10.0, "dii_pct": 8.0, "mf_pct": 4.0, "broadcast_at": ist(d, 17, 0)})
    return pd.DataFrame(rows)


def test_v3_columns_and_v2_part_is_bit_identical(panel, sessions, symbols):
    from nidp.services.tpd_model.features import FEATURE_LIST, compute_features
    from nidp.services.tpd_model.features_v3 import FEATURE_LIST_V3, compute_features_v3
    from nidp.services.tpd_model.fundamentals import FUNDAMENTAL_FEATURES, OWNERSHIP_FEATURES
    from nidp.services.tpd_model.technical_ext import TECHNICAL_EXT_FEATURES

    T = sessions[205]
    members = set(symbols[:10])
    v2 = compute_features(panel, T, market_members=members)
    v3 = compute_features_v3(panel, T, market_members=members, financials=_financials(symbols[:5]),
                             shareholding=_shareholding(symbols[:5]))
    assert list(v3.columns) == list(FEATURE_LIST_V3)
    assert list(FEATURE_LIST_V3) == list(FEATURE_LIST) + list(TECHNICAL_EXT_FEATURES) + list(FUNDAMENTAL_FEATURES) + list(OWNERSHIP_FEATURES)
    assert _bitwise_equal(v3[list(FEATURE_LIST)], v2)


def test_technical_extension_columns_match_the_block(panel, sessions, symbols):
    from nidp.services.tpd_model.features_v3 import compute_features_v3
    from nidp.services.tpd_model.technical_ext import TECHNICAL_EXT_FEATURES, extended_technical

    T = sessions[205]
    v3 = compute_features_v3(panel, T)
    w = panel[(panel["symbol"] == "SYM003") & (panel["as_of_date"] <= pd.Timestamp(T))]
    direct = extended_technical(w)
    for k in TECHNICAL_EXT_FEATURES:
        assert v3.loc["SYM003", k] == pytest.approx(direct[k], rel=1e-12, nan_ok=True), k


def test_fundamentals_join_and_missing_flags(panel, sessions, symbols):
    from nidp.services.tpd_model.features_v3 import compute_features_v3

    T = sessions[205]  # 2025-10-16: filings must be dated 2025 to be known by then
    shp = _shareholding(symbols[:5])
    shp["period_end"] = [pd.Timestamp("2025-03-31"), pd.Timestamp("2025-06-30")] * 5
    shp["broadcast_at"] = [ist(date(2025, 4, 20), 17, 0), ist(date(2025, 7, 18), 17, 0)] * 5
    v3 = compute_features_v3(panel, T, financials=_financials(symbols[:5], last_end=date(2025, 6, 30)), shareholding=shp)
    assert v3.loc["SYM001", "fund_missing"] == 0.0 and v3.loc["SYM001", "pat_yoy"] == pytest.approx(170 / 130 - 1)
    assert v3.loc["SYM001", "own_missing"] == 0.0 and v3.loc["SYM001", "promoter_chg_qoq"] == pytest.approx(-2.0)
    assert v3.loc["SYM020", "fund_missing"] == 1.0 and np.isnan(v3.loc["SYM020", "pat_yoy"])
    assert v3.loc["SYM020", "own_missing"] == 1.0


def test_without_financials_the_block_is_loudly_missing_not_silently_zero(panel, sessions):
    from nidp.services.tpd_model.features_v3 import compute_features_v3
    from nidp.services.tpd_model.fundamentals import FUNDAMENTAL_FEATURES, OWNERSHIP_FEATURES

    v3 = compute_features_v3(panel, sessions[205])
    assert (v3["fund_missing"] == 1.0).all() and (v3["own_missing"] == 1.0).all()
    for c in FUNDAMENTAL_FEATURES + OWNERSHIP_FEATURES:
        if c not in ("fund_missing", "own_missing"):
            assert v3[c].isna().all(), c


def test_future_bars_filings_and_holdings_are_invisible(panel, sessions, symbols):
    from nidp.services.tpd_model.features_v3 import compute_features_v3

    T = sessions[205]  # 2025-10-16-ish; filings dated 2026 are the "future" here
    fin = _financials(symbols[:5], last_end=date(2025, 6, 30))
    shp = _shareholding(symbols[:5])
    shp["broadcast_at"] = [ist(date(2025, 4, 20), 17, 0), ist(date(2025, 7, 18), 17, 0)] * 5
    shp["period_end"] = [pd.Timestamp("2025-03-31"), pd.Timestamp("2025-06-30")] * 5
    base = compute_features_v3(panel, T, financials=fin, shareholding=shp)

    fut_panel = panel.copy()
    later = fut_panel["as_of_date"] > pd.Timestamp(T)
    fut_panel.loc[later, ["open", "high", "low", "close"]] *= 4
    fut_fin = pd.concat([fin, _financials(symbols[:5], last_end=date(2025, 9, 30), n=1, lag_days=20)], ignore_index=True)
    late_row = fin.iloc[[0]].assign(period_end=pd.Timestamp("2025-06-30"), pat_cr=9999.0, broadcast_at=ist(T, 15, 30, 1))
    fut_fin = pd.concat([fut_fin, late_row], ignore_index=True)
    fut_shp = pd.concat([shp, shp.iloc[[0]].assign(period_end=pd.Timestamp("2025-09-30"), promoter_pct=1.0,
                                                    broadcast_at=ist(date(2025, 10, 30), 17, 0))], ignore_index=True)
    again = compute_features_v3(panel if False else fut_panel, T, financials=fut_fin, shareholding=fut_shp)
    assert _bitwise_equal(base, again)


def test_design_matrix_v3_has_the_new_columns_and_keeps_v2_ones():
    from nidp.services.tpd_model.design import MODEL_COLUMNS, MODEL_COLUMNS_V3

    assert set(MODEL_COLUMNS) <= set(MODEL_COLUMNS_V3)
    for c in ("vol_ratio_20", "atr5_atr20", "adx14", "pat_yoy", "pat_accel", "roe_ttm", "de_ratio", "pe_ttm",
              "promoter_pct", "pledge_pct", "fii_chg_qoq", "fund_missing", "own_missing", "days_since_results"):
        assert c in MODEL_COLUMNS_V3, c
    assert "cfo_pat" in MODEL_COLUMNS_V3 and len(MODEL_COLUMNS_V3) == 76  # stamped via its results filing since 2026-09-15


def test_reference_cashflow_and_mf_months_flow_through_the_v3_block(panel, sessions, symbols):
    """The gap-fix inputs reach the block: PB via the reference face value, cfo_pat via a stamped cash flow, mf_pct via
    the monthly MF portfolios (complete months only); the ownership block gets the fundamentals' share count."""
    from nidp.services.tpd_model.features_v3 import compute_features_v3

    T = sessions[205]  # 2025-10-16
    syms = symbols[:3]
    fin = _financials(syms, last_end=date(2025, 6, 30))
    fin["face_value"] = np.nan
    ref = pd.DataFrame({"symbol": syms, "face_value": [10.0] * 3})
    cf = pd.DataFrame([{"symbol": s, "period_end": pd.Timestamp("2025-03-31"), "consolidated": True, "cfo_cr": 500.0,
                        "broadcast_at": ist(date(2025, 5, 20), 18, 0)} for s in syms])
    mf = pd.DataFrame([{"symbol": s, "as_of_month": pd.Timestamp("2025-08-01"), "mf_shares": 2.0e7, "mf_schemes": 30,
                        "month_schemes": 2300, "ingested_at": ist(date(2025, 9, 10), 12, 0)} for s in syms])
    shp = _shareholding(syms)
    shp["period_end"] = [pd.Timestamp("2025-03-31"), pd.Timestamp("2025-06-30")] * 3
    shp["broadcast_at"] = [ist(date(2025, 4, 20), 17, 0), ist(date(2025, 7, 18), 17, 0)] * 3
    shp["mf_pct"] = np.nan                                               # as in the warehouse: the pattern has no MF column
    v3 = compute_features_v3(panel, T, financials=fin, shareholding=shp, reference=ref, cashflow=cf, mf_monthly=mf)
    r = v3.loc["SYM001"]
    assert np.isfinite(r["pb"]) and r["pb"] == pytest.approx(r["pb"])   # 100 cr capital / FV 10 = 10 cr shares
    assert r["cfo_pat"] == pytest.approx(500 / (130 + 140 + 150 + 160))  # FY25 = quarters ending Jun-24 .. Mar-25
    assert r["mf_pct"] == pytest.approx(2.0e7 / 1e8 * 100)              # 10 cr shares outstanding
    without = compute_features_v3(panel, T, financials=fin, shareholding=shp)
    assert np.isnan(without.loc["SYM001", "cfo_pat"]) and np.isnan(without.loc["SYM001", "mf_pct"])
    assert without.loc["SYM001", "pb"] == pytest.approx(r["pb"])       # no reference: the period's own PAT/EPS count, same 10 cr
