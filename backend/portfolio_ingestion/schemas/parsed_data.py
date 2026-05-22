"""ParsedData — the normalised payload the CASParser SDK hands us.

The shape mirrors PRD §6.3 and the SDK's ``onSuccess`` callback. Fields not
exercised by V1 (``meta``, ``investor``, ``summary``) are accepted as ``Any``
so we don't bounce a perfectly-good payload on cosmetic drift.

This is the *only* place the SDK schema is interpreted. Every other module
works in terms of :class:`portfolio_ingestion.schemas.snapshot.HoldingRow`.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Demat side (CDSL / NSDL) ──────────────────────────────────────────────


class DematHolding(BaseModel):
    """One line in a demat account: an equity, ETF, bond, SGB or AIF unit."""
    model_config = ConfigDict(extra="ignore")

    isin: str | None = None
    name: str
    quantity: Decimal
    value: Decimal
    instrument_type: str = Field(
        default="equity", description="equity | etf | bond | sgb | aif"
    )


class DematAccount(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dp_id: str | None = None
    client_id: str | None = None
    holdings: list[DematHolding] = Field(default_factory=list)


# ── Mutual funds (CAMS / KFin or via eCAS) ────────────────────────────────


class MfScheme(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scheme_code: str | None = None
    name: str
    units: Decimal
    nav: Decimal | None = None
    value: Decimal


class MfFolio(BaseModel):
    model_config = ConfigDict(extra="ignore")
    folio: str
    schemes: list[MfScheme] = Field(default_factory=list)


class MfAmc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amc: str
    folios: list[MfFolio] = Field(default_factory=list)


# ── Insurance + NPS (V1: stored but minimally enriched) ───────────────────


class InsurancePolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    policy_number: str | None = None
    name: str
    sum_assured: Decimal | None = None
    value: Decimal = Decimal("0")


class InsuranceSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    life_insurance_policies: list[InsurancePolicy] = Field(default_factory=list)


class NpsHolding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pran: str | None = None
    scheme: str
    units: Decimal
    nav: Decimal | None = None
    value: Decimal


# ── Top-level ParsedData ──────────────────────────────────────────────────


class ParsedData(BaseModel):
    """The ``data`` field of the SDK ``onSuccess`` callback."""
    model_config = ConfigDict(extra="ignore")

    meta: dict[str, Any] = Field(default_factory=dict)
    investor: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    demat_accounts: list[DematAccount] = Field(default_factory=list)
    mutual_funds: list[MfAmc] = Field(default_factory=list)
    insurance: InsuranceSection = Field(default_factory=InsuranceSection)
    nps: list[NpsHolding] = Field(default_factory=list)

    @property
    def total_value(self) -> Decimal:
        """Sum of every line we can read a value out of."""
        total = Decimal("0")
        for da in self.demat_accounts:
            total += sum((h.value for h in da.holdings), Decimal("0"))
        for amc in self.mutual_funds:
            for fol in amc.folios:
                total += sum((s.value for s in fol.schemes), Decimal("0"))
        total += sum((p.value for p in self.insurance.life_insurance_policies), Decimal("0"))
        total += sum((n.value for n in self.nps), Decimal("0"))
        return total


class SdkMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    method: str = "upload"          # upload | inbox | generator | cdsl_fetch
    cas_type: str | None = None     # cdsl | nsdl | cams_kfintech
    processing_time_ms: int | None = None
    raw_pdf_available: bool = True  # False for cdsl_fetch (OTP path — no PDF)


class SdkCallbackPayload(BaseModel):
    """Wire body of POST /api/cas/sdk-callback."""
    model_config = ConfigDict(extra="ignore")

    upload_id: str | None = None
    checksum: str | None = None
    statement_from: dt.date | None = None
    statement_to: dt.date | None = None
    generated_at: dt.datetime | None = None
    source_type: str                      # ECAS_CDSL|ECAS_NSDL|MF_CAMS|MF_KFIN
    metadata: SdkMetadata = Field(default_factory=SdkMetadata)
    data: ParsedData
