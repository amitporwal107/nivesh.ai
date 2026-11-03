"""TrueDataAdapter on the provider contract (AD-1, AD-2 in test_reports/truedata_client_TESTCASES.md). No network: the
client is a fake; the rows are SYNTHETIC."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td
from services.providers import contract as c
from services.providers.truedata_adapter import TrueDataAdapter


class FakeClient:
    configured = True

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def _reply(self, name, *args):
        self.calls.append((name, args))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def bars(self, *a):
        return self._reply("bars", *a)

    def bhavcopy(self, *a):
        return self._reply("bhavcopy", *a)

    def symbol_master(self, *a):
        return self._reply("symbol_master", *a)

    def corporate_actions(self, *a):
        return self._reply("corporate_actions", *a)


CREDS = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}
ON = mds.resolve({"source": "shadow"}, CREDS, integrated=True)                 # TrueData runs beside ours


def on():
    return ON


BARS = [{"timestamp": "2026-10-27", "open": 100.5, "high": 102, "low": 99.75, "close": 101.25, "volume": 1200},
        {"timestamp": "2026-10-28", "open": 101.25, "high": 103.4, "low": 100, "close": 103, "volume": 980}]


def test_reason_codes_match_the_contract():
    for name in ("NOT_CONFIGURED", "AUTH_EXPIRED", "RATE_LIMITED", "EMPTY_RESPONSE", "IDENTIFIER_NOT_RESOLVED",
                 "INVALID_PAYLOAD", "TOOL_SCHEMA_CHANGED", "PROVIDER_UNAVAILABLE", "PROVIDER_ERROR", "INVALID_REQUEST"):
        assert getattr(td, name) == getattr(c, name)
    assert td.RETRYABLE == c.RETRYABLE and td.PROVIDER_ID == c.PROVIDER_TRUEDATA == "truedata"


def test_ad1_successful_bars_is_a_normalized_result():
    fake = FakeClient(BARS)
    r = TrueDataAdapter(fake, switch=on).fetch_bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert isinstance(r, c.ProviderResult)
    assert (r.provider_id, r.provider_version, r.instrument_identifier) == ("truedata", td.CLIENT_VERSION, "AAAA")
    assert r.data_quality_status == c.DQ_OK and r.error_code is None and r.retryable is False
    assert r.normalized_records == BARS and r.source_timestamp == "2026-10-28"
    assert r.meta["price_adjustment"] == "ADJUSTED" and r.meta["series_type"] == "EOD" and r.meta["count"] == 2
    assert fake.calls == [("bars", ("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod", False))]
    d = r.to_dict()
    assert d["provider_id"] == "truedata" and d["data_quality_status"] == c.DQ_OK


@pytest.mark.parametrize("error,status,retryable", [
    (td.TrueDataError(td.EMPTY_RESPONSE, "TrueData getbars: No data exists for AAAA"), c.DQ_EMPTY, False),
    (td.TrueDataError(td.RATE_LIMITED, "TrueData getbars: rate limited"), c.DQ_BLOCKED, True),
    (td.TrueDataError(td.NOT_CONFIGURED, "TrueData credentials are not configured"), c.DQ_BLOCKED, False),
    (td.TrueDataError(td.PROVIDER_UNAVAILABLE, "TrueData getbhavcopy: HTTP 503"), c.DQ_BLOCKED, True),
])
def test_ad2_client_error_becomes_a_result_never_an_exception(error, status, retryable):
    a = TrueDataAdapter(FakeClient(error), switch=on)
    for r in (a.fetch_bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28)),
              a.fetch_bhavcopy("EQ", date(2026, 10, 28)),
              a.fetch_symbol_master("fo", "AAAA"),
              a.fetch_corporate_actions(date(2026, 10, 1), date(2026, 10, 28))):
        assert r.data_quality_status == status and r.error_code == error.code and r.retryable is retryable
        assert r.normalized_records == [] and r.meta["message"] == error.message


def test_ad2_empty_list_is_empty_response():
    r = TrueDataAdapter(FakeClient([]), switch=on).fetch_bhavcopy("fo", date(2026, 10, 28))
    assert r.data_quality_status == c.DQ_EMPTY and r.error_code == c.EMPTY_RESPONSE
    assert r.instrument_identifier == "FO:2026-10-28" and "traded contracts only" in r.meta["coverage"]


# ── SW-3 / SW-4: the switch decides ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("resolution,effective", [
    (mds.resolve({"source": "current"}, CREDS, integrated=True), "current"),                       # the way back
    (mds.resolve({"source": "shadow"}, {}, integrated=True), "current"),                      # no credentials
    (mds.resolve({"source": "truedata", "truedata_licence_confirmed": True},
                 {**CREDS, "MARKET_DATA_SOURCE_FORCE_CURRENT": "1"}, integrated=True), "current"),  # emergency
])
def test_sw3_switched_off_never_calls_truedata(resolution, effective):
    fake = FakeClient(BARS)
    a = TrueDataAdapter(fake, switch=lambda: resolution)
    for r in (a.fetch_bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28)),
              a.fetch_bhavcopy("EQ", date(2026, 10, 28)), a.fetch_symbol_master("eq"),
              a.fetch_corporate_actions(date(2026, 10, 1), date(2026, 10, 28))):
        assert r.data_quality_status == c.DQ_BLOCKED and r.error_code == c.NOT_CONFIGURED and r.retryable is False
        assert r.meta["switched_off"] is True and r.meta["market_data_source"] == effective
        assert "switched off" in r.meta["message"] and r.normalized_records == []
    assert fake.calls == []


def test_sw3_default_switch_is_the_committed_file():
    fake = FakeClient(BARS)
    r = TrueDataAdapter(fake).fetch_bhavcopy("EQ", date(2026, 10, 28))     # shipped file: current
    assert r.meta.get("switched_off") is True and fake.calls == []


@pytest.mark.parametrize("config", [{"source": "shadow"}, {"source": "truedata", "truedata_licence_confirmed": True}])
def test_sw4_switched_on_calls_truedata(config):
    fake = FakeClient(BARS)
    r = TrueDataAdapter(fake, switch=lambda: mds.resolve(config, CREDS, integrated=True)).fetch_bars(
        "AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28))
    assert r.data_quality_status == c.DQ_OK and len(fake.calls) == 1 and "switched_off" not in r.meta
