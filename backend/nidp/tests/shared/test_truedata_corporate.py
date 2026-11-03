"""TrueData corporate (financial results) client methods — TC-01..TC-05 of
test_reports/truedata_fundamentals_job_TESTCASES.md.

No network: a fake transport answers. Every payload is SYNTHETIC, shaped like TrueData's answers on 2 Nov 2026 (key
names and failure texts as seen); no vendor data.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from datetime import date

import pytest

from nidp.shared.sources import truedata as td

PASSWORD = "pw-S3CRET-corp"


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


class FakeCorp:
    """Answers corporate URLs. routes: endpoint name → (status, body) or a list (served in order, last repeats)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.tokens = 0

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers)})
        if url == td.AUTH_URL:
            self.tokens += 1
            return 200, json.dumps({"access_token": f"TOK-SECRET-{self.tokens}", "expires_in": 3600}).encode()
        name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        r = self.routes[name]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        status, body = r
        return status, (json.dumps(body) if isinstance(body, (dict, list)) else body).encode()

    def data_calls(self):
        return [c for c in self.calls if c["url"] != td.AUTH_URL]

    def query(self, i=-1):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.data_calls()[i]["url"]).query))


def client(fake, clock=None, min_interval=0.0):
    clock = clock or Clock()
    return td.TrueDataClient(td.Credentials("user", PASSWORD), transport=fake, min_interval=min_interval,
                             clock=clock.now, sleep=clock.sleep)


LIST = {"status": "Success", "Records": [
    {"id": 9000002, "file_time": "2026-10-08T22:05:59", "scripcode": "500001", "Symbol": "AAAA",
     "ReportingQuarter": "Second quarter", "company": "Aaaa Synthetic Ltd", "Audited": "Audited",
     "Nature": "Consolidated"},
    {"id": 9000003, "file_time": "2026-10-08T22:05:10", "scripcode": "500002", "Symbol": "B&amp;B",
     "ReportingQuarter": "Second quarter", "company": "B and B Synthetic Ltd", "Audited": "Unaudited",
     "Nature": "Standalone"}]}
AL = {"GeneralInfo": {"Symbol": "AAAA", "DateOfStartOfFinancialYear": "2026-04-01",
                      "DateOfEndOfFinancialYear": "2027-03-31", "LevelOfRoundingUsedInFinancialStatements": ""},
      "AllLiabilities": {}, "AllAssets": {}}
CF = {"GeneralInfo": {"ReportingStartDate": "2026-04-01", "ReportingEndDate": "2026-09-30"},
      "CashFlowSummary": {"CashFlowOperating": "100"}}
PL = {"GeneralInfo": {"Type": "Main/Ind", "ReportingStartDate": "2026-07-01", "ReportingEndDate": "2026-09-30"},
      "Income": {"Operating": {"RevenueFromOperations": 10.0}}, "PaidUpCapital": "5", "FaceValue": "1"}


# ── TC-01 result list ─────────────────────────────────────────────────────────────────────────────────────────

def test_tc01_result_list_hits_corporate_host_with_bearer_and_returns_records():
    fake = FakeCorp({"getResultList": (200, LIST)})
    recs = client(fake).result_list(date(2026, 10, 8))
    assert [r["id"] for r in recs] == [9000002, 9000003]
    assert recs[1]["Symbol"] == "B&amp;B"                       # passed through raw: the transform decodes it
    call = fake.data_calls()[0]
    assert call["url"].startswith("https://corporate.truedata.in/getResultList?")
    assert fake.query() == {"date": "2026-10-08", "response": "json"}
    assert call["headers"]["Authorization"] == "Bearer TOK-SECRET-1"


def test_tc01_result_list_empty_day_is_an_empty_list():
    fake = FakeCorp({"getResultList": (200, {"status": "Success", "Records": ""})})
    assert client(fake).result_list(date(2026, 10, 4)) == []


def test_tc01_result_list_records_not_a_list_is_schema_change():
    fake = FakeCorp({"getResultList": (200, {"status": "Success", "Records": {"id": 1}})})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).result_list(date(2026, 10, 4))
    assert e.value.code == td.TOOL_SCHEMA_CHANGED


