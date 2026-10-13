"""Unit tests for services.brokers.fenix_reader.

Fenix's HTTP layer is stubbed. Every Fenix object built during a test gets a
fake `requests` session that answers from canned payloads shaped like the
brokers' documented responses, and records each request it is asked to make.
Nothing here talks to a broker, so these tests prove the header construction,
the mapping and the error handling. They do NOT prove a read against a live
account.

Payload sources: Kite Connect v3 docs (Zerodha), Upstox v2 docs, Fyers v3
docs, SmartAPI docs (Angel One), Groww trade-API docs, DhanHQ v2 docs. The
AliceBlue payloads follow the legacy ANT response as best recalled; AliceBlue
no longer publishes that page, so that shape is unconfirmed.

Tests that need the `fenix` package are skipped when it is not installed; the
"fenix is not installed" behaviour is tested in both cases.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests

from services.brokers import fenix_reader as fr
from services.brokers import registry
from services.brokers.base import AccessToken, Holding, HubPosition

HAVE_FENIX = importlib.util.find_spec("fenix") is not None
needs_fenix = pytest.mark.skipif(not HAVE_FENIX, reason="fenix is not installed in this image")

# ── Obviously fake credentials (never real) ──────────────────────────────
KITE_APP_KEY = "kiteappkey00test"
KITE_TOKEN = "KITE-ACCESS-TOKEN-do-not-leak-0001"
KITE_USER = "ZX9912"
UPSTOX_TOKEN = "UPSTOX-ACCESS-TOKEN-do-not-leak-0002"
FYERS_APP_KEY = "FYAPP12345-100"
FYERS_TOKEN = "FYERS-ACCESS-TOKEN-do-not-leak-0003"
ALICE_USER = "AB778899"
ALICE_SESSION = "ALICE-SESSION-ID-do-not-leak-0004"
DHAN_CLIENT = "1100778899"
DHAN_TOKEN = "DHAN-ACCESS-TOKEN-do-not-leak-0005"
ANGEL_JWT = "ANGEL-JWT-do-not-leak-0006"
ANGEL_FEED = "ANGEL-FEED-TOKEN-do-not-leak-0007"
ANGEL_CLIENT = "A55667788"
ANGEL_APP_KEY = "angelAppKey9"
GROWW_TOKEN = "GROWW-ACCESS-TOKEN-do-not-leak-0008"

SECRETS = [
    KITE_APP_KEY, KITE_TOKEN, KITE_USER, UPSTOX_TOKEN, FYERS_APP_KEY, FYERS_TOKEN,
    ALICE_USER, ALICE_SESSION, DHAN_CLIENT, DHAN_TOKEN, ANGEL_JWT, ANGEL_FEED,
    ANGEL_CLIENT, ANGEL_APP_KEY, GROWW_TOKEN,
]

APP_KEYS = {
    "BROKER_ZERODHA_API_KEY": KITE_APP_KEY,
    "BROKER_FYERS_API_KEY": FYERS_APP_KEY,
}

TOKENS = {
    "zerodha": AccessToken(token=KITE_TOKEN, extras={"user_id": KITE_USER, "broker": "ZERODHA"}),
    "upstox": AccessToken(token=UPSTOX_TOKEN, extras={"user_id": "7XAB12", "expires_in": None}),
    "fyers": AccessToken(token=FYERS_TOKEN, extras={"refresh_token": "r", "expires_in": None}),
    "aliceblue": AccessToken(token=ALICE_SESSION, extras={"user_id": ALICE_USER}),
    "dhan": AccessToken(token=DHAN_TOKEN, extras={"client_id": DHAN_CLIENT}),
}

EXPECTED_HEADERS = {
    "zerodha": {
        "X-Kite-Version": "3",
        "User-Agent": "Kiteconnect-python/4.2.0",
        "Authorization": f"token {KITE_APP_KEY}:{KITE_TOKEN}",
        "user_id": KITE_USER,
        "api_key": KITE_APP_KEY,
        "access_token": KITE_TOKEN,
    },
    "upstox": {
        "Authorization": f"Bearer {UPSTOX_TOKEN}",
        "Accept": "application/json",
    },
    "fyers": {"Authorization": f"{FYERS_APP_KEY}:{FYERS_TOKEN}"},
    "aliceblue": {
        "ID": ALICE_USER,
        "AccessToken": ALICE_SESSION,
        "Authorization": f"Bearer {ALICE_USER} {ALICE_SESSION}",
        "X-SAS-Version": "2.0",
        "User-Agent": "AliceBlue_V21.0.1",
        "Content-Type": "application/json",
        "susertoken": hashlib.sha256(
            hashlib.sha256(ALICE_SESSION.encode()).hexdigest().encode(),
        ).hexdigest(),
    },
    "dhan": {
        "access-token": DHAN_TOKEN,
        "Accept": "application/json",
        "user_id": DHAN_CLIENT,
    },
}

FENIX_CLASS_OF = {
    "zerodha": "Zerodha", "upstox": "Upstox", "fyers": "Fyers",
    "aliceblue": "AliceBlue", "dhan": "Dhan",
}

# ── Read endpoints (the only URLs a read may touch) ──────────────────────
URL = {
    ("zerodha", "holdings"): "https://api.kite.trade/portfolio/holdings",
    ("zerodha", "positions"): "https://api.kite.trade/portfolio/positions",
    ("upstox", "holdings"): "https://api.upstox.com/v2/portfolio/long-term-holdings",
    ("upstox", "positions"): "https://api.upstox.com/v2/portfolio/short-term-positions",
    ("fyers", "holdings"): "https://api-t1.fyers.in/api/v3/holdings",
    ("fyers", "positions"): "https://api-t1.fyers.in/api/v3/positions",
    ("aliceblue", "holdings"):
        "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/positionAndHoldings/holdings",
    ("aliceblue", "positions"):
        "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/positionAndHoldings/positionBook",
    ("dhan", "holdings"): "https://api.dhan.co/v2/holdings",
    ("dhan", "positions"): "https://api.dhan.co/v2/positions",
    ("angel", "holdings"):
        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/portfolio/v1/getAllHolding",
    ("angel", "positions"):
        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/getPosition",
    ("groww", "holdings"): "https://api.groww.in/v1/holdings/user",
    ("groww", "positions"): "https://api.groww.in/v1/positions/user",
}


# ── Fake HTTP layer ──────────────────────────────────────────────────────
def _response(status: int, payload: Any, url: str) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = (payload if isinstance(payload, str) else json.dumps(payload)).encode("utf-8")
    resp.encoding = "utf-8"
    resp.url = url
    resp.reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                   500: "Internal Server Error"}.get(status, "")
    resp.headers["Content-Type"] = "application/json"
    return resp


class FakeHTTP:
    """Stands in for `requests.Session` inside every Fenix object."""

    def __init__(self) -> None:
        self.routes: Dict[str, Any] = {}
        self.calls: List[Dict[str, Any]] = []
        self.sessions = 0
        self.closed = 0

    def reply(self, url: str, payload: Any, status: int = 200) -> None:
        self.routes[url] = (status, payload)

    def fail(self, url: str, exc: Exception) -> None:
        self.routes[url] = exc

    def make_session(self) -> "_FakeSession":
        self.sessions += 1
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, http: FakeHTTP) -> None:
        self._http = http

    def request(self, method=None, url=None, headers=None, data=None, json=None,
                params=None, **_kwargs):
        self._http.calls.append({
            "method": method, "url": url, "headers": dict(headers or {}),
            "json": json, "data": data, "params": params,
            "thread": threading.current_thread().name,
        })
        if url not in self._http.routes:
            raise AssertionError(f"unexpected request: {method} {url}")
        outcome = self._http.routes[url]
        if isinstance(outcome, Exception):
            raise outcome
        status, payload = outcome
        return _response(status, payload, url)

    def close(self) -> None:
        self._http.closed += 1


@pytest.fixture
def app_keys(monkeypatch):
    monkeypatch.setattr(fr, "conf", lambda key: APP_KEYS.get(key, ""))


@pytest.fixture
def http(monkeypatch, app_keys):
    import fenix

    fake = FakeHTTP()
    monkeypatch.setattr(fenix.Broker, "_create_session", staticmethod(fake.make_session))
    return fake


def run(coro):
    return asyncio.run(coro)


def fenix_rows(http, class_name, slug, method, headers=None):
    """What the installed Fenix class itself returns for one read (stubbed
    HTTP), through the reader's own synchronous call path."""
    import fenix

    headers = dict(headers or EXPECTED_HEADERS[slug])
    return fr._read_sync(slug, getattr(fenix, class_name), headers, {}, method)


