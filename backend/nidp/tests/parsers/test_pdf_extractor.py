"""Unit tests for the PDF text extractor's storage-safety guarantees.

Pure functions, no network/DB.

NUL bytes are the case that matters here: pypdf, OCR and the vision fallback can
all emit them, Postgres TEXT cannot store them, and asyncpg fails the whole
parse with CharacterNotInRepertoireError. The download outage masked this for
the entire corpus — nothing ever reached the insert — so it only surfaced once
filings started downloading again.
"""
from __future__ import annotations

from nidp.services.document_parser.pdf_extractor import ExtractedDoc


def test_nul_bytes_are_stripped_from_full_text_and_pages():
    doc = ExtractedDoc(
        full_text="Board Meeting\x00 Outcome",
        pages=["Board Meeting\x00", "\x00Outcome\x00"],
        page_count=2,
    )
    assert "\x00" not in doc.full_text
    assert doc.full_text == "Board Meeting Outcome"
    assert all("\x00" not in p for p in doc.pages)
    assert doc.pages == ["Board Meeting", "Outcome"]


def test_a_none_page_does_not_crash_sanitisation():
    # pypdf yields "" for unreadable pages, but the vision/OCR paths can hand
    # back None for a page they failed to render.
    doc = ExtractedDoc(full_text="text", pages=[None, "ok"], page_count=2)
    assert doc.pages == ["", "ok"]


def test_clean_text_is_left_byte_for_byte_unchanged():
    text = "Q3 FY26 Earnings Call Transcript\n\nपृष्ठ 1 — ₹1,234.56 crore"
    pages = ["Q3 FY26 Earnings Call Transcript", "पृष्ठ 1 — ₹1,234.56 crore"]
    doc = ExtractedDoc(full_text=text, pages=list(pages), page_count=2)
    assert doc.full_text == text
    assert doc.pages == pages


def test_lone_surrogates_are_stripped():
    # The real 18k backfill died here: pypdf emitted a LONE surrogate (\ud800 —
    # not a valid astral char, which is a surrogate *pair*) from a filing with a
    # broken CMap, and asyncpg raised
    #   DataError: ... 'utf-8' codec can't encode characters ... surrogates not allowed
    raw = "TBO Tek Limited \ud800 CIN: L74999DL2006PLC155233"
    doc = ExtractedDoc(full_text=raw, pages=[raw], page_count=1)
    assert "\ud800" not in doc.full_text
    assert doc.full_text == "TBO Tek Limited  CIN: L74999DL2006PLC155233"
    assert doc.pages[0] == doc.full_text


def test_valid_astral_characters_are_NOT_stripped():
    # Guard against over-sanitising: an emoji/astral char is a surrogate *pair*
    # and is perfectly storable — only LONE surrogates are the problem.
    doc = ExtractedDoc(full_text="Profit 😀 ₹1cr 𐀀", pages=["😀"], page_count=1)
    assert doc.full_text == "Profit 😀 ₹1cr 𐀀"
    assert doc.pages[0] == "😀"


def test_sanitised_text_survives_the_encode_that_asyncpg_performs():
    # The precise operation that threw inside asyncpg's bind_execute. If this
    # raises, the document fails to store — so assert it cannot.
    nasty = "Board\x00 Meeting \ud800 Outcome \udfff ₹1,234"
    doc = ExtractedDoc(full_text=nasty, pages=[nasty], page_count=1)
    doc.full_text.encode("utf-8")          # must not raise
    for p in doc.pages:
        p.encode("utf-8")                  # must not raise
    assert "₹1,234" in doc.full_text       # real content preserved
