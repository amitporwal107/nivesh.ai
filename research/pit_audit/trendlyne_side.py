"""Trendlyne side of the PIT audit (TL-01..06, OPS-04). Runs in the research venv (redis-backed TLCache).

Budget: at most 60 Trendlyne tools/call requests for the whole audit (measured from the Redis day counter at start;
the script stops before exceeding it). Every raw response is archived with server metadata and a tool-schema hash.
A successful response is NEVER read as historical PIT capability; it only documents what the server returns now.

run: /app/research/tpd3_forward/venv/bin/python trendlyne_side.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys

sys.path.insert(0, "/app/.claude/worktrees/paper-engine/research/trendlyne")
import tl_cache as T  # noqa: E402
from tl_client import TLClient, TLError  # noqa: E402

import sample  # noqa: E402
from archive import Archive  # noqa: E402
from contracts import IST, canonical_json, iso  # noqa: E402

BUDGET = 60
ROOT = "/app/research/pit_audit/trendlyne"
DATE_PARAM_QUERIES = ["result date", "announcement date", "filing date", "shareholding date"]
LAG_QUERIES = ["net profit quarter ago", "revenue quarter ago", "EPS quarter ago"]
EVENTS_STOCKS = 4


def prior_calls(arc: Archive) -> int:
    """Calls already spent by earlier audit runs (from their archived reports) - the 60 is audit-wide."""
    return sum(r.get("calls_used", 0) for r in arc.read("tl_report"))


class Budgeted:
    def __init__(self, cache: T.TLCache, arc: Archive, meta: dict):
        self.c, self.arc, self.meta = cache, arc, meta
        self.start = cache.calls_today() - prior_calls(arc)

    def used(self) -> int:
        return self.c.calls_today() - self.start

    def guard(self, need: int = 1):
        if self.used() + need > BUDGET:
            raise T.BudgetExceeded(f"audit Trendlyne budget {BUDGET} would be exceeded (used {self.used()})")

    def log(self, kind: str, args: dict, text: str | None, error: str | None = None):
        self.arc.append("tl_raw", [{"kind": kind, "args": args, "retrieved_at": iso(dt.datetime.now(IST)),
                                    "server": self.meta.get("server"), "tools_schema_sha256": self.meta.get("tools_schema_sha256"),
                                    "text": text, "error": error, "calls_used_so_far": self.used()}])


def server_metadata(client: TLClient) -> dict:
    init = client._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "nivesh-pit-audit", "version": "0.1"}})
    client._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)
    client._initialized = True
    tools = client._rpc("tools/list").get("result", {}).get("tools", [])
    date_args = {t["name"]: [k for k in t.get("inputSchema", {}).get("properties", {})
                             if any(w in k.lower() for w in ("date", "asof", "as_of", "period", "time"))] for t in tools}
    return {"server": init.get("result", {}).get("serverInfo"), "protocol": init.get("result", {}).get("protocolVersion"),
            "tools": [t["name"] for t in tools], "tools_schema_sha256": hashlib.sha256(canonical_json(tools).encode()).hexdigest(),
            "additional_properties": {t["name"]: t.get("inputSchema", {}).get("additionalProperties") for t in tools},
            "date_like_arguments": date_args, "tools_schema": tools}


def pick_lag_codes(results: dict) -> dict:
    """{metric: {k_quarters_ago: code}} from parameter-search results (helping_text parsed, never guessed)."""
    import re
    out = {"pat": {}, "revenue": {}, "eps": {}}
    for q, data in results.items():
        for d in data:
            h = d["helping_text"].lower()
            metric = "pat" if "net profit" in h else ("revenue" if "revenue" in h else ("eps" if "eps" in h or "earning per share" in h else None))
            if metric is None or "growth" in h or "ttm" in h or "annual" in h:
                continue
            m = re.search(r"(\d+)\s*qtr ago", h)
            k = int(m.group(1)) if m else (0 if ("qtr" in h and "ago" not in h) else None)
            if k is not None and d["parameter"] not in out[metric].setdefault(k, []):
                out[metric][k].append(d["parameter"])
    return out


def confirm_lag_nulls():
    """TL-02 follow-up: ONE uncached call re-asking lag codes for one stock outside the bulk path."""
    arc = Archive(ROOT)
    client = TLClient()
    meta = server_metadata(client)
    cache = T.TLCache(client, T.RedisStore())
    b = Budgeted(cache, arc, meta)
    b.guard()
    args = {"stock_codes": ["ITC"], "parameters": ["npq", "npqmq1", "npqmq7", "totalsrqmq1", "epsqmq1", "npqmy1"]}
    before = b.used()
    try:
        text, err = cache._call("get_stock_parameter_values", args), None
    except TLError as e:
        text, err = None, str(e)[:500]
    b.log("lag_null_confirm", args, text, err)
    report = {"step": "confirm_lag_nulls", "args": args, "response_head": (text or err or "")[:1500],
              "calls_used": b.used() - before, "audit_calls_total": b.used(), "budget": BUDGET,
              "finished_at": iso(dt.datetime.now(IST))}
    arc.append("tl_report", [report])
    print(json.dumps(report, indent=1))


def main():
    arc = Archive(ROOT)
    client = TLClient()
    meta = server_metadata(client)
    arc.append("tl_server", [dict(meta, retrieved_at=iso(dt.datetime.now(IST)))])
    cache = T.TLCache(client, T.RedisStore())
    b = Budgeted(cache, arc, meta)
    report = {"server": meta["server"], "tools_schema_sha256": meta["tools_schema_sha256"],
              "date_like_arguments": meta["date_like_arguments"], "additional_properties": meta["additional_properties"]}
    # TL-01: undocumented as-of argument (expected: rejected by the schema)
    b.guard()
    args = {"stock_codes": ["INFY"], "parameters": ["roea"], "as_of_date": "2025-06-30"}
    try:
        text = cache._call("get_stock_parameter_values", args)  # counted by the cache like every other call
        b.log("as_of_probe", args, text)
        rejected = bool(__import__("re").search(r"(?i)error|invalid|unexpected|not allowed|validation|additional", text or ""))
        report["as_of_probe"] = {"accepted": not rejected, "classified_from": "response text", "response_head": (text or "")[:300]}
    except TLError as e:
        b.log("as_of_probe", args, None, str(e)[:500])
        report["as_of_probe"] = {"accepted": False, "error": str(e)[:300]}
    # TL-01/TL-02: availability-date parameters and lag codes (cached lookups)
    found = {}
    for q in DATE_PARAM_QUERIES + LAG_QUERIES:
        b.guard()
        data = cache.search_parameters(q)
        found[q] = data
        b.log("param_search", {"query": q}, json.dumps(data))
    report["date_parameter_search"] = {q: found[q] for q in DATE_PARAM_QUERIES}
    lag = pick_lag_codes({q: found[q] for q in LAG_QUERIES})
    report["lag_codes"] = lag
    codes = sorted({c for m in lag.values() for cs in m.values() for c in cs})
    m = json.load(open(sample.OUT))
    syms = m["symbols"]
    need = -(-len(syms) // 10) * -(-len(codes) // 50)
    report["bulk_planned_calls"] = need
    b.guard(need)
    before = b.used()
    values = cache.get_params(syms, codes)
    b.log("bulk_lag_values", {"stock_codes": syms, "parameters": codes}, json.dumps(values))
    report["bulk_calls"] = b.used() - before
    # TL-06 ownership history + events (subset, budget permitting)
    own, ev = {}, {}
    try:
        _ownership_and_events(b, cache, syms, own, ev)
    except T.BudgetExceeded as e:
        report["budget_stop"] = str(e)
    report.update(ownership_stocks=len(own), events_stocks=len(ev), calls_used=b.used(), budget=BUDGET,
                  finished_at=iso(dt.datetime.now(IST)))
    arc.append("tl_report", [report])
    print(json.dumps({k: v for k, v in report.items() if k not in ("date_like_arguments", "additional_properties")}, indent=1)[:3000])


def _ownership_and_events(b, cache, syms, own, ev):
    for s in syms:
        b.guard()
        try:
            own[s] = cache.ownership(s, "shareholding")
            b.log("ownership", {"stock_code": s, "type": "shareholding"}, own[s])
        except TLError as e:
            b.log("ownership", {"stock_code": s, "type": "shareholding"}, None, str(e)[:300])
    for s in syms[:EVENTS_STOCKS]:
        b.guard()
        try:
            ev[s] = cache.overview(s, "events")
            b.log("events", {"stock_code": s, "type": "events"}, ev[s])
        except TLError as e:
            b.log("events", {"stock_code": s, "type": "events"}, None, str(e)[:300])


if __name__ == "__main__":
    confirm_lag_nulls() if sys.argv[1:] == ["confirm"] else main()
