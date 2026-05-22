"""HMAC-SHA256 signature verification for CASParser inbound-email webhooks (T3.3).

CASParser signs the raw request body with HMAC-SHA256 using the shared
``PI_WEBHOOK_SECRET`` and puts the hex digest in the ``X-Casparser-Signature``
header.  A 5-minute timestamp window prevents replay attacks.

Header format:
    X-Casparser-Signature: t=<unix_ts>,v1=<hex_digest>

    where hex_digest = HMAC-SHA256(secret, "<unix_ts>.<raw_body>")
"""
from __future__ import annotations

import hashlib
import hmac
import time


class WebhookSignatureError(ValueError):
    """Signature missing, malformed, expired, or wrong."""


def verify_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
    max_age_seconds: int = 300,
) -> None:
    """Raise :class:`WebhookSignatureError` if the signature is invalid.

    Args:
        body:             Raw (undecoded) request body bytes.
        signature_header: Value of the ``X-Casparser-Signature`` header.
        secret:           Shared webhook secret from ``PI_WEBHOOK_SECRET``.
        max_age_seconds:  Reject signatures older than this (default 5 min).
    """
    if not signature_header:
        raise WebhookSignatureError("missing X-Casparser-Signature header")

    # Parse "t=<ts>,v1=<hex>"
    parts: dict[str, str] = {}
    for part in signature_header.split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            parts[k.strip()] = v.strip()

    ts_str = parts.get("t")
    sig_v1 = parts.get("v1")
    if not ts_str or not sig_v1:
        raise WebhookSignatureError(
            "X-Casparser-Signature must contain t=<ts> and v1=<hex>"
        )

    try:
        ts = int(ts_str)
    except ValueError as e:
        raise WebhookSignatureError("timestamp is not an integer") from e

    age = int(time.time()) - ts
    if age > max_age_seconds:
        raise WebhookSignatureError(
            f"signature expired ({age}s old; max {max_age_seconds}s)"
        )
    if age < -30:
        raise WebhookSignatureError("signature timestamp is in the future")

    signed_payload = f"{ts}.".encode() + body
    mac = hmac.new(key=secret.encode(), msg=signed_payload, digestmod=hashlib.sha256)
    expected = mac.hexdigest()

    if not hmac.compare_digest(expected, sig_v1):
        raise WebhookSignatureError("signature mismatch")