# ── Documented-shape payloads ────────────────────────────────────────────
def kite_holding(symbol, isin, qty, avg, ltp, exchange="NSE"):
    return {
        "tradingsymbol": symbol, "exchange": exchange, "instrument_token": 408065, "isin": isin,
        "product": "CNC", "price": 0, "quantity": qty, "used_quantity": 0, "t1_quantity": 0,
        "realised_quantity": qty, "authorised_quantity": 0, "authorised_date": "2026-10-13 00:00:00",
        "opening_quantity": qty, "collateral_quantity": 0, "collateral_type": "",
        "discrepancy": False, "average_price": avg, "last_price": ltp, "close_price": ltp,
        "pnl": round((ltp - avg) * qty, 2), "day_change": 0.5, "day_change_percentage": 0.03,
    }


KITE_HOLDINGS = {"status": "success", "data": [
    kite_holding("INFY", "INE009A01021", 10, 1450.5, 1502.25),
    kite_holding("NIFTYBEES", "INF204KB14I2", 25, 251.1, 262.4),
]}


def kite_position(symbol, exchange, product, qty, avg, ltp, pnl):
    return {
        "tradingsymbol": symbol, "exchange": exchange, "instrument_token": 13825026,
        "product": product, "quantity": qty, "overnight_quantity": 0, "multiplier": 1,
        "average_price": avg, "close_price": avg, "last_price": ltp, "value": -avg * qty,
        "pnl": pnl, "m2m": pnl, "unrealised": pnl, "realised": 0,
        "buy_quantity": max(qty, 0), "buy_price": avg, "buy_value": avg * max(qty, 0), "buy_m2m": 0,
        "sell_quantity": max(-qty, 0), "sell_price": avg, "sell_value": avg * max(-qty, 0), "sell_m2m": 0,
        "day_buy_quantity": max(qty, 0), "day_buy_price": avg, "day_buy_value": avg * max(qty, 0),
        "day_sell_quantity": max(-qty, 0), "day_sell_price": avg, "day_sell_value": avg * max(-qty, 0),
    }


KITE_POSITIONS = {"status": "success", "data": {
    "net": [
        kite_position("NIFTY26OCT25000CE", "NFO", "NRML", 75, 150.4, 166.0, 1170.0),
        kite_position("NIFTY26OCTFUT", "NFO", "MIS", -75, 25010.0, 24990.0, 1500.0),
        kite_position("SBIN", "NSE", "MIS", 100, 801.0, 803.5, 250.0),
        kite_position("INFY", "NSE", "CNC", 5, 1500.0, 1502.25, 11.25),
        kite_position("CRUDEOIL26OCTFUT", "MCX", "NRML", 1, 6400.0, 6425.0, 2500.0),
        kite_position("USDINR26OCTFUT", "CDS", "NRML", -2, 88.1, 88.05, 100.0),
    ],
    "day": [
        kite_position("NIFTY26OCTFUT", "NFO", "MIS", -75, 25010.0, 24990.0, 1500.0),
        kite_position("SBIN", "NSE", "MIS", 40, 802.0, 803.5, 60.0),
    ],
}}

UPSTOX_HOLDINGS = {"status": "success", "data": [
    {"isin": "INE528G01035", "cnc_used_quantity": 0, "collateral_type": "WC",
     "company_name": "YES BANK LTD.", "haircut": 0.2, "product": "D", "quantity": 36,
     "trading_symbol": "YESBANK", "tradingsymbol": "YESBANK", "last_price": 17.05,
     "close_price": 17.05, "pnl": -61.2, "day_change": 0, "day_change_percentage": 0,
     "instrument_token": "NSE_EQ|INE528G01035", "average_price": 18.75, "collateral_quantity": 0,
     "collateral_update_quantity": 0, "t1_quantity": 0, "exchange": "NSE"},
    {"isin": "INF204KB17I5", "cnc_used_quantity": 0, "collateral_type": "WC",
     "company_name": "NIPPON INDIA ETF GOLD BEES", "haircut": 0.1, "product": "D", "quantity": 100,
     "trading_symbol": "GOLDBEES", "tradingsymbol": "GOLDBEES", "last_price": 61.2,
     "close_price": 61.0, "pnl": 120.0, "day_change": 0.2, "day_change_percentage": 0.3,
     "instrument_token": "NSE_EQ|INF204KB17I5", "average_price": 60.0, "collateral_quantity": 0,
     "collateral_update_quantity": 0, "t1_quantity": 0, "exchange": "NSE"},
]}


def upstox_position(symbol, exchange, product, qty, avg, ltp, unrealised, realised=0.0):
    return {
        "exchange": exchange, "multiplier": 1.0, "value": avg * qty, "pnl": unrealised + realised,
        "product": product, "instrument_token": "NSE_FO|43919", "average_price": avg,
        "buy_value": avg * qty, "overnight_quantity": 0, "day_buy_value": avg * qty,
        "day_buy_price": avg, "overnight_buy_amount": 0.0, "overnight_buy_quantity": 0,
        "day_buy_quantity": qty, "day_sell_value": 0.0, "day_sell_price": 0.0,
        "overnight_sell_amount": 0.0, "overnight_sell_quantity": 0, "day_sell_quantity": 0,
        "quantity": qty, "last_price": ltp, "unrealised": unrealised, "realised": realised,
        "sell_value": 0.0, "trading_symbol": symbol, "tradingsymbol": symbol,
        "close_price": avg, "buy_price": avg, "sell_price": 0.0,
    }


UPSTOX_POSITIONS = {"status": "success", "data": [
    upstox_position("NIFTY26OCT25000CE", "NFO", "D", 75, 150.4, 166.0, 1170.0),
    upstox_position("SBIN", "NSE", "I", 100, 801.0, 803.5, 250.0),
    upstox_position("INFY", "NSE", "D", 5, 1500.0, 1502.25, 11.25, realised=3.0),
]}

FYERS_HOLDINGS = {"s": "ok", "code": 200, "message": "", "holdings": [
    {"holdingType": "HLD", "quantity": 18, "costPrice": 1150.2, "marketVal": 21600.0,
     "remainingQuantity": 18, "pl": 896.4, "ltp": 1200.0, "id": 0, "fyToken": "10100000002885",
     "exchange": 10, "symbol": "NSE:RELIANCE-EQ", "segment": 10, "isin": "INE002A01018",
     "qty_t1": 0, "remainingPledgeQuantity": 0, "collateralQuantity": 0},
], "overall": {"count_total": 1, "total_investment": 20703.6, "total_current_value": 21600.0,
               "total_pl": 896.4, "pnl_perc": 4.33}}


def fyers_position(symbol, exchange, segment, product, qty, avg, ltp, pl):
    return {
        "netQty": qty, "qty": abs(qty), "avgPrice": avg, "netAvg": avg, "side": 1 if qty >= 0 else -1,
        "productType": product, "realized_profit": 0.0, "unrealized_profit": pl, "pl": pl, "ltp": ltp,
        "buyQty": max(qty, 0), "buyAvg": avg, "buyVal": avg * max(qty, 0),
        "sellQty": max(-qty, 0), "sellAvg": 0.0, "sellVal": 0.0, "slNo": 0,
        "fyToken": "1120200831217406", "crossCurrency": "N", "rbiRefRate": 1.0, "qtyMulti_com": 1.0,
        "segment": segment, "symbol": symbol, "id": f"{symbol}-{product}",
        "cfBuyQty": 0, "cfSellQty": 0, "dayBuyQty": max(qty, 0), "daySellQty": max(-qty, 0),
        "exchange": exchange,
    }


FYERS_POSITIONS = {"s": "ok", "code": 200, "message": "", "netPositions": [
    fyers_position("MCX:SILVERMIC26NOVFUT", 11, 20, "MARGIN", 1, 71856.0, 72717.0, 861.0),
    fyers_position("NSE:USDINR26OCTFUT", 10, 12, "CARRYFORWARD", -2, 88.1, 88.05, 100.0),
    fyers_position("NSE:SBIN-EQ", 10, 10, "INTRADAY", 100, 801.0, 803.5, 250.0),
    fyers_position("NSE:NIFTY26OCT25000PE", 10, 11, "CARRYFORWARD", 75, 90.0, 80.0, -750.0),
], "overall": {"count_total": 4, "count_open": 4, "pl_total": 461.0, "pl_realized": 0.0,
               "pl_unrealized": 461.0}}

