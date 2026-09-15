"""Evening capture of the day's results filings from NSE's integrated-filing listing + XBRL (no network in tests)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import ist

T = date(2026, 8, 13)


def _listing():
    return {"data": [
        {"symbol": "AAA", "broadcast_Date": "13-Aug-2026 18:05:10", "qe_Date": "30-JUN-2026", "consolidated": "Consolidated", "audited": "Un-Audited",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1_WEB.xml"},
        {"symbol": "AAA", "broadcast_Date": "13-Aug-2026 17:59:00", "qe_Date": "30-JUN-2026", "consolidated": "Standalone", "audited": "Un-Audited",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_2_WEB.xml"},
        {"symbol": "BBB", "broadcast_Date": None, "qe_Date": "30-JUN-2026", "consolidated": "Standalone", "audited": "Un-Audited",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_3_WEB.xml"},
        {"symbol": "CCC", "broadcast_Date": "13-Aug-2026 20:45:00", "qe_Date": "30-JUN-2026", "consolidated": "Standalone", "audited": "Un-Audited",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_4_WEB.xml"},
        {"symbol": "DDD", "broadcast_Date": "13-Aug-2026 08:30:00", "qe_Date": "30-JUN-2026", "consolidated": "Standalone", "audited": "Un-Audited",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_5_WEB.xml"},
        {"symbol": "EEE", "broadcast_Date": "13-Aug-2026 16:00:00", "qe_Date": "30-JUN-2026", "consolidated": "Standalone", "audited": "Un-Audited",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/-"},
    ], "size": 500, "page": -1, "totalCount": 6}


XBRL = """<?xml version="1.0" encoding="UTF-8" standalone="no"?><xbrli:xbrl>
<in-capmkt:DateOfEndOfReportingPeriod contextRef="OneD">2026-06-30
</in-capmkt:DateOfEndOfReportingPeriod>
<in-capmkt:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated
</in-capmkt:NatureOfReportStandaloneConsolidated>
<in-capmkt:RevenueFromOperations contextRef="OneD" decimals="-5" unitRef="INR">13000000000
</in-capmkt:RevenueFromOperations>
<in-capmkt:RevenueFromOperations contextRef="FourD" decimals="-5" unitRef="INR">10000000000
</in-capmkt:RevenueFromOperations>
<in-capmkt:ProfitLossForPeriodAttributableToOwnersOfParent contextRef="OneD" unitRef="INR">999
</in-capmkt:ProfitLossForPeriodAttributableToOwnersOfParent>
<in-capmkt:ProfitLossForPeriod contextRef="OneD" decimals="-3" unitRef="INR">1800000000
</in-capmkt:ProfitLossForPeriod>
<in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare">18.00
</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>
</xbrli:xbrl>"""


def test_listing_parse_drops_unbroadcast_and_linkless_filings_and_keeps_ist_times():
    from nidp.services.tpd_model.results_live import parse_listing

    df = parse_listing(_listing())
    assert set(df["symbol"]) == {"AAA", "CCC", "DDD"}                     # BBB no broadcast time, EEE no XBRL link
    a = df[(df["symbol"] == "AAA") & df["consolidated"]].iloc[0]
    assert a["broadcast_at"] == pd.Timestamp(ist(T, 18, 5, 10)) and a["period_end"] == pd.Timestamp("2026-06-30")


def test_print_window_is_open_to_freeze_cutoff_on_T():
    from nidp.services.tpd_model.results_live import in_print_window, parse_listing

    df = in_print_window(parse_listing(_listing()), T)
    assert set(df["symbol"]) == {"AAA"}                                    # CCC after 20:30, DDD before the open


def test_xbrl_parse_takes_exact_tags_in_the_current_quarter_context():
    from nidp.services.tpd_model.results_live import parse_xbrl

    r = parse_xbrl(XBRL)
    assert r["period_end"] == pd.Timestamp("2026-06-30") and r["consolidated"] is True
    assert r["revenue_from_ops_cr"] == pytest.approx(1300.0)              # OneD, not the year-ago FourD column
    assert r["pat_cr"] == pytest.approx(180.0)                            # ProfitLossForPeriod, not the ...AttributableToOwners tag
    assert r["eps_basic"] == pytest.approx(18.0)
    assert parse_xbrl("<html>not xbrl</html>") is None


def test_live_rows_fill_gaps_without_overriding_stamped_warehouse_rows():
    from nidp.services.tpd_model.results_live import merge_live

    fin = pd.DataFrame([{"symbol": "AAA", "period_end": pd.Timestamp("2026-03-31"), "period_type": "quarterly", "consolidated": True,
                         "revenue_from_ops_cr": 1100.0, "pat_cr": 120.0, "eps_basic": 12.0, "broadcast_at": pd.Timestamp(ist(date(2026, 5, 10), 18, 0))},
                        {"symbol": "ZZZ", "period_end": pd.Timestamp("2026-06-30"), "period_type": "quarterly", "consolidated": True,
                         "revenue_from_ops_cr": 50.0, "pat_cr": 5.0, "eps_basic": 1.0, "broadcast_at": pd.Timestamp(ist(T, 17, 0))}])
    live = pd.DataFrame([{"symbol": "AAA", "period_end": pd.Timestamp("2026-06-30"), "consolidated": True, "revenue_from_ops_cr": 1300.0,
                          "pat_cr": 180.0, "eps_basic": 18.0, "broadcast_at": pd.Timestamp(ist(T, 18, 5))},
                         {"symbol": "ZZZ", "period_end": pd.Timestamp("2026-06-30"), "consolidated": True, "revenue_from_ops_cr": 999.0,
                          "pat_cr": 99.0, "eps_basic": 9.0, "broadcast_at": pd.Timestamp(ist(T, 17, 0))}])
    out = merge_live(fin, live)
    assert len(out) == 3 and out["source_live"].sum() == 1
    assert out.loc[(out["symbol"] == "ZZZ"), "pat_cr"].iloc[0] == 5.0                 # warehouse row kept
    new = out[(out["symbol"] == "AAA") & (out["period_end"] == pd.Timestamp("2026-06-30"))].iloc[0]
    assert new["period_type"] == "quarterly" and new["pat_cr"] == 180.0


def test_captured_print_feeds_the_results_print_block():
    from nidp.services.tpd_model.results_live import merge_live
    from nidp.services.tpd_model.results_print import results_print

    ends = [pd.Timestamp("2026-06-30") - pd.DateOffset(months=3 * k) + pd.offsets.QuarterEnd(0) for k in range(1, 5)]
    fin = pd.DataFrame([{"symbol": "AAA", "period_end": e, "period_type": "quarterly", "consolidated": True, "revenue_from_ops_cr": 1000.0,
                         "pat_cr": 100.0, "eps_basic": 10.0, "broadcast_at": pd.Timestamp(ist((e + pd.Timedelta(days=40)).date(), 18, 0))} for e in ends])
    live = pd.DataFrame([{"symbol": "AAA", "period_end": pd.Timestamp("2026-06-30"), "consolidated": True, "revenue_from_ops_cr": 1300.0,
                          "pat_cr": 180.0, "eps_basic": 18.0, "broadcast_at": pd.Timestamp(ist(T, 18, 5))}])
    f = results_print(merge_live(fin, live), ["AAA"], T).loc["AAA"]
    assert f["filed_today"] == 1.0 and f["filed_pat_yoy"] == pytest.approx(0.80) and f["filed_rev_yoy"] == pytest.approx(0.30)
