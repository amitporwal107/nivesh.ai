"""V3 Phase 0b primitive extraction from Groww __NEXT_DATA__.

All tests run against synthetic fixtures — no network, no DB.
Locks the parser contract against future regressions.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.groww_client import (  # noqa: E402
    _extract_v3_primitives,
    parse_next_data,
    _years_between,
    _parse_iso_date,
)


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


def _make_nd(**overrides):
    """Minimal Groww __NEXT_DATA__ fixture that exercises every v3 field."""
    base = {
        "scheme_name": "HDFC Balanced Advantage Fund Direct Growth",
        "plan_type": "Direct",
        "regular_search_id": "hdfc-growth-fund-growth",
        "direct_search_id": None,
        "allotment_date": "2013-01-01",
        "launch_date": "01-Jan-2013",
        "portfolio_turnover": 27,
        "fund_manager_details": [
            {
                "person_name": "Anil Bamboli",
                "date_from": _days_ago(365 * 3 + 60),  # ~3.2y ago
                "education": "CFA, Masters in Management",
                "experience": "SBI Fund Management prior.",
                "funds_managed": [{"scheme_name": "X"}, {"scheme_name": "Y"}, {"scheme_name": "Z"}],
            },
            {
                "person_name": "Junior Manager",
                "date_from": _days_ago(180),  # 0.5y ago
                "education": "CA",
                "experience": "",
                "funds_managed": [{"scheme_name": "X"}],
            },
        ],
        "historic_fund_expense": [
            {"expense_ratio": 0.75, "as_on_date": _days_ago(10), "turn_over_ratio": None, "frequency": "Monthly"},
            {"expense_ratio": 0.81, "as_on_date": _days_ago(365 * 3), "turn_over_ratio": 30.0, "frequency": "Monthly"},
            {"expense_ratio": 1.93, "as_on_date": _days_ago(365 * 10), "turn_over_ratio": 27.75, "frequency": "Monthly"},
        ],
        "stats": [
            {"type": "FUND_RETURN", "stat_1y": 5.34, "stat_3y": 17.21, "stat_5y": 18.54},
            {"type": "CATEGORY_AVG_RETURN", "stat_1y": 4.59, "stat_3y": 11.87, "stat_5y": 10.67},
            {"type": "RANK_WITHIN_CATEGORY", "stat_1y": 19, "stat_3y": 2, "stat_5y": 1},
        ],
        "analysis": [
            {"analysis_type": "PROS", "analysis_subject": "p_return_analysis",
             "analysis_desc": "Consistently higher returns", "rating": None},
            {"analysis_type": "CONS", "analysis_subject": "c_risk_analysis",
             "analysis_desc": "High drawdown in 2020", "rating": None},
        ],
    }
    base.update(overrides)
    return base


def test_allotment_date_and_fund_age():
    nd = _make_nd()
    v3 = _extract_v3_primitives(nd, holdings=[])
    assert v3["allotment_date"] == "2013-01-01"
    # Fund was allotted Jan 2013 → age > 12 years in 2026
    assert v3["fund_age_years"] is not None
    assert v3["fund_age_years"] >= 12.0


def test_primary_manager_is_longest_tenured():
    v3 = _extract_v3_primitives(_make_nd(), holdings=[])
    assert v3["primary_manager"]["name"] == "Anil Bamboli"
    assert v3["primary_manager"]["tenure_years"] >= 3.0
    assert v3["primary_manager"]["funds_managed_count"] == 3
    assert len(v3["fund_managers"]) == 2


def test_expense_trend_delta_latest_vs_3y_ago():
    v3 = _extract_v3_primitives(_make_nd(), holdings=[])
    # latest 0.75 - 3y-ago 0.81 = -0.06 (declining expense, good)
    assert v3["expense_ratio_latest"] == 0.75
    assert v3["expense_ratio_3y_ago"] == 0.81
    assert v3["expense_trend_delta"] == -0.06


def test_turnover_takes_first_non_null_in_history():
    v3 = _extract_v3_primitives(_make_nd(), holdings=[])
    # First entry has null turn_over, second is 30.0 → picks 30.0
    assert v3["turnover_ratio"] == 30.0
    assert v3["turnover_as_of"] is not None


def test_turnover_falls_back_to_top_level_when_history_empty():
    nd = _make_nd(historic_fund_expense=[])
    v3 = _extract_v3_primitives(nd, holdings=[])
    assert v3["turnover_ratio"] == 27.0


def test_category_peer_stats_and_rank():
    v3 = _extract_v3_primitives(_make_nd(), holdings=[])
    assert v3["category_avg_returns"] == {"1y": 4.59, "3y": 11.87, "5y": 10.67}
    assert v3["rank_within_category"] == {"1y": 19, "3y": 2, "5y": 1}


def test_top10_concentration_sums_first_10_holdings():
    holdings = [{"pct": 5.5 - i * 0.3} for i in range(15)]
    v3 = _extract_v3_primitives(_make_nd(), holdings=holdings)
    # First 10 pcts: 5.5,5.2,4.9,4.6,4.3,4.0,3.7,3.4,3.1,2.8 → sum = 41.5
    assert v3["top10_concentration_pct"] == 41.5


def test_sibling_slug_is_regular_when_primary_is_direct():
    v3 = _extract_v3_primitives(_make_nd(plan_type="Direct"), holdings=[])
    assert v3["sibling_slug"] == "hdfc-growth-fund-growth"


def test_sibling_slug_is_direct_when_primary_is_regular():
    nd = _make_nd(plan_type="Regular", direct_search_id="foo-direct", regular_search_id=None)
    v3 = _extract_v3_primitives(nd, holdings=[])
    assert v3["sibling_slug"] == "foo-direct"


def test_analysis_preserves_pros_and_cons():
    v3 = _extract_v3_primitives(_make_nd(), holdings=[])
    assert len(v3["analysis"]) == 2
    assert v3["analysis"][0]["type"] == "PROS"
    assert v3["analysis"][1]["type"] == "CONS"


def test_historic_expense_truncated_to_36():
    hfe = [
        {"expense_ratio": 0.75 + i * 0.01, "as_on_date": _days_ago(i * 30),
         "turn_over_ratio": None, "frequency": "Monthly"}
        for i in range(60)
    ]
    v3 = _extract_v3_primitives(_make_nd(historic_fund_expense=hfe), holdings=[])
    assert len(v3["historic_expense"]) == 36


def test_parse_next_data_emits_v3_block():
    """Integration: full parse_next_data must surface v3_primitives key."""
    parsed = parse_next_data(_make_nd())
    assert "v3_primitives" in parsed
    assert parsed["v3_primitives"]["primary_manager"]["name"] == "Anil Bamboli"


def test_handles_missing_fields_gracefully():
    """All V3 fields must be None (not raise) when Groww omits them."""
    v3 = _extract_v3_primitives({}, holdings=[])
    assert v3["allotment_date"] is None
    assert v3["fund_age_years"] is None
    assert v3["primary_manager"] is None
    assert v3["fund_managers"] == []
    assert v3["expense_trend_delta"] is None
    assert v3["turnover_ratio"] is None
    assert v3["top10_concentration_pct"] is None
    assert v3["sibling_slug"] is None
    assert v3["analysis"] == []


def test_years_between_helper():
    today = _today_iso()
    assert _years_between(today) == 0.0
    # 1 year ago
    one_y = _days_ago(365)
    assert 0.9 <= _years_between(one_y) <= 1.1
    # Future date → clamped to 0
    future = (datetime.now(timezone.utc).date() + timedelta(days=100)).isoformat()
    assert _years_between(future) == 0.0


def test_iso_date_parser_handles_z_suffix():
    assert _parse_iso_date("2022-07-28T18:30:00.788Z") == "2022-07-28"
    assert _parse_iso_date("2013-01-01") == "2013-01-01"
    assert _parse_iso_date("") is None
    assert _parse_iso_date(None) is None
    assert _parse_iso_date("garbage") is None
