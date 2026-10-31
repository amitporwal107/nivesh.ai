"""Open Positions workspace — services/positions (symbols, analytics, store, service) and routes/positions.py.

Test-case ids match test_reports/r2_open_positions_20261031.md. Broker reads, pricing reads and Mongo are faked here;
the real-data checks are in that report. Every broker row below is shaped as services/brokers/base.HubPosition.
"""
from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from services import option_pricing
from services.positions import analytics, service, store, symbols
from services.positions.symbols import Contract


def run(coro):
    return asyncio.run(coro)


# ── a small async fake of the Mongo collections used here ────────────────────
class _Res(SimpleNamespace):
    pass


class FakeColl:
    def __init__(self):
        self.docs = []
        self.indexes = []

    @staticmethod
    def _match(d, q):
        return all(d.get(k) == v for k, v in (q or {}).items())

    async def create_index(self, keys, **kw):
        self.indexes.append((keys, kw))

    def find(self, q=None, proj=None):
        docs = [dict(d) for d in self.docs if self._match(d, q)]

        class _Cur:
            def __aiter__(self_inner):
                self_inner._it = iter(docs)
                return self_inner

            async def __anext__(self_inner):
                try:
                    return next(self_inner._it)
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
        return _Res(inserted_id=doc.get("_id"))

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                return _Res(matched_count=1)
        if upsert:
            d = dict(q)
            d.update(upd.get("$setOnInsert", {}))
            d.update(upd.get("$set", {}))
            self.docs.append(d)
        return _Res(matched_count=0)

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._match(d, q):
                self.docs.pop(i)
                return _Res(deleted_count=1)
        return _Res(deleted_count=0)


class FakeDB(dict):
    def __getitem__(self, name):
        if name not in self:
            dict.__setitem__(self, name, FakeColl())
        return dict.__getitem__(self, name)


@pytest.fixture(autouse=True)
def _fresh_indexes(monkeypatch):
    monkeypatch.setattr(store, "_indexed", False)


# ── PS: broker rows → NSE contracts ───────────────────────────────────────────
def row(symbol, qty, avg, **kw):
    r = {"symbol": symbol, "exchange": kw.pop("exchange", "NFO"), "quantity": qty, "avg_price": avg,
         "last_price": kw.pop("last_price", None), "pnl": kw.pop("pnl", 0.0), "product": "carryforward",
         "segment": kw.pop("segment", "fno"), "instrument_type": kw.pop("instrument_type", None),
         "expiry": kw.pop("expiry", None), "strike": kw.pop("strike", None), "kind": "net", "name": None}
    r.update(kw)
    return r


def test_ps1_icici_codes_map_through_icicis_own_master():
    fut = symbols.normalise(row("SONBLW", 1225, 890.0, instrument_type="FUT", expiry="2026-11-24"), "icicidirect")
    assert (fut.underlying, fut.instrument, fut.expiry, fut.mapped) == ("SONACOMS", "FUT", "2026-11-24", True)
    assert fut.key == "SONACOMS|2026-11-24|FUT"
    opt = symbols.normalise(row("CNXBAN", -30, 410.0, instrument_type="PE", expiry="2026-11-25", strike=54500), "icicidirect")
    assert (opt.underlying, opt.key) == ("BANKNIFTY", "BANKNIFTY|2026-11-25|54500|PE")
    eq = symbols.normalise(row("RELIND", 10, 1400.0, exchange="NSE", segment="equity"), "icicidirect")
    assert (eq.underlying, eq.instrument, eq.key) == ("RELIANCE", "EQ", "RELIANCE|EQ")
    bad = symbols.normalise(row("ZZZQQQ", 1, 1.0, instrument_type="FUT", expiry="2026-11-24"), "icicidirect")
    assert not bad.mapped and bad.key is None and "not in ICICI's security master" in bad.problem


