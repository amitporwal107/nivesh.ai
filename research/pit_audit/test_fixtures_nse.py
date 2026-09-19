"""Fixture tests on real NSE documents captured 2026-09-19 (NSE-01, NSE-02, QA-01).

Hand-read values (from the raw XBRL facts, recorded before these tests were written):
- legacy Reg-33, NH (Narayana Hrudayalaya) Q2 FY25 consolidated, context OneD (2024-07-01..2024-09-30):
  RevenueFromOperations 14000050000 INR = 1400.005 cr; ProfitLossForPeriod 1987980000 = 198.798 cr; basic EPS 9.78.
  Year-to-date context FourD (reported 2024-04-01..2024-09-30, but its <context> DECLARES 07-01..09-30):
  revenue 2740.957 cr, PAT 400.292 cr, EPS 19.70 - must never be returned as the quarter.
- Integrated Filing, SEJALLTD Q1 FY27 consolidated, OneD (2026-04-01..2026-06-30): revenue 1179489000 = 117.9489 cr;
  PAT 72160000 = 7.216 cr; basic EPS 6.27.
- Banking taxonomy, IDFCFIRSTB Q2 FY25 standalone, OneD (2024-07-01..2024-09-30), BANKING_113533_1289890_26102024052655
  (listing broadCastDate 26-Oct-2024 17:26:55): ProfitLossForThePeriod 2006900000 = 200.69 cr; basic EPS after
  extraordinary items 0.27; InterestEarned 89569300000 = 8956.93 cr; Income 106842300000 = 10684.23 cr; no
  RevenueFromOperations tag at all.
- SHP 3MINDIA, ShareholdingAsAPercentageOfTotalNumberOfShares: Sep-24 (older format, percent): promoter 75, FII 4.07,
  DII 8.15, MF 7.14, public 25. Jun-26 (current format, fractions): promoter 0.75, FII 0.035, DII 0.0816, MF 0.0726,
  public 0.25. HINDUNILVR Jun-25 transition filing (current contexts, PERCENT values): promoter 61.90, FII 10.18,
  DII 16.07, MF 6.57, public 38.10.
"""
import datetime as dt
import json
import os

import pytest

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "raw")
D = dt.date