# Legacy ANT (NEST) shape as best recalled: unconfirmed against AliceBlue today.
ALICE_HOLDINGS = {"stat": "Ok", "clientid": ALICE_USER, "HoldingVal": [
    {"Nsetsym": "ITC-EQ", "Bsetsym": "ITC", "ExchSeg1": "NSE", "ExchSeg2": "BSE", "Pcode": "CNC",
     "Holdqty": "0", "HUqty": "0", "SellableQty": "12", "Btst": "0", "Usedqty": "0", "Colqty": "0",
     "Price": "410.25", "LTnse": "431.10", "LTbse": "431.00", "isin": "INE154A01025",
     "Token1": "1660", "Token2": "500875", "Series": "EQ"},
    {"Nsetsym": "0", "Bsetsym": "BSEONLYCO", "ExchSeg1": "", "ExchSeg2": "BSE", "Pcode": "CNC",
     "Holdqty": "7", "HUqty": "0", "SellableQty": "7", "Btst": "0", "Usedqty": "0", "Colqty": "0",
     "Price": "55.00", "LTnse": "", "LTbse": "58.40", "isin": "INE000X01010",
     "Token1": "0", "Token2": "512345", "Series": "B"},
]}
ALICE_POSITIONS = [
    {"Tsym": "NIFTY26OCT25000CE", "Exchange": "NFO", "Exchangeseg": "nse_fo", "Pcode": "NRML",
     "Netqty": "75", "Bqty": "75", "Sqty": "0", "Buyavgprc": "150.40", "Sellavgprc": "0.00",
     "LTP": "166.00", "MtoM": "1,170.00", "realisedprofitloss": "0.00",
     "unrealisedprofitloss": "1,170.00", "Opttype": "CE", "Stikeprc": "25000.00",
     "Expdate": "28 Oct 2026", "Instname": "OPTIDX", "Symbol": "NIFTY", "Token": "43919",
     "companyname": "NIFTY", "stat": "Ok"},
    {"Tsym": "SBIN-EQ", "Exchange": "NSE", "Exchangeseg": "nse_cm", "Pcode": "MIS",
     "Netqty": "-10", "Bqty": "0", "Sqty": "10", "Buyavgprc": "0.00", "Sellavgprc": "805.00",
     "LTP": "803.50", "MtoM": "15.00", "realisedprofitloss": "0.00",
     "unrealisedprofitloss": "15.00", "Opttype": "XX", "Stikeprc": "0.00", "Expdate": "NA",
     "Instname": "", "Symbol": "SBIN", "Token": "3045",
     "companyname": "STATE BANK OF INDIA", "stat": "Ok"},
]

DHAN_HOLDINGS = [
    {"exchange": "ALL", "tradingSymbol": "HDFC", "securityId": "1330", "isin": "INE001A01036",
     "totalQty": 1000, "dpQty": 1000, "t1Qty": 0, "availableQty": 1000, "collateralQty": 0,
     "avgCostPrice": 2655.0, "lastTradedPrice": 2710.5},
]
DHAN_POSITIONS = [
    {"dhanClientId": DHAN_CLIENT, "tradingSymbol": "TCS", "securityId": "11536",
     "positionType": "LONG", "exchangeSegment": "NSE_EQ", "productType": "CNC", "buyAvg": 3345.8,
     "buyQty": 40, "costPrice": 3215.0, "sellAvg": 0.0, "sellQty": 0, "netQty": 40,
     "realizedProfit": 0.0, "unrealizedProfit": 6122.0, "rbiReferenceRate": 1.0, "multiplier": 1,
     "carryForwardBuyQty": 0, "carryForwardSellQty": 0, "carryForwardBuyValue": 0.0,
     "carryForwardSellValue": 0.0, "dayBuyQty": 40, "daySellQty": 0, "dayBuyValue": 133832.0,
     "daySellValue": 0.0, "drvExpiryDate": "0001-01-01", "drvOptionType": None,
     "drvStrikePrice": 0.0, "crossCurrency": False},
    {"dhanClientId": DHAN_CLIENT, "tradingSymbol": "NIFTY-Oct2026-25000-PE", "securityId": "52175",
     "positionType": "SHORT", "exchangeSegment": "NSE_FNO", "productType": "MARGIN",
     "buyAvg": 0.0, "buyQty": 0, "costPrice": 90.0, "sellAvg": 90.0, "sellQty": 75, "netQty": -75,
     "realizedProfit": 100.0, "unrealizedProfit": 750.0, "rbiReferenceRate": 1.0, "multiplier": 1,
     "carryForwardBuyQty": 0, "carryForwardSellQty": 0, "carryForwardBuyValue": 0.0,
     "carryForwardSellValue": 0.0, "dayBuyQty": 0, "daySellQty": 75, "dayBuyValue": 0.0,
     "daySellValue": 6750.0, "drvExpiryDate": "2026-10-27", "drvOptionType": "PUT",
     "drvStrikePrice": 25000.0, "crossCurrency": False},
]

ANGEL_HOLDINGS = {"status": True, "message": "SUCCESS", "errorcode": "", "data": {
    "holdings": [
        {"tradingsymbol": "TATASTEEL-EQ", "exchange": "NSE", "isin": "INE081A01020",
         "t1quantity": 0, "realisedquantity": 2, "quantity": 2, "authorisedquantity": 0,
         "product": "DELIVERY", "collateralquantity": None, "collateraltype": None, "haircut": 0,
         "averageprice": 111.87, "ltp": 130.15, "symboltoken": "3499", "close": 129.6,
         "profitandloss": 37, "pnlpercentage": 16.34},
    ],
    "totalholding": {"totalholdingvalue": 260.3, "totalinvvalue": 223.74,
                     "totalprofitandloss": 36.56, "totalpnlpercentage": 16.34},
}}
ANGEL_POSITIONS = {"status": True, "message": "SUCCESS", "errorcode": "", "data": [
    {"exchange": "NFO", "symboltoken": "39619", "producttype": "CARRYFORWARD",
     "tradingsymbol": "NIFTY27OCT2625000CE", "symbolname": "NIFTY", "instrumenttype": "OPTIDX",
     "priceden": "1", "pricenum": "1", "genden": "1", "gennum": "1", "precision": "2",
     "multiplier": "-1", "boardlotsize": "1", "buyqty": "75", "sellqty": "0",
     "buyamount": "11280", "sellamount": "0", "symbolgroup": "XX", "strikeprice": "25000.0",
     "optiontype": "CE", "expirydate": "27OCT2026", "lotsize": "75", "cfbuyqty": "0",
     "cfsellqty": "0", "cfbuyamount": "0", "cfsellamount": "0", "buyavgprice": "150.4",
     "sellavgprice": "0", "avgnetprice": "150.4", "netvalue": "-11280", "netqty": "75",
     "totalbuyvalue": "11280", "totalsellvalue": "0", "cfbuyavgprice": "0",
     "cfsellavgprice": "0", "totalbuyavgprice": "150.4", "totalsellavgprice": "0",
     "netprice": "150.4", "realised": "0", "unrealised": "1170", "ltp": "166", "pnl": "1170",
     "close": "150"},
]}

GROWW_HOLDINGS = {"status": "SUCCESS", "payload": {"holdings": [
    {"isin": "INE545U01014", "trading_symbol": "BANDHANBNK", "quantity": 20,
     "average_price": 262.5, "pledge_quantity": 0, "demat_locked_quantity": 0,
     "groww_locked_quantity": 0, "repledge_quantity": 0, "t1_quantity": 0,
     "demat_free_quantity": 20, "corporate_action_additional_quantity": 0,
     "active_demat_transfer_quantity": 0},
]}}
GROWW_POSITIONS = {"status": "SUCCESS", "payload": {"positions": [
    {"trading_symbol": "RELIANCE", "segment": "CASH", "credit_quantity": 10, "credit_price": 1250.0,
     "debit_quantity": 5, "debit_price": 1200.0, "carry_forward_credit_quantity": 8,
     "carry_forward_credit_price": 1230.0, "carry_forward_debit_quantity": 3,
     "carry_forward_debit_price": 1180.0, "exchange": "NSE", "symbol_isin": "INE002A01018",
     "quantity": 15, "product": "CNC", "net_carry_forward_quantity": 10, "net_price": 1240.0,
     "net_carry_forward_price": 1220.0, "realised_pnl": 500.0},
    {"trading_symbol": "NIFTY26OCT25000CE", "segment": "FNO", "credit_quantity": 75,
     "credit_price": 150.4, "debit_quantity": 0, "debit_price": 0.0, "exchange": "NSE",
     "quantity": 75, "product": "NRML", "net_price": 150.4, "realised_pnl": 0.0},
]}}


