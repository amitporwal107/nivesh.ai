"""The suggestion engine (services/suggestions, routes/suggestions.py): SG-T* catalog, SG-E* engine, SG-I* inputs,
SG-R* route contract. Test cases: test_reports/dtc_r3_suggestions_20261031.md.

Every input below is a MOCK — not real data: fixtures in the shape the real readers return (services/suggestions/
inputs.py), dated against a fixed session window (today 2026-10-30, previous session 2026-10-29). The Mongo stores are
an in-memory fake that supports exactly the calls the engine and the route make.
"""
from __future__ import annotations

import asyncio
import copy
import itertools
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import suggestions as route
from services import market_freshness
from services.copilot_visual import resolve_intent
from services.suggestions import catalog, engine, inputs, rules, store
from services.suggestions.inputs import Input

NOW = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)          # 21:30 IST, after the evening data jobs
TODAY, FLOOR = "2026-10-30", "2026-10-29"
WINDOW = market_freshness.Window(today=date(2026, 10, 30), floor=date(2026, 10, 29), calendar_checked=True)
BANNED = re.compile(r"\b(buy now|strong buy|recommend\w*|pick\w*)\b", re.I)


# ── an in-memory Mongo, just enough ──────────────────────────────────────────

def _matches(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
    for k, v in q.items():
        if isinstance(v, dict) and any(op.startswith("$") for op in v):
            for op, arg in v.items():
                have = doc.get(k)
                if op == "$gte" and not (have is not None and have >= arg):
                    return False
                if op == "$in" and have not in arg:
                    return False
        elif doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        self.docs.sort(key=lambda d: str(d.get(key) or ""), reverse=direction == -1)
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self.docs[: n or len(self.docs)]]


class _Res:
    def __init__(self, upserted_id=None):
        self.upserted_id = upserted_id


class FakeColl:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.writes = 0
        self._ids = itertools.count(1)

    async def create_index(self, *a, **k):
        return None

    def find(self, q=None, projection=None):
        return _Cursor([d for d in self.docs if _matches(d, q or {})])

    async def find_one(self, q, projection=None):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, q)), None)

    async def insert_one(self, doc):
        self.writes += 1
        doc.setdefault("_id", f"oid{next(self._ids)}")
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, q, update, upsert=False):
        self.writes += 1
        for d in self.docs:
            if _matches(d, q):
                d.update(copy.deepcopy(update.get("$set", {})))
                return _Res()
        if upsert:
            new = {k: v for k, v in q.items() if not isinstance(v, dict)}
            new.update(copy.deepcopy(update.get("$setOnInsert", {})))
            new.update(copy.deepcopy(update.get("$set", {})))
            self.docs.append(new)
            return _Res(new["_id"])
        return _Res()


class FakeDb:
    def __init__(self):
        self.colls: Dict[str, FakeColl] = {}

    def __getitem__(self, name):
        return self.colls.setdefault(name, FakeColl())

    def __getattr__(self, name):
        return self[name]


# ── MOCK inputs, as the readers return them ──────────────────────────────────

AI_DAY = {
    "list_date": TODAY,
    "cash": [{"rank": 1, "symbol": "PNB", "plan_status": "plan"}, {"rank": 2, "symbol": "ANANDRATHI", "plan_status": "plan"},
             {"rank": 3, "symbol": "TVSMOTOR", "plan_status": "wait"}, {"rank": 4, "symbol": "IIFLCAPS", "plan_status": "no_trade"},
             {"rank": 5, "symbol": "PERSISTENT", "plan_status": "plan"}, {"rank": 6, "symbol": "COFORGE", "plan_status": "plan"}],
    "fno": [{"rank": 1, "underlying": "BANKNIFTY", "kind": "index", "name": "Bear put spread 53100/54700", "fit": {"score": 92.5}},
            {"rank": 2, "underlying": "TVSMOTOR", "kind": "stock", "name": "Bull call spread 3500/3600", "fit": {"score": 80}},
            {"rank": 3, "underlying": "NIFTY", "kind": "index", "name": "Bear put spread 22800/23050", "fit": {"score": 78}},
            {"rank": 4, "underlying": "SBIN", "kind": "stock", "name": "Long call 900", "fit": {"score": 70}}],
    "notes": {"fno_staleness": None},
}

INSIGHTS = [  # routes/insights._deterministic_insights output shape
    {"title": "Reduce Information Technology sector exposure", "type": "warning", "category": "risk",
     "current_value": "32.1%", "target_value": "25%"},
    {"title": "Add debt allocation", "type": "opportunity", "category": "allocation", "current_value": "4.0%", "target_value": "≥10%"},
]


