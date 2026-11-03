"""Stock autocomplete for the Copilot: GET /api/chat/instrument-search, ranked, with short forms, F&O indices, any word
order and the `tail` mode that completes a stock inside a sentence (services/stock_search.py).

Covers SC-1 … SC-11 of test_reports/copilot_stock_autocomplete_20261029.md.

MOCK — not real data: the symbol master below is a small invented subset in the real search's shape ({data: [{symbol,
company_name, sector, industry, isin}]}). The fake search matches the way the real DaaS /v1/symbols/search was measured to
on staging (29 Oct): a case-insensitive substring of the symbol or the company name, in master order, with no short
forms, no word order and no indices. Fund search is replaced by an empty or a one-row answer. No network.
"""
from __future__ import annotations

import asyncio

import pytest

from routes import chat
from services import stock_search as ss
from services.copilot_tools import daas_client

MASTER = [  # MOCK
    ("ITC", "ITC Limited", "FMCG"), ("ITCHOTELS", "ITC Hotels Limited", "Hotels"), ("KILITCH", "Kilitch Drugs (India) Limited", "Pharma"),
    ("MITCON", "MITCON Consultancy & Engineering Services Limited", "Services"), ("NITCO", "Nitco Limited", "Building"),
    ("TVSELECT", "TVS Electronics Limited", "IT"), ("TVSHLTD", "TVS Holdings Limited", "Finance"),
    ("TVSMOTOR", "TVS Motor Company Limited", "Automobile"), ("HINDUNILVR", "Hindustan Unilever Limited", "FMCG"),
    ("HCL-INSYS", "HCL Infosystems Limited", "IT"), ("INFY", "Infosys Limited", "IT"),
    ("LTF", "L&T Finance Limited", "Finance"), ("LTTS", "L&T Technology Services Limited", "IT"),
    ("LT", "Larsen & Toubro Limited", "Construction"), ("SBIN", "State Bank of India", "Banks"),
    ("TCS", "Tata Consultancy Services Limited", "IT"), ("TMCV", "Tata Motors Limited", "Automobile"),
    # Short tickers that start with a fragment's last word: on staging "tvs mo" first picked "mo" → MOL, MOIL (fixed).
    ("MOL", "Mol Industries Limited", "Chemicals"), ("MOIL", "MOIL Limited", "Mining"),
]


@pytest.fixture(autouse=True)
def master(monkeypatch):
    calls = []

    async def search_symbols(q, limit=8):
        calls.append(q)
        ql = q.strip().lower()
        rows = [{"symbol": s, "company_name": n, "sector": sec, "industry": sec, "isin": None}
                for s, n, sec in MASTER if ql in s.lower() or ql in n.lower()]
        return {"data": rows[:limit]}

    async def no_funds(term, limit=30):
        return []

    ss._cache.clear()
    monkeypatch.setattr(daas_client, "search_symbols", search_symbols)
    monkeypatch.setattr(daas_client, "search_mf_schemes", no_funds)
    return calls


def search(q, limit=6, tail=False):
    return asyncio.run(chat.chat_instrument_search(q=q, limit=limit, tail=tail))


def syms(q, **kw):
    return [s["symbol"] for s in search(q, **kw)["stocks"]]


# ── SC-1 … SC-6: ranking ─────────────────────────────────────────────────────
def test_sc1_an_exact_ticker_comes_first():
    assert syms("itc")[0] == "ITC"
    assert syms("itc")[1] == "ITCHOTELS"                          # ticker prefix before substrings in other names


@pytest.mark.parametrize("q, first", [("tvs mo", "TVSMOTOR"), ("TVSMOTOR", "TVSMOTOR"), ("tvsmotor", "TVSMOTOR"),
                                      ("hindustan uni", "HINDUNILVR"), ("tata mot", "TMCV")])
def test_sc2_ticker_full_name_and_partial_name(q, first):
    assert syms(q)[0] == first


def test_sc3_words_in_another_order():
    assert syms("motor tvs") == ["TVSMOTOR"]


@pytest.mark.parametrize("q, first, name", [("hul", "HINDUNILVR", "Hindustan Unilever Limited"),
                                            ("l&t", "LT", "Larsen & Toubro Limited"), ("sbi", "SBIN", "State Bank of India")])
