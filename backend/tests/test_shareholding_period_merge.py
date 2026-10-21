"""One row per quarter for the Chart tab's ownership block.

Staging 2026-10-19: RELIANCE's newest quarter held only a pledge figure (the pledge file), and
PERSISTENT had two rows for 30 Sep 2026 (exchange filing and screener); the screen took one
row and showed "—" for fields another row of the same quarter had.
"""
import asyncio
from unittest.mock import patch

from services.copilot_tools import company_financials as cf

# MOCK — not real data: shapes copied from the staging /v1/shareholding rows; values invented.
ROWS = [
    {"symbol": "TESTCO", "period_end": "2026-09-30", "promoter_pct": None, "promoter_pledged_pct": 6.0,
     "fii_pct": None, "dii_pct": None, "mf_pct": None, "public_pct": None, "source": "NSE_SHP"},
    {"symbol": "TESTCO", "period_end": "2026-09-30", "promoter_pct": 30.29, "promoter_pledged_pct": None,
     "fii_pct": 20.79, "dii_pct": 31.96, "mf_pct": None, "public_pct": 16.39, "source": "screener_in"},
    {"symbol": "TESTCO", "period_end": "2026-06-30", "promoter_pct": 30.0, "promoter_pledged_pct": None,
     "fii_pct": 21.0, "dii_pct": 30.0, "mf_pct": None, "public_pct": 18.0, "source": "screener_in"},
]


def test_a_pledge_only_row_does_not_hide_the_same_quarters_other_figures():
    async def fake(sym, limit=5):
        return list(ROWS)
    with patch("services.copilot_tools.daas_client.get_shareholding_history", fake):
        res = asyncio.run(cf.get_shareholding_analysis("testco"))
    assert res.ok
    latest = res.rows[0]
    assert len(res.rows) == 2 and latest["period_end"] == "2026-09-30"
    assert (latest["promoter_pct"], latest["fii_pct"], latest["dii_pct"]) == (30.29, 20.79, 31.96)
    assert latest["promoter_pledged_pct"] == 6.0          # the pledge from the other source is kept
    assert latest["mf_pct"] is None                       # nobody gave it: stays null, never filled


def test_the_first_source_wins_when_two_give_the_same_figure():
    rows = [dict(ROWS[0], promoter_pct=31.0), dict(ROWS[1])]
    assert cf._merge_periods(rows)[0]["promoter_pct"] == 31.0
