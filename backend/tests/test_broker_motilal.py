"""services/brokers/motilal.py — portal sign-in, DP holdings, positions, margin summary.

No network and no Motilal Oswal account: every call is answered by an `httpx.MockTransport`, so nothing
in this file proves behaviour against the live MOFSL OpenAPI.

Payloads are the samples on MOFSL's official API documentation page, copied as published:
    https://invest.motilaloswal.com/moapi/APIDocumentation/Introduction
        "Generate Access Token", "Get Profile", "Holding", "Position", "Margin Summary",
        "Responses Format" (the failed envelope), "Error Codes And Description" (MO8001 Invalid Token, ...)
The session tokens in the samples are replaced by `AUTH_TOKEN` / `ACCESS_TOKEN`. The docs show ONE
position row, a cash one with every amount at 0; the option, future, intraday and carried rows below
are that same row shape with other values. What MOFSL really puts in `symbol`, `expirydate` and
`optiontype` on a derivative row is NOT shown for the Position call: the option's symbol and expiry
are written the way the docs' scrip master and "Position Detail" samples write them
("NIFTY 13-Oct-2022 PE 16500", "29-Aug-2023"), and the future's "XX" option type is the value on the
documented cash row.
"""
from __future__ import annotations

import asyncio
import json
import platform
from datetime import datetime, timezone

import httpx
import pytest

from services.brokers import hub_reads, motilal, registry
from services.brokers.base import AccessToken, Funds, Holding, HubPosition, Position

# Stand in for what MOFSL hands back and for Nivesh's own keys. None may appear in an error message.
AUTH_TOKEN = "authSECRET5c1e9bb0a_M"
ACCESS_TOKEN = "accessSECRET77d02f4c_M"
APP_KEY = "nivesh-app-key"
APP_SECRET = "nivesh-app-SECRET"
VENDOR = "NIVESH"
CLIENT_CODE = "AA017"
CALLBACK = "https://nivesh.example/api/broker/native/callback/motilal"

ACCESS_PATH = "/rest/login/v1/getaccesstoken"
PROFILE_PATH = "/rest/login/v5/getprofile"
HOLDINGS_PATH = "/rest/report/v3/getdpholding"
POSITIONS_PATH = "/rest/book/v4/getposition"
MARGIN_PATH = "/rest/report/v3/getreportmarginsummary"

ACCESS = {"status": "SUCCESS", "message": "", "errorcode": "", "accesstoken": ACCESS_TOKEN}

PROFILE = {
    "status": "SUCCESS",
    "message": "Profile Data",
    "errorcode": "",
    "data": {
        "clientcode": CLIENT_CODE,
        "name": "Amit Kumar",
        "exchanges": ["NSE", "BSE", "NSEFO", "NSECD", "NSEEX", "MCX", "BSECD"],
        "products": ["Normal", "Delivery"],
        "usertype": "Investorclient",
    },
}

DOC_HOLDING = {
    "clientcode": "AA020", "scripisinno": "INE131B01039", "dpquantity": 1119, "blockedquantity": 0,
    "scripname": "RELAXO EQ", "buyavgprice": 813.66, "poaquantity": 41, "collateralquantity": 1078,
    "outstandingquantity": 0, "debitstockquantity": 0, "nonpoaquantity": 0, "rmssellingquantity": 0,
    "btstquantity": 0, "buybackquantity": 0, "tpinquantity": 0, "slbmquantity": 0, "nbfcquantity": 0,
    "bsescripcode": 50001, "nsesymboltoken": 123,
}
HOLDINGS = {"status": "SUCCESS", "message": "DP Holding Data", "errorcode": "", "data": [DOC_HOLDING]}

DOC_POSITION = {
    "exchange": "NSE", "clientcode": "AA020", "productname": "NORMAL", "symboltoken": 1660,
    "symbol": "INFY", "buyquantity": 0, "buyamount": 0, "sellquantity": 0, "sellamount": 0,
    "daybuyquantity": 0, "daybuyamount": 0, "daysellquantity": 0, "daysellamount": 0, "LTP": 0,
    "marktomarket": 0, "bookedprofitloss": 0, "cfbuyquantity": 0, "cfbuyamount": 0,
    "cfsellquantity": 0, "cfsellamount": 0, "actualbookedprofitloss": 0, "actualmarktomarket": 0,
    "series": "EQ", "expirydate": "0", "strikeprice": 0, "optiontype": "XX",
}


def _row(**changes) -> dict:
    return {**DOC_POSITION, **changes}


