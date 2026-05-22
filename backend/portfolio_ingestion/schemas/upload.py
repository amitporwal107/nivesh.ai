"""Schemas for the signed-URL upload flow (T3.1/T3.2)."""
from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UploadInitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_type: str = Field(..., description="ECAS_CDSL | ECAS_NSDL | MF_CAMS | MF_KFIN")
    filename: str = Field(default="cas.pdf", max_length=256)


class UploadInitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: UUID
    upload_url: str
    object_key: str
    expires_at: dt.datetime
    stub: bool = False


class UploadCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    upload_id: UUID
    checksum: str | None = Field(
        default=None,
        description="SHA-256 of the uploaded PDF (hex). Optional in V1.",
    )