def trade(sym, entry, stop, last, *, target=None, entered=True, exited=False, last_date=TODAY, tid=None):
    return {"trade_id": tid or f"t_{sym}", "symbol": sym, "entry": entry, "stop": stop, "target": target, "last": last,
            "last_date": last_date, "entered": entered, "exited": exited, "mark_error": None}


def market_inputs(**over) -> Dict[str, Input]:
    base = {
        "market_snapshot": Input("market_snapshot", as_of=TODAY),
        "fii_dii": Input("fii_dii", as_of=TODAY, facts={"fii_net": "+₹3,598.54 Cr", "dii_net": "−₹817.51 Cr"}),
        "chain_NIFTY": Input("chain_NIFTY", as_of=TODAY, facts={"expiry": "3 Nov 2026"}),
        "chain_BANKNIFTY": Input("chain_BANKNIFTY", as_of=TODAY, facts={"expiry": "25 Nov 2026"}),
        "positional_watchlist": Input("positional_watchlist", as_of=TODAY, facts={"count": 3}),
        "scan_snapshot": Input("scan_snapshot", as_of=TODAY, facts={"count": 74}),
        "ai_watchlist": Input("ai_watchlist", as_of=TODAY, value=copy.deepcopy(AI_DAY)),
    }
    base.update(over)
    return base


def personal_inputs(*, holdings=True, holdings_as_of="2026-10-29T18:00:00+00:00", trades=None, book=None,
                    symbols=None, brokers=None, insights=None, facts=None) -> Dict[str, Any]:
    if holdings:
        h = Input("holdings", as_of=holdings_as_of, value=[{"ticker": "TVSMOTOR", "asset_type": "stock", "quantity": 10}],
                  facts={"count": 1})
        pr = Input("portfolio_rules", as_of=holdings_as_of, value=copy.deepcopy(INSIGHTS if insights is None else insights))
        pf = Input("portfolio_facts", as_of=holdings_as_of, value=facts or {"total_value": 1_000_000, "max_overlap_pct": 47.2})
    else:
        h = Input("holdings", empty=True, value=[])
        pr = Input("portfolio_rules", empty=True, value=[])
        pf = Input("portfolio_facts", empty=True, value={})
    sy = symbols if symbols is not None else ({"TVSMOTOR": "holdings", "PNB": "watchlist"} if holdings else {})
    us = Input("user_symbols", as_of=NOW.isoformat(), value=sy, empty=not sy)
    pt = Input("paper_trades", empty=True, value=[]) if not trades else \
        Input("paper_trades", as_of=max(t["last_date"] for t in trades), value=trades, facts={"count": len(trades)})
    rb = Input("risk_book", empty=True) if book is None else Input("risk_book", as_of=TODAY, value=book)
    return {"holdings": h, "portfolio_rules": pr, "portfolio_facts": pf, "user_symbols": us, "paper_trades": pt,
            "risk_book": rb, "brokers": brokers or []}


class World:
    def __init__(self, monkeypatch):
        self.db = FakeDb()
        self.market = market_inputs()
        self.personal = personal_inputs()
        self.market_calls = 0

        async def fake_market(request, names, *, fresh_read=False):
            self.market_calls += 1
            return {n: self.market[n] for n in names}

        async def fake_personal(db, uid):
            return copy.deepcopy(self.personal)

        async def fake_window(now=None, holiday=None):
            return WINDOW

        monkeypatch.setattr(inputs, "market", fake_market)
        monkeypatch.setattr(inputs, "personal", fake_personal)
        monkeypatch.setattr(market_freshness, "window", fake_window)
        monkeypatch.setattr(store, "_indexes_ready", False)
        engine._memo.clear()

    def run(self, *, mode="trader", now=NOW, uid="u1", persist=True):
        engine._memo.clear()
        return asyncio.run(engine.evaluate(self.db, {"user_id": uid}, request="REQ", mode=mode, now=now, persist=persist))


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch)


def titles(result, tab):
    return [c["title"] for c in result["per_tab"][tab]]


def card(result, rule_id):
    return next(c for tab in result["per_tab"].values() for c in tab if c["rule_id"] == rule_id)


def has_rule(result, rule_id):
    return any(c["rule_id"] == rule_id for tab in result["per_tab"].values() for c in tab)


# ── SG-T: the catalog ────────────────────────────────────────────────────────

@pytest.mark.parametrize("persona", ["trader", "investor"])
@pytest.mark.parametrize("tmpl", catalog.QUERY_TEMPLATES, ids=lambda t: t["_id"])
def test_sg_t1_every_template_opens_its_declared_answer(tmpl, persona):
    q = tmpl["query"].format(symbol="TVSMOTOR") if tmpl["params"] else tmpl["query"]
    got = resolve_intent(q, persona, None)
    assert (got.name if got else None) == tmpl["intent"], q
    if tmpl["intent"] == "stock_decision" or tmpl["params"]:
        assert got.symbol == "TVSMOTOR"


