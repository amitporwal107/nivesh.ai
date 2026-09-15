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
    assert c["event_type"] == "REGULATORY" and c["event_subtype"] == "debarment" and c["direction"] == "negative"
    assert c["event_severity"] >= 80 and "debarment" in c["matched_terms"] and c["classifier"].startswith("rules") and c["raw_language"] == "en"
    assert "NHAI" in c["named_authorities"]


def test_rules_classify_the_emudhra_release_as_a_positive_institution_event():
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("nse_announcements_api", "EMUDHRA: Press Release", 'eMudhra Limited has informed the Exchange regarding a press release titled "GLEIF Welcomes eMudhra as a Validation Agent, Expanding LEI Access"',
            category="Press Release", symbol="EMUDHRA")
    c = classify(e)
    assert c["event_type"] == "INSTITUTION" and c["event_subtype"] == "appointment" and c["direction"] == "positive" and 40 <= c["event_severity"] <= 70
    assert "GLEIF" in c["named_authorities"]


def test_rules_classify_rbi_rejection_and_approval_and_pharma_terms():
    from nidp.services.catalyst_intel.rules import classify

    r = classify(_ev("bs_companies", "RBI files caveat after rejecting Tata Sons bid to avoid market listing", "The move follows the RBI's rejection of Tata Sons' application to deregister"))
    assert r["event_type"] == "REGULATORY" and r["event_subtype"] == "forced_listing" and r["direction"] == "positive" and "RBI" in r["named_authorities"]
    plain = classify(_ev("rbi_press", "RBI rejects XYZ Bank's application for a payment aggregator licence"))
    assert plain["event_subtype"] == "rejection" and plain["direction"] == "negative"
    a = classify(_ev("rbi_press", "RBI grants in-principle approval to XYZ Finance for a payment aggregator licence"))
    assert a["event_subtype"] in ("approval", "licence_granted") and a["direction"] == "positive"
    w = classify(_ev("et_stocks", "Lupin gets USFDA warning letter for Pithampur plant"))
    assert w["event_type"] == "PHARMA" and w["event_subtype"] == "fda_warning" and w["direction"] == "negative" and w["event_severity"] >= 60
    o = classify(_ev("nse_announcements_api", "HGINFRA: Updates", "H.G. Infra Engineering has received Letter of Award from NHAI for a project worth Rs 1,250 crore", category="Updates", symbol="HGINFRA"))
    assert o["event_type"] == "CONTRACT" and o["direction"] == "positive" and o["quantities"].get("order_value_cr") == 1250.0
    t = classify(_ev("nse_announcements_api", "ACME: Trading Window", "Closure of trading window", category="Trading Window", symbol="ACME"))
    assert t["event_type"] == "ROUTINE" and t["event_severity"] <= 10


def test_rules_keep_hindi_items_and_tag_the_language():
    from nidp.services.catalyst_intel.rules import classify

    h = classify(_ev("mnre", "सौर ऊर्जा योजना के लिए निविदा आमंत्रित", published=ist(datetime(2026, 9, 10).date(), 12, 0)))
    assert h["raw_language"] == "hi" and h["event_type"] in ("GOVERNMENT", "CONTRACT", "UNCLASSIFIED") and h["classifier"].startswith("rules")


# ── entity map ──────────────────────────────────────────────────────────────────────────────────────────────────
def _entities():
    from nidp.services.catalyst_intel.entities import EntityMap

    names = "symbol,isin,company_name,sector,industry\nTATACHEM,INE092A01019,Tata Chemicals Limited,Chemicals,Chemicals\nTATAINVEST,INE672A01026,Tata Investment Corporation Limited,Finance,Financial Services\nEMUDHRA,INE01QM01018,eMudhra Limited,,\nPNCINFRA,INE195J01029,PNC Infratech Limited,Construction,Construction\nHGINFRA,INE926X01010,H.G. Infra Engineering Limited,Construction,Construction\n"
    return EntityMap.from_csv_text(names, seed_path=FX.parent.parent.parent.parent / "services" / "catalyst_intel" / "seed_relationships.csv")