def test_sc4_the_resolvers_short_forms_come_first_with_their_names(q, first, name):
    got = search(q)["stocks"]
    assert got[0]["symbol"] == first and got[0]["name"] == name
    if q == "l&t":
        assert [s["symbol"] for s in got[1:]] == ["LTF", "LTTS"]       # the master's own matches stay, after it


def test_sc5_fno_indices_are_offered_as_indices():
    got = search("nifty")["stocks"]
    assert got[0] == {"symbol": "NIFTY", "name": "Nifty 50", "sector": ss.INDEX_SECTOR, "kind": "index"}
    assert syms("bank nifty")[0] == "BANKNIFTY"
    assert [s["kind"] for s in search("tvs")["stocks"]] == ["stock"] * 3


def test_sc6_a_name_word_beats_a_substring():
    assert syms("infosys") == ["INFY", "HCL-INSYS"]


# ── SC-7: the symbol master cannot be read ───────────────────────────────────
def test_sc7_without_the_symbol_master_the_old_fallback_answers(monkeypatch):
    async def down(q, limit=8):
        return None

    async def universe():
        return [{"symbol": "FIXCO", "sector": "Fixture"}]               # symbols only, as staging's is
    monkeypatch.setattr(daas_client, "search_symbols", down)
    monkeypatch.setattr(chat, "_stock_universe", universe)
    assert search("fixc")["stocks"] == [{"symbol": "FIXCO", "name": "FIXCO", "sector": "Fixture"}]
    got = search("reliance")["stocks"]                                    # the curated list, as before
    assert got and got[0]["symbol"] == "RELIANCE"


# ── SC-8 … SC-10: completing a stock inside a sentence ───────────────────────
def test_sc8_the_fragment_at_the_end_of_a_sentence():
    text = "Plan a breakout trade for tvs mo"
    got = search(text, tail=True)
    assert got["fragment"] == "tvs mo" and got["fragment_start"] == text.index("tvs mo") and text[got["fragment_start"]:] == "tvs mo"
    assert got["stocks"][0]["symbol"] == "TVSMOTOR" and got["funds"] == []


@pytest.mark.parametrize("text", ["how is the market", "trade plan for ", "tell me about a", "Plan a breakout trade for tvs mo?", ""])
def test_sc9_ordinary_words_a_finished_word_or_one_letter_give_nothing(text, master):
    got = search(text, tail=True)
    assert got == {"stocks": [], "funds": [], "fragment": None, "fragment_start": None}


def test_sc9_ordinary_words_are_never_searched(master):
    search("how is the market", tail=True)
    assert master == []


@pytest.mark.parametrize("text, fragment, first", [("compare infy and tcs", "tcs", "TCS"),
                                                   ("buy a put on nifty", "nifty", "NIFTY"),
                                                   ("how is hul", "hul", "HINDUNILVR"),
                                                   ("trade TVSMOTOR", "TVSMOTOR", "TVSMOTOR")])
def test_sc10_the_last_stock_mentioned(text, fragment, first):
    got = search(text, tail=True)
    assert got["fragment"] == fragment and got["stocks"][0]["symbol"] == first
    assert text[got["fragment_start"]:] == fragment


# ── SC-11: the plain answer keeps its shape ──────────────────────────────────
def test_sc11_shape_limit_and_short_terms(monkeypatch):
    got = search("tvs", limit=2)
    assert set(got) == {"stocks", "funds"} and len(got["stocks"]) == 2
    assert set(got["stocks"][0]) == {"symbol", "name", "sector", "kind"}
    assert search("t") == {"stocks": [], "funds": []}

    async def one_fund(term, limit=30):
        return [{"scheme_name": "Fixture Bluechip Fund - Direct Plan - Growth", "scheme_code": 1, "amc_name": "Fixture AMC",
                 "scheme_category": "Large Cap"}]
    monkeypatch.setattr(daas_client, "search_mf_schemes", one_fund)
    funds = search("fixture")["funds"]
    assert len(funds) == 1 and funds[0]["scheme_code"] == 1 and funds[0]["amc"] == "Fixture AMC"
