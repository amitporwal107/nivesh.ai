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


async def _done(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return snapshot


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


SECTOR_LIST_CONCURRENCY = 5


async def _sector_members(sym: str, sectors: Dict[str, Any], memo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Which desk sector indices list `sym`: each sector index's latest list is read once (DaaS /v1/indices/{index}/constituents,
    nidp.index_constituents), five at a time, for this plan build only. A list that cannot be read is named in `unreadable`,
    never taken as "not a member". An empty list is `unreadable` too (no list is not a list without the stock).
    `memo` (name -> task) lets several plans built in one request read each index list once."""
    src = "DaaS /v1/indices/{index}/constituents (nidp.index_constituents, each sector index's latest list)"
    if not sectors["ok"]:
        return src_fail(f"the sector index names come from /v1/desk/sector-returns, which is unavailable: {sectors['error']}", src)
    names = [r["index"] for r in (sectors["data"] or {}).get("sectors") or [] if r.get("index")]
    if not names:
        return src_fail("/v1/desk/sector-returns listed no sector indices", src)
    gate = asyncio.Semaphore(SECTOR_LIST_CONCURRENCY)

    async def one(name: str):
        async with gate:
            return await daas_client.get_index_constituents(name)

    def task(n: str):
        if memo is None:
            return one(n)
        if n not in memo:
            memo[n] = asyncio.ensure_future(one(n))
        return memo[n]

    res = await asyncio.gather(*(task(n) for n in names), return_exceptions=True)
    member_of: List[str] = []
    unreadable: Dict[str, str] = {}
    for name, r in zip(names, res):
        if isinstance(r, BaseException):
            unreadable[name] = _why(r)
        elif not r:
            unreadable[name] = "no constituent list on record"
        elif sym in {str(x).upper() for x in r}:
            member_of.append(name)
    return src_ok({"symbol": sym, "member_of": member_of, "lists_read": len(names) - len(unreadable), "unreadable": unreadable}, src)


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


SCANNER_SOURCE = "positional engine watchlist (setup_rules buckets) + picks (positional_signals), picks win for plan levels"


def scanner_snapshot(sym: str, bucket: Optional[str], watch_item: Optional[Dict[str, Any]], pick: Optional[Dict[str, Any]],
                     as_of: Optional[str], version: Optional[str]) -> Dict[str, Any]:
    """The scanner's snapshot of one stock: its watchlist bucket and row, and its pick (a pick's stop replaces the watchlist row's
    stop, as in the desk's merged list). A pick that is not in the watchlist carries its stage; the cash rule reads that as the
    bucket it stands for and says so. Built the same way for a single plan and for the ideas route, so the two agree."""
    item = dict(watch_item) if watch_item else None
    data: Dict[str, Any] = {"bucket": bucket, "item": item}
    if pick:
        stop, entry = num(pick.get("stoploss")), num(pick.get("entry_price"))
        if item is None and (entry or stop):
            item = data["item"] = {"nse_symbol": sym, "trigger_price": entry}
        if item is not None and stop and stop > 0:
            item["stop_price"] = stop
        data["pick"] = {"stage": pick.get("stage"), "entry_price": entry, "stoploss": stop, "target_price": num(pick.get("target_price")),
                        "final_score": num(pick.get("final_score")), "signal_date": str(pick.get("signal_date"))[:10] if pick.get("signal_date") else None}
        if bucket is None:
            data["pick_stage"] = pick.get("stage")
    return src_ok(data, SCANNER_SOURCE, as_of, version)


async def _scanner_bucket(request: Request, sym: str) -> Dict[str, Any]:
    from routes import positional
    body, picks = await asyncio.gather(positional.get_watchlist(request, limit=300),
                                       positional.get_picks(request, date=None, min_score=0.55, stage=None, limit=300), return_exceptions=True)
    if isinstance(body, BaseException):
        raise body
    pick = None
    if not isinstance(picks, BaseException):
        pick = next((p for p in picks.get("picks") or [] if str(p.get("nse_symbol") or "").upper() == sym), None)
    else:
        logger.warning("strategy plan: picks read failed: %s", _why(picks))
    found, it = None, None
    for bucket, items in (body.get("buckets") or {}).items():
        for cand in items:
            if str(cand.get("nse_symbol") or "").upper() == sym:
                found, it = bucket, cand
                break
        if found:
            break
    return scanner_snapshot(sym, found, it, pick, body.get("as_of_date"), body.get("_classifier_version"))


async def _portfolio(user_id: str) -> Dict[str, Any]:
    from routes import portfolio_desk
    rows = await portfolio_desk._holdings(user_id)
    return src_ok(rows, "portfolio_enrichment.build_enriched_portfolio (holdings-enriched)", date.today().isoformat())


async def _shareholding(sym: str) -> Dict[str, Any]:
    body = await daas_client._get(f"/shareholding/{sym}", params={"limit": 24})
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        return src_fail(f"no shareholding rows for {sym}", "DaaS /v1/shareholding/{symbol} (nidp.shareholding_pattern)")
    newest = max((str(r.get("period_end"))[:10] for r in rows if r.get("period_end")), default=None)
    return src_ok(rows, "DaaS /v1/shareholding/{symbol} (nidp.shareholding_pattern: NSE_SHP first, screener_in)", newest)


async def _deals(sym: str, today: date) -> Dict[str, Any]:
    """Bulk and block deals of the stock in the last `deal_window_days` days, with the first day the stored deal history covers."""
    start = (today - timedelta(days=RULES["ownership"]["deal_window_days"])).isoformat()
    window = {"symbol": sym, "start": start, "end": today.isoformat(), "limit": 100}
    bulk, block = await asyncio.gather(daas_client._get("/flows/bulk-deals", params=window), daas_client._get("/flows/block-deals", params=window))
    rows: List[Dict[str, Any]] = []
    for kind, body in (("bulk", bulk), ("block", block)):
        got = (body or {}).get("data") if isinstance(body, dict) else None
        if not isinstance(got, list):
            return src_fail(f"the {kind}-deals route returned no list", "DaaS /v1/flows/bulk-deals, /block-deals")
        rows += [{**r, "kind": r.get("kind") or kind} for r in got]
    # The oldest stored bulk-deal day: the market-wide list is newest first, so its last row is the oldest.
    everything = await daas_client._get("/flows/bulk-deals", params={"start": "2000-01-01", "limit": 1})
    total = ((everything or {}).get("pagination") or {}).get("total") if isinstance(everything, dict) else None
    coverage = None
    if isinstance(total, int) and total > 0:
        oldest = await daas_client._get("/flows/bulk-deals", params={"start": "2000-01-01", "limit": 1, "offset": total - 1})
        first = ((oldest or {}).get("data") or [None])[0] if isinstance(oldest, dict) else None
        coverage = str((first or {}).get("as_of_date") or "")[:10] or None
    return src_ok({"window": {"from": start, "to": today.isoformat()}, "rows": rows, "coverage_from": coverage},
                  "DaaS /v1/flows/bulk-deals + /block-deals (NSE bulk and block deal files)", today.isoformat())


async def _broker_bid_ask(user_id: str, sym: str, chain: Dict[str, Any]) -> Dict[str, Any]:
    """Live bid/ask of the chain's ATM call and put from the user's own connected broker, when one can quote. Read only."""
    from deps import db
    from services.brokers import sessions
    from . import quotes
    if not chain["ok"]:
        return src_fail(f"no option chain to pick contracts from: {chain['error']}", "broker quote API")
    summary = (chain["data"] or {}).get("summary") or {}
    strike, expiry = summary.get("atm_strike"), summary.get("expiry")
    if strike is None or not expiry:
        return src_fail("the chain has no ATM strike or expiry", "broker quote API")
    contracts = [{"label": f"ATM {name} {strike:g}", "instrument_type": kind, "strike": float(strike), "expiry": str(expiry)[:10]} for name, kind in (("call", "CE"), ("put", "PE"))]
    accounts = await db.broker_accounts.find({"user_id": user_id, "native": True}, {"_id": 0}).to_list(length=20)
    isin = None
    if any(a.get("broker") in quotes.default_readers() and sessions.is_live(a) for a in accounts):
        px = await daas_client.get_stock_price_latest(sym)
        isin = (px or {}).get("isin") if isinstance(px, dict) else None
    return await quotes.read_option_bid_ask(accounts, sym, isin, contracts, load_token=sessions.load_token, is_live=sessions.is_live)


async def collect_snapshots(request: Request, user_id: str, inputs: Dict[str, Any], today: date, shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every source snapshot for one plan, read concurrently. Never raises.

    `shared` is for building several plans in one request (the ideas route): snapshots already read once for the whole request
    (`regime`, `sectors`, `portfolio`), this symbol's scanner snapshot (`scanner_bucket`: {symbol: snapshot}) and the sector index
    lists memo (`sector_lists`). Anything not in it is read as usual."""
    sym = inputs["underlying"]
    shared = shared or {}

    def pre(key: str, coro):
        if key == "scanner_bucket" and sym in (shared.get("scanner_bucket") or {}):
            coro.close()
            return _done(shared["scanner_bucket"][sym])
        if key in shared and key != "scanner_bucket":
            coro.close()
            return _done(shared[key])
        return _safe(key, coro)

    first = await asyncio.gather(
        pre("regime", _regime()), pre("sectors", _sectors()), _safe("indicators", _indicators(sym)), _safe("patterns", _patterns(sym)),
        _safe("scan_row", _scan_snapshot(sym)), _safe("features", _features(sym)), _safe("financials", _financials(sym)),
        _safe("announcements", _announcements(sym, today)), _safe("events", _events(sym, today)), _safe("corporate_actions", _corporate_actions(sym, today)),
        _safe("buildup", _buildup(sym)), _safe("futures", _futures(request, sym)), _safe("expiries", _expiries(request, sym)),
        _safe("calibration", _calibration(request, sym)), pre("scanner_bucket", _scanner_bucket(request, sym)), pre("portfolio", _portfolio(user_id)),
        _safe("shareholding", _shareholding(sym)), _safe("deals", _deals(sym, today)))
    keys = ["regime", "sectors", "indicators", "patterns", "scan_row", "features", "financials", "announcements", "events", "corporate_actions",
            "buildup", "futures", "expiries", "calibration", "scanner_bucket", "portfolio", "shareholding", "deals"]
    snaps: Dict[str, Any] = dict(zip(keys, first))
    snaps["sector_members"] = await _safe("sector_members", _sector_members(sym, snaps["sectors"], shared.get("sector_lists")))
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
    snaps["broker_quotes"] = await _safe("broker_quotes", _broker_bid_ask(user_id, sym, snaps["chain"]))
    return snaps


async def shared_for_ideas(user_id: str) -> Dict[str, Any]:
    """What every plan of one ideas request shares, read once: the market regime, the sector returns, the user's holdings, and the
    memo of sector index lists. Never raises."""
    regime, sectors, portfolio = await asyncio.gather(_safe("regime", _regime()), _safe("sectors", _sectors()), _safe("portfolio", _portfolio(user_id)))
    return {"regime": regime, "sectors": sectors, "portfolio": portfolio, "sector_lists": {}}


async def company_name(symbol: str) -> Optional[str]:
    """The company's name from the symbol master (DaaS /v1/symbols/search, exact symbol match), or None; the scanner sends symbols only."""
    try:
        res = await daas_client.search_symbols(symbol, limit=5)
    except Exception as e:  # noqa: BLE001 — a missing name never fails an idea
        logger.warning("company name for %s unavailable: %s", symbol, _why(e))
        return None
    for row in (res or {}).get("data") or []:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol and row.get("company_name"):
            return str(row["company_name"])
    return None