# ── TC-02 JSON failure answers (HTTP 200) ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,code", [
    ("There is no row at position 0.", td.EMPTY_RESPONSE),
    ("Invalid Period, should be Yearly or Quarterly", td.INVALID_REQUEST),
    ("Invalid Type", td.INVALID_REQUEST),
    ("API calls quota exceeded! Please try after some time", td.RATE_LIMITED),
    ("Segment not subscribed", td.NOT_CONFIGURED),
    ("Something odd happened", td.PROVIDER_ERROR),
])
def test_tc02_json_status_failures_are_classified_never_data(status, code):
    fake = FakeCorp({"getResultALById": (200, {"status": status, "Records": ""})})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).balance_sheet(123)
    assert e.value.code == code
    assert e.value.retryable == (code in td.RETRYABLE)


def test_tc02_classify_json_status_success_and_statements_are_data():
    assert td.classify_json_status({"status": "Success", "Records": []}) is None
    assert td.classify_json_status(AL) is None                 # statements carry no status key
    assert td.classify_json_status([1, 2]) is None


def test_tc02_statement_without_general_info_is_schema_change():
    fake = FakeCorp({"getPnLById": (200, {"Income": {}})})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).pnl(1)
    assert e.value.code == td.TOOL_SCHEMA_CHANGED


# ── TC-03 one-line text, HTML, non-JSON ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body,code", [
    ("API calls quota exceeded! Your limit is 3600 calls per hour", td.RATE_LIMITED),
    ("Segment not subscribed", td.NOT_CONFIGURED),
    ('"Authorization has been denied for this request."', td.NOT_CONFIGURED),
    ("<!DOCTYPE html><html><body>Server Error</body></html>", td.PROVIDER_ERROR),
    ("not json at all", td.INVALID_PAYLOAD),
])
def test_tc03_text_failures(body, code):
    fake = FakeCorp({"getCashFlowDetailById": (200, body)})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).cash_flow(5)
    assert e.value.code == code


def test_tc03_http_errors():
    fake = FakeCorp({"getResultList": (503, "busy")})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).result_list(date(2026, 10, 8))
    assert e.value.code == td.PROVIDER_UNAVAILABLE
    fake = FakeCorp({"getResultList": (429, "")})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).result_list(date(2026, 10, 8))
    assert e.value.code == td.RATE_LIMITED


# ── TC-04 statement params, 401 refresh, rate gate ────────────────────────────────────────────────────────────

def test_tc04_statement_params():
    fake = FakeCorp({"getResultALById": (200, AL), "getCashFlowDetailById": (200, CF), "getPnLById": (200, PL)})
    c = client(fake)
    assert c.balance_sheet("2331084")["GeneralInfo"]["Symbol"] == "AAAA"
    assert fake.query() == {"id": "2331084", "response": "json"}
    c.cash_flow(2331084)
    assert fake.query() == {"id": "2331084", "response": "json", "cumulative": "true"}
    c.pnl(2331084, cumulative=False)
    assert fake.query() == {"id": "2331084", "response": "json", "cumulative": "false"}
    c.pnl(2331084)
    assert fake.query()["cumulative"] == "true"
    assert all(x["url"].startswith(td.CORPORATE + "/") for x in fake.data_calls())


def test_tc04_401_refreshes_the_token_once():
    fake = FakeCorp({"getResultALById": [(401, ""), (200, AL)]})
    c = client(fake)
    assert c.balance_sheet(1)["GeneralInfo"]
    assert fake.tokens == 2
    assert fake.data_calls()[-1]["headers"]["Authorization"] == "Bearer TOK-SECRET-2"


def test_tc04_rate_gate_spaces_corporate_calls():
    clock = Clock()
    fake = FakeCorp({"getResultALById": (200, AL)})
    c = client(fake, clock=clock, min_interval=1.2)
    for i in range(3):
        c.balance_sheet(i)
    assert clock.sleeps.count(1.2) >= 2                       # the 2nd and 3rd call waited a full interval


# ── TC-05 no secret anywhere ──────────────────────────────────────────────────────────────────────────────────

def test_tc05_no_password_or_token_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    texts = []
    for body in ('{"status": "Invalid Type", "Records": ""}', "Segment not subscribed", "garbage"):
        fake = FakeCorp({"getPnLById": (200, body)})
        with pytest.raises(td.TrueDataError) as e:
            client(fake).pnl(1)
        texts += [str(e.value), repr(e.value), e.value.message]
    texts.append(repr(td.Credentials("user", PASSWORD)))
    texts.append(caplog.text)
    for t in texts:
        assert PASSWORD not in t and "TOK-SECRET" not in t and "corporate.truedata.in/get" not in t