def test_ps2_kite_symbols_monthly_weekly_and_futures():
    f = symbols.parse_zerodha("NIFTY26NOVFUT")
    assert (f.underlying, f.instrument, f.expiry, f.expiry_month) == ("NIFTY", "FUT", None, "2026-11")
    m = symbols.parse_zerodha("NIFTY26NOV23000CE")
    assert (m.underlying, m.instrument, m.strike, m.expiry_month) == ("NIFTY", "CE", 23000.0, "2026-11")
    w = symbols.parse_zerodha("NIFTY26N0322800PE")
    assert (w.underlying, w.instrument, w.strike, w.expiry) == ("NIFTY", "PE", 22800.0, "2026-11-03")
    assert symbols.parse_zerodha("M&M26NOVFUT").underlying == "M&M"
    assert symbols.parse_zerodha("NIFTYNXT5026NOVFUT").underlying == "NIFTYNXT50"
    assert symbols.parse_zerodha("RELIANCE") is None
    c = symbols.normalise(row("WHATEVER", 50, 10.0), "zerodha")
    assert not c.mapped and "not a recognised futures or options symbol" in c.problem


def test_ps3_a_monthly_kite_contract_takes_the_listed_futures_expiry_of_its_month():
    m = symbols.parse_zerodha("SONACOMS26NOV900CE")
    got = symbols.resolve_monthly(m, ["2026-11-24", "2026-12-29", "2027-01-26"])
    assert got.expiry == "2026-11-24" and got.key == "SONACOMS|2026-11-24|900|CE"
    none = symbols.resolve_monthly(m, ["2026-12-29"])
    assert not none.mapped and "expiry day is unknown" in none.problem


def test_ps4_labels_and_missing_contract_fields_are_flagged_not_guessed():
    assert symbols.label(Contract("NIFTY", "CE", expiry="2026-11-03", strike=23000.0)) == "NIFTY 3 Nov 2026 23000 CE"
    assert symbols.label(Contract("SONACOMS", "FUT", expiry="2026-11-24")) == "SONACOMS 24 Nov 2026 FUT"
    no_exp = symbols.normalise(row("NIFTY", 65, 100.0, instrument_type="CE", strike=23000), "upstox")
    assert not no_exp.mapped and "no expiry" in no_exp.problem
    no_strike = symbols.normalise(row("NIFTY", 65, 100.0, instrument_type="PE", expiry="2026-11-03"), "upstox")
    assert not no_strike.mapped and "no strike" in no_strike.problem


# ── AN: analytics ─────────────────────────────────────────────────────────────
def fut(sign, units, entry, mark):
    return {"kind": "future", "sign": sign, "units": units, "entry_price": entry, "mark": mark, "forward": mark}


def opt(option_type, strike, sign, units, entry, mark=None, forward=None, iv=None, days=None, **g):
    leg = {"kind": "option", "option_type": option_type, "strike": strike, "sign": sign, "units": units,
           "entry_price": entry, "mark": mark, "forward": forward, "iv": iv,
           "t": option_pricing.year_fraction(days) if days is not None else None, "days_to_expiry": days,
           "delta": None, "gamma": None, "theta": None, "vega": None}
    leg.update(g)
    return leg


def test_an1_a_long_future_shows_the_loss_at_the_stop_never_the_price_at_zero():
    legs = [fut(1, 1225, 868.0, 890.5)]
    a = analytics.analyse(legs, 890.5, {"stop": 824.6})
    p = a["payoff"]
    assert p["risk_basis"] == "stop" and p["max_loss"] is None
    assert p["pnl_at_stop_rs"] == round((824.6 - 868.0) * 1225, 2)
    assert p["loss_at_stop_rs"] == round((868.0 - 824.6) * 1225, 2)
    assert p["risk_to_stop_rs"] == round((890.5 - 824.6) * 1225, 2)     # from the current price down to the stop
    nostop = analytics.analyse(legs, 890.5, None)
    assert nostop["payoff"]["loss_at_stop_rs"] is None and nostop["payoff"]["max_loss"] is None
    assert [w["code"] for w in nostop["warnings"]] == ["no_stop"]


def test_an2_a_bull_call_spread_keeps_its_expiry_max_loss_and_breakeven():
    legs = [opt("call", 23000, 1, 65, 180.0), opt("call", 23500, -1, 65, 60.0)]
    p = analytics.analyse(legs, 23100.0, None)["payoff"]
    assert p["risk_basis"] == "expiry"
    assert p["max_loss"] == round(-(180.0 - 60.0) * 65, 2) and p["max_profit"] == round((500 - 120.0) * 65, 2)
    assert p["breakevens"] == [23120.0]