# ── Fake adapters for the hook ───────────────────────────────────────────
class FakeAngelAdapter:
    SLUG = "fakeangel"
    DISPLAY = "Fake Angel"
    AUTH_STYLE = "oauth"
    FENIX_CLASS = "AngelOne"

    @staticmethod
    def fenix_headers(token: AccessToken) -> Dict[str, str]:
        return {
            "Content-type": "application/json",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "Accept": "application/json",
            "X-PrivateKey": ANGEL_APP_KEY,
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "Authorization": f"Bearer {token.token}",
            "x-api-key": ANGEL_APP_KEY,
            "x-client-code": token.extras["client_code"],
            "x-feed-token": token.extras["feedToken"],
        }


ANGEL_TOKEN = AccessToken(token=ANGEL_JWT, extras={"client_code": ANGEL_CLIENT, "feedToken": ANGEL_FEED})


class FakeGrowwAdapter:
    SLUG = "fakegroww"
    DISPLAY = "Fake Groww"
    AUTH_STYLE = "oauth"
    FENIX_CLASS = "Groww"

    @staticmethod
    def fenix_headers(token: AccessToken) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-client-id": "growwapi",
            "x-api-version": "1.0",
        }


class FakeDhanViaHook:
    """Supplies Fenix's auth context through `fenix_auth_params`."""
    SLUG = "fakedhan"
    DISPLAY = "Fake Dhan"
    AUTH_STYLE = "apikey"
    FENIX_CLASS = "Dhan"

    @staticmethod
    def fenix_headers(token: AccessToken) -> Dict[str, str]:
        return {"access-token": token.token, "Accept": "application/json"}

    @staticmethod
    def fenix_auth_params(token: AccessToken) -> Dict[str, Any]:
        return {"user_id": token.extras["client_id"]}


def register(monkeypatch, adapter, slug=None):
    monkeypatch.setitem(registry._REGISTRY, slug or adapter.SLUG, adapter)


def assert_no_secret(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"secret leaked into: {text!r}"


_DETAIL = r"\(\w+(, HTTP \d{3})?(, broker code [A-Za-z0-9_.\-]{1,24})?\)"


def assert_only_safe_parts(text: str, slug: str, what: str) -> None:
    """A failure message is the slug, fixed words, the error class, the HTTP
    status and a short broker code. Nothing else: no URL, no broker text."""
    assert re.fullmatch(f"{re.escape(slug)}: {what} {_DETAIL}", text), text


# ═════════════════════════════════════════════════════════════════════════
# Header construction
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("slug", sorted(EXPECTED_HEADERS))
def test_builtin_header_dict_is_built_from_stored_session(slug, app_keys):
    assert dict(fr._BUILTIN[slug].headers(TOKENS[slug])) == EXPECTED_HEADERS[slug]


@needs_fenix
@pytest.mark.parametrize("slug", sorted(EXPECTED_HEADERS))
def test_builtin_headers_satisfy_what_the_fenix_class_requires(slug, app_keys):
    import fenix

    cls = getattr(fenix, FENIX_CLASS_OF[slug])
    built = EXPECTED_HEADERS[slug]
    assert fr._BUILTIN[slug].fenix_class == FENIX_CLASS_OF[slug]
    assert set(cls._REQUIRED_AUTH_HEADER_KEYS) <= set(built)
    assert set(cls._AUTH_CONTEXT_KEYS) <= set(built)
    # Fenix accepts the dict as a restored session.
    restored = cls({"logger": logging.getLogger("test.fenix")}).use_headers(dict(built))
    assert restored == built


@needs_fenix
@pytest.mark.parametrize("slug,payload", [
    ("zerodha", KITE_HOLDINGS), ("upstox", UPSTOX_HOLDINGS), ("fyers", FYERS_HOLDINGS),
    ("aliceblue", ALICE_HOLDINGS), ("dhan", DHAN_HOLDINGS),
])
def test_headers_on_the_wire_and_exactly_one_request_per_read(slug, payload, http):
    http.reply(URL[(slug, "holdings")], payload)
    run(fr.read_holdings(slug, TOKENS[slug]))

    assert len(http.calls) == 1, "a read must be exactly one HTTP request"
    call = http.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == URL[(slug, "holdings")]
    sent = dict(EXPECTED_HEADERS[slug])
    if slug == "dhan":
        sent.pop("user_id")  # auth context: Fenix keeps the client id off the wire
    assert call["headers"] == sent
    assert call["thread"] != threading.main_thread().name, "Fenix must run off the event loop"


def test_missing_app_key_is_a_clean_read_error(monkeypatch):
    monkeypatch.setattr(fr, "conf", lambda key: "")
    with pytest.raises(fr.BrokerReadError) as err:
        fr._zerodha_headers(TOKENS["zerodha"])
    assert "BROKER_ZERODHA_API_KEY is not configured" in str(err.value)
    assert not isinstance(err.value, (fr.BrokerSessionExpired, fr.BrokerNotSupported))
    assert_no_secret(str(err.value))


def test_incomplete_stored_session_names_the_missing_field(app_keys):
    with pytest.raises(fr.BrokerReadError) as err:
        fr._aliceblue_headers(AccessToken(token=ALICE_SESSION, extras={}))
    assert "user id" in str(err.value)
    with pytest.raises(fr.BrokerReadError) as err:
        fr._upstox_headers(AccessToken(token="", extras={}))
    assert "access token" in str(err.value)
    with pytest.raises(fr.BrokerReadError):
        fr._dhan_headers(AccessToken(token=DHAN_TOKEN, extras={}))


# ═════════════════════════════════════════════════════════════════════════
# Holdings
# ═════════════════════════════════════════════════════════════════════════
@needs_fenix
def test_zerodha_holdings_unified_records(http):
    http.reply(URL[("zerodha", "holdings")], KITE_HOLDINGS)
    rows = run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    assert rows == [
        Holding(isin="INE009A01021", symbol="INFY", asset_type="equity", quantity=10.0,
                avg_price=1450.5, current_price=1502.25, name="INFY", sector=None,
                exchange="NSE", source_id="NSE:INFY"),
        Holding(isin="INF204KB14I2", symbol="NIFTYBEES", asset_type="etf", quantity=25.0,
                avg_price=251.1, current_price=262.4, name="NIFTYBEES", sector=None,
                exchange="NSE", source_id="NSE:NIFTYBEES"),
    ]


@needs_fenix
def test_upstox_holdings_broker_rows(http):
    http.reply(URL[("upstox", "holdings")], UPSTOX_HOLDINGS)
    rows = run(fr.read_holdings("upstox", TOKENS["upstox"]))
    assert rows == [
        Holding(isin="INE528G01035", symbol="YESBANK", asset_type="equity", quantity=36.0,
                avg_price=18.75, current_price=17.05, name="YES BANK LTD.", sector=None,
                exchange="NSE", source_id="NSE:YESBANK"),
        Holding(isin="INF204KB17I5", symbol="GOLDBEES", asset_type="etf", quantity=100.0,
                avg_price=60.0, current_price=61.2, name="NIPPON INDIA ETF GOLD BEES",
                sector=None, exchange="NSE", source_id="NSE:GOLDBEES"),
    ]


@needs_fenix
def test_fyers_holdings_whole_response_and_symbol_prefix(http):
    http.reply(URL[("fyers", "holdings")], FYERS_HOLDINGS)
    rows = run(fr.read_holdings("fyers", TOKENS["fyers"]))
    assert rows == [
        Holding(isin="INE002A01018", symbol="RELIANCE", asset_type="equity", quantity=18.0,
                avg_price=1150.2, current_price=1200.0, name="RELIANCE", sector=None,
                exchange="NSE", source_id="NSE:RELIANCE-EQ"),
    ]


@needs_fenix
def test_aliceblue_holdings_legacy_rows(http):
    http.reply(URL[("aliceblue", "holdings")], ALICE_HOLDINGS)
    rows = run(fr.read_holdings("aliceblue", TOKENS["aliceblue"]))
    assert rows == [
        Holding(isin="INE154A01025", symbol="ITC", asset_type="equity", quantity=12.0,
                avg_price=410.25, current_price=431.1, name="ITC", sector=None,
                exchange="NSE", source_id="NSE:ITC-EQ"),
        Holding(isin="INE000X01010", symbol="BSEONLYCO", asset_type="equity", quantity=7.0,
                avg_price=55.0, current_price=58.4, name="BSEONLYCO", sector=None,
                exchange="BSE", source_id="BSE:BSEONLYCO"),
    ]


@needs_fenix
def test_dhan_holdings_unknown_exchange_stays_none(http):
    http.reply(URL[("dhan", "holdings")], DHAN_HOLDINGS)
    rows = run(fr.read_holdings("dhan", TOKENS["dhan"]))
    assert rows == [
        Holding(isin="INE001A01036", symbol="HDFC", asset_type="equity", quantity=1000.0,
                avg_price=2655.0, current_price=2710.5, name="HDFC", sector=None,
                exchange=None, source_id="HDFC"),
    ]


@needs_fenix
def test_empty_holdings_is_an_empty_list(http):
    http.reply(URL[("zerodha", "holdings")], {"status": "success", "data": []})
    http.reply(URL[("fyers", "holdings")], {"s": "ok", "code": 200, "holdings": [], "overall": {}})
    assert run(fr.read_holdings("zerodha", TOKENS["zerodha"])) == []
    assert run(fr.read_holdings("fyers", TOKENS["fyers"])) == []


@needs_fenix
def test_unrecognised_holdings_shape_fails_instead_of_returning_nothing(http):
    http.reply(URL[("upstox", "holdings")], {"status": "success", "data": [{"foo": 1}, {"bar": 2}]})
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("upstox", TOKENS["upstox"]))
    assert "none of the 2 holdings rows" in str(err.value)

    http.reply(URL[("fyers", "holdings")], {"s": "ok", "code": 200, "unexpected": {}})
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("fyers", TOKENS["fyers"]))
    assert "not recognised" in str(err.value)


