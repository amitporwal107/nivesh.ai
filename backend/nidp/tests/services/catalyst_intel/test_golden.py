"""The mandatory regression suite (user, 2026-09-16): TATACHEM, EMUDHRA and PNCINFRA reconstructed from the stored events,
plus the contamination cases the first live board exposed. Attribution rules under test: the issuer owns its filing
(hops 0, match 100); any other stock only through a verified relationship (hops >= 1); entity_match_score < 80 never
becomes a stock event; event severity is separate from exposure; the universe flag never influences attribution."""
import json
from datetime import datetime
from pathlib import Path

import pytest

FX = Path(__file__).parent / "fixtures"
GOLD = json.loads((FX / "golden_events.json").read_text())
ROW_KEYS = {"symbol", "event_id", "event_time", "known_at", "source", "source_url", "source_entity", "affected_entity", "listed_entity", "entity_match_type", "entity_match_score",
            "hops", "event_type", "event_subtype", "direction", "event_severity", "business_materiality", "exposure_score", "confidence", "catalyst_score", "title", "classification_method"}


def _em():
    from nidp.services.catalyst_intel.entities import EntityMap
    return EntityMap.from_files(Path("/app/research/tpd3_forward/exports/company_names.csv")) if Path("/app/research/tpd3_forward/exports/company_names.csv").exists() else EntityMap.from_csv_text(
        "symbol,isin,company_name,sector,industry\nPNCINFRA,INE195J01029,PNC Infratech Limited,Construction,Construction\nEMUDHRA,INE01QM01018,eMudhra Limited,,\n"
        "TATACHEM,INE092A01019,Tata Chemicals Limited,Chemicals,Chemicals\nTATAINVEST,INE672A01026,Tata Investment Corporation Limited,Finance,Financial Services\n"
        "NBCC,INE095N01031,NBCC (India) Limited,Construction,Construction\nNH,INE410P01011,Narayana Hrudayalaya Limited,Healthcare,Healthcare\nAFFLE,INE00WC01027,Affle 3i Limited,Information Technology,IT\n")


def _attribute(key):
    from nidp.services.catalyst_intel.catalysts import attribute
    from nidp.services.catalyst_intel.rules import classify
    e = dict(GOLD[key]); c = classify(e)
    return c, attribute(e, c, _em())


def test_golden_pncinfra_negative_regulatory_direct():
    c, rows = _attribute("PNCINFRA")
    assert c["event_type"] == "REGULATORY" and c["event_subtype"] in ("debarment", "bidding_restriction") and c["direction"] == "negative" and c["event_severity"] >= 85
    assert [r["symbol"] for r in rows] == ["PNCINFRA"], [r["symbol"] for r in rows]          # nothing else inherits a company's own filing
    r = rows[0]
    assert set(r) >= ROW_KEYS and r["hops"] == 0 and r["entity_match_type"] == "exact_nse_issuer" and r["entity_match_score"] == 100
    assert r["source_entity"] == "National Highways Authority of India" and r["affected_entity"] == "PNC Infratech Limited" and r["listed_entity"] == "PNC Infratech Limited"
    assert r["exposure_score"] == 100 and r["catalyst_score"] >= 80 and r["classification_method"] == "RULE" and r["known_at"] == GOLD["PNCINFRA"]["first_seen_at"]


def test_golden_emudhra_positive_institution_direct():
    c, rows = _attribute("EMUDHRA")
    assert c["event_type"] == "INSTITUTION" and c["direction"] == "positive" and 40 <= c["event_severity"] <= 75
    assert [r["symbol"] for r in rows] == ["EMUDHRA"] and rows[0]["hops"] == 0 and rows[0]["source_entity"] == "Global Legal Entity Identifier Foundation"
    c2, rows2 = _attribute("GLEIF_PRESS")                                                     # the institution's own release names eMudhra in the title
    assert [r["symbol"] for r in rows2] == ["EMUDHRA"] and rows2[0]["entity_match_type"] == "named_in_title" and rows2[0]["entity_match_score"] >= 90


