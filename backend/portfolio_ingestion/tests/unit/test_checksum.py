"""Unit tests for the PAN-hash helper."""
from __future__ import annotations

import hashlib

import pytest

from portfolio_ingestion.services.checksum import is_pan_hash, pan_hash


def test_pan_hash_is_deterministic_and_64_chars() -> None:
    h = pan_hash("ABCDE1234F")
    assert len(h) == 64
    assert h == hashlib.sha256(b"ABCDE1234F").hexdigest()


def test_pan_hash_is_case_and_whitespace_insensitive() -> None:
    assert pan_hash("abcde1234f") == pan_hash("ABCDE1234F")
    assert pan_hash(" ABCDE1234F ") == pan_hash("ABCDE1234F")


def test_pan_hash_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="10 characters"):
        pan_hash("ABCDE")
    with pytest.raises(ValueError):
        pan_hash("ABCDE1234F0")


def test_is_pan_hash_validates_format() -> None:
    assert is_pan_hash("a" * 64) is True
    assert is_pan_hash("0123456789abcdef" * 4) is True
    assert is_pan_hash("A" * 64) is False        # uppercase hex not allowed
    assert is_pan_hash("a" * 63) is False
    assert is_pan_hash("") is False
    assert is_pan_hash(None) is False