def test_entity_map_resolves_symbol_scrip_and_aliases():
    m = _entities()
    assert m.resolve_symbol("PNCINFRA")["entity_name"] == "PNC Infratech Limited"
    hits = m.find_in_text("The move follows the RBI's rejection of Tata Sons' application; Tata Chemicals and Tata Investment Corporation rallied; TATAINVEST too")
    names = {h["entity_name"] for h in hits}
    assert {"Tata Sons", "Tata Chemicals Limited", "Reserve Bank of India", "Tata Investment Corporation Limited"} <= names   # names resolve; bare symbols in prose do not
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
    from nidp.services.catalyst_intel.catalysts import attribute, explain
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("nse_announcements_api", "PNCINFRA: Action(s) taken or orders passed", "PNC Infratech Limited has informed the Exchange about Action(s) taken or orders passed",
            category="Action(s) taken or orders passed", symbol="PNCINFRA", entity_text="PNC Infratech Limited",
            doc_text="received a letter from NHAI on 11.09.2026, extending the debarment of Awadh Expressway Private Limited for three years to the Company being Promoter; not able to participate in any bid of MoRTH/NHAI for three years.")
    c = classify(e); imp = attribute(e, c, _entities())
    x = explain(e, c, imp, symbol="PNCINFRA")
    for k in ("when_first_available", "where_found", "what_happened", "which_entity", "which_stocks", "why", "direction", "materiality", "confidence"):
        assert x[k] not in (None, "", []), k
    assert x["direction"] == "negative" and x["which_stocks"][0]["symbol"] == "PNCINFRA" and "NHAI" in x["why"] and x["which_stocks"][0]["entity_match_type"] == "exact_nse_issuer"
    assert x["when_first_available"] == "2026-09-14T21:15:00+05:30" and x["where_found"].startswith("nse_announcements_api")


