"""Symbol lookup (services/symbol_lookup.py, routes/symbol_lookup.py) and the plan route's `unknown_symbol` answer.

MOCK — not real data: the universe below is hand-made, shaped like DaaS /v1/symbols/universe rows (a few real NSE names so the cases read
naturally; market caps are round numbers chosen so the tie-break order can be checked by hand). No network, no database.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.symbol_lookup as route
import routes.strategy_plan as plan_route
from services import symbol_lookup as sl
from services.strategy_plan import sources as src
from services.strategy_plan.evidence import src_fail

D = "2026-10-19"


def row(sym, name, isin=None, mc=None, fno=False, last=D, sector="Sector", industry="Industry"):
    return {"symbol": sym, "company_name": name, "isin": isin, "series": "EQ", "sector": sector, "industry": industry,
            "last_price_date": last, "fno_eligible": fno, "market_cap_cr": mc}


ROWS: List[Dict[str, Any]] = [
    row("RELIANCE", "Reliance Industries Limited", "INE002A01018", 1500000, True),
    row("RELIGARE", "Religare Enterprises Limited", "INE621H01010", 3000, False),
    row("RELAXO", "Relaxo Footwears Limited", "INE131B01039", 9000, False),
    row("PCJEWELLER", "PC Jeweller Limited", "INE785M01021", 14000, False),
    row("PCBL", "PCBL Chemical Limited", "INE602A01031", 15000, True),
    row("HDFCBANK", "HDFC Bank Limited", "INE040A01034", 1200000, True),
    row("HDFCLIFE", "HDFC Life Insurance Company Limited", "INE795G01014", 150000, True),
    row("HDFCAMC", "HDFC Asset Management Company Limited", "INE127D01025", 100000, True),
    row("TATAMOTORS", "Tata Motors Limited", "INE155A01022", 300000, True),
    row("TATASTEEL", "Tata Steel Limited", "INE081A01020", 200000, True),
    row("ZOMATO", "Zomato Limited", "INE758T01015", 250000, True),
    row("DELISTCO", "Delist Company Limited", "INE000Z01011", None, False, last=None),      # on the master, no bars
    row("ABSLLIQUID", None, None, None, None),                                              # prices only, no master row
]


def universe(rows=None, scanner=None) -> sl.Universe:
    return sl.Universe(rows or ROWS, "MOCK", D, scanner)


def syms(res):
    return [r["symbol"] for r in res]


def find(q, **kw):
    u = kw.pop("u", None) or universe(scanner={"RELIANCE", "PCBL"})
    return [sl.public(h) for h in sl.search(u, sl.normalise(q), **kw)]


# ── ranking ──────────────────────────────────────────────────────────────────

def test_exact_symbol_first_then_prefix_by_market_cap():
    r = find("reliance")
    assert r[0]["symbol"] == "RELIANCE" and r[0]["match"] == "exact" and r[0]["matched_on"] == "symbol"
    r = find("rel")
    assert syms(r)[:3] == ["RELIANCE", "RELAXO", "RELIGARE"]                       # prefix tier, biggest market cap first
    assert all(x["match"] == "prefix" for x in r[:3])


def test_company_name_word_prefix_finds_pc_jeweller():
    r = find("pc jew")
    assert r[0]["symbol"] == "PCJEWELLER"
    r = find("industries limited")
    assert r[0]["symbol"] == "RELIANCE" and r[0]["match"] == "name_prefix" and r[0]["matched_on"] == "name"
    assert r[0]["highlight"]["name"] == [[9, 19], [20, 27]]                        # "Industries", "Limited" in "Reliance Industries Limited"


def test_plural_singular_variant_pcjewellers_gives_pcjeweller():
    r = find("pcjewellers")
    assert syms(r)[0] == "PCJEWELLER" and r[0]["match"] == "variant"
    assert find("tatasteels")[0]["symbol"] == "TATASTEEL"
    assert find("PCJEWELLERS", u=universe([row("PCJEWELLERS", "X Ltd")] + ROWS))[0]["match"] == "exact"      # a real symbol with an S is itself


def test_isin_exact_and_partial():
    r = find("INE002A01018")
    assert syms(r) == ["RELIANCE"] and r[0]["match"] == "isin" and r[0]["matched_on"] == "isin"
    assert syms(find("INE040A0")) == ["HDFCBANK"]
    assert find("INE999Z99999") == []


def test_typo_edit_distance_and_short_ticker_rule():
    assert find("RELIANSE")[0]["symbol"] == "RELIANCE" and find("RELIANSE")[0]["match"] == "edit_distance"
    assert find("RELAINCE")[0]["symbol"] == "RELIANCE"                              # a swap of neighbours counts as one edit
    assert find("TATASTEL")[0]["symbol"] == "TATASTEEL"
    assert find("PCBX") == [] or find("PCBX")[0]["symbol"] == "PCBL"                 # a 4-letter text: one edit at most
    assert "PCBL" not in syms(find("PCXX"))                                         # two edits on a short ticker: no match
    assert find("ZZ") == []                                                         # under 3 characters: no fuzzy matching
    assert damerau_ok()


def damerau_ok():
    return sl.damerau("RELIANCE", "RELIANSE", 2) == 1 and sl.damerau("ABCD", "BACD", 2) == 1 and sl.damerau("ABC", "XYZ", 1) == 2


def test_name_word_typos_are_tight():
    assert "HDFCBANK" in syms(find("hdfc")) and find("IDFC", u=universe(ROWS + [row("IDFCFIRSTB", "IDFC First Bank Limited")]))[0]["symbol"] == "IDFCFIRSTB"
    assert find("jewler") == []                                                          # two edits on an 8-letter word: not offered
    assert find("BORGLA") == []                                                          # nothing within the rules: no invented neighbour
    assert find("PCJEWELLERS")[0]["symbol"] == "PCJEWELLER" and syms(find("PCJEWELLERS")) == ["PCJEWELLER"]


def test_contains_never_spans_two_words_of_a_name():
    u = universe(ROWS + [row("FORTIS", "Fortis Healthcare Limited", mc=1)])
    assert "FORTIS" not in syms(find("rel", u=u, limit=20))                              # "HealthCARE LImited" holds REL only across a word break
    assert find("jewel")[0]["symbol"] == "PCJEWELLER"


def test_typo_in_a_company_word():
    r = find("jeweler")                                                    # one edit from the name word JEWELLER
    assert r and r[0]["symbol"] == "PCJEWELLER"


def test_contains_symbol_and_name():
    assert "HDFCAMC" in syms(find("FCAM"))
    assert find("FCAM")[0]["match"] == "contains"
    r = find("asset management")
    assert r[0]["symbol"] == "HDFCAMC" and r[0]["match"] == "name_prefix"


def test_stock_with_no_price_history_is_returned_but_ranks_lower():
    r = find("del")
    assert r[0]["symbol"] == "DELISTCO" and r[0]["has_prices"] is False
    both = universe([row("AAAX", "A Co", mc=1, last=None), row("AAAY", "B Co", mc=1)])
    assert syms([sl.public(h) for h in sl.search(both, "AAA", 5)]) == ["AAAY", "AAAX"]
    assert find("DELISTCO")[0]["match"] == "exact"                                  # an exact ticker still comes first


def test_price_only_symbol_has_no_invented_name():
    r = find("abslliq")[0]
    assert r["symbol"] == "ABSLLIQUID" and r["name"] is None and r["isin"] is None


def test_flags_and_fields_come_from_the_rows():
    r = find("reliance")[0]
    assert r["fno_eligible"] is True and r["in_scanner"] is True and r["last_price_date"] == D and r["has_prices"] is True
    assert find("relaxo")[0]["in_scanner"] is False
    assert universe(scanner=None).entries["RELIANCE"]["in_scanner"] is None        # unknown, never "no"


def test_fno_only_and_limit():
    r = find("h", fno_only=True)
    assert set(syms(r)) <= {"HDFCBANK", "HDFCLIFE", "HDFCAMC"}
    assert find("rel", fno_only=True)[0]["symbol"] == "RELIANCE" and len(find("rel", fno_only=True)) == 1
    assert len(find("t", limit=1)) == 1


def test_ties_break_by_market_cap_then_symbol():
    u = universe([row("ABCA", "N Co", mc=5), row("ABCB", "N Co", mc=5), row("ABCC", "N Co", mc=9)])
    assert syms([sl.public(h) for h in sl.search(u, "ABC", 5)]) == ["ABCC", "ABCA", "ABCB"]


def test_nonsense_matches_nothing():
    assert find("QQQQXZXZ") == []


def test_highlight_ranges_for_symbol_prefix():
    assert find("rel")[0]["highlight"]["symbol"] == [[0, 3]]


# ── input rules ──────────────────────────────────────────────────────────────

def test_normalise_rules():
    assert sl.normalise("  pc   jeweller ") == "PC JEWELLER" and sl.normalise(None) == "" and sl.normalise("") == ""
    assert sl.normalise("m&m") == "M&M" and sl.normalise("bajaj-auto") == "BAJAJ-AUTO"
    for bad in ("x" * 41, "a;drop", "a/b", "<b>", "a\u0000"):
        with pytest.raises(sl.BadQuery):
            sl.normalise(bad)


def test_strong_suggestion_only_when_exactly_one_close():
    assert sl.strong_suggestion(find("pcjewellers"))["symbol"] == "PCJEWELLER"
    assert sl.strong_suggestion(find("rel")) is None


# ── speed: a large synthetic universe ────────────────────────────────────────

def test_warm_search_is_fast_on_a_large_universe():
    import random
    rnd = random.Random(7)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    big = []
    for i in range(6000):
        s = "".join(rnd.choice(letters) for _ in range(rnd.randint(4, 12)))
        big.append(row(s + str(i % 7 if i % 3 == 0 else ""), f"{s.title()} {rnd.choice(['Industries', 'Bank', 'Finance', 'Motors'])} Limited", mc=float(rnd.randint(1, 10 ** 6))))
    u = universe(ROWS + big)
    worst = 0.0
    for q in ("r", "reli", "pc jew", "hdfc", "INE002A01018", "pcjewellers", "qqzzxx", "industries lim", "fcam", "tatasteal"):
        t = time.perf_counter()
        sl.search(u, sl.normalise(q), 8)
        worst = max(worst, time.perf_counter() - t)
    assert worst < 0.150, f"slowest query took {worst * 1000:.0f} ms"


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    sl.reset_cache()
    calls = {"universe": 0}

    async def fake_raw(path, params=None, timeout=10.0):
        if path == "/symbols/universe":
            calls["universe"] += 1
            return 200, {"data": ROWS}
        raise AssertionError(path)

    monkeypatch.setattr(sl.daas_client, "get_raw", fake_raw)

    async def no_scan():
        raise HTTPException(status_code=502, detail="x")
    from routes import positional
    monkeypatch.setattr(positional, "_scan_snapshot", no_scan)

    async def fake_user(request: Request):
        if not request.headers.get("X-Test-User"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": "u"}
    monkeypatch.setattr(route, "get_current_user", fake_user)

    async def fake_sel(request, limit):
        return {"source": "MOCK scanner", "setups": [{"symbol": "PCBL"}, {"symbol": "NOSUCH"}, {"symbol": "RELIANCE"}], "empty_reason": None}
    import services.strategy_plan.selection as selection
    monkeypatch.setattr(selection, "select_opportunities", fake_sel)
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    c.calls, c.h = calls, {"X-Test-User": "u"}
    yield c
    sl.reset_cache()


def test_route_requires_sign_in(client):
    assert client.get("/api/markets/symbol-lookup?q=rel").status_code == 401


def test_route_exact_and_results_shape(client):
    r = client.get("/api/markets/symbol-lookup?q=reliance", headers=client.h)
    b = r.json()
    assert r.status_code == 200 and b["exact"]["symbol"] == "RELIANCE" and b["results"][0]["symbol"] == "RELIANCE" and b["reason"] is None
    assert b["count"] == len(b["results"]) and "MOCK" not in b["source"] and b["source"].startswith("DaaS")
    assert b["results"][0]["in_scanner"] is None                       # the scan snapshot was unreadable: unknown, not false


def test_route_name_isin_and_variant(client):
    assert client.get("/api/markets/symbol-lookup?q=pc%20jew", headers=client.h).json()["results"][0]["symbol"] == "PCJEWELLER"
    assert client.get("/api/markets/symbol-lookup?q=INE002A01018", headers=client.h).json()["results"][0]["match"] == "isin"
    b = client.get("/api/markets/symbol-lookup?q=PCJEWELLERS", headers=client.h).json()
    assert b["exact"] is None and b["results"][0]["symbol"] == "PCJEWELLER" and b["results"][0]["match"] == "variant"


def test_route_no_match_has_a_reason(client):
    b = client.get("/api/markets/symbol-lookup?q=QQQQXZXZ", headers=client.h).json()
    assert b["results"] == [] and b["exact"] is None and b["reason"] == "No NSE stock matches QQQQXZXZ."


def test_route_bad_input(client):
    for url in ("/api/markets/symbol-lookup?q=" + "x" * 41, "/api/markets/symbol-lookup?q=a%3Bb", "/api/markets/symbol-lookup?q=rel&limit=0",
                "/api/markets/symbol-lookup?q=rel&limit=21"):
        r = client.get(url, headers=client.h)
        assert r.status_code == 422, url
    assert client.get("/api/markets/symbol-lookup?q=a%3Bb", headers=client.h).json()["detail"]["code"] == "invalid_query"


def test_route_empty_query_gives_popular_and_recent_from_real_rows_only(client):
    b = client.get("/api/markets/symbol-lookup?q=&recent=HDFCBANK,NOSUCH,bad!sym,RELIANCE", headers=client.h).json()
    assert b["results"] == [] and b["reason"] is None
    assert [p["symbol"] for p in b["popular"]] == ["PCBL", "RELIANCE"] and b["popular_source"] == "MOCK scanner"      # NOSUCH is not invented
    assert [p["symbol"] for p in b["recent"]] == ["HDFCBANK", "RELIANCE"]
    f = client.get("/api/markets/symbol-lookup?q=&fno_only=true&recent=RELAXO,HDFCBANK", headers=client.h).json()
    assert [p["symbol"] for p in f["recent"]] == ["HDFCBANK"]


def test_route_caches_the_universe(client):
    for q in ("a", "b", "c"):
        client.get(f"/api/markets/symbol-lookup?q={q}", headers=client.h)
    assert client.calls["universe"] == 1


def test_stale_universe_is_served_when_a_refresh_fails(client, monkeypatch):
    client.get("/api/markets/symbol-lookup?q=a", headers=client.h)
    sl._cache["at"] = time.monotonic() - sl.CACHE_TTL_S - 1

    async def boom(path, params=None, timeout=10.0):
        raise sl.daas_client.DaasError("down")
    monkeypatch.setattr(sl.daas_client, "get_raw", boom)
    r = client.get("/api/markets/symbol-lookup?q=reliance", headers=client.h)
    assert r.status_code == 200 and r.json()["exact"]["symbol"] == "RELIANCE"


def test_unreadable_universe_is_502_not_empty(client, monkeypatch):
    sl.reset_cache()

    async def down(path, params=None, timeout=10.0):
        return 503, None
    monkeypatch.setattr(sl.daas_client, "get_raw", down)
    r = client.get("/api/markets/symbol-lookup?q=rel", headers=client.h)
    assert r.status_code == 502 and r.json()["detail"] == "lookup_unavailable"


def test_fallback_to_the_plain_symbol_list_leaves_price_days_unknown(client, monkeypatch):
    sl.reset_cache()

    async def old_daas(path, params=None, timeout=10.0):
        if path == "/symbols/universe":
            return 404, None
        return 200, {"data": [{"symbol": "RELIANCE", "company_name": "Reliance Industries Limited", "isin": "INE002A01018"}]}
    monkeypatch.setattr(sl.daas_client, "get_raw", old_daas)
    b = client.get("/api/markets/symbol-lookup?q=reliance", headers=client.h).json()
    assert b["exact"]["has_prices"] is None and b["exact"]["last_price_date"] is None and "not deployed" in b["source"]


def test_fallback_takes_fno_cap_and_price_day_from_the_scan_snapshot_only_for_stocks_in_it(client, monkeypatch):
    sl.reset_cache()

    async def old_daas(path, params=None, timeout=10.0):
        if path == "/symbols/universe":
            return 404, None
        return 200, {"data": [{"symbol": "RELIANCE", "company_name": "Reliance Industries Limited", "isin": "INE002A01018"},
                              {"symbol": "ZOMATO", "company_name": "Zomato Limited", "isin": "INE758T01015"}]}
    monkeypatch.setattr(sl.daas_client, "get_raw", old_daas)

    async def snap():
        return {"rows": [{"symbol": "RELIANCE", "fno_eligible": True, "market_cap_cr": 1500000, "price_date": "2026-10-19"}]}
    from routes import positional
    monkeypatch.setattr(positional, "_scan_snapshot", snap)
    r = client.get("/api/markets/symbol-lookup?q=reliance", headers=client.h).json()["exact"]
    assert r["fno_eligible"] is True and r["has_prices"] is True and r["last_price_date"] == "2026-10-19" and r["in_scanner"] is True
    z = client.get("/api/markets/symbol-lookup?q=zomato", headers=client.h).json()["exact"]
    assert z["has_prices"] is None and z["in_scanner"] is False        # not in the scan: price history unknown, never "no prices"


# ── the plan route ───────────────────────────────────────────────────────────

NOBARS = "HTTP 404: no_bars_for_symbol"


def test_unknown_symbol_reason_only_for_a_404_with_no_bars():
    from services.strategy_plan import plan as pl
    assert pl.is_unknown_symbol(NOBARS) and not pl.is_unknown_symbol("HTTP 502: upstream_unavailable")
    assert not pl.is_unknown_symbol("HTTP 404: something_else") and not pl.is_unknown_symbol("TimeoutError: ")


def _plan_for(sym: str, error: str):
    from tests import test_strategy_plan as t
    i = t.inputs(underlying=sym)
    return t.pl.build_plan(i, t.world(indicators=src_fail(error, "x")), t.NOW, t.TODAY)


def test_plan_unknown_symbol_gets_suggestions_and_keeps_the_input(client):
    p = _plan_for("PCJEWELLERS", NOBARS)
    assert p["status"] == "insufficient_data" and p["candidates"] == []
    assert [r["code"] for r in p["status_reasons"]] == ["unknown_symbol"] and p["inputs"]["underlying"] == "PCJEWELLERS"
    p = asyncio.run(src.attach_symbol_suggestions(p))
    r = p["status_reasons"][0]
    assert r["message"] == "No price history for PCJEWELLERS. Did you mean PCJEWELLER (PC Jeweller Limited)?"
    assert r["suggested"] == "PCJEWELLER" and r["suggestions"][0]["symbol"] == "PCJEWELLER" and p["symbol_suggestions"] == r["suggestions"]
    assert p["inputs"]["underlying"] == "PCJEWELLERS" and p["underlying"]["symbol"] == "PCJEWELLERS"


def test_plan_unknown_symbol_without_a_match_says_so(client):
    p = asyncio.run(src.attach_symbol_suggestions(_plan_for("QQQQXZXZ", NOBARS)))
    r = p["status_reasons"][0]
    assert r["suggestions"] == [] and r["suggested"] is None and r["message"] == "No price history for QQQQXZXZ. No NSE stock matches QQQQXZXZ."


def test_plan_symbol_listed_without_bars_is_named(client):
    p = asyncio.run(src.attach_symbol_suggestions(_plan_for("DELISTCO", NOBARS)))
    assert "DELISTCO (Delist Company Limited) is on the NSE symbol master, but the data platform holds no end-of-day bars" in p["status_reasons"][0]["message"]


def test_plan_lookup_failure_leaves_the_plan_as_built(client, monkeypatch):
    sl.reset_cache()

    async def down(path, params=None, timeout=10.0):
        return 503, None
    monkeypatch.setattr(sl.daas_client, "get_raw", down)
    p = asyncio.run(src.attach_symbol_suggestions(_plan_for("PCJEWELLERS", NOBARS)))
    assert p["status_reasons"][0]["code"] == "unknown_symbol" and "suggestions" not in p["status_reasons"][0] and "symbol_suggestions" not in p


def test_real_outage_stays_required_source_failed(client):
    for err in ("HTTP 502: upstream_unavailable", "HTTP 503: x", "TimeoutError: read timed out"):
        p = asyncio.run(src.attach_symbol_suggestions(_plan_for("RELIANCE", err)))
        assert [r["code"] for r in p["status_reasons"]] == ["required_source_failed"] and "symbol_suggestions" not in p


def test_plan_route_attaches_suggestions(client, monkeypatch):
    from tests import test_strategy_plan as t

    async def collect(request, user_id, inp, today):
        return t.world(indicators=src_fail(NOBARS, "x"))
    monkeypatch.setattr(plan_route, "collect_snapshots", collect)
    monkeypatch.setattr(plan_route, "utcnow", lambda: t.NOW)
    monkeypatch.setattr(plan_route, "today", lambda: t.TODAY)

    async def fake_user(request: Request):
        return {"user_id": "u"}
    monkeypatch.setattr(plan_route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(plan_route.router)
    r = TestClient(app).post("/api/desk/strategy/plan", json={**t.BODY, "underlying": "PCJEWELLERS"})
    b = r.json()
    assert r.status_code == 200 and b["status"] == "insufficient_data" and b["status_reasons"][0]["code"] == "unknown_symbol"
    assert b["status_reasons"][0]["suggested"] == "PCJEWELLER" and b["sent_to_broker"] is False
