"""TrendlyneResearchAdapter — Trendlyne's MCP server as an enrichment provider (docs/charting.md §32.6).

Transport: MCP over streamable HTTP, spoken directly with httpx as JSON-RPC (the server is
stateless — no session id — and answers each POST with a one-message SSE body; verified against
Trendlyne-Financial-Server 3.1.1 on 2026-10-12). No MCP SDK dependency is needed for that.

Three properties of the live server shaped this module:
  * A failed lookup comes back as HTTP 200 with `isError: false` and a body that says
    `status: error ... [code:NNNN]`. That is mapped to a reason code here; it is never a success.
  * Payloads are text in three different shapes (JSON, pipe tables, indented sections). Each tool
    has its own parser, and a payload that does not match the recorded shape is INVALID_PAYLOAD /
    TOOL_SCHEMA_CHANGED — never a best-effort partial parse.
  * The server also exposes tools that MUTATE the account's watchlists. Only the read-only tools in
    READ_TOOLS can be called through this adapter.

Every record is PIT_UNVERIFIED: the server takes no as-of parameter and serves latest revisions, so
no value may be used at an earlier decision point (§32.6, §32.9). `publication_timestamp` is null
because the provider does not give one.

The MCP URL embeds the access token. It is read at call time, never logged, and scrubbed from any
error text.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from .contract import (
    AUTH_EXPIRED, DQ_EMPTY, DQ_OK, EMPTY_RESPONSE, IDENTIFIER_NOT_RESOLVED, INVALID_PAYLOAD, INVALID_REQUEST,
    NOT_CONFIGURED, PIT_UNVERIFIED, PROVIDER_ERROR, PROVIDER_TRENDLYNE, PROVIDER_UNAVAILABLE, RATE_LIMITED,
    TOOL_SCHEMA_CHANGED, ProviderError, ProviderResult, new_request_id, utcnow,
)
from .request_log import redact

SECRET_KEY = "TRENDLYNE_MCP_URL"
PROTOCOL_VERSION = "2025-03-26"
NORMALIZATION_VERSION = "trendlyne-mcp-v1"
TIMEOUT_SECONDS = 60.0
MAX_STOCK_CODES = 10          # live tool limit (the tool text says "at most 10 stock codes and 10 parameters")
MAX_PARAMETERS = 10

# Read-only tools this adapter may call -> the required arguments recorded from the live schema.
READ_TOOLS: Dict[str, Tuple[str, ...]] = {
    "search_entities": ("query",),
    "search_financial_parameters": ("query",),
    "get_stock_parameter_values": ("stock_codes", "parameters"),
    "get_overview_news_corp_events": ("stock_code", "type"),
    "get_document_search_results": ("query",),
}
ENTITY_COLUMNS = ["name", "nse_code", "bse_code", "isin", "entity_type", "sector", "industry"]
ENTITY_TYPES = ("stock", "etf", "index")
_PROVIDER_CODE = re.compile(r"\[code:(\d+)\]")
_DOC_HEADER = re.compile(r"^(\d+)\|([^|\n]+)\|([^|\n]*)\|(\d+)\|([^|\n]+)\|(\d{4}-\d{2}-\d{2})$", re.M)


def default_url() -> str:
    from helpers import secrets
    return (secrets.get(SECRET_KEY) or "").strip()


class TrendlyneResearchAdapter:
    provider_id = PROVIDER_TRENDLYNE

    def __init__(self, *, url_getter: Callable[[], str] = default_url,
                 transport: Optional[httpx.AsyncBaseTransport] = None, timeout: float = TIMEOUT_SECONDS):
        self._url_getter = url_getter
        self._transport = transport
        self._timeout = timeout
        self._tools: Optional[Dict[str, dict]] = None
        self.provider_version = "unknown"

    # ── MCP transport ────────────────────────────────────────────────────
    async def _rpc(self, client: httpx.AsyncClient, url: str, method: str, params: Optional[dict], rpc_id: int) -> dict:
        try:
            resp = await client.post(
                url, json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}},
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        except httpx.TimeoutException as e:
            raise ProviderError(PROVIDER_UNAVAILABLE, f"timeout calling Trendlyne MCP ({method})") from e
        except httpx.HTTPError as e:
            raise ProviderError(PROVIDER_UNAVAILABLE, f"{type(e).__name__} calling Trendlyne MCP ({method})") from e
        if resp.status_code in (401, 403):
            raise ProviderError(AUTH_EXPIRED, f"Trendlyne MCP refused the request (HTTP {resp.status_code})")
        if resp.status_code == 429:
            raise ProviderError(RATE_LIMITED, "Trendlyne MCP rate limit reached (HTTP 429)")
        if resp.status_code >= 500:
            raise ProviderError(PROVIDER_UNAVAILABLE, f"Trendlyne MCP HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderError(PROVIDER_ERROR, f"Trendlyne MCP HTTP {resp.status_code}")
        message = _decode_body(resp)
        if not isinstance(message, dict) or message.get("id") != rpc_id:
            raise ProviderError(INVALID_PAYLOAD, f"no JSON-RPC reply to {method}", raw_payload=redact(resp.text[:2000]))
        if "error" in message:
            err = message["error"] or {}
            raise ProviderError(PROVIDER_ERROR, redact(f"JSON-RPC error {err.get('code')}: {err.get('message')}")[:300],
                                raw_payload=message)
        return message.get("result") or {}

    async def _session(self, client: httpx.AsyncClient, url: str) -> Dict[str, dict]:
        """initialize + tools/list, once per adapter instance."""
        if self._tools is None:
            init = await self._rpc(client, url, "initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "nivesh-provider-adapter", "version": NORMALIZATION_VERSION}}, 1)
            info = init.get("serverInfo") or {}
            self.provider_version = f"{info.get('name', 'unknown')}/{info.get('version', 'unknown')}"
            listed = await self._rpc(client, url, "tools/list", None, 2)
            self._tools = {t["name"]: t for t in listed.get("tools", []) if isinstance(t, dict) and "name" in t}
        return self._tools

    def _check_schema(self, tools: Dict[str, dict], name: str, arguments: dict) -> None:
        tool = tools.get(name)
        if tool is None:
            raise ProviderError(TOOL_SCHEMA_CHANGED, f"tool {name} is no longer offered by the server")
        schema = tool.get("inputSchema") or {}
        required = tuple(sorted(schema.get("required") or []))
        if required != tuple(sorted(READ_TOOLS[name])):
            raise ProviderError(TOOL_SCHEMA_CHANGED, f"tool {name} now requires {list(required)}")
        unknown = set(arguments) - set(schema.get("properties") or {})
        if unknown:
            raise ProviderError(TOOL_SCHEMA_CHANGED, f"tool {name} no longer accepts {sorted(unknown)}")

    async def _call_tool(self, name: str, arguments: dict) -> Tuple[str, dict]:
        """Returns (payload text, raw tools/call result). Raises ProviderError on any failure."""
        if name not in READ_TOOLS:
            raise ProviderError(INVALID_REQUEST, f"tool {name} is not in the read-only allowlist")
        url = (self._url_getter() or "").strip()
        if not url:
            raise ProviderError(NOT_CONFIGURED, f"{SECRET_KEY} is not set")
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            tools = await self._session(client, url)
            self._check_schema(tools, name, arguments)
            result = await self._rpc(client, url, "tools/call", {"name": name, "arguments": arguments}, 3)
        texts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(texts)
        if result.get("isError"):
            raise ProviderError(PROVIDER_ERROR, redact(text)[:300] or "tool reported an error", raw_payload=result)
        if not text.strip():
            raise ProviderError(EMPTY_RESPONSE, f"tool {name} returned no content", raw_payload=result)
        _raise_if_body_error(text, result)
        return text, result

    def _result(self, request_id, requested_at, records: List[dict], raw: dict, *, identifier: Optional[str],
                tool: str, meta: Optional[dict] = None) -> ProviderResult:
        received_at = utcnow()
        return ProviderResult(
            provider_id=self.provider_id, provider_version=self.provider_version, request_id=request_id,
            requested_at=requested_at, response_received_at=received_at, instrument_identifier=identifier,
            availability_timestamp=received_at.isoformat(), normalized_records=records,
            data_quality_status=DQ_OK if records else DQ_EMPTY, error_code=None if records else EMPTY_RESPONSE,
            meta={"source_tool": tool, "normalization_version": NORMALIZATION_VERSION,
                  "pit_status": PIT_UNVERIFIED, **(meta or {})},
            raw_payload=raw,
        )

    def _pit(self, record: dict, *, tool: str, request_id: str, retrieved_at: str) -> dict:
        """Stamp the §32.6 research-use fields. Nothing from this provider is PIT-validated."""
        record.update({
            "publication_timestamp": None, "availability_timestamp": retrieved_at,
            "retrieval_timestamp": retrieved_at, "source_identifier": f"trendlyne-mcp:{tool}",
            "provider_response_id": request_id, "point_in_time_validated": False,
            "validation_status": PIT_UNVERIFIED,
        })
        return record

    # ── operations ───────────────────────────────────────────────────────
    async def search_entity(self, query: str, entity_type: str = "stock", limit: int = 10) -> ProviderResult:
        if entity_type not in ENTITY_TYPES:
            raise ProviderError(INVALID_REQUEST, f"unsupported entity_type: {entity_type}")
        request_id, requested_at = new_request_id(), utcnow()
        text, raw = await self._call_tool("search_entities", {"query": query, "entity_type": entity_type, "limit": limit})
        records = _parse_entities(text, raw)
        return self._result(request_id, requested_at, records, raw, identifier=query, tool="search_entities",
                            meta={"ambiguous": len(records) > 1})

    async def search_parameters(self, query: str) -> ProviderResult:
        request_id, requested_at = new_request_id(), utcnow()
        text, raw = await self._call_tool("search_financial_parameters", {"query": query})
        data = _json_body(text, raw).get("data")
        if not isinstance(data, list) or any(not isinstance(d, dict) or "parameter" not in d for d in data):
            raise ProviderError(INVALID_PAYLOAD, "parameter search payload is not a list of {parameter, helping_text}",
                                raw_payload=raw)
        records = [{"parameter": d["parameter"], "label": d.get("helping_text")} for d in data]
        return self._result(request_id, requested_at, records, raw, identifier=query, tool="search_financial_parameters")

    async def fetch_parameters(self, stock_codes: List[str], parameters: List[str]) -> ProviderResult:
        if not stock_codes or not parameters:
            raise ProviderError(INVALID_REQUEST, "stock_codes and parameters must both be non-empty")
        if len(stock_codes) > MAX_STOCK_CODES or len(parameters) > MAX_PARAMETERS:
            raise ProviderError(INVALID_REQUEST,
                                f"at most {MAX_STOCK_CODES} stock codes and {MAX_PARAMETERS} parameters per call")
        request_id, requested_at = new_request_id(), utcnow()
        tool = "get_stock_parameter_values"
        text, raw = await self._call_tool(tool, {"stock_codes": stock_codes, "parameters": parameters})
        data = _json_body(text, raw).get("data")
        if not isinstance(data, str):
            raise ProviderError(INVALID_PAYLOAD, "parameter values payload has no text `data`", raw_payload=raw)
        rows, missing = _parse_parameter_values(data, parameters, raw)
        retrieved_at = utcnow().isoformat()
        records = [self._pit(r, tool=tool, request_id=request_id, retrieved_at=retrieved_at) for r in rows]
        return self._result(request_id, requested_at, records, raw, identifier=",".join(stock_codes), tool=tool,
                            meta={"requested_parameters": parameters, "values_not_returned": missing})

    async def fetch_events(self, stock_code: str) -> ProviderResult:
        request_id, requested_at = new_request_id(), utcnow()
        tool = "get_overview_news_corp_events"
        text, raw = await self._call_tool(tool, {"stock_code": stock_code, "type": "events"})
        rows, sections = _parse_event_sections(text, raw)
        retrieved_at = utcnow().isoformat()
        records = [self._pit(r, tool=tool, request_id=request_id, retrieved_at=retrieved_at) for r in rows]
        return self._result(request_id, requested_at, records, raw, identifier=stock_code, tool=tool,
                            meta={"sections": sections})

    async def search_documents(self, query: str) -> ProviderResult:
        request_id, requested_at = new_request_id(), utcnow()
        tool = "get_document_search_results"
        text, raw = await self._call_tool(tool, {"query": query})
        markdown = _json_body(text, raw).get("markdown_data")
        if not isinstance(markdown, str):
            raise ProviderError(INVALID_PAYLOAD, "document search payload has no text `markdown_data`", raw_payload=raw)
        retrieved_at = utcnow().isoformat()
        records = [self._pit(r, tool=tool, request_id=request_id, retrieved_at=retrieved_at)
                   for r in _parse_documents(markdown, raw)]
        return self._result(request_id, requested_at, records, raw, identifier=query, tool=tool)

    async def health(self) -> Dict[str, Any]:
        """Reachability + schema check. Makes no tool call, so it spends no data quota."""
        url = (self._url_getter() or "").strip()
        if not url:
            return {"provider_id": self.provider_id, "configured": False, "reachable": False, "error_code": NOT_CONFIGURED}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                tools = await self._session(client, url)
            for name in READ_TOOLS:
                self._check_schema(tools, name, {})
        except ProviderError as e:
            return {"provider_id": self.provider_id, "configured": True, "reachable": e.code == TOOL_SCHEMA_CHANGED,
                    "error_code": e.code, "detail": e.message, "retryable": e.retryable}
        return {"provider_id": self.provider_id, "configured": True, "reachable": True, "error_code": None,
                "provider_version": self.provider_version, "tools_offered": len(tools)}


# ── payload decoding ─────────────────────────────────────────────────────
def _decode_body(resp: httpx.Response) -> Any:
    """A JSON-RPC message from either a JSON body or a one-message SSE body."""
    try:
        if "text/event-stream" in resp.headers.get("content-type", ""):
            messages = [json.loads(line[5:].strip()) for line in resp.text.splitlines() if line.startswith("data:")]
            return messages[-1] if messages else None
        return resp.json()
    except ValueError:
        return None


def _raise_if_body_error(text: str, raw: dict) -> None:
    """Trendlyne reports failures inside a 200/isError:false body, as JSON or as `status: error` text."""
    status = message = None
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            body = json.loads(stripped)
        except ValueError:
            body = None
        if isinstance(body, dict):
            status, message = body.get("status"), body.get("message")
    elif stripped.startswith("status:"):
        lines = stripped.splitlines()
        status = lines[0].split(":", 1)[1].strip()
        message = next((l.split(":", 1)[1].strip() for l in lines[1:] if l.startswith("message:")), None)
    if status != "error":
        return
    message = redact(str(message or "provider reported an error"))[:300]
    code = IDENTIFIER_NOT_RESOLVED if "could not resolve stock code" in message.lower() else \
        INVALID_REQUEST if _PROVIDER_CODE.search(message) and "invalid" in message.lower() else PROVIDER_ERROR
    raise ProviderError(code, message, raw_payload=raw)


def _json_body(text: str, raw: dict) -> dict:
    try:
        body = json.loads(text)
    except ValueError as e:
        raise ProviderError(INVALID_PAYLOAD, "payload is not JSON", raw_payload=raw) from e
    if not isinstance(body, dict):
        raise ProviderError(INVALID_PAYLOAD, "payload is not a JSON object", raw_payload=raw)
    return body


def _cell(value: str) -> Optional[str]:
    value = value.strip()
    return None if value in ("", "None", "null") else value


def _pipe_rows(lines: List[str]) -> List[List[str]]:
    """Split ` | `-delimited rows. A row may end with an empty cell (`a | b | `), whose trailing
    space is gone once the line has been stripped — so the delimiter is ` |` + (space or end)."""
    return [[c.strip() for c in re.split(r" \|(?: |$)", line)] for line in lines]


def _parse_entities(text: str, raw: dict) -> List[dict]:
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 3 or lines[0].strip() != "status: success" or lines[1].strip() != "data:":
        raise ProviderError(INVALID_PAYLOAD, "entity search payload does not start with status/data", raw_payload=raw)
    if lines[2].strip() == "[]":
        return []
    header = _pipe_rows([lines[2].strip()])[0]
    if header != ENTITY_COLUMNS:
        raise ProviderError(TOOL_SCHEMA_CHANGED, f"entity search columns are now {header}", raw_payload=raw)
    records = []
    for cells in _pipe_rows([l.strip() for l in lines[3:]]):
        if len(cells) != len(header):
            raise ProviderError(INVALID_PAYLOAD, "entity row does not match the header width", raw_payload=raw)
        records.append({col: _cell(val) for col, val in zip(header, cells)})
    return records


def _parse_parameter_values(data: str, parameters: List[str], raw: dict) -> Tuple[List[dict], List[dict]]:
    """`data` is: one `id|name|nse|bse|date` line per stock, a blank line, then one block per
    parameter (`label`, `CODE:value` lines) separated by `---`. Blocks carry the display label, not
    the token; the token is attached only when the block count equals the request (same order)."""
    head, _, body = data.partition("\n\n")
    stocks: Dict[str, dict] = {}
    for line in head.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            raise ProviderError(INVALID_PAYLOAD, "parameter values stock header is not 5 fields", raw_payload=raw)
        stocks[parts[2]] = {"provider_stock_id": parts[0], "name": parts[1], "nse_code": parts[2],
                            "bse_code": _cell(parts[3]), "as_of": parts[4]}
    blocks = [b.strip() for b in body.split("---") if b.strip()]
    if not stocks or not blocks:
        raise ProviderError(INVALID_PAYLOAD, "parameter values payload has no stock header or no value block",
                            raw_payload=raw)
    tokens = parameters if len(blocks) == len(parameters) else [None] * len(blocks)
    records, missing = [], []
    for token, block in zip(tokens, blocks):
        label, *value_lines = block.splitlines()
        seen = set()
        for line in value_lines:
            code, sep, value = line.partition(":")
            if not sep or code not in stocks:
                raise ProviderError(INVALID_PAYLOAD, "parameter value line is not `CODE:value` for a listed stock",
                                    raw_payload=raw)
            seen.add(code)
            stock = stocks[code]
            records.append({
                "instrument_identifier": code, "bse_code": stock["bse_code"], "name": stock["name"],
                "field_name": label.strip(), "parameter_token": token, "value": _number(value),
                "value_text": value.strip(), "as_of_period": stock["as_of"],
                "calculation_definition": None,
            })
        missing.extend({"instrument_identifier": c, "field_name": label.strip()} for c in stocks if c not in seen)
    return records, missing


def _number(value: str) -> Optional[float]:
    """A numeric value, or None when the provider gave no number. Never coerced to zero."""
    try:
        return float(value.strip().replace(",", ""))
    except ValueError:
        return None


def _parse_event_sections(text: str, raw: dict) -> Tuple[List[dict], Dict[str, dict]]:
    """Top-level `section:` blocks each hold a `tableData:` pipe table (or `[]`). One record per
    table row, tagged with its section. Header/descriptor blocks without tableData are skipped."""
    sections: Dict[str, List[str]] = {}
    current = None
    for line in text.splitlines():
        if line and not line.startswith(" ") and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1]
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    if not sections:
        raise ProviderError(INVALID_PAYLOAD, "events payload has no sections", raw_payload=raw)
    records, summary = [], {}
    for name, lines in sections.items():
        try:
            start = next(i for i, l in enumerate(lines) if l.strip() == "tableData:") + 1
        except StopIteration:
            continue
        indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
        table = []
        for line in lines[start:]:
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            if line.strip():
                table.append(line.strip())
        curtailed = any(l.strip() == "isCurtailed: True" for l in lines)
        if not table or table == ["[]"]:
            summary[name] = {"rows": 0, "curtailed": curtailed}
            continue
        header, *rows = _pipe_rows(table)
        for cells in rows:
            if len(cells) != len(header):
                raise ProviderError(INVALID_PAYLOAD, f"events section {name}: row does not match the header width",
                                    raw_payload=raw)
            records.append({"event_type": name, "as_of_period": None,
                            **{col: _cell(val) for col, val in zip(header, cells)}})
        summary[name] = {"rows": len(rows), "curtailed": curtailed}
    if not summary:
        raise ProviderError(TOOL_SCHEMA_CHANGED, "events payload has no tableData section", raw_payload=raw)
    return records, summary


def _parse_documents(markdown: str, raw: dict) -> List[dict]:
    """`markdown_data` is itself a JSON-encoded string. Decoded, it is a run of chunks, each opening
    with a `document_id|company|nse_code|stock_id|document_type|date` line; several chunks may come
    from one document."""
    body = markdown.strip()
    if body.startswith('"'):
        try:
            body = json.loads(body)
        except ValueError as e:
            raise ProviderError(INVALID_PAYLOAD, "document search markdown_data is not a decodable string",
                                raw_payload=raw) from e
        if not isinstance(body, str):
            raise ProviderError(INVALID_PAYLOAD, "document search markdown_data did not decode to text", raw_payload=raw)
        body = body.strip()
    if not body:
        return []
    heads = list(_DOC_HEADER.finditer(body))
    if not heads or heads[0].start() != 0:
        raise ProviderError(INVALID_PAYLOAD, "document search payload does not open with a chunk header", raw_payload=raw)
    records = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        records.append({
            "provider_record_id": m.group(1), "chunk_index": i, "name": m.group(2),
            "instrument_identifier": _cell(m.group(3)), "document_type": m.group(5),
            "as_of_period": m.group(6), "text": body[m.end():end].strip(),
        })
    return records
