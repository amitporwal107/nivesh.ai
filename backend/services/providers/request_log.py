"""Provider request/response log (docs/charting.md §32.10 `provider_requests` / `provider_responses`).

One request document and one response document per adapter call, success or failure, so a missing
value is always attributable (§32.11: "preserve the failed request and reason code"). The original
provider payload is kept beside the normalized record (§32.7 rule 5) and addressed by
`raw_payload_reference`.

No secret is ever written: adapters pass parameters, not URLs or tokens, and `redact` is applied to
every string on the way in as a second line of defence.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Optional

from .contract import ProviderError, ProviderResult, utcnow

MAX_PAYLOAD_BYTES = 8 * 1024 * 1024      # Mongo's document ceiling is 16 MB; stay well under it

_SECRET_PATTERNS = (
    re.compile(r"(token=)[^&\s\"']+", re.I),
    re.compile(r"(access_token[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_\-\.]+", re.I),
    re.compile(r"(authorization[\"']?\s*[:=]\s*[\"']?)[^\"'\n]+", re.I),
)


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(r"\1<redacted>", text)
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _payload_doc(raw_payload: Any) -> Dict[str, Any]:
    if raw_payload is None:
        return {"payload_json": None, "payload_sha256": None, "payload_bytes": 0, "payload_truncated": False}
    text = redact(json.dumps(raw_payload, default=str, sort_keys=True))
    size = len(text.encode())
    digest = hashlib.sha256(text.encode()).hexdigest()
    if size > MAX_PAYLOAD_BYTES:
        return {"payload_json": None, "payload_sha256": digest, "payload_bytes": size, "payload_truncated": True}
    return {"payload_json": text, "payload_sha256": digest, "payload_bytes": size, "payload_truncated": False}


async def record(db, *, operation: str, params: Dict[str, Any], user_id: Optional[str],
                 result: Optional[ProviderResult] = None, error: Optional[ProviderError] = None,
                 provider_id: Optional[str] = None, request_id: Optional[str] = None,
                 requested_at=None) -> str:
    """Persist one call. Exactly one of `result` / `error` is given. Returns the
    raw_payload_reference and, for a result, sets it on the result."""
    if (result is None) == (error is None):
        raise ValueError("record() needs exactly one of result / error")
    now = utcnow()
    rid = result.request_id if result else request_id
    reference = f"provider_responses/{rid}"
    await db.provider_requests.insert_one({
        "request_id": rid,
        "provider_id": result.provider_id if result else provider_id,
        "provider_version": result.provider_version if result else None,
        "operation": operation,
        "params": _clean(params),
        "user_id": user_id,
        "requested_at": result.requested_at if result else requested_at,
        "response_received_at": result.response_received_at if result else now,
        "status": result.data_quality_status if result else "ERROR",
        "error_code": result.error_code if result else error.code,
        "error_message": None if result else redact(error.message)[:500],
        "retryable": result.retryable if result else error.retryable,
        "record_count": len(result.normalized_records) if result else 0,
    })
    await db.provider_responses.insert_one({
        "request_id": rid,
        "received_at": result.response_received_at if result else now,
        **_payload_doc(result.raw_payload if result else error.raw_payload),
    })
    if result:
        result.raw_payload_reference = reference
    return reference
