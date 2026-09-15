"""CIE Phase 2/3 without an LLM: a deterministic rules engine, an entity map with sourced relationships, document text for
filings whose exchange summary says nothing, and the nine-question explanation. Tests before implementation; the three
benchmark events of 15 September 2026 are the acceptance cases."""
from datetime import datetime
from pathlib import Path

import pytest

from nidp.tests.services.tpd_model.conftest import ist

FX = Path(__file__).parent / "fixtures"


def _ev(source_id, title, summary=None, category=None, symbol=None, scrip_code=None, entity_text=None, published=None, url="https://x/y.pdf", doc_text=None):
    return {"source_id": source_id, "title": title, "summary": summary, "category": category, "symbol": symbol, "scrip_code": scrip_code, "entity_text": entity_text,
            "published_at": published or ist(datetime(2026, 9, 14).date(), 21, 2), "first_seen_at": ist(datetime(2026, 9, 14).date(), 21, 15), "url": url, "hash": "h" + title[:20], "doc_text": doc_text}


# ── rules engine ────────────────────────────────────────────────────────────────────────────────────────────────
def test_rules_classify_the_pnc_debarment_as_a_negative_regulatory_event():
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("nse_announcements_api", "PNCINFRA: Action(s) taken or orders passed", "PNC Infratech Limited has informed the Exchange about Action(s) taken or orders passed",
            category="Action(s) taken or orders passed", symbol="PNCINFRA",
            doc_text="received a letter from NHAI on 11.09.2026, extending the debarment of Awadh Expressway Private Limited for a period of three years, to the Company being Promoter. "
                     "Company will not be able to participate in any bid of MoRTH/NHAI for a period of three years.")
    c = classify(e)
    assert c["event_type"] == "regulatory_decision" and c["event_subtype"] == "debarment" and c["direction"] == "negative"
    assert c["materiality"] >= 80 and "debarment" in c["matched_terms"] and c["classifier"] == "rules-v1" and c["raw_language"] == "en"
    assert "NHAI" in c["named_authorities"]


def test_rules_classify_the_emudhra_release_as_a_positive_institution_event():
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("nse_announcements_api", "EMUDHRA: Press Release", 'eMudhra Limited has informed the Exchange regarding a press release titled "GLEIF Welcomes eMudhra as a Validation Agent, Expanding LEI Access"',
            category="Press Release", symbol="EMUDHRA")
    c = classify(e)
    assert c["event_type"] == "institution" and c["event_subtype"] == "appointment" and c["direction"] == "positive" and 40 <= c["materiality"] <= 70
    assert "GLEIF" in c["named_authorities"]


def test_rules_classify_rbi_rejection_and_approval_and_pharma_terms():
    from nidp.services.catalyst_intel.rules import classify

    r = classify(_ev("bs_companies", "RBI files caveat after rejecting Tata Sons bid to avoid market listing", "The move follows the RBI's rejection of Tata Sons' application to deregister"))
    assert r["event_type"] == "regulatory_decision" and r["event_subtype"] == "rejection" and r["direction"] == "negative" and "RBI" in r["named_authorities"]
    a = classify(_ev("rbi_press", "RBI grants in-principle approval to XYZ Finance for a payment aggregator licence"))
    assert a["event_subtype"] == "approval" and a["direction"] == "positive"
    w = classify(_ev("et_stocks", "Lupin gets USFDA warning letter for Pithampur plant"))
    assert w["event_type"] == "operations" and w["event_subtype"] == "warning_letter" and w["direction"] == "negative" and w["materiality"] >= 60
    o = classify(_ev("nse_announcements_api", "HGINFRA: Updates", "H.G. Infra Engineering has received Letter of Award from NHAI for a project worth Rs 1,250 crore", category="Updates", symbol="HGINFRA"))
    assert o["event_type"] == "order_win" and o["direction"] == "positive" and o["quantities"].get("order_value_cr") == 1250.0
    t = classify(_ev("nse_announcements_api", "ACME: Trading Window", "Closure of trading window", category="Trading Window", symbol="ACME"))
    assert t["event_type"] == "routine" and t["materiality"] <= 10


def test_rules_keep_hindi_items_and_tag_the_language():
    from nidp.services.catalyst_intel.rules import classify

    h = classify(_ev("mnre", "सौर ऊर्जा योजना के लिए निविदा आमंत्रित", published=ist(datetime(2026, 9, 10).date(), 12, 0)))
    assert h["raw_language"] == "hi" and h["event_type"] in ("order_win", "regulatory_policy", "unclassified") and h["classifier"] == "rules-v1"


