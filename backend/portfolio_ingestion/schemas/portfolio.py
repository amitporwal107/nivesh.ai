"""Response schema for ``POST /api/cas/sdk-callback`` + portfolio reads."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_class: str
    value: Decimal
    pct: Decimal


class TopHolding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    asset_class: str
    value: Decimal
    pct: Decimal


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_value: Decimal
    holdings_count: int
    allocation: list[AllocationItem]
    top_holdings: list[TopHolding]


class SdkCallbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    snapshot_id: UUID
    is_new: bool
    is_active: bool
    status: Literal["activated", "stored_inactive"]
    raw_pdf_available: bool = True   # False for cdsl_fetch OTP path
    portfolio: PortfolioResponse
