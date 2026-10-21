"""nidp/services/macro_calendar: FRED maths, release matching, FOMC and RBI parsing, the MoSPI calendar layout, the service.

MOCK — not real data: every figure and text here is made up so each expected value can be checked by hand; the layouts of the
MoSPI PDF blocks, the Fed page and the RBI page copy what the real pages looked like on 2026-10-21. The real runs against FRED,
the Fed, MoSPI and RBI are in test_reports/desk_macro_calendar_backend_20261021.md.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from nidp.services.macro_calendar import catalog, fred_us as fu, india, service, writer

D = date


def payload(series, matrix):
    """An output_type=2 answer from {vintage: {obs: value}} (an observation row carries a key per vintage that knows it)."""
    obs = {}
    for v, col in matrix.items():
        for od, val in col.items():
            obs.setdefault(od, {})[f"{series}_{v.strftime('%Y%m%d')}"] = str(val)
    return {"observations": [{"date": od.isoformat(), **cols} for od, cols in sorted(obs.items())]}


# ── FRED: parsing and maths ──────────────────────────────────────────────────

def test_parse_vintage_matrix_reads_columns_and_drops_missing_values():
    p = {"observations": [{"date": "2026-08-01", "CPI_20260911": "334.98", "CPI_20261014": "334.98"},
                          {"date": "2026-09-01", "CPI_20261014": "336.94"},
                          {"date": "2026-07-01", "CPI_20260911": ".", "OTHER_20260911": "1"}]}
    m = fu.parse_vintage_matrix(p, "CPI")
    assert list(m) == [D(2026, 9, 11), D(2026, 10, 14)]
    assert m[D(2026, 9, 11)] == {D(2026, 8, 1): 334.98} and m[D(2026, 10, 14)] == {D(2026, 8, 1): 334.98, D(2026, 9, 1): 336.94}


def test_yoy_hand_example_uses_one_vintage():
    col = {D(2025, 9, 1): 320.0, D(2026, 8, 1): 331.0, D(2025, 8, 1): 318.0, D(2026, 9, 1): 332.8}
    assert fu.transform("yoy", col, D(2026, 9, 1)) == 4.0                      # 332.8 / 320 − 1
    assert fu.transform("yoy", col, D(2026, 8, 1)) == 4.09                     # 331 / 318 − 1 = 4.0881 %
    assert fu.transform("yoy", {D(2026, 9, 1): 1.0}, D(2026, 9, 1)) is None    # no year-ago value → None, not a guess


def test_change_level_and_mom():
    col = {D(2026, 7, 1): 1000.0, D(2026, 8, 1): 1100.0, D(2026, 9, 1): 1130.0}
    assert fu.transform("chg", col, D(2026, 9, 1)) == 30.0 and fu.transform("chg", col, D(2026, 8, 1)) == 100.0
    assert fu.transform("chg", col, D(2026, 7, 1)) is None
    assert fu.transform("level", {D(2026, 10, 10): 199000.0}, D(2026, 10, 10), 0.001) == 199.0      # claims: persons → thousands
    assert fu.transform("mom", {D(2026, 8, 1): 600000.0, D(2026, 9, 1): 604200.0}, D(2026, 9, 1)) == 0.7


def test_shift_months_clamps_the_day():
    assert fu.shift_months(D(2026, 3, 31), -1) == D(2026, 2, 28) and fu.shift_months(D(2026, 1, 15), -12) == D(2025, 1, 15)
    assert fu.shift_months(D(2026, 11, 1), 3) == D(2027, 2, 1)


@pytest.mark.parametrize("v,release,want", [(D(2026, 10, 14), D(2026, 10, 14), D(2026, 10, 14)), (D(2026, 10, 17), D(2026, 10, 14), D(2026, 10, 17)),
                                            (D(2026, 10, 21), D(2026, 10, 14), None)])
def test_match_vintage_within_five_days(v, release, want):
    assert fu.match_vintage([v], release) == want


def test_redact_hides_a_key_in_any_text():
    k = "0123456789abcdef0123456789abcdef"
    assert k not in fu.redact(f"GET https://api.stlouisfed.org/fred/x?series_id=A&api_key={k}&file_type=json failed")


# ── FRED: release rows ───────────────────────────────────────────────────────

CPI = catalog.US["US_CPI_YOY"]


def cpi_matrix():
    base = {D(2025, 7, 1): 320.0, D(2025, 8, 1): 325.0, D(2025, 9, 1): 330.0}
    aug = {**base, D(2026, 7, 1): 336.0, D(2026, 8, 1): 338.0}                        # published 2026-09-14
    sep = {**aug, D(2026, 9, 1): 343.2}                                              # published 2026-10-14
    return {D(2026, 9, 14): aug, D(2026, 10, 14): sep, D(2026, 10, 21): sep}


def test_cpi_rows_first_release_previous_as_known_then_the_scheduled_one():
    rows = fu.build_us_releases(CPI, cpi_matrix(), [D(2026, 9, 14), D(2026, 10, 14), D(2026, 11, 10), D(2026, 12, 10)], D(2026, 10, 21))
    assert [(r["release_date"], r["period"], r["previous"], r["actual"]) for r in rows] == [
        (D(2026, 9, 14), "Aug 2026", 5.0, 4.0),            # Aug: 338/325 − 1 = 4.0 %; previous Jul: 336/320 − 1 = 5.0 %, both from the 09-14 vintage
        (D(2026, 10, 14), "Sep 2026", 4.0, 4.0),           # Sep: 343.2/330 − 1 = 4.0 %; previous Aug is 4.0 % in the 10-14 vintage
        (D(2026, 11, 10), "Oct 2026", 4.0, None),
        (D(2026, 12, 10), "Nov 2026", None, None)]
    assert all(r["estimate"] is None and r["country"] == "US" and r["release_time"] == "08:30" for r in rows)


def test_a_date_with_no_vintage_and_a_revision_only_date_are_left_out():
    rows = fu.build_us_releases(CPI, cpi_matrix(), [D(2026, 8, 1), D(2026, 9, 14), D(2026, 10, 14), D(2026, 10, 19)], D(2026, 10, 21))
    assert [r["release_date"] for r in rows] == [D(2026, 9, 14), D(2026, 10, 14)]      # 08-01: no vintage; 10-19 → the 10-21 vintage, no new period


def test_a_release_due_today_but_not_in_fred_yet_has_no_actual():
    m = cpi_matrix()
    del m[D(2026, 10, 21)]                                                           # newest vintage is 2026-10-14
    rows = fu.build_us_releases(CPI, m, [D(2026, 10, 14), D(2026, 10, 21)], D(2026, 10, 21))
    assert rows[-1]["release_date"] == D(2026, 10, 21) and rows[-1]["actual"] is None and rows[-1]["period"] == "Oct 2026"


def test_gdp_stages_and_the_next_quarter():
    gdp = catalog.US["US_GDP_QOQ"]
    q1, q2 = D(2026, 1, 1), D(2026, 4, 1)
    m = {D(2026, 8, 27): {q1: 2.5, q2: 3.0}, D(2026, 9, 25): {q1: 2.5, q2: 3.2}, D(2026, 10, 29): {q1: 2.5, q2: 3.1}}
    rows = fu.build_us_releases(gdp, m, [D(2026, 8, 27), D(2026, 9, 25), D(2026, 10, 29), D(2026, 11, 25)], D(2026, 10, 29))
    assert [(r["period"], r["previous"], r["actual"]) for r in rows[:3]] == [
        ("Q2 2026 (advance)", 2.5, 3.0), ("Q2 2026 (second)", 2.5, 3.2), ("Q2 2026 (third)", 2.5, 3.1)]
    assert (rows[3]["period"], rows[3]["previous"], rows[3]["actual"]) == ("Q3 2026 (advance)", 3.1, None)     # previous = the latest Q2 figure


def test_gdp_scheduled_estimates_continue_the_stage_order():
    gdp = catalog.US["US_GDP_QOQ"]
    q1, q2 = D(2026, 1, 1), D(2026, 4, 1)
    m = {D(2026, 8, 27): {q1: 2.5, q2: 3.0}}
    rows = fu.build_us_releases(gdp, m, [D(2026, 8, 27), D(2026, 9, 25), D(2026, 10, 29), D(2026, 11, 25)], D(2026, 9, 1))
    assert [r["period"] for r in rows] == ["Q2 2026 (advance)", "Q2 2026 (second)", "Q2 2026 (third)", "Q3 2026 (advance)"]
    assert rows[1]["previous"] == 2.5 and rows[2]["previous"] is None


def test_weekly_claims_scale_label_and_period():
    cl = catalog.US["US_JOBLESS_CLAIMS"]
    m = {D(2026, 10, 15): {D(2026, 10, 3): 197000.0, D(2026, 10, 10): 199000.0}}
    rows = fu.build_us_releases(cl, m, [D(2026, 10, 15), D(2026, 10, 22)], D(2026, 10, 15))
    assert (rows[0]["period"], rows[0]["previous"], rows[0]["actual"], rows[0]["unit"]) == ("Week ending 10 Oct", 197.0, 199.0, "K")
    assert rows[1]["period"] == "Week ending 17 Oct" and rows[1]["previous"] == 199.0 and rows[1]["actual"] is None


# ── FOMC ─────────────────────────────────────────────────────────────────────

FOMC_PAGE = """<h4>2026 FOMC Meetings</h4> January 27-28 Statement: PDF Minutes: PDF | HTML (Released February 18, 2026)
 March 17-18* Statement April 28-29 Statement June 16-17* September 15-16 October 27-28 December 8-9*
 <h4>2025 FOMC Meetings</h4> January 28-29 December 9-10*  <h4>2027 FOMC Meetings</h4> April 27-28 June 29-30"""


def test_parse_fomc_takes_the_second_day_of_each_meeting_in_the_years_asked():
    got = fu.parse_fomc_meetings(FOMC_PAGE, (2026,))
    assert got == [D(2026, 1, 28), D(2026, 3, 18), D(2026, 4, 29), D(2026, 6, 17), D(2026, 9, 16), D(2026, 10, 28), D(2026, 12, 9)]
    assert fu.parse_fomc_meetings("<h4>2026 FOMC Meetings</h4> April 30-May 1", (2026,)) == [D(2026, 5, 1)]
    assert fu.parse_fomc_meetings("nothing here", (2026,)) == []


def test_fomc_actual_is_the_rate_the_day_after_and_previous_the_day_before():
    target = {D(2026, 9, 15): 3.75, D(2026, 9, 17): 4.0, D(2026, 10, 20): 4.0}
    rows = fu.build_fomc_releases([D(2026, 9, 16), D(2026, 10, 28), D(2026, 12, 9)], target, D(2026, 10, 21))
    assert (rows[0]["previous"], rows[0]["actual"], rows[0]["period"], rows[0]["release_time"]) == (3.75, 4.0, "Sep meeting", "14:00")
    assert (rows[1]["previous"], rows[1]["actual"]) == (4.0, None)                  # the next meeting: previous = the rate in force now
    assert (rows[2]["previous"], rows[2]["actual"]) == (None, None)


def test_fomc_decision_today_or_not_yet_in_fred_has_no_actual():
    rows = fu.build_fomc_releases([D(2026, 10, 21)], {D(2026, 10, 20): 4.0}, D(2026, 10, 21))
    assert rows[0]["actual"] is None


# ── MoSPI calendar layout ────────────────────────────────────────────────────

def blk(x, y, text):
    return (x, y, x + 100.0, y + 14.0, text)


PAGE = [
    blk(122.5, 70.3, "Date of"), blk(192.2, 70.3, "Data Release / Publication \nPress Release Link"),            # header
    blk(52.9, 227.7, "6 \nSep \n2026"),                                                                         # month/year cell
    blk(119.9, 227.3, "12th Sep All India Consumer Price Index"), blk(176.8, 241.6, "(CPI)"),
    blk(368.0, 225.0, "Released on 14th  September, 2026 \n \nhttps://www.pib.gov.in/x"),                       # a row moved from the 12th
    blk(119.9, 412.4, "28th Sep All India Index of Industrial"), blk(176.8, 426.7, "Production (IIP)"),
    blk(368.0, 410.0, "Released on 28th  September, 2026 \n \nhttps://www.pib.gov.in/y"),
    blk(119.9, 474.2, "29th Sep Index of Services Production"), blk(176.8, 488.4, "(ISP)"),
    blk(119.9, 597.5, "12th Oct \nAll India Consumer Price Index \n(CPI) \n"),
    blk(119.9, 629.6, "15th Oct \nMonthly Bulletin of PLFS – Sep \n2026 \n"),                                    # a year inside the title
    blk(119.9, 661.7, "7thJan \nFirst Advance Estimates of GDP \nfor FY 2026-27"),                              # no space; a year in the title
    blk(322.4, 744.7, "Advance Release Calendar 2026-27/ Page 5 of 8"),                                           # footer
]


def test_mospi_rows_dates_titles_release_overrides_and_no_footer_leak():
    ents = india.parse_mospi_calendar([PAGE], 2026)
    assert [(str(d), str(r) if r else None) for d, t, r in ents] == [
        ("2026-09-12", "2026-09-14"), ("2026-09-28", "2026-09-28"), ("2026-09-29", None), ("2026-10-12", None), ("2026-10-15", None), ("2027-01-07", None)]
    titles = [t for _, t, _ in ents]
    assert titles[0] == "All India Consumer Price Index (CPI)" and titles[1] == "All India Index of Industrial Production (IIP)"
    assert "Page 5" not in titles[-1] and titles[-1] == "First Advance Estimates of GDP for FY 2026-27"


def test_mospi_keeps_only_cpi_iip_gdp_and_plfs_with_the_release_date_and_period():
    rows = india.build_mospi_releases(india.parse_mospi_calendar([PAGE], 2026), 2026)
    assert [(str(r["release_date"]), r["indicator_code"], r["period"]) for r in rows] == [
        ("2026-09-14", "IN_CPI", "Aug 2026"), ("2026-09-28", "IN_IIP", "Aug 2026"), ("2026-10-12", "IN_CPI", "Sep 2026"),
        ("2026-10-15", "IN_PLFS", "Sep 2026"), ("2027-01-07", "IN_GDP", "FY 2026-27 (first advance)")]
    r0 = rows[0]
    assert "planned 12 Sep, released 14 Sep" in r0["source"] and r0["source_url"] == catalog.MOSPI_CALENDAR_URL
    assert (r0["actual"], r0["previous"], r0["estimate"], r0["release_time"], r0["release_tz"]) == (None, None, None, "16:00", "Asia/Kolkata")
    assert rows[3]["release_time"] is None                                                                      # PLFS: no usual time


@pytest.mark.parametrize("title,want", [
    ("All India Consumer Price Index (CPI)", ("IN_CPI", "Sep 2026")),
    ("CPI for Rural Labourers Consumer Price Index Labour", None),
    ("Quarterly Estimates of GDP for Q2, FY 2026-27", ("IN_GDP", "Q2 FY2026-27")),
    ("Provisional Estimates of Gross Domestic Product (GDP) for FY 2025-26 Quarterly Estimates of GDP for Q4, FY 2025-26", ("IN_GDP", "Q4 FY2025-26")),
    ("Quarterly Bulletin of PLFS for the Quarter July – Sep 2026", None),
    ("Index of Services Production (ISP)", None),
    ("Flash Report- Sep 2026 (For projects costing Rs. 150 crore and above)", None),
])
def test_classify_title(title, want):
    assert india.classify_title(title, D(2026, 10, 12)) == want


def test_an_early_month_iip_row_gets_no_period_rather_than_a_wrong_one():
    rows = india.build_mospi_releases([(D(2026, 6, 1), "All India Index of Industrial Production (IIP)", None)], 2026)
    assert rows[0]["period"] is None


def test_fiscal_year_is_read_from_the_first_page_and_months_roll_into_the_next_year():
    assert india.parse_fy_start("ADVANCE RELEASE CALENDAR (2026-27) Ministry") == 2026 and india.parse_fy_start("nothing") is None
    ents = india.parse_mospi_calendar([[blk(119.9, 100.0, "12th Mar All India Consumer Price Index")]], 2026)
    assert ents[0][0] == D(2027, 3, 12)


# ── RBI ──────────────────────────────────────────────────────────────────────

RBI_PAGE = """<html><body><h1>Meeting Schedule</h1><p>Dates of meetings of Monetary Policy Committee for 2026-27</p>
<p>April 6, 7 and 8, 2026</p><p>June 3, 4 and 5, 2026</p><p>August 3, 4 and 5, 2026</p><p>October 5, 6 and 7, 2026</p>
<p>December 2, 3 and 4, 2026</p><p>February 3, 4 and 5, 2027</p><p>(Brij Raj)</p></body></html>"""
RBI_HOME = "<div>1. Current Rates Policy&nbsp; Rates Policy Repo Rate : 5.50% Standing Deposit Facility Rate : 5.25%</div>"


def test_rbi_mpc_decision_is_the_last_day_of_each_meeting():
    assert india.parse_rbi_mpc(RBI_PAGE) == [D(2026, 4, 8), D(2026, 6, 5), D(2026, 8, 5), D(2026, 10, 7), D(2026, 12, 4), D(2027, 2, 5)]
    assert india.parse_rbi_mpc("<p>some other press release April 6, 7 and 8, 2026</p>") == []


def test_rbi_repo_rate_or_none():
    assert india.parse_rbi_repo(RBI_HOME) == 5.5 and india.parse_rbi_repo("<p>no rates</p>") is None


def test_rbi_only_the_latest_decision_gets_the_current_rate():
    ds = india.parse_rbi_mpc(RBI_PAGE)
    rows = india.build_rbi_releases(ds, 5.5, D(2026, 10, 21))
    assert [r["actual"] for r in rows] == [None, None, None, 5.5, None, None]
    assert rows[3]["period"] == "Oct meeting" and rows[3]["release_time"] == "10:00" and rows[3]["source_url"] == catalog.RBI_MPC_SCHEDULE_URL
    assert all(r["actual"] is None for r in india.build_rbi_releases(ds, None, D(2026, 10, 21)))          # no rate read → no figure, no default
    assert all(r["actual"] is None for r in india.build_rbi_releases(ds, 5.5, D(2026, 3, 1)))             # no decision has happened yet


# ── writer and service ───────────────────────────────────────────────────────

def test_writer_arguments_match_the_sql_placeholders_and_a_null_never_erases():
    row = catalog.make_row(CPI, D(2026, 10, 14), "Sep 2026", 3.4, 3.74, "FRED", "u")
    import uuid
    args = writer._args(row, uuid.uuid4())
    assert len(args) == 17 and "$17" in writer.UPSERT_SQL and "$18" not in writer.UPSERT_SQL
    assert "actual = COALESCE(EXCLUDED.actual" in writer.UPSERT_SQL and "ON CONFLICT (indicator_code, release_date)" in writer.UPSERT_SQL


class FakeRun:
    instances = []

    def __init__(self, ingester, target_date=None, source_url=None):
        import uuid
        self.run_id = uuid.uuid4()
        self.metadata, self.status, self.error = {}, None, None
        self.rows_fetched = self.rows_inserted = self.rows_skipped = 0
        FakeRun.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def finalize(self, status, error_message=None):
        self.status, self.error = status, error_message


@pytest.fixture
def svc(monkeypatch):
    FakeRun.instances = []
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setattr(service, "JobRun", FakeRun)

    async def _up(rows, run_id):
        return len(rows)
    monkeypatch.setattr(service, "upsert_releases", _up)

    def _collect(rows, failures):
        async def c(today=None):
            return rows, failures
        monkeypatch.setattr(service, "collect", c)
    return _collect


ROW = catalog.make_row(CPI, D(2026, 10, 14), "Sep 2026", 3.4, 3.74, "FRED", "u")


@pytest.mark.parametrize("rows,failures,status", [([ROW], [], "OK"), ([ROW], ["MoSPI calendar: X"], "PARTIAL"), ([], ["a", "b"], "FAILED")])
def test_run_status_ok_partial_failed(svc, rows, failures, status):
    svc(rows, failures)
    asyncio.run(service.run(None))
    r = FakeRun.instances[0]
    assert r.status == status and r.rows_inserted == len(rows) and r.metadata["failures"] == failures


def test_a_missing_fred_key_fails_before_any_job_row_is_opened(monkeypatch):
    FakeRun.instances = []
    monkeypatch.setattr(service, "JobRun", FakeRun)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY_FILE", raising=False)
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        asyncio.run(service.run(None))
    assert FakeRun.instances == []


def test_the_key_can_come_from_a_file(monkeypatch, tmp_path):
    f = tmp_path / "k"
    f.write_text("abc123\nignored\n")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("FRED_API_KEY_FILE", str(f))
    assert service.fred_key() == "abc123"


def test_one_source_failing_does_not_stop_the_others(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)

    async def us(session, key, today):
        return [], ["US_CPI_YOY: RuntimeError FRED boom"]

    async def inn(session, today):
        return [ROW], []
    monkeypatch.setattr(service.fred_us, "collect_us", us)
    monkeypatch.setattr(service.india, "collect_india", inn)
    rows, failures = asyncio.run(service.collect(D(2026, 10, 21)))
    assert rows == [ROW] and failures == ["US_CPI_YOY: RuntimeError FRED boom"]