# ── entity map ──────────────────────────────────────────────────────────────────────────────────────────────────
def _entities():
    from nidp.services.catalyst_intel.entities import EntityMap

    names = "symbol,isin,company_name,sector,industry\nTATACHEM,INE092A01019,Tata Chemicals Limited,Chemicals,Chemicals\nTATAINVEST,INE672A01026,Tata Investment Corporation Limited,Finance,Financial Services\nEMUDHRA,INE01QM01018,eMudhra Limited,,\nPNCINFRA,INE195J01029,PNC Infratech Limited,Construction,Construction\nHGINFRA,INE926X01010,H.G. Infra Engineering Limited,Construction,Construction\n"
    return EntityMap.from_csv_text(names, seed_path=FX.parent.parent.parent.parent / "services" / "catalyst_intel" / "seed_relationships.csv")


def test_entity_map_resolves_symbol_scrip_and_aliases():
    m = _entities()
    assert m.resolve_symbol("PNCINFRA")["entity_name"] == "PNC Infratech Limited"
    hits = m.find_in_text("The move follows the RBI's rejection of Tata Sons' application; Tata Chemicals and TATAINVEST rallied")
    names = {h["entity_name"] for h in hits}
    assert {"Tata Sons", "Tata Chemicals Limited", "Reserve Bank of India"} <= names and "Tata Investment Corporation Limited" in names
    assert m.find_in_text("nothing here") == []


def test_seed_relationships_are_sourced_and_propagate_with_exposure():
    m = _entities()
    imp = m.propagate("Tata Sons", direction="positive", materiality=90)
    by = {i["symbol"]: i for i in imp}
    assert "TATACHEM" in by and by["TATACHEM"]["hops"] == 1 and by["TATACHEM"]["exposure"] == pytest.approx(0.0253) and by["TATACHEM"]["source_url"].startswith("http")
    assert "TATAINVEST" in by and by["TATAINVEST"]["exposure"] is None                       # stake not sourced -> unknown, never guessed
    assert "Tata Sons" in by["TATACHEM"]["path"] and "INVESTEE" in by["TATACHEM"]["path"]
    direct = m.propagate("PNC Infratech Limited", direction="negative", materiality=90)
    assert direct[0]["symbol"] == "PNCINFRA" and direct[0]["hops"] == 0 and direct[0]["exposure"] == 1.0
    assert m.regulator_sectors("National Highways Authority of India") and "Construction" in m.regulator_sectors("National Highways Authority of India")


# ── documents ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_filings_with_an_empty_summary_need_their_document():
    from nidp.services.catalyst_intel.documents import needs_document

    assert needs_document(_ev("nse_announcements_api", "PNCINFRA: Action(s) taken or orders passed", "PNC Infratech Limited has informed the Exchange about Action(s) taken or orders passed", category="Action(s) taken or orders passed"))
    assert needs_document(_ev("bse_subcat_api", "PNC Infratech Ltd - 539150 - Intimation", "as per attachment", category="Company Update"))
    assert not needs_document(_ev("nse_announcements_api", "ACME: Trading Window", "Closure of trading window", category="Trading Window"))
    assert not needs_document(_ev("bs_companies", "RBI files caveat", "long summary " * 20))


def test_document_text_is_cached_by_hash_and_size_capped(tmp_path):
    from nidp.services.catalyst_intel.documents import DocumentCache

    calls = []
    def fake_fetch(url): calls.append(url); return b"%PDF-fake"
    def fake_extract(pdf_bytes): return "NHAI debarment text " * 5000
    dc = DocumentCache(tmp_path, fetch=fake_fetch, extract=fake_extract, max_chars=20_000)
    t1 = dc.text("h1", "https://x/a.pdf"); t2 = dc.text("h1", "https://x/a.pdf")
    assert t1 == t2 and len(calls) == 1 and len(t1) == 20_000 and (tmp_path / "h1.txt").exists()


# ── the nine questions ──────────────────────────────────────────────────────────────────────────────────────────
def test_explanation_answers_the_nine_questions_for_pnc():
    from nidp.services.catalyst_intel.catalysts import build_impacts, explain
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("nse_announcements_api", "PNCINFRA: Action(s) taken or orders passed", "PNC Infratech Limited has informed the Exchange about Action(s) taken or orders passed",
            category="Action(s) taken or orders passed", symbol="PNCINFRA", entity_text="PNC Infratech Limited",
            doc_text="received a letter from NHAI on 11.09.2026, extending the debarment of Awadh Expressway Private Limited for three years to the Company being Promoter; not able to participate in any bid of MoRTH/NHAI for three years.")
    c = classify(e); imp = build_impacts(e, c, _entities())
    x = explain(e, c, imp, symbol="PNCINFRA")
    for k in ("when_first_available", "where_found", "what_happened", "which_entity", "which_stocks", "why", "direction", "materiality", "confidence"):
        assert x[k] not in (None, "", []), k
    assert x["direction"] == "negative" and x["which_stocks"][0]["symbol"] == "PNCINFRA" and "NHAI" in x["why"]
    assert x["when_first_available"] == "2026-09-14T21:15:00+05:30" and x["where_found"].startswith("nse_announcements_api")


