"""Research Copilot W1: the five research answers (services/copilot_visual/research_*.py) and the routing fixture.

Covers TC-R1 … TC-R7, TC-B1 … TC-B9 and TC-D1 of test_reports/research_answers_w1_TESTCASES.md. TC-S* (real staging data) are
in the report, not here.

What is replaced (MOCK — not real data; the company ACME, its peers and every figure below are invented): the readers in
services/copilot_visual/research_readers.py (each DaaS read) and the freshness window. The resolver, the builders, the contract
check (payload.validate) and the facts block run for real. The DaaS cash-flow route runs against a fake connection pool.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pytest

from services import market_freshness
from services.copilot_visual import builders, readers as rd, research_readers as rr
from services.copilot_visual.intents import INTENTS, Intent, resolve_intent, stock_in, wants_thread_symbol
from services.copilot_visual.payload import Sources, facts, validate
from services.copilot_visual.research_intents import RESEARCH_INTENTS

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "research_copilot_routing.json").read_text())
TODAY, FLOOR = date(2026, 10, 30), date(2026, 10, 29)
WINDOW = market_freshness.Window(today=TODAY, floor=FLOOR, calendar_checked=True)
W1 = set(RESEARCH_INTENTS)


# ═════ TC-R1: the owner's questions as a routing fixture ════════════════════════════════════════════════════════════

def _ok(expected: Any, got: Any) -> bool:
    name = got.name if got is not None else None
    return name not in W1 if expected == "not_w1" else name == expected


NAMED = [(c, a, b) for c in FIXTURE["cases"] for a, b in FIXTURE["fillers"]]


@pytest.mark.parametrize("case, a, b", NAMED, ids=[f"{c['category']}:{c['source_text'][:40]}:{a}" for c, a, b in NAMED])
def test_r1_fixture_named_company(case, a, b):
    q = case["question"].replace("{company}", a).replace("{company2}", b)
    got = resolve_intent(q, None, None)
    assert _ok(case["expected"], got), (q, case["expected"], got)
    if got is not None and got.name in W1:
        syms = FIXTURE["filler_symbols"]
        if "HDFC Bank, ICICI Bank and Axis Bank" in q:
            assert got.params["symbols"] == ["HDFCBANK", "ICICIBANK", "AXISBANK"]
        else:
            assert got.symbol == syms[a] and not got.symbol_from_thread, (q, got)
        if "{company2}" in case["question"]:
            assert got.params["symbols"] == [syms[a], syms[b]], (q, got.params)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[f"{c['category']}:{c['source_text'][:50]}" for c in FIXTURE["cases"]])
def test_r1_fixture_thread_company(case):
    """The owner's question as written (no company) while the thread's last stock is TCS."""
    q = case["source_text"].replace("[Company]", "this company")
    got = resolve_intent(q, None, None, last_symbol=FIXTURE["thread_symbol"])
    assert _ok(case["thread_expected"], got), (q, case["thread_expected"], got)
    if got is not None and got.name in W1 and "HDFC Bank" not in q:
        assert (got.symbol, got.symbol_from_thread) == ("TCS", True), (q, got)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[f"{c['category']}:{c['source_text'][:50]}" for c in FIXTURE["cases"]])
def test_r1_fixture_no_company_no_thread_is_never_a_company_answer(case):
    """AC-RC-09: no company and no thread stock → never a company answer (the stock analyst then asks which company)."""
    q = case["source_text"].replace("[Company]", "this company")
    got = resolve_intent(q, None, None)
    if "HDFC Bank, ICICI Bank and Axis Bank" in q:
        assert got is not None and got.name == "peer_compare"
    else:
        assert got is None or got.name not in W1, (q, got)


def test_r1_fixture_pass_rate_is_complete():
    total = passed = 0
    for c, a, b in NAMED:
        total += 1
        passed += _ok(c["expected"], resolve_intent(c["question"].replace("{company}", a).replace("{company2}", b), None, None))
    for c in FIXTURE["cases"]:
        total += 1
        passed += _ok(c["thread_expected"], resolve_intent(c["source_text"].replace("[Company]", "this company"), None, None, last_symbol="TCS"))
    assert len(FIXTURE["cases"]) >= 100 and passed == total, f"{passed}/{total}"
    for c in FIXTURE["cases"]:                         # every expectation is a real intent, null or not_w1
        for k in ("expected", "thread_expected"):
            assert c[k] in INTENTS or c[k] in (None, "not_w1"), c


# ═════ TC-R2 … TC-R6: the deliberate routing decisions ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("message, persona, last, expected", [
    ("Build a research thesis for TCS", None, None, None),
    ("Build a complete research thesis for Reliance", None, None, None),
    ("Give me the investment case for HDFC Bank", None, None, None),
    ("Build a research thesis", "trader", "TCS", None),                          # the thread's stock is not a trade either
    ("Has my thesis on INFY weakened?", None, None, ("trade_validity", "INFY")),
    ("Is my trade in TCS still valid?", "trader", None, ("trade_validity", "TCS")),
    ("Is TCS still valid as a setup?", "trader", None, ("trade_validity", "TCS")),
    ("Is margin weakening for TCS?", None, None, ("financial_trend", "TCS")),
    ("Has the TCS setup weakened?", "trader", None, ("trade_validity", "TCS")),
])
def test_r2_research_thesis_is_never_trade_validity(message, persona, last, expected):
    got = resolve_intent(message, persona, None, last_symbol=last)
    assert (None if got is None else (got.name, got.symbol)) == expected, (message, got)


@pytest.mark.parametrize("message, expected", [
    ("Has promoter holding of TCS increased?", ("ownership_trend", "TCS")),
    ("Show promoter holding over time for ADANIPORTS", ("ownership_trend", "ADANIPORTS")),
    ("What is the promoter holding of TCS?", ("ownership_trend", "TCS")),
    ("Is smart money accumulating INFY?", ("ownership_trend", "INFY")),
    ("Has there been promoter pledge change in INFY?", ("event_intelligence", "INFY")),
    ("Any ownership filings for TCS?", ("event_intelligence", "TCS")),
    ("Any SAST disclosures for TCS?", ("event_intelligence", "TCS")),
    ("Show promoter holding changes", ("event_intelligence", None)),
    ("Any promoter pledge this week?", ("event_intelligence", None)),
])
def test_r3_ownership_trend_vs_event(message, expected):
    got = resolve_intent(message)
    assert got is not None and (got.name, got.symbol) == expected, (message, got)


def test_r4_thread_stock_for_a_company_question_that_names_none():
    got = resolve_intent("What is the current ratio?", None, None, last_symbol="TCS")
    assert (got.name, got.symbol, got.symbol_from_thread) == ("company_risks", "TCS", True)
    assert resolve_intent("What is the current ratio?", None, None) is None
    assert wants_thread_symbol("What is the current ratio?") and wants_thread_symbol("Has FII ownership increased?")
    assert not wants_thread_symbol("What is the market view today?")
    # the market-wide event feed's wording keeps going to the feed, even with a stock in the thread
    assert resolve_intent("Show promoter holding changes", None, None, last_symbol="TCS").name == "event_intelligence"
    assert resolve_intent("Any promoter pledge this week?", None, None, last_symbol="TCS").name == "event_intelligence"
    assert resolve_intent("Show FII ownership changes over 4 quarters.", None, None, last_symbol="TCS").name == "ownership_trend"
    # the trade answers keep the thread's stock as before
    assert resolve_intent("Should I book profits?", "trader", None, last_symbol="INFY").name == "exit_options"
    assert resolve_intent("Is this trade still valid?", "trader", None, last_symbol="TVSMOTOR").name == "trade_validity"


@pytest.mark.parametrize("message", [
    "Which stocks are FIIs accumulating?", "Find stocks with increasing FII and DII ownership.", "Which sectors have the best margins?",
    "Where is smart money moving?", "What is the market view today?", "Which debt funds have the best returns?",
    "How is my portfolio doing?", "Show stocks with ROE over 20 and debt to equity under 0.5",
])
def test_r5_market_wide_questions_never_use_the_thread_stock(message):
    got = resolve_intent(message, None, None, last_symbol="TCS")
    assert got is None or got.name not in W1, (message, got)


def test_r6_several_companies_and_metric_words():
    got = resolve_intent("Compare HDFC Bank, ICICI Bank and Axis Bank across fundamentals, valuation, growth, profitability, asset quality "
                         "and institutional ownership.")
    assert got.name == "peer_compare" and got.params["symbols"] == ["HDFCBANK", "ICICIBANK", "AXISBANK"]
    assert resolve_intent("Compare TCS and Infosys").params["symbols"] == ["TCS", "INFY"]
    one = resolve_intent("Compare RADICO and Some Unknown Distiller")
    assert one.name == "peer_compare" and one.params == {"symbols": ["RADICO"], "one_recognised": True}
    for word in ("What is its EV/EBITDA?", "Is FCF positive?", "Show GNPA and NNPA", "What is the NIM?", "TTM EPS"):
        assert stock_in(word) is None, word
    assert resolve_intent("What happens if TCS earnings grow by 15%, 20%, or 25%?").params == {"growth": [15.0, 20.0, 25.0]}
    assert resolve_intent("How has revenue grown over the last 5 years for INFY?").params == {"years": 5}


def test_r6_causal_and_segment_questions_get_no_visual():
    for q in ("Why did margins decline for TCS?", "What is driving TCS's profit growth?", "Which segment contributed most to TCS's growth?"):
        got = resolve_intent(q)
        assert got is None or got.name not in W1, q


# ═════ the readers, replaced (MOCK — not real data) ═════════════════════════════════════════════════════════════════

def q_row(d, rev, ebitda, pat, src="trendlyne_mcp", cons=True, bs=None, bc=None, kind="quarterly", **kw):
    r = {"symbol": "ACME", "period_end": d, "period_type": kind, "consolidated": cons, "source": src, "revenue_from_ops_cr": rev,
         "ebitda_cr": ebitda, "pat_cr": pat, "broadcast_at": bc, "total_equity_cr": None, "long_term_debt_cr": None,
         "short_term_debt_cr": None, "cash_and_equiv_cr": None, "current_assets_cr": None, "current_liabilities_cr": None,
         "trade_receivables_cr": None, "inventory_cr": None, "trade_payables_cr": None, "bs_truedata": False}
    if bs:
        eq, ltd, std, ca, cl, rec, inv, cash = bs
        r.update(total_equity_cr=eq, long_term_debt_cr=ltd, short_term_debt_cr=std, current_assets_cr=ca, current_liabilities_cr=cl,
                 trade_receivables_cr=rec, inventory_cr=inv, cash_and_equiv_cr=cash, bs_truedata=True)
    r.update(kw)
    return r


def quarters() -> List[Dict[str, Any]]:            # MOCK
    return [
        q_row("2026-09-30", 1100, 275, 165, "screener_in", bs=(2000, 300, 200, 1500, 1000, 600, 200, 100), bc="2026-10-15T18:00:00+05:30"),
        q_row("2026-09-30", 700, 140, 90, "screener_in", cons=False),          # standalone: never mixed into the consolidated series
        q_row("2026-06-30", 1050, 252, 150),
        q_row("2026-03-31", 1000, 250, 150, bs=(1900, 300, 150, 1400, 950, 500, 190, 90)),
        q_row("2025-12-31", 980, 245, 140),
        q_row("2025-09-30", 1000, 290, 160, bs=(1800, 200, 100, 1300, 900, 400, 180, 80)),
        q_row("2025-06-30", 950, None, 140),
        q_row("2025-03-31", 900, None, 130, bs=(1700, 200, 100, 1200, 850, 380, 170, 70)),
        q_row("2024-12-31", 880, None, 120),
        q_row("2024-09-30", 850, None, 110),
    ]


def annuals() -> List[Dict[str, Any]]:             # MOCK
    return [
        q_row("2026-03-31", 4000, 1000, 600, "screener_in_annual", kind="annual", total_equity_cr=1900, finance_costs_cr=50, pbt_cr=800),
        q_row("2025-03-31", 3600, 900, 520, "screener_in_annual", kind="annual", total_equity_cr=1700, finance_costs_cr=45, pbt_cr=700),
        q_row("2024-03-31", 3200, 800, 450, "screener_in_annual", kind="annual", finance_costs_cr=40, pbt_cr=600),
    ]


def shareholding() -> List[Dict[str, Any]]:        # MOCK
    def s(d, src, **kw):
        r = {"symbol": "ACME", "period_end": d, "source": src, "promoter_pct": None, "fii_pct": None, "dii_pct": None, "mf_pct": None,
             "promoter_pledged_pct": None, "promoter_pledged_to_total_pct": None, "public_pct": None, "broadcast_at": None}
        r.update(kw)
        return r
    return [
        s("2026-09-30", "NSE_SHP", promoter_pct=50.0, fii_pct=20.0, dii_pct=15.0, mf_pct=8.0, promoter_pledged_pct=12.5,
          promoter_pledged_to_total_pct=6.25, public_pct=49.99, broadcast_at="2026-10-12T10:00:00+05:30"),
        s("2026-09-30", "screener_in", promoter_pct=50.01, fii_pct=20.0, dii_pct=15.02, public_pct=4.78),
        s("2026-06-30", "NSE_SHP", promoter_pledged_pct=11.0),
        s("2026-06-30", "screener_in", promoter_pct=51.0, fii_pct=19.5, dii_pct=15.5, public_pct=5.01),
        s("2026-03-31", "screener_in", promoter_pct=52.0, fii_pct=19.0, dii_pct=15.0),
        s("2025-12-31", "screener_in", promoter_pct=52.5, fii_pct=18.5, dii_pct=14.5),
        s("2025-09-30", "screener_in", promoter_pct=53.0, fii_pct=18.0, dii_pct=14.0),
    ]


FEAT = {"symbol": "ACME", "as_of_date": "2026-10-30", "sector": "IT", "industry": "Information Technology", "pe_ttm": 20.0,
        "sector_median_pe": 25.0, "pb": 5.0, "market_cap_cr": 100000.0, "roe_pct": 30.0, "roce_pct": 35.0, "debt_to_equity": 0.1,
        "fundamentals_source": "trendlyne_mcp", "fundamentals_as_of": "2026-10-12", "piotroski_score": 7, "dividend_yield_pct": 1.5,
        "promoter_pct": 50.0, "fii_pct": 20.0, "dii_pct": 15.0, "ev_ebitda": None}          # MOCK
PE_HIST = [{"as_of_date": f"2026-10-{d:02d}", "pe_ttm": v} for d, v in zip(range(17, 31), (18, 19, 20.5, 21, 22, 23, 24, 25, 26, 20))]
CASH = [{"symbol": "ACME", "period_end": "2026-03-31", "consolidated": True, "cfo_cr": 420.0, "cfi_cr": -450.0, "cff_cr": 10.0,
         "capex_cr": -500.0, "net_change_cash_cr": -20.0, "source": "truedata"},
        {"symbol": "ACME", "period_end": "2025-03-31", "consolidated": True, "cfo_cr": 480.0, "cfi_cr": -300.0, "cff_cr": -150.0,
         "capex_cr": -260.0, "net_change_cash_cr": 30.0, "source": "truedata"}]                 # MOCK
AMC = {"symbol": "ACME", "as_of": "2026-09-01", "previous_month": "2026-08-01", "count": 1,
       "rows": [{"amc_id": "a1", "amc_name": "MOCK Fund House A", "schemes": 5, "schemes_up": 3, "schemes_dn": 1, "shares_delta": 120000,
                 "shares_pct_change": 4.2, "share_of_disclosed_pct": 35.0}],
       "totals": {"amcs": 1, "schemes": 5, "schemes_up": 3, "schemes_dn": 1, "pct_of_equity": 2.5, "largest_amc_share_pct": 35.0}}  # MOCK
UNIVERSE = {"as_of": "2026-10-30", "rows": [
    {"symbol": "ACME", "sector": "IT", "industry": "Information Technology", "market_cap_cr": 100000},
    {"symbol": "PEERA", "sector": "IT", "industry": "Information Technology", "market_cap_cr": 200000},
    {"symbol": "PEERB", "sector": "it", "industry": "Information Technology", "market_cap_cr": 50000},
    {"symbol": "CAPG", "sector": "Capital Goods", "industry": "Capital Goods", "market_cap_cr": 300000},
    {"symbol": "LONE", "sector": None, "industry": None, "market_cap_cr": 1000}]}         # MOCK


PEERS = ("PEERA", "PEERB", "CAPG", "LONE")


class Readers:
    """Every research reader replaced; `fail` names readers that raise, `v` holds what each returns."""

    def __init__(self, mp):
        self.fail: set = set()
        self.calls: List[tuple] = []
        self.v: Dict[str, Any] = {"quarterly": quarters(), "annual": annuals(), "cashflow": CASH, "shareholding": shareholding(),
                                  "features": dict(FEAT), "pe_history": list(reversed(PE_HIST)), "amc": AMC, "universe": UNIVERSE,
                                  "features_on": {"ACME": dict(FEAT), "PEERA": {**FEAT, "symbol": "PEERA", "pe_ttm": 30.0, "roe_pct": 20.0},
                                                  "PEERB": {**FEAT, "symbol": "PEERB", "pe_ttm": 15.0, "roe_pct": 25.0}}}

        async def window():
            return WINDOW
        mp.setattr(rd, "window", window)

        def make(name, value_of):
            async def f(*a, **k):
                self.calls.append((name, a, tuple(sorted(k.items()))))
                if name in self.fail:
                    raise RuntimeError(f"MOCK {name} down" if name != "cashflow_404" else "DaaS /financials/ACME/cashflow answered 404")
                return value_of(*a, **k)
            return f
        mp.setattr(rr, "financials", make("financials", lambda sym, kind, limit=40: self.v[kind] if sym not in PEERS else [
            dict(r, symbol=sym) for r in self.v.get(f"{kind}:{sym}", [])]))
        mp.setattr(rr, "cashflow", self._cashflow)
        mp.setattr(rr, "shareholding", make("shareholding", lambda sym, limit=40: self.v["shareholding"]))
        mp.setattr(rr, "features_latest", make("features_latest", lambda sym: self.v["features_on"].get(sym) if sym in PEERS else self.v["features"]))
        mp.setattr(rr, "pe_history", make("pe_history", lambda sym, limit=600: self.v["pe_history"]))
        mp.setattr(rr, "amc", make("amc", lambda sym: self.v["amc"]))
        mp.setattr(rr, "universe", make("universe", lambda: self.v["universe"]))
        mp.setattr(rr, "features_on", make("features_on", lambda syms, day: {s: self.v["features_on"][s] for s in syms if s in self.v["features_on"]}))

    async def _cashflow(self, sym, limit=20):
        if "cashflow_404" in self.fail:
            raise RuntimeError("DaaS /financials/ACME/cashflow answered 404")
        if "cashflow" in self.fail:
            raise RuntimeError("MOCK cashflow down")
        return self.v["cashflow"]


@pytest.fixture
def src(monkeypatch):
    return Readers(monkeypatch)


def build(name, sym="ACME", message="", **params):
    thread = params.pop("symbol_from_thread", False)
    p = asyncio.run(builders.build(Intent(name, symbol=sym, params=params, symbol_from_thread=thread), {"user_id": "u1"}, message=message))
    assert validate(p) == [], validate(p)
    return p


def blk(p, bid):
    return next((b for b in p["blocks"] if b.get("id") == bid), None)


def kpi(p, bid, label_start):
    return next(i for i in blk(p, bid)["items"] if i["label"].startswith(label_start))


def texts(x) -> List[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [t for k, v in x.items() if k not in ("intent", "schema", "id", "key", "type") for t in texts(v)]
    if isinstance(x, list):
        return [t for v in x for t in texts(v)]
    return []


# ═════ TC-B1: financial_trend ═══════════════════════════════════════════════════════════════════════════════════════

def test_b1_financial_trend_one_basis_yoy_and_depth(src):
    p = build("financial_trend")
    assert p["intent"] == "financial_trend" and p["title"] == "ACME · Financial trend"
    rows = blk(p, "quarters")["rows"]
    assert [r["cells"]["q"] for r in rows] == ["Sep 26", "Jun 26", "Mar 26", "Dec 25", "Sep 25", "Jun 25", "Mar 25", "Dec 24"]   # 8 shown
    assert rows[0]["cells"]["rev"] == "1,100"                       # consolidated, not the standalone 700
    assert rows[0]["cells"]["rev_yoy"] == 10.0 and rows[0]["cells"]["rev_qoq"] == 4.76
    assert rows[-1]["cells"]["rev_yoy"] is None                     # Dec 24 has no year-ago quarter in the data
    assert rows[0]["cells"]["ebitda_m"] == "25.0%" and rows[5]["cells"]["ebitda"] is None
    assert kpi(p, "latest", "EBITDA margin")["sub"] == "−4.00 pp vs Sep 25"
    assert "slower than the Jun 26 quarter's (+10.5%)" in p["headline"]["text"]
    assert "Our data has 9 quarters (Sep 24 to Sep 26) and 3 fiscal years (FY24 to FY26) for ACME." in blk(p, "depth")["text"]
    assert "more than one provider (Trendlyne, screener.in)" in blk(p, "providers")["text"]
    assert "EBITDA is not in our data for 3 of the 8 quarters shown." == blk(p, "noebitda")["text"]
    years = blk(p, "years")["rows"]
    assert years[0]["cells"]["roe"] == "33.3%" and years[1]["cells"]["roe"] is None     # 600 ÷ avg(1,900, 1,700); FY24 equity missing
    assert {i["label"]: i["value"] for i in blk(p, "cagr")["items"]} == {"Revenue CAGR": "+11.8%", "PAT CAGR": "+15.5%"}
    assert kpi(p, "latest", "ROE (latest)")["sub"] == "Trendlyne, 12 Oct 2026"


def test_b1_financial_trend_says_when_the_asked_window_is_longer_than_the_data(src):
    p = build("financial_trend", years=5)
    assert "you asked for 5 years, so the answer covers only what is there" in blk(p, "depth")["text"]


def test_b1_lender_has_no_ebitda(src):
    src.v["features"] = {**FEAT, "sector": "BANKING"}
    p = build("financial_trend")
    assert "ebitda_m" not in {c["key"] for c in blk(p, "quarters")["columns"]} and blk(p, "margin") is None
    assert any("GNPA, NNPA" in i["text"] for i in blk(p, "gaps")["items"])


def test_b1_a_company_without_results(src):
    src.v["quarterly"], src.v["annual"] = [], []
    p = build("financial_trend")
    assert "are not in our data, so there is no trend to show" in blk(p, "nodata")["text"] and p["headline"] is None


# ═════ TC-B2: valuation_view ════════════════════════════════════════════════════════════════════════════════════════

def test_b2_valuation_against_sector_median_and_own_history(src):
    p = build("valuation_view")
    now = {i["label"]: i for i in blk(p, "now")["items"]}
    assert now["P/E (trailing 12 months)"]["value"] == "20.0×"
    assert now["P/E vs sector median"]["value"] == "−20.0%" and now["P/E vs sector median"]["sub"] == "P/E ÷ sector median − 1"
    assert now["EV/EBITDA"]["value"] == "not in our data"
    bars = {i["label"]: i for i in blk(p, "pe_range")["items"]}
    assert (bars["Lowest"]["value"], bars["Highest"]["value"], bars["Now"]["value"]) == (18.0, 26.0, 20.0)
    assert bars["Lowest"]["sub"] == "17 Oct 2026"
    assert kpi(p, "pctile", "Sessions with a lower P/E")["value"] == "20%"          # 18 and 19 of the 10 sessions
    assert "20.0% below the median P/E of its sector label (25.0×)" in p["headline"]["text"]
    assert blk(p, "scenarios") is None                                                # not asked


def test_b2_scenarios_only_when_asked(src):
    p = build("valuation_view", growth=[15.0, 25.0])
    rows = blk(p, "scenarios")["rows"]
    assert [(r["cells"]["g"], r["cells"]["pe"]) for r in rows] == [("15%", "17.4×"), ("25%", "16.0×")]
    assert "no price is projected" in blk(p, "scenarios")["note"]


# ═════ TC-B3: ownership_trend ═══════════════════════════════════════════════════════════════════════════════════════

def test_b3_field_wise_merge_nse_first_and_no_public_figure(src):
    p = build("ownership_trend")
    k = {i["label"]: i for i in blk(p, "latest")["items"]}
    assert k["Promoters · Sep 26"]["value"] == "50.00%" and k["Promoters · Sep 26"]["sub"] == "−1.00 pp vs Jun 26 · −3.00 pp vs Sep 25"
    assert k["DIIs · Sep 26"]["value"] == "15.00%"                                     # NSE's 15.00, not screener.in's 15.02
    assert k["Mutual funds · Sep 26"]["value"] == "8.00%"
    assert k["Pledged (of promoter shares)"]["value"] == "12.50%" and "6.25% of all shares" in k["Pledged (of promoter shares)"]["sub"]
    rows = blk(p, "quarters")["rows"]
    assert rows[1]["cells"]["pledge"] == "11.00%" and rows[2]["cells"]["pledge"] is None        # a blank is not reported, not 0
    assert rows[0]["cells"]["src"] == "NSE filing" and rows[1]["cells"]["src"] == "NSE filing + screener.in"
    flat = " ".join(texts(p))
    assert "4.78" not in flat and "49.99" not in flat                                  # neither provider's public figure
    assert {i["label"] for i in blk(p, "change")["items"]} == {"Promoters", "FIIs", "DIIs"}
    assert blk(p, "amc")["rows"][0]["cells"]["amc"] == "MOCK Fund House A"


def test_b3_fund_house_route_404_is_a_named_missing_source(src, monkeypatch):
    async def amc404(sym):
        raise RuntimeError("DaaS /smart-money/amc answered 404")
    monkeypatch.setattr(rr, "amc", amc404)
    p = build("ownership_trend")
    assert blk(p, "amc") is None and blk(p, "amc_totals") is None
    assert any("does not serve the fund-house view yet (HTTP 404)" in x for x in p["data_quality"]["missing"])


def test_b3_sources_that_disagree_never_make_a_change(src):
    """The ICICIBANK case (real, 2 Nov 2026: NSE FII 50.44% vs screener.in 34.68% for one quarter): screener.in's series is kept
    and no change is computed across the two sources."""
    rows = shareholding()
    rows[0]["fii_pct"] = 30.0                                                          # MOCK: NSE disagrees with screener.in's 20.0
    src.v["shareholding"] = rows
    p = build("ownership_trend")
    assert kpi(p, "latest", "FIIs")["value"] == "20.00%"
    assert blk(p, "quarters")["rows"][0]["cells"]["d_fii"] == "+0.50 pp"             # screener.in to screener.in
    t = blk(p, "conflict-fii_pct")["text"]
    assert "NSE's filing puts ACME's FII holding at 30.00% and screener.in at 20.00%" in t and "no change is computed" in t


def test_b3_pledge_without_a_promoter_is_not_shown(src):
    """The HDFCBANK / ITC case (real: NSE pledge 17.53% / 100% with no promoter group)."""
    rows = shareholding()
    for r in rows:
        r["promoter_pct"] = None
    src.v["shareholding"] = rows
    p = build("ownership_trend")
    assert kpi(p, "latest", "Pledged")["value"] == "not reported"
    assert "does not agree with the promoter holding" in blk(p, "pledge-dropped")["text"]
    assert checks_of(build("company_risks"))["Promoter pledge"]["result"] == "Not in our data"


def test_b3_a_change_across_unchecked_sources_says_so(src):
    src.v["shareholding"] = [r for r in shareholding() if not (r["period_end"] == "2026-09-30" and r["source"] == "screener_in")]
    p = build("ownership_trend")
    assert kpi(p, "latest", "Promoters")["sub"].startswith("−1.00 pp vs Jun 26")
    assert "have no quarter in common to check them" in blk(p, "crossed")["text"]


def test_b3_an_unusually_large_one_quarter_move_is_named(src):
    """The ICICIBANK case (real: screener.in FIIs 43.87% → 34.48% in one quarter)."""
    rows = shareholding()
    rows[4]["fii_pct"] = 12.0                                                          # MOCK: Mar 26 12.0 → Jun 26 19.5
    src.v["shareholding"] = rows
    p = build("ownership_trend")
    assert "FIIs +7.50 pp (Mar 26 to Jun 26)" in blk(p, "jumps")["text"]


def test_b3_short_history_says_so(src):
    src.v["shareholding"] = shareholding()[:2]
    p = build("ownership_trend")
    assert "only 1 quarter of shareholding" in blk(p, "depth")["text"]


# ═════ TC-B4: peer_compare ══════════════════════════════════════════════════════════════════════════════════════════

def test_b4_peers_by_exact_sector_label(src):
    p = build("peer_compare", symbols=["ACME"])
    syms = [r["symbol"] for r in blk(p, "growth")["rows"]]
    assert syms == ["ACME", "PEERA", "PEERB"]                                          # "IT" never matches "Capital Goods"
    assert blk(p, "growth")["rows"][0]["badge"] == "This company"
    assert "same sector label (“IT”)" in blk(p, "peers")["text"] and "covers 4 of 5 stocks" in blk(p, "peers")["text"]
    assert kpi(p, "summary", "Median P/E of the set")["value"] == "20.0×"
    assert kpi(p, "summary", "ACME P/E vs the set's median")["value"] == "±0.0%"
    assert any(t.startswith("ROE: highest ACME (30.0%), lowest PEERA (20.0%)") for t in texts(blk(p, "extremes")))


def test_b4_no_sector_label_says_so(src):
    src.v["universe"] = {"as_of": "2026-10-30", "rows": [{"symbol": "ACME", "sector": None, "industry": None}]}
    p = build("peer_compare", symbols=["ACME"])
    assert "has no sector label or NSE industry" in blk(p, "nomap")["text"]


def test_b4_named_companies_and_lender_gap(src):
    src.v["features_on"]["PEERA"] = {**FEAT, "symbol": "PEERA", "sector": "BANKING"}
    p = build("peer_compare", symbols=["ACME", "PEERA"])
    assert p["title"] == "ACME vs PEERA · Comparison"
    assert [r["symbol"] for r in blk(p, "value")["rows"]] == ["ACME", "PEERA"]
    assert "Asset quality (GNPA, NNPA)" in blk(p, "lender")["text"]
    assert "ebitda_m" not in {c["key"] for c in blk(p, "growth")["columns"]}
    assert not any(c[0] == "universe" for c in src.calls)


def test_b4_one_recognised_company(src):
    p = build("peer_compare", symbols=["ACME"], one_recognised=True)
    assert "Only ACME was recognised" in blk(p, "one_named")["text"]


# ═════ TC-B5: company_risks ═════════════════════════════════════════════════════════════════════════════════════════

def checks_of(p):
    return {r["cells"]["check"]: r["cells"] for r in blk(p, "checks")["rows"]}


def test_b5_every_check_states_its_rule(src):
    p = build("company_risks")
    c = checks_of(p)
    assert c["Debt to equity"]["value"] == "0.25× (₹500 Cr debt)" and c["Debt to equity"]["result"] == "Within the rule"
    assert c["Debt growth vs profit growth"]["result"] == "Flagged"                   # debt +66.7% vs PAT +15.4%
    assert c["Interest cover"]["value"] == "17.0×" and c["Interest cover"]["when"] == "FY26"
    assert c["Current ratio"]["value"] == "1.50×"
    assert c["Cash from operations ÷ PAT"]["value"] == "0.70× (₹420 Cr ÷ ₹600 Cr)" and c["Cash from operations ÷ PAT"]["result"] == "Flagged"
    assert c["PAT growth vs cash-flow growth"]["value"] == "PAT +15.4%, CFO −12.5%" and c["PAT growth vs cash-flow growth"]["result"] == "Flagged"
    assert c["Free cash flow"]["value"] == "−₹80 Cr (CFO ₹420 Cr, capex −₹500 Cr)" and c["Free cash flow"]["result"] == "Flagged"
    assert c["Receivables vs revenue growth"]["value"] == "receivables +50.0%, revenue (12 months) +10.7%"
    assert c["Receivables vs revenue growth"]["result"] == "Flagged"
    assert c["Working capital days"]["value"] == "35 days (a year earlier 31)" and c["Working capital days"]["result"] == "Within the rule"
    assert c["Promoter pledge"]["result"] == "Flagged" and c["Promoter holding change"]["result"] == "Flagged"
    assert c["EBITDA margin trend"]["value"] == "25.0% vs 29.0%" and c["Piotroski F-score"]["result"] == "Within the rule"
    assert all(v["rule"] for v in c.values())
    assert kpi(p, "summary", "Flagged")["value"] == "8 of 13"
    assert p["headline"]["tone"] == "warn" and p["headline"]["text"].startswith("8 of the 13 checks that could run are flagged for ACME")
    assert blk(p, "cash")["rows"][0]["cells"] == {"fy": "FY26", "cfo": "420", "pat": "600", "ratio": "0.70×", "capex": "−500", "fcf": "−80", "src": "TrueData"}
    assert blk(p, "balance")["rows"][0]["cells"]["src"] == "TrueData balance sheet"
    assert len(blk(p, "cannot")["items"]) == 4


def test_b5_debt_growth_from_a_tiny_base_is_not_flagged(src):
    """The ITC case (real: debt ₹91 Cr to ₹2,186 Cr, +2,296%, at 0.03× equity): immaterial debt is not a flag."""
    q = quarters()
    q[0]["long_term_debt_cr"], q[0]["short_term_debt_cr"] = 50.0, 50.0             # MOCK: 0.05× of ₹2,000 Cr equity
    q[5]["long_term_debt_cr"], q[5]["short_term_debt_cr"] = 1.0, 1.0
    src.v["quarterly"] = q
    c = checks_of(build("company_risks"))["Debt growth vs profit growth"]
    assert c["result"] == "Within the rule" and c["value"].startswith("debt +4900.0% to ₹100 Cr (0.05× equity)")


def test_b5_march_balance_sheet_uses_the_fiscal_year_revenue(src):
    src.v["quarterly"] = [r for r in quarters() if r["period_end"] not in ("2026-09-30", "2026-06-30")]
    c = checks_of(build("company_risks"))
    # Mar 26 vs Mar 25: receivables 500 vs 380 (+31.6%) against FY26 vs FY25 revenue 4,000 vs 3,600 (+11.1%)
    assert c["Receivables vs revenue growth"]["value"] == "receivables +31.6%, revenue (12 months) +11.1%"
    assert c["Receivables vs revenue growth"]["result"] == "Flagged" and c["Receivables vs revenue growth"]["when"] == "Mar 25 to Mar 26"


def test_b5_no_source_column_when_no_row_states_one(src):
    src.v["quarterly"] = [{k: v for k, v in r.items() if k != "source"} for r in quarters()]
    src.v["annual"] = [{k: v for k, v in r.items() if k != "source"} for r in annuals()]
    p = build("financial_trend")
    assert "src" not in {c["key"] for c in blk(p, "quarters")["columns"]} and blk(p, "providers") is None
    assert "src" not in {c["key"] for c in blk(p, "years")["columns"]}


def test_b5_cashflow_route_not_served_shows_no_cash_figure(src):
    """AC-RC-03 analogue: the cash-flow source is named missing and no cash-flow figure appears."""
    src.fail.add("cashflow_404")
    p = build("company_risks")
    assert any("does not serve cash-flow statements yet (HTTP 404)" in m for m in p["data_quality"]["missing"])
    c = checks_of(p)
    for name in ("Cash from operations ÷ PAT", "PAT growth vs cash-flow growth", "Free cash flow"):
        assert c[name]["result"] == "Not in our data", name
    assert blk(p, "cash") is None and blk(p, "cfo_pat") is None
    flat = " ".join(texts(p))
    assert "420" not in flat and "480" not in flat


def test_b5_balance_sheet_columns_not_served(src):
    keep = ("current_assets_cr", "current_liabilities_cr", "trade_receivables_cr", "inventory_cr", "trade_payables_cr", "bs_truedata")
    src.v["quarterly"] = [{k: v for k, v in r.items() if k not in keep} for r in quarters()]
    src.v["annual"] = [{k: v for k, v in r.items() if k not in keep} for r in annuals()]
    p = build("company_risks")
    assert "not served by the data platform yet" in blk(p, "bs_not_served")["text"]
    c = checks_of(p)
    assert c["Current ratio"]["value"] == "not served by the data platform yet" and c["Current ratio"]["result"] == "Not in our data"
    assert c["Debt to equity"]["result"] == "Within the rule"                         # equity and debt are served today


def test_b5_lender_checks_are_not_applicable(src):
    src.v["features"] = {**FEAT, "sector": "BANKING"}
    p = build("company_risks")
    c = checks_of(p)
    for name in ("Debt to equity", "Current ratio", "Working capital days", "Free cash flow", "Interest cover", "EBITDA margin trend"):
        assert c[name]["result"] == "Not applicable", name
    assert "GNPA, NNPA" in blk(p, "lender")["text"]


def test_b5_no_cash_rows_for_the_company(src):
    src.v["cashflow"] = []
    p = build("company_risks")
    assert "Cash-flow statements for ACME are not in our data yet" in blk(p, "nocf")["text"]


# ═════ TC-B6: filed evidence and freshness ══════════════════════════════════════════════════════════════════════════

def test_b6_filed_evidence_is_never_stale_price_data(src):
    p = build("company_risks")
    assert not any("older than the previous session" in t for t in texts(p))
    rows = {r["name"]: r for r in p["data_quality"]["sources"]}
    assert rows["Quarterly results (nidp.nse_financials_quarterly)"]["status"] == "fresh"
    assert rows["Quarterly results (nidp.nse_financials_quarterly)"]["as_of"] == "2026-09-30"


def test_b6_an_old_filing_says_a_newer_one_may_exist():
    s = Sources(WINDOW)
    assert s.filed("quarterly result", "2026-09-30", None, 150) is True
    assert s.filed("quarterly result", "2026-03-31", None, 150) is False
    assert s.rows[-1]["status"] == "stale" and "A newer one may have been filed" in s.notices[-1]["text"]
    assert s.filed("annual statement", "2026-03-31") is True                         # no cadence given: never flagged


def test_b6_thread_stock_is_named(src):
    p = build("company_risks", symbol_from_thread=True)
    assert p["blocks"][0]["id"] == "thread" and "the last stock in this conversation" in p["blocks"][0]["text"]


# ═════ TC-B7: SEBI wording lint ═════════════════════════════════════════════════════════════════════════════════════

LINT = re.compile(r"\b(buy|sell|hold|target|targets|recommend\w*|pick|picks|cheap|expensive|undervalued|overvalued)\b", re.I)


@pytest.mark.parametrize("variant", ["full", "lender", "failure", "cash404"])
def test_b7_no_advice_words_in_any_answer(src, variant):
    if variant == "lender":
        src.v["features"] = {**FEAT, "sector": "BANKING"}
    if variant == "failure":
        src.fail.update({"financials", "cashflow", "shareholding", "features_latest", "pe_history", "amc", "universe", "features_on"})
    if variant == "cash404":
        src.fail.add("cashflow_404")
    for name, params in (("financial_trend", {}), ("valuation_view", {"growth": [15.0]}), ("ownership_trend", {}),
                         ("peer_compare", {"symbols": ["ACME"]}), ("peer_compare", {"symbols": ["ACME", "PEERA"]}), ("company_risks", {})):
        p = build(name, **params)
        hits = [t for t in texts(p) if LINT.search(t)]
        assert hits == [], (name, variant, hits)


# ═════ TC-B8: registration, facts subject ═══════════════════════════════════════════════════════════════════════════

def test_b8_registered_everywhere():
    from services import copilot_visual as cv
    for name in RESEARCH_INTENTS:
        assert name in INTENTS and name in cv.BUILDERS and cv.AGENT_FOR[name] == "stock_analyst"
        assert "intent" not in validate({"schema": "visual-answer-v1", "intent": name})


def test_b8_prepare_names_the_stock_as_the_facts_subject(src, monkeypatch):
    from services import copilot_visual as cv
    src.v["features"] = {**FEAT, "symbol": "TCS"}
    va = asyncio.run(cv.prepare(None, {"user_id": "u1"}, "What is the current ratio of TCS?", None, None, None, None))
    assert va is not None and va.intent.name == "company_risks" and va.agent == "stock_analyst"
    assert va.facts.startswith("VISUAL_ANSWER for TCS (company_risks)")
    assert va.widget["widget_type"] == "visual_answer" and va.trade_idea is None



# ═════ TC-B9: every read failing ════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name, params", [("financial_trend", {}), ("valuation_view", {}), ("ownership_trend", {}),
                                          ("peer_compare", {"symbols": ["ACME"]}), ("peer_compare", {"symbols": ["ACME", "PEERA"]}),
                                          ("company_risks", {})])
def test_b9_every_read_failing_is_a_valid_answer_without_figures(src, name, params):
    src.fail.update({"financials", "cashflow", "shareholding", "features_latest", "pe_history", "amc", "universe", "features_on"})
    p = build(name, **params)
    assert p["data_quality"]["missing"], name
    assert not any(b["type"] in ("bars",) for b in p["blocks"]), name
    f = facts(p, subject="ACME")
    assert f.startswith("VISUAL_ANSWER for ACME") and "Missing:" in f


# ═════ TC-D1: the DaaS routes ═══════════════════════════════════════════════════════════════════════════════════════

def test_d1_financials_route_serves_the_balance_sheet_columns_and_cashflow():
    fin = pytest.importorskip("nidp.services.daas_api.routers.financials")
    for col in ("current_assets_cr", "current_liabilities_cr", "trade_receivables_cr", "inventory_cr", "trade_payables_cr",
                "AS bs_truedata", "source,"):
        assert col in fin.FINANCIALS_SQL, col
    assert "FROM nidp.nse_financials_cashflow" in fin.CASHFLOW_SQL and "ORDER BY period_end DESC" in fin.CASHFLOW_SQL

    calls = []

    class Conn:
        async def fetch(self, sql, *args):
            calls.append((sql, args))
            return [{"symbol": "ACME", "period_end": date(2026, 3, 31), "consolidated": True, "cfo_cr": 1.5, "capex_cr": -2.0}]

    class Acquire:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_pool():
        return Pool()
    orig = fin.get_pool
    fin.get_pool = get_pool
    try:
        out = asyncio.run(fin.cashflow(symbol=" acme ", consolidated=None, page={"limit": 20, "offset": 0}))
    finally:
        fin.get_pool = orig
    assert calls == [(fin.CASHFLOW_SQL, ("ACME", None, 20, 0))]
    assert out["symbol"] == "ACME" and out["data"][0]["period_end"] == "2026-03-31" and out["count"] == 1
    paths = {getattr(r, "path", None) for r in fin.router.routes}
    assert {"/financials/{symbol}", "/financials/{symbol}/cashflow"} <= paths


# ═════ C-2 (research): the REAL staging capture matches the contract ════════════════════════════════════════════════

CAPTURE = Path(__file__).parent / "fixtures" / "research_visual_capture.json"


def test_c2_research_real_capture_matches_the_contract():
    """tests/test_copilot_visual.py::test_c2 checks the shared capture for every other intent; the research answers' real staging
    capture is kept here (3 Nov 2026, TC-S1/TC-S2 of test_reports/research_answers_w1_TESTCASES.md)."""
    doc = json.loads(CAPTURE.read_text(encoding="utf-8"))
    assert "REAL staging capture" in doc["about"]
    assert {p["intent"] for p in doc["payloads"].values()} == set(RESEARCH_INTENTS)
    for key, p in doc["payloads"].items():
        assert p["intent"] == key.split(":")[0] and validate(p) == [], (key, validate(p))
        assert [t for t in texts(p) if LINT.search(t)] == [], key
    risks = doc["payloads"]["company_risks:route_sql"]
    assert any(r["cells"]["check"] == "Current ratio" and r["cells"]["value"] for r in blk(risks, "checks")["rows"])
    assert any("does not serve cash-flow statements yet" in m for m in doc["payloads"]["company_risks"]["data_quality"]["missing"])
