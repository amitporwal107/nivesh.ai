"""The chart of a futures or options contract an account holds — the contract's own price, read live
from the broker — and the chart card a chat answer carries when the question was asked from such a
position.

Three layers, each run for real with only what sits below it faked (harness from
test_broker_hub_reads.py and test_broker_connect_native_routes.py):
  services.brokers.hub_reads   parse_contract, supports_contract_chart, read_contract_chart
  routes.broker_connect        GET /api/broker/accounts/{id}/contract-chart
  routes.chat                  the `position` field of POST /api/chat/stream

Nothing here talks to a real broker or a real model.
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import date, datetime

import pytest

from tests.test_broker_connect_native_routes import (  # noqa: F401  (`h`, `flag_off` are fixtures)
    _error, _no_secret, flag_off, h,
)
from tests.test_broker_hub_reads import (  # noqa: F401  (`sib` is a fixture)
    broker_rows_as_given, CLIENT_ID, SECRET, FakeCollection, FakeDB, hub, native_account, sib,
)

import routes.chat as chat  # noqa: E402
from services.brokers.base import Candle, ContractChart, ContractQuote, ContractRef  # noqa: E402

PUT = ContractRef(symbol="FIXCO", exchange="NFO", instrument_type="PE", expiry="2026-10-27", strike=1760.0)
FUTURE = ContractRef(symbol="FIXCO", exchange="NFO", instrument_type="FUT", expiry="2026-10-27", strike=None)
CHART = ContractChart(
    candles=[
        Candle(time="2026-10-13T09:15:00+05:30", open=34.1, high=34.1, low=30.0, close=31.5, volume=1100.0, open_interest=109450.0),
        Candle(time="2026-10-13T09:20:00+05:30", open=31.5, high=32.0, low=31.0, close=31.2, volume=None, open_interest=None),
    ],
    quote=ContractQuote(last_price=21.85, last_traded_at="2026-10-13T15:38:34+05:30", spot_price=1801.0),
)
CHART_JSON = {
    "candles": [
        {"time": "2026-10-13T09:15:00+05:30", "open": 34.1, "high": 34.1, "low": 30.0, "close": 31.5, "volume": 1100.0, "open_interest": 109450.0},
        {"time": "2026-10-13T09:20:00+05:30", "open": 31.5, "high": 32.0, "low": 31.0, "close": 31.2, "volume": None, "open_interest": None},
    ],
    "quote": {"last_price": 21.85, "last_traded_at": "2026-10-13T15:38:34+05:30", "open": None, "high": None, "low": None,
              "previous_close": None, "change_pct": None, "spot_price": 1801.0, "volume": None},
}


class IciciSessionExpired(Exception):
    """An adapter's own "the broker refused the session"."""


class ChartNotSupported(Exception):
    """An adapter's own "I cannot serve this"."""


def chart_reader(sib, result=CHART, slug="icicidirect"):
    """Give the fake ICICI adapter the optional `fetch_contract_chart`; `result` is returned or raised."""
    async def fetch(token, contract, interval):
        sib.calls.append(("adapter.fetch_contract_chart", slug, sib.account_of(token), contract, interval))
        if isinstance(result, BaseException):
            raise result
        return result
    sib.adapters[slug].fetch_contract_chart = fetch


def chart_reads(sib):
    return [c for c in sib.calls if c[0] == "adapter.fetch_contract_chart"]


def icici(account_id="ba_i", **over):
    return native_account(account_id, broker="icicidirect", **over)


# ── parse_contract ────────────────────────────────────────────────────────
def test_a_position_rows_values_name_a_contract_in_one_form():
    assert hub.parse_contract(" fixco ", "nfo", "pe", "2026-10-27", 1760) == PUT
    assert hub.parse_contract("FIXCO", "NFO", "FUT", date(2026, 10, 27), None) == FUTURE
    # A future has no strike, whatever was sent with it.
    assert hub.parse_contract("FIXCO", "NFO", "FUT", "2026-10-27", 1760) == FUTURE
    assert hub.parse_contract("M&M", "NFO", "CE", "2026-10-27", 3012.5).strike == 3012.5


