"""Catalyst Intelligence Engine — source layer (Phase 1). Tests written before the implementation, on responses captured
from the live sources on 2026-09-15. Every raw event carries where it came from, when the source says it was published
and when we received it; nothing is classified here."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

FX = Path(__file__).parent / "fixtures"


def test_registry_lists_the_user_priority_sources_with_a_status_each():
    from nidp.services.catalyst_intel.registry import SOURCES, by_status

    ids = {s.id for s in SOURCES}
    for must in ("nse_announcements_api", "nse_announcements_rss", "bse_announcements_rss", "bse_subcat_api", "rbi_press", "rbi_notifications",
                 "sebi_rss", "cci_combination_press", "cci_combination_orders", "cci_antitrust_orders", "mod", "cdsco_alerts", "gleif_press",
                 "ibbi", "nclt", "mnre", "heavy_industries", "icra", "pib", "nhai", "eprocure", "fda_warning_letters", "fda_import_alerts",
                 "dgft", "mca", "reuters", "et_stocks", "bs_companies", "mint_companies", "cnbc_market"):
        assert must in ids, must
    for s in SOURCES:
        assert s.priority in ("P0", "P1", "P2", "P3") and s.status in ("live", "listing", "blocked", "js_rendered", "not_built") and s.klass
        assert s.status != "live" or s.adapter, s.id
    assert by_status("blocked") and by_status("live")


def _events(adapter, fixture, **kw):
    from nidp.services.catalyst_intel import adapters

    fn = getattr(adapters, adapter)
    return fn((FX / fixture).read_bytes(), received_at=datetime(2026, 9, 15, 23, 0), **kw)


def test_rss_adapter_reads_rbi_sebi_nse_bse_and_news_feeds():
    for fixture, src, expect_symbol in (("rbi_press.xml", "rbi_press", False), ("rbi_notifications.xml", "rbi_notifications", False), ("sebi.xml", "sebi_rss", False),
                                        ("nse_announcements.xml", "nse_announcements_rss", False), ("nse_board_meetings.xml", "nse_board_meetings_rss", False),
                                        ("nse_corporate_actions.xml", "nse_corporate_actions_rss", False), ("bse_announcements.xml", "bse_announcements_rss", True),
                                        ("bs_companies.xml", "bs_companies", False), ("mint_companies.xml", "mint_companies", False), ("cnbc_market.xml", "cnbc_market", False), ("et_stocks.xml", "et_stocks", False)):
        ev = _events("parse_rss", fixture, source_id=src)
        assert len(ev) >= 5, fixture
        e = ev[0]
        assert e["source_id"] == src and e["title"] and e["url"].startswith("http") and e["published_at"] and e["received_at"]
        assert len(e["hash"]) == 64 and e["published_at"].tzinfo is not None
        if expect_symbol:
            assert e["scrip_code"] and e["entity_text"]                   # BSE carries the scrip code and company name


def test_rss_dates_are_parsed_in_each_feeds_own_format():
    from nidp.services.catalyst_intel.adapters import parse_feed_datetime

    assert parse_feed_datetime("Tue, 15 Sep 2026 19:05:00").isoformat() == "2026-09-15T19:05:00+05:30"     # RBI: naive IST
    assert parse_feed_datetime("14 Sep, 2026 +0530").date() == date(2026, 9, 14)                              # SEBI
    assert parse_feed_datetime("15-Sep-2026 22:43:41").isoformat() == "2026-09-15T22:43:41+05:30"            # NSE / BSE
    assert parse_feed_datetime("Tue, 15 Sep 2026 22:06:04 +0530").hour == 22                                 # news RFC-822
    assert parse_feed_datetime("garbage") is None


def test_nse_api_day_rows_become_events_with_symbol_and_attachment():
    ev = _events("parse_nse_api", "nse_api_2026-09-13.json", source_id="nse_announcements_api")
    assert len(ev) >= 20
    e = next(x for x in ev if x["symbol"] == "EMUDHRA")
    assert e["published_at"].isoformat().startswith("2026-09-13T19:14") and e["url"].endswith(".pdf") and "GLEIF" in (e["summary"] or "")
    assert e["category"] == "Press Release"


def test_bse_subcategory_rows_become_events():
    ev = _events("parse_bse_subcat", "bse_subcat_2026-09-15_p1.json", source_id="bse_subcat_api")
    assert len(ev) == 50 and all(x["scrip_code"] for x in ev) and ev[0]["published_at"].date() == date(2026, 9, 15)
    assert any(x["url"].endswith(".pdf") for x in ev) and all(x["entity_text"] for x in ev)


@pytest.mark.parametrize("fixture,source_id,min_items", [
    ("cci_comb_press.html", "cci_combination_press", 3), ("cci_comb_orders.html", "cci_combination_orders", 3), ("cci_antitrust.html", "cci_antitrust_orders", 5),
    ("mod.html", "mod", 5), ("cdsco_alerts.html", "cdsco_alerts", 5), ("gleif_press.html", "gleif_press", 5), ("ibbi.html", "ibbi", 5),
    ("nclt.html", "nclt", 5), ("mnre.html", "mnre", 5), ("heavyind.html", "heavy_industries", 5), ("icra.html", "icra", 3), ("sebi_press.html", "sebi_press", 3),
])
def test_html_listing_extractor_finds_dated_links(fixture, source_id, min_items):
    from nidp.services.catalyst_intel.registry import get_source

    ev = _events("parse_listing", fixture, source_id=source_id, base_url=get_source(source_id).url)
    assert len(ev) >= min_items, (fixture, len(ev))
    for e in ev[:3]:
        assert e["title"].strip() and e["url"].startswith("http") and e["published_at"] is not None


def test_store_dedupes_by_hash_and_keeps_first_seen(tmp_path):
    from nidp.services.catalyst_intel.store import EventStore

    st = EventStore(tmp_path)
    ev = _events("parse_rss", "rbi_press.xml", source_id="rbi_press")
    n1 = st.add(ev); n2 = st.add(ev)
    assert n1 == len(ev) and n2 == 0
    later = _events("parse_rss", "rbi_press.xml", source_id="rbi_press")
    for e in later: e["received_at"] = e["received_at"] + timedelta(hours=1)
    assert st.add(later) == 0
    rows = st.query(since=datetime(2026, 9, 1), source_id="rbi_press")
    assert len(rows) == len(ev) and rows[0]["first_seen_at"] <= rows[0]["received_at"]
    day_files = list((tmp_path / "raw").rglob("*.jsonl"))
    assert day_files and all("rbi_press" in p.name for p in day_files)   # one JSONL per calendar day per source


def test_rolling_window_covers_calendar_days_not_trading_days():
    from nidp.services.catalyst_intel.monitor import window_days

    days = window_days(date(2026, 9, 15), back=5)
    assert days == [date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 13), date(2026, 9, 14), date(2026, 9, 15)]   # Sat, Sun, holiday included


def test_run_manifest_isolates_a_failing_source(tmp_path):
    from nidp.services.catalyst_intel.monitor import run_sources
    from nidp.services.catalyst_intel.store import EventStore

    calls = []
    def ok(source, days, received_at): calls.append(source.id); return _events("parse_rss", "sebi.xml", source_id="sebi_rss")
    def boom(source, days, received_at): raise ConnectionError("timeout")
    from nidp.services.catalyst_intel.registry import get_source
    st = EventStore(tmp_path)
    m = run_sources([get_source("sebi_rss"), get_source("rbi_press")], st, {"sebi_rss": ok, "rbi_press": boom}, today=date(2026, 9, 15))
    assert m["sources"]["sebi_rss"]["new"] >= 5 and m["sources"]["rbi_press"]["error"].startswith("ConnectionError")
    assert m["ok"] == 1 and m["failed"] == 1 and (tmp_path / "runs").exists()