def test_an3_a_short_naked_call_is_unbounded_and_has_no_max_loss():
    p = analytics.analyse([opt("call", 23500, -1, 65, 60.0)], 23100.0, None)["payoff"]
    assert p["loss_unbounded"] and p["max_loss"] is None and p["risk_basis"] == "stop"


def test_an4_a_long_future_with_a_long_put_under_it_is_defined_risk():
    p = analytics.analyse([fut(1, 65, 23100.0, 23100.0), opt("put", 22900, 1, 65, 120.0)], 23100.0, None)["payoff"]
    assert p["risk_basis"] == "expiry" and p["max_loss"] == round(-(200 + 120.0) * 65, 2)


def test_an5_stop_and_target_warnings_for_long_and_short():
    long_ = [fut(1, 100, 1000.0, 1000.0)]
    near = analytics.analyse(long_, 1000.0, {"stop": 985.0, "target": 1100.0})
    assert near["distance_to_stop_pct"] == 1.5 and [w["code"] for w in near["warnings"]] == ["near_stop"]
    past = analytics.analyse(long_, 980.0, {"stop": 985.0})
    assert past["distance_to_stop_pct"] < 0 and past["warnings"][0]["code"] == "stop_breached"
    short = [fut(-1, 100, 1000.0, 1000.0)]
    s = analytics.analyse(short, 1000.0, {"stop": 1050.0, "target": 990.0})
    assert s["direction"] == "short" and s["distance_to_stop_pct"] == 5.0
    assert "near_stop" not in [w["code"] for w in s["warnings"]]
    hit = analytics.analyse(short, 985.0, {"stop": 1050.0, "target": 990.0})
    assert "target_reached" in [w["code"] for w in hit["warnings"]]


def test_an6_todays_valuation_at_the_spot_reproduces_the_marks():
    fwd, k, days, mark = 23150.0, 23000.0, 4, 230.0
    iv = option_pricing.implied_vol("CE", mark, fwd, k, option_pricing.year_fraction(days))
    legs = [opt("call", k, 1, 65, 180.0, mark=mark, forward=fwd, iv=iv, days=days)]
    assert math.isclose(analytics.today_pnl(legs, 23100.0, 23100.0), (mark - 180.0) * 65, abs_tol=0.05)
    up = analytics.today_pnl(legs, 23100.0 * 1.01, 23100.0)
    assert up > (mark - 180.0) * 65                    # a long call gains when the underlying rises


def test_an7_an_option_without_implied_volatility_gets_no_today_column():
    legs = [opt("call", 23000, 1, 65, 180.0, mark=230.0, forward=23150.0, iv=None, days=4)]
    rows = analytics.scenario(legs, 23100.0, (-1.0, 0.0, 1.0))
    assert all(r["today_pnl_rs"] is None for r in rows)
    assert [r["expiry_pnl_rs"] for r in rows] == [round(analytics.expiry_pnl(legs, 23100.0 * (1 + m / 100)), 2) for m in (-1, 0, 1)]


def test_an8_greeks_add_up_by_sign_and_units_and_are_none_when_a_leg_has_none():
    legs = [opt("call", 23000, 1, 65, 180.0, delta=0.55, gamma=0.0004, theta=-12.0, vega=9.0),
            opt("call", 23500, -1, 65, 60.0, delta=0.25, gamma=0.0003, theta=-7.0, vega=6.0), fut(1, 65, 23100.0, 23100.0)]
    g = analytics.greeks(legs)
    assert g == {"delta": round(65 * 0.55 - 65 * 0.25 + 65, 2), "gamma": round(65 * 0.0001, 6),
                 "theta": round(65 * (-12.0 + 7.0), 2), "vega": round(65 * 3.0, 2)}
    assert analytics.greeks([opt("call", 23000, 1, 65, 180.0)]) is None


