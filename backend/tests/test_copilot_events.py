"""The Copilot's results and market-research event answers (services/copilot_visual/events_builders.py; owner, 31 Oct 2026).

"Which companies report results this week?" went to the Filings analyst, which said it had no results calendar; the owner:
"We do have event calendar and all results with us", asked for "an AI summary of each of the result and management commentary
and source pdf link to download", and that users can ask "any questions on the market research like order winning, Mergers and
Acquisitions, Ownership" from the desk's AI Event Intelligence chips. Test cases EV-* of test_reports/copilot_events_answers_20261031.md.

What is replaced (MOCK — not real data; every company, figure, summary and link below is invented): the readers in
services/copilot_visual/readers.py (the results calendar, the stored filing analyses, a company's filings, the Market
Intelligence filings feed, bulk and block deals, SEBI circulars) and the freshness window. The resolver, the builders, the link
check, the contract check and the facts block run for real.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from pathlib import Path

import pytest

from services import market_freshness
from services.copilot_visual import BUILDERS, INTENTS, builders, readers as rd
from services.copilot_visual import links as lk
from services.copilot_visual.intents import Intent, resolve_intent
from services.copilot_visual.payload import facts, validate

TODAY, FLOOR = date(2026, 10, 30), date(2026, 10, 29)           # a Friday; Thursday is the previous session
WINDOW = market_freshness.Window(today=TODAY, floor=FLOOR, calendar_checked=True)


# ── EV-R: the resolver, both directions ──────────────────────────────────────
def got(message, persona="trader"):
    return resolve_intent(message, persona, None)


@pytest.mark.parametrize("message, period, fno, sector", [
    ("Which companies report results this week?", "this_week", False, None),          # the owner's screenshot
    ("which companies are reporting results today?", "today", False, None),
    ("Who reports results tomorrow?", "tomorrow", False, None),
    ("Results calendar for next week", "next_week", False, None),
    ("Which F&O stocks report results tomorrow?", "tomorrow", True, None),
    ("Which IT companies report results this week?", "this_week", False, "Information Technology"),
    ("What results are coming up next week?", "next_week", False, None),
    ("Which companies announced results today?", "today", False, None),
    ("Earnings this week", "this_week", False, None),
    ("upcoming results", "this_week", False, None),
    ("Results due next week", "next_week", False, None),
    ("Show me the results calendar", "this_week", False, None),
    ("Who reports earnings tomorrow", "tomorrow", False, None),
    ("Which banks declared results yesterday?", "yesterday", False, "Financial Services"),
    ("Which companies declared results last week", "last_week", False, None),
    ("Q2 results this week", "this_week", False, None),
    ("earnings calendar", "this_week", False, None),
])
def test_ev_r1_results_calendar(message, period, fno, sector):
    r = got(message)
    assert r is not None and r.name == "results_calendar", message
    assert r.symbol is None and r.params == {"period": period, "fno_only": fno, "sector": sector}


@pytest.mark.parametrize("message, category, period", [
    ("Any order wins this week?", "orders", "week"),
    ("Which companies won big orders today?", "orders", "today"),
    ("Show recent order wins", "orders", "week"),
    ("order book updates", "orders", "week"),
    ("contracts awarded this week", "orders", "week"),
    ("Any M&A announcements today?", "mna", "today"),
    ("Mergers and acquisitions this week", "mna", "week"),
    ("any demerger announced?", "mna", "week"),
    ("Show recent buyback announcements", "mna", "week"),
    ("open offers and takeovers", "mna", "week"),
    ("dividend announcements this week", "mna", "week"),
    ("stake sale by promoters", "mna", "week"),
    ("Show promoter holding changes", "ownership", "week"),
    ("Any promoter pledge this week?", "ownership", "week"),
    ("insider trading disclosures", "ownership", "week"),
    ("SAST disclosures this week", "ownership", "week"),
    ("Which stocks saw bulk deals today?", "deals", "today"),
    ("Block deals today", "deals", "today"),
    ("bulk and block deals this week", "deals", "week"),
    ("What did management say on the earnings calls this week?", "calls", "week"),
    ("Which companies gave guidance this week?", "calls", "week"),
    ("concall highlights", "calls", "week"),
    ("SEBI circulars this week", "regulatory", "week"),
    ("regulatory announcements today", "regulatory", "today"),
    ("exchange notices today", "exchange", "today"),
    ("price movement queries this week", "exchange", "week"),
    ("Any capex or QIP announcements?", "announcements", "week"),
    ("latest corporate announcements", "all", "week"),
])
def test_ev_r2_event_intelligence(message, category, period):
    r = got(message)
    assert r is not None and r.name == "event_intelligence", message
    assert r.symbol is None and r.params == {"category": category, "period": period}


@pytest.mark.parametrize("message, category, symbol", [
    ("How were TCS results?", "results", "TCS"),
    ("Did INFY beat estimates?", "results", "INFY"),
    ("What are the Q2 results of Reliance?", "results", "RELIANCE"),
    ("What did Infosys management say about guidance?", "calls", "INFY"),
    ("Any order wins for L&T?", "orders", "LT"),
    ("Latest announcements for TCS", "all", "TCS"),
    ("Any bulk deals in RELIANCE this week?", "deals", "RELIANCE"),
    ("Has there been promoter pledge change in INFY?", "ownership", "INFY"),
])
def test_ev_r3_a_named_stock_scopes_the_event_answer(message, category, symbol):
    r = got(message)
    assert r is not None and r.name == "event_intelligence", message
    assert (r.symbol, r.params["category"]) == (symbol, category)


@pytest.mark.parametrize("message, persona, expected", [
    ("Is INFY a buy now?", "trader", "stock_decision"),
    ("Is TCS a buy after results?", "trader", "stock_decision"),                # decision words win over a results word
    ("What is the entry, target and stop-loss for INFY after results?", "trader", "stock_decision"),
    ("Where is smart money moving?", "trader", "smart_money"),
    ("FII DII flows this week", None, "smart_money"),
    ("Which sectors are leading and lagging?", "trader", "sector_rotation"),
    ("What is the market view today?", "trader", "market_view"),
    ("Which F&O stocks show long build-up today?", "trader", "smart_money"),
    ("Which breakouts are confirmed?", "trader", "breakouts"),
    ("Which stocks have unusual volume?", "trader", "unusual_volume"),
    ("How did I do this week?", "trader", "daily_review"),
    ("What did I learn from today's trades?", "trader", "daily_review"),
    ("What are my open trades doing?", "trader", "open_trades"),
    ("Should I hold TCS after results?", "trader", "exit_options"),
    ("Is my trade in TCS still valid?", "trader", "trade_validity"),
    ("Which F&O setups are attractive?", "trader", "fno_setups"),
    ("What is the expected move in Nifty?", "trader", "expected_move"),
])
def test_ev_r4_questions_that_belong_elsewhere_stay_there(message, persona, expected):
    r = got(message, persona)
    assert r is not None and r.name == expected, message


@pytest.mark.parametrize("message", [
    "What is the promoter holding of TCS?",                  # a fact about the company, not an event
    "What is the dividend yield of ITC?",
    "What is a bulk deal?",                                   # a definition
    "Explain how to read quarterly results",
    "How do M&A deals work?",
    "Why did TCS fall after results?",                        # a price move
    "How did Nifty react to results this week?",
    "What is the order book depth of RELIANCE?",              # market depth, not order wins
    "Place an order for 10 shares of TCS",
    "How do I place a limit order?",
    "Latest news on TCS",                                     # news is not this feed
    "Compare TCS and Infosys",
    "TCS PE ratio",
    "Show the FIXCO chart",
    "Top gainers today",
    "Is this stock a buy now?",
])
def test_ev_r5_fundamentals_definitions_and_orders_are_not_events(message):
    r = got(message)
    assert r is None or r.name not in ("results_calendar", "event_intelligence"), (message, r)


def test_ev_r6_the_two_intents_are_registered_everywhere():
    from services import copilot_visual as cv
    for name in ("results_calendar", "event_intelligence"):
        assert name in INTENTS and name in BUILDERS and cv.AGENT_FOR[name] == "market_analyst"
    assert not re.search(r"\b(buy|sell|recommend|pick)\b", " ".join(INTENTS))


def test_ev_r7_every_follow_up_and_ask_the_answers_offer_resolves_back_to_an_answer():
    for q in ("Which F&O stocks report results tomorrow?", "Which companies report results next week?", "Any order wins this week?",
              "Any M&A announcements today?", "Which stocks saw bulk deals today?", "How were TCS results?", "Any recent announcements for INFY?",
              "Any order wins for TCS?", "Which companies report results this week?"):
        r = got(q)
        assert r is not None and r.name in ("results_calendar", "event_intelligence"), q


# ── EV-L: source-filing links ────────────────────────────────────────────────
GOOD = "https://nsearchives.nseindia.com/corporate/ACME_30102026170516_Outcome.pdf"


@pytest.mark.parametrize("url, ok", [
    (GOOD, True),
    ("https://www.bseindia.com/xml-data/corpfiling/AttachLive/abc.pdf", True),
    ("https://archives.nseindia.com/corporate/x.zip", True),
    ("https://www.sebi.gov.in/legal/circulars/oct-2026/x.html", True),
    ("http://nsearchives.nseindia.com/corporate/x.pdf", False),                  # not https
    ("javascript:alert(1)", False),
    ("https://nseindia.com.evil.io/x.pdf", False),                               # look-alike host
    ("https://evil.io/nseindia.com/x.pdf", False),
    ("https://user:pw@nsearchives.nseindia.com/x.pdf", False),                   # user-info
    ("https://nsearchives.nseindia.com@evil.io/x.pdf", False),
    ("https://nsearchives.nseindia.com:8443/x.pdf", False),
    ("https://nsearchives.nseindia.com/a b.pdf", False),
    ("https://nsearchives.nseindia.com\\@evil.io/x.pdf", False),
    ("//nsearchives.nseindia.com/x.pdf", False),
    ("", False), (None, False), (42, False),
])
def test_ev_l1_only_https_on_an_exchange_host(url, ok):
    assert (lk.safe_url(url) is not None) is ok and (not ok or lk.safe_url(url) == url)


def test_ev_l2_a_link_says_what_opens():
    assert lk.link("Results filing", GOOD) == {"label": "Results filing (PDF)", "url": GOOD, "kind": "pdf"}
    z = lk.link("Source filing", "https://nsearchives.nseindia.com/corporate/X_Doc.zip")
    assert z["kind"] == "file" and z["label"] == "Source filing (file)"
    assert lk.link("Circular", "https://www.sebi.gov.in/legal/circulars/x.html")["kind"] == "page"
    assert lk.link("x", "http://nsearchives.nseindia.com/x.pdf") is None


# ── MOCK sources ─────────────────────────────────────────────────────────────
def nse(name):
    return f"https://nsearchives.nseindia.com/corporate/{name}.pdf"


def outlook(summary=None, band=None, mat=None, analyzed="2026-10-29T09:30:00+00:00", aid=None):
    if summary is None:
        return {"analysed": False, "summary": None, "net_band": None, "net_impact_score": None, "confidence_score": None,
                "materiality_score": None, "event_ts": None, "analyzed_at": None, "announcement_id": None, "reason": "not analysed"}
    return {"analysed": True, "summary": summary, "net_band": band, "net_impact_score": 20.0, "confidence_score": 70.0,
            "materiality_score": mat, "event_ts": "2026-10-28T10:00:00+00:00", "analyzed_at": analyzed, "announcement_id": aid, "reason": None}


def rrow(sym, day="2026-10-28", status="declared", fno=False, sector="Capital Goods", verdict=None, intensity=None, ol=None, url=None, name=None):
    return {"symbol": sym, "name": name or f"{sym.title()} Limited", "sector": sector, "event_date": day, "status": status, "fno": fno,
            "period_label": "Q2 FY27 (Jul–Sep 2026)", "basis": "consolidated",
            "verdict": {"label": verdict, "intensity": intensity, "reason": None if verdict else "not rated: baseline too uncertain"},
            "outlook": ol or outlook(), "filing_url": url}


def week_rows():
    """12 declared (3 analysed, one of them F&O; 2 more F&O unanalysed), 1 held with figures not loaded, 2 due on Saturday."""
    rows = [
        rrow("RELI", fno=True, sector="Oil Gas & Consumable Fuels", verdict="above", ol=outlook("RELI stored summary.", "moderately_positive", 60.0, aid="a-reli")),
        rrow("ALPHA", verdict="below", intensity="well_below", ol=outlook("ALPHA stored summary.", "moderately_negative", 90.0, aid="a-alpha")),
        rrow("BETA", day="2026-10-29", ol=outlook("BETA stored summary.", "neutral_mixed", 30.0, aid="a-beta")),
        rrow("FNOA", fno=True, verdict="in_line"), rrow("FNOB", fno=True, sector="Financial Services"),
    ] + [rrow(f"PLAIN{i}", day=f"2026-10-{26 + i % 4}", sector=None if i % 2 else "Healthcare") for i in range(7)]
    rows += [rrow("HELD1", day="2026-10-30", status="pending", url=nse("HELD1_Outcome")),
             rrow("DUE1", day="2026-10-31", status="upcoming", fno=True, sector="Financial Services"),
             rrow("DUE2", day="2026-10-31", status="upcoming")]
    return rows


def afile(sym, mgmt=(), filings=(), name=None, gaps=()):
    return {"symbol": sym, "name": name or f"{sym.title()} Limited", "analyses": list(mgmt), "filings": list(filings), "gaps": list(gaps)}


def aitem(kind, summary, at="2026-10-28T12:00:00+00:00", pos=(), neg=(), unk=(), url=None, aid="x"):
    return {"at": at, "kind": kind, "title": kind, "subtype": None, "band": "moderately_positive", "impact": 20.0, "confidence": 70.0,
            "summary": summary, "positives": list(pos), "negatives": list(neg), "amounts": [], "open_questions": list(unk),
            "announcement_id": aid, "url": url}


def fl(kind, subject, day, fname, results=True):
    return {"announcement_id": f"id-{fname}", "filed_at": f"{day}T11:00:00+00:00", "subject": subject, "description": subject,
            "url": nse(fname) if fname else None, "kind": kind, "results_related": results}


def frow(i, sym, day="2026-10-29", one=None, impact=None, sentiment=None, doc="Updates", cat="Orders", url="auto"):
    return {"id": f"f{i}", "ticker": sym, "code": sym, "name": f"{sym.title()} Limited", "date": f"{day}T11:30:00+00:00", "exchange": "NSE",
            "category": cat, "impact": impact, "sentiment": sentiment, "docLabel": doc, "one": one, "hasInsights": bool(one),
            "url": nse(f"{sym}_{i}") if url == "auto" else url}


class Ev:
    """Every event reader, replaced. `fail` names readers that raise."""

    def __init__(self, mp):
        self.rows = week_rows()
        self.files = {}
        self.feed = {}
        self.fail = set()
        self.deals = {"as_of": "2026-10-29", "source": "NSE bulk and block deals", "disclosure": "Every row is NSE's own disclosure.", "total": 0, "rows": []}
        self.circulars = {"as_of": "2026-10-29", "rows": []}
        self.newest = "2026-10-30"
        self.calls = []
        self.running = 0
        self.peak = 0
        self.analysis_ok = True

        async def window():
            return WINDOW

        async def results_rows(start, end):
            self.calls.append(("results_rows", start, end))
            if "results_rows" in self.fail:
                raise RuntimeError("MOCK calendar down")
            rows = [r for r in self.rows if start.isoformat() <= r["event_date"] <= end.isoformat()]
            return {"rows": rows, "as_of": "2026-10-30", "partial": False, "gaps": [], "analysis_ok": self.analysis_ok}

        async def company_results_file(symbol, since):
            self.calls.append(("file", symbol, since))
            self.running += 1
            self.peak = max(self.peak, self.running)
            try:
                await asyncio.sleep(0.01)
                if "file" in self.fail or symbol in self.fail:
                    raise RuntimeError(f"MOCK file of {symbol} down")
                return self.files.get(symbol) or afile(symbol)
            finally:
                self.running -= 1

        async def filings_feed(request, *, days, category=None, family=None, symbol=None, limit=40):
            self.calls.append(("feed", category, family, symbol, days, limit))
            if "feed" in self.fail:
                raise RuntimeError("MOCK feed down")
            key = ("symbol", symbol) if symbol else (category or family or "all")
            rows = self.feed.get(key, [])
            return {"ok": True, "total": len(rows) if key not in self.feed.get(("totals",), {}) else self.feed[("totals",)][key], "rows": rows}

        async def latest_filing_day(request):
            if "newest" in self.fail:
                raise RuntimeError("MOCK newest down")
            return self.newest

        async def deals(request, *, days, symbol, limit):
            self.calls.append(("deals", days, symbol))
            if "deals" in self.fail:
                raise RuntimeError("MOCK deals down")
            return self.deals

        async def sebi_circulars(request, *, days, limit):
            if "circulars" in self.fail:
                raise RuntimeError("MOCK circulars down")
            return self.circulars
        for name, fn in (("window", window), ("results_rows", results_rows), ("company_results_file", company_results_file),
                         ("filings_feed", filings_feed), ("latest_filing_day", latest_filing_day), ("deals", deals),
                         ("sebi_circulars", sebi_circulars)):
            mp.setattr(rd, name, fn)


@pytest.fixture
def ev(monkeypatch):
    return Ev(monkeypatch)


def build(name, symbol=None, params=None):
    p = asyncio.run(builders.build(Intent(name, symbol=symbol, params=params or {}), {"user_id": "u1"}, request="REQ"))
    assert validate(p) == [], validate(p)
    return p


def calendar(period="this_week", fno=False, sector=None):
    return build("results_calendar", params={"period": period, "fno_only": fno, "sector": sector})


def events(category, period="week", symbol=None):
    return build("event_intelligence", symbol=symbol, params={"category": category, "period": period})


def blk(p, bid):
    return next((b for b in p["blocks"] if b.get("id") == bid), None)


def texts(p):
    out = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
    walk(p)
    return " ".join(out)


def test_ev_l3_the_reader_classifies_a_filing_by_its_subject_line_only(monkeypatch):
    """readers.company_results_file: the desk's own kind_of on the exchange subject; the description only says whether it is about results."""
    from services.results_week import loaders, stock as rws
    rows = [{"announcement_id": "a1", "subject": "Outcome of Board Meeting", "description": "submitted the Unaudited financial results", "attachment_url": nse("O"), "filed_at": "2026-10-28T10:00:00+00:00"},
            {"announcement_id": "a2", "subject": "Copy of Newspaper Publication", "description": "Newspaper Publication of Unaudited Financial Results", "attachment_url": nse("N")},
            {"announcement_id": "a3", "subject": "Press Release", "description": "press release titled Financial Results", "attachment_url": nse("P")},
            {"announcement_id": "a4", "subject": "Investor Presentation", "description": "Investor Presentation", "attachment_url": nse("I")},
            {"announcement_id": "a5", "subject": "Analysts/Institutional Investor Meet/Con. Call Updates", "description": "Audio recording of the call", "attachment_url": nse("C")},
            {"announcement_id": "a6", "subject": "Updates", "description": "an order win", "attachment_url": None}]

    async def all_analyses(db, sym, start, end):
        return [], None

    async def daas_get(path, params=None, timeout=20.0):
        assert path == "/announcements" and params["symbol"] == "ACME"
        return 200, {"data": [{**r, "company_name": "Acme Limited"} for r in rows]}
    monkeypatch.setattr(rws, "all_analyses", all_analyses)
    monkeypatch.setattr(loaders, "daas_get", daas_get)
    f = asyncio.run(rd.company_results_file("ACME", date(2026, 10, 1)))
    kinds = {x["announcement_id"]: (x["kind"], x["results_related"]) for x in f["filings"]}
    assert kinds == {"a1": ("board_outcome", True), "a2": ("other", True), "a3": ("press_release", True), "a4": ("presentation", False),
                     "a5": ("earnings_call", False), "a6": ("business_update", False)}      # "Updates" is the desk's own business-update subject
    assert f["name"] == "Acme Limited" and f["gaps"] == []