# ── the board: which stocks are exposed to the events known by a cutoff ──────────────────────────────────────────
def test_board_lists_exposed_stocks_by_score_with_the_top_event_and_hides_routine(tmp_path):
    import sqlite3
    from nidp.services.catalyst_intel.catalysts import DDL, ROW_COLUMNS, board, write_rows

    db = sqlite3.connect(tmp_path / "events.sqlite"); db.executescript("""
    CREATE TABLE raw_events (hash TEXT PRIMARY KEY, source_id TEXT, source_event_id TEXT, url TEXT, title TEXT, summary TEXT, category TEXT, symbol TEXT, scrip_code TEXT, entity_text TEXT, published_at TEXT, received_at TEXT, first_seen_at TEXT, day TEXT);
    """); db.executescript(DDL)
    def row(sym, ev, title, etype, sub, direction, sev, mtype, mscore, hops, exp, known, pub, path, src="nse_announcements_api"):
        return {"symbol": sym, "event_id": ev, "event_time": pub, "known_at": known, "source": src, "source_url": "https://x", "source_entity": "NHAI", "affected_entity": path.split(" →")[0], "listed_entity": sym,
                "entity_match_type": mtype, "entity_match_score": mscore, "hops": hops, "event_type": etype, "event_subtype": sub, "direction": direction, "event_severity": sev, "business_materiality": int(sev * exp / 100),
                "exposure_score": exp, "confidence": 0.8, "catalyst_score": int(sev * mscore / 100 * exp / 100 * 0.8 / 0.9), "title": title, "classification_method": "RULE", "path": path}
    write_rows(db, [row("PNCINFRA", "h_pnc", "PNCINFRA: Action(s) taken or orders passed", "REGULATORY", "debarment", "negative", 95, "exact_nse_issuer", 100, 0, 100, "2026-09-14T21:15:00+05:30", "2026-09-14T21:02:44+05:30", "PNC Infratech Limited"),
                   row("EMUDHRA", "h_emu", "EMUDHRA: Press Release", "INSTITUTION", "appointment", "positive", 60, "exact_nse_issuer", 100, 0, 100, "2026-09-13T19:29:00+05:30", "2026-09-13T19:14:31+05:30", "eMudhra Limited"),
                   row("TATACHEM", "h_news", "RBI files caveat after rejecting Tata Sons bid", "REGULATORY", "rejection", "positive", 85, "verified_investee", 90, 1, 37, "2026-09-15T14:00:00+05:30", "2026-09-15T13:49:37+05:30", "Tata Sons → (INVESTEE 2.53%) → Tata Chemicals Limited", "bs_companies"),
                   row("TATAINVEST", "h_news", "RBI files caveat after rejecting Tata Sons bid", "REGULATORY", "rejection", "positive", 85, "verified_investee", 90, 1, 50, "2026-09-15T14:00:00+05:30", "2026-09-15T13:49:37+05:30", "Tata Sons → (INVESTEE) → Tata Investment Corporation Limited", "bs_companies"),
                   row("ACME", "h_tw", "ACME: Trading Window", "ROUTINE", "routine", "neutral", 5, "exact_nse_issuer", 100, 0, 100, "2026-09-14T18:15:00+05:30", "2026-09-14T18:00:00+05:30", "ACME")])
    db.commit(); db.close()
    b = board(tmp_path, known_before="2026-09-15T09:15:00+05:30", since="2026-09-10", min_score=10, universe={"PNCINFRA", "EMUDHRA", "TATACHEM"})
    syms = [r["symbol"] for r in b]
    assert syms[:2] == ["PNCINFRA", "EMUDHRA"] and "ACME" not in syms and "TATACHEM" not in syms            # news landed after the cutoff; routine hidden
    assert b[0]["direction"] == "negative" and b[0]["title"].startswith("PNCINFRA") and b[0]["in_universe"] and b[0]["n_events"] == 1 and set(ROW_COLUMNS) <= set(b[0])
    later = board(tmp_path, known_before="2026-09-15T20:30:00+05:30", since="2026-09-10", min_score=10, universe={"PNCINFRA", "EMUDHRA", "TATACHEM"})
    row_ = next(r for r in later if r["symbol"] == "TATACHEM")
    assert row_["hops"] == 1 and "Tata Sons" in row_["path"] and row_["in_universe"] and row_["entity_match_type"] == "verified_investee"
    assert next(r for r in later if r["symbol"] == "TATAINVEST")["in_universe"] is False



# ── first live board showed two rule traps and one entity trap (2026-09-16 00:25) ────────────────────────────────
def test_negated_and_regulation_name_terms_do_not_fire():
    from nidp.services.catalyst_intel.rules import classify

    d = classify(_ev("nse_announcements_api", "NAUKRI: Change in Director(s)", "Info Edge has informed the Exchange about Change in Director(s)", category="Change in Director(s)", symbol="NAUKRI",
                     doc_text="Mr X is not debarred from holding the office of director by virtue of any SEBI order or any other such authority. Appointment of Mr X as Independent Director."))
    assert d["event_type"] == "CORPORATE" and d["event_subtype"] != "debarment" and d["event_severity"] < 50
    t = classify(_ev("bse_subcat_api", "Varroc Engineering Ltd - 541578 - Closure of Trading Window", "pursuant to SEBI (Prohibition of Insider Trading) Regulations, 2015 the trading window shall remain closed", category="Insider Trading / SAST"))
    assert t["event_type"] == "ROUTINE"
    g = classify(_ev("nse_announcements_api", "ABDL: Granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals", "Grant of licence", category="Granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals", symbol="ABDL",
                     doc_text="the Company has received the grant of licence from the Excise department in accordance with the Prohibition of Insider Trading code"))
    assert g["event_subtype"] in ("approval", "licence_granted") and g["direction"] == "positive"
    real = classify(_ev("nse_announcements_api", "SMCGLOBAL: Action(s) initiated or orders passed", "informed the Exchange", category="Action(s) initiated or orders passed", symbol="SMCGLOBAL",
                        doc_text="SEBI has passed an order debarring the Company from the securities market for a period of two years"))
    assert real["event_subtype"] == "debarment" and real["direction"] == "negative" and real["event_type"] == "REGULATORY"


