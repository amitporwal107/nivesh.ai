"""services/brokers/icicidirect.py — ICICI Direct (Breeze API) adapter.

No network: every HTTP call is answered by an `httpx.MockTransport`. Nothing in this file has been run
against a live ICICI Direct account.

Payloads marked DOCS are copied from ICICI Direct's Breeze API reference
(https://api.icicidirect.com/breezeapi/documents/index.html). Payloads marked OBSERVED are what the live
API answered on 2026-10-13 to requests carrying made-up credentials. Rows marked CONSTRUCTED have no
sample in the reference and are built from the documented field set — their values are not ICICI's.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from services.brokers import icicidirect as icici
from services.brokers import registry
from services.brokers.base import AccessToken, Funds, Holding, HubPosition, Position

# The reference's own example AppKey (public text, chosen for its special characters).
APP_KEY = "8g791^N029R47I831B8153=^O2f#7u8g"
APP_SECRET = "unit-test-secret"
SESSION_KEY = "58593"                         # DOCS: the one-time key from the redirect
SESSION_TOKEN = "QUgzNzkzMDA6NDUwNTM0MjI="    # DOCS: `session_token` from /customerdetails
TOKEN = AccessToken(token=SESSION_TOKEN, extras={"user_id": "379XTZ300"})

# ── DOCS payloads ────────────────────────────────────────────────────────
DOCS_CUSTOMER_DETAILS = {
    "Success": {
        "exg_trade_date": {"NSE": "17-Apr-2025", "BSE": "17-Apr-2025", "FNO": "17-Apr-2025", "NDX": "17-Apr-2025"},
        "exg_status": {"NSE": "O", "BSE": "O", "FNO": "Y", "NDX": "O"},
        "segments_allowed": {"Trading": "Y", "Equity": "Y", "Derivatives": "Y", "Currency": "Z"},
        "idirect_userid": "379XTZ300",
        "session_token": SESSION_TOKEN,
        "idirect_user_name": "JOHN SMITH",
        "idirect_ORD_TYP": "N",
        "idirect_lastlogin_time": "17-Apr-2025 11:50:42",
        "mf_holding_mode_popup_flg": "N",
        "commodity_exchange_status": "N",
        "commodity_trade_date": "17-Apr-2025",
        "commodity_allowed": "O",
    },
    "Status": 200,
    "Error": None,
}

DOCS_DEMAT_ROW = {
    "stock_code": "UNITEC",
    "stock_ISIN": "INE694A01020",
    "quantity": "1",
    "demat_total_bulk_quantity": "1",
    "demat_avail_quantity": "0",
    "blocked_quantity": "0",
    "demat_allocated_quantity": "1",
}

DOCS_PORTFOLIO_OPTION_ROW = {
    "stock_code": "NIFTY", "exchange_code": "NFO", "quantity": "0", "average_price": "0",
    "booked_profit_loss": None, "current_market_price": "0", "change_percentage": None,
    "answer_flag": None, "product_type": "Options", "expiry_date": "01-Aug-2024",
    "strike_price": "25200", "right": "Call", "category_index_per_stock": "I", "action": "NA",
    "realized_profit": "-349.26", "unrealized_profit": "0", "open_position_value": "0",
    "portfolio_charges": "5.51",
}

DOCS_POSITION_OPTION_ROW = {
    "segment": "fno", "product_type": "Options", "exchange_code": "NFO", "stock_code": "NIFTY",
    "expiry_date": "27-Feb-2025", "strike_price": "24800", "right": "Call", "action": "NA",
    "quantity": "0", "average_price": "0", "settlement_id": None, "margin_amount": None,
    "ltp": "29.95", "price": "28.85", "stock_index_indicator": "Index", "cover_quantity": "0",
    "stoploss_trigger": "0", "stoploss": None, "take_profit": None, "available_margin": None,
    "squareoff_mode": None, "mtf_sell_quantity": None, "mtf_net_amount_payable": None,
    "mtf_expiry_date": None, "order_id": "", "cover_order_flow": None,
    "cover_order_executed_quantity": None, "pledge_status": None, "pnl": None,
    "underlying": "NIFTY", "order_segment_code": None,
}

DOCS_FUNDS = {
    "bank_account": "123456789012", "total_bank_balance": 800000000.0,
    "allocated_equity": 200000000.0, "allocated_fno": 200000000.0,
    "allocated_commodity": 200000000.0, "allocated_currency": 200000000.0,
    "block_by_trade_equity": 0.0, "block_by_trade_fno": 12500000.53,
    "block_by_trade_commodity": 0.0, "block_by_trade_currency": 0.0,
    "block_by_trade_balance": 15500000, "unallocated_balance": "87500000",
}

# ── OBSERVED answers (live API, made-up credentials, 2026-10-13) ─────────
OBSERVED_UNKNOWN_KEY_ON_EXCHANGE = (200, {"Success": None, "Status": 5, "Error": "Public Key does not exist."})
OBSERVED_UNKNOWN_KEY_ON_READ = (401, {"Status": 5, "Error": "Public Key does not exist."})

# ── CONSTRUCTED rows (documented field set, invented values) ─────────────
# The reference has no equity row for /portfolioholdings; same keys as its NFO sample.
PORTFOLIO_EQUITY_ROW = dict(
    DOCS_PORTFOLIO_OPTION_ROW, stock_code="UNITEC", exchange_code="NSE", quantity="1",
    average_price="2.35", current_market_price="2.90", product_type="Cash",
    expiry_date=None, strike_price="0", right=None,
)
# An open short put: `action` carries the side.
POSITION_SHORT_PUT = dict(
    DOCS_POSITION_OPTION_ROW, strike_price="24000", right="Put", action="Sell",
    quantity="75", average_price="112.5", ltp="98.4", pnl="1057.5",
)
POSITION_FUTURE = dict(
    DOCS_POSITION_OPTION_ROW, product_type="Futures", stock_code="RELIND", strike_price="0",
    right="Others", action="Buy", quantity="250", average_price="1290.4", ltp="1301.15",
    stock_index_indicator="Stock", underlying="RELIND",
)
# Intraday equity. `Margin` is ICICI's intraday product; `segment: "M"` is what its
# trade-list sample shows for a Margin trade — the positions value is not documented.
POSITION_INTRADAY_CASH = dict(
    DOCS_POSITION_OPTION_ROW, segment="M", product_type="Margin", exchange_code="NSE",
    stock_code="ITC", expiry_date=None, strike_price=None, right=None, action="Buy",
    quantity="10", average_price="452.20", ltp="451.95", underlying=None,
)
POSITION_DELIVERY_CASH = dict(POSITION_INTRADAY_CASH, product_type="Cash", action="Sell", quantity="4")


def ok(success) -> tuple:
    return 200, {"Success": success, "Status": 200, "Error": None}


class Wire:
    """Answers every httpx call from `routes` (last path segment → (status, body)) and keeps the
    requests. A body that is a str is sent as plain text, anything else as JSON."""

    def __init__(self, monkeypatch, routes: dict):
        self.requests: list[httpx.Request] = []
        real_client = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            status, body = routes[request.url.path.rsplit("/", 1)[-1]]
            if isinstance(body, str):
                return httpx.Response(status, text=body)
            return httpx.Response(status, json=body)

        monkeypatch.setattr(
            httpx, "AsyncClient",
            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        )

    def sent(self, path: str) -> httpx.Request:
        return next(r for r in self.requests if r.url.path.endswith("/" + path))


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("BROKER_ICICIDIRECT_API_KEY", APP_KEY)
    monkeypatch.setenv("BROKER_ICICIDIRECT_API_SECRET", APP_SECRET)


@pytest.fixture
def connectable(monkeypatch):
    """Sign-in is switched off in the module; these tests switch it on to pin the pieces that are
    ready for the day it can be."""
    monkeypatch.setattr(icici, "CONNECTABLE", True)


def run(coro):
    return asyncio.run(coro)


# ── Sign-in is switched off ──────────────────────────────────────────────
def test_adapter_is_registered_but_not_connectable(keys):
    adapter = registry.get("icicidirect")
    assert (adapter.SLUG, adapter.DISPLAY, adapter.AUTH_STYLE) == ("icicidirect", "ICICI Direct", "oauth")
    assert adapter.CONNECTABLE is False and adapter.IMPLEMENTED is False
    assert adapter.CALLBACK_CODE_PARAMS == ("apisession",)
    row = next(r for r in registry.list_supported() if r["slug"] == "icicidirect")
    assert row["implemented"] is False
    assert not row.get("connectable")


def test_auth_url_refuses_while_sign_in_is_off(keys):
    with pytest.raises(icici.IciciDirectNotSupported) as err:
        icici.auth_url(state="s1", redirect_uri="https://nivesh.example/cb")
    assert str(err.value) == icici.CONNECT_BLOCKED_REASON
    assert APP_KEY not in str(err.value)


def test_exchange_refuses_while_sign_in_is_off_and_calls_nobody(keys, monkeypatch):
    wire = Wire(monkeypatch, {"customerdetails": (200, DOCS_CUSTOMER_DETAILS)})
    with pytest.raises(icici.IciciDirectNotSupported):
        run(icici.exchange_code(code=SESSION_KEY, state="s1", redirect_uri="https://nivesh.example/cb"))
    assert wire.requests == []


# ── Login URL ────────────────────────────────────────────────────────────
def test_auth_url_is_the_documented_login_url_with_the_key_url_encoded(keys, connectable):
    url = icici.auth_url(state="state-abc", redirect_uri="https://nivesh.example/cb?broker=icicidirect")
    assert url == "https://api.icicidirect.com/apiuser/login?api_key=8g791%5EN029R47I831B8153%3D%5EO2f%237u8g"
    # Breeze documents no `state` or redirect parameter; neither is sent.
    assert "state-abc" not in url and "nivesh.example" not in url


def test_auth_url_needs_the_app_key(connectable, monkeypatch):
    monkeypatch.delenv("BROKER_ICICIDIRECT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="BROKER_ICICIDIRECT_API_KEY is not configured"):
        icici.auth_url(state="s1", redirect_uri="https://nivesh.example/cb")


# ── Session exchange ─────────────────────────────────────────────────────
def test_exchange_turns_the_session_key_into_a_session_token(keys, connectable, monkeypatch):
    wire = Wire(monkeypatch, {"customerdetails": (200, DOCS_CUSTOMER_DETAILS)})
    before = datetime.now(timezone.utc)
    token = run(icici.exchange_code(code=SESSION_KEY, state="s1", redirect_uri="https://nivesh.example/cb"))

    request = wire.sent("customerdetails")
    assert request.method == "GET"
    assert str(request.url) == "https://api.icicidirect.com/breezeapi/api/v1/customerdetails"
    assert json.loads(request.content) == {"SessionToken": SESSION_KEY, "AppKey": APP_KEY}
    # /customerdetails is the one call that takes no signing headers.
    assert not [h for h in request.headers if h.lower().startswith("x-")]

    assert token.token == SESSION_TOKEN
    assert set(token.extras) == {"user_id", "expires_at"}
    assert token.extras["user_id"] == "379XTZ300"
    expires = datetime.fromisoformat(token.extras["expires_at"])
    assert expires.utcoffset() == timedelta(0)
    assert before < expires <= before + timedelta(hours=24, seconds=5)
    assert expires.astimezone(icici._IST).strftime("%H:%M:%S") == "00:00:00"


@pytest.mark.parametrize("now_ist, expires_utc", [
    ("2025-04-17T11:50:42+05:30", "2025-04-17T18:30:00+00:00"),   # midnight comes before 24h
    ("2025-04-17T23:59:30+05:30", "2025-04-17T18:30:00+00:00"),
    ("2025-04-18T00:00:00+05:30", "2025-04-18T18:30:00+00:00"),   # at midnight: the next one, 24h on
])
def test_session_ends_at_the_next_midnight_ist(now_ist, expires_utc):
    assert icici._session_expiry(datetime.fromisoformat(now_ist)).isoformat() == expires_utc


def test_exchange_with_an_unknown_app_key_is_a_config_error_not_an_expired_session(keys, connectable, monkeypatch):
    Wire(monkeypatch, {"customerdetails": OBSERVED_UNKNOWN_KEY_ON_EXCHANGE})
    with pytest.raises(icici.IciciDirectError) as err:
        run(icici.exchange_code(code=SESSION_KEY, state="s1", redirect_uri="https://nivesh.example/cb"))
    assert not isinstance(err.value, icici.IciciDirectSessionExpired)
    assert "BROKER_ICICIDIRECT_API_KEY" in str(err.value)
    assert APP_KEY not in str(err.value) and SESSION_KEY not in str(err.value)


def test_exchange_with_a_refused_session_key_fails(keys, connectable, monkeypatch):
    # "Invalid session." is the text ICICI's SDK checks for; the envelope around it is CONSTRUCTED.
    Wire(monkeypatch, {"customerdetails": (200, {"Success": None, "Status": 500, "Error": "Invalid session."})})
    with pytest.raises(icici.IciciDirectSessionExpired) as err:
        run(icici.exchange_code(code=SESSION_KEY, state="s1", redirect_uri="https://nivesh.example/cb"))
    assert SESSION_KEY not in str(err.value) and APP_KEY not in str(err.value)


def test_exchange_without_a_session_token_in_the_answer_fails(keys, connectable, monkeypatch):
    details = {k: v for k, v in DOCS_CUSTOMER_DETAILS["Success"].items() if k != "session_token"}
    Wire(monkeypatch, {"customerdetails": ok(details)})
    with pytest.raises(icici.IciciDirectError, match="no session token"):
        run(icici.exchange_code(code=SESSION_KEY, state="s1", redirect_uri="https://nivesh.example/cb"))


def test_exchange_needs_both_app_secrets_before_calling_icici(connectable, monkeypatch):
    monkeypatch.setenv("BROKER_ICICIDIRECT_API_KEY", APP_KEY)
    monkeypatch.delenv("BROKER_ICICIDIRECT_API_SECRET", raising=False)
    wire = Wire(monkeypatch, {"customerdetails": (200, DOCS_CUSTOMER_DETAILS)})
    with pytest.raises(RuntimeError, match="BROKER_ICICIDIRECT_API_SECRET is not configured"):
        run(icici.exchange_code(code=SESSION_KEY, state="s1", redirect_uri="https://nivesh.example/cb"))
    assert wire.requests == []


# ── Request signing ──────────────────────────────────────────────────────
def test_timestamp_is_iso8601_utc_with_zero_milliseconds():
    # DOCS: X-Timestamp example `2024-06-01T10:23:56.000Z`.
    moment = datetime(2024, 6, 1, 15, 53, 56, 987654, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert icici._timestamp(moment.astimezone(timezone.utc)) == "2024-06-01T10:23:56.000Z"


def test_checksum_is_sha256_of_timestamp_body_secret():
    # The reference gives the recipe, not a worked digest; these two were computed with coreutils
    # `sha256sum` over the documented concatenation (timestamp + JSON body + secret_key).
    ts = "2024-06-01T10:23:56.000Z"
    assert icici._checksum(ts, "{}", APP_SECRET) == (
        "ac848eede0c00c494392ea17f1df3f46844c15b5a3935bdcfae8e8d7f057fcf9"
    )
    body = '{"exchange_code":"NSE","from_date":"","to_date":"","stock_code":"","portfolio_type":""}'
    assert icici._checksum(ts, body, APP_SECRET) == (
        "56627c28088e335d5fe6b2007a0154386f6dcb4b6425746af1bb653e7a41c283"
    )


def test_a_read_is_a_get_with_a_json_body_signed_over_exactly_what_is_sent(keys, monkeypatch):
    wire = Wire(monkeypatch, {"portfoliopositions": ok([])})
    run(icici.fetch_hub_positions(TOKEN, "net"))

    request = wire.sent("portfoliopositions")
    assert request.method == "GET"
    assert str(request.url) == "https://api.icicidirect.com/breezeapi/api/v1/portfoliopositions"
    assert request.content == b"{}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-AppKey"] == APP_KEY
    assert request.headers["X-SessionToken"] == SESSION_TOKEN
    timestamp = request.headers["X-Timestamp"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.000Z", timestamp)
    sent_at = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - sent_at).total_seconds()) < 60
    # DOCS recipe, verbatim: sha256((time_stamp + payload + secret_key).encode("utf-8")).hexdigest()
    expected = hashlib.sha256((timestamp + request.content.decode() + APP_SECRET).encode("utf-8")).hexdigest()
    assert request.headers["X-Checksum"] == "token " + expected
    assert APP_SECRET not in str(dict(request.headers))


# ── Holdings ─────────────────────────────────────────────────────────────
def test_holdings_are_the_demat_rows_priced_from_the_nse_portfolio(keys, monkeypatch):
    wire = Wire(monkeypatch, {
        "dematholdings": ok([DOCS_DEMAT_ROW]),
        "portfolioholdings": ok([PORTFOLIO_EQUITY_ROW]),
    })
    holdings = run(icici.fetch_holdings(TOKEN))

    assert holdings == [Holding(
        isin="INE694A01020", symbol="UNITEC", asset_type="equity", quantity=1.0,
        avg_price=2.35, current_price=2.90, name=None, sector=None, exchange=None,
        source_id="icicidirect:UNITEC",
    )]
    assert wire.sent("dematholdings").content == b"{}"
    portfolio = wire.sent("portfolioholdings")
    assert portfolio.content == (
        b'{"exchange_code":"NSE","from_date":"","to_date":"","stock_code":"","portfolio_type":""}'
    )
    ts = portfolio.headers["X-Timestamp"]
    assert portfolio.headers["X-Checksum"] == "token " + icici._checksum(ts, portfolio.content.decode(), APP_SECRET)


def test_holdings_keep_only_what_icici_returned(keys, monkeypatch):
    etf = dict(DOCS_DEMAT_ROW, stock_code="goldbees", stock_ISIN="inf204kb17i5", quantity="12")  # CONSTRUCTED
    no_isin = dict(DOCS_DEMAT_ROW, stock_code="ABCLTD", stock_ISIN=None, quantity="3")           # CONSTRUCTED
    blank = dict(DOCS_DEMAT_ROW, stock_code="")
    Wire(monkeypatch, {
        "dematholdings": ok([DOCS_DEMAT_ROW, etf, no_isin, blank]),
        # A derivative row and an equity row with no demat row: neither becomes a holding.
        "portfolioholdings": ok([DOCS_PORTFOLIO_OPTION_ROW, dict(PORTFOLIO_EQUITY_ROW, stock_code="ONLYPF")]),
    })
    holdings = run(icici.fetch_holdings(TOKEN))

    assert [(h.symbol, h.isin, h.asset_type, h.quantity) for h in holdings] == [
        ("UNITEC", "INE694A01020", "equity", 1.0),
        ("GOLDBEES", "INF204KB17I5", "etf", 12.0),
        ("ABCLTD", None, "equity", 3.0),
    ]
    # No portfolio row for these stock codes → no price was returned → 0, never a guess.
    assert [(h.avg_price, h.current_price) for h in holdings] == [(0.0, 0.0)] * 3


def test_no_holdings_is_an_empty_list(keys, monkeypatch):
    Wire(monkeypatch, {"dematholdings": ok(None), "portfolioholdings": ok(None)})
    assert run(icici.fetch_holdings(TOKEN)) == []


# ── Positions ────────────────────────────────────────────────────────────
def test_net_positions_option_future_and_intraday_cash(keys, monkeypatch):
    Wire(monkeypatch, {"portfoliopositions": ok([
        DOCS_POSITION_OPTION_ROW, POSITION_SHORT_PUT, POSITION_FUTURE,
        POSITION_INTRADAY_CASH, POSITION_DELIVERY_CASH,
    ])})
    flat_call, short_put, future, intraday, delivery = run(icici.fetch_hub_positions(TOKEN, "net"))

    # DOCS row: a flat NIFTY call. `pnl` is null in the sample → 0, not computed.
    assert flat_call == HubPosition(
        symbol="NIFTY", exchange="NFO", quantity=0.0, avg_price=0.0, last_price=29.95, pnl=0.0,
        product=None, product_raw="Options", segment="fno", is_intraday=False,
        instrument_type="CE", expiry="2025-02-27", strike=24800.0, kind="net", name=None,
    )
    assert short_put == HubPosition(
        symbol="NIFTY", exchange="NFO", quantity=-75.0, avg_price=112.5, last_price=98.4, pnl=1057.5,
        product=None, product_raw="Options", segment="fno", is_intraday=False,
        instrument_type="PE", expiry="2025-02-27", strike=24000.0, kind="net", name=None,
    )
    assert future == HubPosition(
        symbol="RELIND", exchange="NFO", quantity=250.0, avg_price=1290.4, last_price=1301.15, pnl=0.0,
        product=None, product_raw="Futures", segment="fno", is_intraday=False,
        instrument_type="FUT", expiry="2025-02-27", strike=None, kind="net", name=None,
    )
    assert intraday == HubPosition(
        symbol="ITC", exchange="NSE", quantity=10.0, avg_price=452.20, last_price=451.95, pnl=0.0,
        product="intraday", product_raw="Margin", segment="equity", is_intraday=True,
        instrument_type=None, expiry=None, strike=None, kind="net", name=None,
    )
    assert (delivery.product, delivery.product_raw, delivery.is_intraday, delivery.quantity) == (
        "delivery", "Cash", False, -4.0,
    )


def test_day_positions_are_refused_not_relabelled(keys, monkeypatch):
    wire = Wire(monkeypatch, {"portfoliopositions": ok([POSITION_INTRADAY_CASH])})
    with pytest.raises(icici.IciciDirectNotSupported, match="'day'"):
        run(icici.fetch_hub_positions(TOKEN, "day"))
    assert wire.requests == []
    # hub_reads recognises the class by this suffix and reports "not supported".
    assert icici.IciciDirectNotSupported.__name__.endswith("NotSupported")


def test_fetch_positions_is_the_net_book_in_the_base_shape(keys, monkeypatch):
    Wire(monkeypatch, {"portfoliopositions": ok([POSITION_SHORT_PUT, POSITION_INTRADAY_CASH])})
    assert run(icici.fetch_positions(TOKEN)) == [
        Position(symbol="NIFTY", exchange="NFO", quantity=-75.0, avg_price=112.5, pnl=1057.5, product="Options"),
        Position(symbol="ITC", exchange="NSE", quantity=10.0, avg_price=452.20, pnl=0.0, product="Margin"),
    ]


def test_no_positions_is_an_empty_list(keys, monkeypatch):
    Wire(monkeypatch, {"portfoliopositions": ok(None)})
    assert run(icici.fetch_hub_positions(TOKEN, "net")) == []


# ── Funds ────────────────────────────────────────────────────────────────
def test_funds_are_the_allocated_and_blocked_amounts_across_segments(keys, monkeypatch):
    Wire(monkeypatch, {"funds": ok(DOCS_FUNDS)})
    funds = run(icici.fetch_funds(TOKEN))
    assert funds == Funds(available_cash=pytest.approx(800000000.0 - 12500000.53), used_margin=12500000.53)


# ── A rejected session, and other failures ───────────────────────────────
@pytest.mark.parametrize("answer", [
    (401, {"Status": 401, "Error": "Unauthorized"}),                      # CONSTRUCTED body
    (403, "Forbidden"),                                                    # CONSTRUCTED body
    (200, {"Success": None, "Status": 500, "Error": "Invalid session."}),  # SDK text, CONSTRUCTED envelope
])
@pytest.mark.parametrize("read", ["holdings", "positions", "funds"])
def test_a_rejected_session_raises_session_expired(keys, monkeypatch, answer, read):
    Wire(monkeypatch, {p: answer for p in ("dematholdings", "portfolioholdings", "portfoliopositions", "funds")})
    call = {
        "holdings": lambda: icici.fetch_holdings(TOKEN),
        "positions": lambda: icici.fetch_hub_positions(TOKEN, "net"),
        "funds": lambda: icici.fetch_funds(TOKEN),
    }[read]
    with pytest.raises(icici.IciciDirectSessionExpired) as err:
        run(call())
    # hub_reads ends the session for any exception class named `…SessionExpired`.
    assert type(err.value).__name__.endswith("SessionExpired")
    text = str(err.value)
    assert SESSION_TOKEN not in text and APP_KEY not in text and APP_SECRET not in text


def test_an_unknown_app_key_on_a_read_is_not_a_session_expiry(keys, monkeypatch):
    Wire(monkeypatch, {"portfoliopositions": OBSERVED_UNKNOWN_KEY_ON_READ})
    with pytest.raises(icici.IciciDirectError) as err:
        run(icici.fetch_hub_positions(TOKEN, "net"))
    assert not isinstance(err.value, icici.IciciDirectSessionExpired)
    assert "BROKER_ICICIDIRECT_API_KEY" in str(err.value) and APP_KEY not in str(err.value)


@pytest.mark.parametrize("status", [200, 401, 403])
def test_a_static_ip_refusal_is_not_a_session_expiry(keys, monkeypatch, status):
    # The text is quoted in ICICI's FAQ; the status and envelope it arrives in are CONSTRUCTED.
    denied = "Request Denied: The IP address used does not match with the static IP declared when this API key was created"
    Wire(monkeypatch, {"portfoliopositions": (status, {"Success": None, "Status": 500, "Error": denied})})
    with pytest.raises(icici.IciciDirectError, match="static IP registered with the app key") as err:
        run(icici.fetch_hub_positions(TOKEN, "net"))
    assert not isinstance(err.value, icici.IciciDirectSessionExpired)


@pytest.mark.parametrize("answer, label", [
    ((500, "upstream timeout tok-LEAK"), "HTTP 500, API status None"),
    ((200, {"Success": None, "Status": 500, "Error": "tok-LEAK went wrong"}), "HTTP 200, API status 500"),
    ((200, "not json tok-LEAK"), "HTTP 200, API status None"),
])
def test_any_other_failure_is_a_read_error_that_never_quotes_the_broker(keys, monkeypatch, answer, label):
    Wire(monkeypatch, {"dematholdings": answer})
    with pytest.raises(icici.IciciDirectError) as err:
        run(icici.fetch_holdings(TOKEN))
    assert not isinstance(err.value, icici.IciciDirectSessionExpired)
    assert str(err.value) == f"ICICI Direct demat holdings failed ({label})"


# ── Missing config ───────────────────────────────────────────────────────
@pytest.mark.parametrize("missing", ["BROKER_ICICIDIRECT_API_KEY", "BROKER_ICICIDIRECT_API_SECRET"])
def test_reads_need_both_app_secrets_and_call_nobody_without_them(keys, monkeypatch, missing):
    monkeypatch.delenv(missing)
    wire = Wire(monkeypatch, {"dematholdings": ok([DOCS_DEMAT_ROW]), "portfolioholdings": ok([])})
    with pytest.raises(RuntimeError, match=f"{missing} is not configured"):
        run(icici.fetch_holdings(TOKEN))
    assert wire.requests == []