# ── EV-B: the results calendar ───────────────────────────────────────────────
def test_ev_b1_this_week_counts_cards_and_the_due_list(ev):
    p = calendar()
    assert p["intent"] == "results_calendar" and p["as_of"] == "2026-10-30" and p["title"] == "Results calendar · 26–31 Oct 2026"
    assert "15 companies report" in p["headline"]["text"] and "12 declared" in p["headline"]["text"] and "3 with an AI summary" in p["headline"]["text"]
    kp = {i["label"]: i for i in blk(p, "counts")["items"]}
    assert (kp["Companies"]["value"], kp["Declared"]["value"], kp["Figures awaited"]["value"], kp["Still to report"]["value"], kp["F&O names"]["value"]) \
        == ("15", "12", "1", "2", "4")
    assert kp["Declared"]["sub"] == "3 with an AI summary, 9 not analysed yet"
    assert kp["Above · in line · below"]["value"] == "1 · 1 · 1" and kp["Above · in line · below"]["sub"].startswith("9 not rated")
    assert [b["id"] for b in p["blocks"] if b["type"] != "notice"] == ["counts", "declared", "due"] and p["blocks"][-1]["id"] == "more"


def test_ev_b2_cards_are_the_stored_summaries_analysed_first_f_and_o_favoured_capped(ev):
    p = calendar()
    cards = blk(p, "declared")["items"]
    assert len(cards) == 8
    # analysed first (F&O before the rest, then the more material), then the unanalysed F&O names, then the others
    assert [c["symbol"] for c in cards[:5]] == ["RELI", "ALPHA", "BETA", "FNOA", "FNOB"]
    assert cards[0]["body"] == "RELI stored summary." and cards[1]["body"] == "ALPHA stored summary."        # the stored text, verbatim
    assert "AI summary" in cards[0]["body_note"] and "Not a recommendation" in cards[0]["body_note"] and "29 Oct 2026" in cards[0]["body_note"]
    assert cards[3]["body"] is None and cards[3]["body_note"] == "Not analysed yet"
    assert cards[0]["title"] == "Reli Limited"
    more = blk(p, "more")
    assert "8 of 12 declared results" in more["text"] and "all 3 still to report" in more["text"]
    assert more["actions"] == [{"kind": "open_market_intel", "label": "Open in Market Intelligence"}]