@pytest.mark.parametrize("values", [
    ("", "NFO", "PE", "2026-10-27", 1760), (None, "NFO", "PE", "2026-10-27", 1760),
    ("FIX CO", "NFO", "PE", "2026-10-27", 1760), ("FIXCO/../x", "NFO", "PE", "2026-10-27", 1760),
    ("X" * 41, "NFO", "PE", "2026-10-27", 1760),
    ("FIXCO", "", "PE", "2026-10-27", 1760), ("FIXCO", "NF0", "PE", "2026-10-27", 1760), ("FIXCO", 7, "PE", "2026-10-27", 1760),
    ("FIXCO", "NFO", "EQ", "2026-10-27", 1760), ("FIXCO", "NFO", None, "2026-10-27", 1760),
    ("FIXCO", "NFO", "PE", "27-Oct-2026", 1760), ("FIXCO", "NFO", "PE", "2026-13-40", 1760),
    ("FIXCO", "NFO", "PE", None, 1760), ("FIXCO", "NFO", "PE", datetime(2026, 10, 27), 1760),
    ("FIXCO", "NFO", "PE", "2026-10-27", None), ("FIXCO", "NFO", "PE", "2026-10-27", 0),
    ("FIXCO", "NFO", "PE", "2026-10-27", -5), ("FIXCO", "NFO", "PE", "2026-10-27", "1760"),
    ("FIXCO", "NFO", "PE", "2026-10-27", True), ("FIXCO", "NFO", "PE", "2026-10-27", math.inf),
    ("FIXCO", "NFO", "PE", "2026-10-27", math.nan), ("FIXCO", "NFO", "PE", "2026-10-27", 10_000_001),
])
def test_values_that_cannot_name_a_future_or_an_option_are_refused(values):
    with pytest.raises(ValueError):
        hub.parse_contract(*values)


# ── hub_reads.read_contract_chart ─────────────────────────────────────────
def test_only_a_broker_whose_adapter_reads_charts_supports_them(sib):
    chart_reader(sib)
    sib.adapter("stubbed", "Stubbed", implemented=False).fetch_contract_chart = lambda *a: None
    assert hub.supports_contract_chart("icicidirect") is True
    assert hub.supports_contract_chart("zerodha") is False        # adapter without the reader
    assert hub.supports_contract_chart("stubbed") is False        # a placeholder adapter
    assert hub.supports_contract_chart("nobody") is False         # no adapter at all


def test_the_chart_is_read_from_the_accounts_broker_and_nothing_is_stored(sib):
    chart_reader(sib)
    db = FakeDB(accounts=[icici()], holdings=[])
    before = json.dumps([db.broker_accounts.docs, db.holdings.docs], default=str)

    got = asyncio.run(hub.read_contract_chart(db, db.broker_accounts.one(account_id="ba_i"), PUT, "30m"))

    assert got == CHART_JSON
    assert chart_reads(sib) == [("adapter.fetch_contract_chart", "icicidirect", "ba_i", PUT, "30m")]
    assert json.dumps([db.broker_accounts.docs, db.holdings.docs], default=str) == before
    assert db.broker_sync_snapshots.docs == []


def test_the_chart_has_a_five_minute_and_a_thirty_minute_view_and_no_daily_one():
    assert hub.CHART_INTERVALS == ("5m", "30m")


@pytest.mark.parametrize("interval", ["1m", "1d", "1day", "", None])
def test_an_unknown_view_is_refused_before_anything_is_read(sib, interval):
    chart_reader(sib)
    with pytest.raises(ValueError):
        asyncio.run(hub.read_contract_chart(FakeDB(accounts=[icici()]), icici(), PUT, interval))
    assert sib.calls == []


def test_a_broker_with_no_chart_reader_is_not_supported_and_not_called(sib):
    db = FakeDB(accounts=[native_account("ba_z")])
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_contract_chart(db, db.broker_accounts.one(account_id="ba_z"), PUT, "5m"))
    assert sib.reads() == [] and sib.ended == []


def test_an_adapter_that_says_it_cannot_serve_the_contract_is_not_supported(sib):
    chart_reader(sib, ChartNotSupported("no such view"))
    with pytest.raises(hub.BrokerNotSupported):
        asyncio.run(hub.read_contract_chart(FakeDB(accounts=[icici()]), icici(), PUT, "5m"))
    assert sib.ended == []


def test_a_session_the_broker_refuses_is_ended(sib):
    chart_reader(sib, IciciSessionExpired("Invalid session."))
    db = FakeDB(accounts=[icici()])
    with pytest.raises(hub.BrokerSessionExpired):
        asyncio.run(hub.read_contract_chart(db, db.broker_accounts.one(account_id="ba_i"), PUT, "5m"))
    assert sib.ended == [("ba_i", "broker_rejected")]


def test_an_account_whose_session_has_ended_is_not_read(sib):
    chart_reader(sib)
    with pytest.raises(hub.sessions.SessionEnded):
        asyncio.run(hub.read_contract_chart(FakeDB(accounts=[icici(status="expired")]), icici(status="expired"), PUT, "5m"))
    assert chart_reads(sib) == [] and sib.ended == []


