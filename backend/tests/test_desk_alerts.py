"""Smart trading desk — the alert conditions of PRD §6.7 (services/desk_alerts.py, the alert routes in
routes/desk_trading.py and scripts/check_desk_alerts.py).

No network and no real database. Replaced, and by what:
  * `route.db` / the script's db   an in-memory stand-in for the Mongo alert collection (equality filters only)
  * `route.get_current_user`       reads the test's `X-Test-User` header
  * the data platform              `daas_client._get` serving /prices/eod, /announcements, /flows/{bulk,block}-deals
                                   and /indices/{index}/eod from the World's rows, the way the real routers answer
  * the scanner database           `pg_client.get_pool` → a fake pool answering the positional_signals query
  * the clock                      `svc.utcnow`, fixed at 2026-10-12 05:00 UTC (10:30 IST, a Monday)

Everything the modules do runs for real: validation, ownership, limits, dedupe, each condition's rule, the
idempotent writes, the reasons and the response shapes.

MOCK — not real data: every symbol, filing, deal, index close and bar here is made up.

Worked examples
  volume   base = 20 sessions of 1,000 shares → average 1,000; a 13 Oct session of 2,600 with multiple 2.5 → 2.6×,
           fires; 2,400 → 2.4×, does not
  risk     every bar high 103, low 97, close 100 → true range 6 → ATR 6 → 6.00 % of the close; level 5 fires on the
           first session after the alert date
  sector   Nifty IT closes 100 (12 Oct), 101.5 (13 Oct, +1.50 %), 98.0 (14 Oct, −3.45 %): threshold 2 either way
           fires on 14 Oct; threshold 2 "up" never fires
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import desk_trading as route
from services import desk_alerts as alerts_svc
from services import desk_trading as svc

URL = "/api/desk/alerts"
A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}
NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)          # Monday 10:30 IST


# ── in-memory collection ─────────────────────────────────────────────────────
def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    return all(doc.get(k) == v for k, v in query.items())


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction):
        self._docs = sorted(self._docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    async def to_list(self, length):
        return self._docs if length is None else self._docs[:length]


class _Res:
    def __init__(self, matched=0, deleted=0):
        self.matched_count = matched
        self.deleted_count = deleted


class Coll:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.writes = 0

    async def create_index(self, keys, **_):
        return None

    def find(self, q):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, q)])

    async def find_one(self, q):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, q)), None)

    async def count_documents(self, q):
        return sum(1 for d in self.docs if _matches(d, q))

    async def insert_one(self, doc):
        self.writes += 1
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, q, update):
        for d in self.docs:
            if _matches(d, q):
                self.writes += 1
                d.update(copy.deepcopy(update["$set"]))
                return _Res(matched=1)
        return _Res()

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _matches(d, q):
                del self.docs[i]
                return _Res(deleted=1)
        return _Res()


class Db:
    def __init__(self):
        self.cols = {svc.TRADES: Coll(), svc.ALERTS: Coll()}

    def __getitem__(self, name):
        return self.cols[name]

    @property
    def alerts(self) -> Coll:
        return self.cols[svc.ALERTS]


def bar(day: str, high, low, close, volume=1000) -> Dict[str, Any]:
    return {"as_of_date": day, "symbol": None, "series": "EQ", "prev_close": None, "open_price": None,
            "high_price": high, "low_price": low, "close_price": close, "volume": volume}


def sessions(start: date, n: int) -> List[str]:
    """n weekdays ending on `start` (oldest first)."""
    out: List[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


class World:
    def __init__(self):
        self.db = Db()
        self.bars: Dict[str, List[Dict[str, Any]]] = {}
        self.filings: List[Dict[str, Any]] = []
        self.deals: Dict[str, List[Dict[str, Any]]] = {"bulk": [], "block": []}
        self.index: Dict[str, List[Dict[str, Any]]] = {}
        self.signals: List[Dict[str, Any]] = []
        self.fail: set = set()
        self.calls: List[str] = []
        self.pg = True


@pytest.fixture
def world(monkeypatch) -> World:
    w = World()
    monkeypatch.setattr(route, "db", w.db)
    monkeypatch.setattr(svc, "_indexes_ready", False)
    monkeypatch.setattr(svc, "utcnow", lambda: NOW)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)

    async def fake_get(path: str, params=None, timeout: float = 10.0, *, creds=None):
        w.calls.append(path)
        params = params or {}
        for prefix in w.fail:
            if path.startswith(prefix):
                raise svc.daas_client.DaasError("unreachable")
        if path.startswith("/prices/eod/"):
            sym = unquote(path[len("/prices/eod/"):])
            rows = [dict(r, symbol=sym) for r in w.bars.get(sym, []) if r["as_of_date"] >= params.get("start", "")]
            rows.sort(key=lambda r: r["as_of_date"], reverse=True)
            return {"data": rows, "pagination": {"next_offset": None}}
        if path == "/announcements":
            rows = [r for r in w.filings
                    if (params.get("symbol") is None or r["ticker_symbol"] == params["symbol"])
                    and (params.get("category") is None or r["event_category"] == params["category"])
                    and r["filed_at"][:10] >= params["filed_from"]]
            return {"data": sorted(rows, key=lambda r: r["filed_at"], reverse=True)}
        if path.startswith("/flows/"):
            kind = path.split("/")[2].split("-")[0]
            rows = [r for r in w.deals[kind] if r["symbol"] == params["symbol"] and r["as_of_date"] >= params["start"]]
            return {"data": rows}
        if path.startswith("/indices/"):
            name = unquote(path.split("/")[2])
            return {"data": [r for r in w.index.get(name, []) if r["as_of_date"] >= params["start"]]}
        raise AssertionError(f"unexpected read {path}")

    monkeypatch.setattr(svc.daas_client, "_get", fake_get)
    monkeypatch.setattr(svc.daas_client, "is_configured", lambda: True)

    class _Conn:
        async def fetch(self, q, symbols, after):
            assert "positional_signals" in q
            return [r for r in w.signals if r["nse_symbol"] in symbols and r["signal_date"] > after]

    class _Pool:
        def acquire(self):
            class _CM:
                async def __aenter__(self_inner):
                    return _Conn()

                async def __aexit__(self_inner, *a):
                    return False
            return _CM()

    from services import pg_client

    async def get_pool():
        return _Pool() if w.pg else None
    monkeypatch.setattr(pg_client, "get_pool", get_pool)
    return w


@pytest.fixture
def api(world) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def create(api, body, who=A, status=201):
    r = api.post(URL, json=body, headers=who)
    assert r.status_code == status, r.text
    return r.json()


def listing(api, who=A):
    r = api.get(URL, headers=who)
    assert r.status_code == 200, r.text
    return r.json()


def by_id(body):
    return {a["id"]: a for a in body["alerts"]}


# ── validation, ownership, limits, dedupe ────────────────────────────────────
@pytest.mark.parametrize("body, code", [
    ({"condition": "filing"}, "invalid_symbol"),
    ({"condition": "filing", "symbol": "FIXA", "impact": "huge"}, "invalid_impact"),
    ({"condition": "category", "category": "gossip"}, "invalid_category"),
    ({"condition": "category", "category": "deal"}, "invalid_symbol"),
    ({"condition": "volume", "symbol": "FIXA", "multiple": 1.0}, "invalid_multiple"),
    ({"condition": "volume", "symbol": "FIXA", "multiple": "3"}, "invalid_multiple"),
    ({"condition": "scanner", "symbol": "FIXA", "stage": "WEAK"}, "invalid_stage"),
    ({"condition": "sector", "index": "Nifty Space", "threshold_pct": 2}, "invalid_index"),
    ({"condition": "sector", "index": "Nifty IT", "threshold_pct": 50}, "invalid_threshold"),
    ({"condition": "sector", "index": "Nifty IT", "threshold_pct": 2, "direction": "sideways"}, "invalid_direction"),
    ({"condition": "risk", "symbol": "FIXA", "level": 0}, "invalid_level"),
    ({"condition": "risk", "symbol": "FIXA", "level": 3, "multiple": 2}, "unknown_field"),
    ({"condition": "news", "symbol": "FIXA"}, "invalid_condition"),
])
def test_each_condition_refuses_a_bad_body_with_a_code(api, world, body, code):
    r = api.post(URL, json=body, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, code)
    assert world.db.alerts.docs == []


def test_every_condition_is_stored_for_its_owner_with_its_settings(api, world):
    made = [
        create(api, {"condition": "filing", "symbol": "fixa"})["alert"],
        create(api, {"condition": "category", "category": "earnings"})["alert"],
        create(api, {"condition": "category", "category": "deal", "symbol": "FIXA"})["alert"],
        create(api, {"condition": "volume", "symbol": "FIXA", "multiple": 2.5})["alert"],
        create(api, {"condition": "scanner", "symbol": "FIXA", "stage": "BREAKOUT"})["alert"],
        create(api, {"condition": "sector", "index": "Nifty IT", "threshold_pct": 2})["alert"],
        create(api, {"condition": "risk", "symbol": "FIXA", "level": 5})["alert"],
    ]
    assert [a["label"] for a in made] == [
        "FIXA: a new exchange filing",
        "Any company: a new results filing",
        "FIXA: a new bulk or block deal",
        "FIXA: volume at 2.5× its 20-session average",
        "FIXA: enters the scanner's picks as breakout",
        "Nifty IT: moves 2% or more in a session",
        "FIXA: 14-session ATR at 5% of price or more",
    ]
    assert made[1]["symbol"] is None and made[5]["params"] == {"index": "Nifty IT", "threshold_pct": 2.0, "direction": "either"}
    assert all(a["status"] == "active" and a["reason"] is None and a["rule"] for a in made)
    assert {d["user_id"] for d in world.db.alerts.docs} == {"user_a"}
    # another user sees none of them and cannot delete one
    assert listing(api, B)["alerts"] == []
    assert api.delete(f"{URL}/{made[0]['id']}", headers=B).status_code == 404


def test_the_same_active_alert_twice_is_409_duplicate_but_another_user_may_have_it(api, world):
    create(api, {"condition": "volume", "symbol": "FIXA", "multiple": 2.5})
    r = api.post(URL, json={"condition": "volume", "symbol": "FIXA", "multiple": 2.5}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "duplicate_alert")
    create(api, {"condition": "volume", "symbol": "FIXA", "multiple": 3})            # another level is another alert
    create(api, {"condition": "volume", "symbol": "FIXA", "multiple": 2.5}, who=B)   # another owner
    r = api.post(URL, json={"symbol": "FIXA", "condition": "above", "level": 105}, headers=A)
    assert r.status_code == 201
    r = api.post(URL, json={"symbol": "FIXA", "condition": "above", "level": 105.0}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "duplicate_alert")


def test_the_50_active_limit_covers_every_condition(api, world):
    for i in range(50):
        world.db.alerts.docs.append({**alerts_svc.new_alert("user_a", {"condition": "risk", "symbol": "FIXA", "level": 1 + i * 0.1}, NOW),
                                     "_id": f"r{i}"})
    r = api.post(URL, json={"condition": "filing", "symbol": "FIXA"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "active_alert_limit")


# ── each condition fires once, with its reason ───────────────────────────────
def test_a_filing_alert_fires_on_the_first_filing_after_it_was_made(api, world):
    a = create(api, {"condition": "filing", "symbol": "FIXA"})["alert"]
    hi = create(api, {"condition": "filing", "symbol": "FIXA", "impact": "high"})["alert"]
    world.filings = [
        # filed before the alert (10:00 IST < 10:30 IST): old news, never fires
        {"announcement_id": "f0", "source": "NSE_ANN", "ticker_symbol": "FIXA", "subject": "Old outcome", "filed_at": "2026-10-12T04:30:00+00:00",
         "event_category": "earnings", "impact_score": "high", "attachment_url": "https://nsearchives.nseindia.com/f0.pdf"},
        {"announcement_id": "f2", "source": "BSE_ANN", "ticker_symbol": "FIXA", "subject": "Copy of the outcome", "filed_at": "2026-10-13T09:02:00+00:00",
         "event_category": None, "impact_score": None, "attachment_url": None},
        {"announcement_id": "f1", "source": "NSE_ANN", "ticker_symbol": "FIXA", "subject": "Outcome of Board Meeting", "filed_at": "2026-10-13T09:00:00+00:00",
         "event_category": "earnings", "impact_score": "medium", "attachment_url": "https://nsearchives.nseindia.com/f1.pdf"},
        {"announcement_id": "f3", "source": "NSE_ANN", "ticker_symbol": "FIXA", "subject": "Order win", "filed_at": "2026-10-14T06:00:00+00:00",
         "event_category": "orders", "impact_score": "high", "attachment_url": None},
    ]
    body = listing(api)
    got = by_id(body)
    # the earliest after the alert: the NSE copy at 14:30 IST; its BSE twin two minutes later does not fire it again
    assert got[a["id"]]["status"] == "fired" and got[a["id"]]["fired_session"] == "2026-10-13"
    assert got[a["id"]]["reason"] == "FIXA filed “Outcome of Board Meeting” with NSE at 14:30 IST on 13 Oct 2026."
    assert got[a["id"]]["evidence"]["announcement_id"] == "f1" and got[a["id"]]["evidence"]["url"].endswith("f1.pdf")
    # "high" only: the first high-impact filing after the alert, said to be an AI label
    assert got[hi["id"]]["reason"] == ("FIXA filed “Order win” with NSE at 11:30 IST on 14 Oct 2026. "
                                       "The classifier rated it high impact (an AI label).")
    writes = world.db.alerts.writes
    listing(api)
    assert world.db.alerts.writes == writes                              # fired once


def test_a_category_alert_for_any_company_and_a_deal_alert(api, world):
    cat = create(api, {"condition": "category", "category": "orders"})["alert"]
    deal = create(api, {"condition": "category", "category": "deal", "symbol": "FIXB"})["alert"]
    world.filings = [{"announcement_id": "o1", "source": "NSE_ANN", "ticker_symbol": "FIXZ", "subject": "Bagging of orders",
                      "filed_at": "2026-10-12T10:00:00+00:00", "event_category": "orders", "impact_score": "medium", "attachment_url": None}]
    world.deals["bulk"] = [
        # dated the alert's own day: published after that close, but the rule counts from the next session
        {"as_of_date": "2026-10-12", "symbol": "FIXB", "client_name": "EARLY FUND", "deal_type": "BUY", "quantity": 1000, "avg_price": 10.0, "deal_seq": 1},
        {"as_of_date": "2026-10-13", "symbol": "FIXB", "client_name": "FIXTURE FUND", "deal_type": "SELL", "quantity": 250000, "avg_price": 98.5,
         "deal_seq": 1, "pct_of_shares": 0.5},
    ]
    got = by_id(listing(api))
    assert got[cat["id"]]["reason"] == ("FIXZ filed “Bagging of orders” with NSE at 15:30 IST on 12 Oct 2026. "
                                        "The classifier labelled it Order (an AI label).")
    assert got[deal["id"]]["reason"] == ("FIXTURE FUND sold 250,000 shares of FIXB at ₹98.50 in a bulk deal on 13 Oct 2026 "
                                         "(NSE's own deal disclosure).")
    assert got[deal["id"]]["evidence"]["pct_of_shares"] == 0.5


def test_a_volume_alert_fires_at_the_multiple_of_the_20_session_average(api, world):
    days = sessions(date(2026, 10, 12), 21)                              # 20 sessions to 9 Oct, then 12 Oct
    world.bars["FIXA"] = [bar(d, 101, 99, 100, 1000) for d in days]
    a = create(api, {"condition": "volume", "symbol": "FIXA", "multiple": 2.5})["alert"]
    world.bars["FIXA"].append(bar("2026-10-13", 101, 99, 100, 2400))   # 2.4×: not yet
    got = by_id(listing(api))
    assert got[a["id"]]["status"] == "active" and got[a["id"]]["checked_through"] == "2026-10-13"
    world.bars["FIXA"].append(bar("2026-10-14", 101, 99, 100, 2900))   # base now 19 × 1,000 + 2,400 → 1,070 → 2.71×
    got = by_id(listing(api))
    assert got[a["id"]]["status"] == "fired" and got[a["id"]]["fired_session"] == "2026-10-14"
    assert got[a["id"]]["reason"] == ("FIXA traded 2,900 shares on 14 Oct 2026, 2.7× its average of 1,070 over the "
                                      "20 sessions before (your level: 2.5×).")


def test_a_volume_alert_without_20_sessions_before_is_not_fired(api, world):
    world.bars["FIXA"] = [bar(d, 101, 99, 100, 1000) for d in sessions(date(2026, 10, 12), 5)]
    a = create(api, {"condition": "volume", "symbol": "FIXA", "multiple": 2})["alert"]
    world.bars["FIXA"].append(bar("2026-10-13", 101, 99, 100, 99000))
    assert by_id(listing(api))[a["id"]]["status"] == "active"


def test_a_risk_alert_fires_when_the_atr_percent_reaches_the_level(api, world):
    world.bars["FIXA"] = [bar(d, 103, 97, 100) for d in sessions(date(2026, 10, 12), 20)]
    a = create(api, {"condition": "risk", "symbol": "FIXA", "level": 5})["alert"]
    b = create(api, {"condition": "risk", "symbol": "FIXA", "level": 7})["alert"]
    world.bars["FIXA"].append(bar("2026-10-13", 103, 97, 100))
    got = by_id(listing(api))
    assert got[a["id"]]["reason"] == "FIXA's 14-session ATR reached 6.00% of its close on 13 Oct 2026 (your level: 5%)."
    assert got[a["id"]]["evidence"]["atr_pct"] == 6.0
    assert got[b["id"]]["status"] == "active"


def test_a_scanner_alert_fires_on_a_later_signal_date_in_the_stage(api, world):
    any_stage = create(api, {"condition": "scanner", "symbol": "FIXA"})["alert"]
    brk = create(api, {"condition": "scanner", "symbol": "FIXA", "stage": "BREAKOUT"})["alert"]
    world.signals = [
        {"nse_symbol": "FIXA", "signal_date": date(2026, 10, 12), "stage": "BREAKOUT", "final_score": 0.9},   # the alert's own day
        {"nse_symbol": "FIXA", "signal_date": date(2026, 10, 13), "stage": "ACCUMULATION", "final_score": 0.61},
        {"nse_symbol": "FIXA", "signal_date": date(2026, 10, 14), "stage": "BREAKOUT", "final_score": 0.74},
    ]
    got = by_id(listing(api))
    assert got[any_stage["id"]]["reason"] == "FIXA entered the scanner's picks on 13 Oct 2026 as accumulation (score 0.61)."
    assert got[brk["id"]]["reason"] == "FIXA entered the scanner's picks on 14 Oct 2026 as breakout (score 0.74)."


def test_a_scanner_alert_is_not_checked_when_the_picks_cannot_be_read(api, world):
    a = create(api, {"condition": "scanner", "symbol": "FIXA"})["alert"]
    world.pg = False
    body = listing(api)
    assert by_id(body)[a["id"]]["status"] == "active" and by_id(body)[a["id"]]["check_error"] == "source_unavailable"
    assert body["check_errors"] == ["source_unavailable"]


def test_a_sector_alert_fires_on_the_session_the_index_moved_past_the_threshold(api, world):
    either = create(api, {"condition": "sector", "index": "Nifty IT", "threshold_pct": 2})["alert"]
    up = create(api, {"condition": "sector", "index": "Nifty IT", "threshold_pct": 2, "direction": "up"})["alert"]
    world.index["Nifty IT"] = [{"as_of_date": "2026-10-14", "close_price": 98.0}, {"as_of_date": "2026-10-13", "close_price": 101.5},
                               {"as_of_date": "2026-10-12", "close_price": 100.0}]
    got = by_id(listing(api))
    assert got[either["id"]]["reason"] == ("Nifty IT fell 3.45% on 14 Oct 2026 (close 98.00 against 101.50; "
                                           "your threshold: 2% either way).")
    assert got[up["id"]]["status"] == "active" and got[up["id"]]["checked_through"] == "2026-10-14"


def test_a_source_that_fails_leaves_its_alerts_active_and_says_so(api, world):
    a = create(api, {"condition": "filing", "symbol": "FIXA"})["alert"]
    world.fail.add("/announcements")
    body = listing(api)
    assert by_id(body)[a["id"]]["status"] == "active" and by_id(body)[a["id"]]["check_error"] == "source_unavailable"


def test_a_price_alert_now_carries_its_reason(api, world):
    world.bars["FIXA"] = [bar("2026-10-09", 102, 98, 100), bar("2026-10-12", 104, 94, 101)]
    a = create(api, {"symbol": "FIXA", "condition": "above", "level": 105})["alert"]
    world.bars["FIXA"].append(bar("2026-10-13", 106.5, 99, 105))
    got = by_id(listing(api))[a["id"]]
    assert (got["status"], got["fired_session"], got["fired_price"]) == ("fired", "2026-10-13", 105.0)
    assert got["reason"] == "FIXA's high of ₹106.50 on 13 Oct 2026 reached your level of ₹105.00."


def test_the_list_names_every_condition_and_says_delivery_is_in_app(api, world):
    body = listing(api)
    assert [c["condition"] for c in body["conditions"]] == ["above", "below", "filing", "category", "volume", "scanner", "sector", "risk"]
    assert body["delivery"] == "in_app" and "in-app" in body["check_note"]
    assert "deal" in [c["key"] for c in body["categories"]]


def test_the_sector_list_matches_the_desk_sector_indices():
    from nidp.services.daas_api.routers.desk_market import SECTOR_INDICES
    assert alerts_svc.SECTOR_INDEX_NAMES == tuple(name for name, _ in SECTOR_INDICES)


# ── the evening script ───────────────────────────────────────────────────────
def test_the_script_fires_every_kind_once_and_a_rerun_changes_nothing(api, world):
    from scripts import check_desk_alerts as script

    world.bars["FIXA"] = [bar(d, 103, 97, 100) for d in sessions(date(2026, 10, 12), 21)]
    create(api, {"condition": "risk", "symbol": "FIXA", "level": 5})
    create(api, {"symbol": "FIXA", "condition": "above", "level": 103.5}, who=B)
    create(api, {"condition": "sector", "index": "Nifty IT", "threshold_pct": 1}, who=B)
    world.bars["FIXA"].append(bar("2026-10-13", 104, 97, 100))
    world.index["Nifty IT"] = [{"as_of_date": "2026-10-12", "close_price": 100.0}, {"as_of_date": "2026-10-13", "close_price": 102.0}]
    world.calls.clear()
    out = asyncio.run(script.run(world.db))
    assert out["alerts_fired"] == 3 and out["alerts_fired_by_condition"] == {"risk": 1, "above": 1, "sector": 1}
    assert out["alerts_not_checked"] == 0
    assert world.calls.count("/prices/eod/FIXA") == 1                      # one bar read for the risk and the price alert
    assert {d["status"] for d in world.db.alerts.docs} == {"fired"} and all(d["reason"] for d in world.db.alerts.docs)
    writes = world.db.alerts.writes
    again = asyncio.run(script.run(world.db))
    assert again["alerts_fired"] == 0 and world.db.alerts.writes == writes


def test_the_script_dry_run_writes_nothing(api, world):
    from scripts import check_desk_alerts as script

    create(api, {"condition": "category", "category": "earnings"})
    world.filings = [{"announcement_id": "e1", "source": "NSE_ANN", "ticker_symbol": "FIXQ", "subject": "Results",
                      "filed_at": "2026-10-13T10:00:00+00:00", "event_category": "earnings", "impact_score": None, "attachment_url": None}]
    writes = world.db.alerts.writes
    out = asyncio.run(script.run(world.db, dry_run=True))
    assert out["alerts_fired"] == 1 and world.db.alerts.writes == writes
    assert {d["status"] for d in world.db.alerts.docs} == {"active"}