def _read(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()


def test_legacy_quarter_not_ytd():
    import xbrl_extract as X
    r = X.extract(_read("legacy_sample_NH.xml"), D(2024, 7, 1), D(2024, 9, 30))
    assert r["status"] == "OK"
    [row] = [x for x in r["rows"] if x["basis"] == "CONSOLIDATED"]
    assert row["context"] == "OneD"
    assert row["revenue_cr"] == pytest.approx(1400.005) and row["pat_cr"] == pytest.approx(198.798)
    assert row["eps_basic"] == pytest.approx(9.78) and row["tags_used"]["pat_cr"] == "ProfitLossForPeriod"
    assert row["total_income_cr"] == pytest.approx(1423.608) and row["pat_owners_cr"] == pytest.approx(198.633)


def test_legacy_ytd_is_reachable_only_by_its_reported_period():
    import xbrl_extract as X
    r = X.extract(_read("legacy_sample_NH.xml"), D(2024, 4, 1), D(2024, 9, 30))
    [row] = [x for x in r["rows"] if x["basis"] == "CONSOLIDATED"]
    assert row["context"] == "FourD" and row["revenue_cr"] == pytest.approx(2740.957)


def test_integrated_quarter():
    import xbrl_extract as X
    r = X.extract(_read("integrated_sample_SEJALLTD.xml"), D(2026, 4, 1), D(2026, 6, 30))
    assert r["status"] == "OK"
    [row] = r["rows"]
    assert row["basis"] == "CONSOLIDATED" and row["revenue_cr"] == pytest.approx(117.9489)
    assert row["pat_cr"] == pytest.approx(7.216) and row["eps_basic"] == pytest.approx(6.27)
    assert row["total_income_cr"] == pytest.approx(119.4361) and row["pat_owners_cr"] == pytest.approx(7.1422)


def test_wrong_period_and_garbage_are_explicit():
    import xbrl_extract as X
    assert X.extract(_read("integrated_sample_SEJALLTD.xml"), D(2026, 1, 1), D(2026, 3, 31))["status"] == "UNRESOLVED"
    assert X.extract(b"not xml at all", D(2026, 4, 1), D(2026, 6, 30))["status"] == "UNPARSEABLE"


def test_existing_parser_deficiency_def6_documented():
    """The reused NIDP parser returns pat_cr=None on this taxonomy (DEF-6); the audit extractor does not."""
    import xbrl_extract as X
    rows = X.P.parse_xbrl_document(_read("legacy_sample_NH.xml"), {"symbol": "NH", "period_end": "2024-09-30",
                                                                     "period_start": "2024-07-01", "consolidated": True})
    assert rows and rows[0].get("pat_cr") is None and rows[0]["revenue_from_ops_cr"] == pytest.approx(1400.005)


def test_listing_raw_fields_present():
    """The raw listing rows carry the timestamps the audit must keep (NSE-02)."""
    leg = json.loads(_read("legacy_quarterly_2024-10.json"))
    leg = leg if isinstance(leg, list) else leg["data"]
    assert {"broadCastDate", "exchdisstime", "filingDate", "seqNumber", "reInd", "isin", "consolidated"} <= set(leg[0])
    integ = json.loads(_read("integrated_2026-07.json"))
    integ = integ if isinstance(integ, list) else integ["data"]
    assert {"broadcast_Date", "creation_Date", "revised_Date", "type_Sub", "seq_Id", "qe_Date"} <= set(integ[0])
    shp = json.loads(_read("shareholding_master_APARINDS.json"))
    shp = shp if isinstance(shp, list) else shp["data"]
    assert {"broadcastDate", "submissionDate", "systemDate", "date", "revisedStatus", "recordId", "xbrl"} <= set(shp[0])


def test_record_builders_keep_raw_and_split_timestamps():
    import nse_ground_truth as G
    leg = json.loads(_read("legacy_quarterly_2024-10.json"))
    leg = leg if isinstance(leg, list) else leg["data"]
    r = G.legacy_record(leg[0], "https://www.nseindia.com/api/x", "2026-09-19T12:00:00+05:30")
    assert r["raw_row"] == leg[0] and r["raw_row_sha256"]
    assert r["submitted_at"] == "2024-10-31T20:36:00+05:30"            # filingDate (minute)
    assert r["broadcast_at"] == "2024-10-31T20:36:01+05:30"            # broadCastDate
    assert r["exchange_disseminated_at"] == "2024-10-31T20:36:18+05:30"  # exchdisstime
    assert r["consolidation_type"] == "STANDALONE" and r["period_end"] == "2024-09-30" and r["period_start"] == "2024-07-01"
    assert r["revision_flag"] == "UNKNOWN" and r["raw_row"]["reInd"] in ("N", "F", "A")  # F-4: reInd is a format code
    integ = json.loads(_read("integrated_2026-07.json"))
    integ = integ if isinstance(integ, list) else integ["data"]
    i = G.integrated_record(integ[0], "u", "2026-09-19T12:00:00+05:30")
    assert i["broadcast_at"] == "2026-07-31T22:29:04+05:30" and i["submitted_at"] == "2026-07-31T22:29:06+05:30"
    assert i["period_end"] == "2026-06-30" and i["period_start"] == "2026-04-01" and i["revision_flag"] == "ORIGINAL"
    rev = [x for x in integ if x.get("revised_Date")]
    if rev:  # revisions carry no broadcast date (DEF-4): never invented
        rr = G.integrated_record(rev[0], "u", "t")
        assert rr["revised_at"] is not None and rr["revision_flag"] != "ORIGINAL"
    shp = json.loads(_read("shareholding_master_APARINDS.json"))
    shp = shp if isinstance(shp, list) else shp["data"]
    s = G.shareholding_record(shp[0], "u", "t")
    assert s["broadcast_at"] == "2026-08-20T15:13:12+05:30"       # second precision
    assert s["submitted_at"] == "2026-08-20T00:00:00+05:30"       # day precision, kept separate (DEF-1 avoided)
    assert s["period_end"] == "2026-08-13"


def test_windows_and_quarter_start():
    import nse_ground_truth as G
    w = list(G.windows(D(2025, 1, 1), D(2025, 3, 31)))
    assert w[0] == (D(2025, 1, 1), D(2025, 1, 30)) and w[-1][1] == D(2025, 3, 31)
    assert all((b - a).days < 30 for a, b in w)
    assert G.quarter_start(D(2026, 6, 30)) == D(2026, 4, 1) and G.quarter_start(D(2025, 3, 31)) == D(2025, 1, 1)
    assert G.quarter_start(D(2024, 12, 31)) == D(2024, 10, 1)


def test_banking_taxonomy_has_pat_and_eps_but_no_revenue():
    import xbrl_extract as X
    r = X.extract(_read("banking_sample_IDFCFIRSTB.xml"), D(2024, 7, 1), D(2024, 9, 30))
    [row] = [x for x in r["rows"] if x["basis"] == "STANDALONE"]
    assert row["pat_cr"] == pytest.approx(200.69) and row["tags_used"]["pat_cr"] == "ProfitLossForThePeriod"
    assert row["eps_basic"] == pytest.approx(0.27)
    assert row["interest_earned_cr"] == pytest.approx(8956.93) and row["total_income_cr"] == pytest.approx(10684.23)
    assert row.get("revenue_cr") is None          # never substituted by interest earned or total income


def test_filename_clock_is_ambiguous_unless_hour_proves_24h():
    from session import filename_ts, filename_ts_candidates, filename_ts_precision
    import nse_ground_truth as G
    bank = "https://nsearchives.nseindia.com/corporate/xbrl/BANKING_113533_1289890_26102024052655.xml"
    assert filename_ts(bank).hour == 5 and filename_ts_precision(bank) == "ambiguous_12h"
    assert [t.hour for t in filename_ts_candidates(bank)] == [5, 17]   # broadcast was 17:26:55
    noon = "https://x/INDAS_113469_1289442_26102024121843.xml"          # broadcast was 00:18:43
    assert [t.hour for t in filename_ts_candidates(noon)] == [0, 12]
    evening = "https://x/INTEGRATED_FILING_INDAS_181410_31072026222906_iXBRL.html"
    assert filename_ts_precision(evening) == "second" and len(filename_ts_candidates(evening)) == 1
    assert G._created(bank) is None and G._created(evening) == "2026-07-31T22:29:06+05:30"


def test_placeholder_document_url_is_not_a_document():
    import nse_ground_truth as G
    assert not G.has_document("https://nsearchives.nseindia.com/corporate/xbrl/-")
    assert not G.has_document(None) and not G.has_document("-")
    assert G.has_document("https://nsearchives.nseindia.com/corporate/xbrl/SHP_1_17072026063501_WEB.xml")


def test_total_eps_is_a_separate_definition():
    import xbrl_extract as X
    r = X.extract(_read("integrated_sample_SEJALLTD.xml"), D(2026, 4, 1), D(2026, 6, 30))
    [row] = r["rows"]
    assert row["eps_basic_total"] == pytest.approx(6.27)      # no discontinued operations: equal to continuing EPS
    assert X.METRICS["pat_cr"][0] == "ProfitLossForPeriod"    # Ind-AS tag keeps priority over bank / insurance tags


@pytest.mark.parametrize("name, fmt, expected", [
    ("shp_old_3MINDIA_2024-09.xml", "pre_2025", {"promoter_pct": 75, "fii_pct": 4.07, "dii_pct": 8.15, "mf_pct": 7.14, "public_pct": 25}),
    ("shp_new_3MINDIA_2026-06.xml", "current", {"promoter_pct": 75, "fii_pct": 3.5, "dii_pct": 8.16, "mf_pct": 7.26, "public_pct": 25}),
    ("shp_transition_HINDUNILVR_2025-06.xml", "current",
     {"promoter_pct": 61.90, "fii_pct": 10.18, "dii_pct": 16.07, "mf_pct": 6.57, "public_pct": 38.10}),
])
def test_shp_reader_both_formats(name, fmt, expected):
    import shp_extract as S
    r = S.extract(_read(name))
    assert r["status"] == "OK" and r["format"] == fmt
    assert r["values"] == pytest.approx(expected)


def test_nidp_shp_parser_deficiencies_documented():
    """DEF-8 (older format -> no rows) and DEF-9 (mf_pct never set) in the NIDP parser, which the audit does not modify."""
    from nidp.services.nse_shareholding import parser as SH
    m = {"symbol": "3MINDIA", "period_end": "2024-09-30", "filing_id": "x", "xbrl_url": "u", "broadcast_at": None}
    assert SH.parse_xbrl_document(_read("shp_old_3MINDIA_2024-09.xml"), m) == []
    rows = SH.parse_xbrl_document(_read("shp_new_3MINDIA_2026-06.xml"), dict(m, period_end="2026-06-30"))
    assert rows and rows[0].get("mf_pct") is None and rows[0]["promoter_pct"] == pytest.approx(75)


def test_shp_reader_rejects_inconsistent_totals():
    import shp_extract as S
    body = _read("shp_new_3MINDIA_2026-06.xml").replace(b">0.25<", b">0.35<", 1)
    r = S.extract(body)
    assert r["status"] == "UNRESOLVED" and "residual" in r["reason"]
    assert S.extract(_read("shp_transition_HINDUNILVR_2025-06.xml"))["scale"] == "percent"
    assert S.extract(_read("shp_new_3MINDIA_2026-06.xml"))["scale"] == "fraction"


def test_request_log_counts_rate_limits_from_status_not_from_url_digits(tmp_path):
    from archive import Archive
    import nse_ground_truth as G
    log = G.RequestLog(Archive(str(tmp_path)), "t")
    log.record("k", "https://x/ad5cd683-9403-4290.pdf", False, None, None, 0.0,
               "ClientError: failed (last status 404, last err HTTP 404): https://x/ad5cd683-9403-4290.pdf")
    assert log.counts["rate_limit_count"] == 0
    log.record("k", "u", True, None, None, 0.0, "ClientError: failed (last status 429, last err HTTP 429)")
    assert log.counts["rate_limit_count"] == 1