def test_any_other_failure_is_a_read_error_that_carries_no_broker_text(sib, caplog):
    chart_reader(sib, RuntimeError(f"upstream said {SECRET} for {CLIENT_ID}"))
    with caplog.at_level("DEBUG", logger="services.brokers.hub_reads"):
        with pytest.raises(hub.BrokerReadError) as e:
            asyncio.run(hub.read_contract_chart(FakeDB(accounts=[icici()]), icici(), PUT, "5m"))
    assert not isinstance(e.value, (hub.BrokerSessionExpired, hub.BrokerNotSupported))
    _no_secret(str(e.value), caplog.text)
    assert "contract chart read failed account=ba_i broker=icicidirect interval=5m" in caplog.text
    assert sib.ended == []


# ── GET /api/broker/accounts/{id}/contract-chart ──────────────────────────
PUT_QUERY = "symbol=FIXCO&exchange=NFO&instrument_type=PE&expiry=2026-10-27&strike=1760"
FUT_QUERY = "symbol=FIXCO&exchange=NFO&instrument_type=FUT&expiry=2026-10-27"


def test_the_route_returns_the_contracts_candles_and_quote(h, sib):
    chart_reader(sib)
    res = h.get(f"/api/broker/accounts/ba_i/contract-chart?{PUT_QUERY}&interval=30m")

    assert res.status_code == 200
    body = res.json()
    as_of = datetime.fromisoformat(body.pop("as_of"))
    assert as_of.utcoffset() is not None and as_of.utcoffset().total_seconds() == 0
    assert body == {
        "account_id": "ba_i", "broker": "icicidirect", "broker_display": "ICICI Direct",
        "contract": {"symbol": "FIXCO", "exchange": "NFO", "instrument_type": "PE", "expiry": "2026-10-27", "strike": 1760.0},
        "interval": "30m", **CHART_JSON,
    }
    assert chart_reads(sib) == [("adapter.fetch_contract_chart", "icicidirect", "ba_i", PUT, "30m")]
    _no_secret(res.text)
    assert h.audits == []                                    # a read, like positions: not audited


def test_a_future_needs_no_strike_and_the_view_defaults_to_five_minutes(h, sib):
    chart_reader(sib)
    res = h.get(f"/api/broker/accounts/ba_i/contract-chart?{FUT_QUERY}")
    assert res.status_code == 200
    assert res.json()["contract"]["strike"] is None and res.json()["interval"] == "5m"
    assert chart_reads(sib)[0][3:] == (FUTURE, "5m")


@pytest.mark.parametrize("query", [
    "symbol=FIXCO&exchange=NFO&instrument_type=PE&expiry=2026-10-27",                 # an option with no strike
    "symbol=FIXCO&exchange=NFO&instrument_type=PE&expiry=27-10-2026&strike=1760",     # not a date
    "symbol=FIX%20CO&exchange=NFO&instrument_type=PE&expiry=2026-10-27&strike=1760",  # not a symbol
    "symbol=FIXCO&exchange=NFO&instrument_type=EQ&expiry=2026-10-27",                 # a share
    "symbol=FIXCO&exchange=NFO&instrument_type=PE&expiry=2026-10-27&strike=abc",
    f"{PUT_QUERY}&interval=1m",
    f"{PUT_QUERY}&interval=1d",                                                       # there is no daily view
    "exchange=NFO&instrument_type=PE&expiry=2026-10-27&strike=1760",                  # no symbol
])
def test_a_request_that_does_not_name_a_contract_and_a_view_is_refused_before_any_read(h, sib, query):
    chart_reader(sib)
    res = h.get(f"/api/broker/accounts/ba_i/contract-chart?{query}")
    assert res.status_code == 422
    assert sib.reads() == [] and chart_reads(sib) == []


def test_the_chart_of_someone_elses_account_does_not_exist(h, sib):
    chart_reader(sib, slug="zerodha")
    res = h.get(f"/api/broker/accounts/ba_u2/contract-chart?{PUT_QUERY}")
    assert res.status_code == 404 and chart_reads(sib) == []
    assert h.get(f"/api/broker/accounts/ba_i/contract-chart?{PUT_QUERY}", who="nobody").status_code == 401


def test_an_openalgo_account_and_a_broker_without_a_reader_are_not_supported(h, sib):
    for account in ("ba_oa", "ba_z"):
        res = h.get(f"/api/broker/accounts/{account}/contract-chart?{PUT_QUERY}")
        _error(res, 400, "BROKER_READ_NOT_SUPPORTED")
    assert sib.reads() == []


