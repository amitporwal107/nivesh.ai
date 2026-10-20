"""Chartink hits merged into the Strategy Builder's AI opportunities: services/strategy_plan selection, ideas, evidence, candidates, plan, rules.

No network and no real database. Everything below is MOCK — not real data: invented symbols (AAA, BBB ...) beside the RELIANCE-like fixture world of
tests/test_strategy_plan.py, invented scan names ("Mock Alpha Scan"). The scanner side reuses the fixtures of tests/test_strategy_ideas.py.

Ordering arithmetic (chartink_limit 4, five Chartink-only stocks pass the gates):
    BBB: 3 bullish scans, 20-session traded value 80 Cr     AAA: 3 bullish scans, 20 Cr     DDD: 2 bullish scans     CCC: 1 bullish scan, 500 Cr
    -> the order is BBB, AAA (same count 3: the larger traded value first), DDD, CCC (fewest scans last, whatever its traded value)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import pytest

from services.strategy_plan import candidates as cd
from services.strategy_plan import evidence as ev
from services.strategy_plan import ideas as ideas_mod
from services.strategy_plan import plan as pl
from services.strategy_plan import selection as sel
from services.strategy_plan import sources
from services.strategy_plan.evidence import src_fail, src_ok
from services.strategy_plan.rules import RULES, STRATEGY_RULES_VERSION
from tests.test_strategy_ideas import BIG, IDEAS_BODY, SYMS, client, fake_selection, gate_row, merged, patch_scanner, run, witem, watch_body  # noqa: F401
from tests.test_strategy_plan import ASOF, NOW, TODAY, bucket, build, cand, codes, events, indicators, inputs, scan_row, world

A = {"X-Test-User": "user_a"}


def hit(i, name, direction="bullish"):
    return {"id": str(i), "name": name, "direction": direction}


def index(hits: Dict[str, List[Dict[str, Any]]], state="ok", **o) -> Dict[str, Any]:
    ix = {"state": state, "reason": None if state == "ok" else f"MOCK reason for {state}", "dashboard_id": "123456", "scan_date": "2026-10-20",
          "fetched_at": "2026-10-20T11:00:00Z", "mode": "end_of_day_snapshot", "scans": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
          "symbols": {s: {"scans": h, "close": 100.0, "pct_change": 1.0, "volume": 10.0} for s, h in hits.items()} if state == "ok" else {}}
    ix.update(o)
    return ix


B3 = [hit(1, "Mock Alpha Scan"), hit(2, "Mock Beta Scan"), hit(3, "Mock Gamma Scan")]
B2 = B3[:2]
B1 = B3[:1]
BEAR = [hit(2, "Mock Beta Scan", "bearish")]
UNI = {"AAA": 20.0, "BBB": 80.0, "CCC": 500.0, "DDD": 50.0, "EEE": 40.0, "FFF": 30.0}


def rows_with(**tv):
    base = {s: gate_row(s) for s in ("HDFCBANK", "ICICIBANK", "TCS", "INFY")}
    base.update({s: gate_row(s, traded_value_cr_20d=v, name=f"Mock {s} Ltd") for s, v in UNI.items()})
    base.update({s: v for s, v in tv.items()})
    return base


def select(monkeypatch, ix, rows="default", limit=8, climit=4, watch=None, picks="default"):
    w, p = merged()
    if watch is not None:
        w = watch
    patch_scanner(monkeypatch, w, p if picks == "default" else picks, rows=rows_with() if rows == "default" else rows)
    return run(sel.select_opportunities(None, limit, chartink=ix, chartink_limit=climit))


def syms(out):
    return [s["symbol"] for s in out["setups"]]


# ── selection: the merge ─────────────────────────────────────────────────────

def test_chartink_only_stocks_follow_the_scanners_ranked_by_scan_count_then_traded_value(monkeypatch):
    ix = index({"AAA": B3, "BBB": B3, "CCC": B1, "DDD": B2, "TCS": B2, "EEE": BEAR})
    out = select(monkeypatch, ix)
    assert syms(out) == ["HDFCBANK", "ICICIBANK", "TCS", "INFY", "BBB", "AAA", "DDD", "CCC"]          # scanner by score (90, 80, 72, 65), then Chartink-only
    assert out["selected"] == 8 and out["chartink"]["added"] == 4 and out["chartink"]["considered"] == 4       # EEE: bearish only, not a candidate
    assert "EEE" not in syms(out) and out["chartink"]["excluded"] == []
    ck = {s["symbol"]: s for s in out["setups"]}
    # nothing is borrowed from a scanner that does not list the stock
    b = ck["BBB"]
    assert b["source"] == "chartink" and b["bucket"] is None and b["score"] is None and b["status"] is None and not b["in_watchlist"] and not b["in_picks"]
    assert b["entry"] is None and b["stop"] is None and b["target"] is None and b["risk_reward"] is None
    assert b["chartink"] == {"scans": B3, "count": 3, "fetched_at": "2026-10-20T11:00:00Z", "bullish_scans": 3}
    assert b["avg_traded_cr"] == 80.0 and b["name"] == "Mock BBB Ltd" and b["fno_eligible"] is True and b["close"] == 100.0
    view = sel.scanner_view(b)
    assert view["bucket"] is None and view["status"] is None and view["score"] is None and view["in_watchlist"] is False
    assert out["chartink"]["rule"] == RULES["chartink"]["ranking"] and "not a probability" in out["chartink"]["rule"]


def test_the_cap_defaults_to_four_and_is_clamped_to_zero_and_eight(monkeypatch):
    ix = index({s: B1 for s in UNI})
    base = ["HDFCBANK", "ICICIBANK", "TCS", "INFY"]
    assert syms(select(monkeypatch, ix))[4:] == ["CCC", "BBB", "DDD", "EEE"]                          # default 4: the same count, so the larger traded value first
    assert syms(select(monkeypatch, ix, climit=2))[4:] == ["CCC", "BBB"]
    assert syms(select(monkeypatch, ix, climit=0)) == base and select(monkeypatch, ix, climit=0)["chartink"]["added"] == 0
    assert len(syms(select(monkeypatch, ix, climit=99))) == 4 + 6                                    # only six Chartink-only stocks exist; the cap would be 8
    many = index({f"S{i:02d}": B1 for i in range(12)})
    rows = rows_with(**{f"S{i:02d}": gate_row(f"S{i:02d}") for i in range(12)})
    assert len(select(monkeypatch, many, rows=rows, climit=99)["setups"]) == 4 + RULES["chartink"]["limit_max"] == 12
    assert len(select(monkeypatch, many, rows=rows, limit=2, climit=3)["setups"]) == 2 + 3         # the cap is separate from the scanner limit
    assert RULES["chartink"]["limit_default"] == 4 and RULES["chartink"]["limit_max"] == 8


def test_chartink_only_stocks_pass_the_same_eligibility_gates(monkeypatch):
    ix = index({"AAA": B1, "BBB": B1, "CCC": B1, "DDD": B1, "EEE": B1, "FFF": B1, "NOSNAP": B1})
    rows = rows_with(AAA=gate_row("AAA", traded_value_cr_20d=5.0), BBB=gate_row("BBB", is_etf=True), CCC=gate_row("CCC", series="BE", traded_value_cr_20d=11.0),
                     DDD=gate_row("DDD", close=None), EEE=gate_row("EEE", has_reference=False))
    out = select(monkeypatch, ix, rows=rows, climit=8)
    got = {x["symbol"]: x["code"] for x in out["chartink"]["excluded"]}
    assert got == {"AAA": "illiquid", "BBB": "etf", "DDD": "missing_price", "EEE": "no_reference", "NOSNAP": "not_in_snapshot"}
    assert syms(out)[4:] == ["FFF", "CCC"]                                                          # series BE passes; ordered by traded value (30, 11)
    assert all(x["reason"] for x in out["chartink"]["excluded"]) and "scanner liquid flag" in [x["reason"] for x in out["chartink"]["excluded"] if x["symbol"] == "NOSNAP"][0]
    assert out["chartink"]["added"] == 2


def test_excluded_stocks_do_not_use_up_the_cap(monkeypatch):
    ix = index({"AAA": B3, "BBB": B3, "CCC": B2, "DDD": B2, "EEE": B1})
    rows = rows_with(AAA=gate_row("AAA", traded_value_cr_20d=1.0), BBB=gate_row("BBB", is_etf=True))
    out = select(monkeypatch, ix, rows=rows, climit=2)
    assert syms(out)[4:] == ["DDD", "CCC"] or syms(out)[4:] == ["CCC", "DDD"]
    assert syms(out)[4:] == ["CCC", "DDD"]                                                          # both have 2 scans; CCC trades more (500 vs 50)


def test_without_the_scan_snapshot_no_chartink_only_stock_is_added_and_it_says_so(monkeypatch):
    out = select(monkeypatch, index({"AAA": B3}), rows=None)
    assert syms(out) == ["ICICIBANK", "TCS", "INFY"] and out["chartink"]["added"] == 0              # HDFCBANK has no traded value: the scanner's own flag cannot clear it
    assert "cannot be tested" in out["chartink"]["note"]


def test_an_empty_or_unreadable_scanner_still_lists_the_chartink_only_stocks(monkeypatch):
    patch_scanner(monkeypatch, None, None, rows=rows_with(), fails=["watchlist: HTTP 503: down", "picks: HTTP 503: down"])
    out = run(sel.select_opportunities(None, 8, chartink=index({"AAA": B2, "BBB": B1}), chartink_limit=4))
    assert syms(out) == ["AAA", "BBB"] and out["empty_reason"] is None and out["source_failures"] and out["selected"] == 2
    patch_scanner(monkeypatch, watch_body(), {"signal_date": ASOF, "picks": []}, rows=rows_with())
    out = run(sel.select_opportunities(None, 8, chartink=index({"AAA": B2}), chartink_limit=4))
    assert syms(out) == ["AAA"] and out["considered"] == 0 and out["empty_reason"] is None
    out = run(sel.select_opportunities(None, 8, chartink=index({}), chartink_limit=4))
    assert out["setups"] == [] and "scanner tables empty" in out["empty_reason"]


def test_a_stock_in_the_scanner_list_is_never_chartink_only_even_when_the_gates_excluded_it(monkeypatch):
    rows = rows_with(HDFCBANK=gate_row("HDFCBANK", traded_value_cr_20d=2.0))
    out = select(monkeypatch, index({"HDFCBANK": B3, "AAA": B1}), rows=rows)
    assert "HDFCBANK" not in syms(out) and [x["symbol"] for x in out["excluded"]] == ["HDFCBANK"] and syms(out)[-1] == "AAA"
    assert out["chartink"]["considered"] == 1


def test_source_field_and_chartink_part_on_every_selected_stock(monkeypatch):
    ix = index({"TCS": B2, "ICICIBANK": BEAR, "AAA": B1, "INFY": [hit(9, "Mock Neutral", "neutral")]})
    out = select(monkeypatch, ix)
    by = {s["symbol"]: s for s in out["setups"]}
    assert by["TCS"]["source"] == "both" and by["TCS"]["chartink"] == {"scans": B2, "count": 2, "fetched_at": "2026-10-20T11:00:00Z"}
    assert by["ICICIBANK"]["source"] == "ai_scanner" and by["ICICIBANK"]["chartink"]["scans"] == BEAR      # a bearish-tagged hit is shown, and does not make it "both"
    assert by["INFY"]["source"] == "ai_scanner" and by["INFY"]["chartink"]["count"] == 1
    assert by["HDFCBANK"]["source"] == "ai_scanner" and by["HDFCBANK"]["chartink"] is None
    assert by["AAA"]["source"] == "chartink" and by["AAA"]["chartink"]["bullish_scans"] == 1
    assert [s["symbol"] for s in out["setups"] if s["source"] != "chartink"] == ["HDFCBANK", "ICICIBANK", "TCS", "INFY"]    # the scanner's rank is untouched


@pytest.mark.parametrize("state", ["no_source", "not_refreshed", "stale", "failed"])
def test_unavailable_chartink_degrades_to_the_scanner_only_with_the_reason(monkeypatch, state):
    out = select(monkeypatch, index({}, state=state))
    plain = select(monkeypatch, None)
    assert syms(out) == syms(plain) == ["HDFCBANK", "ICICIBANK", "TCS", "INFY"]
    assert out["chartink"]["state"] == state and out["chartink"]["reason"] == f"MOCK reason for {state}" and out["chartink"]["added"] == 0
    assert all(s["source"] == "ai_scanner" and s["chartink"] is None for s in out["setups"])


def test_without_chartink_the_selection_is_what_it_was(monkeypatch):
    out = select(monkeypatch, None)
    assert out["chartink"] is None and "_merged" not in out and "_rows" not in out and "_rows_read" not in out
    assert all("source" not in s for s in out["setups"])
    assert out["selected"] == 4 and out["rule"] == sel.SELECTION_RULE


# ── ideas ────────────────────────────────────────────────────────────────────

def test_ideas_input_validation_for_the_new_inputs(client):
    for body, code in (({"chartink_limit": -1}, "bad_chartink_limit"), ({"chartink_limit": 9}, "bad_chartink_limit"), ({"chartink_limit": "4"}, "bad_chartink_limit"),
                       ({"chartink_limit": True}, "bad_chartink_limit"), ({"chartink_limit": 1.5}, "bad_chartink_limit"), ({"include_chartink": "yes"}, "bad_include_chartink"),
                       ({"include_chartink": 1}, "bad_include_chartink")):
        r = client.post("/api/desk/strategy/ideas", json=body, headers=A)
        assert r.status_code == 422 and code in {p["code"] for p in r.json()["detail"]["problems"]}, body
    for ok in (0, 4, 8):
        assert client.post("/api/desk/strategy/ideas", json={**IDEAS_BODY, "chartink_limit": ok}, headers=A).status_code == 200


def test_ideas_defaults_are_disclosed_and_the_switch_turns_chartink_off(client, monkeypatch):
    seen = {}

    async def fake_select(request, limit, chartink=None, chartink_limit=4):
        seen.update(chartink=chartink, chartink_limit=chartink_limit)
        return {**client.state["selection"], "chartink": {"included": True, "state": "no_source", "reason": "MOCK", "added": 0} if chartink else None}

    reads = []

    async def fake_index(user_id, today):
        reads.append(user_id)
        return index({}, state="no_source")
    monkeypatch.setattr(ideas_mod, "select_opportunities", fake_select)
    monkeypatch.setattr(ideas_mod, "chartink_index", fake_index)
    on = client.post("/api/desk/strategy/ideas", json=IDEAS_BODY, headers=A).json()
    assert on["inputs"]["include_chartink"] is True and on["inputs"]["chartink_limit"] == 4
    assert {"include_chartink", "chartink_limit"} <= set(on["inputs"]["defaults_applied"])
    assert seen["chartink"]["state"] == "no_source" and seen["chartink_limit"] == 4
    assert on["selection"]["chartink"]["state"] == "no_source"
    note = on["ranking_note"]
    assert "ranked by its score" in note and "only Chartink listed follow" in note and "not a probability" in note
    assert all(i["source"] == "ai_scanner" and i["chartink"] is None for i in on["ideas"])
    assert reads == ["user_a"]
    seen.clear()
    reads.clear()
    off = client.post("/api/desk/strategy/ideas", json={**IDEAS_BODY, "include_chartink": False, "chartink_limit": 2}, headers=A).json()
    assert off["inputs"]["include_chartink"] is False and off["inputs"]["chartink_limit"] == 2 and "include_chartink" not in off["inputs"]["defaults_applied"]
    assert "chartink_limit" not in off["inputs"]["defaults_applied"] and seen["chartink"] is None and reads == []        # switched off: Chartink was not even read
    assert off["selection"]["chartink"] is None and "Chartink" not in off["ranking_note"] and off["data_as_of"]["chartink"] is None


def test_ideas_carry_source_chartink_and_the_shared_index(client, monkeypatch):
    ix = index({"AAA": B3, "SYM0": B1})
    patch = {}

    async def fake_index(user_id, today):
        return ix

    async def fake_shared(user_id, chartink=None):
        patch["chartink"] = chartink
        return {"regime": src_ok({}, "x"), "sectors": src_ok({}, "x"), "portfolio": src_ok([], "x"), "sector_lists": {}, "chartink_index": chartink}
    monkeypatch.setattr(ideas_mod, "chartink_index", fake_index)
    monkeypatch.setattr(ideas_mod, "shared_for_ideas", fake_shared)
    s = client.state["selection"]
    only = sel.chartink_setup("AAA", {"scans": B3, "count": 3, "fetched_at": ix["fetched_at"], "bullish_scans": 3}, gate_row("AAA", name="Mock AAA Ltd"), ASOF)
    s["setups"][0] = {**s["setups"][0], "source": "both", "chartink": {"scans": B1, "count": 1, "fetched_at": ix["fetched_at"]}}
    s["setups"] = s["setups"][:2] + [only]
    s["chartink"] = {"included": True, "state": "ok", "scan_date": "2026-10-20", "fetched_at": ix["fetched_at"], "mode": "end_of_day_snapshot", "added": 1}
    b = client.post("/api/desk/strategy/ideas", json={**IDEAS_BODY, "chartink_limit": 1}, headers=A).json()
    assert patch["chartink"] is ix
    i0, i1, i2 = b["ideas"]
    assert (i0["source"], i0["chartink"]) == ("both", {"scans": B1, "count": 1, "fetched_at": ix["fetched_at"]})
    assert (i1["source"], i1["chartink"]) == ("ai_scanner", None)
    assert i2["symbol"] == "AAA" and i2["source"] == "chartink" and i2["chartink"] == {"scans": B3, "count": 3, "fetched_at": ix["fetched_at"]}
    assert i2["scanner"]["bucket"] is None and i2["scanner"]["score"] is None and i2["name"] == "Mock AAA Ltd" and i2["rank"] == 3
    assert [i["rank"] for i in b["ideas"]] == [1, 2, 3] and b["data_as_of"]["chartink"] == {"scan_date": "2026-10-20", "fetched_at": ix["fetched_at"], "mode": "end_of_day_snapshot"}
    assert b["selection"]["chartink"]["added"] == 1 and b["sent_to_broker"] is False


# ── the plan input and the source snapshot ───────────────────────────────────

def test_include_chartink_is_a_plan_input_with_a_disclosed_default():
    i = inputs()
    assert i["include_chartink"] is True and "include_chartink" in i["defaults_applied"]
    j = inputs(include_chartink=False)
    assert j["include_chartink"] is False and "include_chartink" not in j["defaults_applied"]
    i2, probs = pl.normalise_inputs({"underlying": "RELIANCE", "direction": "bullish", "include_chartink": "no"})
    assert i2 is None and probs[0]["code"] == "bad_include_chartink"


def test_chartink_snapshot_states():
    ix = index({"AAA": B2})
    s = sources.chartink_snapshot(ix, "AAA")
    assert s["ok"] and s["as_of"] == "2026-10-20" and s["version"] == STRATEGY_RULES_VERSION
    assert s["source"] == "Chartink scans (user's dashboard 123456), fetched 2026-10-20T11:00:00Z"
    assert s["data"]["hits"] == B2 and s["data"]["enabled_scans"] == 3 and s["data"]["close"] == 100.0
    none = sources.chartink_snapshot(ix, "ZZZ")
    assert none["ok"] and none["data"]["hits"] == []                                               # read fine, and no scan listed it
    for state in ("no_source", "not_refreshed", "stale", "failed"):
        bad = sources.chartink_snapshot(index({}, state=state), "AAA")
        assert bad["ok"] is False and bad["error"] == f"MOCK reason for {state}"
    off = sources.chartink_snapshot(None, "AAA")
    assert off["ok"] is False and "include_chartink" in off["error"]


def test_a_storage_failure_reading_the_index_is_a_failed_state_never_an_exception(monkeypatch):
    from services.chartink_desk import hits as hits_mod

    async def boom(db, user_id, today):
        raise RuntimeError("mongo down")
    monkeypatch.setattr(hits_mod, "read_index", boom)
    import deps
    monkeypatch.setattr(deps, "db", object(), raising=False)
    ix = run(sources.chartink_index("user_a", TODAY))
    assert ix["state"] == "failed" and "mongo down" in ix["reason"] and ix["symbols"] == {}
    assert sources.chartink_snapshot(ix, "AAA")["ok"] is False


# ── evidence ─────────────────────────────────────────────────────────────────

def snap_for(hits=None, **kw):
    return sources.chartink_snapshot(index({"AAA": hits} if hits is not None else {}, **kw), "AAA")


def test_evidence_item_directions():
    item = lambda s, d="bullish": ev.chartink_item({"chartink": s}, d)  # noqa: E731
    sup = item(snap_for(B2))
    assert (sup["group"], sup["key"], sup["direction"]) == ("technical", "chartink_scans", "supports")
    assert sup["value"]["count"] == 2 and [x["name"] for x in sup["value"]["scans"]] == ["Mock Alpha Scan", "Mock Beta Scan"]
    assert "Mock Alpha Scan, Mock Beta Scan" in sup["interpretation"] and "not validated" in sup["interpretation"] and "not a probability" in sup["interpretation"]
    assert sup["source"] == "Chartink scans (user's dashboard 123456), fetched 2026-10-20T11:00:00Z" and sup["source_as_of"] == "2026-10-20" and sup["version"] == STRATEGY_RULES_VERSION
    assert item(snap_for(BEAR))["direction"] == "conflicts"                                          # a bearish-tagged hit conflicts with a bullish view
    assert item(snap_for(B1 + BEAR))["direction"] == "neutral" and "neither way" in item(snap_for(B1 + BEAR))["interpretation"]
    assert item(snap_for(B1), "bearish")["direction"] == "conflicts" and item(snap_for(BEAR), "bearish")["direction"] == "supports"
    for d in ("neutral", "vol_expansion", "vol_contraction"):
        assert item(snap_for(B3), d)["direction"] == "neutral"
    assert item(snap_for([hit(5, "Mock Neutral", "neutral")]))["direction"] == "neutral"
    none = item(snap_for([]))
    assert none["direction"] == "neutral" and none["value"]["count"] == 0 and "None of the 3 enabled Chartink scans" in none["interpretation"]


def test_evidence_item_unavailable_with_the_reason():
    for state in ("no_source", "stale", "failed", "not_refreshed"):
        it = ev.chartink_item({"chartink": sources.chartink_snapshot(index({}, state=state), "AAA")}, "bullish")
        assert it["direction"] == "unavailable" and it["value"] is None and f"MOCK reason for {state}" in it["interpretation"]
    off = ev.chartink_item({"chartink": sources.chartink_snapshot(None, "AAA")}, "bullish")
    assert off["direction"] == "unavailable" and "switched off" in off["interpretation"]


def test_the_ledger_has_the_item_only_when_chartink_was_asked_for():
    plain = build(world(), instrument="cash")
    assert "chartink_scans" not in {e["key"] for e in plain["evidence"]}
    p = build(world(chartink=snap_for(B2)), instrument="cash")
    items = [e for e in p["evidence"] if e["key"] == "chartink_scans"]
    assert len(items) == 1 and items[0]["direction"] == "supports"
    base, withc = plain["evidence_summary"]["technical"], p["evidence_summary"]["technical"]
    assert withc["supports"] == base["supports"] + 1
    unavailable = build(world(chartink=sources.chartink_snapshot(index({}, state="no_source"), "RELIANCE")), instrument="cash")
    assert [e["direction"] for e in unavailable["evidence"] if e["key"] == "chartink_scans"] == ["unavailable"]
    assert "technical.chartink_scans" in unavailable["thesis"]["unavailable"]


def test_a_bearish_tagged_hit_counts_as_a_conflict_in_the_plan_gate():
    p = build(world(chartink=sources.chartink_snapshot(index({"RELIANCE": BEAR}), "RELIANCE")), instrument="cash")
    assert [e["direction"] for e in p["evidence"] if e["key"] == "chartink_scans"] == ["conflicts"]
    assert any(c["key"] == "chartink_scans" for c in p["thesis"]["conflicts"])


# ── the Chartink-only cash candidate ─────────────────────────────────────────

def ck(*hits, sym="RELIANCE"):
    return sources.chartink_snapshot(index({sym: list(hits)} if hits else {}), sym)


def no_bucket_world(**over):
    return world(scanner_bucket=bucket(None), **over)


def test_chartink_screen_signal_qualifies_with_levels_from_the_atr_rule():
    p = build(no_bucket_world(chartink=ck(*B2)), instrument="cash", **BIG)
    c = cand(p, "cash:chartink_screen_signal")
    assert c["status"] == "candidate" and c["segment"] == "cash" and c["family"] == "chartink_screen_signal" and c["label"] == "Chartink screen signal (long)"
    assert p["status"] == "plan" and p["preferred"] == "cash:chartink_screen_signal" and [x["id"] for x in p["candidates"]] == ["cash:chartink_screen_signal"]
    # the levels are the chart engine's ATR rule: stop 1160 (hypothetical_levels), entry the last close 1200, ATR 20, resistance 1290
    assert c["invalidation"]["technical"]["price"] == 1160.0 and c["legs"][0]["entry_price"] == 1200.0
    assert c["targets"] == cd.scenario_levels(1200.0, True, 1160.0, 20.0, 1290.0)
    assert "ATR" in c["invalidation"]["technical"]["basis"] and RULES["chartink"]["levels_label"] in c["invalidation"]["technical"]["basis"]
    assert RULES["chartink"]["levels_label"] == "rule-based levels; the scan is the user's Chartink scan, not validated"
    assert any(w == "Rule-based levels; the scan is the user's Chartink scan, not validated." for w in c["warnings"])
    assert "Mock Alpha Scan, Mock Beta Scan" in c["why_qualifies"][0] and "2 enabled bullish" in c["why_qualifies"][0]
    # sizing by the same rule as every cash candidate: floor(50 000 / 40) = 1250 shares, capped by 25% of 5 000 000 / 1200 = 1041
    assert c["sizing"]["quantity"] == 1041 and c["sizing"]["binding"] == "allocation_cap" and c["actionable"] is True
    assert c["payoff"]["valid"] and c["payoff"]["sent_to_broker"] is False and p["summary"]["sources"] == ["chartink"]


def test_the_plan_gates_decide_the_chartink_candidate_status():
    low_liq = build(no_bucket_world(chartink=ck(*B1), scan_row=scan_row(traded_value_cr_20d=5.0)), instrument="cash", **BIG)
    c = cand(low_liq, "cash:chartink_screen_signal")
    assert c["status"] == "no_trade" and "liquidity_below_gate" in codes(c) and low_liq["status"] == "no_trade"
    event = build(no_bucket_world(chartink=ck(*B1), events=events("2026-10-23")), instrument="cash", **BIG)
    assert cand(event, "cash:chartink_screen_signal")["status"] == "no_trade" and "event_in_horizon" in codes(cand(event, "cash:chartink_screen_signal"))
    rr = build(no_bucket_world(chartink=ck(*B1)), instrument="cash", min_reward_risk=50, **BIG)
    assert cand(rr, "cash:chartink_screen_signal")["status"] == "no_trade" and "reward_risk_below_minimum" in codes(cand(rr, "cash:chartink_screen_signal"))
    small = build(no_bucket_world(chartink=ck(*B1)), instrument="cash", capital=1000, risk_budget_inr=10)
    assert cand(small, "cash:chartink_screen_signal")["status"] == "no_trade" and "sizing_zero" in codes(cand(small, "cash:chartink_screen_signal"))
    # no usable ATR stop: not calculable, never a made-up level
    nostop = indicators()
    nostop["data"]["hypothetical_levels"] = None
    bad = build(no_bucket_world(chartink=ck(*B1), indicators=nostop), instrument="cash", **BIG)
    assert cand(bad, "cash:chartink_screen_signal")["status"] == "insufficient_data" and "risk_not_calculable" in codes(cand(bad, "cash:chartink_screen_signal"))


def test_no_chartink_candidate_without_an_enabled_bullish_hit():
    for snapshot in (ck(*BEAR), ck(), ck(hit(5, "Mock Neutral", "neutral")), sources.chartink_snapshot(index({}, state="failed"), "RELIANCE"),
                     sources.chartink_snapshot(None, "RELIANCE")):
        p = build(no_bucket_world(chartink=snapshot), instrument="cash", **BIG)
        assert [c["id"] for c in p["candidates"]] == ["cash:scanner"] and codes(p["candidates"][0]) == ["no_setup"] and p["status"] == "no_trade"
    assert build(no_bucket_world(), instrument="cash", **BIG)["candidates"][0]["id"] == "cash:scanner"      # no chartink key at all: as before
    bear = build(no_bucket_world(chartink=ck(*B2)), direction="bearish", instrument="cash")
    assert [c["id"] for c in bear["candidates"]] == ["cash:avoid"]                                          # a bearish view has no cash entry whatever the scans say


def test_a_scanner_setup_is_not_replaced_by_the_chartink_candidate():
    p = build(world(chartink=ck(*B3)), instrument="cash", **BIG)
    assert [c["id"] for c in p["candidates"]] == ["cash:breakout_continuation"] and p["summary"]["sources"] == ["ai_scanner", "chartink"]
    assert cand(p, "cash:breakout_continuation")["status"] == "candidate"
    only_scanner = build(world(chartink=ck()), instrument="cash", **BIG)
    assert only_scanner["summary"]["sources"] == ["ai_scanner"]
    neither = build(no_bucket_world(), instrument="cash", **BIG)
    assert neither["summary"]["sources"] == []


def test_chartink_stock_gets_every_segment_like_any_other_stock():
    p = build(no_bucket_world(chartink=ck(*B2)), **BIG)
    segs = {c["segment"] for c in p["candidates"]}
    assert "cash" in segs and {"futures", "options"} <= segs
    assert cand(p, "cash:chartink_screen_signal")["status"] == "candidate"


# ── versions and honesty ─────────────────────────────────────────────────────

def test_rules_version_is_1_4_and_carries_the_chartink_constants():
    assert STRATEGY_RULES_VERSION.startswith("strategy-rules.v1.4") and RULES["version"] == STRATEGY_RULES_VERSION
    C = RULES["chartink"]
    assert C["include_default"] is True and (C["limit_default"], C["limit_max"]) == (4, 8) and C["cash_family"] == "chartink_screen_signal"
    assert {"ranking", "gates", "evidence", "cash_rule", "levels_label", "stale_after_calendar_days", "eod_after_ist"} <= set(C)
    p = build(world(), instrument="cash")
    assert p["rules_version"] == STRATEGY_RULES_VERSION and p["rules"]["chartink"] == C


def test_nothing_in_the_chartink_merge_can_send_anything_to_a_broker():
    p = build(no_bucket_world(chartink=ck(*B2)), **BIG)
    assert p["sent_to_broker"] is False and all(c["sent_to_broker"] is False for c in p["candidates"])
    for mod in (sel, ideas_mod, cd, ev, sources):
        text = open(mod.__file__).read()
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        assert not re.search(r"(place|modify|cancel|submit)[_ ]?order", code, re.I), mod.__name__


# ── collect_snapshots: the chartink source ───────────────────────────────────

def stub_other_sources(monkeypatch):
    for name in ("_regime", "_sectors", "_indicators", "_patterns", "_scan_snapshot", "_features", "_financials", "_announcements", "_events", "_corporate_actions",
                 "_buildup", "_futures", "_expiries", "_calibration", "_scanner_bucket", "_portfolio", "_shareholding", "_deals"):
        async def f(*a, _n=name, **k):
            return src_fail("not under test", _n)
        monkeypatch.setattr(sources, name, f)


def test_collect_snapshots_uses_the_shared_index_or_reads_it_once_and_respects_the_switch(monkeypatch):
    stub_other_sources(monkeypatch)
    reads = []

    async def fake_index(user_id, today):
        reads.append(user_id)
        return index({"TCS": B2})
    monkeypatch.setattr(sources, "chartink_index", fake_index)
    shared = {"regime": src_ok({}, "s"), "sectors": src_ok({}, "s"), "portfolio": src_ok([], "s"), "sector_lists": {}, "chartink_index": index({"TCS": B1})}
    on = pl.normalise_inputs({"underlying": "TCS", "direction": "bullish"})[0]
    snaps = run(sources.collect_snapshots(None, "u", on, TODAY, shared))
    assert snaps["chartink"]["ok"] and snaps["chartink"]["data"]["hits"] == B1 and reads == []         # the request's own index: no second read
    snaps = run(sources.collect_snapshots(None, "u", on, TODAY))
    assert snaps["chartink"]["data"]["hits"] == B2 and reads == ["u"]                                  # a single plan reads it itself
    off = pl.normalise_inputs({"underlying": "TCS", "direction": "bullish", "include_chartink": False})[0]
    snaps = run(sources.collect_snapshots(None, "u", off, TODAY))
    assert snaps["chartink"]["ok"] is False and "switched off" in snaps["chartink"]["error"] and reads == ["u"]
    hand_built = {k: v for k, v in on.items() if k != "include_chartink"}
    assert run(sources.collect_snapshots(None, "u", hand_built, TODAY))["chartink"]["ok"] is False and reads == ["u"]
