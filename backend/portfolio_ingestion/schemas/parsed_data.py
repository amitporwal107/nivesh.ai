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

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Demat side (CDSL / NSDL) ──────────────────────────────────────────────
#
# Real CASParser SDK output (proven against an actual NSDL e-CAS payload —
# see tests/fixtures/sdk_real_nsdl_demat.json):
#
#     demat_accounts: [
#       {
#         "holdings": {                  ← bucket OBJECT, not a list
#             "equities":              [DematHolding, …],
#             "demat_mutual_funds":    [DematHolding, …],
#             "corporate_bonds":       [DematHolding, …],
#             "aifs":                  [DematHolding, …],
#             "government_securities": [DematHolding, …]
#         }
#       }, ...
#     ]
#
# An older synthetic shape used the same key (`holdings`) but as a FLAT LIST
# with an `instrument_type` field. We accept both via a model_validator at
# parse time, normalising the input into a single canonical bucket object.


class DematHolding(BaseModel):
    """One line within a demat-account bucket (equity, ETF, MF unit, bond, …)."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    isin: str | None = None
    name: str
    units: Decimal = Field(..., alias="quantity")   # accept both `units` (SDK) and `quantity` (legacy)
    value: Decimal
    # Optional — only carries a value when we accept the legacy flat list,
    # used by the legacy-shape normaliser to bucket each item. With the SDK
    # bucketed shape, asset_class is inferred from the parent bucket name.
    instrument_type: str | None = None


# ── Bucket → asset_class map. Defined once, used by both the parser and the
# portfolio builder via iter_lines() below.
_BUCKET_TO_ASSET: dict[str, str] = {
    "equities":              "equity",
    "demat_mutual_funds":    "mutual_fund",
    "corporate_bonds":       "bond",
    "aifs":                  "aif",
    "government_securities": "g_sec",
}

# legacy instrument_type → bucket name (when bucketising a flat list).
_LEGACY_TYPE_TO_BUCKET: dict[str, str] = {
    "equity":      "equities",
    "etf":         "equities",   # ETFs hold in demat side as equities
    "mf":          "demat_mutual_funds",
    "mutual_fund": "demat_mutual_funds",
    "bond":        "corporate_bonds",
    "sgb":         "government_securities",
    "aif":         "aifs",
}


class DematHoldingsBuckets(BaseModel):
    """The bucket object that lives under ``demat_accounts[].holdings``."""
    model_config = ConfigDict(extra="ignore")
    equities:              list[DematHolding] = Field(default_factory=list)
    demat_mutual_funds:    list[DematHolding] = Field(default_factory=list)
    corporate_bonds:       list[DematHolding] = Field(default_factory=list)
    aifs:                  list[DematHolding] = Field(default_factory=list)
    government_securities: list[DematHolding] = Field(default_factory=list)


class DematAccount(BaseModel):
    """An aggregated demat account.

    The SDK sends:
        { dp_id?, client_id?, holdings: { equities: […], … } }

    The legacy synthetic shape sent:
        { dp_id?, client_id?, holdings: [DematHolding, …] }   # flat list

    Both are normalised below into the canonical bucket object so the
    iterator + builder code below only ever sees one shape.
    """
    model_config = ConfigDict(extra="ignore")

    dp_id: str | None = None
    client_id: str | None = None
    holdings: DematHoldingsBuckets = Field(default_factory=DematHoldingsBuckets)

    @field_validator("holdings", mode="before")
    @classmethod
    def _accept_legacy_flat_list(cls, v):
        """Normalise an incoming flat list of holdings into a bucket object."""
        if v is None:
            return {}
        if isinstance(v, list):
            buckets: dict[str, list] = {k: [] for k in _BUCKET_TO_ASSET}
            for h in v:
                # Tolerate dict or BaseModel-shaped items.
                instrument = None
                if isinstance(h, dict):
                    instrument = (h.get("instrument_type") or "equity").lower()
                else:
                    instrument = (getattr(h, "instrument_type", None) or "equity").lower()
                bucket_name = _LEGACY_TYPE_TO_BUCKET.get(instrument, "equities")
                buckets[bucket_name].append(h)
            return buckets
        return v   # dict or DematHoldingsBuckets — pass through

    def iter_lines(self) -> "list[tuple[str, DematHolding]]":
        """Yield (asset_class, holding) tuples across all five buckets."""
        out: list[tuple[str, DematHolding]] = []
        for bucket_name, asset_class in _BUCKET_TO_ASSET.items():
            for h in getattr(self.holdings, bucket_name):
                out.append((asset_class, h))
        return out


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
            for _asset_class, h in da.iter_lines():
                total += h.value
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