def test_read_failures_carry_the_hubs_stable_codes(h, sib):
    chart_reader(sib, IciciSessionExpired("Invalid session."))
    _error(h.get(f"/api/broker/accounts/ba_i/contract-chart?{PUT_QUERY}"), 409, "BROKER_SESSION_EXPIRED")
    assert sib.ended == [("ba_i", "broker_rejected")]

    h.db.broker_accounts.one(account_id="ba_i")["status"] = "active"
    chart_reader(sib, RuntimeError(f"boom {SECRET}"))
    res = h.get(f"/api/broker/accounts/ba_i/contract-chart?{PUT_QUERY}")
    _error(res, 502, "BROKER_READ_FAILED")
    _no_secret(res.text)


def test_the_chart_is_refused_when_the_broker_hub_is_switched_off(h, sib, flag_off):
    chart_reader(sib)
    res = h.get(f"/api/broker/accounts/ba_i/contract-chart?{PUT_QUERY}")
    assert res.status_code == 403 and chart_reads(sib) == []


# ── The chart card on a chat answer ───────────────────────────────────────
POSITION = {"account_id": "ba_i", "symbol": "FIXCO", "exchange": "NFO", "instrument_type": "PE",
            "expiry": "2026-10-27", "strike": 1760, "quantity": 550, "avg_price": 35.88}


class _ChatCollection(FakeCollection):
    async def count_documents(self, query=None):
        return len([d for d in self.docs if self._matches(d, query)])


@pytest.fixture
def chat_db(monkeypatch, sib):
    chart_reader(sib)
    db = FakeDB(accounts=[icici(), native_account("ba_z"), icici("ba_u2", user_id="u2"),
                          native_account("ba_oa", broker="icicidirect", native=False)])
    db.chat_messages, db.chat_sessions, db.user_profiles = _ChatCollection(), _ChatCollection(), _ChatCollection()
    db.copilot_chart_invalid = _ChatCollection()
    monkeypatch.setattr(chat, "db", db)
    return db


def card(position, user_id="u1"):
    return asyncio.run(chat._position_chart_widget(user_id, position))


def test_a_question_from_an_option_position_gets_that_contracts_chart_card(chat_db, sib):
    got = card(POSITION)
    stamp = datetime.fromisoformat(got["freshness"].pop("last_updated"))
    assert stamp.utcoffset() is not None
    assert got == {
        "widget_type": "broker_contract_chart",
        "title": "FIXCO 1,760 put · 27 Oct 2026",
        "data": {"account_id": "ba_i", "broker": "icicidirect", "broker_display": "ICICI Direct",
                 "symbol": "FIXCO", "exchange": "NFO", "instrument_type": "PE", "expiry": "2026-10-27",
                 "strike": 1760.0, "quantity": 550.0, "avg_price": 35.88},
        "freshness": {"state": "live", "source": ["ICICI Direct"]},
        "agent": {"id": "broker", "confidence": 100},
    }
    # The card is a reference: no price is read to build it, and nothing secret is in it.
    assert chart_reads(sib) == []
    _no_secret(got)


@pytest.mark.parametrize("change,title,strike,quantity,avg", [
    ({"instrument_type": "FUT", "strike": None, "quantity": -275, "avg_price": 1770},
     "FIXCO future · 27 Oct 2026", None, -275.0, 1770.0),
    ({"instrument_type": "CE", "strike": 3012.5, "expiry": "2026-11-05"},
     "FIXCO 3,012.50 call · 5 Nov 2026", 3012.5, 550.0, 35.88),
    ({"avg_price": None, "quantity": None}, "FIXCO 1,760 put · 27 Oct 2026", 1760.0, None, None),
    ({"avg_price": 0, "quantity": "550"}, "FIXCO 1,760 put · 27 Oct 2026", 1760.0, None, None),
])
def test_the_card_names_the_contract_and_keeps_only_real_figures(chat_db, change, title, strike, quantity, avg):
    got = card({**POSITION, **change})
    assert got["title"] == title
    assert (got["data"]["strike"], got["data"]["quantity"], got["data"]["avg_price"]) == (strike, quantity, avg)


