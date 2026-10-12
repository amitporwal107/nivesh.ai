"""services/providers/* + routes/research_providers.py (TC-1..TC-33 in
test_reports/provider_foundations_20261012.md). No network, no real Mongo.

Trendlyne: an httpx.MockTransport replays RECORDED live MCP responses (tests/fixtures/trendlyne_mcp/
recorded_20261012.json, captured from Trendlyne-Financial-Server 3.1.1) in the server's own SSE
framing, so the adapter's transport, schema check and parsers all run for real. Kite: a fake
KiteConnect object stands in for the SDK; chunking, retry and normalization run for real.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
import routes.research_providers as rp
from services.providers import contract as c
from services.providers import kite_adapter as ka
from services.providers import request_log
from services.providers import trendlyne_adapter as ta

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "trendlyne_mcp" / "recorded_20261012.json").read_text())
CALLS = FIXTURE["calls"]
SECRET_URL = "https://mcp.example.test/mcp/?token=SECRETTOKEN123"
KITE_TOKEN = "KITEACCESSTOKEN456"
IST = timezone(timedelta(hours=5, minutes=30))
USERS = {"a": {"user_id": "u_a", "email": "a@example.com", "role": "user"},
         "other": {"user_id": "u_o", "email": "other@example.com", "role": "user"}}


def run(coro):
    return asyncio.run(coro)


# ── Trendlyne harness ────────────────────────────────────────────────────
class McpServer:
    """Replays recorded tool results. `tools` and `results` can be replaced per test."""

    def __init__(self, results=None, tools=None, status=200):
        self.tools = copy.deepcopy(FIXTURE["tools_list"]) if tools is None else tools
        self.results = results or {}
        self.status = status
        self.calls: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.status != 200:
            return httpx.Response(self.status, text="<html>nope</html>")
        msg = json.loads(request.content)
        self.calls.append((msg["method"], msg.get("params") or {}))
        if msg["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26", "serverInfo": {"name": "Trendlyne-Financial-Server", "version": "3.1.1"}}
        elif msg["method"] == "tools/list":
            result = self.tools
        else:
            result = self.results[msg["params"]["name"]]
        body = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    @property
    def tool_calls(self):
        return [p for m, p in self.calls if m == "tools/call"]


def tl(server: McpServer, url=SECRET_URL) -> ta.TrendlyneResearchAdapter:
    return ta.TrendlyneResearchAdapter(url_getter=lambda: url, transport=httpx.MockTransport(server.handler))


def text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False, "structuredContent": {"result": text}}


# ── Kite harness ─────────────────────────────────────────────────────────
class KiteError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class TokenException(KiteError):
    pass


class NetworkException(KiteError):
    pass


INSTRUMENTS = [
    {"instrument_token": 408065, "exchange_token": "1594", "tradingsymbol": "INFY", "name": "INFOSYS", "exchange": "NSE",
     "segment": "NSE", "instrument_type": "EQ", "lot_size": 1, "tick_size": 0.05},
    {"instrument_token": 256265, "exchange_token": "1001", "tradingsymbol": "NIFTY 50", "name": "NIFTY 50", "exchange": "NSE",
     "segment": "INDICES", "instrument_type": "EQ", "lot_size": 0, "tick_size": 0},
]


def bar(day: date, o=100.0, h=105.0, low=99.0, cl=104.0, v=1000):
    return {"date": datetime(day.year, day.month, day.day, tzinfo=IST), "open": o, "high": h, "low": low, "close": cl, "volume": v}


class FakeKite:
    def __init__(self, history=None, instruments=None):
        self._history = history if history is not None else (lambda **kw: [bar(kw["from_date"])])
        self._instruments = INSTRUMENTS if instruments is None else instruments
        self.history_calls: list[dict] = []
        self.instrument_calls = 0

    def instruments(self, exchange):
        self.instrument_calls += 1
        return self._instruments

    def historical_data(self, **kw):
        self.history_calls.append(kw)
        return self._history(**kw)


@pytest.fixture(autouse=True)
def _clear_instrument_cache():
    ka._instrument_cache.clear()
    yield
    ka._instrument_cache.clear()


def kite(fake: FakeKite, token=KITE_TOKEN, sleeps=None) -> ka.KiteMarketDataAdapter:
    return ka.KiteMarketDataAdapter(token_getter=lambda: token, kite_factory=lambda t: fake,
                                    sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


# ── TC-1 contract ────────────────────────────────────────────────────────
def test_tc1_result_dict_carries_every_contract_field():
    r = kite(FakeKite()).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 1))
    d = r.to_dict()
    for field in ("provider_id", "provider_version", "request_id", "requested_at", "response_received_at",
                  "source_timestamp", "availability_timestamp", "instrument_identifier", "raw_payload_reference",
                  "normalized_records", "data_quality_status", "error_code", "retryable"):
        assert field in d
    assert "raw_payload" not in d
    assert datetime.fromisoformat(d["requested_at"]).utcoffset() == timedelta(0)


# ── Kite: TC-2..TC-14 ────────────────────────────────────────────────────
def test_tc2_no_access_token_is_auth_expired_without_calling_the_sdk():
    fake = FakeKite()
    with pytest.raises(c.ProviderError) as e:
        kite(fake, token="").fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 2))
    assert (e.value.code, e.value.retryable) == (c.AUTH_EXPIRED, False)
    assert fake.instrument_calls == 0 and fake.history_calls == []


def test_tc3_token_exception_is_auth_expired_and_not_retried():
    def boom(**kw):
        raise TokenException("Incorrect `api_key` or `access_token`.", 403)
    fake, sleeps = FakeKite(history=boom), []
    with pytest.raises(c.ProviderError) as e:
        kite(fake, sleeps=sleeps).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 2))
    assert e.value.code == c.AUTH_EXPIRED and not e.value.retryable
    assert len(fake.history_calls) == 1 and sleeps == []


def test_tc4_rate_limit_is_retried_with_backoff_then_succeeds():
    state = {"n": 0}

    def flaky(**kw):
        state["n"] += 1
        if state["n"] <= 2:
            raise NetworkException("Too many requests", 429)
        return [bar(kw["from_date"])]
    fake, sleeps = FakeKite(history=flaky), []
    r = kite(fake, sleeps=sleeps).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 1))
    assert r.data_quality_status == c.DQ_OK and len(fake.history_calls) == 3
    assert sleeps == [ka.BACKOFF_SECONDS, ka.BACKOFF_SECONDS * 2]


def test_tc5_retry_exhaustion_is_rate_limited_and_retryable():
    def always(**kw):
        raise NetworkException("Too many requests", 429)
    fake = FakeKite(history=always)
    with pytest.raises(c.ProviderError) as e:
        kite(fake).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 1))
    assert (e.value.code, e.value.retryable) == (c.RATE_LIMITED, True)
    assert len(fake.history_calls) == ka.MAX_RETRIES


def test_tc6_long_daily_range_is_chunked_and_merged_in_order():
    fake = FakeKite()
    start, end = date(2020, 1, 1), date(2026, 1, 1)
    r = kite(fake).fetch_candles("INFY", start, end)
    spans = [(k["from_date"], k["to_date"]) for k in fake.history_calls]
    assert len(spans) == 2 and spans[0][0] == start and spans[-1][1] == end
    assert all((b - a).days < 2000 for a, b in spans) and spans[1][0] == spans[0][1] + timedelta(days=1)
    assert [x["ts"][:10] for x in r.normalized_records] == [spans[0][0].isoformat(), spans[1][0].isoformat()]
    assert r.meta["windows_requested"] == 2


def test_tc7_unknown_symbol_is_identifier_not_resolved_and_no_candle_call():
    fake = FakeKite()
    with pytest.raises(c.ProviderError) as e:
        kite(fake).fetch_candles("NOSUCH", date(2026, 9, 1), date(2026, 9, 2))
    assert e.value.code == c.IDENTIFIER_NOT_RESOLVED and fake.history_calls == []


def test_tc8_zero_candles_is_empty_with_a_reason_code():
    r = kite(FakeKite(history=lambda **kw: [])).fetch_candles("INFY", date(2026, 9, 5), date(2026, 9, 6))
    assert (r.data_quality_status, r.error_code, r.normalized_records) == (c.DQ_EMPTY, c.EMPTY_RESPONSE, [])
    assert r.source_timestamp is None


def test_tc9_identical_duplicate_bar_is_collapsed_and_counted():
    d = date(2026, 9, 1)
    r = kite(FakeKite(history=lambda **kw: [bar(d), bar(d)])).fetch_candles("INFY", d, d)
    assert len(r.normalized_records) == 1 and r.meta["findings"]["duplicate_bars"] == 1
    assert r.data_quality_status == c.DQ_OK


def test_tc10_conflicting_duplicate_blocks_the_series():
    d = date(2026, 9, 1)
    r = kite(FakeKite(history=lambda **kw: [bar(d), bar(d, cl=101.0)])).fetch_candles("INFY", d, d)
    assert r.data_quality_status == c.DQ_BLOCKED and r.error_code == c.INVALID_PAYLOAD
    assert r.meta["findings"]["conflicting_duplicates"] == 1 and r.normalized_records == []


@pytest.mark.parametrize("bad", [dict(h=98.0), dict(low=0.0, o=0.0), dict(low=104.5), dict(h=103.0)])
def test_tc11_impossible_bar_blocks_the_series(bad):
    d = date(2026, 9, 1)
    good = bar(d + timedelta(days=1))
    r = kite(FakeKite(history=lambda **kw: [bar(d, **bad), good])).fetch_candles("INFY", d, d + timedelta(days=1))
    assert r.data_quality_status == c.DQ_BLOCKED and r.meta["findings"]["invalid_ohlc"] == 1
    assert len(r.normalized_records) == 1


def test_tc12_one_failed_window_is_partial_and_listed():
    def second_fails(**kw):
        if kw["from_date"] > date(2024, 1, 1):
            raise NetworkException("gateway timeout", 504)
        return [bar(kw["from_date"])]
    r = kite(FakeKite(history=second_fails)).fetch_candles("INFY", date(2020, 1, 1), date(2026, 1, 1))
    assert (r.data_quality_status, r.error_code, r.retryable) == (c.DQ_PARTIAL, c.PARTIAL_RESPONSE, True)
    assert len(r.meta["failed_windows"]) == 1 and r.meta["failed_windows"][0]["error_code"] == c.PROVIDER_UNAVAILABLE
    assert len(r.normalized_records) == 1


def test_tc13_series_metadata_is_explicit():
    eod = kite(FakeKite()).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 1))
    intra = kite(FakeKite()).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 1), interval="minute")
    assert (eod.meta["series_type"], intra.meta["series_type"]) == ("EOD", "INTRADAY")
    assert eod.meta["price_adjustment"] == "UNVERIFIED" and eod.meta["session_completeness"] == "UNCHECKED"
    assert eod.meta["corporate_action_reconciled"] is False and eod.instrument_identifier == "NSE:INFY"
    with pytest.raises(c.ProviderError) as e:
        kite(FakeKite()).fetch_candles("INFY", date(2026, 9, 2), date(2026, 9, 1))
    assert e.value.code == c.INVALID_REQUEST


def test_tc14_instrument_sync_normalizes_and_rejects_other_exchanges():
    r = kite(FakeKite()).sync_instruments("NSE")
    assert r.normalized_records[0] == {
        "instrument_token": 408065, "exchange_token": "1594", "tradingsymbol": "INFY", "name": "INFOSYS",
        "exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "lot_size": 1, "tick_size": 0.05}
    assert r.meta["by_segment"] == {"NSE": 1, "INDICES": 1}
    with pytest.raises(c.ProviderError) as e:
        kite(FakeKite()).sync_instruments("NFO")
    assert e.value.code == c.INVALID_REQUEST
    empty = kite(FakeKite(instruments=[])).sync_instruments("NSE")
    assert (empty.data_quality_status, empty.error_code) == (c.DQ_EMPTY, c.EMPTY_RESPONSE)


# ── Trendlyne: TC-15..TC-27 ──────────────────────────────────────────────
def test_tc15_unconfigured_url_makes_no_network_call():
    server = McpServer()
    with pytest.raises(c.ProviderError) as e:
        run(tl(server, url="").search_entity("Infosys"))
    assert e.value.code == c.NOT_CONFIGURED and server.calls == []


def test_tc16_entity_search_parses_the_recorded_pipe_table():
    server = McpServer({"search_entities": CALLS["entities_infosys"]["result"]})
    r = run(tl(server).search_entity("Infosys", limit=3))
    assert r.normalized_records[0] == {
        "name": "Infosys Ltd.", "nse_code": "INFY", "bse_code": "500209", "isin": "INE009A01021",
        "entity_type": "stock", "sector": "Software & Services", "industry": "IT Consulting & Software"}
    assert r.provider_version == "Trendlyne-Financial-Server/3.1.1" and r.data_quality_status == c.DQ_OK
    assert server.tool_calls == [{"name": "search_entities", "arguments": {"query": "Infosys", "entity_type": "stock", "limit": 3}}]


def test_tc17_entity_search_with_no_match_is_empty_with_a_reason_code():
    server = McpServer({"search_entities": CALLS["entities_empty"]["result"]})
    r = run(tl(server).search_entity("zzqxnotacompany123"))
    assert (r.data_quality_status, r.error_code, r.normalized_records) == (c.DQ_EMPTY, c.EMPTY_RESPONSE, [])


def test_tc18_ambiguous_entity_returns_every_candidate_and_says_so():
    server = McpServer({"search_entities": CALLS["entities_infosys"]["result"]})
    r = run(tl(server).search_entity("Infosys"))
    assert len(r.normalized_records) == 3 and r.meta["ambiguous"] is True
    assert {x["nse_code"] for x in r.normalized_records} == {"INFY", "MINFY", "INFOBEAN"}


def test_tc19_parameter_values_are_pit_unverified_field_records():
    server = McpServer({"get_stock_parameter_values": CALLS["parameter_values_infy_tcs"]["result"]})
    r = run(tl(server).fetch_parameters(["INFY", "TCS"], ["pettm", "roea"]))
    assert len(r.normalized_records) == 4
    first = r.normalized_records[0]
    assert (first["instrument_identifier"], first["field_name"], first["parameter_token"]) == ("INFY", "PE TTM", "pettm")
    assert first["value"] == 13.71 and first["as_of_period"] == "2026-10-12"
    for rec in r.normalized_records:
        assert rec["validation_status"] == c.PIT_UNVERIFIED and rec["point_in_time_validated"] is False
        assert rec["publication_timestamp"] is None and rec["retrieval_timestamp"]
        assert rec["provider_response_id"] == r.request_id
    assert r.meta["pit_status"] == c.PIT_UNVERIFIED and r.meta["values_not_returned"] == []


def test_tc19b_missing_value_is_reported_not_zero_filled():
    body = json.dumps({"status": "success", "data": "630|Infosys|INFY|500209|2026-10-12\n1372|TCS|TCS|532540|2026-10-12\n\nPE TTM\nINFY:-\n\n---"})
    r = run(tl(McpServer({"get_stock_parameter_values": text_result(body)})).fetch_parameters(["INFY", "TCS"], ["pettm"]))
    assert r.normalized_records[0]["value"] is None and r.normalized_records[0]["value_text"] == "-"
    assert r.meta["values_not_returned"] == [{"instrument_identifier": "TCS", "field_name": "PE TTM"}]


def test_tc20_error_body_under_http_200_is_not_a_success():
    server = McpServer({"get_stock_parameter_values": CALLS["parameter_values_unresolved"]["result"],
                        "get_overview_news_corp_events": CALLS["events_invalid_type"]["result"]})
    assert CALLS["parameter_values_unresolved"]["result"]["isError"] is False
    with pytest.raises(c.ProviderError) as e:
        run(tl(server).fetch_parameters(["NOTASYMBOLXYZ"], ["pettm"]))
    assert e.value.code == c.IDENTIFIER_NOT_RESOLVED and e.value.raw_payload is not None
    with pytest.raises(c.ProviderError) as e2:
        run(tl(server).fetch_events("INFY"))          # recorded `status: error` text body
    assert e2.value.code == c.INVALID_REQUEST


@pytest.mark.parametrize("codes,params", [([f"S{i}" for i in range(11)], ["pettm"]),
                                          (["INFY"], [f"p{i}" for i in range(11)]), ([], ["pettm"])])
def test_tc21_over_limit_request_is_refused_before_any_network_call(codes, params):
    server = McpServer()
    with pytest.raises(c.ProviderError) as e:
        run(tl(server).fetch_parameters(codes, params))
    assert e.value.code == c.INVALID_REQUEST and server.calls == []


def test_tc22_schema_change_blocks_the_call():
    tools = copy.deepcopy(FIXTURE["tools_list"])
    tools["tools"] = [t for t in tools["tools"] if t["name"] != "search_entities"]
    gone = McpServer({"search_entities": CALLS["entities_infosys"]["result"]}, tools=tools)
    with pytest.raises(c.ProviderError) as e:
        run(tl(gone).search_entity("Infosys"))
    assert e.value.code == c.TOOL_SCHEMA_CHANGED and gone.tool_calls == []

    tools = copy.deepcopy(FIXTURE["tools_list"])
    next(t for t in tools["tools"] if t["name"] == "get_stock_parameter_values")["inputSchema"]["required"] = ["stock_codes", "parameters", "as_of"]
    changed = McpServer({"get_stock_parameter_values": CALLS["parameter_values_infy_tcs"]["result"]}, tools=tools)
    with pytest.raises(c.ProviderError) as e:
        run(tl(changed).fetch_parameters(["INFY"], ["pettm"]))
    assert e.value.code == c.TOOL_SCHEMA_CHANGED and changed.tool_calls == []


def test_tc23_unrecognised_payload_shape_yields_no_records():
    renamed = "status: success\ndata:\n  company | nse_code | bse_code | isin | entity_type | sector | industry\n  Infosys Ltd. | INFY | 500209 | INE009A01021 | stock | a | b"
    with pytest.raises(c.ProviderError) as e:
        run(tl(McpServer({"search_entities": text_result(renamed)})).search_entity("Infosys"))
    assert e.value.code == c.TOOL_SCHEMA_CHANGED
    with pytest.raises(c.ProviderError) as e:
        run(tl(McpServer({"search_entities": text_result("<html>maintenance</html>")})).search_entity("Infosys"))
    assert e.value.code == c.INVALID_PAYLOAD
    with pytest.raises(c.ProviderError) as e:
        run(tl(McpServer({"get_stock_parameter_values": text_result(json.dumps({"status": "success", "data": "garbage"}))})).fetch_parameters(["INFY"], ["pettm"]))
    assert e.value.code == c.INVALID_PAYLOAD
    with pytest.raises(c.ProviderError) as e:
        run(tl(McpServer({"search_entities": text_result("   ")})).search_entity("Infosys"))
    assert e.value.code == c.EMPTY_RESPONSE


def test_tc24_account_mutating_tools_cannot_be_called():
    offered = {t["name"] for t in FIXTURE["tools_list"]["tools"]}
    assert {"watchlist_add_stock", "watchlist_remove_stock", "watchlist_creation"} <= offered
    assert not any(name.startswith("watchlist") for name in ta.READ_TOOLS)
    server = McpServer()
    with pytest.raises(c.ProviderError) as e:
        run(tl(server)._call_tool("watchlist_add_stock", {"stock_id": 630, "watchlist_id": 1}))
    assert e.value.code == c.INVALID_REQUEST and server.calls == []


@pytest.mark.parametrize("status,code,retryable", [(403, c.AUTH_EXPIRED, False), (401, c.AUTH_EXPIRED, False),
                                                    (429, c.RATE_LIMITED, True), (503, c.PROVIDER_UNAVAILABLE, True)])
def test_tc25_http_failures_map_to_reason_codes(status, code, retryable):
    with pytest.raises(c.ProviderError) as e:
        run(tl(McpServer(status=status)).search_entity("Infosys"))
    assert (e.value.code, e.value.retryable) == (code, retryable)


def test_tc25b_timeout_is_provider_unavailable():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)
    adapter = ta.TrendlyneResearchAdapter(url_getter=lambda: SECRET_URL, transport=httpx.MockTransport(slow))
    with pytest.raises(c.ProviderError) as e:
        run(adapter.search_entity("Infosys"))
    assert (e.value.code, e.value.retryable) == (c.PROVIDER_UNAVAILABLE, True)
    assert "SECRETTOKEN123" not in e.value.message


def test_tc26_events_become_one_record_per_table_row():
    server = McpServer({"get_overview_news_corp_events": CALLS["events_infy"]["result"]})
    r = run(tl(server).fetch_events("INFY"))
    by_type = {}
    for rec in r.normalized_records:
        by_type.setdefault(rec["event_type"], []).append(rec)
    assert set(by_type) == {"bonus", "dividend", "boardMeeting"}
    assert by_type["bonus"][0]["exdate"] == "2018-09-04" and by_type["bonus"][0]["ratiotext"] == "1:1"
    assert by_type["bonus"][1]["record_date"] is None              # provider's `None` is null, not a string
    assert by_type["dividend"][0] ["amount"] == "25.0" and by_type["dividend"][0]["dividend_type"] == "FINAL"
    assert r.meta["sections"]["split"] == {"rows": 0, "curtailed": False}
    assert r.meta["sections"]["dividend"]["rows"] == len(by_type["dividend"])
    assert all(rec["validation_status"] == c.PIT_UNVERIFIED for rec in r.normalized_records)
    assert server.tool_calls[0]["arguments"] == {"stock_code": "INFY", "type": "events"}


def test_tc27_document_search_yields_chunk_records():
    server = McpServer({"get_document_search_results": CALLS["documents_infosys_trimmed"]["result"]})
    r = run(tl(server).search_documents("Infosys FY25 annual report revenue and operating margin"))
    assert len(r.normalized_records) == 3
    first = r.normalized_records[0]
    assert (first["provider_record_id"], first["instrument_identifier"], first["document_type"], first["as_of_period"]) == \
        ("2181114", "INFY", "Annual Report", "2026-04-22")
    assert first["text"] and [x["chunk_index"] for x in r.normalized_records] == [0, 1, 2]
    assert all(x["validation_status"] == c.PIT_UNVERIFIED for x in r.normalized_records)


# ── TC-28 / TC-29: secrets and the log ───────────────────────────────────
class _Coll:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))


class _FlagColl:
    def __init__(self, flags):
        self.doc = {"key": "feature_flags", "flags": flags}

    async def find_one(self, q, proj=None):
        return copy.deepcopy(self.doc)


class _DB:
    def __init__(self, flags=None):
        self.system_config = _FlagColl(flags if flags is not None else
                                       {"charting": {"mode": "allowlist", "allowlist": ["a@example.com"]}})
        self.users = _FlagColl({})
        self.provider_requests = _Coll()
        self.provider_responses = _Coll()

    def dump(self) -> str:
        return json.dumps([self.provider_requests.docs, self.provider_responses.docs], default=str)


def test_tc28_redaction_removes_tokens_from_logged_text():
    assert "SECRETTOKEN123" not in request_log.redact(f"failed calling {SECRET_URL}")
    assert "abc.def" not in request_log.redact('{"access_token": "abc.def"}')
    assert "hunter2" not in request_log.redact("Authorization: token hunter2")


def test_tc29_success_and_failure_are_both_logged_with_payload_hash():
    db = _DB()
    ok = kite(FakeKite()).fetch_candles("INFY", date(2026, 9, 1), date(2026, 9, 1))
    ref = run(request_log.record(db, operation="fetch-candles", params={"symbol": "INFY", "note": SECRET_URL},
                                 user_id="u_a", result=ok))
    assert ok.raw_payload_reference == ref == f"provider_responses/{ok.request_id}"
    err = c.ProviderError(c.RATE_LIMITED, f"boom at {SECRET_URL}", raw_payload={"x": 1})
    run(request_log.record(db, operation="fetch-candles", params={}, user_id="u_a", error=err,
                           provider_id=c.PROVIDER_KITE, request_id="rid2", requested_at=c.utcnow()))
    assert [d["status"] for d in db.provider_requests.docs] == [c.DQ_OK, "ERROR"]
    assert db.provider_requests.docs[1]["error_code"] == c.RATE_LIMITED and db.provider_requests.docs[1]["retryable"] is True
    assert len(db.provider_responses.docs) == 2 and all(len(d["payload_sha256"]) == 64 for d in db.provider_responses.docs)
    assert json.loads(db.provider_responses.docs[0]["payload_json"])[0]["close"] == 104.0
    assert "SECRETTOKEN123" not in db.dump()
    with pytest.raises(ValueError):
        run(request_log.record(db, operation="x", params={}, user_id=None))


# ── API: TC-30..TC-33 ────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags)
    feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear()
    ff._flags.update(saved)
    feature_gate._state["at"] = float("-inf")


def _client(monkeypatch, db, *, kite_adapter=None, trendlyne=None, kite_token=KITE_TOKEN, url=SECRET_URL):
    monkeypatch.setattr(rp, "db", db)
    monkeypatch.setattr(rp, "default_token", lambda: kite_token)
    monkeypatch.setattr(rp, "default_url", lambda: url)
    if kite_adapter is not None:
        monkeypatch.setattr(rp, "_kite", lambda: kite_adapter)
    if trendlyne is not None:
        monkeypatch.setattr(rp, "_trendlyne", lambda: trendlyne)

    async def resolve(request: Request):
        if "X-Test-User" not in request.headers:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Not authenticated")
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("charting", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    app = FastAPI()
    app.include_router(rp.router)
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dep in (dependant.dependencies if dependant else []):
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app)


A = {"X-Test-User": "a"}
ROUTES = [("get", "", None), ("get", "/health", None),
          ("post", "/kite/sync-instruments", {}),
          ("post", "/kite/fetch-candles", {"symbol": "INFY", "start": "2026-09-01", "end": "2026-09-02"}),
          ("post", "/trendlyne/search-entity", {"query": "Infosys"}),
          ("post", "/trendlyne/search-parameters", {"query": "PE"}),
          ("post", "/trendlyne/fetch-parameters", {"stock_codes": ["INFY"], "parameters": ["pettm"]}),
          ("post", "/trendlyne/fetch-events", {"stock_code": "INFY"}),
          ("post", "/trendlyne/search-documents", {"query": "Infosys revenue"})]


def _hit(client, method, path, body, headers):
    url = "/api/research/providers" + path
    return client.get(url, headers=headers) if method == "get" else client.post(url, json=body, headers=headers)


def test_tc30_every_route_is_gated(monkeypatch):
    db, fake, server = _DB(), FakeKite(), McpServer()
    client = _client(monkeypatch, db, kite_adapter=kite(fake), trendlyne=tl(server))
    for method, path, body in ROUTES:
        assert _hit(client, method, path, body, {}).status_code == 401, path
        denied = _hit(client, method, path, body, {"X-Test-User": "other"})
        assert (denied.status_code, denied.json()["detail"]) == (403, "feature_not_enabled"), path
    assert fake.instrument_calls == 0 and server.calls == [] and db.provider_requests.docs == []


def test_tc31_catalogue_lists_both_providers_without_secrets(monkeypatch):
    client = _client(monkeypatch, _DB())
    r = client.get("/api/research/providers", headers=A)
    assert r.status_code == 200
    by_id = {p["provider_id"]: p for p in r.json()["providers"]}
    assert set(by_id) == {"kite", "trendlyne"} and all(p["configured"] for p in by_id.values())
    assert by_id["trendlyne"]["pit_status"] == c.PIT_UNVERIFIED
    assert "SECRETTOKEN123" not in r.text and KITE_TOKEN not in r.text and "mcp.example.test" not in r.text
    unset = _client(monkeypatch, _DB(), kite_token="", url="").get("/api/research/providers", headers=A).json()
    assert [p["configured"] for p in unset["providers"]] == [False, False]


def test_tc31b_success_path_returns_the_contract_and_logs_it(monkeypatch):
    db = _DB()
    server = McpServer({"search_entities": CALLS["entities_infosys"]["result"]})
    client = _client(monkeypatch, db, kite_adapter=kite(FakeKite()), trendlyne=tl(server))
    r = client.post("/api/research/providers/trendlyne/search-entity", json={"query": "Infosys", "limit": 3}, headers=A)
    assert r.status_code == 200 and r.json()["normalized_records"][0]["isin"] == "INE009A01021"
    assert r.json()["raw_payload_reference"] == f"provider_responses/{r.json()['request_id']}"
    k = client.post("/api/research/providers/kite/fetch-candles",
                    json={"symbol": "INFY", "start": "2026-09-01", "end": "2026-09-01"}, headers=A)
    assert k.status_code == 200 and k.json()["normalized_records"][0]["close"] == 104.0
    s = client.post("/api/research/providers/kite/sync-instruments", json={}, headers=A)
    assert s.status_code == 200 and s.json()["meta"]["record_count"] == 2
    assert [d["operation"] for d in db.provider_requests.docs] == ["search-entity", "fetch-candles", "sync-instruments"]
    assert all(d["user_id"] == "u_a" for d in db.provider_requests.docs) and len(db.provider_responses.docs) == 3
    assert "SECRETTOKEN123" not in db.dump() and KITE_TOKEN not in db.dump()


def test_tc32_adapter_failure_is_an_http_error_with_reason_code_and_is_logged(monkeypatch):
    db = _DB()
    server = McpServer({"get_stock_parameter_values": CALLS["parameter_values_unresolved"]["result"]})
    client = _client(monkeypatch, db, kite_adapter=kite(FakeKite(), token=""), trendlyne=tl(server))
    r = client.post("/api/research/providers/trendlyne/fetch-parameters",
                    json={"stock_codes": ["NOTASYMBOLXYZ"], "parameters": ["pettm"]}, headers=A)
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert (detail["error_code"], detail["retryable"], detail["provider_id"]) == (c.IDENTIFIER_NOT_RESOLVED, False, "trendlyne")
    k = client.post("/api/research/providers/kite/fetch-candles",
                    json={"symbol": "INFY", "start": "2026-09-01", "end": "2026-09-02"}, headers=A)
    assert k.status_code == 503 and k.json()["detail"]["error_code"] == c.AUTH_EXPIRED
    logged = {d["request_id"]: d for d in db.provider_requests.docs}
    assert logged[detail["request_id"]]["status"] == "ERROR" and logged[k.json()["detail"]["request_id"]]["error_code"] == c.AUTH_EXPIRED
    assert len(db.provider_responses.docs) == 2

    down = _client(monkeypatch, _DB(), kite_adapter=kite(FakeKite(), token=""), trendlyne=tl(McpServer(status=503)))
    h = down.get("/api/research/providers/health", headers=A)
    assert h.status_code == 200
    states = {p["provider_id"]: p for p in h.json()["providers"]}
    assert states["trendlyne"]["reachable"] is False and states["trendlyne"]["error_code"] == c.PROVIDER_UNAVAILABLE


@pytest.mark.parametrize("path,body", [
    ("/kite/fetch-candles", {"symbol": "infy; drop", "start": "2026-09-01", "end": "2026-09-02"}),
    ("/kite/fetch-candles", {"symbol": "INFY", "start": "2026-09-01", "end": "2026-09-02", "interval": "2minute"}),
    ("/kite/fetch-candles", {"symbol": "INFY", "start": "not-a-date", "end": "2026-09-02"}),
    ("/kite/sync-instruments", {"exchange": "NFO"}),
    ("/trendlyne/search-entity", {"query": ""}),
    ("/trendlyne/search-entity", {"query": "Infosys", "entity_type": "mutualfund"}),
    ("/trendlyne/fetch-parameters", {"stock_codes": [f"S{i}" for i in range(11)], "parameters": ["pettm"]}),
    ("/trendlyne/fetch-events", {"stock_code": "INFY", "type": "news"}),
])
def test_tc33_malformed_requests_never_reach_a_provider(monkeypatch, path, body):
    db, fake, server = _DB(), FakeKite(), McpServer()
    client = _client(monkeypatch, db, kite_adapter=kite(fake), trendlyne=tl(server))
    assert client.post("/api/research/providers" + path, json=body, headers=A).status_code == 422
    assert fake.instrument_calls == 0 and fake.history_calls == [] and server.calls == []


def test_tc33b_reversed_date_range_is_400_invalid_request(monkeypatch):
    db, fake = _DB(), FakeKite()
    client = _client(monkeypatch, db, kite_adapter=kite(fake), trendlyne=tl(McpServer()))
    r = client.post("/api/research/providers/kite/fetch-candles",
                    json={"symbol": "INFY", "start": "2026-09-05", "end": "2026-09-01"}, headers=A)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == c.INVALID_REQUEST
    assert fake.history_calls == []