# ═════════════════════════════════════════════════════════════════════════
# Positions
# ═════════════════════════════════════════════════════════════════════════
@needs_fenix
def test_zerodha_net_and_day_books_are_different_reads_of_one_endpoint(http):
    http.reply(URL[("zerodha", "positions")], KITE_POSITIONS)
    net = run(fr.read_positions("zerodha", TOKENS["zerodha"]))
    day = run(fr.read_positions("zerodha", TOKENS["zerodha"], kind="day"))

    assert [c["url"] for c in http.calls] == [URL[("zerodha", "positions")]] * 2
    assert all(isinstance(p, HubPosition) for p in net + day)
    assert [p.symbol for p in net] == [
        "NIFTY26OCT25000CE", "NIFTY26OCTFUT", "SBIN", "INFY", "CRUDEOIL26OCTFUT", "USDINR26OCTFUT",
    ]
    assert {p.kind for p in net} == {"net"}
    assert [(p.symbol, p.quantity, p.kind) for p in day] == [
        ("NIFTY26OCTFUT", -75.0, "day"), ("SBIN", 40.0, "day"),
    ]
    # The same instrument differs between the two books.
    assert next(p for p in net if p.symbol == "SBIN").quantity == 100.0


@needs_fenix
def test_zerodha_option_and_future(http):
    http.reply(URL[("zerodha", "positions")], KITE_POSITIONS)
    by_symbol = {p.symbol: p for p in run(fr.read_positions("zerodha", TOKENS["zerodha"]))}

    option = by_symbol["NIFTY26OCT25000CE"]
    assert option == HubPosition(
        symbol="NIFTY26OCT25000CE", exchange="NFO", quantity=75.0, avg_price=150.4,
        last_price=166.0, pnl=1170.0, product="carryforward", product_raw="NRML",
        segment="fno", is_intraday=False, instrument_type="CE", expiry=None, strike=None,
        kind="net", name=None,
    )
    future = by_symbol["NIFTY26OCTFUT"]
    assert (future.segment, future.instrument_type, future.quantity) == ("fno", "FUT", -75.0)
    assert (future.product, future.product_raw, future.is_intraday) == ("intraday", "MIS", True)
    # Kite sends no contract details and no name: they are left empty, not derived.
    assert (future.expiry, future.strike, future.name) == (None, None, None)


@needs_fenix
def test_zerodha_segment_and_intraday_classification(http):
    http.reply(URL[("zerodha", "positions")], KITE_POSITIONS)
    got = {
        p.symbol: (p.exchange, p.segment, p.product, p.is_intraday, p.instrument_type)
        for p in run(fr.read_positions("zerodha", TOKENS["zerodha"]))
    }
    assert got == {
        "NIFTY26OCT25000CE": ("NFO", "fno", "carryforward", False, "CE"),
        "NIFTY26OCTFUT": ("NFO", "fno", "intraday", True, "FUT"),
        "SBIN": ("NSE", "equity", "intraday", True, None),
        "INFY": ("NSE", "equity", "delivery", False, None),
        "CRUDEOIL26OCTFUT": ("MCX", "commodity", "carryforward", False, "FUT"),
        "USDINR26OCTFUT": ("CDS", "currency", "carryforward", False, "FUT"),
    }


@needs_fenix
def test_upstox_net_positions_map_from_either_record_shape(http):
    """Fenix 2.0.2 hands back Upstox's own rows from `fetch_net_positions()`
    (it builds unified records and then returns the raw list). The mapping
    must give the same result for those rows and for unified records, so it
    keeps working if Fenix starts returning what it builds."""
    import fenix

    http.reply(URL[("upstox", "positions")], UPSTOX_POSITIONS)
    net = run(fr.read_positions("upstox", TOKENS["upstox"], kind="net"))
    assert "netQty" not in fenix_rows(http, "Upstox", "upstox", "fetch_net_positions")[0]
    unified = fenix_rows(http, "Upstox", "upstox", "fetch_day_positions")
    assert "netQty" in unified[0] and "info" in unified[0]

    expected = [
        # symbol, exchange, qty, avg, ltp, pnl, product, raw, segment, intraday, type
        ("NIFTY26OCT25000CE", "NFO", 75.0, 150.4, 166.0, 1170.0, "carryforward", "D", "fno", False, "CE"),
        ("SBIN", "NSE", 100.0, 801.0, 803.5, 250.0, "intraday", "I", "equity", True, None),
        ("INFY", "NSE", 5.0, 1500.0, 1502.25, 14.25, "delivery", "D", "equity", False, None),
    ]
    for book in (net, [fr._to_position(row, "net") for row in unified]):
        assert [
            (p.symbol, p.exchange, p.quantity, p.avg_price, p.last_price, p.pnl, p.product,
             p.product_raw, p.segment, p.is_intraday, p.instrument_type)
            for p in book
        ] == expected
        assert {p.kind for p in book} == {"net"}
    assert fenix.Upstox.__name__ not in fr._DAY_BOOK_CLASSES


@needs_fenix
@pytest.mark.parametrize("slug", ["upstox", "fyers", "dhan"])
def test_day_read_is_refused_where_fenix_only_has_the_net_book(slug, http):
    """Fenix's day read for these brokers returns the net snapshot. Net rows
    must never come back labelled "day"."""
    with pytest.raises(fr.BrokerNotSupported) as err:
        run(fr.read_positions(slug, TOKENS[slug], kind="day"))
    assert "no separate day book" in str(err.value)
    assert http.calls == [], "the refusal must not cost a request"
    assert fr.supports(slug)["positions"] is True  # the net book is still served