# A short put carried from an earlier day: sold 50 at 100 (actual), valued at yesterday's close of 90
# in the totals' amount, last price 80.
OPTION = _row(
    exchange="NSEFO", symbol="NIFTY 13-Oct-2022 PE 16500", symboltoken=52826, series="XX",
    expirydate="13-Oct-2022", strikeprice=16500, optiontype="PE",
    sellquantity=50, sellamount=4500, cfsellquantity=50, cfsellamount=5000,
    LTP=80, marktomarket=500, actualmarktomarket=1000,
)
# Bought today: 25 at 40000.
FUTURE = _row(
    exchange="NSEFO", symbol="BANKNIFTY 27-Oct-2022", symboltoken=35020, series="XX",
    expirydate="27-Oct-2022",
    buyquantity=25, buyamount=1000000, daybuyquantity=25, daybuyamount=1000000,
    LTP=40100, marktomarket=2500, actualmarktomarket=2500,
)
# Sold short today in the intraday product: 10 at 579.05.
INTRADAY_CASH = _row(
    symbol="SBIN", symboltoken=3045, productname="VALUEPLUS",
    sellquantity=10, sellamount=5790.5, daysellquantity=10, daysellamount=5790.5,
    LTP=575, marktomarket=40.5, actualmarktomarket=40.5,
)
# 10 carried at an actual 2400 (valued at a close of 2500 in the totals), 5 more bought today at 2520.
CARRIED_AND_TRADED = _row(
    symbol="RELIANCE", symboltoken=2885, productname="DELIVERY",
    buyquantity=15, buyamount=37600, daybuyquantity=5, daybuyamount=12600,
    cfbuyquantity=10, cfbuyamount=24000, LTP=2530, marktomarket=350, actualmarktomarket=1350,
)

POSITIONS = {
    "status": "SUCCESS", "message": "Position Data", "errorcode": "",
    "data": [DOC_POSITION, OPTION, FUTURE, INTRADAY_CASH, CARRIED_AND_TRADED],
}

MARGIN_SUMMARY = {
    "status": "SUCCESS",
    "message": "REPORT MARGIN SUMMARY",
    "errorcode": "",
    "data": [
        {"srno": 102, "particulars": "Total Available Margin for Cash", "amount": 999998900000},
        {"srno": 103, "particulars": "Total Available Margin for FNO", "amount": 999998900000},
        {"srno": 104, "particulars": "Total Available Margin for Curr", "amount": 999998900000},
        {"srno": 105, "particulars": "Total Available Margin for Comm", "amount": 999998900000},
        {"srno": 106, "particulars": "Total Available Margin for Other", "amount": 0},
        {"srno": 201, "particulars": "Cash deposit", "amount": 1000000000000},
        {"srno": 220, "particulars": "Non cash deposit", "amount": 0},
        {"srno": 301, "particulars": "Margin Usage(B) Cash", "amount": 0},
        {"srno": 321, "particulars": "Margin Usage(B) FO", "amount": 560127.5},
        {"srno": 340, "particulars": "Margin Usage(B) Currency", "amount": 0},
        {"srno": 360, "particulars": "Margin Usage(B) Commodity", "amount": 547544},
        {"srno": 381, "particulars": "Margin Usage(B) Brokerage", "amount": 0},
        {"srno": 600, "particulars": "Total Profit and Loss(MTM)", "amount": 16050.07},
        {"srno": 700, "particulars": "Total Profit and Loss(BPL)", "amount": 0},
    ],
}

# "Responses Format" → Failed Response, as published.
FAILED = {"status": "FAILURE", "message": "Login Id/Password Is Invalid", "errorcode": "MOSL100", "data": "null"}


def _error(code: str, message: str) -> dict:
    # The shape of the docs' failure samples ("status": "ERROR", message, errorcode).
    return {"status": "ERROR", "message": message, "errorcode": code}


# The docs' "Header Parameters" for a WEB source: every one of them, on every call.
DOC_HEADERS = (
    "Accept", "User-Agent", "Authorization", "ApiKey", "ClientLocalIp", "ClientPublicIp", "MacAddress",
    "SourceId", "vendorinfo", "osname", "osversion", "devicemodel", "manufacturer", "productname",
    "productversion", "browsername", "browserversion", "apisecretkey", "accesstoken",
)


class FakeMofsl:
    """Answers `openapi.motilaloswal.com` by path and keeps the requests it was sent."""

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
def api(monkeypatch) -> FakeMofsl:
    fake = FakeMofsl()
    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(motilal.httpx, "AsyncClient", client)
    return fake


