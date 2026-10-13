"""services/brokers/groww.py — pasted-token sign-in, holdings, positions, margin, Fenix headers.

No network and no Groww account: every call is answered by an `httpx.MockTransport`, so nothing in
this file proves behaviour against the live Groww API.

Payloads are the samples on Groww's official docs pages, copied as published:
    https://groww.in/trade-api/docs/curl/user        GET /v1/user/detail
    https://groww.in/trade-api/docs/curl/portfolio   GET /v1/holdings/user, GET /v1/positions/user
    https://groww.in/trade-api/docs/python-sdk/portfolio   (the positions row with `segment`)
    https://groww.in/trade-api/docs/curl/margin      GET /v1/margins/detail/user
    https://groww.in/trade-api/docs/curl             the FAILURE envelope
The F&O and intraday position rows are that same documented row shape with other values; their
trading symbols are the ones shown on https://groww.in/trade-api/docs/curl/instruments and
.../python-sdk/instruments.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from services.brokers import groww, registry
from services.brokers.base import AccessToken, Funds, Holding, HubPosition, Position

# Stands in for a Groww access token. It must never appear in an error message.
SECRET = "tok-GROWW-SECRET-51c9"

USER_DETAIL = {
    "status": "SUCCESS",
    "payload": {
        "vendor_user_id": "d86890d1-c60d-4ebd-9730-4f451670",
        "ucc": "924189",
        "nse_enabled": True,
        "bse_enabled": True,
        "ddpi_enabled": False,
        "active_segments": ["CASH", "FNO"],
    },
}

HOLDINGS = {
    "status": "SUCCESS",
    "payload": {
        "holdings": [
            {
                "isin": "INE545U01014",
                "trading_symbol": "RELIANCE",
                "quantity": 10,
                "average_price": 100,
                "pledge_quantity": 2,
                "demat_locked_quantity": 1,
                "groww_locked_quantity": 1.5,
                "repledge_quantity": 0.5,
                "t1_quantity": 3,
                "demat_free_quantity": 5,
                "corporate_action_additional_quantity": 1,
                "active_demat_transfer_quantity": 1,
            },
        ],
    },
}

# The documented positions row (delivery, cash).
DOC_POSITION = {
    "trading_symbol": "RELIANCE",
    "segment": "CASH",
    "credit_quantity": 10,
    "credit_price": 12500,
    "debit_quantity": 5,
    "debit_price": 12000,
    "carry_forward_credit_quantity": 8,
    "carry_forward_credit_price": 12300,
    "carry_forward_debit_quantity": 3,
    "carry_forward_debit_price": 11800,
    "exchange": "NSE",
    "symbol_isin": "INE123A01016",
    "quantity": 15,
    "product": "CNC",
    "net_carry_forward_quantity": 10,
    "net_price": 12400,
    "net_carry_forward_price": 12200,
    "realised_pnl": 500,
}


def _row(**changes) -> dict:
    return {**DOC_POSITION, **changes}


OPTION = _row(
    trading_symbol="BANKNIFTY25DEC27000PE", segment="FNO", exchange="NSE", symbol_isin="",
    quantity=35, product="NRML", net_price=212.5, realised_pnl=0,
)
FUTURE = _row(
    trading_symbol="ASIANPAINT25FEBFUT", segment="FNO", exchange="NSE", symbol_isin="",
    quantity=-200, product="NRML", net_price=2310.4, realised_pnl=-1250.5,
)
INTRADAY_CASH = _row(quantity=-4, product="MIS", net_price=1290.25, realised_pnl=36)

POSITIONS = {
    "status": "SUCCESS",
    "payload": {"positions": [OPTION, FUTURE, INTRADAY_CASH, DOC_POSITION]},
}

MARGIN = {
    "status": "SUCCESS",
    "payload": {
        "clear_cash": 5000,
        "net_margin_used": 35000,
        "brokerage_and_charges": 200,
        "collateral_used": 3000,
        "collateral_available": 7000,
        "adhoc_margin": 1500,
        "fno_margin_details": {
            "net_fno_margin_used": 15000,
            "span_margin_used": 7000,
            "exposure_margin_used": 4000,
            "future_balance_available": 3000,
            "option_buy_balance_available": 11000,
            "option_sell_balance_available": 1000,
        },
        "equity_margin_details": {
            "net_equity_margin_used": 10000,
            "cnc_margin_used": 5000,
            "mis_margin_used": 3000,
            "cnc_balance_available": 9000,
            "mis_balance_available": 1000,
        },
    },
}

FAILURE = {
    "status": "FAILURE",
    "error": {"code": "GA005", "message": "User not authorised to perform this operation", "metadata": None},
}


class FakeGroww:
    """Answers `api.groww.in` by path and keeps the requests it was sent."""

    def __init__(self) -> None:
        self.replies: dict[str, tuple[int, object]] = {}
        self.requests: list[httpx.Request] = []

    def reply(self, path: str, body: object, status: int = 200) -> None:
        self.replies[path] = (status, body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.replies[request.url.path]
        return httpx.Response(status, json=body, request=request)


@pytest.fixture
def api(monkeypatch) -> FakeGroww:
    fake = FakeGroww()
    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(groww.httpx, "AsyncClient", client)
    return fake


def _token() -> AccessToken:
    return AccessToken(token=SECRET, extras={"user_id": "924189"})


def _sign_in(code: str) -> AccessToken:
    return asyncio.run(groww.exchange_code(code=code, state="st", redirect_uri="https://nivesh.example/cb"))


# ── Sign-in: the pasted access token ─────────────────────────────────────
@pytest.mark.parametrize("code", [
    SECRET,
    f"  {SECRET}\n",
    f"Bearer {SECRET}",
    json.dumps({"access_token": SECRET}),
])
def test_sign_in_accepts_the_token_after_one_profile_read(api, code):
    api.reply("/v1/user/detail", USER_DETAIL)

    got = _sign_in(code)

    assert got.token == SECRET
    assert got.extras["user_id"] == "924189"          # the UCC, not the vendor id
    assert set(got.extras) == {"user_id", "expires_at"}
    assert len(api.requests) == 1                      # one cheap read, nothing else
    sent = api.requests[0]
    assert sent.method == "GET"
    assert str(sent.url) == "https://api.groww.in/v1/user/detail"
    assert sent.headers["Authorization"] == f"Bearer {SECRET}"
    assert sent.headers["Accept"] == "application/json"
    assert sent.headers["X-API-VERSION"] == "1.0"


def test_sign_in_expiry_is_the_next_6am_ist_in_utc(api):
    api.reply("/v1/user/detail", USER_DETAIL)
    before = datetime.now(timezone.utc)

    expires = datetime.fromisoformat(_sign_in(SECRET).extras["expires_at"])

    assert expires.utcoffset().total_seconds() == 0
    assert (expires.hour, expires.minute, expires.second) == (0, 30, 0)   # 06:00 IST
    assert 0 < (expires - before).total_seconds() <= 24 * 3600


@pytest.mark.parametrize("now, expected", [
    # 05:59 IST on the 14th -> 06:00 IST the same morning
    (datetime(2026, 10, 14, 0, 29, tzinfo=timezone.utc), datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc)),
    # exactly 06:00 IST -> that cut-off has passed; the next one
    (datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc), datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)),
    # 19:00 IST on the 13th -> 06:00 IST on the 14th
    (datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc), datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc)),
])
def test_next_expiry(now, expected):
    assert groww._next_expiry(now) == expected


def test_sign_in_falls_back_to_the_vendor_user_id(api):
    payload = {k: v for k, v in USER_DETAIL["payload"].items() if k != "ucc"}
    api.reply("/v1/user/detail", {"status": "SUCCESS", "payload": payload})

    assert _sign_in(SECRET).extras["user_id"] == "d86890d1-c60d-4ebd-9730-4f451670"


@pytest.mark.parametrize("code", ["", "   ", "{}", json.dumps({"access_token": ""}), json.dumps({"client_id": "924189"})])
def test_sign_in_without_a_token_is_refused_before_any_request(api, code):
    with pytest.raises(RuntimeError, match="access_token required"):
        _sign_in(code)
    assert api.requests == []


def test_sign_in_malformed_body_does_not_echo_what_was_pasted(api):
    with pytest.raises(RuntimeError) as err:
        _sign_in('{"access_token": "' + SECRET)
    assert "malformed" in str(err.value)
    assert SECRET not in str(err.value)
    assert api.requests == []


@pytest.mark.parametrize("status", [401, 403])
def test_sign_in_with_a_rejected_or_expired_token(api, status):
    api.reply("/v1/user/detail", FAILURE, status=status)

    with pytest.raises(groww.GrowwTokenRejected) as err:
        _sign_in(SECRET)

    assert f"HTTP {status}" in str(err.value)
    assert SECRET not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_sign_in_when_groww_is_down_is_not_reported_as_a_bad_token(api):
    api.reply("/v1/user/detail", {"status": "FAILURE"}, status=503)

    with pytest.raises(httpx.HTTPStatusError) as err:
        _sign_in(SECRET)

    assert err.value.response.status_code == 503
    assert SECRET not in str(err.value)


def test_sign_in_refuses_a_failure_body_sent_with_http_200(api):
    api.reply("/v1/user/detail", FAILURE)

    with pytest.raises(groww.GrowwError, match="GA005"):
        _sign_in(SECRET)


# ── No operator configuration ────────────────────────────────────────────
def test_works_with_no_groww_app_keys_configured(api, monkeypatch):
    """The user brings the token: nothing reads BROKER_GROWW_API_KEY / _SECRET."""
    monkeypatch.delenv("BROKER_GROWW_API_KEY", raising=False)
    monkeypatch.delenv("BROKER_GROWW_API_SECRET", raising=False)
    api.reply("/v1/user/detail", USER_DETAIL)
    api.reply("/v1/holdings/user", HOLDINGS)

    assert groww.auth_url(state="abc123", redirect_uri="https://nivesh.example/cb") == "/broker-credentials/groww?state=abc123"
    token = _sign_in(SECRET)
    assert len(asyncio.run(groww.fetch_holdings(token))) == 1


# ── Holdings ─────────────────────────────────────────────────────────────
def test_holdings_mapping(api):
    api.reply("/v1/holdings/user", HOLDINGS)

    got = asyncio.run(groww.fetch_holdings(_token()))

    assert got == [Holding(
        isin="INE545U01014",
        symbol="RELIANCE",
        asset_type="equity",
        quantity=10.0,
        avg_price=100.0,
        current_price=0.0,     # Groww's holdings carry no last price
        name="RELIANCE",
        sector=None,
        exchange=None,         # ... and no exchange
        source_id="RELIANCE",
    )]
    sent = api.requests[0]
    assert str(sent.url) == "https://api.groww.in/v1/holdings/user"
    assert sent.headers["Authorization"] == f"Bearer {SECRET}"
    assert sent.headers["X-API-VERSION"] == "1.0"


def test_holdings_etf_detection_blank_rows_and_none(api):
    rows = [
        {"isin": "inf204kb14i2", "trading_symbol": "niftybees", "quantity": 25, "average_price": 251.4},
        {"isin": "INE000000000", "trading_symbol": "", "quantity": 1, "average_price": 1},
    ]
    api.reply("/v1/holdings/user", {"status": "SUCCESS", "payload": {"holdings": rows}})
    got = asyncio.run(groww.fetch_holdings(_token()))
    assert [(h.symbol, h.isin, h.asset_type, h.quantity) for h in got] == [("NIFTYBEES", "INF204KB14I2", "etf", 25.0)]

    api.reply("/v1/holdings/user", {"status": "SUCCESS", "payload": {"holdings": []}})
    assert asyncio.run(groww.fetch_holdings(_token())) == []


@pytest.mark.parametrize("status", [401, 403])
def test_read_with_a_rejected_token_raises_http_status_error(api, status):
    api.reply("/v1/holdings/user", FAILURE, status=status)
    api.reply("/v1/positions/user", FAILURE, status=status)

    for read in (groww.fetch_holdings(_token()), groww.fetch_hub_positions(_token(), "net")):
        with pytest.raises(httpx.HTTPStatusError) as err:
            asyncio.run(read)
        assert err.value.response.status_code == status
        assert SECRET not in str(err.value)


def test_a_failure_body_is_an_error_not_an_empty_portfolio(api):
    api.reply("/v1/holdings/user", FAILURE)

    with pytest.raises(groww.GrowwError) as err:
        asyncio.run(groww.fetch_holdings(_token()))

    assert "GA005" in str(err.value)
    assert "not authorised" not in str(err.value)   # Groww's free text is left out


# ── Positions ────────────────────────────────────────────────────────────
def test_net_positions_option_future_intraday_and_delivery(api):
    api.reply("/v1/positions/user", POSITIONS)

    got = asyncio.run(groww.fetch_hub_positions(_token(), "net"))

    assert all(isinstance(p, HubPosition) for p in got)
    option, future, intraday, delivery = got
    assert option == HubPosition(
        symbol="BANKNIFTY25DEC27000PE", exchange="NFO", quantity=35.0, avg_price=212.5,
        last_price=None, pnl=0.0, product="carryforward", product_raw="NRML",
        segment="fno", is_intraday=False, instrument_type="PE",
        expiry=None, strike=None, kind="net", name=None,
    )
    assert future == HubPosition(
        symbol="ASIANPAINT25FEBFUT", exchange="NFO", quantity=-200.0, avg_price=2310.4,
        last_price=None, pnl=-1250.5, product="carryforward", product_raw="NRML",
        segment="fno", is_intraday=False, instrument_type="FUT",
        expiry=None, strike=None, kind="net", name=None,
    )
    # RELIANCE ends in "CE": a cash row is never read as an option.
    assert intraday == HubPosition(
        symbol="RELIANCE", exchange="NSE", quantity=-4.0, avg_price=1290.25,
        last_price=None, pnl=36.0, product="intraday", product_raw="MIS",
        segment="equity", is_intraday=True, instrument_type=None,
        expiry=None, strike=None, kind="net", name=None,
    )
    assert delivery == HubPosition(
        symbol="RELIANCE", exchange="NSE", quantity=15.0, avg_price=12400.0,
        last_price=None, pnl=500.0, product="delivery", product_raw="CNC",
        segment="equity", is_intraday=False, instrument_type=None,
        expiry=None, strike=None, kind="net", name=None,
    )
    assert len(api.requests) == 1
    assert str(api.requests[0].url) == "https://api.groww.in/v1/positions/user"   # no segment filter


def test_net_positions_bse_derivative_call_and_unknown_product(api):
    rows = [
        _row(trading_symbol="SENSEX25DEC85000CE", segment="FNO", exchange="BSE", quantity=20, product="NRML"),
        _row(product="XYZ"),
        _row(product=None),
    ]
    api.reply("/v1/positions/user", {"status": "SUCCESS", "payload": {"positions": rows}})

    call, unknown, missing = asyncio.run(groww.fetch_hub_positions(_token(), "net"))

    assert (call.exchange, call.segment, call.instrument_type) == ("BFO", "fno", "CE")
    assert (unknown.product, unknown.product_raw, unknown.is_intraday) == (None, "XYZ", False)
    assert (missing.product, missing.product_raw, missing.is_intraday) == (None, None, False)


def test_day_positions_are_not_supported_and_make_no_request(api):
    api.reply("/v1/positions/user", POSITIONS)

    with pytest.raises(groww.GrowwDayPositionsNotSupported) as err:
        asyncio.run(groww.fetch_hub_positions(_token(), "day"))

    # What `hub_reads._is_not_supported` matches on.
    assert isinstance(err.value, NotImplementedError)
    assert type(err.value).__name__.endswith("NotSupported")
    assert api.requests == []


def test_unknown_position_kind(api):
    with pytest.raises(ValueError):
        asyncio.run(groww.fetch_hub_positions(_token(), "week"))
    assert api.requests == []


def test_fetch_positions_is_the_net_book(api):
    api.reply("/v1/positions/user", POSITIONS)

    got = asyncio.run(groww.fetch_positions(_token()))

    assert got == [
        Position(symbol="BANKNIFTY25DEC27000PE", exchange="NFO", quantity=35.0, avg_price=212.5, pnl=0.0, product="NRML"),
        Position(symbol="ASIANPAINT25FEBFUT", exchange="NFO", quantity=-200.0, avg_price=2310.4, pnl=-1250.5, product="NRML"),
        Position(symbol="RELIANCE", exchange="NSE", quantity=-4.0, avg_price=1290.25, pnl=36.0, product="MIS"),
        Position(symbol="RELIANCE", exchange="NSE", quantity=15.0, avg_price=12400.0, pnl=500.0, product="CNC"),
    ]


def test_no_positions(api):
    api.reply("/v1/positions/user", {"status": "SUCCESS", "payload": {"positions": []}})
    assert asyncio.run(groww.fetch_hub_positions(_token(), "net")) == []
    assert asyncio.run(groww.fetch_positions(_token())) == []


# ── Margin ───────────────────────────────────────────────────────────────
def test_funds_mapping(api):
    api.reply("/v1/margins/detail/user", MARGIN)

    got = asyncio.run(groww.fetch_funds(_token()))

    assert got == Funds(available_cash=5000.0, collateral=7000.0, used_margin=35000.0)
    assert str(api.requests[0].url) == "https://api.groww.in/v1/margins/detail/user"


# ── The registered adapter ───────────────────────────────────────────────
def test_registered_adapter_surface():
    adapter = registry.get("groww")

    assert (adapter.SLUG, adapter.DISPLAY, adapter.AUTH_STYLE) == ("groww", "Groww", "apikey")
    assert getattr(adapter, "IMPLEMENTED", True) is True     # the real adapter, not the `_stub` placeholder
    for name in (
        "auth_url", "exchange_code", "fetch_holdings", "fetch_positions",
        "fetch_hub_positions", "fetch_funds",
    ):
        assert callable(getattr(adapter, name)), name
    # No redirect, so no callback parameter of its own.
    assert not hasattr(adapter, "CALLBACK_CODE_PARAMS")
    # Reads use Groww's own REST API: no Fenix hook, so the hub never reads Groww through Fenix.
    assert not hasattr(adapter, "FENIX_CLASS") and not hasattr(adapter, "fenix_headers")


def test_adapter_is_read_only():
    public = [n for n in dir(groww) if not n.startswith("_")] + [n for n in dir(registry.get("groww")) if not n.startswith("_")]
    assert not [n for n in public if any(w in n.lower() for w in ("order", "place", "modify", "cancel"))]
