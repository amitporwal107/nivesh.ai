"""Unit tests for the document_parser Claude-vision fallback.

Covers the pure page-selection helper and the graceful-availability gate — no
anthropic package, no pdftoppm, and no network required.
"""
import nidp.services.document_parser.pdf_extractor as pe
import nidp.services.document_parser.vision_extractor as ve


# ── _low_text_pages (pure) ───────────────────────────────────────────

def test_low_text_pages_flags_image_heavy_slides():
    pages = ["A" * 500, "", "   ", "B" * 10, "C" * 300]
    # min_chars=200 → indices 1 (empty), 2 (blank), 3 (10 chars) are low-text
    assert pe._low_text_pages(pages, min_chars=200) == [1, 2, 3]


def test_low_text_pages_all_rich_returns_empty():
    pages = ["x" * 300, "y" * 400]
    assert pe._low_text_pages(pages, min_chars=200) == []


def test_low_text_pages_none_safe():
    assert pe._low_text_pages([None, "", "ok" * 200], min_chars=200) == [0, 1]


def test_low_text_pages_default_threshold():
    # Default threshold is 200 chars; a 199-char page is low-text.
    assert pe._low_text_pages(["z" * 199]) == [0]
    assert pe._low_text_pages(["z" * 200]) == []


# ── vision_available gate (graceful) ─────────────────────────────────

def test_vision_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ve.vision_available() is False


def test_extract_pages_noop_when_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Even with page numbers, returns {} (never raises) when the fallback is off.
    assert ve.extract_pages(b"%PDF-1.4 fake", [1, 2, 3]) == {}


def test_extract_pages_empty_input():
    assert ve.extract_pages(b"", []) == {}