def test_sg_t1b_every_visual_answer_intent_has_a_template():
    from services.copilot_visual import INTENTS
    assert len(INTENTS) == 13 and "daily_review" in INTENTS
    assert {t["intent"] for t in catalog.QUERY_TEMPLATES if t["intent"]} == set(INTENTS)
    review = [t["query"] for t in catalog.QUERY_TEMPLATES if t["intent"] == "daily_review"]
    assert review == ["What did I learn from today's trades?", "How did I do this week?"]
    assert resolve_intent("How did I do this week?", "trader", None).params == {"period": "week"}
    assert resolve_intent("What did I learn from today's trades?", "trader", None).params == {"period": "day"}


def test_sg_t2_every_rule_is_wired():
    tmpl_ids = {t["_id"] for t in catalog.QUERY_TEMPLATES}
    known_inputs = set(inputs.LABELS)
    for r in catalog.RULES:
        assert r["trigger"] in rules.EVALUATORS, r["_id"]
        assert r["template_id"] in tmpl_ids, r["_id"]
        assert r["class"] in catalog.CLASSES and r["tab"] in catalog.TAB_KEYS, r["_id"]
        assert set(r["inputs"]) <= known_inputs, r["_id"]
        assert r["freshness"]["kind"] in ("session", "days", "none")
    assert set(catalog.INDEX_TEMPLATES.values()) <= tmpl_ids
    assert len({r["_id"] for r in catalog.RULES}) == len(catalog.RULES)


def test_sg_t3_no_wording_says_buy_now_recommend_or_pick():
    texts = [c["label"] for c in catalog.CLASSES.values()] + [c["footer"] for c in catalog.CLASSES.values()]
    texts += [t[k] for t in catalog.QUERY_TEMPLATES for k in ("label", "query")]
    texts += [r[k] for r in catalog.RULES for k in ("title", "why", "name", "description")]
    for t in texts:
        assert not BANNED.search(t), t


# ── SG-E: the engine ─────────────────────────────────────────────────────────

def test_sg_e1_market_starters_one_per_current_source(world):
    out = world.run()
    market = out["per_tab"]["market"]
    assert [c["rule_id"] for c in market] == ["market_view_daily", "smart_money_daily", "expected_move_nifty_daily",
                                               "breakouts_daily", "unusual_volume_daily"]
    sm = card(out, "smart_money_daily")
    assert sm["why"] == "FII cash +₹3,598.54 Cr, DII cash −₹817.51 Cr on 30 Oct 2026."
    assert sm["query"] == "Where is smart money moving?" and sm["intent"] == "smart_money"
    assert sm["class"] == "informational" and sm["class_label"] == "To explore"
    assert sm["inputs"] == [{"name": "fii_dii", "label": "NSE FII/DII cash flows", "as_of": TODAY, "status": "fresh"}]
    assert card(out, "expected_move_nifty_daily")["title"] == "Nifty's expected move to 3 Nov 2026"
    assert out["notices"]["market"] == []


def test_sg_e2_stale_or_missing_source_gives_no_card_and_says_so(world):
    world.market["fii_dii"] = Input("fii_dii", as_of="2026-10-21", facts={"fii_net": "+₹1.00 Cr", "dii_net": "+₹1.00 Cr"})
    world.market["chain_NIFTY"] = Input("chain_NIFTY", error="RuntimeError: DaaS /fno answered 404")
    out = world.run()
    assert not has_rule(out, "smart_money_daily") and not has_rule(out, "expected_move_nifty_daily")
    texts = [n["text"] for n in out["notices"]["market"]]
    assert ("NSE FII/DII cash flows: the newest data is from 21 Oct 2026, older than the previous session (29 Oct 2026). "
            "Nothing is suggested from it today.") in texts
    assert any(t.startswith("NIFTY option chain (NSE F&O bhavcopy) could not be read just now (RuntimeError") for t in texts)
    assert {n["kind"] for n in out["notices"]["market"]} == {"stale", "missing"}


def test_sg_e3_no_portfolio_no_personal_card_and_a_connect_notice(world):
    world.personal = personal_inputs(holdings=False)
    out = world.run(mode="investor")
    personal_rules = {"portfolio_review", "sector_concentration", "amc_concentration", "fund_overlap", "debt_allocation",
                      "regular_plan_cost", "watchlist_on_scanner", "near_stop", "near_target", "loss_limit_use",
                      "open_trades_check"}
    assert not any(c["rule_id"] in personal_rules for tab in out["per_tab"].values() for c in tab)
    assert out["notices"]["for_you"][0]["kind"] == "no_portfolio"
    # What remains are questions about the market, never a figure about the user's money.
    assert titles(out, "for_you") == ["Find today's opportunities"]