def test_ev_b3_the_badge_is_the_desks_verdict_else_the_filing_read_else_not_rated(ev):
    cards = {c["symbol"]: c for c in blk(calendar(), "declared")["items"]}
    assert (cards["RELI"]["badge"], cards["RELI"]["tone"]) == ("Above historical trend", "up")
    assert (cards["ALPHA"]["badge"], cards["ALPHA"]["tone"]) == ("Well below historical trend", "down")
    assert (cards["BETA"]["badge"], cards["BETA"]["tone"]) == ("Filing read: neutral mixed", "neutral")
    assert (cards["FNOA"]["badge"], cards["FNOA"]["tone"]) == ("In line with historical trend", "neutral")
    assert (cards["FNOB"]["badge"], cards["FNOB"]["tone"]) == ("Not rated", "neutral")
    assert "F&O" in cards["RELI"]["sub"] and "Q2 FY27" in cards["RELI"]["sub"] and "28 Oct" in cards["RELI"]["sub"]
    assert "consensus" in blk(calendar(), "declared")["note"]


def test_ev_b4_management_commentary_and_source_links_come_from_the_companys_file(ev):
    ev.files["RELI"] = afile("RELI", mgmt=[
        aitem("presentation", "Investor deck: refining margins firmed.", pos=["GRM up", "Retail steady", "third"], neg=["Capex heavy"], unk=["Guidance on O2C?"],
              url=nse("RELI_pres"), aid="p1"),
        aitem("earnings_call", "Call: management expects a firmer second half.", at="2026-10-29T12:00:00+00:00", aid="c1", url=nse("RELI_call")),
        aitem("presentation", "Last quarter's deck.", at="2026-07-20T12:00:00+00:00", aid="old")],
        filings=[fl("results", "Outcome of Board Meeting", "2026-10-28", "RELI_outcome"), fl("press_release", "Press Release", "2026-10-28", "RELI_pr"),
                 fl("presentation", "Investor Presentation", "2026-10-28", "RELI_pres"), fl("earnings_call", "Con. Call", "2026-10-29", "RELI_call", results=False),
                 fl("presentation", "Investor Presentation", "2026-07-20", "RELI_old"), fl("results", "Outcome of Board Meeting", "2026-10-28", None)])
    c = next(c for c in blk(calendar(), "declared")["items"] if c["symbol"] == "RELI")
    assert [l["label"] for l in c["links"]] == ["Results filing (PDF)", "Results press release (PDF)", "Investor presentation (PDF)", "Earnings call / investor meet (PDF)"]
    assert all(l["kind"] == "pdf" and lk.safe_url(l["url"]) for l in c["links"])
    assert c["links"][0]["url"] == nse("RELI_outcome")                      # an older quarter's deck and a filing with no URL are not linked
    texts_ = [pt["text"] for pt in c["points"]]
    assert any("Investor presentation" in t and "Investor deck: refining margins firmed." in t for t in texts_)
    assert any("Earnings call" in t and "firmer second half" in t for t in texts_)
    assert not any("Last quarter's deck" in t for t in texts_)                       # before this result: not its commentary
    tones = {(pt["tone"], pt["text"]) for pt in c["points"]}
    assert ("up", "GRM up") in tones and ("down", "Capex heavy") in tones and any(t == "neutral" and "Guidance on O2C?" in x for t, x in tones)
    assert len(c["points"]) <= 7


