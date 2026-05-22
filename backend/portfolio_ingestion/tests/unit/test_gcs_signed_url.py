"""Unit tests for GCS signed URL helpers — stub mode only (T3.1)."""
from __future__ import annotations

import os

import pytest

from portfolio_ingestion.services.gcs_signed_url import (
    SignedUploadUrl,
    build_object_key,
    generate_upload_url,
    verify_object_exists,
)


@pytest.fixture(autouse=True)
def force_stub_mode(monkeypatch):
    """Ensure GCS stub mode for all tests in this module."""
    monkeypatch.delenv("PI_GCS_BUCKET", raising=False)
    monkeypatch.setenv("PI_GCS_STUB", "true")


def test_build_object_key_structure():
    key = build_object_key("user-123", "upload-abc", "statement.pdf")
    assert key.startswith("cas-uploads/user-123/upload-abc/")
    assert key.endswith("statement.pdf")


def test_build_object_key_sanitises_slashes():
    key = build_object_key("user/with/slashes", "uid", "f.pdf")
    assert "//" not in key
    assert "user_with_slashes" in key


@pytest.mark.asyncio
async def test_generate_upload_url_stub_returns_fake_url():
    result = await generate_upload_url("cas-uploads/u1/j1/cas.pdf")
    assert isinstance(result, SignedUploadUrl)
    assert result.stub is True
    assert "stub" in result.url
    assert result.object_key == "cas-uploads/u1/j1/cas.pdf"


@pytest.mark.asyncio
async def test_generate_upload_url_stub_expires_in_future():
    import datetime as dt
    result = await generate_upload_url("k", ttl_seconds=900)
    assert result.expires_at > dt.datetime.now(dt.timezone.utc)


@pytest.mark.asyncio
async def test_verify_object_exists_stub_returns_true():
    exists = await verify_object_exists("cas-uploads/u1/j1/cas.pdf")
    assert exists is True