def test_sg_e4_portfolio_rules_become_cards_from_fresh_holdings_only(world):
    out = world.run(mode="investor")
    sec = card(out, "sector_concentration")
    assert sec["why"] == "Information Technology is 32.1% of your holdings, above the 25% ceiling the portfolio checks use."
    assert sec["query"] == "Show the sector concentration and overlapping holdings in my portfolio" and sec["intent"] is None
    assert card(out, "portfolio_review")["why"] == "2 portfolio checks flag something (allocation, sector); holdings as of 29 Oct 2026."
    assert card(out, "fund_overlap")["why"] == "Your two most similar funds share 47% of their holdings."
    # Holdings last updated 12 days ago: nothing from them, and the tab says why.
    world.personal = personal_inputs(holdings_as_of="2026-10-18T10:00:00+00:00")
    out = world.run(mode="investor")
    assert not has_rule(out, "sector_concentration") and not has_rule(out, "portfolio_review")
    n = next(n for n in out["notices"]["for_you"] if n["source"] == "Your holdings")
    assert n["text"].startswith("Your holdings were last updated on 18 Oct 2026. Suggestions about them are paused")
    assert n["action"] == "refresh_holdings"


def test_sg_e5_a_held_or_watched_stock_on_the_scanner_list_is_a_validated_signal(world):
    out = world.run()
    sig = [c for c in out["per_tab"]["for_you"] if c["rule_id"] == "watchlist_on_scanner"]
    assert [c["symbol"] for c in sig] == ["PNB", "TVSMOTOR"]        # TVSMOTOR is also on the F&O list: shown here once
    assert sig[1]["title"] == "TVSMOTOR from your holdings is on today's scanner list"
    assert sig[1]["why"] == "Rank 3 of the AI scanner's list of 30 Oct 2026; desk status: waiting for confirmation."
    pnb = sig[0]
    assert pnb["class"] == "validated_signal" and pnb["class_label"] == "Rule-based signal"
    assert pnb["title"] == "PNB from your watchlist is on today's scanner list"
    assert pnb["why"] == "Rank 1 of the AI scanner's list of 30 Oct 2026; desk status: setup ready."
    assert pnb["query"] == "What's the setup for PNB?" and pnb["intent"] == "stock_decision"
    assert pnb["footer"] == "Met a scanner rule on 30 Oct 2026. An idea to review with its evidence, not advice."


def test_sg_e6_trades_near_their_stop_or_target(world):
    world.personal = personal_inputs(trades=[
        trade("SONACOMS", 868.87, 824.60, 834.0, target=957.41),                 # 78.6% of the way to the stop → alert
        trade("SHORTCO", 100.0, 110.0, 108.0),                                    # a short: 80% of the way up to its stop
        trade("FARCO", 100.0, 90.0, 99.0),                                        # 10%: nothing
        trade("WAITCO", 100.0, 90.0, 92.0, entered=False),                        # not entered: nothing
        trade("GONECO", 100.0, 90.0, 89.0, exited=True),                          # past its exit: the desk closes it
        trade("OLDCO", 100.0, 90.0, 92.0, last_date="2026-10-28"),                # its mark is not the newest: nothing
        trade("COFORGE", 2010.81, 1904.91, 2200.0, target=2222.61),               # 89% of the way to the target
    ])
    out = world.run()
    alerts = [c for c in out["per_tab"]["my_trades"] if c["rule_id"] == "near_stop"]
    assert sorted(c["symbol"] for c in alerts) == ["SHORTCO", "SONACOMS"]
    s = next(c for c in alerts if c["symbol"] == "SONACOMS")
    assert s["class"] == "risk_alert" and s["title"] == "SONACOMS is near its stop-loss"
    assert s["why"] == "Last close ₹834.00 on 30 Oct 2026; stop ₹824.60, 1.13% away."
    assert s["query"] == "Should I book profits or hold SONACOMS?" and s["intent"] == "exit_options"
    assert s["footer"] == "About your own trade's levels and limits. It does not tell you to exit or hold."
    tgt = card(out, "near_target")
    assert tgt["symbol"] == "COFORGE" and tgt["class"] == "informational"
    assert card(out, "open_trades_check")["why"] == "6 open paper trades, marked at the close of 30 Oct 2026."  # not GONECO
    # A stale mark: no trade card at all, and "prices stale" said.
    world.personal = personal_inputs(trades=[trade("SONACOMS", 868.87, 824.60, 834.0, last_date="2026-10-27")])
    out = world.run()
    assert not any(c["rule_id"] in ("near_stop", "open_trades_check") for c in out["per_tab"]["my_trades"])
    assert any(n["text"].startswith("Prices stale: your paper trades are marked at the close of 27 Oct 2026")
               for n in out["notices"]["my_trades"])


