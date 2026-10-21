"""Minimal MCP client for the Trendlyne financial server, plus a shared call budget.

The account's daily call allowance is shared with other NIDP jobs, so every caller goes through
one budget object rather than each service guessing. Two hard limits the server enforces, both
discovered by probing it: get_stock_parameter_values accepts at most 10 stock codes per call, and
get_ownership_deals_insider_sast takes exactly one.

Responses are JSON or SSE depending on the endpoint's mood, so both are parsed. The credential
lives in a git-ignored file and is never logged: only the host is ever printed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

# httpx logs every request at INFO as "HTTP Request: POST <full url>", and this endpoint carries
# its token in the QUERY STRING — so the default logging writes the credential into nidp's log
# files and into Loki. Silenced at import time, before any client is constructed. Observed leaking
# on 2026-10-22; do not remove without moving the token out of the URL first.
for _noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

CRED_FILE = pathlib.Path(
    os.environ.get("TRENDLYNE_MCP_FILE", "/home/deploy/nivesh.ai/.trendlyne-mcp"))

MAX_STOCKS_PER_PARAM_CALL = 10      # server-enforced
POLITE_GAP_S = 0.35

_HEADERS = {
    "User-Agent": "python-httpx/0.28",   # the WAF 403s curl's default agent
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class TrendlyneError(RuntimeError):
    pass


def resolve_url() -> str:
    """Credential file first, environment second.

    Deliberately the opposite of the usual precedence: the token is rotated by replacing the
    git-ignored file, while TRENDLYNE_MCP_URL is baked into /opt/nidp-staging/nidp.env and goes
    stale without anyone noticing. On 2026-10-22 the env var still held a revoked token and every
    call returned "user not subscribed" while a valid token sat in the file.
    """
    url = ""
    if CRED_FILE.exists():
        line = CRED_FILE.read_text().strip().splitlines()
        url = line[0].strip() if line else ""
    if not url:
        url = (os.environ.get("TRENDLYNE_MCP_URL") or "").strip()
    if not url:
        raise TrendlyneError(
            f"no Trendlyne MCP URL: create {CRED_FILE} or set TRENDLYNE_MCP_URL")
    return url


def safe_host(url: str) -> str:
    """The host alone — the token sits in the query string and must never be logged."""
    return urlsplit(url).netloc


class CallBudget:
    """Shared daily allowance. Refuses rather than silently exhausting another job's quota."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise TrendlyneError(
                f"Trendlyne call budget exhausted ({self.used}/{self.limit}); "
                "the allowance is shared with other NIDP jobs — raise --max-calls deliberately")
        self.used += 1

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def _parse(text: str) -> dict:
    t = text.lstrip()
    if t.startswith("{"):
        return json.loads(t)
    for line in text.splitlines():               # SSE framing
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise TrendlyneError(f"unparseable MCP response: {text[:200]!r}")


class TrendlyneClient:
    def __init__(self, budget: CallBudget, *, timeout: float = 120.0) -> None:
        self._url = resolve_url()
        self._budget = budget
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._rpc_id = 0

    async def __aenter__(self) -> "TrendlyneClient":
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True,
                                         headers=_HEADERS)
        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "nidp", "version": "1"}}, budgeted=False)
        logger.info("trendlyne: session open to %s (budget %d calls)",
                    safe_host(self._url), self._budget.remaining)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _rpc(self, method: str, params: Optional[dict], *, budgeted: bool = True) -> dict:
        assert self._client is not None
        if budgeted:
            self._budget.take()
        self._rpc_id += 1
        r = await self._client.post(self._url, json={
            "jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params or {}})
        r.raise_for_status()
        return _parse(r.text)

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Returns the tool's text payload. Raises TrendlyneError on an API-level error."""
        res = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if "error" in res:
            raise TrendlyneError(f"{name}: {str(res['error'])[:200]}")
        text = "".join(b.get("text", "")
                       for b in res.get("result", {}).get("content", []))
        # The server reports its own failures inside a 200 payload.
        stripped = text.lstrip()
        if stripped.startswith("{"):
            try:
                body = json.loads(stripped)
            except json.JSONDecodeError:
                body = None
            if isinstance(body, dict) and body.get("status") == "error":
                raise TrendlyneError(f"{name}: {body.get('message', '')[:200]}")
        await asyncio.sleep(POLITE_GAP_S)
        return text