def test_an9_expiry_soon_and_delivery_warning_for_stock_fno_only():
    legs = [fut(1, 1225, 868.0, 890.5)]
    stock = analytics.analyse(legs, 890.5, {"stop": 824.6}, days_to_expiry=1, physically_settled=True)
    assert {"expiry_soon", "physical_settlement"} <= {w["code"] for w in stock["warnings"]}
    index = analytics.analyse(legs, 890.5, {"stop": 824.6}, days_to_expiry=1, physically_settled=False)
    assert "physical_settlement" not in {w["code"] for w in index["warnings"]}
    later = analytics.analyse(legs, 890.5, {"stop": 824.6}, days_to_expiry=5, physically_settled=True)
    assert not {"expiry_soon", "physical_settlement"} & {w["code"] for w in later["warnings"]}


# ── ST: the user's levels and the snapshots ──────────────────────────────────
@pytest.mark.parametrize("body,why", [
    ({"stop": 100, "colour": "red"}, "unknown field"),
    ({"stop": "100"}, "must be a number"),
    ({"stop": True}, "must be a number"),
    ({"stop": 0}, "above zero"),
    ({"target": -5}, "above zero"),
    ({}, "set a stop"),
    ({"stop": None, "target": None, "trail_pct": None}, "set a stop"),
    ({"trail_pct": 60}, "at most 50"),
    ({"stop": 100, "target": 100}, "cannot be the same"),
])
def test_st1_level_bodies_are_validated(body, why):
    with pytest.raises(ValueError, match=why):
        store.validate_levels(body)


def test_st1b_a_valid_body():
    assert store.validate_levels({"stop": 824.6, "target": 957}) == {"stop": 824.6, "target": 957.0, "trail_pct": None}


def test_st2_a_trail_tightens_a_stop_and_never_loosens_it():
    lv = {"stop": 820.0, "trail_pct": 5.0, "peak": 900.0}
    assert store.effective_stop(lv, 880.0, "long") == 855.0          # 900 × 0.95 beats the fixed 820
    assert store.effective_stop({"stop": 870.0, "trail_pct": 5.0, "peak": 900.0}, 880.0, "long") == 870.0
    assert store.effective_stop({"stop": 1050.0, "trail_pct": 2.0, "trough": 1000.0}, 1010.0, "short") == 1020.0
    assert store.effective_stop({"stop": 820.0}, 880.0, "long") == 820.0


def test_st3_a_snapshot_is_stored_only_when_the_read_changes():
    db = FakeDB()
    rows = [row("SONBLW", 1225, 890.0, instrument_type="FUT", expiry="2026-11-24")]
    a = run(store.record_snapshot(db, user_id="u1", account_id="a1", broker="icicidirect", read_at="2026-10-31T04:00:00", rows=rows))
    b = run(store.record_snapshot(db, user_id="u1", account_id="a1", broker="icicidirect", read_at="2026-10-31T04:05:00", rows=rows))
    assert a == b and len(db[store.SNAPSHOTS].docs) == 1
    assert db[store.SNAPSHOTS].docs[0]["last_seen_at"] == "2026-10-31T04:05:00"
    assert db[store.SNAPSHOTS].docs[0]["broker_as_of"] is None       # brokers send no time for the book
    c = run(store.record_snapshot(db, user_id="u1", account_id="a1", broker="icicidirect", read_at="2026-10-31T04:10:00",
                                  rows=rows + [row("NIFTY", 65, 100.0, instrument_type="CE", expiry="2026-11-03", strike=23000)]))
    assert c != a and len(db[store.SNAPSHOTS].docs) == 2


def test_st4_save_and_delete_levels():
    db = FakeDB()
    doc = run(store.save_levels(db, "u1", "SONACOMS", {"stop": 824.6, "target": 957.0, "trail_pct": None}))
    assert doc["_id"] == "u1|SONACOMS" and doc["stop"] == 824.6 and doc["created_at"]
    assert run(store.read_levels(db, "u1"))["SONACOMS"]["target"] == 957.0
    assert run(store.delete_levels(db, "u1", "SONACOMS")) and not run(store.delete_levels(db, "u1", "SONACOMS"))


# ── SV: grouping, pricing and the summary ────────────────────────────────────
def chain_for(strikes, spot=23100.0, forward=23150.0, days=4, as_of="2026-10-30", lot=65):
    return {"summary": {"as_of": as_of, "spot": spot, "forward": forward, "days_to_expiry": days},
            "lot_size": lot, "strikes": strikes}