def test_sg_e7_daily_loss_limit_in_use(world):
    book = {"day": {"start": TODAY, "pnl_rs": -12_000.0, "start_equity_rs": 1_000_000.0},
            "profile": {"limits": {"daily_loss_pct": 2.0}}, "equity": {"marks_as_of": TODAY}}
    world.personal = personal_inputs(trades=[trade("FARCO", 100.0, 90.0, 99.0)], book=book)
    out = world.run()
    c = card(out, "loss_limit_use")
    assert c["title"] == "60% of today's loss limit is used" and c["class"] == "risk_alert"
    assert c["why"] == "Today's paper P&L −₹12,000.00 against a 2.0% daily limit, marked 30 Oct 2026."
    book["day"]["pnl_rs"] = -4_000.0                                              # 20% of the limit: nothing
    world.personal = personal_inputs(trades=[trade("FARCO", 100.0, 90.0, 99.0)], book=book)
    assert not has_rule(world.run(), "loss_limit_use")


def test_sg_e8_fno_lab_from_the_current_list_and_never_a_stale_chain(world):
    out = world.run()
    fno = out["per_tab"]["fno_lab"]
    sig = [c for c in fno if c["rule_id"] == "fno_top_signals"]
    # The list's top 3 are BANKNIFTY, TVSMOTOR and NIFTY; TVSMOTOR's setup question is already the For-you card about
    # the user's own holding, so it is shown once, there.
    assert [c["title"] for c in sig] == ["BANKNIFTY: Bear put spread 53100/54700 fits today's regime",
                                         "NIFTY: Bear put spread 22800/23050 fits today's regime"]
    assert all(c["class"] == "validated_signal" for c in sig)
    assert sig[0]["query"] == "Which F&O setups are attractive?" and sig[0]["intent"] == "fno_setups" and sig[0]["symbol"] is None
    assert sig[0]["why"] == "Rank 1 on the AI scanner's F&O list of 30 Oct 2026; regime fit 92.5."
    assert card(out, "fno_setups_daily")["why"] == \
        "Defined-risk structures on the AI scanner's F&O list of 30 Oct 2026 (4 instruments)."
    assert has_rule(out, "expected_move_banknifty_daily") and has_rule(out, "expected_move_nifty_daily")
    # A user with no holdings or watchlist: TVSMOTOR's idea stays on the F&O list.
    world.personal = personal_inputs(holdings=False)
    out = world.run()
    assert [c["subject"] for c in out["per_tab"]["fno_lab"] if c["rule_id"] == "fno_top_signals"] == \
        ["BANKNIFTY", "TVSMOTOR", "NIFTY"]
    assert card(out, "fno_top_signals") and next(c for c in out["per_tab"]["fno_lab"] if c["subject"] == "TVSMOTOR")["query"] \
        == "What's the setup for TVSMOTOR?"
    stale_day = copy.deepcopy(AI_DAY)
    stale_day["notes"]["fno_staleness"] = "chain of 2026-10-28 for 3 instruments"
    world.market["ai_watchlist"] = Input("ai_watchlist", as_of=TODAY, value=stale_day)
    out = world.run()
    assert not has_rule(out, "fno_top_signals") and not has_rule(out, "fno_setups_daily")


def test_sg_e9_ranking_puts_risk_first_then_signals_then_questions(world):
    world.personal = personal_inputs(trades=[trade("SONACOMS", 868.87, 824.60, 834.0, target=957.41)])
    out = world.run()
    my = out["per_tab"]["my_trades"]
    assert [c["class"] for c in my][:1] == ["risk_alert"]
    order = {"risk_alert": 0, "validated_signal": 1, "informational": 2}
    for tab in out["per_tab"].values():
        classes = [order[c["class"]] for c in tab]
        assert classes == sorted(classes)
    # Audience: an investor sees the investor-only overlap card above the trader-only starters' weight.
    inv = world.run(mode="investor")
    tr = world.run(mode="trader")
    assert card(inv, "fund_overlap")["score"] > card(tr, "fund_overlap")["score"]


def test_sg_e10_one_card_per_question_across_tabs(world):
    out = world.run()
    keys = [(c["template_id"], tuple(sorted(c["params"].items())), c["subject"]) for tab in out["per_tab"].values() for c in tab]
    assert len(keys) == len(set(keys))
    setups = [c for tab in out["per_tab"].values() for c in tab if c["query"] == "What's the setup for TVSMOTOR?"]
    assert len(setups) == 1 and setups[0]["tab"] == "for_you"


