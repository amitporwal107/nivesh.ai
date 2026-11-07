"""Slack incoming-webhook transport. The URL is a secret: it is never logged, repr'd, or put in a result."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


@dataclass(frozen=True)
class SendResult:
    ok: bool
    permanent: bool = False            # retrying cannot help (bad URL, revoked, channel gone)
    retry_after: Optional[float] = None
    reason: Optional[str] = None


class Transport(Protocol):
    def send(self, text: str, thread_ts: Optional[str] = None) -> SendResult: ...


def _urllib_post(url: str, payload: dict, timeout: float):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 — https URL from the owner's env
            return r.status, r.read(200).decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode("utf-8", "replace"), dict(e.headers)


class SlackWebhookTransport:
    """Posts one message to the channel the webhook was created for. A webhook gives back no message id, so replies
    in a thread are not possible with it (thread_ts is accepted and ignored)."""

    def __init__(self, url: str, http_post: Callable = _urllib_post, timeout: float = 10.0):
        self._url, self._post, self._timeout = url, http_post, timeout

    def __repr__(self) -> str:
        return "SlackWebhookTransport(url=***)"

    def send(self, text: str, thread_ts: Optional[str] = None) -> SendResult:
        try:
            status, body, headers = self._post(self._url, {"text": text}, self._timeout)
        except Exception as e:              # the exception text may hold the URL: keep only its type
            return SendResult(ok=False, reason=f"error:{type(e).__name__}")
        if status == 200:
            return SendResult(ok=True)
        slug = body.strip() if re.fullmatch(r"[a-z_]{3,40}", (body or "").strip()) else f"http_{status}"
        if status == 429:
            h = {k.lower(): v for k, v in (headers or {}).items()}
            try:
                wait = float(h.get("retry-after", "30"))
            except ValueError:
                wait = 30.0
            return SendResult(ok=False, retry_after=wait, reason="rate_limited")
        if status in (400, 403, 404, 410):
            return SendResult(ok=False, permanent=True, reason=slug)
        return SendResult(ok=False, reason=f"http_{status}")
