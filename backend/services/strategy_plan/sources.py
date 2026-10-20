"""Reads the sources a strategy plan is built from, into source snapshots (see evidence.py). Read-only; nothing is written.

Each reader reuses an existing route function or the DaaS client (no HTTP loopback) and never raises: a failure becomes
`src_fail(reason, source)` and the plan labels the evidence unavailable. The route functions that need the caller's `request`
(F&O, positional) are called with it, so their own sign-in checks run.

Not exercised by the unit tests (they feed snapshots to the pure builder); see the test report for what was checked live.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

from services.copilot_tools import daas_client

from . import candidates as cd
from .evidence import num, src_fail, src_ok
from .rules import RULES

logger = logging.getLogger(__name__)


def _why(e: BaseException) -> str:
    if isinstance(e, HTTPException):
        return f"HTTP {e.status_code}: {e.detail}"
    return f"{type(e).__name__}: {str(e)[:160]}"


async def _safe(source: str, coro) -> Dict[str, Any]:
    try:
        return await coro
    except Exception as e:  # noqa: BLE001 — a failed source is evidence marked unavailable, never a failed plan
        logger.warning("strategy plan source %s failed: %s", source, _why(e))
        return src_fail(_why(e), source)


async def _regime() -> Dict[str, Any]:
    from routes import macro
    from services import macro_engine
    st = await macro_engine.latest_state()
    if not st:
        return src_fail("macro_state is empty", "macro_engine.classify_desk_regime")
    reg = await macro._desk_regime(st)
    return src_ok(reg, "macro_engine.classify_desk_regime (routes/macro._desk_regime)", reg.get("date"), (reg.get("rule") or {}).get("version") if isinstance(reg.get("rule"), dict) else None)


async def _sectors() -> Dict[str, Any]:
    status, body = await daas_client.get_raw("/desk/sector-returns")
    if status != 200 or not isinstance(body, dict):
        return src_fail(f"DaaS /desk/sector-returns answered HTTP {status}", "DaaS /v1/desk/sector-returns")
    return src_ok(body, "DaaS /v1/desk/sector-returns (NSE sectoral indices, end of day)", body.get("as_of"))


async def _indicators(sym: str) -> Dict[str, Any]:
    from routes import research_chart as rc
    out = await rc.live_indicators(sym, user={})
    return src_ok(out, out.get("source") or "nidp.prices_eod_adjusted via research_chart.live_indicators", out.get("as_of"), "research_chart indicators; HYPOTHETICAL_RULE " + str(rc.HYPOTHETICAL_RULE["version"]))


async def _patterns(sym: str) -> Dict[str, Any]:
    from routes import research_chart as rc
    out = await rc.live_patterns(sym, user={})
    return src_ok(out, "research.charting P0 pattern engine via research_chart.live_patterns", out.get("as_of"), (out.get("engine") or {}).get("engine_version"))


async def _scan_snapshot(sym: str) -> Dict[str, Any]:
    from routes import positional
    from services.positional_engine import setup_rules
    body = await positional._scan_snapshot()
    row = next((r for r in body["rows"] if str(r.get("symbol") or "").upper() == sym), None)
    if row is None:
        return src_fail(f"{sym} is not in the scan snapshot (no feature row)", "DaaS /v1/features/scan-snapshot")
    row = dict(row)
    row["exclusion"] = setup_rules.exclusion(row)
    row["eligible"] = row["exclusion"] is None
    row["liquidity_class"] = setup_rules.liquidity_class(row.get("traded_value_cr_20d"))
    row["risk_class"] = setup_rules.risk_class(row.get("atr_pct"))
    return src_ok(row, "DaaS /v1/features/scan-snapshot (nidp.stock_features_daily, prices_eod, security_reference_daily)", str(body["as_of"])[:10], setup_rules.RULES_VERSION)


async def _features(sym: str) -> Dict[str, Any]:
    row = await daas_client.get_stock_features_latest(sym)
    if not row:
        return src_fail(f"No feature row for {sym}", "DaaS /v1/features/stocks/{symbol}/latest")
    return src_ok(row, "DaaS /v1/features/stocks/{symbol}/latest (nidp.stock_features_daily)", str(row.get("as_of_date"))[:10])


async def _peers(sym: str, scan_row: Dict[str, Any]) -> Dict[str, Any]:
    """Same-industry peers: the industry comes from nidp.index_constituents (carried on the scan snapshot), each peer's valuation
    from its latest stock_features_daily row. At most max_peers_read peers, largest market cap first."""
    from routes import positional
    industry = scan_row.get("industry")
    if not industry:
        return src_fail(f"{sym} has no industry in nidp.index_constituents (sparse sector master)", "nidp.index_constituents industry")
    body = await positional._scan_snapshot()
    peers = [r for r in body["rows"] if r.get("industry") == industry and str(r.get("symbol") or "").upper() != sym]
    peers.sort(key=lambda r: -(num(r.get("market_cap_cr")) or 0.0))
    peers = peers[:RULES["valuation_peers"]["max_peers_read"]]
    feats = await asyncio.gather(*(daas_client.get_stock_features_latest(str(p["symbol"]).upper()) for p in peers), return_exceptions=True)
    rows: List[Dict[str, Any]] = []
    for p, f in zip(peers, feats):
        if isinstance(f, dict):
            rows.append({"symbol": p["symbol"], **{k: f.get(k) for k in ("pe_ttm", "pb", "roe_pct")}})
    return src_ok({"industry": industry, "peers": rows, "peers_in_industry": len(peers)},
                  "nidp.index_constituents industry (DaaS scan snapshot) + nidp.stock_features_daily peers (DaaS)", str(body["as_of"])[:10])


async def _financials(sym: str) -> Dict[str, Any]:
    from services.copilot_tools import company_financials
    res = await company_financials.get_company_financials(sym, limit=8)
    if not res.ok:
        return src_fail(res.error or res.summary, "services/copilot_tools/company_financials (DaaS quarterly financials)")
    latest = (res.rows or [{}])[0]
    return src_ok({**(res.data or {}), "rows": res.rows}, "DaaS quarterly financials via copilot_tools.company_financials (exchange filings)", str(latest.get("period_end") or "")[:10] or None)


async def _announcements(sym: str, today: date) -> Dict[str, Any]:
    since = (today - timedelta(days=RULES["catalysts"]["filings_days"])).isoformat()
    body = await daas_client._get("/announcements", params={"symbol": sym, "filed_from": since, "limit": 50})
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return src_ok([], "DaaS /v1/announcements (nidp.corporate_announcements)", since)
    return src_ok(rows, "DaaS /v1/announcements (nidp.corporate_announcements)", since)


async def _events(sym: str, today: date) -> Dict[str, Any]:
    body = await daas_client._get(f"/events/{sym}", params={"from_date": (today - timedelta(days=10)).isoformat(), "limit": 100})
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    return src_ok(rows if isinstance(rows, list) else [], "DaaS /v1/events/{symbol} (nidp.event_calendar)", today.isoformat())


async def _corporate_actions(sym: str, today: date) -> Dict[str, Any]:
    body = await daas_client._get(f"/corporate-actions/{sym}", params={"limit": 50})
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    return src_ok(rows if isinstance(rows, list) else [], "DaaS /v1/corporate-actions/{symbol} (nidp.corporate_actions)", today.isoformat())


async def _buildup(sym: str) -> Dict[str, Any]:
    from routes import fno
    body = await fno._daas("/desk/fno-buildup", {}, sym)
    rows = [r for r in (body.get("rows") or []) + (body.get("indices") or []) if str(r.get("symbol") or "").upper() == sym]
    if not rows:
        return src_fail(f"{sym} has no futures row on {body.get('as_of')}", "DaaS /v1/desk/fno-buildup")
    return src_ok(rows[0], "DaaS /v1/desk/fno-buildup (NSE F&O bhavcopy + bhavcopy cash close)", body.get("as_of"), "desk fno-buildup (setup_quality null: not validated)")


async def _futures(request: Request, sym: str) -> Dict[str, Any]:
    from routes import fno
    out = await fno.futures(request, symbol=sym)
    return src_ok(out, "NSE F&O bhavcopy via /api/fno/{symbol}/futures", out.get("as_of"))


async def _expiries(request: Request, sym: str) -> Dict[str, Any]:
    from routes import fno
    out = await fno.expiries(request, symbol=sym)
    return src_ok(out, "NSE F&O bhavcopy via /api/fno/{symbol}/expiries", out.get("as_of"))


async def _chain(request: Request, sym: str, expiry: str) -> Dict[str, Any]:
    from routes import fno
    out = await fno.chain(request, symbol=sym, expiry=date.fromisoformat(expiry), around=fno.DEFAULT_AROUND)
    return src_ok(out, "NSE F&O bhavcopy via /api/fno/{symbol}/chain (Black-76 IV/Greeks from end-of-day prices)", (out.get("summary") or {}).get("as_of"), "option_pricing Black-76")


async def _calibration(request: Request, sym: str) -> Dict[str, Any]:
    from routes import positional
    out = await positional.get_calibration(request, metric=None, horizon_days=None, symbol=sym)
    return src_ok(out, out.get("source") or "accumulation_calibration", ((out.get("sample") or {}).get("last_scan_date")), "accumulation backtest (in-sample, price-only)")


async def _scanner_bucket(request: Request, sym: str) -> Dict[str, Any]:
    from routes import positional
    body = await positional.get_watchlist(request, limit=300)
    for bucket, items in (body.get("buckets") or {}).items():
        for it in items:
            if str(it.get("nse_symbol") or "").upper() == sym:
                return src_ok({"bucket": bucket, "item": it}, "positional engine watchlist (setup_rules buckets)", body.get("as_of_date"), body.get("_classifier_version"))
    return src_ok({"bucket": None, "item": None}, "positional engine watchlist (setup_rules buckets)", body.get("as_of_date"), body.get("_classifier_version"))


async def _portfolio(user_id: str) -> Dict[str, Any]:
    from routes import portfolio_desk
    rows = await portfolio_desk._holdings(user_id)
    return src_ok(rows, "portfolio_enrichment.build_enriched_portfolio (holdings-enriched)", date.today().isoformat())


async def collect_snapshots(request: Request, user_id: str, inputs: Dict[str, Any], today: date) -> Dict[str, Any]:
    """Every source snapshot for one plan, read concurrently. Never raises."""
    sym = inputs["underlying"]
    first = await asyncio.gather(
        _safe("regime", _regime()), _safe("sectors", _sectors()), _safe("indicators", _indicators(sym)), _safe("patterns", _patterns(sym)),
        _safe("scan_row", _scan_snapshot(sym)), _safe("features", _features(sym)), _safe("financials", _financials(sym)),
        _safe("announcements", _announcements(sym, today)), _safe("events", _events(sym, today)), _safe("corporate_actions", _corporate_actions(sym, today)),
        _safe("buildup", _buildup(sym)), _safe("futures", _futures(request, sym)), _safe("expiries", _expiries(request, sym)),
        _safe("calibration", _calibration(request, sym)), _safe("scanner_bucket", _scanner_bucket(request, sym)), _safe("portfolio", _portfolio(user_id)))
    keys = ["regime", "sectors", "indicators", "patterns", "scan_row", "features", "financials", "announcements", "events", "corporate_actions",
            "buildup", "futures", "expiries", "calibration", "scanner_bucket", "portfolio"]
    snaps: Dict[str, Any] = dict(zip(keys, first))
    snaps["peers"] = await _safe("peers", _peers(sym, snaps["scan_row"]["data"] or {})) if snaps["scan_row"]["ok"] else src_fail("the scan snapshot row (industry) is unavailable", "nidp.index_constituents industry")
    # The chain is read for the expiry the rules pick from the listed ones (or the one the user asked for).
    ex = snaps["expiries"]
    if ex["ok"]:
        expiry, why = cd.pick_expiry((ex["data"] or {}).get("expiries") or [], inputs["horizon_days"], inputs.get("expiry"))
        if expiry:
            snaps["chain"] = await _safe("chain", _chain(request, sym, expiry))
            if snaps["chain"]["ok"]:
                snaps["chain"]["data"]["expiry_why"] = why
        else:
            snaps["chain"] = src_fail(why, "NSE F&O bhavcopy expiries")
    else:
        snaps["chain"] = src_fail(f"no expiry list: {ex['error']}", "NSE F&O bhavcopy expiries")
    return snaps