@pytest.fixture(autouse=True)
def app_config(monkeypatch) -> None:
    monkeypatch.setenv("BROKER_MOTILAL_API_KEY", APP_KEY)
    monkeypatch.setenv("BROKER_MOTILAL_API_SECRET", APP_SECRET)
    monkeypatch.setenv("BROKER_MOTILAL_VENDOR_INFO", VENDOR)
    monkeypatch.delenv("BROKER_MOTILAL_PUBLIC_IP", raising=False)


def _token() -> AccessToken:
    return AccessToken(token=AUTH_TOKEN, extras={"user_id": CLIENT_CODE, "access_token": ACCESS_TOKEN})


def _sign_in(code: str = AUTH_TOKEN) -> AccessToken:
    # The three keywords are exactly what routes.broker_native passes.
    return asyncio.run(motilal.exchange_code(code=code, state="st", redirect_uri=CALLBACK))


def _leaks(text: str) -> list[str]:
    return [s for s in (AUTH_TOKEN, ACCESS_TOKEN, APP_KEY, APP_SECRET) if s in text]


# ── Registration ─────────────────────────────────────────────────────────
def test_registered_as_a_redirect_sign_in_with_a_read_only_surface():
    adapter = registry.get("motilal")

    # The real adapter, not the `_stub` placeholder of the same slug.
    assert type(adapter).__module__ == "services.brokers.motilal"
    assert (adapter.SLUG, adapter.DISPLAY, adapter.AUTH_STYLE) == ("motilal", "Motilal Oswal", "oauth")
    assert getattr(adapter, "IMPLEMENTED", True) is True
    # MOFSL appends `?authtoken=` to the registered URL: path-style callback, value read as the code.
    assert adapter.CALLBACK_CODE_PARAMS == ("authtoken",)
    assert adapter.CALLBACK_PATH_STYLE is True
    for name in ("auth_url", "exchange_code", "fetch_holdings", "fetch_positions",
                 "fetch_hub_positions", "fetch_funds"):
        assert callable(getattr(adapter, name))
    # Reads stay on this adapter: no Fenix hook (Fenix's MotilalOswal is the per-client XTS API).
    assert getattr(adapter, "FENIX_CLASS", None) is None and not hasattr(adapter, "fenix_headers")


def test_nothing_order_related_is_exposed():
    names = dir(motilal) + dir(registry.get("motilal"))

    assert [n for n in names if any(w in n.lower() for w in ("order", "place", "modify", "cancel", "convert"))] == []
    assert not hasattr(motilal, "require_sdk")
    # The only MOFSL paths in the module are the five read / session calls.
    source = open(motilal.__file__, encoding="utf-8").read()
    assert "/rest/trans/" not in source
    assert sorted(set(part.split('"')[0] for part in source.split('"/rest/')[1:])) == sorted(
        p.removeprefix("/rest/") for p in (ACCESS_PATH, PROFILE_PATH, HOLDINGS_PATH, POSITIONS_PATH, MARGIN_PATH))


# ── Sign-in: the redirect to MOFSL's own page ────────────────────────────
def test_auth_url_is_the_portal_login_with_only_the_app_key(monkeypatch):
    monkeypatch.setenv("BROKER_MOTILAL_API_KEY", "key with/+&")

    url = motilal.auth_url(state="st-1", redirect_uri=CALLBACK)

    assert url == "https://invest.motilaloswal.com/OpenAPI/Login.aspx?apikey=key%20with%2F%2B%26"
    # Neither is a documented parameter: the redirect URL is the one registered with the key.
    assert "st-1" not in url and "nivesh.example" not in url
    assert APP_SECRET not in url and VENDOR not in url


@pytest.mark.parametrize("missing", [
    "BROKER_MOTILAL_API_KEY", "BROKER_MOTILAL_API_SECRET", "BROKER_MOTILAL_VENDOR_INFO",
])
def test_missing_config_stops_sign_in_and_reads_before_any_request(api, monkeypatch, missing):
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match=f"{missing} is not configured"):
        motilal.auth_url(state="st", redirect_uri=CALLBACK)
    with pytest.raises(RuntimeError, match=f"{missing} is not configured"):
        _sign_in()
    for read in (motilal.fetch_holdings(_token()), motilal.fetch_positions(_token()),
                 motilal.fetch_hub_positions(_token(), "net"), motilal.fetch_funds(_token())):
        with pytest.raises(RuntimeError, match=f"{missing} is not configured"):
            asyncio.run(read)
    assert api.requests == []


