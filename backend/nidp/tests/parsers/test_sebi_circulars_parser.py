"""SEBI circulars parsers (services/sebi_circulars/parser.py).

Fixtures (backend/nidp/tests/fixtures/sebi/):
  sebirss_20261014_trimmed.xml                 trimmed copy of the 2026-10-14 SEBI RSS feed; its header comment
                                               says which items are verbatim, synthetic (the PAN-bearing notice)
                                               or constructed from the listing (the feed had no circular that day)
  sebi_circulars_listing_20261014_trimmed.html trimmed copy of the 2026-10-14 Circulars listing, page 1
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from nidp.services.sebi_circulars.parser import (
    SebiFeedError, canonical_url, kind_for_url, parse_listing, parse_rss, parse_sebi_day, redact_rss,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sebi"
RSS = (FIXTURES / "sebirss_20261014_trimmed.xml").read_bytes()
LISTING = (FIXTURES / "sebi_circulars_listing_20261014_trimmed.html").read_bytes()

_RSS_HEAD = (b'<?xml version="1.0" encoding="UTF-8" standalone="no"?><rss version="2.0"><channel><ttl>60</ttl>'
             b"<title>SEBI RSS Feed</title>")


def _feed(*items: tuple[str, str, str]) -> bytes:
    body = "".join(f"<item><title>{t}</title><description>{t}</description><link>{l}</link><pubDate>{d}</pubDate></item>"
                   for t, l, d in items)
    return _RSS_HEAD + body.encode("utf-8") + b"</channel></rss>"


# ── RSS ───────────────────────────────────────────────────────────────────────

def test_rss_keeps_only_circulars_and_master_circulars():
    rows = parse_rss(RSS)
    assert [(r["kind"], r["issued_on"]) for r in rows] == [
        ("circular", date(2026, 10, 7)),
        ("circular", date(2026, 10, 1)),
        ("master_circular", date(2026, 9, 28)),
    ]
    assert rows[0] == {
        "url": "https://www.sebi.gov.in/legal/circulars/oct-2026/introduction-of-credit-risk-o-meter-as-an-additional-disclosure-mechanism-for-debt-securities_105081.html",
        "title": "Introduction of Credit Risk-o-Meter as an additional disclosure mechanism for debt securities",
        "kind": "circular",
        "issued_on": date(2026, 10, 7),
        "department": None,
        "source": "sebi_rss",
    }
    assert rows[1]["title"] == ("Display of “investor awareness message(s)” by stock brokers on their trading apps "
                                "and websites, under Project Jagrook")


def test_rss_drops_enforcement_recovery_and_press_items_and_never_keeps_a_pan():
    rows = parse_rss(RSS)
    assert all("/legal/" in r["url"] for r in rows)
    assert not any("enforcement" in r["url"] or "press-releases" in r["url"] for r in rows)
    flat = repr(rows)
    assert "ABCDE1234F" not in flat and "Test Person" not in flat
    assert all("description" not in r for r in rows)


def test_today_shaped_feed_with_no_circular_gives_no_rows():
    # The 2026-10-14 feed: 30 items, all enforcement orders and recovery notices (synthetic text here).
    feed = _feed(
        ("Notice of attachment issued against Synthetic Person under RC No. 0001 of 2024",
         "https://www.sebi.gov.in/enforcement/recovery-proceedings/oct-2026/notice-of-attachment-synthetic_100003.html",
         "13 Oct, 2026 +0530"),
        ("Appeal No. 0002 of 2026 filed by Synthetic Appellant",
         "https://www.sebi.gov.in/enforcement/orders/oct-2026/appeal-no-0002-of-2026-synthetic_100004.html",
         "12 Oct, 2026 +0530"),
    )
    assert parse_rss(feed) == []


def test_a_pan_in_a_circular_title_is_dropped_too():
    feed = _feed(("Circular naming PAN ABCDE1234F (synthetic)",
                  "https://www.sebi.gov.in/legal/circulars/oct-2026/synthetic_100005.html", "13 Oct, 2026 +0530"),
                 ("Synthetic circular without one",
                  "https://www.sebi.gov.in/legal/circulars/oct-2026/synthetic_100006.html", "13 Oct, 2026 +0530"))
    assert [r["title"] for r in parse_rss(feed)] == ["Synthetic circular without one"]


def test_duplicate_links_and_http_scheme_collapse_to_one_https_row():
    feed = _feed(("Synthetic circular", "http://sebi.gov.in/legal/circulars/oct-2026/synthetic_100007.html", "13 Oct, 2026 +0530"),
                 ("Synthetic circular", "https://www.sebi.gov.in/legal/circulars/oct-2026/synthetic_100007.html", "13 Oct, 2026 +0530"))
    rows = parse_rss(feed)
    assert [r["url"] for r in rows] == ["https://www.sebi.gov.in/legal/circulars/oct-2026/synthetic_100007.html"]


def test_unparseable_pubdate_keeps_the_row_with_a_null_date():
    feed = _feed(("Synthetic circular", "https://www.sebi.gov.in/legal/circulars/oct-2026/synthetic_100008.html", "soon"))
    assert parse_rss(feed)[0]["issued_on"] is None


@pytest.mark.parametrize("body", [
    b"",
    b"<html><body>Access Denied</body></html>",
    b"not xml at all",
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel></channel></rss>',
])
def test_a_body_that_is_not_the_rss_feed_fails_loud(body):
    with pytest.raises(SebiFeedError):
        parse_rss(body)


def test_redacted_feed_keeps_the_header_and_only_the_circular_items():
    red = redact_rss(RSS)
    assert red.startswith(b"<?xml")
    assert b"<title>SEBI RSS Feed</title>" in red and b"<pubDate>14 Oct 2026 14:00:02 +0530</pubDate>" in red
    assert red.count(b"<item>") == 3
    for gone in (b"ABCDE1234F", b"Test Person", b"Example Synthetic", b"IIFL", b"/enforcement/", b"press-releases"):
        assert gone not in red
    assert parse_rss(red) == parse_rss(RSS)


def test_redacting_a_feed_with_no_circular_leaves_an_empty_channel():
    red = redact_rss(_feed(("Notice of attachment issued against Synthetic Person (PAN: ABCDE1234F)",
                            "https://www.sebi.gov.in/enforcement/recovery-proceedings/oct-2026/synthetic_100009.html",
                            "13 Oct, 2026 +0530")))
    assert b"<item>" not in red and b"ABCDE1234F" not in red and b"Synthetic Person" not in red
    assert parse_rss(red) == []


def test_redact_refuses_a_body_that_is_not_the_feed():
    with pytest.raises(SebiFeedError):
        redact_rss(b"<html><body>Access Denied</body></html>")


# ── link and date helpers ─────────────────────────────────────────────────────

@pytest.mark.parametrize("url,kind", [
    ("https://www.sebi.gov.in/legal/circulars/oct-2026/x_1.html", "circular"),
    ("https://www.sebi.gov.in/legal/master-circulars/sep-2026/x_2.html", "master_circular"),
    ("https://sebi.gov.in/legal/circulars/oct-2026/x_3.html", "circular"),
    ("https://www.sebi.gov.in/legal/circulars/", None),                       # the section index, not a circular
    ("https://www.sebi.gov.in/legal/regulations/oct-2026/x_4.html", None),
    ("https://www.sebi.gov.in/enforcement/orders/oct-2026/x_5.html", None),
    ("https://www.sebi.gov.in/enforcement/recovery-proceedings/oct-2026/x_6.html", None),
    ("https://www.sebi.gov.in/media-and-notifications/press-releases/oct-2026/x_7.html", None),
    ("https://evil.example/legal/circulars/oct-2026/x_8.html", None),
    ("ftp://www.sebi.gov.in/legal/circulars/oct-2026/x_9.html", None),
    ("", None),
])
def test_kind_for_url(url, kind):
    assert kind_for_url(url) == kind


def test_canonical_url_is_https_www():
    assert canonical_url(" http://sebi.gov.in/legal/circulars/a_1.html#top ") == "https://www.sebi.gov.in/legal/circulars/a_1.html"


@pytest.mark.parametrize("text,day", [
    ("13 Oct, 2026 +0530", date(2026, 10, 13)),          # RSS pubDate as served
    ("Mon, 13 Oct 2026 10:00:00 +0530", date(2026, 10, 13)),
    ("Oct 07, 2026", date(2026, 10, 7)),                 # listing Date column
    ("Sept 9, 2026", date(2026, 9, 9)),
    ("31 Feb, 2026 +0530", None),
    ("", None),
    (None, None),
])
def test_parse_sebi_day(text, day):
    assert parse_sebi_day(text) == day


# ── listing page ──────────────────────────────────────────────────────────────

def test_listing_page_rows():
    rows = parse_listing(LISTING)
    assert [(r["issued_on"], r["kind"], r["source"]) for r in rows] == [
        (date(2026, 10, 7), "circular", "sebi_listing")] * 3
    assert rows[2] == {
        "url": "https://www.sebi.gov.in/legal/circulars/oct-2026/review-of-provisions-related-to-international-securities-identification-number-isin-for-debt-securities-issued-on-private-placement-basis_105076.html",
        "title": "Review of provisions related to International Securities Identification Number (ISIN) for debt securities issued on private placement basis",
        "kind": "circular",
        "issued_on": date(2026, 10, 7),
        "department": None,
        "source": "sebi_listing",
    }


def test_listing_url_matches_the_rss_url_for_the_same_circular():
    rss_urls = {r["url"] for r in parse_rss(RSS)}
    listing_urls = {r["url"] for r in parse_listing(LISTING)}
    assert "https://www.sebi.gov.in/legal/circulars/oct-2026/introduction-of-credit-risk-o-meter-as-an-additional-disclosure-mechanism-for-debt-securities_105081.html" in rss_urls & listing_urls


def test_listing_page_without_the_table_gives_no_rows():
    assert parse_listing(b"<html><body><a href='/legal/circulars/oct-2026/x_1.html'>menu link</a></body></html>") == []
