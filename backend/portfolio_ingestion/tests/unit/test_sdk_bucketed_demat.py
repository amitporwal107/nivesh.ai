"""Schema acceptance against the ACTUAL CASParser SDK shape.

Driven by ``tests/fixtures/sdk_real_nsdl_demat.json`` — a verbatim capture
of a real /api/cas/sdk-callback payload as the SDK sends it.

The earlier version of this file tested an incorrect guess at the shape
(buckets at the wrong nesting level). The fixture is the source of truth
here so the test cannot drift from reality.

Real shape:

    demat_accounts: [
      {
        "holdings": {                  ← bucket OBJECT, not a list
            "equities": [...],
            "demat_mutual_funds": [...],
            "corporate_bonds": [],
            "aifs": [],
            "government_securities": []
        }
      },
      ...
    ]
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from portfolio_ingestion.schemas.parsed_data import ParsedData
from portfolio_ingestion.services.portfolio_builder import build_holdings


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sdk_real_nsdl_demat.json"


def _load_real_payload() -> dict:
    return json.loads(FIXTURE.read_text())


def test_real_sdk_payload_parses_without_422():
    """The exact shape the SDK sends must validate cleanly."""
    raw = _load_real_payload()
    payload = ParsedData.model_validate(raw)

    assert len(payload.demat_accounts) == 2
    # buckets are exposed via holdings.*
    da0 = payload.demat_accounts[0]
    assert len(da0.holdings.equities) == 1
    assert da0.holdings.equities[0].isin == "INE701B01021"        # PUNJ LLOYD
    assert da0.holdings.equities[0].units == Decimal("500")
    assert da0.holdings.equities[0].value == Decimal("1115")
    assert len(da0.holdings.demat_mutual_funds) == 4
    assert da0.holdings.demat_mutual_funds[0].isin == "INF109KC1NT3"
    assert da0.holdings.demat_mutual_funds[0].units == Decimal("5147")


def test_iter_lines_emits_correct_asset_classes_from_real_payload():
    payload = ParsedData.model_validate(_load_real_payload())
    asset_classes = []
    for da in payload.demat_accounts:
        asset_classes.extend(ac for ac, _ in da.iter_lines())
    # Account 0: 1 equity + 4 demat MFs.
    # Account 1: 6 equities + 2 demat MFs.
    assert asset_classes.count("equity") == 1 + 6
    assert asset_classes.count("mutual_fund") == 4 + 2
    assert asset_classes.count("bond") == 0     # corporate_bonds empty
    assert asset_classes.count("aif") == 0
    assert asset_classes.count("g_sec") == 0


def test_total_value_sums_across_buckets():
    """Money math is the load-bearing assertion; everything else is shape."""
    payload = ParsedData.model_validate(_load_real_payload())
    # Account 0:
    #   PUNJ LLOYD          1115.00
    #   ICICI Gold ETF    658155.12
    #   ICICI Nifty100      5610.77
    #   PARAG PARIKH      248877.36
    #   SBI L&M             36276.40
    a0 = Decimal("1115") + Decimal("658155.12") + Decimal("5610.77") + Decimal("248877.36") + Decimal("36276.4")
    # Account 1:
    #   NIPPON LIQUID         708.00
    #   ZERODHA              5804.94
    #   BHARTI              28302.00
    #   HDFC BANK           54790.70
    #   RELIANCE            31477.60
    #   NETWEB             162592.00
    #   NTPC GREEN         109850.00
    #   JIO FIN            231587.80
    a1 = (Decimal("708") + Decimal("5804.94") + Decimal("28302")
          + Decimal("54790.7") + Decimal("31477.6") + Decimal("162592")
          + Decimal("109850") + Decimal("231587.8"))
    assert payload.total_value == a0 + a1


def test_builder_emits_one_row_per_real_holding():
    payload = ParsedData.model_validate(_load_real_payload())
    rows = build_holdings(
        payload,
        pan_hash="0" * 64,
        source_type="ECAS_NSDL",
        statement_to="2026-04-30",
        ingestion_job_id=uuid4(),
        raw_data_ref=None,
    )
    # 1 + 4 + 6 + 2 = 13 lines across the two accounts.
    assert len(rows) == 13

    by_isin = {r.isin: r for r in rows}
    # Spot-check a few real ISINs across both accounts and both asset classes.
    assert by_isin["INE701B01021"].asset_class == "equity"        # PUNJ LLOYD
    assert by_isin["INE701B01021"].quantity == Decimal("500")
    assert by_isin["INF109KC1NT3"].asset_class == "mutual_fund"   # ICICI Gold ETF
    assert by_isin["INF109KC1NT3"].quantity == Decimal("5147")
    assert by_isin["INE002A01018"].asset_class == "equity"        # RELIANCE
    assert by_isin["INF0R8F01034"].asset_class == "mutual_fund"   # ZERODHA LIQUID


def test_legacy_flat_list_still_parses():
    """The pre-SDK fixture shape (`holdings` as a flat list with
    `quantity`/`instrument_type`) must continue to work — the normaliser in
    DematAccount.holdings validator buckets each item by instrument_type."""
    legacy = {
        "investor": {"pan": "ABCDE1234F"},
        "demat_accounts": [
            {
                "dp_id": "IN300000",
                "holdings": [
                    {"isin": "INE002A01018", "name": "RELIANCE", "quantity": 10, "value": 14000, "instrument_type": "equity"},
                    {"isin": "INE0R8F01034", "name": "ZERODHA ETF",  "quantity": 100, "value": 11382, "instrument_type": "etf"},
                ],
            }
        ],
        "mutual_funds": [],
    }
    payload = ParsedData.model_validate(legacy)
    da = payload.demat_accounts[0]
    # Both 'equity' and 'etf' from the legacy shape bucket into equities/.
    assert len(da.holdings.equities) == 2
    assert len(da.holdings.demat_mutual_funds) == 0


def test_legacy_synthetic_fixture_from_audit_tests_still_works():
    """Mirrors the construct in tests/integration/test_parsed_data_archive.py:
    DematHolding(..., quantity=Decimal('1.23456')) → schema accepts 'quantity'
    as an alias for 'units'."""
    from portfolio_ingestion.schemas.parsed_data import DematHolding
    h = DematHolding.model_validate({
        "isin": "INE002A01018", "name": "X",
        "quantity": "1.23456", "value": "99999.99",
    })
    assert h.units == Decimal("1.23456")
    assert h.value == Decimal("99999.99")