@pytest.mark.parametrize("code", [AUTH_TOKEN, f"  {AUTH_TOKEN}\n"])
def test_sign_in_fetches_the_access_token_then_the_client_code(api, code):
    api.reply(ACCESS_PATH, ACCESS)
    api.reply(PROFILE_PATH, PROFILE)

    got = _sign_in(code)

    assert got.token == AUTH_TOKEN
    assert got.extras["user_id"] == CLIENT_CODE
    assert got.extras["access_token"] == ACCESS_TOKEN
    assert set(got.extras) == {"user_id", "access_token", "expires_at"}   # no name, no app key or secret
    first, second = api.requests
    assert (first.method, str(first.url)) == (
        "POST", "https://openapi.motilaloswal.com/rest/login/v1/getaccesstoken")
    assert first.headers["Authorization"] == AUTH_TOKEN
    assert first.headers["ApiKey"] == APP_KEY
    assert first.headers["apisecretkey"] == APP_SECRET
    assert first.headers["accesstoken"] == ""           # not issued yet — sent empty, as MOFSL's SDK does
    assert (second.method, str(second.url)) == (
        "POST", "https://openapi.motilaloswal.com/rest/login/v5/getprofile")
    assert second.headers["Authorization"] == AUTH_TOKEN
    assert second.headers["accesstoken"] == ACCESS_TOKEN


def test_sign_in_expiry_is_the_next_6am_ist_in_utc(api):
    api.reply(ACCESS_PATH, ACCESS)
    api.reply(PROFILE_PATH, PROFILE)
    before = datetime.now(timezone.utc)

    expires = datetime.fromisoformat(_sign_in().extras["expires_at"])

    assert expires.utcoffset().total_seconds() == 0
    assert (expires.hour, expires.minute, expires.second) == (0, 30, 0)   # 06:00 IST
    assert 0 < (expires - before).total_seconds() <= 24 * 3600


@pytest.mark.parametrize("now, expected", [
    # 05:59:59 IST on the 14th -> one second later
    (datetime(2026, 10, 14, 0, 29, 59, tzinfo=timezone.utc), datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc)),
    # exactly 06:00 IST on the 14th -> that reset has passed; the next one
    (datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc), datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)),
    # an evening sign-in IST -> the coming morning
    (datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc), datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)),
])
def test_session_end(now, expected):
    assert motilal._session_end(now) == expected


def test_sign_in_without_an_authtoken_fails_before_any_request(api):
    with pytest.raises(motilal.MotilalError, match="no authtoken"):
        _sign_in("   ")
    assert api.requests == []


def test_sign_in_fails_when_mofsl_refuses_the_authtoken(api):
    api.reply(ACCESS_PATH, _error("MO8001", "Invalid Token"))

    with pytest.raises(motilal.MotilalSessionExpired) as err:
        _sign_in()

    assert "MO8001" in str(err.value)
    assert _leaks(str(err.value)) == [] and "Invalid Token" not in str(err.value)
    assert [r.url.path for r in api.requests] == [ACCESS_PATH]      # the profile is never asked for


@pytest.mark.parametrize("body", [
    _error("MO2006", "ApiSecretKey is InVaild In Header Parameter"),
    FAILED,
    {**ACCESS, "accesstoken": ""},
])
def test_sign_in_fails_when_no_access_token_is_issued(api, body):
    api.reply(ACCESS_PATH, body)

    with pytest.raises(motilal.MotilalError) as err:
        _sign_in()

    assert not isinstance(err.value, motilal.MotilalSessionExpired)
    assert _leaks(str(err.value)) == [] and str(body.get("message") or "no-message") not in str(err.value)
    assert [r.url.path for r in api.requests] == [ACCESS_PATH]


def test_sign_in_fails_when_the_profile_has_no_client_code(api):
    api.reply(ACCESS_PATH, ACCESS)
    api.reply(PROFILE_PATH, {**PROFILE, "data": {**PROFILE["data"], "clientcode": ""}})

    with pytest.raises(motilal.MotilalError, match="no client code"):
        _sign_in()