# ── the board: which stocks are exposed to the events known by a cutoff ──────────────────────────────────────────
def test_board_lists_exposed_stocks_by_score_with_the_top_event_and_hides_routine(tmp_path):
    import sqlite3
    from nidp.services.catalyst_intel.catalysts import DDL, board

    db = sqlite3.connect(tmp_path / "events.sqlite"); db.executescript("""
    CREATE TABLE raw_events (hash TEXT PRIMARY KEY, source_id TEXT, source_event_id TEXT, url TEXT, title TEXT, summary TEXT, category TEXT, symbol TEXT, scrip_code TEXT, entity_text TEXT, published_at TEXT, received_at TEXT, first_seen_at TEXT, day TEXT);
    """); db.executescript(DDL)
    rows = [("h_pnc", "nse_announcements_api", "https://x/pnc.pdf", "PNCINFRA: Action(s) taken or orders passed", "PNCINFRA", "2026-09-14T21:02:44+05:30", "2026-09-14T21:15:00+05:30"),
            ("h_emu", "nse_announcements_api", "https://x/emu.pdf", "EMUDHRA: Press Release", "EMUDHRA", "2026-09-13T19:14:31+05:30", "2026-09-13T19:29:00+05:30"),
            ("h_news", "bs_companies", "https://x/n", "RBI files caveat after rejecting Tata Sons bid", None, "2026-09-15T13:49:37+05:30", "2026-09-15T14:00:00+05:30"),
            ("h_tw", "nse_announcements_api", "https://x/tw.pdf", "ACME: Trading Window", "ACME", "2026-09-14T18:00:00+05:30", "2026-09-14T18:15:00+05:30")]
    for h, s, u, t, sym, pub, seen in rows:
        db.execute("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (h, s, None, u, t, None, None, sym, None, None, pub, seen, seen, seen[:10]))
    norm = [("h_pnc", "regulatory_decision", "debarment", "negative", 95), ("h_emu", "institution", "appointment", "positive", 60), ("h_news", "regulatory_decision", "rejection", "positive", 85), ("h_tw", "routine", "routine", "neutral", 5)]
    for h, t, st, d, m in norm:
        db.execute("INSERT INTO normalized_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (h, t, st, d, m, 0.8, "[]", "[]", "{}", "en", "rules-v1", "2026-09-15T23:00:00+05:30", 1))
    imps = [("h_pnc", "PNCINFRA", 0, 1.0, "PNC Infratech Limited", None, "negative", 95, "2026-09-14T21:15:00+05:30"),
            ("h_emu", "EMUDHRA", 0, 1.0, "eMudhra Limited", None, "positive", 60, "2026-09-13T19:29:00+05:30"),
            ("h_news", "TATACHEM", 1, 0.0253, "Tata Sons → (INVESTEE 2.53%) → Tata Chemicals Limited", "https://src", "positive", 41, "2026-09-15T14:00:00+05:30"),
            ("h_news", "TATAINVEST", 1, None, "Tata Sons → (INVESTEE) → Tata Investment Corporation Limited", "https://src", "positive", 25, "2026-09-15T14:00:00+05:30"),
            ("h_tw", "ACME", 0, 1.0, "ACME", None, "neutral", 3, "2026-09-14T18:15:00+05:30")]
    for i in imps:
        db.execute("INSERT INTO event_stock_impacts VALUES (?,?,?,?,?,?,?,?,?)", i)
    db.commit(); db.close()
    b = board(tmp_path, known_before="2026-09-15T09:15:00+05:30", since="2026-09-10", min_score=10, universe={"PNCINFRA", "EMUDHRA", "TATACHEM"})
    syms = [r["symbol"] for r in b]
    assert syms[:2] == ["PNCINFRA", "EMUDHRA"] and "ACME" not in syms and "TATACHEM" not in syms            # news landed after the cutoff; routine hidden
    assert b[0]["direction"] == "negative" and b[0]["top_event"]["title"].startswith("PNCINFRA") and b[0]["in_universe"] and b[0]["n_events"] == 1
    later = board(tmp_path, known_before="2026-09-15T20:30:00+05:30", since="2026-09-10", min_score=10, universe={"PNCINFRA", "EMUDHRA", "TATACHEM"})
    row = next(r for r in later if r["symbol"] == "TATACHEM")
    assert row["hops"] == 1 and "Tata Sons" in row["top_event"]["path"] and row["in_universe"]
    assert next(r for r in later if r["symbol"] == "TATAINVEST")["in_universe"] is False