@pytest.mark.parametrize("position", [
    None, "ba_i", [], {},
    {**POSITION, "account_id": "ba_u2"},            # another user's account
    {**POSITION, "account_id": "ba_missing"},
    {**POSITION, "account_id": "ba_z"},             # its broker reads no contract chart
    {**POSITION, "account_id": "ba_oa"},            # not a redirect-connected account
    {**POSITION, "account_id": 7}, {**POSITION, "account_id": "x" * 65}, {**POSITION, "account_id": ""},
    {**POSITION, "instrument_type": "EQ"},          # a share: no contract
    {**POSITION, "strike": None},                   # an option with no strike
    {**POSITION, "expiry": "27-Oct-2026"},
    {**POSITION, "symbol": "FIXCO; drop"},
])
def test_a_missing_bad_or_foreign_reference_gives_no_card_and_never_raises(chat_db, position):
    assert card(position) is None


def test_a_failing_account_lookup_costs_the_card_not_the_answer(chat_db, monkeypatch):
    async def down(*_a, **_k):
        raise RuntimeError(f"mongo down {SECRET}")
    monkeypatch.setattr(chat_db.broker_accounts, "find_one", down)
    assert card(POSITION) is None


# The stream: the card goes out first, the engine's own card is dropped, and the card is what is saved.
class _Chunk:
    def __init__(self, text):
        self.content = text


class _Response:
    text = "Levels for FIXCO."
    widget_type = "instrument_detail"
    widget_data = {"symbol": "FIXCO"}
    agent = "stock_analyst"
    follow_ups = ["What is the breakeven?"]


class _Graph:
    """The engine, reduced to the events `/chat/stream` reads: an early card for the underlying
    share, some answer text, and the final response carrying the same share card."""

    async def astream_events(self, _input, config=None, version=None):
        yield {"event": "on_custom_event", "name": "copilot_widget",
               "data": {"widget_type": "instrument_detail", "widget_data": {"symbol": "FIXCO"}}}
        yield {"event": "on_chat_model_stream", "tags": [], "data": {"chunk": _Chunk("Levels for FIXCO.")}}
        yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"response": _Response()}}}


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def stream(monkeypatch, chat_db):
    async def current_user(_request):
        return {"user_id": "u1"}

    async def not_an_advisor(*_a):
        return False

    async def nothing(*_a, **_k):
        return None

    async def no_persona(*_a, **_k):
        return {}

    monkeypatch.setattr(chat, "get_current_user", current_user)
    monkeypatch.setattr(chat, "_is_advisor_caller", not_an_advisor)
    monkeypatch.setattr(chat, "_bust_chat_cache", nothing)
    monkeypatch.setattr(chat, "_ensure_plan_for_actionable_question", nothing)
    monkeypatch.setattr(chat, "_load_persona_context", no_persona)
    monkeypatch.setattr(chat, "_lg_available", True)
    monkeypatch.setattr(chat, "_get_copilot_graph", lambda: _Graph())
    monkeypatch.setattr(chat, "_llm_text_of", lambda chunk: chunk.content)

    def ask(**extra):
        async def run():
            response = await chat.stream_chat(_Request({"message": "Show the FIXCO chart", "session_id": "s1", **extra}))
            frames = []
            async for part in response.body_iterator:
                text = part.decode() if isinstance(part, bytes) else part
                frames += [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
            return frames
        frames = asyncio.run(run())
        saved = [m for m in chat_db.chat_messages.docs if m.get("role") == "assistant"]
        return frames, saved[-1]

    return ask


def test_the_contract_card_is_the_answers_only_card_and_is_what_is_saved(stream):
    frames, saved = stream(position=POSITION)

    widgets = [f for f in frames if f["type"] == "widget"]
    assert [w["widget_type"] for w in widgets] == ["broker_contract_chart"]
    assert widgets[0]["data"]["account_id"] == "ba_i" and widgets[0]["title"] == "FIXCO 1,760 put · 27 Oct 2026"
    # It is sent before any of the answer's text.
    kinds = [f["type"] for f in frames]
    assert kinds.index("widget") < kinds.index("token")
    assert saved["widget"]["widget_type"] == "broker_contract_chart" and saved["content"] == "Levels for FIXCO."
    assert frames[-1]["type"] == "done"


def test_without_a_position_the_engines_own_card_is_sent_and_saved_as_before(stream):
    frames, saved = stream()
    assert [f["widget_type"] for f in frames if f["type"] == "widget"] == ["instrument_detail"]
    assert saved["widget"]["widget_type"] == "instrument_detail"


def test_a_reference_that_is_not_the_callers_changes_nothing(stream):
    frames, saved = stream(position={**POSITION, "account_id": "ba_u2"})
    assert [f["widget_type"] for f in frames if f["type"] == "widget"] == ["instrument_detail"]
    assert saved["widget"]["widget_type"] == "instrument_detail"