def test_free_text_aliases_are_never_symbols_or_common_words():
    from nidp.services.catalyst_intel.entities import EntityMap

    names = ("symbol,isin,company_name,sector,industry\nNH,INE410P01011,Narayana Hrudayalaya Limited,Healthcare,Healthcare\nTOTAL,INE0AJP01015,Total Transport Systems Limited,Services,Logistics\n"
             "BSE,INE118H01025,BSE Limited,Finance,Exchanges\nGLOBAL,INE0BDU01026,Global Education Limited,Services,Education\nFOCUS,INE0BXG01014,Focus Lighting And Fixtures Limited,Consumer Durables,Lighting\n"
             "TATACHEM,INE092A01019,Tata Chemicals Limited,Chemicals,Chemicals\nPNC,INE00PNC0001,PNC Limited,Construction,Construction\n")
    m = EntityMap.from_csv_text(names, seed_path=FX / "no_seed.csv")
    hits = {h["entity_name"] for h in m.find_in_text("Work on NH 24 near Total shares outstanding; BSE Limited has informed the Exchange; a global focus on Tata Chemicals and PNC Infratech")}
    assert hits == {"Tata Chemicals Limited"}
    assert {h["entity_name"] for h in m.find_in_text("Narayana Hrudayalaya reported results; Total Transport Systems won a contract")} == {"Narayana Hrudayalaya Limited", "Total Transport Systems Limited"}
    assert m.resolve_symbol("NH")["entity_name"] == "Narayana Hrudayalaya Limited"          # exact symbol fields still resolve


def test_explain_finds_an_old_filing_among_thousands_of_newer_events(tmp_path):
    import sqlite3
    from nidp.services.catalyst_intel.catalysts import DDL, explain_symbol

    names = tmp_path / "names.csv"; names.write_text("symbol,isin,company_name,sector,industry\nPNCINFRA,INE195J01029,PNC Infratech Limited,Construction,Construction\n")
    db = sqlite3.connect(tmp_path / "events.sqlite"); db.executescript("""
    CREATE TABLE raw_events (hash TEXT PRIMARY KEY, source_id TEXT, source_event_id TEXT, url TEXT, title TEXT, summary TEXT, category TEXT, symbol TEXT, scrip_code TEXT, entity_text TEXT, published_at TEXT, received_at TEXT, first_seen_at TEXT, day TEXT);"""); db.executescript(DDL)
    db.execute("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("h_pnc", "nse_announcements_api", None, "https://x/pnc.pdf", "PNCINFRA: Action(s) taken or orders passed", "informed the Exchange about Action(s) taken or orders passed",
               "Action(s) taken or orders passed", "PNCINFRA", None, "PNC Infratech Limited", "2026-09-14T21:02:44+05:30", "2026-09-14T21:15:00+05:30", "2026-09-14T21:15:00+05:30", "2026-09-14"))
    for k in range(3000):
        db.execute("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"h{k}", "bse_announcements_rss", None, "https://x/n", f"Other Co {k} - 500{k:03d} - Investor meet", "Investor meet", None, None, f"500{k:03d}", None, "2026-09-15T20:00:00+05:30", "2026-09-15T23:06:00+05:30", "2026-09-15T23:06:00+05:30", "2026-09-15"))
    db.execute("INSERT INTO event_stock_impacts VALUES (?,?,?,?,?,?,?,?,?)", ("h_pnc", "PNCINFRA", 0, 1.0, "PNC Infratech Limited", None, "negative", 95, "2026-09-14T21:15:00+05:30")); db.commit(); db.close()
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "h_pnc.txt").write_text("NHAI extended the debarment of Awadh Expressway to the Company for three years; not able to participate in any bid of MoRTH/NHAI")
    out = explain_symbol(tmp_path, names, "PNCINFRA", before="2026-09-15T09:15", docs=True)
    assert out and out[0]["explanation"]["direction"] == "negative" and out[0]["explanation"]["when_first_available"].startswith("2026-09-14T21:15")
