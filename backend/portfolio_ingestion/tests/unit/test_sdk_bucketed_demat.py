"""Unit test against the real CASParser SDK demat shape.

Regression: the SDK splits demat positions into typed buckets per account
(equities, demat_mutual_funds, corporate_bonds, aifs, government_securities)
rather than a single flat holdings list. The earlier schema rejected this
shape with a 422 'Input should be a valid list' on demat_accounts[*].holdings.

This test pins both the schema acceptance and the builder's asset_class
mapping for each bucket.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from portfolio_ingestion.schemas.parsed_data import ParsedData
from portfolio_ingestion.services.portfolio_builder import build_holdings


def _sample_bucketed_payload() -> dict:
    """Trimmed-down NSDL e-CAS demat shape — same keys as the real SDK."""
    return {
        "meta": {"cas_type": "NSDL"},
        "investor": {"pan": "ABCDE1234F"},
        "demat_accounts": [
            {
                "dp_id": "IN300000",
                "client_id": "12345678",
                "equities": [
                    {
                        "isin": "INE002A01018",
                        "name": "RELIANCE INDUSTRIES LIMITED",
                        "units": 22,
                        "value": 31477.6,
                        "transactions": [],
                        "additional_info": {"stock_symbol": "RELIANCE.NSE"},
                    },
                ],
                "demat_mutual_funds": [
                    {
                        "isin": "INF109KC1NT3",
                        "name": "ICICI PRUDENTIAL GOLD ETF",
                        "units": 5147,
                        "value": 658155.12,
                    },
                ],
                "corporate_bonds": [],
                "aifs": [],
                "government_securities": [],
            },
        ],
        "mutual_funds": [],
    }


def test_parsed_data_accepts_bucketed_demat_shape():
    payload = ParsedData.model_validate(_sample_bucketed_payload())
    assert len(payload.demat_accounts) == 1
    da = payload.demat_accounts[0]
    assert len(da.equities) == 1
    assert da.equities[0].isin == "INE002A01018"
    assert da.equities[0].units == Decimal("22")
    assert len(da.demat_mutual_funds) == 1
    assert da.demat_mutual_funds[0].units == Decimal("5147")


def test_iter_lines_yields_correct_asset_classes():
    payload = ParsedData.model_validate(_sample_bucketed_payload())
    da = payload.demat_accounts[0]
    lines = da.iter_lines()
    assets = sorted(ac for ac, _ in lines)
    assert assets == ["equity", "mutual_fund"]


def test_legacy_flat_holdings_still_parses():
    """Older fixtures use the flat `holdings` list with `quantity`/instrument_type.
    Schema accepts both via populate_by_name."""
    legacy = {
        "investor": {"pan": "ABCDE1234F"},
        "demat_accounts": [
            {
                "dp_id": "IN300000",
                "holdings": [
                    {"isin": "INE002A01018", "name": "RELIANCE", "quantity": 10, "value": 14000,
                     "instrument_type": "equity"},
                    {"isin": "INE0R8F01034", "name": "ZERODHA LIQUID ETF", "quantity": 100, "value": 11382,
                     "instrument_type": "etf"},
                ],
            },
        ],
        "mutual_funds": [],
    }
    payload = ParsedData.model_validate(legacy)
    da = payload.demat_accounts[0]
    lines = da.iter_lines()
    assert len(lines) == 2
    assert {ac for ac, _ in lines} == {"equity", "etf"}


def test_builder_emits_correct_asset_classes_from_buckets():
    payload = ParsedData.model_validate(_sample_bucketed_payload())
    rows = build_holdings(
        payload,
        pan_hash="0" * 64,
        source_type="ECAS_NSDL",
        statement_to="2026-04-30",
        ingestion_job_id=uuid4(),
        raw_data_ref=None,
    )
    by_isin = {r.isin: r for r in rows}
    assert by_isin["INE002A01018"].asset_class == "equity"
    assert by_isin["INE002A01018"].quantity == Decimal("22")
    assert by_isin["INF109KC1NT3"].asset_class == "mutual_fund"
    assert by_isin["INF109KC1NT3"].quantity == Decimal("5147")


def test_total_value_sums_all_buckets():
    payload = ParsedData.model_validate(_sample_bucketed_payload())
    # 31477.6 (equity) + 658155.12 (mf) = 689632.72
    assert payload.total_value == Decimal("31477.6") + Decimal("658155.12")