# ── Headers ──────────────────────────────────────────────────────────────
def test_a_read_carries_every_documented_header(api):
    api.reply(HOLDINGS_PATH, HOLDINGS)

    asyncio.run(motilal.fetch_holdings(_token()))

    sent = api.requests[0]
    assert [name for name in DOC_HEADERS if name not in sent.headers] == []
    assert all(sent.headers[name] != "" for name in DOC_HEADERS)
    assert sent.headers["Accept"] == "application/json"
    assert sent.headers["Content-Type"] == "application/json"
    assert sent.headers["User-Agent"] == "MOSL/V.1.1.0"
    assert sent.headers["Authorization"] == AUTH_TOKEN          # the authtoken as given, no "Bearer"
    assert sent.headers["accesstoken"] == ACCESS_TOKEN
    assert sent.headers["ApiKey"] == APP_KEY
    assert sent.headers["apisecretkey"] == APP_SECRET
    assert sent.headers["vendorinfo"] == VENDOR
    assert sent.headers["SourceId"] == "WEB"
    assert sent.headers["ClientLocalIp"] == "127.0.0.1"
    assert sent.headers["ClientPublicIp"] == "127.0.0.1"
    assert sent.headers["MacAddress"] == "00:00:00:00:00:00"
    # What makes the call is the Nivesh backend; nothing is claimed about the customer's device.
    assert sent.headers["osname"] == platform.system()
    assert sent.headers["osversion"] == platform.release()
    assert (sent.headers["devicemodel"], sent.headers["manufacturer"]) == ("server", "unknown")
    assert (sent.headers["productname"], sent.headers["productversion"]) == ("Nivesh", "1")
    assert (sent.headers["browsername"], sent.headers["browserversion"]) == ("httpx", httpx.__version__)
    # DESKTOP / MOBILE only.
    assert "installedappid" not in sent.headers and "imeino" not in sent.headers


def test_public_ip_header_comes_from_config_when_set(api, monkeypatch):
    monkeypatch.setenv("BROKER_MOTILAL_PUBLIC_IP", "203.0.113.7")
    api.reply(HOLDINGS_PATH, HOLDINGS)

    asyncio.run(motilal.fetch_holdings(_token()))

    assert api.requests[0].headers["ClientPublicIp"] == "203.0.113.7"


def test_every_call_is_a_post_with_no_request_fields(api):
    for path, body in ((ACCESS_PATH, ACCESS), (PROFILE_PATH, PROFILE), (HOLDINGS_PATH, HOLDINGS),
                       (POSITIONS_PATH, POSITIONS), (MARGIN_PATH, MARGIN_SUMMARY)):
        api.reply(path, body)

    token = _sign_in()
    asyncio.run(motilal.fetch_holdings(token))
    asyncio.run(motilal.fetch_positions(token))
    asyncio.run(motilal.fetch_hub_positions(token, "day"))
    asyncio.run(motilal.fetch_funds(token))

    assert {r.method for r in api.requests} == {"POST"}
    assert {r.url.host for r in api.requests} == {"openapi.motilaloswal.com"}
    assert [r.url.path for r in api.requests] == [
        ACCESS_PATH, PROFILE_PATH, HOLDINGS_PATH, POSITIONS_PATH, POSITIONS_PATH, MARGIN_PATH]
    # No client code, and nothing a customer typed, is ever in a request body.
    assert all(json.loads(r.content) == {} for r in api.requests)


# ── Holdings ─────────────────────────────────────────────────────────────
def test_holdings_are_mapped_from_get_dp_holding(api):
    api.reply(HOLDINGS_PATH, HOLDINGS)

    got = asyncio.run(motilal.fetch_holdings(_token()))

    # No last price, exchange or trading symbol in the payload: the scrip name stands as the symbol.
    assert got == [Holding(
        isin="INE131B01039", symbol="RELAXO EQ", asset_type="equity", quantity=1119.0,
        avg_price=813.66, current_price=0.0, name="RELAXO EQ", sector=None, exchange=None,
        source_id="motilal:INE131B01039",
    )]
    assert (api.requests[0].method, api.requests[0].url.path) == ("POST", HOLDINGS_PATH)


def test_holdings_mark_an_etf_and_skip_a_row_with_neither_name_nor_isin(api):
    etf = {**DOC_HOLDING, "scripisinno": "inf204kb14i2", "scripname": "NIFTYBEES EQ", "dpquantity": 5}
    isin_only = {**DOC_HOLDING, "scripisinno": "INE062A01020", "scripname": "", "dpquantity": 8}
    blank = {**DOC_HOLDING, "scripisinno": "", "scripname": " "}
    api.reply(HOLDINGS_PATH, {**HOLDINGS, "data": [etf, isin_only, blank]})

    got = asyncio.run(motilal.fetch_holdings(_token()))

    assert [(h.symbol, h.isin, h.asset_type, h.name, h.source_id) for h in got] == [
        ("NIFTYBEES EQ", "INF204KB14I2", "etf", "NIFTYBEES EQ", "motilal:INF204KB14I2"),
        ("INE062A01020", "INE062A01020", "equity", None, "motilal:INE062A01020"),
    ]