def test_ev_b4b_a_newspaper_advertisement_is_not_the_results_filing_and_a_file_is_linked_once(ev):
    ad = fl("other", "Copy of Newspaper Publication", "2026-10-28", "RELI_newspaper")            # its text mentions the results
    ev.files["RELI"] = afile("RELI", filings=[ad, fl("press_release", "Press Release", "2026-10-28", "RELI_deck"),
                                              fl("presentation", "Investor Presentation", "2026-10-28", "RELI_deck")])      # one PDF is both
    c = next(c for c in blk(calendar(), "declared")["items"] if c["symbol"] == "RELI")
    assert [(l["label"], l["url"]) for l in c["links"]] == [("Results press release (PDF)", nse("RELI_deck"))]


def test_ev_b5_a_forged_or_foreign_link_never_reaches_the_payload(ev):
    bad = fl("results", "Outcome of Board Meeting", "2026-10-28", None)
    bad["url"] = "http://evil.example/x.pdf"
    worse = fl("presentation", "Investor Presentation", "2026-10-28", None)
    worse["url"] = "https://nseindia.com.evil.io/x.pdf"
    ev.files["RELI"] = afile("RELI", filings=[bad, worse])
    c = next(c for c in blk(calendar(), "declared")["items"] if c["symbol"] == "RELI")
    assert c["links"] == []
    assert "evil" not in json.dumps(calendar())