def test_golden_tatachem_positive_through_a_sourced_stake():
    c, rows = _attribute("TATASONS_NEWS_BS")
    assert c["event_type"] == "REGULATORY" and c["event_subtype"] in ("forced_listing", "rejection")
    by = {r["symbol"]: r for r in rows}
    assert "TATACHEM" in by and by["TATACHEM"]["hops"] == 1 and by["TATACHEM"]["entity_match_type"] == "verified_investee" and by["TATACHEM"]["entity_match_score"] >= 85
    assert by["TATACHEM"]["source_entity"] == "Reserve Bank of India" and by["TATACHEM"]["affected_entity"] == "Tata Sons" and by["TATACHEM"]["listed_entity"] == "Tata Chemicals Limited"
    assert by["TATACHEM"]["direction"] == "positive" and by["TATACHEM"]["exposure_score"] < 100 and by["TATACHEM"]["classification_method"] == "RULE"
    assert "TATAINVEST" in by and by["TATAINVEST"]["hops"] == 1
    assert by["TATACHEM"]["catalyst_score"] < c["event_severity"]                            # a 2.53% stake is not the event itself


def test_a_director_change_is_corporate_and_touches_only_the_issuer():
    from nidp.services.catalyst_intel.catalysts import attribute
    from nidp.services.catalyst_intel.rules import classify
    e = {"source_id": "nse_announcements_api", "hash": "h_naukri", "url": "https://x/naukri.pdf", "title": "NAUKRI: Change in Director(s)", "summary": "Info Edge (India) Limited has informed the Exchange about Change in Director(s)",
         "category": "Change in Director(s)", "symbol": "NAUKRI", "scrip_code": None, "entity_text": "Info Edge (India) Limited", "published_at": "2026-09-15T18:00:00+05:30", "first_seen_at": "2026-09-15T18:15:00+05:30",
         "doc_text": "Appointment of Mr X as Independent Director. Mr X is not debarred from holding the office of director by virtue of any SEBI order. Mr X also serves on the boards of Affle 3i Limited and NBCC (India) Limited. Narayana Hrudayalaya Limited is a customer."}
    c = classify(e); rows = attribute(e, c, _em())
    assert c["event_type"] == "CORPORATE" and c["event_subtype"] == "director_change" and c["event_severity"] <= 30
    assert [r["symbol"] for r in rows] == ["NAUKRI"]                                          # names inside the document never attribute; no graph edge, no row


def test_gate_and_severity_separation():
    from nidp.services.catalyst_intel.catalysts import catalyst_score, gate
    assert gate("exact_nse_issuer") == 100 and gate("verified_subsidiary") == 95 and gate("verified_investee") == 90 and gate("named_in_title") == 90
    assert gate("supplier_customer") == 60 and gate("sector_inference") == 30 and gate("keyword_similarity") == 0
    assert catalyst_score(event_severity=95, entity_match_score=100, exposure_score=100, confidence=0.9) >= 80
    assert catalyst_score(event_severity=95, entity_match_score=90, exposure_score=20, confidence=0.9) < 50
    assert catalyst_score(event_severity=95, entity_match_score=60, exposure_score=100, confidence=0.9) == 0   # below the gate: no event at all


def test_taxonomy_is_strict():
    from nidp.services.catalyst_intel.rules import TAXONOMY, classify
    assert set(TAXONOMY) >= {"CORPORATE", "REGULATORY", "CONTRACT", "FINANCIAL", "M&A", "GOVERNMENT", "PHARMA", "RESULTS", "CAPITAL", "INSTITUTION", "ROUTINE", "UNCLASSIFIED"}
    assert "director_change" in TAXONOMY["CORPORATE"] and "debarment" in TAXONOMY["REGULATORY"] and "fda_warning" in TAXONOMY["PHARMA"] and "loa" in TAXONOMY["CONTRACT"]
    for text, want in (("Lupin gets USFDA warning letter for Pithampur plant", ("PHARMA", "fda_warning")), ("H.G. Infra receives Letter of Award from NHAI for Rs 1,250 crore project", ("CONTRACT", "loa")),
                       ("ICRA downgrades XYZ to BBB-", ("FINANCIAL", "rating_downgrade")), ("CCI approves acquisition of ABC by DEF", ("M&A", "cci_approval")),
                       ("Ministry invites tenders for 500 MW solar", ("GOVERNMENT", "tender")), ("Closure of trading window", ("ROUTINE", "routine"))):
        c = classify({"source_id": "et_stocks", "title": text, "summary": None, "category": None, "symbol": None, "doc_text": None, "published_at": "2026-09-15T10:00:00+05:30", "first_seen_at": "2026-09-15T10:00:00+05:30"})
        assert (c["event_type"], c["event_subtype"]) == want, (text, c["event_type"], c["event_subtype"])
        assert c["event_subtype"] in TAXONOMY[c["event_type"]]