@needs_fenix
def test_fenix_day_read_really_is_the_net_snapshot_for_those_brokers(http):
    """The fact the refusal rests on, checked against the installed Fenix."""
    cases = [
        ("Upstox", "upstox", UPSTOX_POSITIONS, EXPECTED_HEADERS["upstox"]),
        ("Fyers", "fyers", FYERS_POSITIONS, EXPECTED_HEADERS["fyers"]),
        ("Dhan", "dhan", DHAN_POSITIONS, EXPECTED_HEADERS["dhan"]),
        ("AngelOne", "angel", ANGEL_POSITIONS, FakeAngelAdapter.fenix_headers(ANGEL_TOKEN)),
        ("Groww", "groww", GROWW_POSITIONS, FakeGrowwAdapter.fenix_headers(AccessToken(token=GROWW_TOKEN))),
    ]
    for class_name, slug, payload, headers in cases:
        http.reply(URL[(slug, "positions")], payload)
        net = fenix_rows(http, class_name, slug, "fetch_net_positions", headers)
        day = fenix_rows(http, class_name, slug, "fetch_day_positions", headers)
        quantity = lambda row: row.get("netQty", row.get("quantity"))  # noqa: E731
        assert [quantity(r) for r in day] == [quantity(r) for r in net], class_name
        assert class_name not in fr._DAY_BOOK_CLASSES

    # Zerodha is the contrast: Kite sends a day list of its own.
    http.reply(URL[("zerodha", "positions")], KITE_POSITIONS)
    assert len(fenix_rows(http, "Zerodha", "zerodha", "fetch_day_positions")) == 2
    assert len(fenix_rows(http, "Zerodha", "zerodha", "fetch_net_positions")) == 6
    assert fr._DAY_BOOK_CLASSES == {"Zerodha", "AliceBlue"}


@needs_fenix
def test_fyers_positions_exchange_codes_and_symbol_prefix(http):
    http.reply(URL[("fyers", "positions")], FYERS_POSITIONS)
    rows = run(fr.read_positions("fyers", TOKENS["fyers"]))
    assert [
        (p.symbol, p.exchange, p.segment, p.product, p.product_raw, p.is_intraday,
         p.instrument_type, p.quantity, p.last_price, p.pnl)
        for p in rows
    ] == [
        ("SILVERMIC26NOVFUT", "MCX", "commodity", "margin", "MARGIN", False, "FUT", 1.0, 72717.0, 861.0),
        ("USDINR26OCTFUT", "CDS", "currency", "carryforward", "CARRYFORWARD", False, "FUT", -2.0, 88.05, 100.0),
        ("SBIN-EQ", "NSE", "equity", "intraday", "INTRADAY", True, None, 100.0, 803.5, 250.0),
        ("NIFTY26OCT25000PE", "NFO", "fno", "carryforward", "CARRYFORWARD", False, "PE", 75.0, 80.0, -750.0),
    ]


@needs_fenix
def test_aliceblue_positions_legacy_rows_post_the_book_name(http):
    http.reply(URL[("aliceblue", "positions")], ALICE_POSITIONS)
    net = run(fr.read_positions("aliceblue", TOKENS["aliceblue"], kind="net"))
    day = run(fr.read_positions("aliceblue", TOKENS["aliceblue"], kind="day"))

    # AliceBlue's position book is a POST whose body only names the book.
    assert [(c["method"], c["json"]) for c in http.calls] == [("POST", {"ret": "NET"}), ("POST", {"ret": "DAY"})]
    assert net[0] == HubPosition(
        symbol="NIFTY26OCT25000CE", exchange="NFO", quantity=75.0, avg_price=150.4,
        last_price=166.0, pnl=1170.0, product="carryforward", product_raw="NRML",
        segment="fno", is_intraday=False, instrument_type="CE", expiry="2026-10-28",
        strike=25000.0, kind="net", name="NIFTY",
    )
    short = net[1]
    assert (short.symbol, short.quantity, short.avg_price, short.is_intraday) == ("SBIN-EQ", -10.0, 805.0, True)
    assert (short.instrument_type, short.expiry, short.strike) == (None, None, None)
    assert short.name == "STATE BANK OF INDIA"
    assert {p.kind for p in day} == {"day"}


@needs_fenix
def test_dhan_positions_contract_details_and_missing_last_price(http):
    http.reply(URL[("dhan", "positions")], DHAN_POSITIONS)
    cash, option = run(fr.read_positions("dhan", TOKENS["dhan"]))

    assert (cash.symbol, cash.exchange, cash.segment, cash.product) == ("TCS", "NSE", "equity", "delivery")
    assert cash.pnl == 6122.0
    assert cash.last_price is None, "Dhan sends no last price; it must not become 0.0"
    assert (cash.instrument_type, cash.expiry, cash.strike) == (None, None, None)

    assert (option.exchange, option.segment, option.quantity) == ("NFO", "fno", -75.0)
    assert (option.instrument_type, option.expiry, option.strike) == ("PE", "2026-10-27", 25000.0)
    assert (option.product, option.product_raw, option.is_intraday) == ("margin", "MARGIN", False)
    assert option.pnl == 850.0  # realised 100 + unrealised 750


@pytest.mark.parametrize("exchange,product,expected", [
    ("NSE", "MIS", ("equity", "intraday", True)),
    ("BSE", "CNC", ("equity", "delivery", False)),
    ("NFO", "NRML", ("fno", "carryforward", False)),
    ("BFO", "MIS", ("fno", "intraday", True)),
    ("MCX", "NRML", ("commodity", "carryforward", False)),
    ("CDS", "MIS", ("currency", "intraday", True)),
    ("BCD", "NRML", ("currency", "carryforward", False)),
    ("NSE", "MTF", ("equity", "margin", False)),
    ("NSE", "CO", ("equity", "intraday", True)),
    ("NSE", "D", ("equity", "delivery", False)),       # Upstox delivery, cash
    ("NFO", "D", ("fno", "carryforward", False)),      # Upstox delivery, derivative
    ("NSE", "SOMETHING_NEW", ("equity", None, False)),  # unknown code is not guessed
])
def test_segment_and_product_rules(exchange, product, expected):
    record = {"symbol": "ABC", "netQty": 1, "avgPrice": 10.0, "ltp": 11.0, "pnl": 1.0,
              "product": product, "exchange": exchange,
              "info": {"tradingsymbol": "ABC", "product": product, "exchange": exchange}}
    position = fr._to_position(record, "net")
    assert (position.segment, position.product, position.is_intraday) == expected
    assert position.product_raw == product


def test_position_kind_is_validated():
    with pytest.raises(ValueError):
        run(fr.read_positions("zerodha", TOKENS["zerodha"], kind="week"))


# ═════════════════════════════════════════════════════════════════════════
# Failures
# ═════════════════════════════════════════════════════════════════════════
@needs_fenix
@pytest.mark.parametrize("slug,status,payload,code", [
    ("zerodha", 403, {"status": "error", "error_type": "TokenException",
                      "message": "Incorrect `api_key` or `access_token`."}, "TokenException"),
    ("upstox", 401, {"status": "error", "errors": [{
        "errorCode": "UDAPI100050", "message": "Invalid token used to access API",
        "propertyPath": None, "invalidValue": None, "error_code": "UDAPI100050",
        "property_path": None, "invalid_value": None}]}, "UDAPI100050"),
    ("fyers", 200, {"s": "error", "code": -16, "message": "Could not authenticate the user"}, "-16"),
    ("aliceblue", 200, {"stat": "Not_Ok", "emsg": "Session Expired"}, None),
    ("dhan", 401, "", None),
])
def test_rejected_session_maps_to_session_expired(slug, status, payload, code, http, caplog):
    caplog.set_level(logging.DEBUG)
    http.reply(URL[(slug, "holdings")], payload, status=status)
    with pytest.raises(fr.BrokerSessionExpired) as err:
        run(fr.read_holdings(slug, TOKENS[slug]))

    text = str(err.value)
    assert_only_safe_parts(text, slug, "the broker rejected the stored session")
    assert ("AuthenticationError" in text) and (f"HTTP {status}" in text)
    if code:
        assert f"broker code {code}" in text
    assert_no_secret(text)
    assert_no_secret(caplog.text)
    # The Fenix error (which holds the response and request headers) is not chained.
    assert err.value.__cause__ is None and err.value.__context__ is None
    assert http.closed == 1


@needs_fenix
def test_other_failures_map_to_read_error_not_session_expired(http):
    url = URL[("zerodha", "holdings")]
    http.reply(url, {"status": "error", "error_type": "GeneralException", "message": "boom"}, status=500)
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    assert not isinstance(err.value, fr.BrokerSessionExpired)
    assert str(err.value) == "zerodha: fetch_holdings failed (BrokerError, HTTP 500, broker code GeneralException)"

    request = requests.Request("GET", url).prepare()
    http.fail(url, requests.exceptions.ConnectionError("connection reset", request=request))
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    assert type(err.value) is fr.BrokerReadError
    assert str(err.value) == "zerodha: fetch_holdings failed (NetworkError)"

    http.fail(url, requests.exceptions.Timeout("read timed out"))
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    assert type(err.value) is fr.BrokerReadError
    assert str(err.value) == "zerodha: fetch_holdings failed (RequestTimeoutError)"