def test_ev_b6_an_unreadable_company_file_is_said_and_the_card_keeps_its_summary(ev):
    ev.fail.add("RELI")
    p = calendar()
    c = next(c for c in blk(p, "declared")["items"] if c["symbol"] == "RELI")
    assert c["body"] == "RELI stored summary." and c["points"] == [] and c["links"] == []
    assert any("RELI" in m for m in p["data_quality"]["missing"])


def test_ev_b7_per_company_reads_are_capped_and_gated(ev):
    calendar()
    reads = [c for c in ev.calls if c[0] == "file"]
    assert len(reads) == 8 and ev.peak <= 4                                             # CARD_CAP companies, FILE_CONCURRENCY at a time


def test_ev_b8_figures_awaited_and_due_companies_are_listed_f_and_o_first(ev):
    p = calendar()
    r = blk(p, "due")
    assert r["type"] == "ranked" and [row["symbol"] for row in r["rows"]] == ["DUE1", "HELD1", "DUE2"]
    assert r["rows"][0]["cells"]["fno"] == "F&O" and r["rows"][1]["cells"]["status"] == "Figures awaited" and r["rows"][2]["cells"]["fno"] == "—"
    assert r["rows"][0]["cells"]["date"] == "31 Oct" and r["rows"][0]["ask"] == "How were DUE1 results?"
    held = r["rows"][1]
    assert held["cells"]["status"] == "Figures awaited"


def test_ev_b9_next_week_has_no_cards_only_the_list(ev):
    ev.rows = [rrow(f"N{i}", day=f"2026-11-0{2 + i % 5}", status="upcoming", fno=i < 3) for i in range(20)]
    p = calendar("next_week")
    assert p["title"] == "Results calendar · 2–7 Nov 2026" and blk(p, "declared") is None
    r = blk(p, "due")
    assert len(r["rows"]) == 15 and [x["symbol"] for x in r["rows"][:3]] == ["N0", "N1", "N2"]       # F&O names first, then by date
    assert "15 of 20" in blk(p, "more")["text"]
    assert ev.calls[0][1:] == (date(2026, 11, 2), date(2026, 11, 7))


@pytest.mark.parametrize("period, start, end, title", [
    ("today", date(2026, 10, 30), date(2026, 10, 30), "Results calendar · Fri 30 Oct 2026"),
    ("tomorrow", date(2026, 10, 31), date(2026, 10, 31), "Results calendar · Sat 31 Oct 2026"),
    ("yesterday", date(2026, 10, 29), date(2026, 10, 29), "Results calendar · Thu 29 Oct 2026"),
    ("last_week", date(2026, 10, 19), date(2026, 10, 24), "Results calendar · 19–24 Oct 2026"),
])
def test_ev_b10_the_period_is_the_date_range_asked_for(ev, period, start, end, title):
    p = calendar(period)
    assert p["title"] == title and ev.calls[0][1:] == (start, end)


def test_ev_b11_f_and_o_only_and_sector_filters(ev):
    p = calendar(fno=True)
    assert {c["symbol"] for c in blk(p, "declared")["items"]} == {"RELI", "FNOA", "FNOB"}
    assert "F&O names only" in p["headline"]["text"]
    q = calendar(sector="Financial Services")
    assert {c["symbol"] for c in blk(q, "declared")["items"]} == {"FNOB"} and [r["symbol"] for r in blk(q, "due")["rows"]] == ["DUE1"]
    assert "Financial Services" in q["title"] and any("no sector on record" in n["text"] for n in q["blocks"] if n["type"] == "notice")


def test_ev_b12_nothing_reporting_says_so(ev):
    ev.rows = []
    p = calendar("tomorrow")
    assert blk(p, "declared") is None and blk(p, "due") is None
    assert any("No company has a results meeting" in n["text"] for n in p["blocks"] if n["type"] == "notice")


def test_ev_b13_calendar_unreadable_is_missing_and_nothing_is_invented(ev):
    ev.fail.add("results_rows")
    p = calendar()
    assert not [b for b in p["blocks"] if b["type"] in ("kpis", "briefs", "ranked")]
    assert p["headline"] is None and any("calendar" in m.lower() for m in p["data_quality"]["missing"])


def test_ev_b14_analyses_unreadable_is_not_called_not_analysed(ev):
    ev.analysis_ok = False
    p = calendar()
    cards = blk(p, "declared")["items"]
    assert all(c["body_note"] != "Not analysed yet" for c in cards)
    assert any("could not be read" in c["body_note"] for c in cards) and any("filing analyses" in m for m in p["data_quality"]["missing"])


def test_ev_b15_a_stale_calendar_is_flagged(ev, monkeypatch):
    async def old(start, end):
        return {"rows": [rrow("OLD1", day="2026-10-28")], "as_of": "2026-10-20", "partial": False, "gaps": [], "analysis_ok": True}
    monkeypatch.setattr(rd, "results_rows", old)
    p = calendar()
    assert p["data_quality"]["stale"] is True


