"""Trendlyne MCP client: JSON-RPC over HTTP, read-only tools, with a daily call budget.

The URL carries the account token in its query string, so it is read from the
environment (TRENDLYNE_MCP_URL) and never logged. The server sits behind a WAF
that answers 403 to curl's user agent and 200 to httpx's.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlsplit

import httpx

PROTOCOL_VERSION = "2025-03-26"
MAX_STOCKS = 10
MAX_PARAMETERS = 10
READ_TOOLS = ("search_entities", "get_stock_parameter_values")


class TrendlyneError(RuntimeError):
    """A call failed; the run cannot trust what it has for this request."""


class BudgetExhausted(TrendlyneError):
    """Today's call budget is spent, or the provider answered 429. Stop and resume tomorrow."""


def mcp_url() -> str:
    return os.environ.get("TRENDLYNE_MCP_URL", "").strip()


def redact(text: str, url: str) -> str:
    """`text` without the MCP URL, its host or anything from its query string. For any text
    that came back from the server (an error page can echo the address it was asked at)
    before it goes into an exception or a log."""
    if not url:
        return text
    parts = urlsplit(url)
    secrets = {url, parts.netloc, parts.query, *(v for _, v in parse_qsl(parts.query) if len(v) >= 4)}
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return text


class TrendlyneClient:
    """One MCP session. `on_call(tool, ok, detail)` is told about every tools/call
    so the caller can keep the ledger the budget is counted from."""

    def __init__(self, url: str, *, budget_left: int,
                 on_call: Optional[Callable[[str, bool, str], Any]] = None,
                 transport: Optional[httpx.BaseTransport] = None, timeout: float = 60.0) -> None:
        if not url:
            raise TrendlyneError("TRENDLYNE_MCP_URL is not set")
        self._url = url
        self.budget_left = budget_left
        self._on_call = on_call
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._id = 0
        self._ready = False

    def close(self) -> None:
        self._http.close()

    def redact(self, text: str) -> str:
        return redact(text, self._url)

    def _rpc(self, method: str, params: Optional[dict]) -> dict:
        self._id += 1
        try:
            resp = self._http.post(
                self._url, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}},
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        except httpx.HTTPError as exc:
            raise TrendlyneError(f"{type(exc).__name__} calling Trendlyne MCP ({method})") from None
        if resp.status_code == 429:
            raise BudgetExhausted("Trendlyne MCP rate limit reached (HTTP 429)")
        if resp.status_code != 200:
            raise TrendlyneError(f"Trendlyne MCP HTTP {resp.status_code} on {method}")
        try:
            if "text/event-stream" in resp.headers.get("content-type", ""):
                messages = [json.loads(line[5:].strip()) for line in resp.text.splitlines() if line.startswith("data:")]
                message = messages[-1] if messages else None
            else:
                message = resp.json()
        except ValueError:
            message = None
        if not isinstance(message, dict):
            raise TrendlyneError(f"no JSON-RPC reply to {method}")
        if "error" in message:
            err = message["error"] or {}
            raise TrendlyneError(f"JSON-RPC error {err.get('code')} on {method}")
        return message.get("result") or {}

    def call(self, tool: str, arguments: dict) -> str:
        """Text payload of one tools/call. Counts against the budget whether it works or not."""
        if tool not in READ_TOOLS:
            raise TrendlyneError(f"tool {tool} is not in the read-only allowlist")
        if self.budget_left <= 0:
            raise BudgetExhausted("today's Trendlyne call budget is spent")
        if not self._ready:
            self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": {"name": "nivesh-nidp-ingest", "version": "1"}})
            self._ready = True
        self.budget_left -= 1
        try:
            result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        except TrendlyneError as exc:
            self._log(tool, False, str(exc))
            raise
        text = "\n".join(c.get("text", "") for c in result.get("content") or []
                         if isinstance(c, dict) and c.get("type") == "text")
        if result.get("isError") or not text.strip():
            self._log(tool, False, "tool error" if result.get("isError") else "empty response")
            raise TrendlyneError(f"tool {tool} returned {'an error' if result.get('isError') else 'no content'}")
        self._log(tool, True, "")
        return text

    def _log(self, tool: str, ok: bool, detail: str) -> None:
        if self._on_call:
            self._on_call(tool, ok, detail[:200])
