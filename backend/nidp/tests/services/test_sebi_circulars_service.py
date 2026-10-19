"""services/sebi_circulars: page selection, fetch failure modes, the writer, and every place the feed is registered.

No network and no Postgres: aiohttp's session and the asyncpg pool are replaced by fakes (MOCK — not real data).
The parsers are tested against the real 2026-10-14 pages in tests/parsers/test_sebi_circulars_parser.py.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import re
import uuid
from datetime import date
from pathlib import Path

import pytest

from nidp.services.sebi_circulars import service as svc
from nidp.services.sebi_circulars import writer
from nidp.services.sebi_circulars.parser import parse_listing, parse_rss

REPO = Path(__file__).resolve().parents[4]


# ── which pages a run reads ───────────────────────────────────────────────────

def test_rss_is_the_default_and_listing_reads_both_legal_listings():
    rss = svc.ingesters_for("rss")
    assert [(i.url, i._parser) for i in rss] == [("https://www.sebi.gov.in/sebirss.xml", parse_rss)]
    listing = svc.ingesters_for("listing")
    assert [i.url for i in listing] == [
        "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0",
        "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=6&smid=0",
    ]
    assert all(i._parser is parse_listing for i in listing)
    assert len(svc.ingesters_for("all")) == 3
    with pytest.raises(ValueError):
        svc.ingesters_for("everything")


def test_run_goes_through_every_page_of_the_source(monkeypatch):
    seen = []

    async def fake_run(self, target_date=None):
        seen.append((self.url, target_date))
        return type("Job", (), {"run_id": uuid.uuid4()})()

    monkeypatch.setattr(svc.SebiCircularsIngester, "run", fake_run)
    asyncio.run(svc.run(date(2026, 10, 14), source="all"))
    assert [u for u, _ in seen] == [svc.SEBI_RSS_URL, *svc.SEBI_LISTING_URLS.values()]
    assert all(d is None for _, d in seen)       # SEBI only shows the newest items; no dated fetch


# ── fetch ─────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def read(self):
        return self._body

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _fake_session(status, body, seen):
    class _Session:
        def __init__(self, timeout=None, headers=None):
            seen["headers"] = headers

        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        def get(self, url):
            seen["url"] = url
            return _Resp(status, body)
    return _Session


FIXTURE_RSS = (Path(__file__).resolve().parents[1] / "fixtures" / "sebi" / "sebirss_20261014_trimmed.xml").read_bytes()


def test_fetch_hands_on_only_the_circular_items_and_says_who_is_asking(monkeypatch):
    seen = {}
    monkeypatch.setattr(svc.aiohttp, "ClientSession", _fake_session(200, FIXTURE_RSS, seen))
    body, url, status = asyncio.run(svc.SebiCircularsIngester().fetch(None))
    assert (url, status) == (svc.SEBI_RSS_URL, 200)
    assert seen["url"] == svc.SEBI_RSS_URL and "NiveshNIDP" in seen["headers"]["User-Agent"]
    # What BaseIngester archives: no recovery notice, no PAN, no name, no enforcement or press item.
    for gone in (b"ABCDE1234F", b"Test Person", b"/enforcement/", b"press-releases"):
        assert gone not in body
    assert body.count(b"<item>") == 3
    assert parse_rss(body) == parse_rss(FIXTURE_RSS)


def test_fetch_of_a_listing_page_is_not_rewritten(monkeypatch):
    page = b"<html><body><table><tr><td>Oct 07, 2026</td><td><a href='/legal/circulars/oct-2026/x_1.html'>X</a></td></tr></table></body></html>"
    monkeypatch.setattr(svc.aiohttp, "ClientSession", _fake_session(200, page, {}))
    body, _, _ = asyncio.run(svc.ingesters_for("listing")[0].fetch(None))
    assert body == page


def test_fetch_fails_before_archiving_when_the_feed_is_not_rss(monkeypatch):
    from nidp.services.sebi_circulars.parser import SebiFeedError
    monkeypatch.setattr(svc.aiohttp, "ClientSession", _fake_session(200, b"<html><body>Service down</body></html>", {}))
    with pytest.raises(SebiFeedError):
        asyncio.run(svc.SebiCircularsIngester().fetch(None))


@pytest.mark.parametrize("status,body", [(403, b"<html>Forbidden</html>"), (500, b""), (200, b""), (200, b"  \n")])
def test_fetch_fails_loud_on_an_error_status_or_an_empty_body(monkeypatch, status, body):
    monkeypatch.setattr(svc.aiohttp, "ClientSession", _fake_session(status, body, {}))
    with pytest.raises(RuntimeError):
        asyncio.run(svc.SebiCircularsIngester().fetch(None))


# ── writer ────────────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self):
        self.calls = []

    def transaction(self):
        class _Tx:
            async def __aenter__(self): return None
            async def __aexit__(self, *a): return False
        return _Tx()

    async def executemany(self, sql, args):
        self.calls.append((sql, list(args)))


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _CM()


def test_writer_upserts_by_url_and_keeps_the_first_sighting(monkeypatch):
    pool = _Pool()

    async def _get_pool(): return pool
    monkeypatch.setattr(writer, "get_pool", _get_pool)
    run_id = uuid.uuid4()
    row = {"url": "https://www.sebi.gov.in/legal/circulars/oct-2026/a_1.html", "title": "Synthetic circular", "kind": "circular",
           "issued_on": date(2026, 10, 7), "department": None, "source": "sebi_rss"}
    assert asyncio.run(writer.upsert_circulars([row], run_id)) == 1
    sql, args = pool.conn.calls[0]
    assert args == [(row["url"], row["title"], "circular", date(2026, 10, 7), None, "sebi_rss", run_id)]
    assert "ON CONFLICT (url) DO UPDATE" in sql
    update = sql.split("DO UPDATE SET", 1)[1]
    assert "first_seen_at" not in update and re.search(r"\bsource\s*=", update) is None
    assert "COALESCE(nidp.sebi_circulars.issued_on, EXCLUDED.issued_on)" in update


def test_writer_with_no_rows_does_not_touch_the_database(monkeypatch):
    async def _no_pool(): raise AssertionError("pool used")
    monkeypatch.setattr(writer, "get_pool", _no_pool)
    assert asyncio.run(writer.upsert_circulars([], uuid.uuid4())) == 0


# ── registration ──────────────────────────────────────────────────────────────

def test_cli_and_runner_can_find_the_service():
    from nidp.cli import SERVICES
    assert SERVICES["sebi_circulars"] == "nidp.services.sebi_circulars.service"
    assert callable(importlib.import_module(SERVICES["sebi_circulars"]).run)
    assert importlib.util.find_spec("nidp.services.sebi_circulars.__main__") is not None   # run_service.sh: python -m


def test_feed_registry_lists_it_unmonitored():
    from nidp.shared.feed_registry import FEEDS_BY_NAME, expected_feeds
    f = FEEDS_BY_NAME["sebi_circulars"]
    assert (f.cadence, f.monitored, f.severity) == ("high-freq", False, "WARN")
    assert "sebi_circulars" not in [name for name, _, _ in expected_feeds()]


def test_staging_cron_runs_it_every_3_hours_mon_to_sat():
    cron = (REPO / "deploy" / "cloudpe" / "nidp" / "nidp-staging.cron").read_text()
    lines = [l for l in cron.splitlines() if re.search(r"run_service\.sh sebi_circulars\b", l) and not l.lstrip().startswith("#")]
    assert lines == ["15 9-21/3 * * 1-6  nidp-staging  /opt/nidp-staging/run_service.sh sebi_circulars"]
    # 9-21/3 → 09:15, 12:15, 15:15, 18:15, 21:15 IST (CRON_TZ=Asia/Kolkata in the file)
    assert "CRON_TZ=Asia/Kolkata" in cron


def test_index_constituents_gets_the_mid_and_small_cap_lists():
    from nidp.shared.config import INDEX_CONSTITUENT_URLS
    assert INDEX_CONSTITUENT_URLS["Nifty Midcap 150"].endswith("/content/indices/ind_niftymidcap150list.csv")
    assert INDEX_CONSTITUENT_URLS["Nifty Smallcap 250"].endswith("/content/indices/ind_niftysmallcap250list.csv")