# ── the second live board (2026-09-16 00:55): boilerplate deep in documents drove REGULATORY/FINANCIAL readings ──
def _filing(symbol, category, summary, doc_text, source_id="nse_announcements_api"):
    return {"source_id": source_id, "hash": "h_" + symbol, "url": "https://x/a.pdf", "title": f"{symbol}: {category}", "summary": summary, "category": category, "symbol": symbol,
            "scrip_code": None, "entity_text": None, "published_at": "2026-09-15T18:00:00+05:30", "first_seen_at": "2026-09-15T18:15:00+05:30", "doc_text": doc_text}


@pytest.mark.parametrize("symbol,category,summary,doc,want_group,max_sev", [
    ("VENUSPIPES", "Change in Management", "informed the Exchange about Change in Management", "Re-appointment of seven directors following the AGM. Mahendrakumar Patel (DIN 02617107) is not debarred from holding the office of director by virtue of any SEBI order.", "CORPORATE", 35),
    ("PIRAMALFIN", "Credit Rating", "informed the Exchange about Credit Rating", "CRISIL reaffirms AA rating. ... ANY ESTIMATED FINANCIAL LOSS IN THE EVENT OF DEFAULT OR IMPAIRMENT. SEE APPLICABLE MOODY'S RATING SYMBOLS AND DEFINITIONS.", "FINANCIAL", 45),
    ("UNIMECH", "Credit Rating", "informed the Exchange about Credit Rating", "CARE assigns CARE A+; Stable. Reproduction in whole or in part is prohibited except with prior express written consent from CARE Ratings Limited.", "FINANCIAL", 60),
    ("RBLBANK", "Credit Rating", "informed the Exchange about Credit Rating", "Moody's upgrades RBL Bank's deposit rating. Leverage, measured as debt to tangible net worth, declined to about 3.1x from 9.8x.", "FINANCIAL", 60),
    ("UTKARSHBNK", "Company Update", "as per attachment", "Approval of issuance of NCDs. Details of any delay in payment of interest / principal amount for a period of more than three months from the due date or default in payment of interest / principal: None", "CAPITAL", 45),
    ("MUTHOOTMF", "Others", "Asset Liability Management", "Statement of structural liquidity. (g) Credit Default Swaps Y1220 0.00 0.00 nil", "ROUTINE", 15),
    ("BAYERCROP", "AGM/EGM", "Postal Ballot Notice", "Postal Ballot Notice dated August 05, 2026, seeking approval of the members of the Company by way of remote e-Voting for the appointment of a director", "ROUTINE", 15),
    ("TBZ", "General Updates", "informed the Exchange about General Updates", "Letter of Offer for the open offer. Last date of communicating the rejection/ acceptance and completion of payment of consideration: Monday, 23 November 2026", "M&A", 60),
    ("RAILTEL", "Company Update", "Profile of the Statutory Auditor", "The firm provides Internal Audit, valuation of Assets, Liquidation and other Company matters, NCLT, ITAT, Arbitration. The firm has 4 locations.", "CORPORATE", 30),
])
def test_boilerplate_deep_in_a_document_never_escalates(symbol, category, summary, doc, want_group, max_sev):
    from nidp.services.catalyst_intel.rules import classify
    c = classify(_filing(symbol, category, summary, doc, source_id="bse_subcat_api" if category in ("Company Update", "Others", "AGM/EGM") else "nse_announcements_api"))
    assert c["event_type"] == want_group, (symbol, c["event_type"], c["event_subtype"], c["matched_terms"])
    assert c["event_severity"] <= max_sev, (symbol, c["event_severity"], c["matched_terms"])


def test_a_real_default_and_a_real_debarment_still_read_from_the_subject_line():
    from nidp.services.catalyst_intel.rules import classify
    d = classify(_filing("MTNL", "General Updates", "MTNL has informed the Exchange regarding default in payment of interest on its bonds due on September 10, 2026", "Sub: Default in payment of interest on 7.59% MTNL bonds. The Company has defaulted on the interest payment due on 10.09.2026."))
    assert d["event_type"] == "FINANCIAL" and d["event_subtype"] == "default" and d["event_severity"] >= 80
    p = classify(_filing("PNCINFRA", "Action(s) taken or orders passed", "informed the Exchange about Action(s) taken or orders passed", "Sub: Intimation under Regulation 30. NHAI letter dated 11.09.2026 extending the debarment of Awadh Expressway to the Company; not able to participate in any bid of MoRTH/NHAI for three years."))
    assert p["event_type"] == "REGULATORY" and p["event_subtype"] == "debarment" and p["event_severity"] >= 85 and "NHAI" in p["named_authorities"][:1]
