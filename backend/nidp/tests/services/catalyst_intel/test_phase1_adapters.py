"""Phase 1 sources (user priority 2026-09-16: NHAI + PIB + eProcure first, then FDA/SEC), on responses captured live
the same morning. Every adapter yields the raw-event dict the store already understands; nothing here classifies."""
from datetime import date, datetime
from pathlib import Path

FX = Path(__file__).parent / "fixtures"
RECV = datetime(2026, 9, 16, 9, 0)


def _run(adapter, fixture, **kw):
    from nidp.services.catalyst_intel import adapters

    return getattr(adapters, adapter)((FX / fixture).read_bytes(), received_at=RECV, **kw)


# ── PIB: ASP.NET postback per calendar day (the RSS is Hindi-only and now answers 0 bytes) ─────────────────────────────
def test_pib_form_state_and_postback_body_for_a_day():
    from nidp.services.catalyst_intel.adapters import pib_form_state, pib_postback_body

    st = pib_form_state((FX / "pib_allrel_form.html").read_bytes())
    assert len(st["__VIEWSTATE"]) > 1000 and st["__EVENTVALIDATION"] and st["__VIEWSTATEGENERATOR"] == "CBED066B"
    body = pib_postback_body(st, date(2026, 9, 15)).decode()
    for must in ("__EVENTTARGET=ctl00%24ContentPlaceHolder1%24ddlday", "ddlday=15", "ddlMonth=9", "ddlYear=2026", "ddlLang=1", "ddlregion=3", "ddlMinistry=0", "hydLangid=1"):
        assert must in body, must


def test_pib_day_listing_yields_one_event_per_release_grouped_by_ministry():
    ev = _run("parse_pib_day", "pib_allrel_2026-09-15.html", source_id="pib", day=date(2026, 9, 15))
    assert len(ev) == 48
    e = ev[0]
    assert e["url"] == "https://www.pib.gov.in/PressReleaseDetail.aspx?PRID=2310671" and e["source_event_id"] == "2310671"
    assert e["title"].startswith("RSS’s Century of Service") and e["category"] == "Vice President's Secretariat"
    assert e["published_at"].date() == date(2026, 9, 15) and e["published_at"].tzinfo is not None and e["summary"].startswith("PIB Delhi")
    assert "day" in e["summary"]                                                     # listing has day precision only; the detail page carries the time
    assert len({e["category"] for e in ev}) >= 10 and all(len(e["hash"]) == 64 for e in ev)
    assert len({e["source_event_id"] for e in ev}) == 48                            # one event per PRID


def test_pib_form_page_with_no_releases_yields_nothing_and_does_not_crash():
    assert _run("parse_pib_day", "pib_allrel_form.html", source_id="pib", day=date(2026, 9, 16)) == []


# ── NHAI: the Angular app's own FormData API at nhai.gov.in/nhai/api (found in main.b6072fa2…js) ─────────────────────
def test_nhai_news_press_release_and_tenders_become_events_with_pdf_links_and_dates():
    news = _run("parse_nhai_api", "nhai_news.json", source_id="nhai_news")
    assert len(news) == 4 and news[0]["category"] == "news" and news[0]["source_event_id"] == "58751"
    assert news[0]["published_at"].date() == date(2026, 9, 15) and news[0]["url"].endswith("The_Indian_Express_Delhi_15-9-2026.pdf")
    assert "The Indian Express" in news[0]["summary"] and news[0]["title"].startswith("Real-time location")
    pr = _run("parse_nhai_api", "nhai_press_release.json", source_id="nhai_press_release")
    assert len(pr) == 30 and pr[0]["category"] == "press_release" and pr[0]["url"].startswith("https://nhai.gov.in/nhai/sites/default/files/") and pr[0]["published_at"]
    assert pr[0]["title"].startswith("NHAI Tightens Compliance Norms")
    td = _run("parse_nhai_api", "nhai_tenderlist.json", source_id="nhai_tenders")
    assert len(td) == 10 and td[0]["category"] == "tender" and td[0]["entity_text"] == "NHAI/RO/CHD/2026-2027/ASR/26"
    assert td[0]["published_at"].isoformat() == "2026-09-14T05:30:00+05:30" and "bid closes 2026-10-13" in td[0]["summary"]
    assert td[0]["title"].startswith("Consultancy Services for Supervision Consultant")


def test_nhai_multipart_body_matches_the_apps_form_fields():
    from nidp.services.catalyst_intel.transports import multipart

    body, ctype = multipart({"language": "en", "index": "0", "totalrecord": "50"})
    assert ctype.startswith("multipart/form-data; boundary=") and b'name="totalrecord"\r\n\r\n50\r\n' in body and body.endswith(b"--\r\n")