def test_ev_b16_a_partial_calendar_says_the_counts_are_partial(ev, monkeypatch):
    async def partial(start, end):
        return {"rows": week_rows()[:3], "as_of": "2026-10-30", "partial": True, "gaps": ["results calendar 29 Oct to 31 Oct could not be read"], "analysis_ok": True}
    monkeypatch.setattr(rd, "results_rows", partial)
    p = calendar()
    assert any(n["tone"] == "warn" and "part of the calendar" in n["text"].lower() for n in p["blocks"] if n["type"] == "notice")


def test_ev_b17_sunday_this_week_is_the_coming_week(ev, monkeypatch):
    async def sunday():
        return market_freshness.Window(today=date(2026, 11, 1), floor=date(2026, 10, 30), calendar_checked=True)
    monkeypatch.setattr(rd, "window", sunday)
    p = calendar("this_week")
    assert p["title"] == "Results calendar · 2–7 Nov 2026"


# ── EV-E: event intelligence ─────────────────────────────────────────────────
def order_rows():
    rows = [frow(1, "GAYA", one="Gayatri won a Rs 342 crore contract.", impact="high", sentiment="positive", doc="Updates"),
            frow(2, "WAAR", one=None, doc="Bagging/Receiving of orders/contracts"),
            frow(3, "ATLA", one="MSRDC re-invited bids. · Assessed as routine (importance 50/100)", impact="medium", sentiment="negative", day="2026-10-28"),
            frow(4, "ZED", one="Zed won an order.", impact="low", sentiment="neutral", day="2026-10-30"),
            frow(5, "NOURL", one="No attachment here.", impact="high", sentiment="positive", url=None)]
    rows += [frow(10 + i, f"X{i}", one=f"X{i} summary.", impact="medium", sentiment="positive") for i in range(6)]
    return rows


def test_ev_e1_orders_cards_are_the_stored_text_analysed_first_then_by_impact(ev):
    ev.feed["orders"] = order_rows()
    ev.feed[("totals",)] = {"orders": 74}
    p = events("orders")
    assert p["title"] == "Order wins · last 7 days" and p["as_of"] == "2026-10-30"
    cards = blk(p, "events")["items"]
    assert len(cards) == 8
    assert [c["symbol"] for c in cards[:4]] == ["GAYA", "NOURL", "X0", "X1"]            # high impact first, then medium by recency/order
    gaya = cards[0]
    assert gaya["body"] == "Gayatri won a Rs 342 crore contract." and gaya["badge"] == "Positive · high impact" and gaya["tone"] == "up"
    assert gaya["links"] == [{"label": "Source filing (PDF)", "url": nse("GAYA_1"), "kind": "pdf"}]
    assert "29 Oct 2026" in gaya["sub"] and "NSE" in gaya["sub"] and "Updates" in gaya["sub"]
    assert "Not a recommendation" in gaya["body_note"] and "AI summary" in gaya["body_note"]
    nourl = cards[1]
    assert nourl["links"] == []
    assert re.search(r"8 of 74 order filings", blk(p, "more")["text"]) and blk(p, "more")["actions"][0]["kind"] == "open_market_intel"


def test_ev_e1b_a_filing_with_no_stored_analysis_says_so_and_keeps_its_link(ev):
    ev.feed["orders"] = order_rows()[:2]
    waar = next(c for c in blk(events("orders"), "events")["items"] if c["symbol"] == "WAAR")
    assert waar["body"] is None and waar["body_note"] == "Not analysed yet" and waar["badge"] is None
    assert waar["links"] == [{"label": "Source filing (PDF)", "url": nse("WAAR_2"), "kind": "pdf"}]


def test_ev_e2_m_and_a_merges_the_desks_three_categories_without_duplicates(ev):
    ev.feed["mna"] = [frow(1, "AAA", cat="Mna", one="AAA merger.", day="2026-10-28")]
    ev.feed["dividend"] = [frow(2, "BBB", cat="Dividend", one="BBB dividend.", day="2026-10-29"), frow(1, "AAA", cat="Mna", one="AAA merger.", day="2026-10-28")]
    ev.feed["buyback"] = [frow(3, "CCC", cat="Buyback", one="CCC buyback.", day="2026-10-30")]
    p = events("mna")
    assert p["title"] == "M&A and corporate actions · last 7 days"
    assert sorted(c["symbol"] for c in blk(p, "events")["items"]) == ["AAA", "BBB", "CCC"]
    assert sorted((c[1] for c in ev.calls if c[0] == "feed")) == ["buyback", "dividend", "mna"]


def test_ev_e3_ownership_uses_the_family_feed_and_repeats_the_desks_gap(ev):
    ev.feed["ownership"] = [frow(1, "MACP", cat="Mna", doc="Disclosure under SEBI Takeover Regulations", one="A promoter will receive 13.38% in a family transfer.",
                                 impact="low", sentiment="neutral")]
    p = events("ownership")
    assert [c[2] for c in ev.calls if c[0] == "feed"] == ["ownership"]
    assert blk(p, "events")["items"][0]["symbol"] == "MACP"
    assert any("not loaded yet" in n["text"] and "SAST" in n["text"] for n in p["blocks"] if n["type"] == "notice")


def test_ev_e4_bulk_and_block_deals_are_a_table_with_the_exchanges_disclosure(ev):
    ev.deals = {"as_of": "2026-10-29", "source": "NSE bulk and block deals", "disclosure": "Every row is NSE's own disclosure; nothing is inferred.", "total": 389,
                "rows": [{"date": "2026-10-29", "kind": "bulk", "symbol": "SAGI", "client_name": "SAGI B.V.", "side": "SELL", "quantity": 560000000,
                          "avg_price": 42.76, "value_cr": 2394.56, "pct_of_shares": 11.9624},
                         {"date": "2026-10-29", "kind": "block", "symbol": "SWIG", "client_name": "TENCENT", "side": "BUY", "quantity": 54347662,
                          "avg_price": 180.65, "value_cr": 981.79, "pct_of_shares": None}]}
    p = events("deals", "week")
    r = blk(p, "deals")
    assert r["type"] == "ranked" and [x["symbol"] for x in r["rows"]] == ["SAGI", "SWIG"]
    c = r["rows"][0]["cells"]
    assert (c["kind"], c["client"], c["side"], c["value"], c["pct"], c["date"]) == ("Bulk", "SAGI B.V.", "Sell", "₹2,394.56 Cr", "11.96%", "29 Oct")
    assert r["rows"][1]["cells"]["pct"] == "—" and r["rows"][0]["ask"]
    assert "nothing is inferred" in texts(p) and re.search(r"2 of 389", blk(p, "more")["text"])