@needs_fenix
@pytest.mark.parametrize("status,error_class,what", [
    (400, fr.BrokerReadError, "fetch_holdings failed"),
    (401, fr.BrokerSessionExpired, "the broker rejected the stored session"),
])
def test_broker_error_text_that_echoes_secrets_never_reaches_the_message(
    status, error_class, what, http, caplog,
):
    caplog.set_level(logging.DEBUG)
    http.reply(URL[("zerodha", "holdings")], {
        "status": "error",
        "error_type": KITE_APP_KEY,  # a "code" that is really a secret
        "message": f"key {KITE_APP_KEY}:{KITE_TOKEN} for {KITE_USER} is not valid here",
    }, status=status)
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    assert type(err.value) is error_class
    assert_only_safe_parts(str(err.value), "zerodha", what)
    assert "broker code" not in str(err.value), "a code that matches a session value is dropped"
    assert_no_secret(str(err.value))
    assert_no_secret(repr(err.value))
    assert_no_secret(caplog.text)
    assert "not valid here" not in caplog.text and "https://" not in caplog.text


@needs_fenix
def test_nothing_sensitive_is_logged_on_success_even_at_debug(http, caplog):
    caplog.set_level(logging.DEBUG)
    http.reply(URL[("zerodha", "holdings")], KITE_HOLDINGS)
    http.reply(URL[("upstox", "positions")], UPSTOX_POSITIONS)
    run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    run(fr.read_positions("upstox", TOKENS["upstox"], kind="net"))
    assert_no_secret(caplog.text)
    # Fenix's own request/response logging stays off.
    assert [r for r in caplog.records if r.name.startswith(fr._FENIX_LOGGER.name)] == []
    assert "INE009A01021" not in caplog.text


def test_safe_code_drops_anything_that_is_not_plainly_a_code():
    assert fr._safe_code("TokenException", []) == "TokenException"
    assert fr._safe_code(-16, []) == "-16"
    assert fr._safe_code("x" * 25, []) is None
    assert fr._safe_code("has space", []) is None
    assert fr._safe_code(KITE_APP_KEY, [KITE_APP_KEY]) is None
    assert fr._safe_code("ZX99", ["ZX9912"]) is None
    assert fr._safe_code(None, []) is None


# ═════════════════════════════════════════════════════════════════════════
# Unsupported slugs / fenix missing
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("slug", ["fivepaisa", "icicidirect", "no-such-broker", "", None])
def test_unmapped_slug_is_not_supported(slug):
    assert fr.supports(slug) == {"holdings": False, "positions": False}
    with pytest.raises(fr.BrokerNotSupported):
        run(fr.read_holdings(slug, AccessToken(token="t")))
    with pytest.raises(fr.BrokerNotSupported):
        run(fr.read_positions(slug, AccessToken(token="t")))


@pytest.mark.parametrize("slug", sorted(EXPECTED_HEADERS))
def test_without_fenix_nothing_is_supported_and_reads_say_so(slug, monkeypatch, app_keys):
    def missing(module_name, install_hint):
        raise RuntimeError(f"{module_name} not installed. {install_hint}")

    monkeypatch.setattr(fr, "require_sdk", missing)
    assert fr.supports(slug) == {"holdings": False, "positions": False}
    with pytest.raises(fr.BrokerNotSupported) as err:
        run(fr.read_holdings(slug, TOKENS[slug]))
    assert "fenix is not installed" in str(err.value)
    with pytest.raises(fr.BrokerNotSupported):
        run(fr.read_positions(slug, TOKENS[slug], kind="day"))


def test_a_broken_fenix_import_counts_as_not_installed(monkeypatch):
    def broken(module_name, install_hint):
        raise AttributeError("a transitive import blew up")

    monkeypatch.setattr(fr, "require_sdk", broken)
    assert fr.supports("zerodha") == {"holdings": False, "positions": False}


@pytest.mark.skipif(HAVE_FENIX, reason="only meaningful where fenix is really absent")
def test_module_works_where_fenix_is_really_absent(app_keys):
    assert fr.supports("zerodha") == {"holdings": False, "positions": False}
    with pytest.raises(fr.BrokerNotSupported):
        run(fr.read_holdings("zerodha", TOKENS["zerodha"]))


@needs_fenix
@pytest.mark.parametrize("slug", sorted(EXPECTED_HEADERS))
def test_builtin_slugs_are_supported_when_fenix_is_installed(slug):
    assert fr.supports(slug) == {"holdings": True, "positions": True}
    assert fr.supports(f"  {slug.upper()} ") == {"holdings": True, "positions": True}


# ═════════════════════════════════════════════════════════════════════════
# Adapter hook
# ═════════════════════════════════════════════════════════════════════════
@needs_fenix
def test_hook_adapter_gets_a_reader(monkeypatch, http):
    register(monkeypatch, FakeAngelAdapter())
    assert fr.supports("fakeangel") == {"holdings": True, "positions": True}

    http.reply(URL[("angel", "holdings")], ANGEL_HOLDINGS)
    http.reply(URL[("angel", "positions")], ANGEL_POSITIONS)
    holdings = run(fr.read_holdings("fakeangel", ANGEL_TOKEN))
    positions = run(fr.read_positions("fakeangel", ANGEL_TOKEN, kind="net"))

    assert http.calls[0]["headers"] == FakeAngelAdapter.fenix_headers(ANGEL_TOKEN)
    assert holdings == [
        Holding(isin="INE081A01020", symbol="TATASTEEL", asset_type="equity", quantity=2.0,
                avg_price=111.87, current_price=130.15, name="TATASTEEL", sector=None,
                exchange="NSE", source_id="NSE:TATASTEEL-EQ"),
    ]
    assert positions == [
        HubPosition(symbol="NIFTY27OCT2625000CE", exchange="NFO", quantity=75.0, avg_price=150.4,
                    last_price=166.0, pnl=1170.0, product="carryforward",
                    product_raw="CARRYFORWARD", segment="fno", is_intraday=False,
                    instrument_type="CE", expiry="2026-10-27", strike=25000.0, kind="net",
                    name="NIFTY"),
    ]


@needs_fenix
def test_hook_groww_reads(monkeypatch, http):
    register(monkeypatch, FakeGrowwAdapter())
    token = AccessToken(token=GROWW_TOKEN)
    http.reply(URL[("groww", "holdings")], GROWW_HOLDINGS)
    http.reply(URL[("groww", "positions")], GROWW_POSITIONS)

    assert run(fr.read_holdings("fakegroww", token)) == [
        # Groww's holdings carry no exchange and no last price.
        Holding(isin="INE545U01014", symbol="BANDHANBNK", asset_type="equity", quantity=20.0,
                avg_price=262.5, current_price=0.0, name="BANDHANBNK", sector=None,
                exchange=None, source_id="BANDHANBNK"),
    ]
    cash, option = run(fr.read_positions("fakegroww", token, kind="net"))
    assert (cash.symbol, cash.exchange, cash.quantity, cash.avg_price) == ("RELIANCE", "NSE", 15.0, 1240.0)
    assert (cash.product, cash.last_price, cash.pnl, cash.kind) == ("delivery", None, 500.0, "net")
    assert (option.exchange, option.segment, option.instrument_type) == ("NFO", "fno", "CE")

    # Groww (like AngelOne) has no separate day book in Fenix.
    before = len(http.calls)
    with pytest.raises(fr.BrokerNotSupported):
        run(fr.read_positions("fakegroww", token, kind="day"))
    assert len(http.calls) == before


@needs_fenix
def test_hook_auth_params_reach_use_headers(monkeypatch, http):
    register(monkeypatch, FakeDhanViaHook())
    http.reply(URL[("dhan", "positions")], DHAN_POSITIONS)
    rows = run(fr.read_positions("fakedhan", TOKENS["dhan"]))
    assert [p.symbol for p in rows] == ["TCS", "NIFTY-OCT2026-25000-PE"]
    assert http.calls[0]["headers"] == {"access-token": DHAN_TOKEN, "Accept": "application/json"}

    class NoContext(FakeDhanViaHook):
        SLUG = "fakedhan2"
        fenix_auth_params = None

    register(monkeypatch, NoContext())
    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_positions("fakedhan2", TOKENS["dhan"]))
    assert "missing: user_id" in str(err.value)
    assert len(http.calls) == 1, "nothing may be sent when the session is incomplete"


