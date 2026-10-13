"""services/brokers/angelone.py — redirect sign-in, holdings, positions, funds, Fenix headers.

No network and no Angel One account: every call is answered by an `httpx.MockTransport`, so nothing
in this file proves behaviour against the live SmartAPI.

Payloads are the samples on Angel One's official SmartAPI docs pages, copied as published:
    https://smartapi.angelone.in/docs/User               Get Profile, Get RMS Limit
    https://smartapi.angelone.in/docs/Portfolio          Get All Holdings, Get Position
    https://smartapi.angelone.in/docs/ResponseStructure  the failed-response envelope
    https://smartapi.angelone.in/docs/Exceptions         the error codes (AG8001 Invalid Token, ...)
    https://smartapi.angelone.in/docs/RateLimit          "403 Access denied because of exceeding rate limit"
The profile's placeholder client code is replaced by `CLIENT_CODE`. The docs show one position row, a
cash one; the F&O and intraday rows are that same row shape with other values. Their symbols are the
ones in the FAQ's naming convention (https://smartapi.angelone.in/faq) and the expiry is written the
way the docs write `expirydate` (25JAN2024), but what SmartAPI really puts in `instrumenttype`,
`optiontype`, `strikeprice` and `expirydate` on a derivative row is NOT shown on any docs page, and
neither are the `ltp` / `pnl` fields the option row carries here.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from services.brokers import angelone, registry
from services.brokers.base import AccessToken, Funds, Holding, HubPosition, Position

# Stands in for the session JWT Angel One puts on the redirect. It must never be in an error message.
SECRET = "eyJhbGciOiJIUzUxMiJ9.angel-SECRET-7c1e.sig"
FEED = "feed-SECRET-22b0"
APP_KEY = "nivesh-app-key"
CLIENT_CODE = "S1234567"
CALLBACK = "https://nivesh.example/api/broker/native/callback?broker=angel"

PROFILE_PATH = "/rest/secure/angelbroking/user/v1/getProfile"
HOLDINGS_PATH = "/rest/secure/angelbroking/portfolio/v1/getAllHolding"
POSITIONS_PATH = "/rest/secure/angelbroking/order/v1/getPosition"
FUNDS_PATH = "/rest/secure/angelbroking/user/v1/getRMS"

PROFILE = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "clientcode": CLIENT_CODE,
        "name": "YOUR_NAME",
        "email": "",
        "mobileno": "",
        "exchanges": ["NSE", "BSE", "MCX", "CDS", "NCDEX", "NFO"],
        "products": ["DELIVERY", "INTRADAY", "MARGIN"],
        "lastlogintime": "",
        "brokerid": "B2C",
    },
}


def _holding(symbol: str, isin: str, quantity: int, averageprice: float, ltp: float, token: str,
             close: float, pnl: int, pct: float) -> dict:
    return {
        "tradingsymbol": symbol, "exchange": "NSE", "isin": isin, "t1quantity": 0,
        "realisedquantity": quantity, "quantity": quantity, "authorisedquantity": 0,
        "product": "DELIVERY", "collateralquantity": None, "collateraltype": None, "haircut": 0,
        "averageprice": averageprice, "ltp": ltp, "symboltoken": token, "close": close,
        "profitandloss": pnl, "pnlpercentage": pct,
    }


ALL_HOLDINGS = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "holdings": [
            _holding("TATASTEEL-EQ", "INE081A01020", 2, 111.87, 130.15, "3499", 129.6, 37, 16.34),
            _holding("PARAGMILK-EQ", "INE883N01014", 2, 154.03, 201, "17130", 192.1, 94, 30.49),
            _holding("SBIN-EQ", "INE062A01020", 8, 573.1, 579.05, "3045", 570.5, 48, 1.04),
        ],
        "totalholding": {
            "totalholdingvalue": 5294, "totalinvvalue": 5116,
            "totalprofitandloss": 178.14, "totalpnlpercentage": 3.48,
        },
    },
}

DOC_POSITION = {
    "exchange": "NSE", "symboltoken": "2885", "producttype": "DELIVERY",
    "tradingsymbol": "RELIANCE-EQ", "symbolname": "RELIANCE", "instrumenttype": "",
    "priceden": "1", "pricenum": "1", "genden": "1", "gennum": "1", "precision": "2",
    "multiplier": "-1", "boardlotsize": "1", "buyqty": "1", "sellqty": "0",
    "buyamount": "2235.80", "sellamount": "0", "symbolgroup": "EQ", "strikeprice": "-1",
    "optiontype": "", "expirydate": "", "lotsize": "1", "cfbuyqty": "0", "cfsellqty": "0",
    "cfbuyamount": "0", "cfsellamount": "0", "buyavgprice": "2235.80", "sellavgprice": "0",
    "avgnetprice": "2235.80", "netvalue": "- 2235.80", "netqty": "1",
    "totalbuyvalue": "2235.80", "totalsellvalue": "0", "cfbuyavgprice": "0",
    "cfsellavgprice": "0", "totalbuyavgprice": "2235.80", "totalsellavgprice": "0",
    "netprice": "2235.80",
}


def _row(**changes) -> dict:
    return {**DOC_POSITION, **changes}


OPTION = _row(
    exchange="NFO", tradingsymbol="BANKNIFTY25JAN2440000PE", symbolname="BANKNIFTY",
    instrumenttype="OPTIDX", producttype="CARRYFORWARD", symbolgroup="XX", strikeprice="40000",
    optiontype="PE", expirydate="25JAN2024", lotsize="15", buyqty="0", sellqty="30",
    netqty="-30", avgnetprice="212.50", netprice="212.50", ltp="198.40", pnl="423.00",
)
# No `optiontype` / `instrumenttype` value: the suffix of the symbol is what is left to read.
FUTURE = _row(
    exchange="NFO", tradingsymbol="BANKNIFTY28AUG24FUT", symbolname="BANKNIFTY",
    producttype="CARRYFORWARD", symbolgroup="XX", expirydate="28AUG2024", lotsize="15",
    buyqty="15", netqty="15", avgnetprice="51250.00", netprice="51250.00",
)
INTRADAY_CASH = _row(
    tradingsymbol="SBIN-EQ", symbolname="SBIN", symboltoken="3045", producttype="INTRADAY",
    buyqty="0", sellqty="10", netqty="-10", avgnetprice="579.05", netprice="579.05",
)

POSITIONS = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": [DOC_POSITION, OPTION, FUTURE, INTRADAY_CASH],
}

RMS = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "net": "9999999999999", "availablecash": "9999999999999", "availableintradaypayin": "0",
        "availablelimitmargin": "0", "collateral": "0", "m2munrealized": "0", "m2mrealized": "0",
        "utiliseddebits": "0", "utilisedspan": "0", "utilisedoptionpremium": "0",
        "utilisedholdingsales": "0", "utilisedexposure": "0", "utilisedturnover": "0",
        "utilisedpayout": "0",
    },
}

FAILED = {"status": False, "message": "Login Id or password is invalid", "errorcode": "AB1007", "data": None}


def _token_error(code: str, message: str) -> dict:
    return {"status": False, "message": message, "errorcode": code, "data": None}


# `_REQUIRED_AUTH_HEADER_KEYS` of `fenix.AngelOne` (fenix==2.0.2, fenix/angelone.py), copied.
FENIX_REQUIRED = (
    "Content-type", "X-ClientLocalIP", "X-ClientPublicIP", "X-MACAddress", "Accept",
    "X-PrivateKey", "X-UserType", "X-SourceID", "Authorization",
    "x-api-key", "x-client-code", "x-feed-token",
)


class FakeAngel:
    """Answers `apiconnect.angelone.in` by path and keeps the requests it was sent."""

    def __init__(self) -> None:
        self.replies: dict[str, tuple[int, object]] = {}
        self.requests: list[httpx.Request] = []

    def reply(self, path: str, body: object, status: int = 200) -> None:
        self.replies[path] = (status, body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.replies[request.url.path]
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(status, json=body, request=request)


@pytest.fixture
def api(monkeypatch) -> FakeAngel:
    fake = FakeAngel()
    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(angelone.httpx, "AsyncClient", client)
    return fake


@pytest.fixture(autouse=True)
def app_key(monkeypatch) -> None:
    monkeypatch.setenv("BROKER_ANGEL_API_KEY", APP_KEY)
    monkeypatch.delenv("BROKER_ANGEL_PUBLIC_IP", raising=False)


def _token(**extras) -> AccessToken:
    return AccessToken(token=SECRET, extras={"user_id": CLIENT_CODE, **extras})


def _sign_in(code: str = SECRET, **kwargs) -> AccessToken:
    # The three keywords are exactly what routes.broker_native passes today.
    return asyncio.run(angelone.exchange_code(code=code, state="st", redirect_uri=CALLBACK, **kwargs))


# ── Registration ─────────────────────────────────────────────────────────
def test_registered_as_a_redirect_sign_in_with_read_only_surface():
    adapter = registry.get("angel")

    assert (adapter.SLUG, adapter.DISPLAY, adapter.AUTH_STYLE) == ("angel", "Angel One", "oauth")
    assert adapter.CALLBACK_CODE_PARAMS == ("auth_token",)
    assert adapter.CALLBACK_EXTRA_PARAMS == ("feed_token",)
    for name in ("auth_url", "exchange_code", "fetch_holdings", "fetch_positions",
                 "fetch_hub_positions", "fetch_funds", "fenix_headers"):
        assert callable(getattr(adapter, name))
    # The Fenix reader is not switched on for Angel One until the callback passes `feed_token`.
    assert getattr(adapter, "FENIX_CLASS", None) is None
    # Nothing that could place, modify or cancel an order, and no SDK left behind.
    assert [n for n in dir(angelone) if "order" in n.lower()] == []
    assert not hasattr(angelone, "require_sdk")


# ── Sign-in: the redirect to Angel One's own page ────────────────────────
def test_auth_url_is_the_publisher_login_with_key_redirect_and_state():
    url = angelone.auth_url(state="st 1/+", redirect_uri=CALLBACK)

    assert url == (
        "https://smartapi.angelone.in/publisher-login"
        "?api_key=nivesh-app-key"
        "&redirect_url=https%3A%2F%2Fnivesh.example%2Fapi%2Fbroker%2Fnative%2Fcallback%3Fbroker%3Dangel"
        "&state=st%201%2F%2B"
    )
    assert parse_qs(urlsplit(url).query) == {
        "api_key": [APP_KEY], "redirect_url": [CALLBACK], "state": ["st 1/+"],
    }
    assert "/broker-credentials/" not in url          # the old Nivesh credentials form is gone


def test_missing_app_key_stops_sign_in_and_reads_before_any_request(api, monkeypatch):
    monkeypatch.delenv("BROKER_ANGEL_API_KEY")

    with pytest.raises(RuntimeError, match="BROKER_ANGEL_API_KEY is not configured"):
        angelone.auth_url(state="st", redirect_uri=CALLBACK)
    with pytest.raises(RuntimeError, match="BROKER_ANGEL_API_KEY is not configured"):
        _sign_in()
    with pytest.raises(RuntimeError, match="BROKER_ANGEL_API_KEY is not configured"):
        asyncio.run(angelone.fetch_holdings(_token()))
    with pytest.raises(RuntimeError, match="BROKER_ANGEL_API_KEY is not configured"):
        angelone.fenix_headers(_token(feed_token=FEED))
    assert api.requests == []


@pytest.mark.parametrize("code", [SECRET, f"  {SECRET}\n", f"Bearer {SECRET}"])
def test_sign_in_keeps_the_auth_token_after_one_profile_read(api, code):
    api.reply(PROFILE_PATH, PROFILE)

    got = _sign_in(code)

    assert got.token == SECRET
    assert got.extras["user_id"] == CLIENT_CODE
    assert set(got.extras) == {"user_id", "expires_at"}      # no name, e-mail, mobile or extra token
    assert len(api.requests) == 1
    sent = api.requests[0]
    assert sent.method == "GET"
    assert str(sent.url) == "https://apiconnect.angelone.in/rest/secure/angelbroking/user/v1/getProfile"
    assert sent.headers["Authorization"] == f"Bearer {SECRET}"
    assert sent.headers["X-PrivateKey"] == APP_KEY
    assert sent.headers["X-UserType"] == "USER"
    assert sent.headers["X-SourceID"] == "WEB"
    assert sent.headers["Accept"] == "application/json"
    assert sent.headers["Content-Type"] == "application/json"
    assert sent.headers["X-ClientLocalIP"] == "127.0.0.1"
    assert sent.headers["X-ClientPublicIP"] == "127.0.0.1"
    assert sent.headers["X-MACAddress"] == "00:00:00:00:00:00"


def test_sign_in_keeps_the_feed_token_when_the_callback_passes_it(api):
    api.reply(PROFILE_PATH, PROFILE)

    got = _sign_in(feed_token=f" {FEED} ")

    assert got.extras["feed_token"] == FEED
    assert set(got.extras) == {"user_id", "expires_at", "feed_token"}


def test_sign_in_expiry_is_the_next_midnight_ist_in_utc(api):
    api.reply(PROFILE_PATH, PROFILE)
    before = datetime.now(timezone.utc)

    expires = datetime.fromisoformat(_sign_in().extras["expires_at"])

    assert expires.utcoffset().total_seconds() == 0
    assert (expires.hour, expires.minute, expires.second) == (18, 30, 0)   # 00:00 IST
    assert 0 < (expires - before).total_seconds() <= 24 * 3600


@pytest.mark.parametrize("now, expected", [
    # 23:59:59 IST on the 13th -> the midnight one second later
    (datetime(2026, 10, 13, 18, 29, 59, tzinfo=timezone.utc), datetime(2026, 10, 13, 18, 30, tzinfo=timezone.utc)),
    # exactly 00:00 IST on the 14th -> that midnight has passed; the next one
    (datetime(2026, 10, 13, 18, 30, tzinfo=timezone.utc), datetime(2026, 10, 14, 18, 30, tzinfo=timezone.utc)),
    # mid-morning IST -> the coming midnight
    (datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc), datetime(2026, 10, 14, 18, 30, tzinfo=timezone.utc)),
])
def test_next_midnight_ist(now, expected):
    assert angelone._next_midnight_ist(now) == expected


def test_sign_in_without_an_auth_token_fails_before_any_request(api):
    with pytest.raises(RuntimeError, match="no auth_token"):
        _sign_in("   ")
    assert api.requests == []


def test_sign_in_fails_when_angel_refuses_the_token(api):
    api.reply(PROFILE_PATH, _token_error("AG8001", "Invalid Token"), status=403)

    with pytest.raises(angelone.AngelSessionExpired) as err:
        _sign_in()

    assert "AG8001" in str(err.value)
    assert SECRET not in str(err.value)


def test_sign_in_fails_on_the_documented_failed_envelope(api):
    api.reply(PROFILE_PATH, FAILED)

    with pytest.raises(angelone.AngelError) as err:
        _sign_in()

    assert "AB1007" in str(err.value)
    assert SECRET not in str(err.value) and FAILED["message"] not in str(err.value)


def test_sign_in_fails_when_the_profile_has_no_client_code(api):
    api.reply(PROFILE_PATH, {**PROFILE, "data": {**PROFILE["data"], "clientcode": ""}})

    with pytest.raises(RuntimeError, match="no client code"):
        _sign_in()


# ── Holdings ─────────────────────────────────────────────────────────────
def test_holdings_are_mapped_from_get_all_holding(api):
    api.reply(HOLDINGS_PATH, ALL_HOLDINGS)

    got = asyncio.run(angelone.fetch_holdings(_token()))

    assert got[0] == Holding(
        isin="INE081A01020", symbol="TATASTEEL-EQ", asset_type="equity", quantity=2.0,
        avg_price=111.87, current_price=130.15, name="TATASTEEL-EQ", exchange="NSE",
        source_id="NSE:TATASTEEL-EQ",
    )
    assert [(h.symbol, h.isin, h.quantity, h.avg_price, h.current_price) for h in got[1:]] == [
        ("PARAGMILK-EQ", "INE883N01014", 2.0, 154.03, 201.0),
        ("SBIN-EQ", "INE062A01020", 8.0, 573.1, 579.05),
    ]
    sent = api.requests[0]
    assert (sent.method, sent.url.path) == ("GET", HOLDINGS_PATH)
    assert sent.headers["Authorization"] == f"Bearer {SECRET}"
    assert sent.headers["X-PrivateKey"] == APP_KEY


def test_holdings_mark_an_etf_and_skip_a_row_without_a_symbol(api):
    etf = _holding("NIFTYBEES-EQ", "INF204KB14I2", 5, 250.0, 262.4, "10576", 261.0, 62, 4.96)
    blank = _holding("", "INE000000000", 1, 1.0, 1.0, "0", 1.0, 0, 0.0)
    api.reply(HOLDINGS_PATH, {**ALL_HOLDINGS, "data": {"holdings": [etf, blank]}})

    got = asyncio.run(angelone.fetch_holdings(_token()))

    assert [(h.symbol, h.asset_type) for h in got] == [("NIFTYBEES-EQ", "etf")]


def test_no_holdings_is_an_empty_list(api):
    api.reply(HOLDINGS_PATH, {**ALL_HOLDINGS, "data": None})

    assert asyncio.run(angelone.fetch_holdings(_token())) == []


def test_public_ip_header_comes_from_config_when_set(api, monkeypatch):
    monkeypatch.setenv("BROKER_ANGEL_PUBLIC_IP", "203.0.113.7")
    api.reply(HOLDINGS_PATH, ALL_HOLDINGS)

    asyncio.run(angelone.fetch_holdings(_token()))

    assert api.requests[0].headers["X-ClientPublicIP"] == "203.0.113.7"


# ── Positions ────────────────────────────────────────────────────────────
def test_net_positions_in_the_hub_shape(api):
    api.reply(POSITIONS_PATH, POSITIONS)

    cash, option, future, intraday = asyncio.run(angelone.fetch_hub_positions(_token(), "net"))

    # The row as the docs publish it: no last price, no P&L, no contract details.
    assert cash == HubPosition(
        symbol="RELIANCE-EQ", exchange="NSE", quantity=1.0, avg_price=2235.80, last_price=None,
        pnl=0.0, product="delivery", product_raw="DELIVERY", segment="equity", is_intraday=False,
        instrument_type=None, expiry=None, strike=None, kind="net", name="RELIANCE",
    )
    assert option == HubPosition(
        symbol="BANKNIFTY25JAN2440000PE", exchange="NFO", quantity=-30.0, avg_price=212.5,
        last_price=198.4, pnl=423.0, product="carryforward", product_raw="CARRYFORWARD",
        segment="fno", is_intraday=False, instrument_type="PE", expiry="2024-01-25",
        strike=40000.0, kind="net", name="BANKNIFTY",
    )
    assert future == HubPosition(
        symbol="BANKNIFTY28AUG24FUT", exchange="NFO", quantity=15.0, avg_price=51250.0,
        last_price=None, pnl=0.0, product="carryforward", product_raw="CARRYFORWARD",
        segment="fno", is_intraday=False, instrument_type="FUT", expiry="2024-08-28",
        strike=None, kind="net", name="BANKNIFTY",
    )
    assert intraday == HubPosition(
        symbol="SBIN-EQ", exchange="NSE", quantity=-10.0, avg_price=579.05, last_price=None,
        pnl=0.0, product="intraday", product_raw="INTRADAY", segment="equity", is_intraday=True,
        instrument_type=None, expiry=None, strike=None, kind="net", name="SBIN",
    )
    assert [(r.method, r.url.path) for r in api.requests] == [("GET", POSITIONS_PATH)]


@pytest.mark.parametrize("row, expected", [
    ({"optiontype": "CE", "instrumenttype": "OPTSTK"}, "CE"),       # the row's own option type first
    ({"optiontype": "XX", "instrumenttype": "FUTSTK"}, "FUT"),      # then its instrument type
    ({"optiontype": "", "instrumenttype": ""}, "PE"),               # then the symbol's suffix
])
def test_instrument_type_sources(row, expected):
    assert angelone._instrument_type(row, "BAJFINANCE28DEC237650PE") == expected


@pytest.mark.parametrize("raw, expected", [
    ("25JAN2024", "2024-01-25"), ("28AUG24", "2024-08-28"), ("2024-08-28", "2024-08-28"),
    ("", None), (None, None), ("next thursday", None),
])
def test_expiry_is_iso_or_none(raw, expected):
    assert angelone._iso_date(raw) == expected


def test_unlisted_product_and_other_segments_are_not_guessed(api):
    api.reply(POSITIONS_PATH, {**POSITIONS, "data": [
        _row(exchange="MCX", tradingsymbol="CRUDEOIL23DEC6450CE", producttype="SOMETHINGNEW"),
        _row(exchange="CDS", tradingsymbol="USDINR24AUGFUT", producttype=""),
    ]})

    commodity, currency = asyncio.run(angelone.fetch_hub_positions(_token(), "net"))

    assert (commodity.segment, commodity.product, commodity.product_raw) == ("commodity", None, "SOMETHINGNEW")
    assert (commodity.instrument_type, commodity.is_intraday) == ("CE", False)
    assert (currency.segment, currency.product, currency.product_raw) == ("currency", None, None)
    assert currency.instrument_type == "FUT"


def test_day_positions_are_refused_without_a_request(api):
    from services.brokers import hub_reads

    with pytest.raises(angelone.AngelDayPositionsNotSupported) as err:
        asyncio.run(angelone.fetch_hub_positions(_token(), "day"))

    assert api.requests == []
    # The hub reports this as "not supported", not as a failed read or an ended session.
    assert hub_reads._is_not_supported(err.value)
    assert not hub_reads._is_token_rejection(err.value)


def test_unknown_position_kind_is_rejected(api):
    with pytest.raises(ValueError, match="kind must be"):
        asyncio.run(angelone.fetch_hub_positions(_token(), "weekly"))
    assert api.requests == []


def test_no_positions_is_an_empty_list(api):
    api.reply(POSITIONS_PATH, {**POSITIONS, "data": None})

    assert asyncio.run(angelone.fetch_hub_positions(_token(), "net")) == []
    assert asyncio.run(angelone.fetch_positions(_token())) == []


def test_legacy_positions_are_the_net_book(api):
    api.reply(POSITIONS_PATH, POSITIONS)

    got = asyncio.run(angelone.fetch_positions(_token()))

    assert got[0] == Position(
        symbol="RELIANCE-EQ", exchange="NSE", quantity=1.0, avg_price=2235.80, pnl=0.0, product="DELIVERY",
    )
    assert [(p.symbol, p.exchange, p.quantity, p.pnl, p.product) for p in got[1:]] == [
        ("BANKNIFTY25JAN2440000PE", "NFO", -30.0, 423.0, "CARRYFORWARD"),
        ("BANKNIFTY28AUG24FUT", "NFO", 15.0, 0.0, "CARRYFORWARD"),
        ("SBIN-EQ", "NSE", -10.0, 0.0, "INTRADAY"),
    ]


# ── A token Angel One refuses, and what is not one ───────────────────────
@pytest.mark.parametrize("status, body", [
    (403, _token_error("AG8001", "Invalid Token")),      # "Preceded by a 403 header" (docs/Exceptions)
    (200, _token_error("AG8002", "Token Expired")),
    (401, {"success": False, "message": "Invalid Token", "errorCode": "AG8001", "data": ""}),
])
def test_a_rejected_token_with_an_error_code_is_session_expired(api, status, body):
    from services.brokers import hub_reads
    api.reply(HOLDINGS_PATH, body, status=status)

    with pytest.raises(angelone.AngelSessionExpired) as err:
        asyncio.run(angelone.fetch_holdings(_token()))

    assert hub_reads._is_token_rejection(err.value)
    assert SECRET not in str(err.value) and APP_KEY not in str(err.value)


@pytest.mark.parametrize("status", [401, 403])
def test_a_bare_401_or_403_is_an_http_status_error(api, status):
    from services.brokers import hub_reads
    api.reply(POSITIONS_PATH, "Unauthorized", status=status)

    with pytest.raises(httpx.HTTPStatusError) as err:
        asyncio.run(angelone.fetch_hub_positions(_token(), "net"))

    assert err.value.response.status_code == status
    assert hub_reads._is_token_rejection(err.value)


@pytest.mark.parametrize("text", [
    "Access denied because of exceeding access rate",
    "Access denied because of exceeding rate limit",
])
def test_a_rate_limit_403_does_not_look_like_a_rejected_token(api, text):
    from services.brokers import hub_reads
    api.reply(HOLDINGS_PATH, text, status=403)

    with pytest.raises(angelone.AngelRateLimited) as err:
        asyncio.run(angelone.fetch_holdings(_token()))

    assert not hub_reads._is_token_rejection(err.value)
    assert not hub_reads._is_not_supported(err.value)


@pytest.mark.parametrize("status, body", [
    (200, FAILED),
    # An app-key problem is Nivesh's, not the user's session — even on a 403.
    (403, {"success": False, "message": "Invalid API Key", "errorCode": "AG8004", "data": ""}),
])
def test_other_broker_errors_carry_the_code_and_end_no_session(api, status, body):
    from services.brokers import hub_reads
    api.reply(FUNDS_PATH, body, status=status)

    with pytest.raises(angelone.AngelError) as err:
        asyncio.run(angelone.fetch_funds(_token()))

    assert (body.get("errorcode") or body.get("errorCode")) in str(err.value)
    assert body["message"] not in str(err.value) and SECRET not in str(err.value)
    assert not hub_reads._is_token_rejection(err.value)


def test_a_server_error_is_an_http_status_error_that_ends_no_session(api):
    from services.brokers import hub_reads
    api.reply(HOLDINGS_PATH, "Bad Gateway", status=502)

    with pytest.raises(httpx.HTTPStatusError) as err:
        asyncio.run(angelone.fetch_holdings(_token()))

    assert not hub_reads._is_token_rejection(err.value)


def test_a_reply_without_a_success_status_never_reads_as_empty(api):
    api.reply(HOLDINGS_PATH, {"data": {"holdings": []}})

    with pytest.raises(angelone.AngelError, match="no success status"):
        asyncio.run(angelone.fetch_holdings(_token()))


# ── Funds ────────────────────────────────────────────────────────────────
def test_funds_are_mapped_from_get_rms(api):
    api.reply(FUNDS_PATH, RMS)

    got = asyncio.run(angelone.fetch_funds(_token()))

    assert got == Funds(available_cash=9999999999999.0, collateral=0.0, used_margin=0.0)
    assert (api.requests[0].method, api.requests[0].url.path) == ("GET", FUNDS_PATH)


def test_every_read_is_a_get(api):
    for path, body in ((PROFILE_PATH, PROFILE), (HOLDINGS_PATH, ALL_HOLDINGS),
                       (POSITIONS_PATH, POSITIONS), (FUNDS_PATH, RMS)):
        api.reply(path, body)

    token = _sign_in()
    asyncio.run(angelone.fetch_holdings(token))
    asyncio.run(angelone.fetch_positions(token))
    asyncio.run(angelone.fetch_hub_positions(token, "net"))
    asyncio.run(angelone.fetch_funds(token))

    assert {r.method for r in api.requests} == {"GET"}
    assert {r.url.host for r in api.requests} == {"apiconnect.angelone.in"}
    assert all(r.content == b"" for r in api.requests)


# ── Fenix headers ────────────────────────────────────────────────────────
def test_fenix_headers_are_what_fenix_requires_when_the_session_has_a_feed_token():
    headers = angelone.fenix_headers(_token(feed_token=FEED))

    assert set(headers) == set(FENIX_REQUIRED)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items())
    assert headers == {
        "Content-type": "application/json",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "Accept": "application/json",
        "X-PrivateKey": APP_KEY,
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "Authorization": f"Bearer {SECRET}",
        "x-api-key": APP_KEY,                # Nivesh's own key, not the literal in Fenix's source
        "x-client-code": CLIENT_CODE,
        "x-feed-token": FEED,
    }


def test_fenix_headers_leave_out_what_the_session_does_not_hold():
    headers = angelone.fenix_headers(AccessToken(token=SECRET, extras={}))

    # Not faked: the Fenix reader reports these two by name as missing.
    assert set(FENIX_REQUIRED) - set(headers) == {"x-client-code", "x-feed-token"}
