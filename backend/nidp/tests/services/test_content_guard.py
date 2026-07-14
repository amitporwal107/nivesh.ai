"""Unit tests for the fetch-layer content guard (WORK-0137).

Two things must hold:
  1. Real feed payloads (CSV/JSON/HTML tables/binary) are NEVER flagged — a
     false positive would fail a good run.
  2. Known HTTP-200 error/bot-block/maintenance pages ARE flagged, so they fail
     LOUD (error_class=CONTENT) instead of parsing to 0 rows -> silent SKIPPED.
"""
from __future__ import annotations

import pytest

from nidp.shared.sources.content_guard import detect_unsupported_content, sniff_content_type
from nidp.shared.ingester_base import _content_type_conflict


# ── real payloads that MUST NOT be flagged ──────────────────────────────────
REAL_OK = {
    "bhavcopy_csv": b"SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE\nRELIANCE,EQ,07-JUL-2026,2900,2910\n",
    "json_array":   b'[{"symbol":"RELIANCE","buyValue":123.4},{"symbol":"TCS","buyValue":56.7}]',
    "rbi_html":     b"<html><head><title>RBI - Weekly Statistical Supplement</title></head>"
                    b"<body><table><tr><td>91-day T-Bill</td><td>6.85</td></tr></table></body></html>",
    "fii_html":     b"<html><body><table id='fiidii'><tr><th>Category</th><th>Buy</th></tr>"
                    b"<tr><td>FII</td><td>1000</td></tr></table></body></html>",
    "index_csv":    b"Index Name,Open,High,Low,Close\nNIFTY 50,24000,24100,23950,24050\n",
}

# ── error / bot-block / maintenance pages that MUST be flagged ──────────────
BLOCKED = {
    "akamai_access_denied": b"<html><head><title>Access Denied</title></head><body>"
                            b"You don't have permission to access ... Reference #18.abc</body></html>",
    "waf_request_rejected": b"<html><body>The requested URL was rejected. "
                            b"Please consult with your administrator.</body></html>",
    "cloudflare":           b"<html><head><title>Attention Required! | Cloudflare</title></head>"
                            b"<body><div class='cf-browser-verification'></div></body></html>",
    "maintenance":          b"<html><body><h1>The site is under maintenance</h1></body></html>",
    "temp_unavailable":     b"<html><body>Service temporarily unavailable. Try again later.</body></html>",
}


@pytest.mark.parametrize("name,body", REAL_OK.items())
def test_real_payloads_not_flagged(name, body):
    assert detect_unsupported_content(body) is None, f"false positive on {name}"


@pytest.mark.parametrize("name,body", BLOCKED.items())
def test_error_pages_flagged(name, body):
    assert detect_unsupported_content(body) is not None, f"missed error page {name}"


def test_case_insensitive():
    assert detect_unsupported_content(b"<TITLE>ACCESS DENIED</TITLE>") is not None


def test_binary_payloads_skipped():
    assert detect_unsupported_content(b"PK\x03\x04rest-of-zip") is None       # xlsx/zip
    assert detect_unsupported_content(b"\x1f\x8bgzip-body") is None            # gzip
    assert detect_unsupported_content(b"%PDF-1.7 ...") is None                 # pdf


def test_empty_body_is_none():
    assert detect_unsupported_content(b"") is None


def test_signature_only_scanned_in_head():
    # A benign body with the phrase far past the sample window is not flagged.
    body = b"x" * 20000 + b"access denied"
    assert detect_unsupported_content(body, sample_bytes=8192) is None


# ── WORK-0140: content-type sniff + conflict ────────────────────────────────
def test_sniff_binary_and_structured():
    assert sniff_content_type(b"PK\x03\x04....") == "application/zip"
    assert sniff_content_type(b"\x1f\x8b\x08rest") == "application/gzip"
    assert sniff_content_type(b"%PDF-1.7") == "application/pdf"
    assert sniff_content_type(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1xls") == "application/vnd.ms-excel"
    assert sniff_content_type(b'  [{"a":1}]') == "application/json"
    assert sniff_content_type(b"<!DOCTYPE html><html>..") == "text/html"
    assert sniff_content_type(b"<?xml version='1.0'?>") == "application/xml"


def test_sniff_plain_csv_is_none():
    assert sniff_content_type(b"SYMBOL,SERIES,CLOSE\nRELIANCE,EQ,2900\n") is None
    assert sniff_content_type(b"") is None


def test_content_type_conflict_flags_text_url_binary_body():
    assert _content_type_conflict("text/csv", "application/gzip") is True
    assert _content_type_conflict("application/json", "text/html") is True


def test_content_type_conflict_ignores_benign():
    assert _content_type_conflict("text/csv", None) is False           # unknown/plain
    assert _content_type_conflict("text/csv", "text/csv") is False     # match
    assert _content_type_conflict("application/zip", "application/zip") is False  # not text-expected