@needs_fenix
def test_hook_supports_reflects_the_fenix_class(monkeypatch):
    class Hook:
        AUTH_STYLE = "oauth"
        DISPLAY = "x"
        fenix_headers = staticmethod(lambda token: {})

    def with_class(name):
        adapter = Hook()
        adapter.SLUG = "probe"
        adapter.FENIX_CLASS = name
        register(monkeypatch, adapter)
        return fr.supports("probe")

    assert with_class("AngelOne") == {"holdings": True, "positions": True}
    assert with_class("Groww") == {"holdings": True, "positions": True}
    # Fenix's FivePaisa has no net/day position methods.
    assert with_class("FivePaisa") == {"holdings": True, "positions": False}
    for not_a_broker in ("NoSuchBroker", "Broker", "errors", "AuthenticationError", ""):
        assert with_class(not_a_broker) == {"holdings": False, "positions": False}

    with_class("NoSuchBroker")
    with pytest.raises(fr.BrokerNotSupported):
        run(fr.read_holdings("probe", AccessToken(token="t")))


@needs_fenix
def test_adapter_without_the_hook_has_no_reader(monkeypatch):
    class Plain:
        SLUG = "plain"
        DISPLAY = "Plain"
        AUTH_STYLE = "oauth"

    class HalfHook(Plain):
        SLUG = "halfhook"
        FENIX_CLASS = "Zerodha"  # no fenix_headers

    register(monkeypatch, Plain())
    register(monkeypatch, HalfHook())
    assert fr.supports("plain") == {"holdings": False, "positions": False}
    assert fr.supports("halfhook") == {"holdings": False, "positions": False}


@needs_fenix
def test_builtin_builder_wins_over_an_adapter_hook(monkeypatch, http):
    class Hijack:
        SLUG = "zerodha"
        DISPLAY = "Zerodha"
        AUTH_STYLE = "oauth"
        FENIX_CLASS = "Upstox"

        @staticmethod
        def fenix_headers(token):
            raise AssertionError("the hook must not be used for a built-in slug")

    register(monkeypatch, Hijack())
    http.reply(URL[("zerodha", "holdings")], KITE_HOLDINGS)
    rows = run(fr.read_holdings("zerodha", TOKENS["zerodha"]))
    assert [h.symbol for h in rows] == ["INFY", "NIFTYBEES"]
    assert http.calls[0]["url"] == URL[("zerodha", "holdings")]
    assert http.calls[0]["headers"] == EXPECTED_HEADERS["zerodha"]


@needs_fenix
def test_hook_errors_are_reported_without_their_text(monkeypatch, http):
    class Leaky(FakeAngelAdapter):
        SLUG = "leaky"

        @staticmethod
        def fenix_headers(token):
            raise KeyError(f"no feed token next to {ANGEL_JWT}")

    class Explains(FakeAngelAdapter):
        SLUG = "explains"

        @staticmethod
        def fenix_headers(token):
            raise fr.BrokerReadError("explains: BROKER_ANGEL_API_KEY is not configured")

    class WrongTypes(FakeAngelAdapter):
        SLUG = "wrongtypes"

        @staticmethod
        def fenix_headers(token):
            headers = FakeAngelAdapter.fenix_headers(token)
            headers["x-feed-token"] = None
            return headers

    class Incomplete(FakeAngelAdapter):
        SLUG = "incomplete"

        @staticmethod
        def fenix_headers(token):
            headers = FakeAngelAdapter.fenix_headers(token)
            del headers["x-client-code"], headers["X-PrivateKey"]
            return headers

    for adapter in (Leaky(), Explains(), WrongTypes(), Incomplete()):
        register(monkeypatch, adapter)

    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("leaky", ANGEL_TOKEN))
    assert "KeyError" in str(err.value)
    assert_no_secret(str(err.value))
    assert err.value.__cause__ is None and err.value.__context__ is None

    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("explains", ANGEL_TOKEN))
    assert str(err.value) == "explains: BROKER_ANGEL_API_KEY is not configured"

    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("wrongtypes", ANGEL_TOKEN))
    assert "must be strings" in str(err.value) and "x-feed-token" in str(err.value)

    with pytest.raises(fr.BrokerReadError) as err:
        run(fr.read_holdings("incomplete", ANGEL_TOKEN))
    assert "missing: X-PrivateKey, x-client-code" in str(err.value)
    assert_no_secret(str(err.value))
    assert http.calls == [], "no request may be made with an invalid session"


# ═════════════════════════════════════════════════════════════════════════
# Isolation, network footprint, read-only
# ═════════════════════════════════════════════════════════════════════════
@needs_fenix
def test_every_call_gets_its_own_fenix_object_and_session(http):
    http.reply(URL[("zerodha", "holdings")], KITE_HOLDINGS)
    http.reply(URL[("zerodha", "positions")], KITE_POSITIONS)

    async def three_reads():
        other_user = AccessToken(token="KITE-OTHER-USER-TOKEN", extras={"user_id": "QQ0001"})
        return await asyncio.gather(
            fr.read_holdings("zerodha", TOKENS["zerodha"]),
            fr.read_holdings("zerodha", other_user),
            fr.read_positions("zerodha", TOKENS["zerodha"]),
        )

    run(three_reads())
    assert http.sessions == 3 and http.closed == 3 and len(http.calls) == 3
    sent = sorted(c["headers"]["access_token"] for c in http.calls)
    assert sent == sorted([KITE_TOKEN, "KITE-OTHER-USER-TOKEN", KITE_TOKEN])
    for call in http.calls:  # each request carries one user's session only
        assert call["headers"]["Authorization"].endswith(call["headers"]["access_token"])


@needs_fenix
def test_reads_touch_only_the_portfolio_endpoints(http):
    """No instrument master, no token load, no sign-in: one request per read,
    always to the broker's holdings or positions endpoint."""
    plan = [
        ("zerodha", KITE_HOLDINGS, KITE_POSITIONS), ("upstox", UPSTOX_HOLDINGS, UPSTOX_POSITIONS),
        ("fyers", FYERS_HOLDINGS, FYERS_POSITIONS), ("aliceblue", ALICE_HOLDINGS, ALICE_POSITIONS),
        ("dhan", DHAN_HOLDINGS, DHAN_POSITIONS),
    ]
    day_books = {"zerodha", "aliceblue"}
    for slug, holdings, positions in plan:
        http.reply(URL[(slug, "holdings")], holdings)
        http.reply(URL[(slug, "positions")], positions)
        run(fr.read_holdings(slug, TOKENS[slug]))
        run(fr.read_positions(slug, TOKENS[slug], kind="net"))
        if slug in day_books:
            run(fr.read_positions(slug, TOKENS[slug], kind="day"))

    assert len(http.calls) == 2 * len(plan) + len(day_books)
    assert {c["url"] for c in http.calls} == {URL[(slug, what)] for slug, _, _ in plan
                                              for what in ("holdings", "positions")}
    assert all(c["data"] is None and c["params"] is None for c in http.calls)
    bodies = [c["json"] for c in http.calls if c["json"] is not None]
    assert bodies == [{"ret": "NET"}, {"ret": "DAY"}]  # AliceBlue's book selector, nothing else


def test_module_is_read_only():
    """The reader may call exactly three Fenix read methods and `use_headers`."""
    assert fr._HOLDINGS_METHOD == "fetch_holdings"
    assert fr._POSITION_METHODS == {"net": "fetch_net_positions", "day": "fetch_day_positions"}

    tree = ast.parse(Path(fr.__file__).read_text(encoding="utf-8"))
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    forbidden_exact = {"authenticate", "create_headers", "kill_switch", "margin_calculator"}
    forbidden_parts = ("order", "square_off", "exit_", "convert_position", "gtt")
    assert not (used & forbidden_exact)
    assert not [name for name in used if any(part in name.lower() for part in forbidden_parts)]
    assert "use_headers" in used

    public = {name for name in dir(fr) if not name.startswith("_")}
    assert not [name for name in public if any(part in name.lower() for part in forbidden_parts)]
    assert set(fr.__all__) == {
        "BrokerNotSupported", "BrokerReadError", "BrokerSessionExpired",
        "read_holdings", "read_positions", "supports",
    }