def test_sg_e11_dismiss_hides_until_the_cooldown_and_not_relevant_lowers_the_rule(world):
    out = world.run()
    sm = card(out, "smart_money_daily")
    inst = asyncio.run(store.get_instance(world.db, "u1", sm["_id"]))
    asyncio.run(store.add_feedback(world.db, inst, "dismissed", now=NOW))
    out = world.run(now=NOW + timedelta(hours=1))
    assert not has_rule(out, "smart_money_daily") and out["suppressed"] == 1
    out = world.run(now=NOW + timedelta(hours=21))                              # its cooldown is 20 hours
    assert has_rule(out, "smart_money_daily")
    before = card(world.run(), "breakouts_daily")["score"]
    inst = asyncio.run(store.get_instance(world.db, "u1", card(world.run(), "breakouts_daily")["_id"]))
    asyncio.run(store.add_feedback(world.db, inst, "not_relevant", now=NOW - timedelta(days=1)))
    later = world.run(now=NOW + timedelta(hours=1))                             # its 20-hour cooldown ran out at NOW-4h
    assert card(later, "breakouts_daily")["score"] == before - 40


def test_sg_e12_instances_and_events_are_stored_once(world):
    world.personal = personal_inputs(trades=[trade("SONACOMS", 868.87, 824.60, 834.0)])
    out = world.run()
    shown = [c for tab in out["per_tab"].values() for c in tab]
    inst = world.db[store.INSTANCES].docs
    assert {d["_id"] for d in inst} == {c["_id"] for c in shown}
    assert all(d["state"] == "active" and d["user_id"] == "u1" and isinstance(d["expires_at"], datetime) for d in inst)
    events = world.db[store.EVENTS].docs
    assert {e["rule_id"] for e in events} >= {"near_stop", "watchlist_on_scanner", "fno_top_signals", "sector_concentration"}
    n = len(events)
    world.run(now=NOW + timedelta(minutes=5))
    assert len(world.db[store.EVENTS].docs) == n                                # the same events are not recorded again
    s = next(e for e in events if e["rule_id"] == "near_stop")
    assert s["inputs"][0]["as_of"] == TODAY and s["detected_at"] == NOW.isoformat()


def test_sg_e13_a_disconnected_broker_is_said(world):
    world.personal = personal_inputs(brokers=[{"broker": "zerodha", "name": "Zerodha", "native": True, "needs_reconnect": True,
                                               "last_sync_at": "2026-10-28T12:00:00+00:00"}])
    out = world.run()
    n = next(n for n in out["notices"]["for_you"] if n["kind"] == "disconnected")
    assert n["text"] == ("Broker disconnected: your Zerodha connection has ended, so its holdings are as of the last sync on "
                         "28 Oct 2026. Reconnect to refresh them.")


def test_sg_e14_a_failing_rule_does_not_hide_the_others(world, monkeypatch):
    def boom(rule, inp):
        raise RuntimeError("MOCK evaluator failure")
    monkeypatch.setitem(rules.EVALUATORS, "source_current", boom)
    monkeypatch.setitem(engine.EVALUATORS, "source_current", boom)
    out = world.run()
    assert not has_rule(out, "market_view_daily") and has_rule(out, "opportunities_daily")


def test_sg_e15_a_stored_rule_overrides_the_default_and_the_seed_never_overwrites(world):
    asyncio.run(store.seed(world.db, now=NOW))
    assert len(world.db[store.RULES].docs) == len(catalog.RULES)
    assert len(world.db[store.TEMPLATES].docs) == len(catalog.QUERY_TEMPLATES)
    asyncio.run(world.db[store.RULES].update_one({"_id": "smart_money_daily"}, {"$set": {"enabled": False}}))
    again = asyncio.run(store.seed(world.db, now=NOW))
    assert again == {"rules": 0, "templates": 0}
    assert next(d for d in world.db[store.RULES].docs if d["_id"] == "smart_money_daily")["enabled"] is False
    assert not has_rule(world.run(), "smart_money_daily")


def test_sg_e16_every_card_text_is_clean_and_dated(world):
    world.personal = personal_inputs(trades=[trade("SONACOMS", 868.87, 824.60, 834.0, target=957.41)],
                                     book={"day": {"start": TODAY, "pnl_rs": -15_000.0, "start_equity_rs": 1_000_000.0},
                                           "profile": {"limits": {"daily_loss_pct": 2.0}}, "equity": {"marks_as_of": TODAY}})
    out = world.run()
    for tab in out["per_tab"].values():
        for c in tab:
            for k in ("title", "why", "footer", "query", "class_label"):
                assert c[k] and not BANNED.search(c[k]), (c["rule_id"], k, c[k])
            if c["rule_id"] not in ("position_size_starter", "daily_review_starter"):     # questions without a figure
                assert c["as_of"], c["rule_id"]
                assert all(u["status"] == "fresh" and u["as_of"] for u in c["inputs"]), c["rule_id"]


