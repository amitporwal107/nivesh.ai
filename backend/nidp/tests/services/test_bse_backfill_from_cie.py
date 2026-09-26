"""backfill_bse_from_cie.py and the writer step that retires its rows.

The RSS carries no NEWSID, so a backfilled filing can never share the API's
announcement_id. Two things keep that from becoming duplicates or bad data:
the backfill must recognise what production already holds (including BSE's
attachment-less notices), and the writer must delete an RSS row the moment its
API twin is written. Both are pinned here; the SQL itself was exercised against
staging Postgres inside a rolled-back transaction (see test_reports).
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from nidp.services.corporate_announcements import backfill_bse_from_cie as B
from nidp.services.corporate_announcements import writer as W
from nidp.services.corporate_announcements.parser_bse import _BSE_ATTACHMENT_BASE as BASE

BARE = BASE                                   # BSE's no-attachment notices link here


def _cie(url, scrip="530577", ts="2026-09-15T12:38:34+05:30", h="h1",
         summary="The Exchange has sought clarification from Ladderup Finance Ltd", seen=None):
    return {"hash": h, "url": url, "title": f"Ladderup Finance Ltd ({scrip})",
            "summary": summary, "scrip_code": scrip, "published_at": ts, "first_seen_at": seen or ts}


# ── attachment_url ──────────────────────────────────────────────────────────────
def test_bare_directory_link_is_stored_as_null_like_production():
    [row] = B._build([_cie(BARE)])
    assert row["attachment_url"] is None


def test_a_pdf_link_comes_through_the_production_parser():
    [row] = B._build([_cie(BASE + "abc.pdf")])
    assert row["attachment_url"] == BASE + "abc.pdf"


def test_a_link_outside_attachlive_is_kept_verbatim():
    link = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/abc.pdf"
    [row] = B._build([_cie(link)])
    assert row["attachment_url"] == link


def test_id_does_not_depend_on_the_attachment():
    """Re-running the write repairs rows stored with the bare URL: the id is
    unchanged, so ON CONFLICT updates attachment_url in place."""
    a = B._parse_one_bse(B._to_api_record(_cie(BARE)))
    b = B._build([_cie(BARE)])[0]
    assert a["announcement_id"] == b["announcement_id"]


# ── one row per filing from the CIE store ───────────────────────────────────────
def _store(tmp_path, rows):
    db = sqlite3.connect(tmp_path / "events.sqlite")
    db.execute("CREATE TABLE raw_events (hash, url, title, summary, scrip_code, published_at, first_seen_at, source_id)")
    db.executemany("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?)",
                   [(r["hash"], r["url"], r["title"], r["summary"], r["scrip_code"],
                     r["published_at"], r["first_seen_at"], B.CIE_SOURCE) for r in rows])
    db.commit(); db.close()
    return tmp_path / "events.sqlite"


def test_distinct_bare_notices_of_one_scrip_are_not_merged(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "CIE_STORE", _store(tmp_path, [
        _cie(BARE, ts="2026-09-15T10:00:00+05:30", h="a"),
        _cie(BARE, ts="2026-09-15T14:00:00+05:30", h="b")]))
    got = B._load_cie(datetime(2026, 9, 15).date(), datetime(2026, 9, 15).date())
    assert len(got) == 2


def test_the_same_pdf_named_twice_is_one_filing(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "CIE_STORE", _store(tmp_path, [
        _cie(BASE + "x.pdf", ts="2026-09-15T10:00:00+05:30", h="a"),
        _cie(BASE + "x.pdf", ts="2026-09-15T10:05:00+05:30", h="b")]))
    [got] = B._load_cie(datetime(2026, 9, 15).date(), datetime(2026, 9, 15).date())
    assert got["hash"] == "a", "earliest publication wins"


def test_a_replaced_attachment_is_one_filing_with_the_latest_file(tmp_path, monkeypatch):
    """Seen for real: 511710 on 2026-09-16 14:04:10 — BSE swapped ...-140350.pdf for
    ...-141516.pdf; production holds only the second."""
    ts = "2026-09-16T14:04:10+05:30"
    monkeypatch.setattr(B, "CIE_STORE", _store(tmp_path, [
        _cie(BASE + "X-140350.pdf", ts=ts, h="old", summary="Outcome", seen="2026-09-16T14:15:02+05:30"),
        _cie(BASE + "X-141516.pdf", ts=ts, h="new", summary="Outcome", seen="2026-09-16T14:30:03+05:30")]))
    [got] = B._load_cie(datetime(2026, 9, 16).date(), datetime(2026, 9, 16).date())
    assert got["url"] == BASE + "X-141516.pdf"


# ── scope ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("isin,equity", [
    ("INE721I01024", True),      # National Stock Exchange of India Ltd, listed 09-24
    ("INE002A01018", True),      # Reliance equity
    ("INE002A08617", False),     # debenture (type 08)
    ("INF204KB14I2", False),     # MF / ETF units
    ("", False), (None, False),
])
def test_equity_isin(isin, equity):
    assert B.is_equity_isin(isin) is equity


# ── what production already holds ───────────────────────────────────────────────
T = datetime(2026, 9, 15, 7, 8, 34, tzinfo=timezone.utc)


def _existing():
    return B.Existing([{"s": "530577", "a": BASE + "x.pdf", "t": T},
                       {"s": "530577", "a": None, "t": T + timedelta(seconds=90)}])


def _b(att, t, scrip="530577"):
    return {"scrip_code": scrip, "attachment_url": att, "filed_at": t}


def test_existing_by_attachment():
    assert _b(BASE + "x.pdf", T) in _existing()
    assert _b(BASE + "y.pdf", T) not in _existing()
    assert _b(BASE + "x.pdf", T, scrip="500003") not in _existing()


@pytest.mark.parametrize("offset_s,held", [   # production row sits at T+90 s
    (90, True),         # identical timestamps (our own earlier write)
    (0, True),          # production 90 s after the RSS submission
    (-90, True),        # 180 s lag: inside the 181.6 s maximum seen in production
    (89, True),         # production 1 s after submission
    (91, True),         # production 1 s BEFORE submission: second truncation
    (92, False),        # production 2 s before: not the same filing
    (-93, False),       # 183 s lag: beyond the observed maximum
])
def test_existing_attachment_less_by_time(offset_s, held):
    assert (_b(None, T + timedelta(seconds=offset_s)) in _existing()) is held


# ── the writer retires RSS rows when their API twin lands ───────────────────────
class _Conn:
    def __init__(self):
        self.calls = []

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Tx()

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):             # the supersede DELETE ... RETURNING
        self.calls.append((sql, args))
        return [{"announcement_id": "rss-twin-1"}]


class _Pool:
    def __init__(self, conn): self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Acq:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Acq()


def _row(aid, source="BSE_ANN", payload=None):
    return {"announcement_id": aid, "source": source, "filed_at": T, "raw_payload": payload or {}}


@pytest.fixture
def conn(monkeypatch):
    c = _Conn()

    async def _get_pool():
        return _Pool(c)
    monkeypatch.setattr(W, "get_pool", _get_pool)
    return c


def _supersedes(conn):
    return [args for sql, args in conn.calls if "RETURNING r.announcement_id" in sql]


def _dependant_deletes(conn):
    return [(sql.split()[2], args) for sql, args in conn.calls
            if sql.startswith("DELETE FROM nidp.corporate_") and "RETURNING" not in sql]


def test_writer_supersedes_only_for_api_rows_within_the_batch_time_span(conn):
    later = dict(_row("api2", payload={"NEWSID": "n2"}), filed_at=T + timedelta(hours=5))
    asyncio.run(W.upsert_announcements([
        _row("nse1", source="NSE_ANN", payload={"NEWSID": "not-bse"}),
        _row("rss1", payload={"via": "cie_bse_rss"}),
        _row("api1", payload={"NEWSID": "n1"}), later], source_run_id=None))
    # ids, then the batch's min/max filed_at as constants the planner can index on
    assert _supersedes(conn) == [(["api1", "api2"], T, T + timedelta(hours=5))]


def test_a_retired_rss_id_is_removed_from_tables_without_a_foreign_key(conn):
    asyncio.run(W.upsert_announcements([_row("api1", payload={"NEWSID": "n1"})], source_run_id=None))
    assert _dependant_deletes(conn) == [
        ("nidp.corporate_transaction_filings", (["rss-twin-1"],)),
        ("nidp.corporate_event_signals", (["rss-twin-1"],))]


def test_writer_skips_the_delete_when_no_api_row_is_written(conn):
    asyncio.run(W.upsert_announcements([_row("rss1", payload={"via": "cie_bse_rss"}),
                                        _row("nse1", source="NSE_ANN")], source_run_id=None))
    assert _supersedes(conn) == [] and _dependant_deletes(conn) == []


def test_every_supersede_form_shares_one_twin_predicate():
    for sql in (W._SUPERSEDE_FOR_BATCH, W.SUPERSEDE_RSS_SQL, W.COUNT_RSS_TWINS_SQL, W.COUNT_TWINS_OF_ROWS_SQL):
        assert W._TWIN_MATCH in sql
    for sql in (W._SUPERSEDE_FOR_BATCH, W.SUPERSEDE_RSS_SQL):
        assert sql.startswith("DELETE FROM nidp.corporate_announcements r USING") and sql.endswith("RETURNING r.announcement_id")
    assert "'cie_bse_rss'" in W._TWIN_MATCH and W.RSS_VIA == B.VIA == "cie_bse_rss"
