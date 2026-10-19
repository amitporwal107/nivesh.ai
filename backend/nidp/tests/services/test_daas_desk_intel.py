"""DaaS — the Market intelligence and F&O additions of the trading desk (PRD §6.3, §6.6, §10.2–§10.6):

    /v1/flows/bulk-deals, /block-deals and /v1/desk/deals    one deals reader (flows.read_deals) with % of shares,
                                                              the price around the deal and the ingestion time
    /v1/desk/fno-buildup                                       cash close and confirmation, vol_z20, the F&O master,
                                                              risk flags, index futures, the intraday state
    /v1/desk/filings?family=                                   filings by the exchange's own subject line
    /v1/desk/event-sources?ids=                                each filing's records, timing, sector and peers

No live Postgres: a fake connection answers each query by the table it reads and records the arguments, so the
routers' own work runs for real. MOCK — not real data, except where a row says it was copied from the staging
warehouse on 2026-10-14.

Worked examples
  % of shares    250,000 ÷ 50,000,000 × 100 = 0.5000 %
  vs close       deal price 98.50 against the day's close 100.00 → 98.5 ÷ 100 − 1 = −1.50 %
  confirmation   RELIANCE (staging 2026-10-14): near future 1,182.20 vs 1,174.30 (up), cash 1,174.60 vs 1,166.70 (up)
                 → confirms; a hand row with the future up and the cash down → diverges
  index future   NIFTY (staging 2026-10-14): future 22,648.50 vs 22,834.80 (down), Nifty 50 22,622.70 with a points
                 change of −99.25 → previous 22,721.95, down → confirms; OI +148,330 → short build-up
  flags          a near expiry 4 days out → expiry_week; next-month OI 2,000 above near-month 1,500 → rollover
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}
D = lambda v: Decimal(str(v)) if v is not None else None  # noqa: E731


class _Conn:
    def __init__(self, db):
        self.db = db
        self.calls = []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        if "nidp.bulk_deals" in q:
            return self.db.get("deal_rows", [])
        if "nidp.fno_bhavcopy" in q:
            return self.db.get("fno_rows", [])
        if "nidp.v_event_asof" in q:
            return self.db.get("asof_rows", [])
        if "ROW_NUMBER" in q and "nidp.index_constituents" in q:
            return self.db.get("peer_rows", [])
        if "nidp.index_constituents" in q:
            return self.db.get("industry_rows", [])
        if "subject ILIKE ANY" in q:
            return self.db.get("family_rows", [])
        if "nidp.corporate_announcements" in q:
            return self.db.get("record_rows", [])
        return []

    async def fetchval(self, q, *a):
        self.calls.append((q, a))
        return self.db.get("latest")


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
    from nidp.services.daas_api.routers import desk_market, flows

    def _make(db):
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(desk_market, "get_pool", _get_pool)
        monkeypatch.setattr(flows, "get_pool", _get_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh",
                             plan="internal", rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)

        async def _resolve(_t):
            return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)

        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                           daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _validation(_request, exc):
            return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

        app.include_router(desk_market.router, prefix="/v1")
        app.include_router(flows.router, prefix="/v1")
        return TestClient(app), pool
    return _make


# ── deals: one reader, enriched ──────────────────────────────────────────────

def _deal(**o):
    row = {"as_of_date": date(2026, 10, 13), "kind": "bulk", "symbol": "FIXD", "client_name": "FIXTURE FUND", "deal_type": "SELL",
           "quantity": 250000, "avg_price": D(98.5), "deal_seq": 1, "remarks": None,
           "ingested_at": datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc), "total": 1,
           "total_shares": 50_000_000, "shares_period_end": date(2026, 6, 30), "close_on_day": D(100.0), "prev_close": D(97.0),
           "next_date": date(2026, 10, 14), "next_close": D(99.0)}
    row.update(o)
    return row


def test_desk_deals_carry_share_of_company_price_around_the_deal_and_ingestion_time(make_client):
    c, pool = make_client({"latest": date(2026, 10, 13), "deal_rows": [_deal(), _deal(symbol="NOSH", total_shares=None,
                                                                                       shares_period_end=None, close_on_day=None)]})
    d = c.get("/v1/desk/deals?days=5", headers=H).json()
    r = d["rows"][0]
    assert (r["pct_of_shares"], r["total_shares"], r["shares_period_end"]) == (0.5, 50_000_000, "2026-06-30")
    assert (r["close_on_day"], r["prev_close"], r["next_date"], r["next_close"]) == (100.0, 97.0, "2026-10-14", 99.0)
    assert r["price_vs_close_pct"] == -1.5 and r["ingested_at"] == "2026-10-13T14:00:00+00:00" and r["disclosure"] == "exchange"
    # no shareholding pattern and no close: null, never 0
    assert (d["rows"][1]["pct_of_shares"], d["rows"][1]["price_vs_close_pct"]) == (None, None)
    assert "No institutional activity is inferred" in d["disclosure"]


def test_flows_bulk_and_block_deals_use_the_same_reader(make_client):
    c, pool = make_client({"deal_rows": [_deal()]})
    body = c.get("/v1/flows/block-deals?symbol=fixd&start=2026-10-01&client=fund&limit=10", headers=H).json()
    q, args = pool.conn.calls[-1]
    assert "nidp.shareholding_pattern" in q and "nidp.prices_eod" in q
    assert args == (date(2026, 10, 1), None, "block", "FIXD", "%FUND%", 10, 0, ["EQ", "BE", "BZ", "SM", "ST"])
    row = body["data"][0]
    assert row["pct_of_shares"] == 0.5 and row["close_on_day"] == 100.0 and "total" not in row
    assert body["pagination"]["total"] == 1 and body["source"] == "NSE bulk and block deals (nidp.bulk_deals, nidp.block_deals)"
    c.get("/v1/flows/bulk-deals", headers=H)
    assert pool.conn.calls[-1][1][:5] == (None, None, "bulk", None, None)


def test_pct_of_shares_refuses_a_missing_or_non_positive_count():
    from nidp.services.daas_api.routers.flows import pct_of_shares
    assert pct_of_shares(250000, 50_000_000) == 0.5
    assert pct_of_shares(1, 3) == 33.3333
    assert pct_of_shares(1000, None) is None and pct_of_shares(1000, 0) is None and pct_of_shares(None, 10) is None


# ── F&O build-up: B20 fields, flags, index futures ───────────────────────────

def _fut(symbol, close, prev, oi, oi_chg, **o):
    row = {"instrument_type": "STF", "symbol": symbol, "near_expiry": date(2026, 10, 27), "close": D(close), "prev_close": D(prev),
           "oi": oi, "oi_chg": oi_chg, "expiries": 3, "near_oi": None, "next_oi": None, "fut_contracts": None, "fut_value": None,
           "cash_close": None, "cash_prev_close": None, "cash_volume": None, "vol_z20": None, "vol_z20_date": None,
           "fno_eligible": None, "master_date": None, "index_close": None, "index_change": None}
    row.update(o)
    return row


FNO = [
    # copied from the staging warehouse 2026-10-14 (nidp.fno_bhavcopy STF summed over 3 expiries, prices_eod EQ close and
    # previous close, stock_features_daily vol_z20, security_reference_daily); cash_volume is made up
    _fut("RELIANCE", 1182.2, 1174.3, 173944000, 2814500, near_oi=146482500, next_oi=24598000, fut_contracts=36223,
         fut_value=D(21457939250.0), cash_close=D(1174.6), cash_prev_close=D(1166.7), cash_volume=8123456,
         vol_z20=D(-0.4501), vol_z20_date=date(2026, 10, 12), fno_eligible=True, master_date=date(2026, 10, 14)),
    # hand rows
    _fut("DIVERGE", 101.0, 100.0, 1100, 100, cash_close=D(99.0), cash_prev_close=D(100.0), fno_eligible=True,
         master_date=date(2026, 10, 14)),
    _fut("ROLL", 99.0, 100.0, 3600, 100, near_expiry=date(2026, 10, 18), near_oi=1500, next_oi=2000, cash_close=D(99.0),
         cash_prev_close=D(100.0), fno_eligible=False, master_date=date(2026, 10, 14)),
    # copied from staging 2026-10-14: NIFTY index futures and the Nifty 50 close
    _fut("NIFTY", 22648.5, 22834.8, 21514025, 148330, instrument_type="IDF", near_oi=18451355, next_oi=2574910,
         fut_contracts=60579, index_close=D(22622.7), index_change=D(-99.25)),
]


def test_fno_buildup_adds_cash_confirmation_rvol_master_and_risk_flags(make_client):
    c, pool = make_client({"latest": date(2026, 10, 14), "fno_rows": FNO})
    d = c.get("/v1/desk/fno-buildup", headers=H).json()
    assert d["universe"] == 3 and sum(d["counts"].values()) == 3            # the index future is not in the stock counts
    by = {r["symbol"]: r for r in d["rows"]}
    rel = by["RELIANCE"]
    assert (rel["cash_close"], rel["cash_prev_close"], rel["cash_chg_pct"], rel["cash_volume"]) == (1174.6, 1166.7, 0.68, 8123456)
    assert (rel["price_chg_pct"], rel["cash_confirmation"], rel["label"]) == (0.67, "confirms", "long_buildup")
    assert (rel["vol_z20"], rel["vol_z20_date"], rel["fno_eligible"], rel["master_date"]) == (-0.45, "2026-10-12", True, "2026-10-14")
    assert (rel["fut_contracts"], rel["fut_turnover_cr"], rel["days_to_expiry"], rel["risk_flags"]) == (36223, 2145.79, 13, [])
    assert rel["setup_quality"] is None
    assert by["DIVERGE"]["cash_confirmation"] == "diverges"
    assert by["ROLL"]["risk_flags"] == ["expiry_week", "rollover"] and by["ROLL"]["days_to_expiry"] == 4
    assert by["ROLL"]["fno_eligible"] is False
    assert d["master"] == {"as_of": "2026-10-14", "eligible": 2, "not_eligible": 1, "unknown": 0}
    assert set(d["risk_flag_text"]) == {"expiry_week", "rollover", "no_cash_price"}
    # index futures: their own list, the cash side from the index close (previous = close − points change)
    [nifty] = d["indices"]
    assert (nifty["symbol"], nifty["index_name"], nifty["label"]) == ("NIFTY", "Nifty 50", "short_buildup")
    assert (nifty["cash_close"], nifty["cash_prev_close"], nifty["cash_chg_pct"], nifty["cash_confirmation"]) == (22622.7, 22721.95, -0.44, "confirms")
    assert nifty["price_chg_pct"] == -0.82 and nifty["fno_eligible"] is True
    # 15-minute confirmation: unavailable, with the reason, never a made-up state
    assert d["intraday"]["status"] == "unavailable" and "No intraday open interest" in d["intraday"]["reason"]
    q, args = pool.conn.calls[-1]
    assert args == (date(2026, 10, 14), ["EQ", "BE", "BZ", "SM", "ST"], ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"],
                    ["Nifty 50", "Nifty Bank", "Nifty Financial Services", "Nifty Midcap Select", "Nifty Next 50"])


def test_cash_confirmation_and_risk_flags_rules():
    from nidp.services.daas_api.routers.desk_market import cash_confirmation, risk_flags
    assert cash_confirmation(1.0, 2.0) == "confirms" and cash_confirmation(-1.0, -0.1) == "confirms"
    assert cash_confirmation(1.0, -2.0) == "diverges"
    assert cash_confirmation(0.0, 1.0) is None and cash_confirmation(None, 1.0) is None and cash_confirmation(1.0, None) is None
    day = date(2026, 10, 20)
    assert risk_flags(day, date(2026, 10, 27), 10, 20, True) == ["expiry_week", "rollover"]
    assert risk_flags(day, date(2026, 10, 28), 10, 20, True) == []                 # 8 days out: not expiry week
    assert risk_flags(day, date(2026, 10, 27), 30, 20, False) == ["expiry_week", "no_cash_price"]


# ── filings by exchange subject family ───────────────────────────────────────

def test_filings_family_reads_the_subject_patterns_and_sends_the_articles_shape(make_client):
    row = {"announcement_id": "c1", "source": "NSE_ANN", "ticker_symbol": "FIXC", "company_name": "Fix C Ltd",
           "subject": "Analysts/Institutional Investor Meet/Con. Call Updates", "event_category": "regulatory", "impact_score": "low",
           "sentiment": "neutral", "filed_at": datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc), "attachment_url": None,
           "ingested_at": datetime(2026, 10, 13, 8, 15, tzinfo=timezone.utc), "total": 7}
    c, pool = make_client({"family_rows": [row]})
    d = c.get("/v1/desk/filings?family=calls&days=7&limit=20", headers=H).json()
    q, args = pool.conn.calls[-1]
    assert args[1] == ["%Con. Call%", "%Analyst%Meet%", "%Investor Meet%", "%Transcript%", "%Earnings Call%", "%Investor Presentation%"]
    assert args[2:] == (20, 0)
    assert d["total"] == 7 and d["family"] == "calls"
    assert d["articles"] == [{"id": "c1", "title": "Analysts/Institutional Investor Meet/Con. Call Updates", "company": "Fix C Ltd",
                              "symbol": "FIXC", "category": "Regulatory", "impact": "low", "sentiment": "neutral",
                              "when": "2026-10-13T08:00:00+00:00", "source": "NSE_ANN", "url": None,
                              "ingested_at": "2026-10-13T08:15:00+00:00"}]
    assert c.get("/v1/desk/filings?family=gossip", headers=H).status_code == 400


# ── each filing's source records ─────────────────────────────────────────────

def test_event_sources_keep_every_record_with_both_times_and_add_sector_and_peers(make_client):
    t = lambda h, m: datetime(2026, 10, 13, h, m, tzinfo=timezone.utc)  # noqa: E731
    rec = lambda i, src, sym, ind: {"announcement_id": i, "source": src, "ticker_symbol": sym, "company_name": "Fix A Ltd",  # noqa: E731
                                    "subject": "Outcome", "filed_at": t(9, 0), "broadcast_at": None, "ingested_at": t(9, 15),
                                    "classified_at": None, "classifier_version": None, "attachment_url": None,
                                    "exchange_industry": ind}
    asof = lambda i, src, sym, res, primary: {"announcement_id": i, "source": src, "nse_symbol": sym, "resolution": res,  # noqa: E731
                                              "timing_type": "intraday", "known_at_open_session": date(2026, 10, 14),
                                              "known_by_close_session": date(2026, 10, 13), "primary_row": primary,
                                              "ts_basis": "dissemination"}
    db = {
        "record_rows": [rec("n1", "NSE_ANN", "FIXA", "Pharmaceuticals"), rec("b1", "BSE_ANN", None, None),
                        rec("n2", "NSE_ANN", "SMALLCO", "Sugar")],
        "asof_rows": [asof("n1", "NSE_ANN", "FIXA", "exchange_symbol", True), asof("b1", "BSE_ANN", "FIXA", "bse_scrip_isin_bridge", False),
                      asof("n2", "NSE_ANN", "SMALLCO", "exchange_symbol", True)],
        "industry_rows": [{"symbol": "FIXA", "industry": "Healthcare", "index_name": "Nifty Total Market", "as_of_date": date(2026, 10, 13)}],
        "peer_rows": [{"industry": "Healthcare", "symbol": s, "company_name": f"{s} Ltd", "t": tier}
                      for s, tier in [("CIPLA", 1), ("FIXA", 4), ("SUNPHARMA", 1), ("ALKEM", 2)]],
    }
    c, pool = make_client(db)
    d = c.get("/v1/desk/event-sources?ids=n1,b1,n2,unknown", headers=H).json()
    ev = d["events"]
    assert set(ev) == {"n1", "b1", "n2"}                                     # an unknown id is left out
    assert ev["n1"]["records"][0]["published_at"] == "2026-10-13T09:00:00+00:00"
    assert ev["n1"]["records"][0]["ingested_at"] == "2026-10-13T09:15:00+00:00"
    assert (ev["n1"]["sector"], ev["n1"]["sector_source"]) == ("Healthcare", "NSE index list (Nifty Total Market, 2026-10-13)")
    # peers: the same industry, the stock itself left out, with the narrowest broad index each is in
    assert ev["n1"]["peers"] == [{"symbol": "CIPLA", "name": "CIPLA Ltd", "largest_index": "Nifty 50"},
                                 {"symbol": "SUNPHARMA", "name": "SUNPHARMA Ltd", "largest_index": "Nifty 50"},
                                 {"symbol": "ALKEM", "name": "ALKEM Ltd", "largest_index": "Nifty 100"}]
    # the BSE copy without a ticker resolves through the scrip bridge to FIXA
    assert (ev["b1"]["nse_symbol"], ev["b1"]["resolution"], ev["b1"]["primary_row"], ev["b1"]["sector"]) == (
        "FIXA", "bse_scrip_isin_bridge", False, "Healthcare")
    # not in an NSE index list: the exchange's own industry field, said so; no peers
    assert (ev["n2"]["sector"], ev["n2"]["sector_source"], ev["n2"]["peers"]) == (
        "Sugar", "The exchange's industry field on the filing (NSE)", [])
    ids_asked = [a for q, a in pool.conn.calls if "nidp.corporate_announcements" in q and "v_event_asof" not in q][0][0]
    assert ids_asked == ["n1", "b1", "n2", "unknown"]


def test_event_sources_without_ids_reads_nothing(make_client):
    c, pool = make_client({})
    assert c.get("/v1/desk/event-sources?ids=,,", headers=H).json()["events"] == {}
    assert pool.conn.calls == []