def test_sg_e17_evaluation_is_memoised_briefly_per_user(world):
    engine._memo.clear()
    asyncio.run(engine.evaluate(world.db, {"user_id": "u1"}, request="REQ", mode="trader", now=NOW))
    asyncio.run(engine.evaluate(world.db, {"user_id": "u1"}, request="REQ", mode="trader", now=NOW))
    assert world.market_calls == 1
    engine.forget("u1")
    asyncio.run(engine.evaluate(world.db, {"user_id": "u1"}, request="REQ", mode="trader", now=NOW))
    assert world.market_calls == 2


# ── SG-I: the readers (read-only) ────────────────────────────────────────────

def test_sg_i1_holdings_as_of_is_the_newest_stamp_and_zero_rows_are_dropped():
    db = FakeDb()
    db.holdings.docs += [
        {"user_id": "u1", "ticker": "A", "quantity": 1, "current_price": 10, "uploaded_at": "2026-10-20T00:00:00+00:00"},
        {"user_id": "u1", "ticker": "B", "quantity": 2, "current_price": 5, "price_updated_at": "2026-10-29T10:00:00+00:00"},
        {"user_id": "u1", "ticker": "C", "quantity": 0, "current_price": 5, "price_updated_at": "2026-10-30T10:00:00+00:00"},
        {"user_id": "u2", "ticker": "Z", "quantity": 9, "current_price": 9, "price_updated_at": "2026-10-30T11:00:00+00:00"},
    ]
    h = asyncio.run(inputs._holdings(db, "u1"))
    assert h.as_of == "2026-10-29T10:00:00+00:00" and h.facts == {"count": 2, "value_rs": 20.0}
    assert asyncio.run(inputs._holdings(db, "nobody")).empty


def test_sg_i2_user_symbols_join_stock_holdings_and_watchlists():
    db = FakeDb()
    db.user_watchlists.docs.append({"user_id": "u1", "symbols": [{"symbol": "pnb"}, {"symbol": "TVSMOTOR"}]})
    h = Input("holdings", as_of=TODAY, value=[{"ticker": "TVSMOTOR", "asset_type": "stock"},
                                              {"ticker": "INF000", "asset_type": "mutual_fund"}])
    s = asyncio.run(inputs._user_symbols(db, "u1", h))
    assert s.value == {"TVSMOTOR": "holdings", "PNB": "watchlist"}


def test_sg_i3_paper_trades_read_marks_without_running_the_exit_job(monkeypatch):
    from services import desk_trading as desk
    db = FakeDb()
    db[desk.TRADES].docs += [
        {"_id": "t1", "user_id": "u1", "status": "open", "symbol": "SONACOMS", "entry_price": 868.87, "stop_price": 824.6,
         "target_price": 957.41, "opened_at": "2026-10-27T05:00:00+00:00"},
        {"_id": "t2", "user_id": "u1", "status": "open", "kind": "strategy", "underlying": "NIFTY"},
    ]
    bars = {"SONACOMS": [{"date": date(2026, 10, 30), "close": 834.0, "high": 840.0, "low": 830.0, "open": 838.0}]}

    async def fetch(starts):
        assert set(starts) == {"SONACOMS"}
        return bars, {}
    monkeypatch.setattr(desk, "fetch_bars_many", fetch)
    monkeypatch.setattr(desk, "simulate", lambda d, b: {"entry_status": "assumed", "current_stop": 830.0, "exit": None})
    monkeypatch.setattr(desk, "apply_trade_exits", lambda *a, **k: pytest.fail("the exit job must not run"))
    p = asyncio.run(inputs._paper_trades(db, "u1"))
    assert p.as_of == TODAY and p.value == [{"trade_id": "t1", "symbol": "SONACOMS", "entry": 868.87, "stop": 830.0,
                                             "target": 957.41, "last": 834.0, "last_date": TODAY, "entered": True,
                                             "exited": False, "mark_error": None}]
    assert db[desk.TRADES].writes == 0


def test_sg_i4_a_failing_market_source_is_missing_and_not_cached(monkeypatch):
    inputs.clear_market_cache()
    calls = {"n": 0}

    async def boom(request):
        calls["n"] += 1
        raise RuntimeError("MOCK DaaS down")
    monkeypatch.setitem(inputs.MARKET_READERS, "fii_dii", boom)
    out = asyncio.run(inputs.market("REQ", ["fii_dii"]))
    assert out["fii_dii"].error == "RuntimeError: MOCK DaaS down"
    asyncio.run(inputs.market("REQ", ["fii_dii"]))
    assert calls["n"] == 2


# ── SG-R: the route contract ─────────────────────────────────────────────────

@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(route, "db", world.db)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


H = {"X-Test-User": "u1"}