# ── eProcure / CPPP: the Drupal listing tables (awards need a captcha search → browser job) ───────────────────────────
def test_cppp_tender_rows_become_events_with_organisation_and_bid_dates():
    ev = _run("parse_cppp_table", "cppp_latest_tenders.html", source_id="cppp_tenders", base_url="https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata")
    assert len(ev) == 10
    e = ev[0]
    assert e["published_at"].isoformat() == "2026-09-15T21:10:00+05:30" and e["category"] == "tender"
    assert e["entity_text"] == "Central Public Works Department (CPWD)" and e["title"] == "75/CE/EE/C-I/CPWD/DEHRADUN/2026-27"
    assert e["url"].startswith("https://eprocure.gov.in/cppp/tendersfullview/") and "bid closes 2026-09-23" in e["summary"] and e["source_event_id"]
    assert len({x["url"] for x in ev}) == 10


def test_cppp_corrigendum_rows_carry_the_tender_title_and_the_corrigendum_link():
    ev = _run("parse_cppp_table", "cppp_corrigendums.html", source_id="cppp_corrigendums", base_url="https://eprocure.gov.in/cppp/latestactivecorrigendumsnew/cpppdata")
    assert len(ev) == 10 and ev[0]["category"] == "corrigendum"
    assert ev[2]["entity_text"] == "National Highways Authority of India" and ev[2]["title"].startswith("Development of High-Speed Access Controlled Greenfield Corridor")
    assert ev[0]["url"].startswith("https://eprocure.gov.in/cppp/corrigfullview/")


def test_cppp_captcha_search_page_yields_no_rows():
    assert _run("parse_cppp_table", "cppp_results_captcha.html", source_id="cppp_awards", base_url="https://eprocure.gov.in/cppp/resultoftendersnew/cpppdata") == []


def test_cppp_page_url_for_page_n_is_the_base64_url_parameter():
    from nidp.services.catalyst_intel.adapters import cppp_page_url

    assert cppp_page_url("https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata", 1) == "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata"
    u = cppp_page_url("https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata", 2)
    assert u == "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata?url=aHR0cHM6Ly9lcHJvY3VyZS5nb3YuaW4vY3BwcC9sYXRlc3RhY3RpdmV0ZW5kZXJzbmV3L2NwcHBkYXRhP3BhZ2U9Mg%3D%3D"


# ── SEC EDGAR: the current-filings Atom feed (structured, no scraping) ────────────────────────────────────────────────
def test_sec_atom_entries_become_events_with_issuer_form_and_accession():
    ev = _run("parse_sec_atom", "sec_6k.atom", source_id="sec_edgar_6k")
    assert len(ev) == 100
    e = ev[0]
    assert e["entity_text"] == "LIBERTY DEFENSE HOLDINGS, LTD." and e["category"] == "6-K" and e["source_event_id"] == "0001104659-26-107976"
    assert e["published_at"].isoformat() == "2026-09-15T17:15:22-04:00" and e["url"].startswith("https://www.sec.gov/Archives/edgar/data/1919776/")
    assert e["title"] == "6-K: LIBERTY DEFENSE HOLDINGS, LTD." and e["summary"] and "0001919776" in e["summary"]


# ── openFDA: enforcement (recalls) API ───────────────────────────────────────────────────────────────────────────────
def test_openfda_enforcement_results_become_events_keyed_by_recall_number():
    ev = _run("parse_openfda_enforcement", "openfda_drug_enforcement.json", source_id="openfda_drug_enforcement")
    assert len(ev) == 5
    e = ev[0]
    assert e["entity_text"] == "Shilpa Medicare Limited" and e["category"] == "Class II" and e["published_at"].date() == date(2026, 8, 26)
    assert e["title"].startswith("Class II recall: Shilpa Medicare Limited") and e["source_event_id"].startswith("D-") and "Discolored solution" in e["summary"]
    assert e["url"].startswith("https://api.fda.gov/drug/enforcement.json?search=recall_number:")
    assert len({x["hash"] for x in ev}) == 5                                       # two Shilpa rows are different recall numbers


def test_fda_recalls_rss_goes_through_the_generic_rss_adapter():
    ev = _run("parse_rss", "fda_recalls.xml", source_id="fda_recalls_rss")
    assert len(ev) == 20 and ev[0]["published_at"] is not None and ev[0]["title"].startswith("Whole Foods Market")


def test_new_date_formats():
    from nidp.services.catalyst_intel.adapters import parse_feed_datetime

    assert parse_feed_datetime("15-Sep-2026 09:10 PM").isoformat() == "2026-09-15T21:10:00+05:30"     # CPPP
    assert parse_feed_datetime("2026-09-14 05:30:00").isoformat() == "2026-09-14T05:30:00+05:30"      # NHAI
    assert parse_feed_datetime("20260826").date() == date(2026, 8, 26)                                # openFDA
    assert parse_feed_datetime("Fri, 11 Sep 2026 18:15:00 EDT").isoformat() == "2026-09-11T18:15:00-04:00"   # FDA RSS
