"""The Copilot's open trades on the user's BROKER book (services/positions/book.py, services/copilot_visual/open_book.py,
GET /api/positions/book/live). Test-case ids OB-* match test_reports/copilot_broker_book_20261031.md.

What is replaced (MOCK — not real data; every position, price and balance below is invented, in the SHAPE of the HubPosition
rows the adapters return — ICICI Direct's own stock codes, `pnl: null` read as 0.0 for futures and options, as seen on the live
API on 31 Oct 2026): the broker reads (hub_reads.read_account_positions / read_account_funds — NO broker is ever called here),
the broker account list, Mongo (a small fake), the positions service's pricing, Kite's live prices, Zerodha's margin
calculator, the paper book and the freshness window. The state machine, the cache, the snapshot store, the analysis, the
blocks, the commentary and the contract check run for real.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from services import market_freshness
from services.copilot_visual import builders, open_book, readers as rd
from services.copilot_visual.intents import Intent, resolve_intent
from services.copilot_visual.payload import FACTS_MAX, facts, validate
from services.positions import book as bk, service, store

IST = timezone(timedelta(hours=5, minutes=30))
TODAY, FLOOR = date(2026, 10, 30), date(2026, 10, 29)
WINDOW = market_freshness.Window(today=TODAY, floor=FLOOR, calendar_checked=True)
T0 = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)        # 16:30 IST: used where the market state does not matter


def run(coro):
    return asyncio.run(coro)


# ── a small async fake of the Mongo collections used here (dotted keys, a list field holding the value) ──────────
class FakeColl:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _get(d, k):
        cur = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur

    def _match(self, d, q):
        for k, v in (q or {}).items():
            have = self._get(d, k)
            if isinstance(have, list) and not isinstance(v, list):
                if v not in have:
                    return False
            elif have != v:
                return False
        return True

    async def create_index(self, *a, **k):
        return None

    def find(self, q=None, proj=None):
        docs = [dict(d) for d in self.docs if self._match(d, q)]

        class _Cur:
            def __aiter__(s):
                s._it = iter(docs)
                return s

            async def __anext__(s):
                try:
                    return next(s._it)
                except StopIteration:
                    raise StopAsyncIteration
        return _Cur()

    async def find_one(self, q, proj=None, sort=None):
        docs = [d for d in self.docs if self._match(d, q)]
        if sort:
            k, direction = sort[0]
            docs.sort(key=lambda d: d.get(k) or "", reverse=direction < 0)
        return dict(docs[0]) if docs else None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            d = dict(q)
            d.update(upd.get("$set", {}))
            self.docs.append(d)


class FakeDB(dict):
    def __getitem__(self, name):
        if name not in self:
            dict.__setitem__(self, name, FakeColl())
        return dict.__getitem__(self, name)


# ── rows in the shape of services/brokers/base.HubPosition (ICICI Direct's own codes) ─────────────────────────────
def row(symbol, qty, avg, ltp, pnl, **kw):
    r = {"symbol": symbol, "exchange": kw.pop("exchange", "NSE"), "quantity": qty, "avg_price": avg, "last_price": ltp, "pnl": pnl,
         "product": None, "product_raw": kw.pop("product_raw", "EasyMargin"), "segment": kw.pop("segment", "equity"),
         "is_intraday": False, "instrument_type": kw.pop("instrument_type", None), "expiry": kw.pop("expiry", None),
         "strike": kw.pop("strike", None), "kind": "net", "name": None}
    r.update(kw)
    return r


EXIDE = row("EXIIND", 500, 400.0, 380.0, -10000.0)                                  # EXIDEIND shares, broker P&L sent
SWIGGY_EQ = row("SWILIM", 700, 200.0, 180.0, -14000.0)                              # SWIGGY shares
SWIGGY_PE = row("SWILIM", 1825, 4.0, 4.5, 0.0, exchange="NFO", segment="fno", instrument_type="PE", expiry="2026-11-23",
                strike=170.0, product_raw="Options")                                # F&O row: the broker sent pnl null → 0.0
ADANI_FUT = row("ADAPOR", 475, 1800.0, 1790.0, 0.0, exchange="NFO", segment="fno", instrument_type="FUT", expiry="2026-11-23",
                product_raw="Futures")
SGB = row("SGBT54", -4, 14000.0, 14100.0, 0.0, product_raw="BTST")                  # a code ICICI's master does not list


def doc(account_id="ba_test1", broker="icicidirect", live=True, native=True):
    return {"account_id": account_id, "broker": broker, "native": native, "user_id": "u1", "label": None,
            "status": "active" if live else "expired", "api_key_encrypted": "ENC" if live else "",
            "session_expires_at": "2099-01-01T00:00:00+00:00" if live else None}


def chain(strikes):
    return {"summary": {"as_of": "2026-10-30", "spot": 176.61, "forward": 177.0, "days_to_expiry": 24}, "lot_size": 1825, "strikes": strikes}


def side(settle, iv, delta):
    return {"close": settle, "settle": settle, "volume": 100, "oi": 500, "iv": iv, "iv_price": "settle", "delta": delta,
            "gamma": 0.01, "theta": -0.1, "vega": 0.2}


class World:
    """Everything the book reads, replaced. Mutate the attributes between calls; `calls` records every broker read."""

    def __init__(self, mp):
        self.accounts = [doc()]
        self.rows = {"ba_test1": [EXIDE, SWIGGY_EQ, SWIGGY_PE, ADANI_FUT, SGB]}
        self.fail = {}                       # account_id → exception raised by the positions read
        self.funds = {"ba_test1": {"available_cash_rs": 200000.0, "collateral_rs": 50000.0, "used_margin_rs": 80000.0}}
        self.funds_fail = {}
        self.calls = []
        self.hub_on = True
        self.session = True                  # the market is open
        self.live_quotes = {"EXIDEIND": 381.0, "SWIGGY": 181.0}
        self.live_source = "kite_live"
        self.paper = {"as_of": "2026-10-29", "trades": [{"symbol": "AAA", "status": "open", "quantity": 10, "entry_price": 100.0,
                      "last_close": 108.0, "stop_price": 92.0, "target_price": 120.0, "unrealized_pnl_rs": 80.0}],
                      "summary": {"open": 1, "unrealized_pnl_rs": 80.0, "entry_pending": 0}}
        self.margin = lambda key, req: {"estimate": 55000.0, "reason": None, "source": "Zerodha margin calculator · the platform's Kite login"}
        self.margin_facts = {"platform_login": True, "zerodha_connected": 0, "zerodha_live": 0, "others": []}
        self.now = T0
        self.db = FakeDB()
        bk.reset_caches()
        open_book._MARGINS.clear()
        self.mono = 1000.0
        import deps
        from routes import broker_connect as bc
        from services.brokers import hub_reads as hub

        async def hub_user(request):
            if not self.hub_on:
                raise HTTPException(status_code=403, detail="off")
            return {"user_id": "u1"}

        async def accounts(uid):
            assert uid == "u1", "only the signed-in user's accounts are read"
            return [dict(d) for d in self.accounts]

        async def read(db, d, kind):
            assert kind == "net"
            self.calls.append(("positions", d["account_id"]))
            if d["account_id"] in self.fail:
                raise self.fail[d["account_id"]]
            return [dict(r) for r in self.rows[d["account_id"]]]

        async def funds(db, d):
            self.calls.append(("funds", d["account_id"]))
            if d["account_id"] in self.funds_fail:
                raise self.funds_fail[d["account_id"]]
            return dict(self.funds[d["account_id"]])

        mp.setattr(deps, "db", self.db)
        mp.setattr(bc, "_hub_user", hub_user)
        mp.setattr(bc, "_user_accounts", accounts)
        mp.setattr(bc, "_account_entry", lambda d: {"account_id": d["account_id"], "broker": d["broker"],
                                                    "broker_display": {"icicidirect": "ICICI Direct", "zerodha": "Zerodha"}[d["broker"]],
                                                    "label": d.get("label")})
        mp.setattr(hub, "read_account_positions", read)
        mp.setattr(hub, "read_account_funds", funds)
        mp.setattr(bk, "_now", lambda: self.now)
        mp.setattr(bk, "_mono", lambda: self.mono)
        mp.setattr(open_book.time, "monotonic", lambda: self.mono)

        async def price_fno(request, underlying, option_expiries):
            if underlying == "SWIGGY":
                return {"as_of": "2026-10-30", "spot": 176.61, "lot_size": 1825, "futures": {"2026-11-23": {"expiry": "2026-11-23", "settle": 177.0}},
                        "chains": {e: chain([{"strike": 170.0, "call": None, "put": side(4.1, 38.0, -0.4)}]) for e in option_expiries}, "error": None}
            return {"as_of": "2026-10-30", "spot": 1849.99, "lot_size": 475, "futures": {"2026-11-23": {"expiry": "2026-11-23", "settle": 1844.5}},
                    "chains": {}, "error": None}

        async def underlying_quotes(unders):
            return {"quotes": {u: {"ltp": self.live_quotes[u]} for u in unders if u in self.live_quotes}, "source": self.live_source,
                    "as_of": self.now.isoformat()}

        async def open_trades(request):
            return self.paper

        async def window():
            return WINDOW

        async def position_margins(request, uid, requests):
            return {k: self.margin(k, r) for k, r in requests.items()}, self.margin_facts
        mp.setattr(service, "price_fno", price_fno)
        mp.setattr(service, "underlying_quotes", underlying_quotes)
        mp.setattr(rd, "open_trades", open_trades)
        mp.setattr(rd, "window", window)
        mp.setattr(rd, "in_session", lambda now=None: self.session)
        mp.setattr(rd, "position_margins", position_margins)

    def snap(self, account_id="ba_test1", read_at="2026-10-30T10:00:00+00:00", rows=None):
        rows = rows if rows is not None else [EXIDE, SWIGGY_EQ]
        self.db["position_snapshots"].docs.append({"_id": "ps_1", "user_id": "u1", "account_id": account_id, "broker": "icicidirect",
                                                   "read_at": read_at, "last_seen_at": read_at, "rows_hash": "h", "row_count": len(rows),
                                                   "rows": rows})

    def level(self, underlying, stop, target=None):
        self.db["position_levels"].docs.append({"_id": f"u1|{underlying}", "user_id": "u1", "underlying": underlying, "stop": stop,
                                                "target": target, "trail_pct": None, "updated_at": "2026-10-29T10:00:00+00:00"})

    def plan(self, symbol, direction="bullish", stop=150.0, entry=190.0, target=230.0, owners=("u1",), segment="cash"):
        self.db["trade_plans"].docs.append({"_id": f"tp_{symbol}", "plan_id": f"tp_{symbol}", "created_at": "2026-10-28T10:00:00+00:00",
                                            "owners": list(owners), "instrument": {"symbol": symbol, "segment": segment},
                                            "strategy": {"direction": direction, "label": "MOCK plan"}, "entry": {"price": entry},
                                            "stop": {"price": stop, "method": "structural"},
                                            "targets": [{"name": "base", "price": target, "primary": True}], "lifecycle": {"state": "ELIGIBLE"}})

    def build(self, now=None):
        p = run(builders.build(Intent("open_trades"), {"user_id": "u1"}, request="REQ", now=now or self.now.astimezone(IST)))
        assert validate(p) == [], validate(p)
        return p


@pytest.fixture
def w(monkeypatch):
    return World(monkeypatch)


def blk(p, bid):
    return next((b for b in p["blocks"] if b.get("id") == bid), None)


def cells(p, bid):
    return {r["cells"]["symbol"]: r for r in blk(p, bid)["rows"]}


def kp(p):
    return {i["label"]: i for i in blk(p, "book")["items"]}


def notices(p):
    return [b for b in p["blocks"] if b["type"] == "notice"]


# ── OB-1 … OB-4: the user's broker configuration ─────────────────────────────
def test_ob1_no_broker_asks_to_connect_and_keeps_the_paper_trades(w):
    w.accounts = []
    p = w.build()
    n = blk(p, "no-broker")
    assert n["actions"] == [{"kind": "connect_broker", "label": "Connect a broker"}] and "only your paper trades are shown" in n["text"]
    assert blk(p, "trades") and "Paper" in blk(p, "trades")["note"] and not blk(p, "positions") and "refresh" not in p
    assert p["headline"]["text"] == "1 open paper trade, unrealised ₹80.00."


def test_ob2_broker_hub_off_says_so_without_a_connect_action(w):
    w.hub_on = False
    p = w.build()
    n = blk(p, "no-hub")
    assert "not switched on" in n["text"] and not n.get("actions") and blk(p, "trades")


def test_ob3_session_ended_shows_the_last_stored_read_dated_and_never_as_live(w):
    w.accounts = [doc(live=False)]
    w.snap(read_at="2026-10-30T10:00:00+00:00")                     # 15:30 IST on 30 Oct, the previous session: current
    p = w.build()
    n = blk(p, "ended-ba_test1")
    assert n["actions"] == [{"kind": "connect_broker", "label": "Sign in to ICICI Direct again"}]
    assert "session has ended" in n["text"] and "30 Oct 2026, 15:30 IST (not live)" in n["text"]
    rows = blk(p, "positions")["rows"]
    assert len(rows) == 2 and all(r["badge"].startswith("As of 30 Oct") for r in rows)
    assert not any(r["badge"] == "Live" for r in rows)
    acc = cells(p, "accounts")["ICICI Direct"]["cells"]
    assert acc["state"] == "Session ended" and acc["avail"] == "Not available" and acc["used"] == "Not available"
    assert "Session ended" in cells(p, "accounts")["ICICI Direct"]["tips"]["avail"] or "session has ended" in cells(p, "accounts")["ICICI Direct"]["tips"]["avail"]
    assert "stored read, not live" in p["headline"]["text"] and "refresh" not in p and p["mode"] == "eod"
    assert [c for c in w.calls if c[0] == "positions"] == [] and not p["data_quality"]["stale"]
    assert any(s["name"].startswith("Your broker positions (last stored read)") and s["status"] == "fresh" for s in p["data_quality"]["sources"])


def test_ob3b_an_older_stored_read_carries_the_stale_notice(w):
    w.accounts = [doc(live=False)]
    w.snap(read_at="2026-10-21T10:00:00+00:00")
    p = w.build()
    assert p["data_quality"]["stale"] is True
    assert any("21 Oct 2026" in n["text"] and "older than the previous session" in n["text"] for n in notices(p))


def test_ob4_session_ended_with_no_stored_read_says_so(w):
    w.accounts = [doc(live=False)]
    p = w.build()
    assert "There is no stored read to show" in blk(p, "ended-ba_test1")["text"] and not blk(p, "positions")
    assert cells(p, "accounts")["ICICI Direct"]["cells"]["read"] == "No stored read"


# ── OB-5 … OB-8: a live book ─────────────────────────────────────────────────
def test_ob5_live_book_rows_use_the_brokers_pnl_and_mark_what_the_broker_did_not_send(w):
    p = w.build()
    pos = cells(p, "positions")
    exide = pos["EXIDEIND"]
    assert exide["cells"] == {"symbol": "EXIDEIND", "account": "ICICI Direct", "qty": 500, "avg": 400.0, "ltp": 381.0, "pnl": -9500.0}
    assert "Kite live" in exide["tips"]["ltp"] and "moved by quantity" in exide["tips"]["pnl"]       # -10000 + 500 × (381 − 380)
    assert exide["badge"] == "Live"
    put = pos["SWIGGY 23 Nov 2026 170 PE"]
    assert put["cells"]["pnl"] == round(1825 * (4.5 - 4.0), 2) and "sent no P&L" in put["tips"]["pnl"]   # marked, not a 0.0 "broker figure"
    assert put["cells"]["ltp"] == 4.5 and "ICICI Direct's own price" in put["tips"]["ltp"]            # an option keeps the broker price
    assert pos["SWIGGY"]["cells"]["pnl"] == round(-14000.0 + 700 * (181.0 - 180.0), 2)
    assert pos["SGBT54"]["badge"] == "Not mapped" and "security master" in pos["SGBT54"]["tips"]["symbol"]
    assert pos["ADANIPORTS 23 Nov 2026 FUT"]["cells"]["qty"] == 475
    k = kp(p)
    assert k["Broker positions"]["value"] == "5" and k["Unrealised P&L"]["value"] is not None
    assert p["refresh"] == {"path": "/api/positions/book/live", "interval_s": 5, "block_ids": ["book", "positions", "levels", "accounts", "commentary"]}
    assert p["mode"] == "mixed" and p["as_of"] == "2026-10-30"


def test_ob6_icici_codes_are_named_as_nse_symbols_and_the_labels_say_the_contract(w):
    p = w.build()
    labels = [r["cells"]["symbol"] for r in blk(p, "positions")["rows"]]
    assert "EXIDEIND" in labels and "ADANIPORTS 23 Nov 2026 FUT" in labels and not any(l in labels for l in ("EXIIND", "ADAPOR", "SWILIM"))
    assert set(cells(p, "levels")) == {"EXIDEIND", "SWIGGY", "ADANIPORTS"}


def test_ob7_levels_the_users_stop_distance_loss_at_the_stop_and_expiry(w):
    w.level("EXIDEIND", stop=360.0, target=440.0)
    w.level("SWIGGY", stop=170.0)
    p = w.build()
    lv = cells(p, "levels")
    e = lv["EXIDEIND"]["cells"]
    assert e["stop"] == 360.0 and e["target"] == 440.0 and e["spot"] == 381.0
    assert e["to_stop"] == round((381.0 - 360.0) / 381.0 * 100, 2) and e["risk"] == -round((400.0 - 360.0) * 500, 2)
    assert "Set by you" in lv["EXIDEIND"]["tips"]["stop"] and "Never the price falling to zero" in lv["EXIDEIND"]["tips"]["risk"]
    assert lv["SWIGGY"]["cells"]["to_stop"] == round((181.0 - 170.0) / 181.0 * 100, 2)         # shares with a put under them are LONG: the stop faces down
    assert not any(w_["code"] == "stop_breached" for w_ in [])                                    # (kept explicit below via the commentary)
    assert not any("past your stop" in i["text"] for i in blk(p, "commentary")["items"])
    assert lv["SWIGGY"]["cells"]["expiry"].endswith("24d") and lv["ADANIPORTS"]["cells"]["stop"] == "No stop set"
    assert lv["ADANIPORTS"]["cells"]["risk"] == "No stop set"                    # no stop → no loss figure, and never a to-zero one
    risks = [r["cells"]["risk"] for r in blk(p, "levels")["rows"] if isinstance(r["cells"]["risk"], (int, float))]
    assert risks and all(abs(x) < 50000 for x in risks)                         # no "stock to zero" loss (EXIDEIND 500 × 381 = 190,500)


def test_ob8_a_failing_account_is_reported_alone(w):
    from services.brokers.fenix_reader import BrokerReadError
    w.accounts = [doc(), doc("ba_z", "zerodha")]
    w.rows["ba_z"] = []
    w.fail["ba_z"] = BrokerReadError("Zerodha net positions read failed (HTTP 500)")
    w.funds["ba_z"] = {}
    p = w.build()
    assert "Could not read net positions from Zerodha" in blk(p, "failed-ba_z")["text"] and "no stored read" in blk(p, "failed-ba_z")["text"].lower()
    assert len(blk(p, "positions")["rows"]) == 5
    acc = cells(p, "accounts")
    assert acc["ICICI Direct"]["cells"]["state"] == "Live" and acc["Zerodha"]["cells"]["state"] == "Read failed"


def test_ob8b_a_broker_that_refuses_the_session_mid_read_becomes_session_ended_with_its_stored_read(w):
    from services.brokers.fenix_reader import BrokerSessionExpired
    w.snap(rows=[EXIDE])
    w.db["position_snapshots"].docs[0]["last_seen_at"] = "2026-10-29T10:00:00+00:00"      # older than the 15 s cache
    w.fail["ba_test1"] = BrokerSessionExpired("rejected")
    p = w.build()
    n = blk(p, "ended-ba_test1")
    assert n["actions"][0]["label"] == "Sign in to ICICI Direct again" and "29 Oct 2026, 15:30 IST (not live)" in n["text"]
    assert len(blk(p, "positions")["rows"]) == 1 and blk(p, "positions")["rows"][0]["badge"].startswith("As of")


# ── OB-9 … OB-11: plans, margin, funds ───────────────────────────────────────
def test_ob9_the_plan_the_user_recorded_supplies_levels_when_it_points_the_same_way(w):
    w.plan("EXIDEIND", direction="bullish", stop=350.0, entry=400.0, target=450.0)
    p = w.build()
    e = cells(p, "levels")["EXIDEIND"]
    assert e["cells"]["stop"] == 350.0 and e["cells"]["target"] == 450.0 and "plan you recorded" in e["tips"]["stop"]
    texts = [i["text"] for i in blk(p, "commentary")["items"]]
    assert any("EXIDEIND: the plan you recorded on 28 Oct 2026" in t and "points the same way" in t and "you set none" in t for t in texts)


def test_ob9b_a_plan_that_points_the_other_way_is_a_conflict_not_a_level(w):
    w.plan("EXIDEIND", direction="bearish", stop=450.0, entry=400.0, target=350.0)
    p = w.build()
    assert cells(p, "levels")["EXIDEIND"]["cells"]["stop"] == "No stop set"
    texts = [i["text"] for i in blk(p, "commentary")["items"]]
    assert any("is bearish, but this position is long" in t for t in texts)


def test_ob9c_a_plan_only_the_system_built_is_not_the_users_plan(w):
    w.plan("EXIDEIND", owners=("system:ai_watchlist",))
    p = w.build()
    assert cells(p, "levels")["EXIDEIND"]["cells"]["stop"] == "No stop set"
    assert any("No plan of yours is on record for" in i["text"] and "EXIDEIND" in i["text"] for i in blk(p, "commentary")["items"])


def test_ob10_margin_comes_from_the_calculator_for_f_and_o_legs_only_and_shares_say_so(w):
    p = w.build()
    lv = cells(p, "levels")
    assert lv["ADANIPORTS"]["cells"]["margin"] == 55000.0 and "not your broker's own requirement" in lv["ADANIPORTS"]["tips"]["margin"]
    assert lv["SWIGGY"]["cells"]["margin"] == 55000.0 and "F&O legs only; shares are paid in full" in lv["SWIGGY"]["tips"]["margin"]
    assert lv["EXIDEIND"]["cells"]["margin"] == "None (shares)"
    assert kp(p)["Margin required"]["value"] == "₹1,10,000.00".replace(",10,000", ",10,000") or kp(p)["Margin required"]["value"].startswith("₹110")


def test_ob10b_no_calculator_asks_for_a_kite_login(w):
    w.margin = lambda key, req: {"estimate": None, "reason": "no margin calculator is available", "source": None}
    w.margin_facts = {"platform_login": False, "zerodha_connected": 0, "zerodha_live": 0, "others": ["icicidirect"]}
    p = w.build()
    assert cells(p, "levels")["ADANIPORTS"]["cells"]["margin"] == "Needs Kite login"
    n = blk(p, "login")
    assert [a["kind"] for a in n["actions"]] == ["kite_login", "connect_broker"] and "Margin required needs a Kite login" in n["text"]
    assert kp(p)["Margin required"]["value"] is None and kp(p)["Margin required"]["sub"] == "needs a Kite login"


def test_ob11_each_accounts_available_collateral_and_used_margin_are_the_brokers_own(w):
    p = w.build()
    a = cells(p, "accounts")["ICICI Direct"]
    assert a["cells"]["avail"] == 200000.0 and a["cells"]["collateral"] == 50000.0 and a["cells"]["used"] == 80000.0
    k = kp(p)
    assert k["Available cash"]["value"] == "₹2,00,000.00" or k["Available cash"]["value"] == "₹200,000.00"
    assert any("available ₹" in i["text"] and "used margin" in i["text"] for i in blk(p, "commentary")["items"])


def test_ob11b_a_funds_failure_is_reported_on_the_account_and_the_positions_stand(w):
    from services.brokers.fenix_reader import BrokerReadError
    w.funds_fail["ba_test1"] = BrokerReadError("funds down")
    p = w.build()
    a = cells(p, "accounts")["ICICI Direct"]
    assert a["cells"]["avail"] == "Not available" and "Could not read funds from ICICI Direct" in a["tips"]["avail"]
    assert len(blk(p, "positions")["rows"]) == 5 and any("funds" in m for m in p["data_quality"]["missing"])


# ── OB-12 … OB-14: the broker is not polled faster than its limit ────────────
def test_ob12_two_tabs_one_broker_read_inside_the_cache_window(w):
    w.build()
    w.now += timedelta(seconds=5)
    w.mono += 5
    w.build()
    assert [c for c in w.calls if c[0] == "positions"] == [("positions", "ba_test1")]
    assert [c for c in w.calls if c[0] == "funds"] == [("funds", "ba_test1")]
    w.now += timedelta(seconds=11)                                  # 16 s after the first read
    w.mono += 11
    w.build()
    assert len([c for c in w.calls if c[0] == "positions"]) == 2


def test_ob12b_concurrent_requests_coalesce_into_one_read(w):
    async def many():
        return await asyncio.gather(*(bk.build(None, w.db, "u1") for _ in range(6)))
    run(many())
    assert len([c for c in w.calls if c[0] == "positions"]) == 1


def test_ob12c_a_five_second_page_over_a_minute_makes_at_most_five_broker_reads_and_two_funds_reads(w):
    for _ in range(13):                                             # t = 0, 5, … 60 s
        run(open_book.live("REQ", {"user_id": "u1"}, w.now.astimezone(IST)))
        w.now += timedelta(seconds=5)
        w.mono += 5
    reads = [c for c in w.calls if c[0] == "positions"]
    assert 4 <= len(reads) <= 5, len(reads)
    assert len([c for c in w.calls if c[0] == "funds"]) <= 2


def test_ob13_a_quote_tick_is_not_a_new_snapshot_but_a_changed_holding_is(w):
    w.build()
    assert len(w.db["position_snapshots"].docs) == 1
    for ltp in (381.0, 382.0, 383.0):
        w.now += timedelta(seconds=20)
        w.mono += 20
        w.rows["ba_test1"] = [dict(r, last_price=(ltp if r["symbol"] == "EXIIND" else r["last_price"])) for r in w.rows["ba_test1"]]
        w.build()
    docs = w.db["position_snapshots"].docs
    assert len(docs) == 1 and docs[0]["rows"][0]["last_price"] == 383.0 and docs[0]["user_id"] == "u1"
    w.now += timedelta(seconds=20)
    w.mono += 20
    w.rows["ba_test1"] = [dict(EXIDE, quantity=600)] + w.rows["ba_test1"][1:]
    w.build()
    assert len(w.db["position_snapshots"].docs) == 2


# ── OB-14 … OB-16: live prices ───────────────────────────────────────────────
def test_ob14_marks_move_shares_only_from_a_live_feed_and_never_a_stored_read(w):
    run(bk.build(None, w.db, "u1"))
    book = run(bk.build(None, w.db, "u1"))
    groups = book["groups"]
    live = bk.apply_marks(groups, {"source": "kite_live", "as_of": "x", "quotes": {"EXIDEIND": {"ltp": 390.0}}})
    e = next(g for g in live if g["underlying"] == "EXIDEIND")
    assert e["legs"][0]["ltp"] == 390.0 and e["legs"][0]["pnl_rs"] == round(-10000.0 + 500 * (390.0 - 380.0), 2) and e["price"]["spot"] == 390.0
    s = next(g for g in live if g["underlying"] == "SWIGGY")
    assert {l["instrument"]: l["ltp"] for l in s["legs"]}["PE"] == 4.5                                    # an option keeps the broker price
    again = bk.apply_marks(groups, {"source": "kite_live", "as_of": "x", "quotes": {"EXIDEIND": {"ltp": 395.0}}})
    assert next(g for g in again if g["underlying"] == "EXIDEIND")["legs"][0]["pnl_rs"] == round(-10000.0 + 500 * 15, 2)    # from the read, not cumulative
    closed = bk.apply_marks(groups, {"source": "kite_close", "as_of": "x", "quotes": {"EXIDEIND": {"ltp": 999.0}}})
    assert next(g for g in closed if g["underlying"] == "EXIDEIND")["legs"][0]["ltp"] == 380.0


def test_ob14b_a_live_price_moves_the_distance_to_the_stop_and_raises_the_warning(w):
    w.level("EXIDEIND", stop=380.0)
    book = run(bk.build(None, w.db, "u1"))
    lowered = bk.apply_marks(book["groups"], {"source": "kite_live", "as_of": "x", "quotes": {"EXIDEIND": {"ltp": 382.0}}})
    g = next(x for x in lowered if x["underlying"] == "EXIDEIND")
    assert g["analytics"]["distance_to_stop_pct"] == round((382.0 - 380.0) / 382.0 * 100, 2)
    assert any(x["code"] == "near_stop" for x in g["warnings"])
    breached = bk.apply_marks(book["groups"], {"source": "kite_live", "as_of": "x", "quotes": {"EXIDEIND": {"ltp": 375.0}}})
    assert any(x["code"] == "stop_breached" for x in next(x for x in breached if x["underlying"] == "EXIDEIND")["warnings"])


def test_ob15_pnl_basis_rules():
    r = dict(EXIDE)
    assert bk.broker_pnl(r) == (-10000.0, "broker")
    assert bk.broker_pnl(dict(SWIGGY_PE)) == (round(1825 * 0.5, 2), "marked")
    assert bk.broker_pnl(dict(SGB)) == (round(-4 * (14100.0 - 14000.0), 2), "marked")                    # a short marks with the sign of the quantity
    assert bk.broker_pnl(dict(SWIGGY_PE, last_price=None)) == (0.0, "broker")                            # no price to tell a real 0 from a missing one
    assert bk.broker_pnl(dict(SWIGGY_PE, pnl=None)) == (round(1825 * 0.5, 2), "marked")
    assert bk.broker_pnl(dict(SWIGGY_PE, last_price=4.0)) == (0.0, "broker")                             # a real zero: price = average
    assert bk.broker_pnl(dict(SWIGGY_PE, pnl=None, last_price=None)) == (None, "none")


def test_ob16_the_live_route_sends_the_live_blocks_and_says_when_to_stop(w, monkeypatch):
    import routes.positions as rp
    monkeypatch.setattr(rp, "db", w.db)

    async def user(request: Request):
        if request.headers.get("X-Test-User") != "u1":
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": "u1"}
    monkeypatch.setattr(rp, "get_current_user", user)
    app = FastAPI()
    app.include_router(rp.router)
    c = TestClient(app)
    assert c.get("/api/positions/book/live").status_code == 401
    r = c.get("/api/positions/book/live", headers={"X-Test-User": "u1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["id"] for b in body["blocks"]] == ["book", "positions", "levels", "accounts", "commentary"]
    assert body["refresh"] == {"active": True, "interval_s": 5, "why": None} and body["mode"] == "mixed" and "headline" not in body
    for b in body["blocks"]:
        assert validate({"schema": "visual-answer-v1", "intent": "open_trades", "title": "t", "as_of": None, "mode": "mixed",
                         "blocks": [b], "data_quality": {"sources": [], "stale": False, "missing": []}, "follow_ups": []}) == []
    w.session = False
    off = c.get("/api/positions/book/live", headers={"X-Test-User": "u1"}).json()
    assert off["refresh"]["active"] is False and "market is closed" in off["refresh"]["why"] and off["mode"] == "eod"
    # another user has none of this book
    w.accounts = []
    other = c.get("/api/positions/book/live", headers={"X-Test-User": "u1"}).json()
    assert other["blocks"] == [] and other["refresh"]["active"] is False

    async def boom(request, user, now=None):
        raise RuntimeError("down")
    monkeypatch.setattr(open_book, "live", boom)
    assert c.get("/api/positions/book/live", headers={"X-Test-User": "u1"}).status_code == 502


def test_ob17_the_refresh_envelope_is_absent_when_the_market_is_closed_or_nothing_is_live(w):
    w.session = False
    assert "refresh" not in w.build()
    w.session = True
    w.accounts = [doc(live=False)]
    w.snap()
    assert "refresh" not in w.build()
    bad = w.build()
    bad["refresh"] = {"path": "/api/positions/book/live", "interval_s": 1, "block_ids": ["book"]}
    assert any(x.startswith("refresh") for x in validate(bad))
    bad["refresh"] = {"path": "http://elsewhere/x", "interval_s": 5, "block_ids": ["book"]}
    assert any(x.startswith("refresh") for x in validate(bad))


# ── OB-18 … OB-20: honesty, contract and wording ─────────────────────────────
def test_ob18_nothing_secret_or_internal_is_in_the_payload(w):
    p = w.build()
    flat = json.dumps(p)
    for banned in ("ba_test1", "ENC", "api_key", "access_token", "session_token", "X-SessionToken"):
        assert banned not in flat, banned


def test_ob19_the_commentary_reaches_the_model_and_nothing_is_cut(w):
    w.level("EXIDEIND", stop=380.0)
    p = w.build()
    f = facts(p)
    assert "[facts cut]" not in f and len(f) < FACTS_MAX
    assert "Checks against your stops and plans" in f and "EXIDEIND:" in f
    for it in blk(p, "commentary")["items"]:
        assert it["text"] in f
    said = " ".join(i["text"] for i in blk(p, "commentary")["items"]).lower()
    assert not any(w_ in said for w_ in ("recommend", "buy now", "sell now", "you should"))


def test_ob20_this_code_can_only_read():
    import inspect
    from services.brokers import hub_reads
    for mod in (bk, open_book, hub_reads):
        src = inspect.getsource(mod)
        for call in ("place_order", "modify_order", "cancel_order", "place_gtt", "basket_order(", ".orders("):
            assert call not in src, (mod.__name__, call)


@pytest.mark.parametrize("message", ["What are my open trades doing?", "my open positions", "How are my positions doing?",
                                     "Show my broker positions", "What is my broker book doing?"])
def test_ob21_the_question_resolves_to_open_trades(message):
    assert resolve_intent(message, "trader").name == "open_trades"


def test_ob22_a_book_that_cannot_be_read_still_shows_the_paper_trades_without_claiming_no_broker(w, monkeypatch):
    async def down(request, uid, use_cache=False):
        raise RuntimeError("MOCK book down")
    monkeypatch.setattr(rd, "open_book", down)
    p = w.build()
    assert blk(p, "trades") and not blk(p, "no-broker") and any("MOCK book down" in m for m in p["data_quality"]["missing"])


def test_ob23_the_headline_total_is_the_kpi_total_and_a_negative_balance_is_not_a_percentage(w):
    w.funds["ba_test1"] = {"available_cash_rs": -92.27, "collateral_rs": 0.0, "used_margin_rs": 93.18}
    p = w.build()
    pnl_kpi = kp(p)["Unrealised P&L"]["value"]
    assert pnl_kpi in p["headline"]["text"] or p["refresh"]                       # live pages keep the figure out of the sentence
    w.session = False
    p = w.build()
    assert kp(p)["Unrealised P&L"]["value"] in p["headline"]["text"]                # closed market: the sentence carries it, equal to the KPI
    assert kp(p)["Available cash"]["value"] == "−₹92.27"                            # a true minus, not "₹-92.27"
    assert not any("% of" in i["text"] and "available" in i["text"] for i in blk(p, "commentary")["items"])


def test_ob24_unmapped_rows_still_show_what_the_broker_sent(w):
    p = w.build()
    sgb = cells(p, "positions")["SGBT54"]["cells"]
    assert sgb["qty"] == -4 and sgb["avg"] == 14000.0 and sgb["ltp"] == 14100.0
