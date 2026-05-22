"""Unit tests for the CDSL OTP path (T3.4)."""
from __future__ import annotations

from portfolio_ingestion.schemas.parsed_data import SdkMetadata
from portfolio_ingestion.schemas.portfolio import SdkCallbackResponse


def test_sdk_metadata_defaults_raw_pdf_available_true():
    m = SdkMetadata(method="upload")
    assert m.raw_pdf_available is True


def test_sdk_metadata_cdsl_fetch_can_set_raw_pdf_available_false():
    m = SdkMetadata(method="cdsl_fetch", raw_pdf_available=False)
    assert m.raw_pdf_available is False


def test_sdk_callback_response_defaults_raw_pdf_available_true(tmp_uuid):
    from decimal import Decimal
    from portfolio_ingestion.schemas.portfolio import PortfolioResponse
    r = SdkCallbackResponse(
        job_id=tmp_uuid,
        snapshot_id=tmp_uuid,
        is_new=True,
        is_active=True,
        status="activated",
        portfolio=PortfolioResponse(
            total_value=Decimal("0"),
            holdings_count=0,
            allocation=[],
            top_holdings=[],
        ),
    )
    assert r.raw_pdf_available is True


def test_sdk_callback_response_accepts_raw_pdf_available_false(tmp_uuid):
    from decimal import Decimal
    from portfolio_ingestion.schemas.portfolio import PortfolioResponse
    r = SdkCallbackResponse(
        job_id=tmp_uuid,
        snapshot_id=tmp_uuid,
        is_new=True,
        is_active=True,
        status="activated",
        raw_pdf_available=False,
        portfolio=PortfolioResponse(
            total_value=Decimal("0"),
            holdings_count=0,
            allocation=[],
            top_holdings=[],
        ),
    )
    assert r.raw_pdf_available is False
