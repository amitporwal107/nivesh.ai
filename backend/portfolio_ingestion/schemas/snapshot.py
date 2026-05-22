"""Pydantic schemas for the snapshot engine input/output."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HoldingRow(BaseModel):
    """A single row that will land in ``portfolio_ingestion.holdings``.

    Used as the input shape to ``snapshot_engine.activate``. The portfolio
    builder (T1.5) is responsible for producing these from raw parsed_data.
    """
    model_config = ConfigDict(extra="forbid")

    asset_class: str = Field(..., min_length=1, max_length=64)
    isin: str | None = Field(default=None, min_length=12, max_length=12)
    amfi_code: str | None = Field(default=None, max_length=10)
    folio: str | None = None
    scheme_code: str | None = None
    amc: str | None = None
    name: str = Field(..., min_length=1, max_length=512)
    quantity: Decimal
    value: Decimal
    source_trace: dict


class ActivationDecision(BaseModel):
    """What the engine did in response to one activation request."""
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    is_active: bool
    activated: bool                     # True if this call moved is_active false→true
    deactivated_snapshot_ids: list[UUID]  # snapshots this call flipped to false
    holdings_written: int
    reason: Literal[
        "no_current_active",
        "ecas_supersedes_mf",
        "newer_statement",
        "higher_method_priority",
        "stored_inactive_loses",
    ]


class ActivationRequest(BaseModel):
    """Caller's perspective. Holdings are already deduped by the builder."""
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    user_id: UUID
    pan_hash: str = Field(..., min_length=64, max_length=64)
    source_type: str
    method: str
    statement_from: dt.date
    statement_to: dt.date
    generated_at: dt.datetime
    total_value: Decimal | None = None
    holdings: list[HoldingRow]