def test_ev_e5_no_deals_says_so_and_stale_deals_are_flagged(ev):
    p = events("deals", "today")
    assert blk(p, "deals") is None and any("No bulk or block deals" in n["text"] for n in p["blocks"] if n["type"] == "notice")
    ev.deals = {**ev.deals, "as_of": "2026-10-20", "total": 1, "rows": [{"date": "2026-10-20", "kind": "bulk", "symbol": "OLD", "client_name": "C", "side": "BUY",
                                                                       "quantity": 1, "avg_price": 1.0, "value_cr": 1.0, "pct_of_shares": 1.0}]}
    assert events("deals")["data_quality"]["stale"] is True


def test_ev_e6_regulatory_adds_sebi_circulars_with_their_own_links(ev):
    ev.feed["regulatory"] = [frow(1, "REGA", cat="Regulatory", one="Reg A.", doc="Reg 30")]
    ev.feed["litigation"] = [frow(2, "LITB", cat="Litigation", one="Lit B.", doc="Court order")]
    ev.circulars = {"as_of": "2026-10-29", "rows": [{"title": "Master circular on X", "url": "https://www.sebi.gov.in/legal/master-circulars/oct-2026/x_1.html",
                                                     "kind": "master_circular", "issued_on": "2026-10-28"},
                                                    {"title": "Forged", "url": "http://evil.example/c.html", "kind": "circular", "issued_on": "2026-10-28"}]}
    p = events("regulatory")
    assert {i["symbol"] for i in blk(p, "events")["items"]} == {"REGA", "LITB"}
    circ = blk(p, "circulars")["items"]
    sebi = next(i for i in circ if i["title"] == "Master circular on X")
    assert sebi["links"][0]["kind"] == "page" and sebi["sub"].startswith("28 Oct 2026") and not [i for i in circ if i["title"] == "Forged" and i["links"]]


def test_ev_e7_calls_and_guidance_say_the_filing_is_not_analysed(ev):
    ev.feed["calls"] = [frow(1, "CALL", cat="Markets", doc="Analysts/Institutional Investor Meet/Con. Call Updates", one=None)]
    p = events("calls")
    c = blk(p, "events")["items"][0]
    assert c["body"] is None and c["body_note"] == "Not analysed yet" and c["links"][0]["url"] == nse("CALL_1")
    assert any("guidance tracker" in n["text"] for n in p["blocks"] if n["type"] == "notice")


def test_ev_e8_today_keeps_only_todays_filings_and_says_when_there_are_none(ev):
    ev.feed["orders"] = order_rows()
    p = events("orders", "today")
    assert [c["symbol"] for c in blk(p, "events")["items"]] == ["ZED"]
    ev.feed["orders"] = [frow(1, "OLDX", day="2026-10-27", one="old")]
    q = events("orders", "today")
    assert blk(q, "events") is None and any("No order filings" in n["text"] and "today" in n["text"] for n in q["blocks"] if n["type"] == "notice")


def test_ev_e9_feed_unreadable_is_missing_and_nothing_is_invented(ev):
    ev.fail.add("feed")
    p = events("orders")
    assert not blk(p, "events") and any("filings feed" in m.lower() for m in p["data_quality"]["missing"])


def test_ev_e10_a_stocks_events_come_from_its_own_feed_filtered_to_the_category(ev):
    ev.feed[("symbol", "LT")] = [frow(1, "LT", cat="Orders", one="L&T won orders.", doc="Bagging/Receiving of orders/contracts"),
                                 frow(2, "LT", cat="Dividend", one="L&T dividend."), frow(3, "LT", cat="Orders", one=None)]
    p = events("orders", "month", symbol="LT")
    assert p["title"] == "LT · order wins · last 30 days"
    assert [c[3] for c in ev.calls if c[0] == "feed"] == ["LT"]
    assert len(blk(p, "events")["items"]) == 2


# ── EV-S: "How were TCS results?" ────────────────────────────────────────────
def tcs_inputs(ev, analysed=True):
    ev.feed[("symbol", "TCS")] = [
        frow(1, "TCS", day="2026-10-09", cat="Earnings", doc="Outcome of Board Meeting", one="TCS stored result summary." if analysed else None,
             impact="medium", sentiment="positive", url=nse("TCS_outcome")),
        frow(2, "TCS", day="2026-10-10", cat="Earnings", doc="Updates", one="TCS filed its call transcript.", url=nse("TCS_transcript")),
        frow(3, "TCS", day="2026-10-05", cat="Orders", doc="Updates", one="An order.")]
    ev.files["TCS"] = afile("TCS", name="Tata Consultancy Services Limited",
                            mgmt=[aitem("presentation", "TCS deck says deal wins were strong.", at="2026-10-09T13:00:00+00:00", pos=["Deal wins"], aid="p9", url=nse("TCS_deck"))],
                            filings=[fl("results", "Outcome of Board Meeting", "2026-10-09", "TCS_outcome"), fl("presentation", "Investor Presentation", "2026-10-09", "TCS_deck")])
    ev.rows = [rrow("TCS", day="2026-10-09", fno=True, sector="Information Technology", verdict="in_line", name="Tata Consultancy Services Limited")]


def test_ev_s1_a_stocks_results_are_one_card_with_summary_commentary_and_links(ev):
    tcs_inputs(ev)
    p = events("results", "month", symbol="TCS")
    assert p["title"] == "Tata Consultancy Services Limited · results"
    cards = blk(p, "events")["items"]
    assert len(cards) == 1
    c = cards[0]
    assert c["body"] == "TCS stored result summary." and c["badge"] == "In line with historical trend" and "Q2 FY27" in c["sub"] and "9 Oct 2026" in c["sub"]
    assert [l["label"] for l in c["links"]][:2] == ["Results filing (PDF)", "Investor presentation (PDF)"]
    pts = [x["text"] for x in c["points"]]
    assert any("deal wins were strong" in t for t in pts) and any("call transcript" in t for t in pts)       # the file's analysis + the feed's other earnings filing
    assert "no analyst consensus" in texts(p).lower() and not re.search(r"\b(beat|missed)\b", c["badge"], re.I)


def test_ev_s2_not_analysed_still_shows_the_filing_link(ev):
    tcs_inputs(ev, analysed=False)
    c = blk(events("results", "month", symbol="TCS"), "events")["items"][0]
    assert c["body"] is None and c["body_note"] == "Not analysed yet" and c["links"][0]["url"] == nse("TCS_outcome")