def side(settle, iv, delta=0.5, gamma=0.0004, theta=-10.0, vega=8.0, volume=1000, oi=5000):
    return {"close": settle, "settle": settle, "volume": volume, "oi": oi, "iv": iv, "iv_price": "settle",
            "delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def broker_row(symbol, qty, avg, broker="icicidirect", **kw):
    r = row(symbol, qty, avg, **kw)
    r.update(_account_id="a1", _broker=broker, _broker_display="ICICI Direct", _read_at="2026-10-31T04:00:00+00:00")
    return r


@pytest.fixture
def priced(monkeypatch):
    calls = []

    async def price_fno(request, underlying, option_expiries):
        calls.append((underlying, tuple(option_expiries)))
        if underlying == "STALE":
            return {"as_of": None, "spot": None, "lot_size": None, "futures": {}, "chains": {},
                    "error": "No current data for STALE F&O: the latest is 2026-10-20, older than the previous session"}
        chains = {e: chain_for([{"strike": 23000.0, "call": side(230.0, 14.0, 0.55), "put": side(80.0, 15.0, -0.45)},
                                {"strike": 23500.0, "call": side(60.0, 13.5, 0.25), "put": None}]) for e in option_expiries}
        return {"as_of": "2026-10-30", "spot": 23100.0, "lot_size": 65,
                "futures": {"2026-11-24": {"expiry": "2026-11-24", "settle": 23180.0, "close": 23175.0}},
                "chains": chains, "error": None}
    monkeypatch.setattr(service, "price_fno", price_fno)
    return calls


def test_sv1_broker_rows_group_by_nse_underlying_with_the_brokers_pnl(priced):
    rows = [broker_row("NIFTY", 65, 180.0, instrument_type="CE", expiry="2026-11-03", strike=23000, pnl=3250.0, last_price=230.0),
            broker_row("NIFTY", -65, 70.0, instrument_type="CE", expiry="2026-11-03", strike=23500, pnl=650.0, last_price=60.0),
            broker_row("ZZZQQQ", 10, 5.0, instrument_type="FUT", expiry="2026-11-24", pnl=-20.0)]
    db = FakeDB()
    groups = run(service.broker_groups(None, db, "u1", rows, {"quotes": {}, "source": None}, {}))
    g = next(x for x in groups if x["underlying"] == "NIFTY")
    assert g["key"] == "broker:NIFTY" and g["kind"] == "fno" and g["pnl_rs"] == 3900.0 and g["pnl_source"] == "broker"
    assert [l["key"] for l in g["legs"]] == ["NIFTY|2026-11-03|23000|CE", "NIFTY|2026-11-03|23500|CE"]
    assert [l["lots"] for l in g["legs"]] == [1, -1] and g["legs"][0]["iv_pct"] == 14.0
    assert g["price"] == {"spot": 23100.0, "source": "nse_bhavcopy", "as_of": "2026-10-30", "pricing_as_of": "2026-10-30"}
    assert g["analytics"]["payoff"]["max_loss"] == round(-(180.0 - 70.0) * 65, 2)
    assert g["margin_request"] == {"underlying": "NIFTY", "legs": [
        {"side": "buy", "option_type": "call", "expiry": "2026-11-03", "strike": 23000.0, "lots": 1},
        {"side": "sell", "option_type": "call", "expiry": "2026-11-03", "strike": 23500.0, "lots": 1}]}
    um = next(x for x in groups if x["kind"] == "unmapped")
    assert um["unmapped"][0]["broker_code"] == "ZZZQQQ" and um["analytics"] is None


def test_sv2_a_stale_chain_gives_no_figure_and_says_why(priced):
    rows = [broker_row("STALE", 100, 50.0, broker="upstox", instrument_type="FUT", expiry="2026-11-24", pnl=10.0)]
    groups = run(service.broker_groups(None, FakeDB(), "u1", rows, {"quotes": {}, "source": None}, {}))
    g = groups[0]
    assert g["analytics"]["payoff"] is None and g["analytics"]["scenario"] == []
    assert any(w["code"] == "price_unavailable" and "older than the previous session" in w["text"] for w in g["warnings"])


def test_sv3_a_live_quote_beats_the_bhavcopy_spot_and_the_users_stop_is_used(priced):
    rows = [broker_row("SONBLW", 1225, 868.0, instrument_type="FUT", expiry="2026-11-24", pnl=27562.5)]
    db = FakeDB()
    lv = {"_id": "u1|SONACOMS", "underlying": "SONACOMS", "stop": 824.6, "target": 957.0, "trail_pct": None}
    quotes = {"quotes": {"SONACOMS": {"ltp": 890.5}}, "source": "kite_close", "as_of": "2026-10-30T10:00:00+00:00"}
    g = run(service.broker_groups(None, db, "u1", rows, quotes, {"SONACOMS": lv}))[0]
    assert g["underlying"] == "SONACOMS" and g["price"]["spot"] == 890.5 and g["price"]["source"] == "kite_close"
    assert g["levels"]["stop"] == 824.6 and g["levels"]["set_by"] == "you"
    assert g["analytics"]["payoff"]["risk_basis"] == "stop" and g["analytics"]["payoff"]["max_loss"] is None
    assert g["analytics"]["payoff"]["loss_at_stop_rs"] is not None


def test_sv4_paper_cash_trade_keeps_its_own_levels():
    t = {"id": "pt1", "kind": "cash", "symbol": "COFORGE", "quantity": 18, "entry_price": 2010.81, "stop_price": 1904.91,
         "target_price": 2222.61, "last_close": 2045.0, "last_close_date": "2026-10-30", "unrealized_pnl_rs": 615.42,
         "status": "open", "opened_at": "2026-10-28T10:00:00+00:00"}
    g = run(service.paper_groups(None, [t], {"quotes": {}, "source": None}))[0]
    assert g["key"] == "paper:pt1" and g["source"] == "paper" and g["levels"]["set_by"] == "paper trade"
    assert g["pnl_rs"] == 615.42 and g["price"]["spot"] == 2045.0
    assert g["analytics"]["payoff"]["loss_at_stop_rs"] == round((2010.81 - 1904.91) * 18, 2)


def test_sv5_read_broker_reports_each_account_and_never_fails_the_others(monkeypatch):
    import routes.broker_connect as bc
    from services.brokers import hub_reads as hub

    async def ok_user(request):
        return {"user_id": "u1"}

    async def accounts(uid):
        return [{"account_id": "a1", "broker": "icicidirect", "native": True}, {"account_id": "a2", "broker": "zerodha", "native": True}]

    async def read(db, doc, kind):
        if doc["account_id"] == "a2":
            raise hub.BrokerSessionExpired("expired")
        return [row("SONBLW", 1225, 868.0, instrument_type="FUT", expiry="2026-11-24"), row("RELIND", 0, 1.0, segment="equity")]
    monkeypatch.setattr(bc, "_hub_user", ok_user)
    monkeypatch.setattr(bc, "_user_accounts", accounts)
    monkeypatch.setattr(bc, "_account_entry", lambda d: {"account_id": d["account_id"], "broker": d["broker"],
                                                         "broker_display": d["broker"].title(), "label": None})
    monkeypatch.setattr(hub, "read_account_positions", read)
    db = FakeDB()
    entries, rows = run(service.read_broker(None, db, "u1"))
    a1, a2 = entries
    assert a1["ok"] and a1["rows"] == 1 and a1["closed_rows"] == 1 and a1["snapshot_id"] and a1["broker_as_of"] is None
    assert not a2["ok"] and a2["error"]["code"] == hub.CODE_SESSION_EXPIRED
    assert len(rows) == 1 and rows[0]["_account_id"] == "a1"

    async def off(request):
        raise HTTPException(status_code=403, detail="off")
    monkeypatch.setattr(bc, "_hub_user", off)
    entries, rows = run(service.read_broker(None, db, "u1"))
    assert entries[0]["error"]["code"] == "BROKER_HUB_OFF" and rows == []


def test_sv6_summary_counts(priced):
    rows = [broker_row("SONBLW", 1225, 868.0, instrument_type="FUT", expiry="2026-11-24", pnl=100.0)]
    lv = {"_id": "u1|SONACOMS", "underlying": "SONACOMS", "stop": 23000.0}
    groups = run(service.broker_groups(None, FakeDB(), "u1", rows, {"quotes": {}, "source": None}, {"SONACOMS": lv}))
    s = service.summarise(groups, waiting_paper=1)
    assert s["groups"] == 1 and s["positions"] == 1 and s["paper_waiting_entry"] == 1
    assert s["unrealised_pnl_rs"] == 100.0 and s["day_realised_pnl_rs"] is None and s["day_realised_note"]


# ── RT: the routes (contract tests for every request body) ───────────────────
@pytest.fixture
def client(monkeypatch):
    import routes.positions as rp
    db = FakeDB()
    monkeypatch.setattr(rp, "db", db)

    async def user(request: Request):
        if request.headers.get("X-Test-User") != "u1":
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": "u1"}
    monkeypatch.setattr(rp, "get_current_user", user)

    async def build(request, db_, u):
        return {"as_of": "x", "read_only": True, "note": service.READ_ONLY_NOTE, "sources": [], "summary": {},
                "groups": [{"key": "broker:NIFTY", "underlying": "NIFTY", "price": {"spot": 1.0}, "warnings": [],
                            "_legs": [fut(1, 65, 1.0, 1.0)], "_spot": 1.0}]}
    monkeypatch.setattr(service, "build", build)
    app = FastAPI()
    app.include_router(rp.router)
    c = TestClient(app)
    c.headers.update({"X-Test-User": "u1"})
    c.db = db
    return c


def test_rt1_get_positions_sends_no_working_fields(client):
    r = client.get("/api/positions")
    assert r.status_code == 200 and r.json()["groups"] == [{"key": "broker:NIFTY", "underlying": "NIFTY", "price": {"spot": 1.0}, "warnings": []}]
    assert client.get("/api/positions", headers={"X-Test-User": "nobody"}).status_code == 401


@pytest.mark.parametrize("body", ['{"stop": 0}', '{"stop": "x"}', '{"colour": 1}', '{}', '[1]', 'not json',
                                  '{"trail_pct": 70}', '{"stop": 10, "target": 10}'])
def test_rt2_put_levels_refuses_bad_bodies(client, body):
    r = client.put("/api/positions/SONACOMS/levels", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_rt3_put_and_delete_levels(client):
    r = client.put("/api/positions/sonacoms/levels", json={"stop": 824.6, "target": 957})
    assert r.status_code == 200 and r.json() == {"underlying": "SONACOMS", "stop": 824.6, "target": 957.0,
                                                 "trail_pct": None, "updated_at": r.json()["updated_at"], "set_by": "you"}
    assert client.db[store.LEVELS].docs[0]["user_id"] == "u1"
    assert client.put("/api/positions/BAD%20SYM/levels", json={"stop": 1}).status_code == 422
    assert client.delete("/api/positions/SONACOMS/levels").json() == {"underlying": "SONACOMS", "deleted": True}
    assert client.delete("/api/positions/SONACOMS/levels").status_code == 404


def test_rt4_scenario_inputs_are_checked(client):
    assert client.get("/api/positions/broker:NIFTY/scenario?moves=1,a").status_code == 422
    assert client.get("/api/positions/broker:NIFTY/scenario?moves=" + ",".join(["1"] * 26)).status_code == 422
    assert client.get("/api/positions/broker:NIFTY/scenario?moves=60").status_code == 422
    assert client.get("/api/positions/broker:NIFTY/scenario?iv_shift=80").status_code == 422
    assert client.get("/api/positions/nifty/scenario").status_code == 422          # not a group key
    assert client.get("/api/positions/broker:BANKNIFTY/scenario").status_code == 404
    r = client.get("/api/positions/broker:NIFTY/scenario?moves=-1,0,1&iv_shift=3&days_forward=1")
    assert r.status_code == 200
    body = r.json()
    assert [x["move_pct"] for x in body["rows"]] == [-1.0, 0.0, 1.0] and body["iv_shift"] == 3.0 and body["gross"]
