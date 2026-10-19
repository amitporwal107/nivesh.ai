"""DaaS /v1/desk/* — the trading desk's market reads (nidp/services/daas_api/routers/desk_market.py).

No live Postgres: a fake connection answers each query by the table it reads and records the arguments, so the
router's own work runs for real — the returns, the deal value and side, the build-up labels and counts, the
sorting, the validation and the empty answers. MOCK — not real data, except where a fixture says it was copied
from the staging warehouse on 2026-10-14 (those rows check the figures the data test produced).

Worked examples
  sector returns (Nifty IT, staging 2026-10-13): close 29830.10, previous 28349.60 → 29830.10 / 28349.60 − 1 = 5.22 %
                 (NSE's own pct_change for that day is 5.22); the hand example below uses closes
                 110 (today), 100 (1 row back), 88 (5 rows back), 125 (21 rows back) → +10.00 %, +25.00 %, −12.00 %
  deal value     CMLL bulk SELL 2,099,164 × ₹633.54 = ₹1,329,904,360.56 → ₹132.99 crore (staging 2026-10-13);
                 JUBLPHARMA block 1,100,000 × ₹915 = ₹1,006,500,000 → ₹100.65 crore (staging 2026-10-12)
  OI change %    UJJIVANSFB: OI 37,184,000, change +5,736,000 → previous 31,448,000 → 5,736,000 / 31,448,000 = 18.24 %
                 price 65.46 vs 62.56 → +4.64 % → long_buildup (staging 2026-10-13)
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}


class _Conn:
    def __init__(self, db):
        self.db = db
        self.calls = []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        # The build-up query also reads nidp.index_eod (the index futures' cash side), so it is matched first.
        if "nidp.fno_bhavcopy" in q:
            return self.db.get("fno_rows", [])
        if "nidp.index_eod" in q:
            return self.db.get("index_rows", [])
        if "nidp.bulk_deals" in q:
            return self.db.get("deal_rows", [])
        return []

    async def fetchval(self, q, *a):
        self.calls.append((q, a))
        if "nidp.bulk_deals" in q:
            return self.db.get("deals_latest")
        if "nidp.fno_bhavcopy" in q:
            return self.db.get("fno_latest")
        return None

    async def fetchrow(self, q, *a):
        self.calls.append((q, a))
        return None


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _CM()


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import desk_market

    def _make(db):
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(desk_market, "get_pool", _get_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh",
                             plan="internal", rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)

        async def _resolve(_t):
            return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)

        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                           daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        # The desk router alone, mounted under /v1 as daas_api/app.py mounts it. The full app is not imported: its
        # other routers bind the storage pool at first import, and test_daas_api relies on that first import
        # happening under its own fake pool. The validation handler below gives the same 400 envelope as app.py's
        # _validation_handler.
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _validation(_request, exc):
            return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

        app.include_router(desk_market.router, prefix="/v1")
        return TestClient(app), pool
    return _make


# ── sector returns ───────────────────────────────────────────────────────────

def _series(name, closes, last=date(2026, 10, 13)):
    """Index rows newest first, one calendar day apart (the router counts rows, not days)."""
    return [{"index_name": name, "as_of_date": last - timedelta(days=i), "close_price": Decimal(str(c))} for i, c in enumerate(closes)]


def test_sector_returns_against_the_close_n_rows_back_in_that_index(make_client):
    hand = [110, 100, 97, 95, 92, 88] + [90] * 15 + [125]          # 22 closes: rows 0, 1, 5 and 21 are the ones read
    db = {"index_rows": _series("Nifty Auto", hand)
          # copied from the staging warehouse (nidp.index_eod, 2026-10-13 and 2026-10-12)
          + _series("Nifty IT", [29830.10, 28349.60])
          + _series("Nifty Bank", [55481.05], last=date(2026, 10, 9))}
    c, pool = make_client(db)
    r = c.get("/v1/desk/sector-returns", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["as_of"] == "2026-10-13" and d["source"] == "NSE index close (nidp.index_eod)"
    assert d["sessions"] == {"1d": 1, "1w": 5, "1m": 21}
    by = {s["index"]: s for s in d["sectors"]}
    assert [s["index"] for s in d["sectors"]][:3] == ["Nifty Auto", "Nifty Bank", "Nifty Financial Services"]
    assert len(d["sectors"]) == 20
    assert by["Nifty Auto"] == {"index": "Nifty Auto", "sector": "Auto", "date": "2026-10-13", "close": 110.0,
                                "ret_1d_pct": 10.0, "ret_1w_pct": 25.0, "ret_1m_pct": -12.0}
    # two closes: the 1-day return only; the rest is null, never 0
    assert by["Nifty IT"]["ret_1d_pct"] == 5.22 and by["Nifty IT"]["ret_1w_pct"] is None and by["Nifty IT"]["ret_1m_pct"] is None
    # a lagging index keeps its own date, so it is not mixed in as today's
    assert by["Nifty Bank"]["date"] == "2026-10-09" and by["Nifty Bank"]["ret_1d_pct"] is None
    # an index with no rows is listed with nulls, not dropped and not zero
    assert by["Nifty Pharma"] == {"index": "Nifty Pharma", "sector": "Pharma", "date": None, "close": None,
                                  "ret_1d_pct": None, "ret_1w_pct": None, "ret_1m_pct": None}
    q, args = pool.conn.calls[0]
    assert "nidp.index_eod" in q and args[1] == 22 and "Nifty Healthcare Index" in args[0] and len(args[0]) == 20


def test_sector_returns_with_no_rows_is_200_with_a_null_as_of(make_client):
    c, _ = make_client({})
    r = c.get("/v1/desk/sector-returns", headers=H)
    assert r.status_code == 200
    assert r.json()["as_of"] is None and all(s["close"] is None for s in r.json()["sectors"])


def test_pct_return_refuses_a_missing_or_non_positive_base():
    from nidp.services.daas_api.routers.desk_market import pct_return
    assert pct_return(110.0, 100.0) == 10.0
    assert pct_return(None, 100.0) is None and pct_return(110.0, None) is None and pct_return(110.0, 0.0) is None


def test_desk_routes_need_an_api_key(make_client):
    c, pool = make_client({})
    for path in ("/v1/desk/sector-returns", "/v1/desk/deals", "/v1/desk/fno-buildup"):
        assert c.get(path).status_code == 401
    assert pool.conn.calls == []


# ── deals ────────────────────────────────────────────────────────────────────

def _deal(kind, symbol, client, side, qty, price, day=date(2026, 10, 13), total=3):
    return {"as_of_date": day, "kind": kind, "symbol": symbol, "client_name": client, "deal_type": side,
            "quantity": qty, "avg_price": Decimal(str(price)) if price is not None else None, "total": total}


def test_deals_shape_value_side_and_window(make_client):
    db = {"deals_latest": date(2026, 10, 13),
          "deal_rows": [
              # copied from the staging warehouse (nidp.bulk_deals, 2026-10-13)
              _deal("bulk", "CMLL", "MICROCURVES TRADING PRIVATE LIMITED", "SELL", 2099164, 633.54),
              _deal("block", "JUBLPHARMA", "QUANT MUTUAL FUND", "SELL", 1100000, 915.0, day=date(2026, 10, 12)),
              _deal("bulk", "ABC", "XYZ FUND", "??", 1000, None),
          ]}
    c, pool = make_client(db)
    r = c.get("/v1/desk/deals?days=5&symbol=cmll&limit=50", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["as_of"], d["from"], d["days"], d["kind"], d["symbol"]) == ("2026-10-13", "2026-10-09", 5, "all", "CMLL")
    assert d["source"] == "NSE bulk and block deals (nidp.bulk_deals, nidp.block_deals)"
    assert (d["count"], d["total"]) == (3, 3)
    assert d["rows"][0] == {"date": "2026-10-13", "kind": "bulk", "symbol": "CMLL", "client_name": "MICROCURVES TRADING PRIVATE LIMITED",
                            "side": "SELL", "quantity": 2099164, "avg_price": 633.54, "value_cr": 132.99,
                            # no enrichment columns on these rows: every one is null, never 0 (worked examples in
                            # test_daas_desk_intel.py)
                            "total_shares": None, "shares_period_end": None, "pct_of_shares": None, "close_on_day": None,
                            "prev_close": None, "next_date": None, "next_close": None, "price_vs_close_pct": None,
                            "ingested_at": None, "disclosure": "exchange"}
    assert d["rows"][1]["value_cr"] == 100.65 and d["rows"][1]["kind"] == "block"
    # an unknown side and a missing price stay null; the value is not worked out from half a deal
    assert d["rows"][2]["side"] is None and d["rows"][2]["value_cr"] is None and d["rows"][2]["avg_price"] is None
    q, args = pool.conn.calls[-1]
    # the one deals reader in flows.py: first day, last day, kind, symbol, client, limit, offset, price series
    assert "nidp.block_deals" in q and args == (date(2026, 10, 9), date(2026, 10, 13), "all", "CMLL", None, 50, 0,
                                                ["EQ", "BE", "BZ", "SM", "ST"])


def test_deals_one_day_window_starts_on_the_latest_day(make_client):
    c, pool = make_client({"deals_latest": date(2026, 10, 13), "deal_rows": []})
    r = c.get("/v1/desk/deals?days=1&kind=block", headers=H)
    assert r.status_code == 200
    d = r.json()
    # no block deals on the latest day is a real empty answer with its date, not an older day
    assert (d["as_of"], d["from"], d["count"], d["total"], d["rows"]) == ("2026-10-13", "2026-10-13", 0, 0, [])
    assert pool.conn.calls[-1][1][:7] == (date(2026, 10, 13), date(2026, 10, 13), "block", None, None, 500, 0)


def test_deals_with_no_deals_on_record(make_client):
    c, pool = make_client({"deals_latest": None})
    r = c.get("/v1/desk/deals", headers=H)
    assert r.status_code == 200
    assert r.json()["as_of"] is None and r.json()["rows"] == [] and r.json()["count"] == 0
    assert len(pool.conn.calls) == 1          # the rows query is not run without a day


@pytest.mark.parametrize("qs", ["days=0", "days=31", "kind=insider", "symbol=AB%20C", "limit=0", "symbol=" + "A" * 21])
def test_deals_rejects_bad_parameters(make_client, qs):
    c, pool = make_client({"deals_latest": date(2026, 10, 13)})
    # the DaaS app answers request-validation errors with 400 (app.py _validation_handler)
    assert c.get(f"/v1/desk/deals?{qs}", headers=H).status_code == 400
    assert pool.conn.calls == []


# ── F&O build-up ─────────────────────────────────────────────────────────────

def _fut(symbol, close, prev, oi, oi_chg, expiries=3, near=date(2026, 10, 27)):
    dec = lambda v: Decimal(str(v)) if v is not None else None  # noqa: E731
    return {"symbol": symbol, "near_expiry": near, "close": dec(close), "prev_close": dec(prev),
            "oi": oi, "oi_chg": oi_chg, "expiries": expiries}


FNO_ROWS = [
    # copied from the staging warehouse (nidp.fno_bhavcopy, 2026-10-13, stock futures summed over 3 expiries)
    _fut("UJJIVANSFB", 65.46, 62.56, 37184000, 5736000),
    _fut("HYUNDAI", 1962.80, 1934.80, 5340775, 486750),
    # hand examples, one per remaining reading
    _fut("SHORTB", 95.0, 100.0, 1100, 100),         # price down, OI up    → short_buildup, OI +10.00 %
    _fut("COVER", 105.0, 100.0, 900, -100),         # price up,   OI down  → short_covering, OI −10.00 %
    _fut("UNWIND", 95.0, 100.0, 1050, -50),         # price down, OI down  → long_unwinding, OI −4.55 %
    _fut("FLATP", 100.0, 100.0, 1020, 20),          # price flat           → neutral, OI +2.00 %
    _fut("FLATOI", 101.0, 100.0, 1000, 0),          # OI flat              → neutral, OI 0.00 %
    _fut("NOPREV", 101.0, None, 1000, 10),          # no previous close    → no label, counted as no_data
    _fut("NOOI", 101.0, 100.0, None, None),         # OI missing on an expiry → null sums, no label
]


def test_fno_buildup_labels_counts_and_percents(make_client):
    c, pool = make_client({"fno_latest": date(2026, 10, 13), "fno_rows": FNO_ROWS})
    r = c.get("/v1/desk/fno-buildup", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["as_of"] == "2026-10-13" and d["source"] == "NSE F&O bhavcopy (nidp.fno_bhavcopy), stock futures"
    assert d["universe"] == 9
    assert d["counts"] == {"long_buildup": 2, "short_buildup": 1, "short_covering": 1, "long_unwinding": 1, "neutral": 2, "no_data": 2}
    by = {x["symbol"]: x for x in d["rows"]}
    assert by["UJJIVANSFB"] == {"symbol": "UJJIVANSFB", "near_expiry": "2026-10-27", "close": 65.46, "prev_close": 62.56,
                                "price_chg_pct": 4.64, "oi": 37184000, "oi_chg": 5736000, "oi_chg_pct": 18.24,
                                "expiries": 3, "label": "long_buildup",
                                # the B20 fields: 27 Oct − 13 Oct = 14 days; no cash row here, so no confirmation and the
                                # no_cash_price flag (worked cash examples in test_daas_desk_intel.py)
                                "days_to_expiry": 14, "fut_contracts": None, "fut_turnover_cr": None, "cash_close": None,
                                "cash_prev_close": None, "cash_chg_pct": None, "cash_volume": None, "cash_confirmation": None,
                                "vol_z20": None, "vol_z20_date": None, "fno_eligible": None, "master_date": None,
                                "risk_flags": ["no_cash_price"], "setup_quality": None}
    assert by["HYUNDAI"]["oi_chg_pct"] == 10.03 and by["HYUNDAI"]["price_chg_pct"] == 1.45
    assert [by[s]["label"] for s in ("SHORTB", "COVER", "UNWIND", "FLATP", "FLATOI")] == \
        ["short_buildup", "short_covering", "long_unwinding", "neutral", "neutral"]
    assert by["UNWIND"]["oi_chg_pct"] == -4.55 and by["FLATOI"]["oi_chg_pct"] == 0.0
    assert by["NOPREV"]["label"] is None and by["NOPREV"]["price_chg_pct"] is None
    assert by["NOOI"]["label"] is None and by["NOOI"]["oi"] is None and by["NOOI"]["oi_chg_pct"] is None
    # largest OI change (either way) first; rows without one last
    assert [x["symbol"] for x in d["rows"]][:4] == ["UJJIVANSFB", "HYUNDAI", "COVER", "SHORTB"]   # 18.24, 10.03, −10.00, 10.00 (tie → symbol)
    assert [x["symbol"] for x in d["rows"]][-1] == "NOOI"
    q, args = pool.conn.calls[-1]
    assert "instrument_type IN ('STF', 'IDF')" in q and args[0] == date(2026, 10, 13)
    assert d["indices"] == [] and d["intraday"]["status"] == "unavailable" and d["setup_quality"] == "not_validated"


def test_fno_buildup_for_a_given_day_with_no_rows(make_client):
    c, pool = make_client({"fno_latest": date(2026, 10, 13), "fno_rows": []})
    r = c.get("/v1/desk/fno-buildup?date=2026-10-02", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert (d["as_of"], d["universe"], d["rows"]) == ("2026-10-02", 0, [])
    assert sum(d["counts"].values()) == 0
    assert len(pool.conn.calls) == 1 and pool.conn.calls[0][1][0] == date(2026, 10, 2)   # the latest-day read is skipped


def test_fno_buildup_with_no_futures_on_record(make_client):
    c, pool = make_client({"fno_latest": None})
    r = c.get("/v1/desk/fno-buildup", headers=H)
    assert r.status_code == 200 and r.json()["as_of"] is None and r.json()["rows"] == []
    assert len(pool.conn.calls) == 1


def test_fno_buildup_rejects_a_bad_date(make_client):
    c, pool = make_client({})
    assert c.get("/v1/desk/fno-buildup?date=13-10-2026", headers=H).status_code == 400
    assert pool.conn.calls == []


def test_buildup_label_reads_signs_only():
    from nidp.services.daas_api.routers.desk_market import buildup_label
    assert buildup_label(0.01, 1) == "long_buildup"
    assert buildup_label(-0.01, 1) == "short_buildup"
    assert buildup_label(0.01, -1) == "short_covering"
    assert buildup_label(-0.01, -1) == "long_unwinding"
    assert buildup_label(0.0, 5) == "neutral" and buildup_label(1.0, 0) == "neutral"
    assert buildup_label(None, 5) is None and buildup_label(1.0, None) is None
