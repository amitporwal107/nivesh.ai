"""The normalized adapter contract (docs/charting.md §32.4) and failure reason codes (§32.11).

Downstream code sees a `ProviderResult` or a `ProviderError`, never a provider's own response
format. An empty or partial response is a status with a reason code — it is never returned as an
ordinary success, so it cannot be read as zero, unchanged or a valid negative (§32.11).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PROVIDER_KITE = "kite"
PROVIDER_TRENDLYNE = "trendlyne"
PROVIDER_TRUEDATA = "truedata"

# Reason codes (§32.11). Deterministic: one failure class maps to exactly one code.
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
AUTH_EXPIRED = "AUTH_EXPIRED"
RATE_LIMITED = "RATE_LIMITED"
TOOL_SCHEMA_CHANGED = "TOOL_SCHEMA_CHANGED"
EMPTY_RESPONSE = "EMPTY_RESPONSE"
PARTIAL_RESPONSE = "PARTIAL_RESPONSE"
INVALID_PAYLOAD = "INVALID_PAYLOAD"
IDENTIFIER_NOT_RESOLVED = "IDENTIFIER_NOT_RESOLVED"
NOT_CONFIGURED = "NOT_CONFIGURED"
INVALID_REQUEST = "INVALID_REQUEST"
PROVIDER_ERROR = "PROVIDER_ERROR"          # the provider answered with an error we cannot classify

RETRYABLE = frozenset({PROVIDER_UNAVAILABLE, RATE_LIMITED})

# data_quality_status values
DQ_OK = "OK"
DQ_EMPTY = "EMPTY"
DQ_PARTIAL = "PARTIAL"
DQ_BLOCKED = "BLOCKED"

# Point-in-time status (§32.9). Trendlyne is PIT_UNVERIFIED by default (§32.6).
PIT_UNVERIFIED = "PIT_UNVERIFIED"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_request_id() -> str:
    return uuid.uuid4().hex


class ProviderError(Exception):
    """A provider call that produced no usable records. `raw_payload` is whatever the provider
    did return (may be None); it is logged, never shown to the caller."""

    def __init__(self, code: str, message: str, *, raw_payload: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = code in RETRYABLE
        self.raw_payload = raw_payload


@dataclass
class ProviderResult:
    provider_id: str
    provider_version: str
    request_id: str
    requested_at: datetime
    response_received_at: datetime
    instrument_identifier: Optional[str] = None
    source_timestamp: Optional[str] = None          # the provider's own data timestamp, if it gives one
    availability_timestamp: Optional[str] = None    # earliest time we can show the data was available
    raw_payload_reference: Optional[str] = None     # set by request_log.record
    normalized_records: List[Dict[str, Any]] = field(default_factory=list)
    data_quality_status: str = DQ_OK
    error_code: Optional[str] = None
    retryable: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)
    raw_payload: Any = None                         # kept for the log; excluded from to_dict

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "request_id": self.request_id,
            "requested_at": self.requested_at.isoformat(),
            "response_received_at": self.response_received_at.isoformat(),
            "source_timestamp": self.source_timestamp,
            "availability_timestamp": self.availability_timestamp,
            "instrument_identifier": self.instrument_identifier,
            "raw_payload_reference": self.raw_payload_reference,
            "normalized_records": self.normalized_records,
            "data_quality_status": self.data_quality_status,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "meta": self.meta,
        }