def test_ev_s3_no_calendar_row_means_no_verdict_not_a_guess(ev):
    tcs_inputs(ev)
    ev.rows = []
    c = blk(events("results", "month", symbol="TCS"), "events")["items"][0]
    assert c["badge"] == "Positive · medium impact"            # the classifier's reading of the filing, labelled as such
    ev.fail.add("results_rows")
    p = events("results", "month", symbol="TCS")
    assert blk(p, "events")["items"][0]["body"] == "TCS stored result summary." and any("calendar" in m.lower() for m in p["data_quality"]["missing"])


def test_ev_s4_no_results_filing_at_all_says_so(ev):
    p = events("results", "month", symbol="NOSUCH")
    assert not blk(p, "events") and any("No results filing" in n["text"] for n in p["blocks"] if n["type"] == "notice")


def test_ev_s5_calls_for_a_stock_is_its_management_commentary(ev):
    tcs_inputs(ev)
    p = events("calls", "month", symbol="TCS")
    assert "management" in p["title"].lower() and blk(p, "events")["items"][0]["points"]


# ── EV-C / EV-F / EV-W: contract, facts, wording, wiring ─────────────────────
def test_ev_c1_the_contract_check_covers_briefs_and_the_new_action(ev):
    p = calendar()
    assert validate(p) == []
    bad = json.loads(json.dumps(p))
    b = blk(bad, "declared")
    b["items"][0]["links"] = [{"label": "x", "url": "http://evil.example/x.pdf", "kind": "pdf"}]
    assert any("link" in x for x in validate(bad))
    b["items"][0]["links"] = [{"label": "x", "url": GOOD, "kind": "exe"}]
    assert any("link" in x for x in validate(bad))
    b["items"][0]["links"] = []
    b["items"][0]["tone"] = "great"
    assert any("tone" in x for x in validate(bad))
    b["items"][0]["tone"] = "up"
    b["items"][0]["title"] = 5
    assert any("briefs" in x for x in validate(bad))
    bad2 = json.loads(json.dumps(p))
    blk(bad2, "more")["actions"] = [{"kind": "rm_rf", "label": "x"}]
    assert any("action" in x for x in validate(bad2))


def test_ev_f1_the_facts_carry_the_cards_so_the_engine_explains_only_what_is_shown(ev):
    f = facts(calendar())
    assert "RELI stored summary." in f and "Above historical trend" in f and "Not analysed yet" in f and "source link" in f
    assert "VISUAL_ANSWER (results_calendar)" in f and len(f) <= 6100


def test_ev_f2_wording_is_ideas_to_review_never_a_recommendation(ev):
    ev.feed["orders"] = order_rows()
    for p in (calendar(), events("orders")):
        body = texts(p)
        assert not re.search(r"\b(buy now|strong buy|recommend(ed|ation)?s?|sell now|picks?|target price)\b", body.replace("Not a recommendation", "").replace("not recommendations", "").replace("not a recommendation", ""), re.I), body[:200]
        assert "not a recommendation" in body.lower() or "not recommendations" in body.lower()


def test_ev_w1_the_suggestions_and_the_trader_prompts_cover_the_new_intents():
    from routes import copilot_prompts as cp
    from services.suggestions import catalog
    for name in ("results_calendar", "event_intelligence"):
        qs = [t["query"] for t in catalog.QUERY_TEMPLATES if t["intent"] == name]
        assert qs and all(resolve_intent(q, "trader", None).name == name for q in qs), name
    ids = [q[0] for q in cp._TRADER_QUESTIONS]
    for name in ("results_calendar", "event_intelligence"):
        row = next(q for q in cp._TRADER_QUESTIONS if q[0] == name)
        assert resolve_intent(row[2], "trader", None).name == name


def test_ev_p1_the_owners_question_goes_through_the_chat_pre_step_to_a_dashboard_pinned_to_the_market_analyst(ev):
    """services.copilot_visual.prepare is what routes/chat.py calls: resolver → builder → payload check → widget + facts + pinned node."""
    from services import copilot_visual as cv
    va = asyncio.run(cv.prepare("REQ", {"user_id": "u1"}, "Which companies report results this week?", "trader", "trading_desk", None, None))
    assert va is not None and va.intent.name == "results_calendar" and va.agent == "market_analyst"
    assert va.widget["widget_type"] == "visual_answer" and va.widget["data"]["intent"] == "results_calendar"
    assert "RELI stored summary." in va.facts and "VISUAL_ANSWER (results_calendar)" in va.facts
    for msg in ("How were TCS results?", "Any order wins this week?"):
        ev.feed["orders"] = order_rows()
        tcs_inputs(ev)
        assert asyncio.run(cv.prepare("REQ", {"user_id": "u1"}, msg, "trader", None, None, None)).widget["data"]["intent"] == "event_intelligence"


CAPTURE = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures" / "events-answers.mock.json"
ABOUT = ("MOCK — not real data. The three event answers built by the real builders (services/copilot_visual/events_builders.py) over the unit tests' "
         "invented inputs (tests/test_copilot_events.py): the results calendar of a week, the orders feed, and one stock's results file.")


def mock_payloads(ev):
    tcs_inputs(ev)
    ev.feed["orders"] = order_rows()[:7]
    ev.feed[("totals",)] = {"orders": 74}
    ev.rows += week_rows()
    ev.files["RELI"] = afile("RELI", mgmt=[aitem("presentation", "Investor deck: refining margins firmed.", pos=["GRM up"], neg=["Capex heavy"], unk=["Guidance on O2C?"],
                                                 url=nse("RELI_pres"), aid="p1")],
                             filings=[fl("results", "Outcome of Board Meeting", "2026-10-28", "RELI_outcome"), fl("presentation", "Investor Presentation", "2026-10-28", "RELI_pres")])
    return {"calendar": calendar(), "orders": events("orders"), "tcs": events("results", "month", symbol="TCS")}


def test_ev_w2_the_committed_mock_fixture_is_what_the_builders_make_today(ev):
    """The Playwright fixture is the REAL builder over THESE mock inputs; set WRITE_EVENTS_FIXTURE=1 to rewrite it."""
    import os
    now = mock_payloads(ev)
    for p in now.values():
        p["generated_at"] = "2026-10-30T20:00:00+05:30"
    if os.environ.get("WRITE_EVENTS_FIXTURE"):
        CAPTURE.write_text(json.dumps({"about": ABOUT, "payloads": now}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not CAPTURE.exists():
        pytest.skip("the frontend fixtures are not in this checkout")
    doc = json.loads(CAPTURE.read_text(encoding="utf-8"))
    assert doc["about"].startswith("MOCK") and doc["payloads"] == now