@pytest.mark.parametrize("body", [
    {**HOLDINGS, "data": []},
    {**HOLDINGS, "data": None},
    _error("MO1015", "Holding Not Found"),
])
def test_no_holdings_is_an_empty_list(api, body):
    api.reply(HOLDINGS_PATH, body)

    assert asyncio.run(motilal.fetch_holdings(_token())) == []


def test_an_empty_code_of_another_read_is_still_an_error(api):
    # "Position Not Found" answering the HOLDINGS call is not "no holdings".
    api.reply(HOLDINGS_PATH, _error("MO1016", "Position Not Found"))

    with pytest.raises(motilal.MotilalError, match="MO1016"):
        asyncio.run(motilal.fetch_holdings(_token()))


# ── Positions ────────────────────────────────────────────────────────────
def test_net_positions_in_the_hub_shape(api):
    api.reply(POSITIONS_PATH, POSITIONS)

    cash, option, future, intraday, carried = asyncio.run(motilal.fetch_hub_positions(_token(), "net"))

    # The row exactly as the docs publish it: nothing held, every amount 0.
    assert cash == HubPosition(
        symbol="INFY", exchange="NSE", quantity=0.0, avg_price=0.0, last_price=0.0, pnl=0.0,
        product="carryforward", product_raw="NORMAL", segment="equity", is_intraday=False,
        instrument_type=None, expiry=None, strike=None, kind="net", name=None,
    )
    # Short 50 carried: the average is the actual 100, not the 90 close in `sellamount`.
    assert option == HubPosition(
        symbol="NIFTY 13-OCT-2022 PE 16500", exchange="NFO", quantity=-50.0, avg_price=100.0,
        last_price=80.0, pnl=1000.0, product="carryforward", product_raw="NORMAL", segment="fno",
        is_intraday=False, instrument_type="PE", expiry="2022-10-13", strike=16500.0, kind="net",
        name=None,
    )
    assert future == HubPosition(
        symbol="BANKNIFTY 27-OCT-2022", exchange="NFO", quantity=25.0, avg_price=40000.0,
        last_price=40100.0, pnl=2500.0, product="carryforward", product_raw="NORMAL", segment="fno",
        is_intraday=False, instrument_type="FUT", expiry="2022-10-27", strike=None, kind="net",
        name=None,
    )
    assert intraday == HubPosition(
        symbol="SBIN", exchange="NSE", quantity=-10.0, avg_price=579.05, last_price=575.0, pnl=40.5,
        product="intraday", product_raw="VALUEPLUS", segment="equity", is_intraday=True,
        instrument_type=None, expiry=None, strike=None, kind="net", name=None,
    )
    # 10 carried at 2400 + 5 today at 2520 = 36600 / 15.
    assert carried == HubPosition(
        symbol="RELIANCE", exchange="NSE", quantity=15.0, avg_price=2440.0, last_price=2530.0,
        pnl=1350.0, product="delivery", product_raw="DELIVERY", segment="equity", is_intraday=False,
        instrument_type=None, expiry=None, strike=None, kind="net", name=None,
    )
    assert [(r.method, r.url.path) for r in api.requests] == [("POST", POSITIONS_PATH)]


def test_day_positions_are_todays_trades_only(api):
    api.reply(POSITIONS_PATH, POSITIONS)

    future, intraday, carried = asyncio.run(motilal.fetch_hub_positions(_token(), "day"))

    # Not in the day book: the untouched documented row and the option that was only carried.
    assert future == HubPosition(
        symbol="BANKNIFTY 27-OCT-2022", exchange="NFO", quantity=25.0, avg_price=40000.0,
        last_price=40100.0, pnl=2500.0, product="carryforward", product_raw="NORMAL", segment="fno",
        is_intraday=False, instrument_type="FUT", expiry="2022-10-27", strike=None, kind="day",
        name=None,
    )
    assert (intraday.symbol, intraday.quantity, intraday.avg_price, intraday.pnl, intraday.kind) == (
        "SBIN", -10.0, 579.05, 40.5, "day")
    # Only today's 5 at 2520. The row's P&L covers the carried 10 as well, so none is given.
    assert (carried.symbol, carried.quantity, carried.avg_price, carried.pnl, carried.kind) == (
        "RELIANCE", 5.0, 2520.0, 0.0, "day")