def test_sg_r1_list_contract(client):
    r = client.get("/api/suggestions", params={"tab": "market", "mode": "trader"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "suggestions-v1" and body["tab"] == "market" and body["mode"] == "trader"
    assert [t["key"] for t in body["tabs"]] == ["for_you", "market", "my_trades", "fno_lab"]
    assert [t["label"] for t in body["tabs"]] == ["For you", "Market", "My trades", "F&O Lab"]
    assert body["tabs"][1]["count"] == len(body["suggestions"]) == 5
    s = body["suggestions"][0]
    assert set(s) == {"id", "tab", "class", "class_label", "title", "why", "footer", "query", "intent", "template_id",
                      "rule_id", "symbol", "as_of", "inputs", "state"}
    assert s["id"].startswith("sg_") and s["state"] == "active"
    assert body["window"] == {"today": body["window"]["today"], "previous_session": FLOOR}


@pytest.mark.parametrize("params", [{"tab": "nope"}, {"mode": "advisor"}])
def test_sg_r2_bad_query_is_422(client, params):
    assert client.get("/api/suggestions", params=params, headers=H).status_code == 422


def test_sg_r3_refresh_body_contract(client):
    r = client.post("/api/suggestions/refresh", json={"tab": "fno_lab", "mode": "trader"}, headers=H)
    assert r.status_code == 200 and r.json()["tab"] == "fno_lab"
    assert client.post("/api/suggestions/refresh", json={}, headers=H).json()["tab"] == "for_you"
    assert client.post("/api/suggestions/refresh", json={"tab": "fno_lab", "extra": 1}, headers=H).status_code == 422
    assert client.post("/api/suggestions/refresh", json={"tab": "x"}, headers=H).status_code == 422


def test_sg_r4_feedback_contract(client, world):
    sid = client.get("/api/suggestions", params={"tab": "market"}, headers=H).json()["suggestions"][0]["id"]
    r = client.post(f"/api/suggestions/{sid}/feedback", json={"action": "dismissed"}, headers=H)
    assert r.status_code == 200 and r.json()["state"] == "dismissed" and r.json()["action"] == "dismissed"
    fb = world.db[store.FEEDBACK].docs[-1]
    assert fb["user_id"] == "u1" and fb["suggestion_id"] == sid and fb["action"] == "dismissed"
    assert sid not in [s["id"] for s in client.get("/api/suggestions", params={"tab": "market"}, headers=H).json()["suggestions"]]
    r = client.post(f"/api/suggestions/{sid}/feedback", json={"action": "useful"}, headers=H)
    assert r.status_code == 200 and r.json()["state"] == "dismissed"
    # A later "useful" does not bring a dismissed card back before its cooldown.
    assert sid not in [s["id"] for s in client.get("/api/suggestions", params={"tab": "market"}, headers=H).json()["suggestions"]]
    assert client.post(f"/api/suggestions/{sid}/feedback", json={"action": "liked"}, headers=H).status_code == 422
    assert client.post(f"/api/suggestions/{sid}/feedback", json={}, headers=H).status_code == 422
    assert client.post("/api/suggestions/sg_0000000000000000/feedback", json={"action": "useful"}, headers=H).status_code == 404
    assert client.post(f"/api/suggestions/{sid}/feedback", json={"action": "useful"},
                       headers={"X-Test-User": "u2"}).status_code == 404


def test_sg_r5_why_contract(client):
    s = next(x for x in client.get("/api/suggestions", params={"tab": "market"}, headers=H).json()["suggestions"]
             if x["rule_id"] == "smart_money_daily")
    r = client.get(f"/api/suggestions/{s['id']}/why", headers=H)
    assert r.status_code == 200
    w = r.json()
    assert w["rule"]["id"] == "smart_money_daily" and w["rule"]["name"] == "Daily smart-money flows"
    assert w["rule"]["freshness"] == {"kind": "session"} and w["rule"]["cooldown_hours"] == 20
    assert w["inputs"] == [{"name": "fii_dii", "label": "NSE FII/DII cash flows", "as_of": TODAY, "status": "fresh"}]
    assert w["query"] == "Where is smart money moving?" and w["intent"] == "smart_money"
    assert client.get("/api/suggestions/sg_0000000000000000/why", headers=H).status_code == 404


def test_sg_r6_signed_out_is_401(client):
    assert client.get("/api/suggestions").status_code == 401
    assert client.post("/api/suggestions/refresh", json={}).status_code == 401


def test_sg_e18_a_starter_whose_answer_is_none_is_not_suggested(world):
    assert card(world.run(), "breakouts_daily")["why"] == "3 stocks met the confirmed-breakout rule on 30 Oct 2026."
    world.market["positional_watchlist"] = Input("positional_watchlist", as_of=TODAY, facts={"count": 0})
    out = world.run()
    assert not has_rule(out, "breakouts_daily") and out["notices"]["market"] == []
