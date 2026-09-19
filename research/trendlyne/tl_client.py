"""Minimal Trendlyne MCP client (streamable HTTP, JSON-RPC 2.0) plus response parsers.

The server URL is the credential: it is read from TL_URL_FILE and never printed or logged.
Server limits (measured 2026-09-19): get_stock_parameter_values takes at most 10 stock codes and 50 parameters.
"""
import json
import os
import re
import time

import requests

TL_URL_FILE = os.environ.get("TL_URL_FILE", "/app/.trendy-line-mcp-server.url")
MAX_STOCKS, MAX_PARAMS = 10, 50


class TLError(RuntimeError):
    pass


class TLClient:
    def __init__(self, url_file: str = TL_URL_FILE, timeout: int = 180):
        self._url = open(url_file).read().strip()
        self._sid = None
        self._n = 0
        self._timeout = timeout
        self._s = requests.Session()
        self._initialized = False

    def _post(self, payload: dict, notify: bool = False) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-06-18"}
        if self._sid:
            h["Mcp-Session-Id"] = self._sid
        r = self._s.post(self._url, data=json.dumps(payload), headers=h, timeout=self._timeout)
        if r.headers.get("Mcp-Session-Id"):
            self._sid = r.headers["Mcp-Session-Id"]
        if notify:
            return {}
        if r.status_code >= 400:
            raise TLError(f"HTTP {r.status_code}: {r.text[:300]}")
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            msgs = [json.loads(l[5:].strip()) for l in r.text.splitlines() if l.startswith("data:") and l[5:].strip()]
            return next((m for m in msgs if m.get("id") == payload.get("id")), msgs[-1] if msgs else {})
        return r.json()

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._n += 1
        return self._post({"jsonrpc": "2.0", "id": self._n, "method": method, "params": params or {}})

    def _init(self):
        if not self._initialized:
            self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "nivesh-research", "version": "0.2"}})
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)
            self._initialized = True

    def call(self, tool: str, args: dict) -> str:
        """One MCP tools/call. Returns the text payload; raises TLError on a protocol error."""
        self._init()
        t0 = time.time()
        msg = self._rpc("tools/call", {"name": tool, "arguments": args})
        if "error" in msg:
            raise TLError(f"{tool}: {msg['error']}")
        res = msg.get("result", {})
        self.last_seconds = round(time.time() - t0, 2)
        return "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")


def parse_param_values(text: str) -> tuple[list[dict], dict[str, dict[str, str]]]:
    """get_stock_parameter_values payload -> (stocks in response order, {label: {stock key: value}}).
    Raises TLError with the server message when status != success."""
    d = json.loads(text)
    if d.get("status") != "success":
        raise TLError(d.get("message", text[:200]))
    head, _, rest = d["data"].partition("\n\n")
    stocks = [dict(zip(["tl_id", "name", "nse", "bse", "asof"], l.split("|"))) for l in head.splitlines() if "|" in l]
    vals = {}
    for blk in rest.split("---"):
        lines = [l for l in blk.strip().splitlines() if l.strip()]
        if lines:
            vals[lines[0]] = {l.split(":", 1)[0]: l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
    return stocks, vals


def parse_entities(text: str) -> list[dict]:
    """search_entities payload (a text table) -> list of row dicts."""
    rows, hdr = [], None
    for l in text.splitlines():
        if "|" not in l:
            continue
        cells = [x.strip() for x in l.strip().strip("|").split("|")]
        if cells[0] == "name":
            hdr = cells
        elif hdr and len(cells) == len(hdr) and not set(cells[0]) <= set("-: "):
            rows.append(dict(zip(hdr, cells)))
    return rows


UNRESOLVED_RE = re.compile(r"Could not resolve stock code\(s\):\s*([^\[]+)")


def unresolved_codes(message: str, sent: list[str]) -> list[str]:
    """Which of the codes we sent the server says it could not resolve (the message lists them with ';' or ', '
    separators and a trailing '.', and a sent code may itself contain ';', so match the sent codes, not the tokens)."""
    m = UNRESOLVED_RE.search(message or "")
    if not m:
        return []
    listed = m.group(1)
    return [c for c in sent if re.search(r"(?<![A-Za-z0-9&])" + re.escape(c) + r"(?![A-Za-z0-9&])", listed)]