def test_exchanges_products_and_instruments_are_not_guessed(api):
    api.reply(POSITIONS_PATH, {**POSITIONS, "data": [
        _row(exchange="MCX", symbol="CRUDEOIL", productname="Value Plus", expirydate="19-Oct-2022",
             optiontype="CE", strikeprice=6450, daybuyquantity=1, daybuyamount=120, buyquantity=1, buyamount=120),
        _row(exchange="NSECD", symbol="USDINR", productname="BTST", expirydate="1350138600", optiontype="XX"),
        _row(exchange="BSEFO", symbol="SENSEX", productname="", expirydate="27-Oct-2022", optiontype="FF"),
        _row(exchange="BSECD", symbol="EURINR", productname="SELLFROMDP", expirydate="", optiontype=""),
        _row(exchange="NSEEX", symbol="GOLDX", LTP=None),
    ]})

    mcx, cds, bfo, bcd, other = asyncio.run(motilal.fetch_hub_positions(_token(), "net"))

    assert (mcx.exchange, mcx.segment, mcx.product, mcx.product_raw, mcx.is_intraday) == (
        "MCX", "commodity", "intraday", "Value Plus", True)
    assert (mcx.instrument_type, mcx.expiry, mcx.strike) == ("CE", "2022-10-19", 6450.0)
    # A product the docs list without a meaning stays None; an expiry in another shape is not passed on.
    assert (cds.exchange, cds.segment, cds.product, cds.product_raw) == ("CDS", "currency", None, "BTST")
    assert (cds.instrument_type, cds.expiry, cds.strike) == ("FUT", None, None)
    # An option type that is neither CE / PE nor the documented "XX" is not turned into anything.
    assert (bfo.exchange, bfo.segment, bfo.product, bfo.product_raw) == ("BFO", "fno", None, None)
    assert (bfo.instrument_type, bfo.expiry) == (None, "2022-10-27")
    assert (bcd.exchange, bcd.segment, bcd.product, bcd.instrument_type) == ("BCD", "currency", None, None)
    # An exchange name the hub has no segment for is kept as it is; no price is not a price of 0.
    assert (other.exchange, other.segment, other.last_price) == ("NSEEX", "equity", None)


@pytest.mark.parametrize("raw, expected", [
    ("29-Aug-2023", "2023-08-29"), (" 13-Oct-2022 ", "2022-10-13"),
    ("0", None), ("", None), (None, None), ("1350138600", None), ("2023-08-29", None),
])
def test_expiry_is_iso_or_none(raw, expected):
    assert motilal._iso_date(raw) == expected


@pytest.mark.parametrize("body", [
    {**POSITIONS, "data": []},
    {**POSITIONS, "data": None},
    _error("MO1016", "Position Not Found"),
])
def test_no_positions_is_an_empty_list(api, body):
    api.reply(POSITIONS_PATH, body)

    assert asyncio.run(motilal.fetch_hub_positions(_token(), "net")) == []
    assert asyncio.run(motilal.fetch_hub_positions(_token(), "day")) == []
    assert asyncio.run(motilal.fetch_positions(_token())) == []


def test_unknown_position_kind_is_rejected(api):
    with pytest.raises(ValueError, match="kind must be"):
        asyncio.run(motilal.fetch_hub_positions(_token(), "weekly"))
    assert api.requests == []


def test_legacy_positions_are_the_net_book(api):
    api.reply(POSITIONS_PATH, POSITIONS)

    got = asyncio.run(motilal.fetch_positions(_token()))

    assert got[0] == Position(symbol="INFY", exchange="NSE", quantity=0.0, avg_price=0.0, pnl=0.0, product="NORMAL")
    assert [(p.symbol, p.exchange, p.quantity, p.avg_price, p.pnl, p.product) for p in got[1:]] == [
        ("NIFTY 13-OCT-2022 PE 16500", "NFO", -50.0, 100.0, 1000.0, "NORMAL"),
        ("BANKNIFTY 27-OCT-2022", "NFO", 25.0, 40000.0, 2500.0, "NORMAL"),
        ("SBIN", "NSE", -10.0, 579.05, 40.5, "VALUEPLUS"),
        ("RELIANCE", "NSE", 15.0, 2440.0, 1350.0, "DELIVERY"),
    ]


# ── A session MOFSL refuses, and what is Nivesh's own fault ──────────────
@pytest.mark.parametrize("status, body", [
    (200, _error("MO8002", "Token Expired")),
    (401, _error("MO8001", "Invalid Token")),
    (200, _error("MO8003", "Token missing")),
    (200, {"status": "FAILURE", "message": "Client Not Login", "errorcode": "mo1011", "data": "null"}),
    (401, "Unauthorized"),                               # no error code at all
])
def test_a_refused_session_is_session_expired(api, status, body):
    api.reply(HOLDINGS_PATH, body, status=status)

    with pytest.raises(motilal.MotilalSessionExpired) as err:
        asyncio.run(motilal.fetch_holdings(_token()))

    assert hub_reads._is_token_rejection(err.value)
    assert _leaks(str(err.value)) == []


