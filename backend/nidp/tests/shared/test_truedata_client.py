"""TrueData REST client, symbol mapping and the shadow cross-check (test_reports/truedata_client_TESTCASES.md).

No network: a fake transport answers. Every row below is SYNTHETIC, written in TrueData's documented formats (headers as
seen on the trial, 29 Oct 2026); none of it is vendor data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from datetime import date, datetime
from decimal import Decimal

import pytest

from nidp.services.truedata_crosscheck import service as xc
from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td

PASSWORD = "pw-S3CRET-xyz"
CREDS = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}
ON = mds.resolve({"source": "shadow"}, CREDS, integrated=True)
OFF = mds.resolve({"source": "current"}, CREDS, integrated=True)
USER = "trial-user"


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


class FakeTD:
    """Answers TrueData URLs. routes: endpoint name → (status, body) or a list of them (served in order, last repeats)."""

    def __init__(self, routes=None, expires_in=3600):
        self.routes = routes or {}
        self.expires_in = expires_in
        self.calls = []
        self.tokens = 0

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append({"method": method, "url": url, "data": data, "headers": dict(headers)})
        if url == td.AUTH_URL:
            self.tokens += 1
            return 200, json.dumps({"access_token": f"TOK-SECRET-{self.tokens}", "token_type": "bearer",
                                    "expires_in": self.expires_in}).encode()
        name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        r = self.routes[name]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        status, body = r
        return status, body.encode() if isinstance(body, str) else body

    def data_calls(self):
        return [c for c in self.calls if c["url"] != td.AUTH_URL]

    def query(self, i=-1):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.data_calls()[i]["url"]).query))


def client(fake, clock=None, min_interval=0.0):
    clock = clock or Clock()
    return td.TrueDataClient(td.Credentials(USER, PASSWORD), transport=fake, min_interval=min_interval,
                             clock=clock.now, sleep=clock.sleep)


EOD_CSV = ("timestamp,open,high,low,close,volume,oi,delvolume,delpercent\n"
           "2026-10-27,100.5,102,99.75,101.25,120000,0,54000,45\n"
           "2026-10-28,101.25,103.4,100,103,98000,0,40180,41\n")
MIN_CSV = ("timestamp,open,high,low,close,volume,oi\n"
           "2026-10-28T09:15:00,100,100.5,99.8,100.2,1500,0\n"
           "2026-10-28T09:16:00,100.2,100.4,100.1,100.3,900,0\n")
TICK_CSV = ("timestamp,ltp,volume,oi,bid,bidqty,ask,askqty\n"
            "2026-10-28T09:15:00,100.2,50,0,100.15,30,100.2,12\n")
BHAV_EQ = ("symbolid,symbol,timestamp,open,high,low,close,volume,oi\n"
           "100000001,AAAA,2026-10-28,10,11,9.5,10.5,1000,0\n"
           "100000002,NAN,2026-10-28,20,21,19,20.5,500,0\n"
           "200000001,INDEX ONE,2026-10-28,500,510,495,505,0,0\n")
BHAV_FO = ("symbolid,symbol,timestamp,open,high,low,close,volume,oi\n"
           "300000001,IDXA26110310000CE,2026-10-28,5,6,4.5,5.5,750,15000\n")
MASTER_FO = ("symbolid,symbol,series,isin,exchange,lotsize,strike,expiry,metastocksymbol,symbolalias,underlying,"
             "company,ticksize,circuit\n"
             "900000001,AAAA-I,XX,,NSE,500,0,24-11-2026,AAAA_I,AAAA_I,AAAA,5,110.5-90.5\n"
             "900000002,AAAA26112410000CE,XX,,NSE,500,100,24-11-2026,AAAA_CE,AAAA_CE,AAAA,5,30-0.05\n")
MASTER_EQ = ("symbolid,symbol,series,isin,exchange,lotsize,strike,expiry,metastocksymbol,symbolalias,symbolalias,"
             "company,ticksize,circuit\n"
             "100000001,AAAA,EQ,INE000X01011,NSE,1,,,AAAA,AAAA,Aaaa Synthetic Ltd,10,90-110\n")
CORP_CSV = ("symbol,company,series,purpose,face_value,ex_date,record_date,bc_start,bc_end,ratio\n"
            "DDDD_BSE,Dddd Synthetic Ltd,,Buy Back of Shares,1,2026-10-22,2026-10-22,0001-01-01,0001-01-01,1\n"
            "DDDD_BSE,Dddd Synthetic Ltd,,Buy Back of Shares,1,2026-10-22,2026-10-22,0001-01-01,0001-01-01,1\n"
            "EEEE_BSE,Eeee Synthetic Ltd,,Stock  Split From Rs.10/- to Rs.2/-,2,2026-10-23,2026-10-23,"
            "0001-01-01,0001-01-01,1\n"
            "AAAA,Aaaa Synthetic Ltd,EQ,Bonus 1:1,10,2026-10-20,2026-10-20,1970-01-01,1970-01-01,2\n"
            "BBBB_BSE,Bbbb Synthetic Ltd,,Stock Split From Rs.10/- to Rs.2/-,2,2026-10-21,2026-10-21,"
            "0001-01-01,0001-01-01,5\n"
            "CCCC,Cccc Synthetic Ltd,EQ,Interim Dividend - Rs 3 Per Share,1,2026-10-22,2026-10-22,1970-01-01,"
            "1970-01-01,1\n")


def _all_secrets_absent(*texts):
    for t in texts:
        assert PASSWORD not in t and "TOK-SECRET" not in t


# ── TC-1 credentials ────────────────────────────────────────────────────────────────────────────────────────────

def test_tc1_no_credentials_is_not_configured_without_network(monkeypatch):
    for k in ("TRUEDATA_USERNAME", "TRUEDATA_PASSWORD", "TRUEDATA_CRED_FILE"):
        monkeypatch.delenv(k, raising=False)
    fake = FakeTD()
    c = td.TrueDataClient(transport=fake, min_interval=0)
    assert c.configured is False
    with pytest.raises(td.TrueDataError) as e:
        c.bars("AAAA", datetime(2026, 10, 1), datetime(2026, 10, 28), "eod")
    assert e.value.code == td.NOT_CONFIGURED and e.value.retryable is False
    assert fake.calls == []


def test_tc1_credentials_from_env_and_file(tmp_path):
    assert td.credentials_from_env({}) is None
    assert td.credentials_from_env({"TRUEDATA_USERNAME": "u"}) is None
    c = td.credentials_from_env({"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": PASSWORD})
    assert (c.username, c.password) == ("u", PASSWORD)
    f = tmp_path / "td.env"
    f.write_text(f"TRUEDATA_USERNAME=fileuser\nTRUEDATA_PASSWORD={PASSWORD}\n")
    c = td.credentials_from_env({"TRUEDATA_CRED_FILE": str(f)})
    assert (c.username, c.password) == ("fileuser", PASSWORD)
    assert td.credentials_from_env({"TRUEDATA_CRED_FILE": str(tmp_path / "missing")}) is None


# ── TC-2 / TC-3 token ───────────────────────────────────────────────────────────────────────────────────────────

def test_tc2_token_posted_as_form_cached_and_refreshed_after_expiry():
    clock = Clock()
    fake = FakeTD({"getbars": (200, EOD_CSV)}, expires_in=3600)
    c = client(fake, clock)
    for _ in range(3):
        c.bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    auth = [x for x in fake.calls if x["url"] == td.AUTH_URL]
    assert len(auth) == 1 and auth[0]["method"] == "POST"
    form = dict(urllib.parse.parse_qsl(auth[0]["data"].decode()))
    assert form == {"username": USER, "password": PASSWORD, "grant_type": "password"}
    assert auth[0]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert fake.data_calls()[0]["headers"]["Authorization"] == "Bearer TOK-SECRET-1"
    clock.t += 3600 - 300 + 1                          # past expires_in minus the safety margin
    c.bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert fake.tokens == 2 and fake.data_calls()[-1]["headers"]["Authorization"] == "Bearer TOK-SECRET-2"


def test_tc3_401_refreshes_token_once_then_auth_expired():
    fake = FakeTD({"getbars": [(401, '{"Message":"Authorization has been denied for this request."}'),
                               (200, EOD_CSV)]})
    rows = client(fake).bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert len(rows) == 2 and fake.tokens == 2 and len(fake.data_calls()) == 2

    fake = FakeTD({"getbars": (401, '{"Message":"Authorization has been denied for this request."}')})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert e.value.code == td.AUTH_EXPIRED and fake.tokens == 2 and len(fake.data_calls()) == 2


def test_tc3_login_refused_is_auth_expired():
    def refuse(method, url, data, headers, timeout):
        return 400, b'{"error":"invalid_grant","error_description":"The user name or password is incorrect."}'
    with pytest.raises(td.TrueDataError) as e:
        client(refuse).bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert e.value.code == td.AUTH_EXPIRED and "incorrect" in e.value.message
    _all_secrets_absent(str(e.value), repr(e.value))


# ── TC-4 … TC-8 failure classification ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,body,code,retryable", [
    (200, '"No data exists for AAAA"', td.EMPTY_RESPONSE, False),                                     # TC-4
    (200, '"Symbol does not exist"', td.IDENTIFIER_NOT_RESOLVED, False),                              # TC-5
    (200, '"API calls quota exceeded! maximum admitted 10 per Second."', td.RATE_LIMITED, True),       # TC-6
    (429, "Too Many Requests", td.RATE_LIMITED, True),                                                 # TC-6
    (200, '"Segment not subscribed"', td.NOT_CONFIGURED, False),                                       # TC-7
    (200, '{"Message":"Authorization has been denied for this request."}', td.NOT_CONFIGURED, False), # TC-7
    (404, "<!DOCTYPE html><html><body>404 Not Found</body></html>", td.PROVIDER_ERROR, False),         # TC-8
    (503, "Service Unavailable", td.PROVIDER_UNAVAILABLE, True),
])
def test_tc4_to_tc8_failures_are_classified(status, body, code, retryable):
    fake = FakeTD({"getbars": (status, body)})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert e.value.code == code and e.value.retryable is retryable
    assert "getbars" in e.value.message                    # names the path, never the URL
    _all_secrets_absent(str(e.value), repr(e.value))


def test_tc8_network_failure_is_unavailable_and_hides_the_url():
    fake = FakeTD({"getbars": OSError("connect to https://history.truedata.in/getbars?symbol=AAAA failed")})
    with pytest.raises(td.TrueDataError) as e:
        client(fake).bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")
    assert e.value.code == td.PROVIDER_UNAVAILABLE and "https://" not in e.value.message


def test_csv_body_mentioning_a_failure_phrase_is_data_not_an_error():
    body = "symbol,company\nAAAA,Symbol does not exist Holdings Ltd\n"
    assert td.classify_message(body) is None


# ── TC-9 rate gate ──────────────────────────────────────────────────────────────────────────────────────────────

def test_tc9_rate_gate_spaces_calls_to_the_same_host():
    clock = Clock()
    fake = FakeTD({"getbars": (200, EOD_CSV), "getbhavcopy": (200, BHAV_EQ)})
    c = client(fake, clock, min_interval=1.1)
    c.bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod")    # auth host + history host: no wait
    assert clock.sleeps == []
    c.bhavcopy("EQ", date(2026, 10, 28))                                       # same host, no time passed
    assert clock.sleeps == [1.1]
    clock.t += 5
    c.bhavcopy("EQ", date(2026, 10, 28))                                       # enough time passed
    assert clock.sleeps == [1.1]


# ── TC-10 … TC-12 history endpoints ─────────────────────────────────────────────────────────────────────────────

def test_tc10_bars_parse_and_request_format():
    fake = FakeTD({"getbars": [(200, EOD_CSV), (200, MIN_CSV)]})
    c = client(fake)
    eod = c.bars("AAAA", datetime(2026, 10, 27, 9, 0), datetime(2026, 10, 28, 15, 30), "eod", delivery=True)
    q = fake.query()
    assert q["from"] == "261027T09:00:00" and q["to"] == "261028T15:30:00"
    assert q["interval"] == "eod" and q["delivery"] == "true" and q["response"] == "csv"
    assert eod[1] == {"timestamp": "2026-10-28", "open": 101.25, "high": 103.4, "low": 100, "close": 103,
                      "volume": 98000, "oi": 0, "delvolume": 40180, "delpercent": 41}
    m = c.bars("AAAA", datetime(2026, 10, 28, 9, 15), datetime(2026, 10, 28, 15, 30), "1min")
    assert "delivery" not in fake.query() and m[0]["timestamp"] == "2026-10-28T09:15:00"
    with pytest.raises(td.TrueDataError) as e:
        c.bars("AAAA", datetime(2026, 10, 28), datetime(2026, 10, 28), "7min")
    assert e.value.code == td.INVALID_REQUEST and len(fake.data_calls()) == 2


def test_tc11_ticks_with_bid_ask():
    fake = FakeTD({"getticks": (200, TICK_CSV)})
    rows = client(fake).ticks("AAAA", datetime(2026, 10, 28, 9, 15), datetime(2026, 10, 28, 9, 16))
    assert fake.query()["bidask"] == "1"
    assert rows == [{"timestamp": "2026-10-28T09:15:00", "ltp": 100.2, "volume": 50, "oi": 0, "bid": 100.15,
                     "bidqty": 30, "ask": 100.2, "askqty": 12}]


def test_tc12_bhavcopy_eq_and_fo():
    fake = FakeTD({"getbhavcopy": [(200, BHAV_EQ), (200, BHAV_FO)]})
    c = client(fake)
    eq = c.bhavcopy("eq", date(2026, 10, 28))
    assert fake.query()["segment"] == "EQ" and fake.query()["date"] == "2026-10-28"
    assert eq[0] == {"symbolid": 100000001, "symbol": "AAAA", "timestamp": "2026-10-28", "open": 10, "high": 11,
                     "low": 9.5, "close": 10.5, "volume": 1000, "oi": 0}
    assert eq[1]["symbol"] == "NAN"                    # a symbol never becomes a number
    fo = c.bhavcopy("FO", date(2026, 10, 28))
    assert fo[0]["symbol"] == "IDXA26110310000CE" and fo[0]["oi"] == 15000
    with pytest.raises(td.TrueDataError) as e:
        c.bhavcopy("CDS", date(2026, 10, 28))
    assert e.value.code == td.INVALID_REQUEST


def test_expiries_drop_the_continuous_marker():
    fake = FakeTD({"getSymbolExpiryList": (200, "expiry\n2026-11-03\n2026-11-24\n2099-12-31\n")})
    assert client(fake).expiries("IDXA") == [date(2026, 11, 3), date(2026, 11, 24)]


def test_symbol_changes_parse_the_effective_date():
    fake = FakeTD({"getsymbolchangehistory": (200, "company,oldsymbol,new_symbol,applicationdate\n"
                                                   "Aaaa Synthetic Ltd,OLDA,AAAA,2/27/2026 12:00:00 AM\n")})
    rows = client(fake).symbol_changes("OLDA")
    assert fake.query()["SYMBOL"] == "OLDA"
    assert rows[0]["oldsymbol"] == "OLDA" and rows[0]["effective_date"] == date(2026, 2, 27)


# ── TC-13 symbol master ─────────────────────────────────────────────────────────────────────────────────────────

def test_tc13_symbol_master_credentials_in_query_and_header_alignment(caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeTD({"getAllSymbols": [(200, MASTER_FO), (200, MASTER_EQ)]})
    c = client(fake)
    fo = c.symbol_master("fo", search="AAAA")
    call = fake.data_calls()[-1]
    assert call["url"].startswith(td.API + "/getAllSymbols?") and "Authorization" not in call["headers"]
    q = fake.query()
    assert q["user"] == USER and q["password"] == PASSWORD and q["search"] == "AAAA"
    assert fake.tokens == 0                                 # this endpoint does not use the bearer token
    assert "company" not in fo[0] and fo[0]["underlying"] == "AAAA" and fo[0]["lotsize"] == 500
    assert fo[0]["tick_size"] == 0.05 and (fo[0]["circuit_low"], fo[0]["circuit_high"]) == (90.5, 110.5)
    assert fo[0]["expiry_date"] == date(2026, 11, 24)
    eq = c.symbol_master("eq")
    assert eq[0]["company"] == "Aaaa Synthetic Ltd" and eq[0]["isin"] == "INE000X01011" and eq[0]["tick_size"] == 0.1
    assert PASSWORD not in caplog.text


def test_tc13_symbol_master_errors_never_carry_the_url():
    for answer in ((200, "symbolid,symbol,series\n1,AAAA,EQ,EXTRA,MORE\n"),
                   (500, "error"), OSError(f"https://api.truedata.in/getAllSymbols?password={PASSWORD}")):
        fake = FakeTD({"getAllSymbols": answer})
        with pytest.raises(td.TrueDataError) as e:
            client(fake).symbol_master("eq")
        assert e.value.code in (td.TOOL_SCHEMA_CHANGED, td.PROVIDER_UNAVAILABLE)
        _all_secrets_absent(str(e.value), repr(e.value), e.value.message)
        assert "https://" not in e.value.message


# ── TC-14 corporate actions ─────────────────────────────────────────────────────────────────────────────────────

def test_tc14_corporate_actions():
    fake = FakeTD({"getcorpactionrange": (200, CORP_CSV)})
    rows = client(fake).corporate_actions(date(2026, 10, 20), date(2026, 10, 22))
    q = fake.query()
    assert (q["exdatefrom"], q["exdateto"]) == ("2026-10-20", "2026-10-22")
    assert len(rows) == 5                                    # TC-14b: the repeated buy-back row counted once
    d, e, a, b, c = rows
    assert d["kind"] == "other" and d["ratio_suspect"] is False
    assert (e["kind"], e["ratio"], e["ratio_suspect"]) == ("split", 1.0, True)        # TC-14c: BSE split, ratio 1
    assert a["ratio_suspect"] is False and b["ratio_suspect"] is False
    assert (a["kind"], a["ratio"], a["exchange"], a["ex_date"], a["bc_start"]) == \
        ("bonus", 2.0, "NSE", date(2026, 10, 20), None)
    assert (b["kind"], b["ratio"], b["exchange"], b["base_symbol"], b["series"], b["bc_end"]) == \
        ("split", 5.0, "BSE", "BBBB", None, None)
    assert isinstance(a["ratio"], float) and c["kind"] == "dividend" and c["ratio"] == 1.0


# ── TC-15 secrets ───────────────────────────────────────────────────────────────────────────────────────────────

def test_tc15_no_secret_in_any_repr_error_or_log(caplog):
    caplog.set_level(logging.DEBUG)
    creds = td.Credentials(USER, PASSWORD)
    assert PASSWORD not in repr(creds) and PASSWORD not in str(creds)
    fake = FakeTD({"getbars": (401, "denied"), "getAllSymbols": (503, "down")})
    c = client(fake)
    texts = [repr(c)]
    for call in (lambda: c.bars("AAAA", datetime(2026, 10, 27), datetime(2026, 10, 28), "eod"),
                 lambda: c.symbol_master("eq")):
        with pytest.raises(td.TrueDataError) as e:
            call()
        texts += [str(e.value), repr(e.value), e.value.message]
    _all_secrets_absent(*texts, caplog.text)


# ── SM-1 … SM-5 symbol mapping ──────────────────────────────────────────────────────────────────────────────────

def test_sm_symbol_mapping():
    assert td.option_symbol("NIFTY", date(2026, 11, 3), 23000, "CE") == "NIFTY26110323000CE"           # SM-1
    assert td.option_symbol("reliance", date(2026, 11, 23), 1080.5, "pe") == "RELIANCE2611231080.5PE"  # SM-2
    assert td.option_symbol("X", date(2026, 11, 23), Decimal("1080.50"), "CE") == "X2611231080.5CE"
    assert td.future_symbol("RELIANCE", date(2026, 11, 23)) == "RELIANCE26NOVFUT"                      # SM-3
    assert td.continuous_future_symbol("NIFTY", 1) == "NIFTY-I"                                         # SM-4
    assert td.continuous_future_symbol("NIFTY", 2) == "NIFTY-II"
    assert td.index_symbol("Nifty 50") == "NIFTY 50" and td.index_symbol(" Nifty  Bank ") == "NIFTY BANK"  # SM-5
    with pytest.raises(ValueError):
        td.option_symbol("NIFTY", date(2026, 11, 3), 23000, "XX")
    with pytest.raises(ValueError):
        td.continuous_future_symbol("NIFTY", 4)


# ── XC-1 / XC-2 cross-check ─────────────────────────────────────────────────────────────────────────────────────

def _eq(symbol, series, o, h, l, c, v):
    return {"symbol": symbol, "series": series, "open_price": Decimal(str(o)), "high_price": Decimal(str(h)),
            "low_price": Decimal(str(l)), "close_price": Decimal(str(c)), "volume": v}


def test_xc1_compare_equity():
    nse = [_eq("AAAA", "EQ", 10, 11, 9.5, 10.5, 1000),
           _eq("NAN", "BE", 20, 21, 19, 20.5, 500),           # close differs in TrueData below
           _eq("GONE", "SM", 5, 5, 5, 5, 10),                  # absent from TrueData
           _eq("BOND1", "N1", 100, 100, 100, 100, 1)]          # not a compared series
    td_rows = td.parse_csv(BHAV_EQ.replace("20.5,500", "20.75,500") + "100000009,EXTRA,2026-10-28,1,1,1,1,1,0\n")
    r = xc.compare_equity(nse, td_rows)
    assert r["nse_rows"] == 3 and r["found"] == 2 and r["all_equal"] == 1
    assert r["missing_count"] == 1 and r["missing_sample"] == ["GONE (SM)"]
    assert r["mismatch_count"] == 1 and r["mismatch_sample"][0]["fields"] == ["close"]
    assert r["by_series"]["EQ"] == {"nse": 1, "found": 1, "close_equal": 1, "all_equal": 1}
    assert r["td_index_rows"] == 1 and r["td_extra_securities"] == 1 and r["verdict"] == "DIFFERENT"
    clean = xc.compare_equity(nse[:1], td.parse_csv(BHAV_EQ))
    assert clean["verdict"] == "EQUAL" and xc.compare_equity([], [])["verdict"] == "NO_NSE_DATA"


def _fo(kind, ticker, expiry, strike, opt, close, oi, vol):
    return {"instrument_type": kind, "ticker_symbol": ticker, "expiry_date": expiry,
            "strike_price": Decimal(str(strike)) if strike is not None else None, "option_type": opt,
            "close_price": Decimal(str(close)), "settle_price": Decimal(str(close)), "open_interest": oi,
            "traded_volume": vol}


def test_xc2_compare_fno_traded_only_and_names_built_from_nse():
    nov3, nov24 = date(2026, 11, 3), date(2026, 11, 24)
    nse = [_fo("IDO", "IDXA", nov3, 10000, "CE", 5.5, 15000, 10),          # traded, equal
           _fo("IDO", "IDXA", nov3, 10100, "CE", 0.05, 0, 0),              # untraded: not expected
           _fo("STO", "AAAA", nov24, 1080.5, "PE", 7.25, 600, 3),          # traded, decimal strike, OI differs
           _fo("STF", "AAAA", nov24, None, None, 101.5, 90000, 40),        # traded future, by name
           _fo("IDF", "IDXA", date(2027, 1, 26), None, None, 10100, 500, 2)]  # traded, absent in TrueData
    td_csv = (BHAV_FO + "300000002,AAAA2611241080.5PE,2026-10-28,7,7.5,7,7.25,1500,650\n"
              "300000003,AAAA26NOVFUT,2026-10-28,100,102,99,101.5,20000,90000\n"
              "300000004,AAAA-I,2026-10-28,100,102,99,101.5,20000,90000\n"
              "300000005,ZZZZ26NOVFUT,2026-10-28,1,1,1,1,1,1\n")
    r = xc.compare_fno(nse, td.parse_csv(td_csv))
    assert r["options"] == {"traded": 2, "found": 2, "close_equal": 2, "oi_equal": 1, "both_equal": 1}
    assert r["futures"] == {"traded": 2, "found": 1, "close_equal": 1, "oi_equal": 1, "both_equal": 1}
    assert r["untraded_not_expected"] == 1 and r["untraded_present_in_td"] == 0
    assert r["missing_count"] == 1 and r["missing_sample"] == ["IDXA27JANFUT"]
    assert r["mismatch_sample"][0]["contract"] == "AAAA2611241080.5PE"
    assert r["td_extra"] == 1 and r["td_continuous_rows"] == 1 and r["verdict"] == "DIFFERENT"
    assert xc.compare_fno(nse[:2], td.parse_csv(BHAV_FO))["verdict"] == "EQUAL"


class _FakeClient:
    def __init__(self, eq, fo):
        self.answers = {"EQ": eq, "FO": fo}

    def bhavcopy(self, segment, day):
        a = self.answers[segment]
        if isinstance(a, Exception):
            raise a
        return a


def test_xc_run_combines_verdicts_and_reports_truedata_errors():
    nse = {"eq": [_eq("AAAA", "EQ", 10, 11, 9.5, 10.5, 1000)],
           "fo": [_fo("IDO", "IDXA", date(2026, 11, 3), 10000, "CE", 5.5, 15000, 10)]}
    ok = asyncio.run(xc.run(date(2026, 10, 28), _FakeClient(td.parse_csv(BHAV_EQ), td.parse_csv(BHAV_FO)), nse,
                            switch=lambda: ON))
    assert ok["verdict"] == "EQUAL" and ok["equity"]["td_rows"] == 3 and ok["writes"] == "none (read only)"
    err = asyncio.run(xc.run(date(2026, 10, 28), _FakeClient(
        td.parse_csv(BHAV_EQ), td.TrueDataError(td.EMPTY_RESPONSE, "TrueData getbhavcopy: No data exists")), nse,
        switch=lambda: ON))
    assert err["fno"]["verdict"] == "TRUEDATA_ERROR" and err["fno"]["error_code"] == td.EMPTY_RESPONSE
    assert err["verdict"] == "NOT_COMPARED"


# ── SW-5 / SW-6 / SW-7: the cross-check obeys the switch ──────────────────────────────────────────────────────

class _NeverCalled:
    def bhavcopy(self, *a):
        raise AssertionError("TrueData called while switched off")


def test_sw5_crosscheck_switched_off_touches_nothing(monkeypatch):
    async def no_db(day):
        raise AssertionError("warehouse read while switched off")
    monkeypatch.setattr(xc, "read_nse", no_db)
    r = asyncio.run(xc.run(date(2026, 10, 28), _NeverCalled(), switch=lambda: OFF))
    assert r["verdict"] == "SWITCHED_OFF" and r["market_data_source"] == "current" and "switched off" in r["message"]


def test_sw5_cli_on_the_shipped_switch_exits_2_without_db_or_truedata(monkeypatch, capsys):
    from nidp.services.truedata_crosscheck import __main__ as cli

    async def no_db(day):
        raise AssertionError("warehouse read while switched off")
    monkeypatch.setattr(xc, "read_nse", no_db)
    monkeypatch.setattr(td.TrueDataClient, "bhavcopy", _NeverCalled.bhavcopy)
    monkeypatch.setattr("sys.argv", ["truedata_crosscheck", "--date", "2026-10-28"])
    assert cli.main() == 2
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "SWITCHED_OFF" and out["market_data_source"] == "current"


def test_sw6_evaluation_runs_while_switched_off_and_says_so():
    nse = {"eq": [_eq("AAAA", "EQ", 10, 11, 9.5, 10.5, 1000)],
           "fo": [_fo("IDO", "IDXA", date(2026, 11, 3), 10000, "CE", 5.5, 15000, 10)]}
    r = asyncio.run(xc.run(date(2026, 10, 28), _FakeClient(td.parse_csv(BHAV_EQ), td.parse_csv(BHAV_FO)), nse,
                           evaluation=True, switch=lambda: OFF))
    assert r["verdict"] == "EQUAL" and r["mode"] == "evaluation (switch is current)"


def test_sw7_shipped_switch_keeps_truedata_off():
    r = mds.resolve()
    assert r.configured == "current" and r.effective == "current" and mds.TRUEDATA_INTEGRATED is False
    assert mds.truedata_is_on() is False and mds.truedata_is_on(r) is False
