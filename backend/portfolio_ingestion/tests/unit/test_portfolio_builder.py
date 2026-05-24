"""Unit tests for the pure portfolio builder (no I/O)."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from portfolio_ingestion.schemas.parsed_data import (
    DematAccount,
    DematHolding,
    InsurancePolicy,
    InsuranceSection,
    MfAmc,
    MfFolio,
    MfScheme,
    NpsHolding,
    ParsedData,
)
from portfolio_ingestion.services.portfolio_builder import build_holdings


JOB_ID = UUID("00000000-0000-0000-0000-000000000123")
PAN = "a" * 64


def _build(payload: ParsedData) -> list:
    return build_holdings(
        payload,
        pan_hash=PAN,
        source_type="ECAS_CDSL",
        statement_to="2026-01-31",
        ingestion_job_id=JOB_ID,
        raw_data_ref="mongo:abc",
        sdk_method="upload",
    )


# ── Empty payload ─────────────────────────────────────────────────────────


def test_empty_payload_yields_no_rows() -> None:
    rows = _build(ParsedData())
    assert rows == []


# ── Demat: each instrument type maps to its own asset_class ───────────────


@pytest.mark.parametrize(
    # The new bucketed schema (which matches the real CASParser SDK output)
    # collapses instrument-type granularity into the SDK's five buckets:
    #   equity, etf  → bucket `equities`              → asset_class "equity"
    #   bond         → bucket `corporate_bonds`       → asset_class "bond"
    #   sgb          → bucket `government_securities` → asset_class "g_sec"
    #   aif          → bucket `aifs`                  → asset_class "aif"
    # The legacy flat-list shape is normalised through this map at parse time.
    "instrument_type,expected_class",
    [("equity", "equity"), ("etf", "equity"), ("bond", "bond"),
     ("sgb", "g_sec"), ("aif", "aif")],
)
def test_demat_instrument_type_drives_asset_class(
    instrument_type: str, expected_class: str
) -> None:
    payload = ParsedData(
        demat_accounts=[DematAccount(holdings=[
            DematHolding(
                isin="INE002A01018", name="X", quantity=Decimal("10"),
                value=Decimal("1000"), instrument_type=instrument_type,
            )
        ])]
    )
    rows = _build(payload)
    assert len(rows) == 1
    assert rows[0].asset_class == expected_class
    assert rows[0].isin == "INE002A01018"


# ── AC1: every leaf becomes one row with the right asset_class ────────────


def test_full_payload_maps_every_leaf() -> None:
    payload = ParsedData(
        demat_accounts=[DematAccount(dp_id="IN30001", client_id="ABCD", holdings=[
            DematHolding(isin="INE002A01018", name="RELIANCE", quantity=Decimal("10"), value=Decimal("25000"), instrument_type="equity"),
            DematHolding(isin="INE090A01021", name="ICICI BANK", quantity=Decimal("5"),  value=Decimal("5000"),  instrument_type="equity"),
        ])],
        mutual_funds=[
            MfFolio(amc="HDFC", folio_number="F-001", schemes=[
                MfScheme(scheme_code="120503", name="HDFC Flexi Cap", units=Decimal("100"), value=Decimal("10000")),
            ])
        ],
        insurance=InsuranceSection(life_insurance_policies=[
            InsurancePolicy(policy_number="P-1", name="LIC Jeevan", sum_assured=Decimal("500000"), value=Decimal("12345")),
        ]),
        nps=[
            NpsHolding(pran="11000", scheme="NPS Equity", units=Decimal("50"), value=Decimal("7000")),
        ],
    )
    rows = _build(payload)
    classes = sorted(r.asset_class for r in rows)
    assert classes == ["equity", "equity", "insurance", "mutual_fund", "nps"]
    assert sum(r.value for r in rows) == Decimal("59345")


# ── AC2: equity dedupe on (isin, quantity) ────────────────────────────────


def test_equity_dedupe_on_isin_and_quantity() -> None:
    h = DematHolding(isin="INE002A01018", name="X", quantity=Decimal("10"), value=Decimal("1000"))
    payload = ParsedData(demat_accounts=[DematAccount(holdings=[h, h, h])])
    rows = _build(payload)
    assert len(rows) == 1


def test_equity_different_qty_is_not_a_duplicate() -> None:
    payload = ParsedData(demat_accounts=[DematAccount(holdings=[
        DematHolding(isin="INE002A01018", name="X", quantity=Decimal("10"), value=Decimal("1000")),
        DematHolding(isin="INE002A01018", name="X", quantity=Decimal("20"), value=Decimal("2000")),
    ])])
    rows = _build(payload)
    assert len(rows) == 2


# ── AC2: MF dedupe on (amc, folio, scheme_code) ───────────────────────────


def test_mf_dedupe_on_amc_folio_scheme() -> None:
    s = MfScheme(scheme_code="120503", name="HDFC Flexi Cap", units=Decimal("100"), value=Decimal("10000"))
    payload = ParsedData(mutual_funds=[
        MfFolio(amc="HDFC", folio_number="F-1", schemes=[s, s]),
    ])
    rows = _build(payload)
    assert len(rows) == 1


def test_mf_different_folio_is_not_a_duplicate() -> None:
    s1 = MfScheme(scheme_code="120503", name="HDFC", units=Decimal("100"), value=Decimal("10000"))
    s2 = MfScheme(scheme_code="120503", name="HDFC", units=Decimal("100"), value=Decimal("10000"))
    payload = ParsedData(mutual_funds=[
        MfFolio(amc="HDFC", folio_number="F-1", schemes=[s1]),
        MfFolio(amc="HDFC", folio_number="F-2", schemes=[s2]),
    ])
    rows = _build(payload)
    assert len(rows) == 2


# ── AC3: source_trace structure ───────────────────────────────────────────


def test_source_trace_on_every_row_has_required_keys() -> None:
    payload = ParsedData(
        demat_accounts=[DematAccount(holdings=[
            DematHolding(isin="INE002A01018", name="Y", quantity=Decimal("1"), value=Decimal("1")),
        ])],
        mutual_funds=[MfFolio(amc="A", folio_number="F", schemes=[
            MfScheme(scheme_code="S", name="N", units=Decimal("1"), value=Decimal("1")),
        ])],
    )
    rows = _build(payload)
    for r in rows:
        assert r.source_trace["source_type"] == "ECAS_CDSL"
        assert r.source_trace["statement_to"] == "2026-01-31"
        assert r.source_trace["parser_ref"]["ingestion_job_id"] == str(JOB_ID)
        assert r.source_trace["parser_ref"]["sdk_method"] == "upload"
        assert "folio" in r.source_trace


# ── total_value sanity ────────────────────────────────────────────────────


def test_parsed_data_total_value_sums_everything() -> None:
    payload = ParsedData(
        demat_accounts=[DematAccount(holdings=[
            DematHolding(isin="INE002A01018", name="Y", quantity=Decimal("1"), value=Decimal("10")),
        ])],
        mutual_funds=[MfFolio(amc="A", folio_number="F", schemes=[
            MfScheme(scheme_code="S", name="N", units=Decimal("1"), value=Decimal("20")),
        ])],
        nps=[NpsHolding(pran="P", scheme="S", units=Decimal("1"), value=Decimal("5"))],
    )
    assert payload.total_value == Decimal("35")