@pytest.mark.parametrize("status, body", [
    (200, _error("MO1004", "Invalid API Key")),
    (401, _error("MO1005", "API Key Not Found")),         # even on a 401: the key is Nivesh's
    (200, _error("MO2006", "ApiSecretKey is InVaild In Header Parameter")),
    (200, _error("MO2012", "Vendor Tag is Invalid In Header Parameter")),
    (403, _error("MO2035", "Unauthorized IP Address")),
    (200, _error("MO1006", "User Has Not Been Authorized For Live")),
    (200, FAILED),
    (403, "Forbidden"),                                   # a bare 403 says nothing about the token
    (502, "Bad Gateway"),
    (200, "<html>maintenance</html>"),
    (200, {"data": []}),                                  # no SUCCESS status never reads as "nothing held"
])
def test_an_operator_side_failure_ends_no_session(api, status, body, caplog):
    api.reply(POSITIONS_PATH, body, status=status)

    with caplog.at_level("WARNING", logger="services.brokers.motilal"):
        with pytest.raises(motilal.MotilalError) as err:
            asyncio.run(motilal.fetch_hub_positions(_token(), "net"))

    assert not isinstance(err.value, motilal.MotilalSessionExpired)
    assert not hub_reads._is_token_rejection(err.value)
    assert not hub_reads._is_not_supported(err.value)
    code = str(body.get("errorcode") or "none") if isinstance(body, dict) else "none"
    assert str(err.value) == f"Motilal Oswal positions failed (HTTP {status}, errorcode {code})"
    # The log line names the code for the operator, and nothing else of the reply.
    logged = [r.getMessage() for r in caplog.records if r.name == "services.brokers.motilal"]
    assert logged == [f"Motilal Oswal positions failed: HTTP {status}, errorcode {code}"]
    message = body.get("message") if isinstance(body, dict) else body
    for text in (str(err.value), caplog.text):
        assert _leaks(text) == [] and str(message or "no-message") not in text


def test_an_error_code_that_is_not_one_of_mofsls_is_not_repeated(api):
    api.reply(HOLDINGS_PATH, {"status": "ERROR", "message": "x", "errorcode": f"token {AUTH_TOKEN} refused"})

    with pytest.raises(motilal.MotilalError) as err:
        asyncio.run(motilal.fetch_holdings(_token()))

    assert str(err.value) == "Motilal Oswal holdings failed (HTTP 200, errorcode none)"


def test_the_hub_maps_both_failures_onto_its_own_errors(api):
    adapter = registry.get("motilal")
    api.reply(HOLDINGS_PATH, _error("MO8002", "Token Expired"))
    api.reply(POSITIONS_PATH, _error("MO2035", "Unauthorized IP Address"), status=403)

    with pytest.raises(hub_reads.BrokerSessionExpired):
        asyncio.run(hub_reads._adapter_call(adapter, "holdings", adapter.fetch_holdings, _token()))
    with pytest.raises(hub_reads.BrokerReadError) as err:
        asyncio.run(hub_reads._adapter_call(adapter, "net positions", adapter.fetch_hub_positions, _token(), "net"))

    assert not isinstance(err.value, (hub_reads.BrokerSessionExpired, hub_reads.BrokerNotSupported))


# ── Margin summary ───────────────────────────────────────────────────────
def test_funds_are_read_from_the_margin_summary(api):
    api.reply(MARGIN_PATH, MARGIN_SUMMARY)

    got = asyncio.run(motilal.fetch_funds(_token()))

    assert got == Funds(
        available_cash=999998900000.0,        # 102 Total Available Margin for Cash
        collateral=0.0,                       # 220 Non cash deposit
        used_margin=560127.5 + 547544,        # 301 + 321 + 340 + 360 + 381 Margin Usage(B)
        pnl_realized=0.0,                     # 700 Total Profit and Loss(BPL)
        pnl_unrealized=16050.07,              # 600 Total Profit and Loss(MTM)
    )
    assert (api.requests[0].method, api.requests[0].url.path) == ("POST", MARGIN_PATH)


def test_funds_default_to_zero_when_a_line_is_missing(api):
    api.reply(MARGIN_PATH, {**MARGIN_SUMMARY, "data": [{"srno": 102, "particulars": "x", "amount": 12.5}]})

    assert asyncio.run(motilal.fetch_funds(_token())) == Funds(available_cash=12.5)
