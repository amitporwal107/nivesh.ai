"""Opportunity selection for the Strategy Builder's ideas (user requirement 2026-10-20: the builder picks trades from the AI
opportunities). The list is the one the Overview's "Top AI opportunities" card shows: the scanner's watchlist and picks merged by
symbol (frontend desk-data.ts `mergeSetups`, mirrored here), ranked by the scanner's score, then gated for eligibility.

Nothing is invented: an empty scanner is an empty list with the reason. Read-only.

Merge rules (mirrors mergeSetups): the watchlist row comes first (first bucket wins); a pick adds its plan (entry, stop, target,
risk : reward, holding days) and wins for those levels; the bucket keeps saying where the setup stands; the score is the pick's
final_score, else the watchlist's, x 100; the order is score descending, ties in insertion order (watchlist rows, then new picks).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

from services.positional_engine import setup_rules

from .evidence import num
from .rules import RULES

logger = logging.getLogger(__name__)

SCANNER_ROUTE_LIMIT = 30          # rows asked of each scanner route: the same as the desk (queries.ts SCANNER_ROUTE_LIMIT)
DEFAULT_LIMIT, MAX_LIMIT = 8, 15
BUCKETS = ("breakout_confirmed", "pre_breakout", "trend_continuation", "true_accumulation")   # desk-data.ts SETUP_BUCKETS order

SELECTION_RULE = ("The scanner's merged list (watchlist and picks, picks win for entry, stop and target), ranked by the scanner's score, "
                  "then only stocks that pass the scan snapshot's eligibility gates (a price and previous close, 20-session traded value, reference "
                  "data, series EQ or BE, not an ETF, price band at least 10%, not at its band limit, and traded value of at least "
                  f"Rs {setup_rules.LIQUIDITY['min_traded_value_cr']:g} crore a day); the top N that pass. When the snapshot cannot be read, "
                  "the scanner's own liquid flag (the same crore gate on its 20-session average) is the only gate. "
                  "Strong results add up to +5 points; weak results make no adjustment (tested on four past results seasons; confirmation pending).")

EXCLUSION_TEXT = {
    "missing_price": "no usable last close or previous close in the scan snapshot",
    "no_traded_value": "no 20-session traded value (fewer than 20 sessions)",
    "no_reference": "no exchange reference data (security reference) for the stock",
    "series": "not traded in series EQ or BE",
    "etf": "an ETF",
    "price_band": "price band below 10% (surveillance or thin trading)",
    "at_band_limit": "the last close sat at its price-band limit, so the move was not tradable",
    "illiquid": f"20-session traded value below Rs {setup_rules.LIQUIDITY['min_traded_value_cr']:g} crore a day",
}


def _price(v: Any) -> Optional[float]:
    x = num(v)
    return x if x is not None and x > 0 else None


def _nonneg(v: Any) -> Optional[float]:
    x = num(v)
    return x if x is not None and x >= 0 else None


def _status_of(bucket: Optional[str], stage: Optional[str]) -> str:
    if bucket == "breakout_confirmed":
        return "confirmed"
    if bucket in ("pre_breakout", "trend_continuation"):
        return "awaiting"
    if bucket == "true_accumulation":
        return "forming"
    s = (stage or "").upper()
    return "confirmed" if s == "BREAKOUT" else "awaiting" if s == "EARLY_BREAKOUT" else "forming"


def _rr(entry: Optional[float], stop: Optional[float], target: Optional[float]) -> Optional[float]:
    if entry is None or stop is None or target is None:
        return None
    risk, reward = entry - stop, target - entry
    return reward / risk if risk > 0 and reward > 0 else None


def _strs(v: Any) -> List[str]:
    """A list of strings from a JSON list or from a JSON-encoded string (the database returns a JSONB column as text in some environments)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return [v] if v.strip() else []
    return [str(x) for x in v if x] if isinstance(v, list) else []


def _days(v: Any) -> Optional[int]:
    x = num(v)
    return int(x) if x is not None and x == int(x) else None


def _text(v: Any) -> Optional[str]:
    return v.strip() if isinstance(v, str) and v.strip() else None


def merge_setups(watch_body: Optional[Dict[str, Any]], picks_body: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The merged, score-ranked setup list. Each setup keeps the raw watchlist item (`watch_item`) and pick row (`pick`) it came from."""
    by: Dict[str, Dict[str, Any]] = {}
    buckets = (watch_body or {}).get("buckets") or {}
    for bucket in BUCKETS:
        for it in buckets.get(bucket) or []:
            sym = str(it.get("nse_symbol") or "").strip().upper()
            if not sym or sym in by:
                continue
            score = num(it.get("final_score"))
            spark = it.get("spark_closes") or []
            by[sym] = {"symbol": sym, "bucket": bucket, "sector": _text(it.get("sector")), "stage": _text(it.get("stage")),
                       "status": _status_of(bucket, _text(it.get("stage"))), "score": score * 100 if score is not None else None,
                       "confidence": _text(it.get("confidence")), "close": _price(it.get("close_price")), "close_date": (watch_body or {}).get("as_of_date"),
                       "entry": _price(it.get("trigger_price")), "stop": _price(it.get("stop_price")), "target": None, "risk_reward": None,
                       "days_min": None, "days_max": None, "atr_pct": num(it.get("atr_pct")), "why": _text(it.get("why")), "reasons": [],
                       "in_watchlist": True, "in_picks": False, "avg_traded_cr": _nonneg(it.get("avg_traded_value_cr_20d")),
                       "spark_last": (num(spark[-1]) if spark else None), "spark_end": it.get("spark_end"), "watch_item": dict(it), "pick": None}
    for p in (picks_body or {}).get("picks") or []:
        sym = str(p.get("nse_symbol") or "").strip().upper()
        if not sym:
            continue
        have = by.get(sym)
        score = num(p.get("final_score"))
        spark = p.get("spark_closes") or []
        base = have or {"symbol": sym, "bucket": None, "sector": None, "stage": _text(p.get("stage")), "status": _status_of(None, _text(p.get("stage"))),
                        "score": score * 100 if score is not None else None, "confidence": _text(p.get("confidence")), "close": None, "close_date": None,
                        "entry": None, "stop": None, "target": None, "risk_reward": None, "days_min": None, "days_max": None, "atr_pct": None,
                        "why": None, "reasons": [], "in_watchlist": False, "in_picks": False, "avg_traded_cr": None,
                        "spark_last": None, "spark_end": None, "watch_item": None, "pick": None}
        entry = _price(p.get("entry_price")) or base["entry"]
        stop = _price(p.get("stoploss")) or base["stop"]
        target = _price(p.get("target_price")) or base["target"]
        merged = dict(base)
        merged.update(
            stage=base["stage"] or _text(p.get("stage")),
            score=score * 100 if score is not None else base["score"],
            confidence=_text(p.get("confidence")) or base["confidence"],
            entry=entry, stop=stop, target=target,
            risk_reward=num(p.get("risk_reward")) if num(p.get("risk_reward")) is not None else _rr(entry, stop, target),
            days_min=_days(p.get("timeframe_days_min")), days_max=_days(p.get("timeframe_days_max")),
            reasons=_strs(p.get("reasons")), in_picks=True,
            avg_traded_cr=base["avg_traded_cr"] if base["avg_traded_cr"] is not None else _nonneg(p.get("avg_traded_value_cr_20d")),
            spark_last=base["spark_last"] if base["spark_last"] is not None else (num(spark[-1]) if spark else None),
            spark_end=base["spark_end"] or p.get("spark_end"), pick=dict(p))
        by[sym] = merged
    for s in by.values():
        if s["risk_reward"] is None:
            s["risk_reward"] = _rr(s["entry"], s["stop"], s["target"])
    return sorted(by.values(), key=lambda s: -(s["score"] if s["score"] is not None else -1.0))


async def read_scanner(request: Request) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """(watchlist body, picks body, failures). The two routes the desk reads, called in-process with the caller's request."""
    from routes import positional
    w, p = await asyncio.gather(positional.get_watchlist(request, limit=SCANNER_ROUTE_LIMIT),
                                positional.get_picks(request, date=None, min_score=0.55, stage=None, limit=SCANNER_ROUTE_LIMIT),
                                return_exceptions=True)
    fails: List[str] = []
    out: List[Optional[Dict[str, Any]]] = []
    for name, r in (("watchlist", w), ("picks", p)):
        if isinstance(r, BaseException):
            if isinstance(r, asyncio.CancelledError):
                raise r
            logger.warning("ideas: scanner %s failed: %s", name, r)
            fails.append(f"{name}: {r.detail if isinstance(r, HTTPException) else type(r).__name__ + ': ' + str(r)[:120]}")
            out.append(None)
        else:
            out.append(r)
    return out[0], out[1], fails


async def _gate_rows() -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[str], Optional[str]]:
    """(symbol -> scan snapshot row, as_of, failure). The snapshot behind GET /api/positional/scan-universe (cached there)."""
    from routes import positional
    try:
        body = await positional._scan_snapshot()
    except Exception as e:  # noqa: BLE001 — falls back to the scanner's own liquid flag, and says so
        return None, None, e.detail if isinstance(e, HTTPException) else f"{type(e).__name__}: {str(e)[:120]}"
    rows = {str(r.get("symbol") or "").upper(): r for r in body.get("rows") or [] if isinstance(r, dict)}
    return rows, str(body.get("as_of"))[:10], None


def scanner_view(s: Dict[str, Any]) -> Dict[str, Any]:
    """The scanner facts of one setup, as the ideas response carries them."""
    close = s["close"] if s["close"] is not None else s["spark_last"]
    close_date = s["close_date"] if s["close"] is not None else s["spark_end"]
    reason = s["why"] or ("; ".join(s["reasons"][:2]) if s["reasons"] else None)
    return {"bucket": s["bucket"], "status": s["status"], "stage": s["stage"], "score": round(s["score"], 1) if s["score"] is not None else None,
            "confidence": s["confidence"], "close": close, "close_date": close_date, "entry": s["entry"], "stop": s["stop"], "target": s["target"],
            "risk_reward": round(s["risk_reward"], 2) if s["risk_reward"] is not None else None, "reason": reason,
            "reasons": s["reasons"], "horizon_days": s["days_max"], "horizon_days_min": s["days_min"],
            "liquidity_cr": s["avg_traded_cr"], "atr_pct": s["atr_pct"], "in_watchlist": s["in_watchlist"], "in_picks": s["in_picks"], "sector": s["sector"]}


def _hit_scans(entry: Optional[Dict[str, Any]], directions: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
    return [x for x in (entry or {}).get("scans") or [] if directions is None or x.get("direction") in directions]


def chartink_view(entry: Optional[Dict[str, Any]], index: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """{scans: [{id, name, direction}], count, fetched_at} for the enabled scans that listed the stock, or None when none did."""
    scans = _hit_scans(entry)
    return {"scans": scans, "count": len(scans), "fetched_at": index.get("fetched_at")} if scans else None


def chartink_setup(sym: str, ch: Dict[str, Any], row: Dict[str, Any], gate_as_of: Optional[str]) -> Dict[str, Any]:
    """A setup for a stock only Chartink listed: every scanner field is empty (nothing is borrowed from a scanner that does not list it)."""
    close = _price(row.get("close"))
    return {"symbol": sym, "bucket": None, "sector": _text(row.get("sector")), "stage": None, "status": None, "score": None, "confidence": None, "close": close,
            "close_date": gate_as_of if close is not None else None, "entry": None, "stop": None, "target": None, "risk_reward": None, "days_min": None, "days_max": None,
            "atr_pct": None, "why": None, "reasons": [], "in_watchlist": False, "in_picks": False, "avg_traded_cr": _nonneg(row.get("traded_value_cr_20d")),
            "spark_last": None, "spark_end": None, "watch_item": None, "pick": None, "source": "chartink", "chartink": ch,
            "fno_eligible": row.get("fno_eligible") if isinstance(row.get("fno_eligible"), bool) else None, "name": _text(row.get("name")) or _text(row.get("company_name"))}


def _tag_scanner_setup(s: Dict[str, Any], index: Dict[str, Any]) -> None:
    entry = index["symbols"].get(s["symbol"])
    s["chartink"] = chartink_view(entry, index)
    s["source"] = "both" if _hit_scans(entry, ("bullish",)) else "ai_scanner"


async def _add_chartink_only(out: Dict[str, Any], merged: List[Dict[str, Any]], rows: Optional[Dict[str, Dict[str, Any]]], gate_as_of: Optional[str],
                             index: Dict[str, Any], cap: int) -> None:
    """Append the stocks only Chartink listed (enabled bullish scans) after the scanner's: gated like scanner stocks, ranked by scan count, then traded value."""
    c = out["chartink"]
    listed = {m["symbol"] for m in merged}
    cands = [(sym, e) for sym, e in index["symbols"].items() if _hit_scans(e, ("bullish",)) and sym not in listed]
    c["considered"] = len(cands)
    if not cands or cap <= 0:
        return
    if rows is None:
        c["note"] = "The scan snapshot could not be read, so the eligibility gates cannot be tested for Chartink-only stocks and none is added."
        return

    def key(item):
        row = rows.get(item[0]) or {}
        return (-len(_hit_scans(item[1], ("bullish",))), -(_nonneg(row.get("traded_value_cr_20d")) or 0.0), item[0])

    floor = setup_rules.LIQUIDITY["min_traded_value_cr"]
    for sym, e in sorted(cands, key=key):
        if c["added"] >= cap:
            break
        row = rows.get(sym)
        if row is None:
            c["excluded"].append({"symbol": sym, "code": "not_in_snapshot", "reason": "not in the scan snapshot, so the eligibility gates cannot be tested (a Chartink-only stock has no scanner liquid flag to fall back on)"})
            continue
        code = setup_rules.exclusion(row)
        if code:
            c["excluded"].append({"symbol": sym, "code": code, "reason": EXCLUSION_TEXT.get(code, code)})
            continue
        ch = chartink_view(e, index)
        ch["bullish_scans"] = len(_hit_scans(e, ("bullish",)))
        setup = chartink_setup(sym, ch, row, gate_as_of)
        setup["close"] = setup["close"] if setup["close"] is not None else _price(e.get("close"))
        out["setups"].append(setup)
        c["added"] += 1
    out["selected"] = len(out["setups"])
    out["empty_reason"] = None if out["setups"] else out["empty_reason"]


def _chartink_block(index: Optional[Dict[str, Any]], cap: int) -> Optional[Dict[str, Any]]:
    if index is None:
        return None
    return {"included": True, "state": index.get("state"), "reason": index.get("reason"), "dashboard_id": index.get("dashboard_id"), "scan_date": index.get("scan_date"),
            "fetched_at": index.get("fetched_at"), "mode": index.get("mode"), "limit": cap, "considered": 0, "added": 0, "excluded": [], "note": None,
            "rule": RULES["chartink"]["ranking"], "gates": RULES["chartink"]["gates"]}


async def select_opportunities(request: Request, limit: int = DEFAULT_LIMIT, chartink: Optional[Dict[str, Any]] = None,
                               chartink_limit: int = RULES["chartink"]["limit_default"]) -> Dict[str, Any]:
    """The top `limit` eligible scanner setups, with what was considered and why any were excluded. Never raises on a source failure.

    `chartink` is the user's Chartink hit index (services/chartink_desk/hits.read_index) when Chartink is included: the scanner's ideas are tagged
    `source` ai_scanner or both, and up to `chartink_limit` stocks only Chartink listed follow them (source chartink). Without it nothing changes."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    cap = max(0, min(int(chartink_limit), RULES["chartink"]["limit_max"]))
    out = await _select_scanner(request, limit)
    merged, rows, rows_read = out.pop("_merged"), out.pop("_rows"), out.pop("_rows_read")
    block = out["chartink"] = _chartink_block(chartink, cap)
    if chartink is None:
        return out
    if block["state"] == "ok":
        for s in out["setups"]:
            _tag_scanner_setup(s, chartink)
        if rows is None and not rows_read:
            rows, gate_as_of, gate_fail = await _gate_rows()
            out["gate_as_of"] = out["gate_as_of"] or gate_as_of
            out["gate"] = out["gate"] or ("scan snapshot eligibility gates (as GET /api/positional/scan-universe)" if rows is not None else
                                          f"the scanner's own liquid flag (the scan snapshot could not be read: {gate_fail})")
        await _add_chartink_only(out, merged, rows, out["gate_as_of"], chartink, cap)
    else:
        for s in out["setups"]:
            s["chartink"], s["source"] = None, "ai_scanner"
    return out


async def eligible_setups(request: Request, limit: int) -> Dict[str, Any]:
    """The same scanner-only selection as select_opportunities without its MAX_LIMIT cap: every merged setup that passes the eligibility gates,
    up to `limit`, each with the scan snapshot's `fno_eligible` (True, False, or None when the snapshot has no row). For the regime-fit board's
    one-row-per-underlying stock F&O class, which has to look past the first 15 names to find enough F&O-listed ones. Never raises on a source failure."""
    out = await _select_scanner(request, max(1, int(limit)))
    for k in ("_merged", "_rows", "_rows_read"):
        out.pop(k, None)
    return out


async def _select_scanner(request: Request, limit: int) -> Dict[str, Any]:
    """The scanner-only selection (the behaviour before Chartink). Private keys for the Chartink step: _merged (the merged scanner list), _rows (the
    scan snapshot rows, None when not read or unreadable) and _rows_read (whether the snapshot read was attempted)."""
    watch, picks, fails = await read_scanner(request)
    out: Dict[str, Any] = {"source": "AI scanner (watchlist + picks), end of day", "rule": SELECTION_RULE, "limit": limit, "scan_date": None,
                           "watchlist_as_of": (watch or {}).get("as_of_date"), "watchlist_version": (watch or {}).get("_classifier_version"), "signal_date": (picks or {}).get("signal_date"),
                           "considered": 0, "selected": 0, "excluded": [], "setups": [], "empty_reason": None, "source_failures": fails,
                           "gate": None, "gate_as_of": None, "_merged": [], "_rows": None, "_rows_read": False,
                           # engine version, price basis, exceptions and data-quality status of the scan (scan_meta)
                           "scan_basis": (watch or {}).get("scan_basis") or (picks or {}).get("scan_basis")}
    out["scan_date"] = out["watchlist_as_of"] or out["signal_date"]
    if watch is None and picks is None:
        out["empty_reason"] = "The scanner could not be read (" + "; ".join(fails) + "): no opportunities are shown in its place."
        return out
    merged = merge_setups(watch, picks)
    out["_merged"] = merged
    out["considered"] = len(merged)
    if not merged:
        why = [m for m in ((watch or {}).get("_reason"), (picks or {}).get("message")) if m]
        out["empty_reason"] = "scanner tables empty: the scanner has no setups in its latest end-of-day run" + (f" ({'; '.join(why)})" if why else "") + "."
        return out
    rows, gate_as_of, gate_fail = await _gate_rows()
    out["gate"] = "scan snapshot eligibility gates (as GET /api/positional/scan-universe)" if rows is not None else \
        f"the scanner's own liquid flag (the scan snapshot could not be read: {gate_fail})"
    out["gate_as_of"] = gate_as_of
    out["_rows"], out["_rows_read"] = rows, True
    floor = setup_rules.LIQUIDITY["min_traded_value_cr"]
    for s in merged:
        if len(out["setups"]) >= limit:
            break
        code, why = None, None
        if rows is not None:
            row = rows.get(s["symbol"])
            if row is None:
                # not in the snapshot: the scanner's own liquid flag still decides
                if s["avg_traded_cr"] is None:
                    code, why = "not_in_snapshot", "not in the scan snapshot and the scanner sent no traded value, so the liquidity gate cannot be tested"
                elif s["avg_traded_cr"] < floor:
                    code, why = "illiquid", EXCLUSION_TEXT["illiquid"]
            else:
                code = setup_rules.exclusion(row)
                why = EXCLUSION_TEXT.get(code, code) if code else None
                s["fno_eligible"] = row.get("fno_eligible") if isinstance(row.get("fno_eligible"), bool) else None
                s["name"] = _text(row.get("name")) or _text(row.get("company_name"))
        else:
            if s["avg_traded_cr"] is None:
                code, why = "no_traded_value", EXCLUSION_TEXT["no_traded_value"]
            elif s["avg_traded_cr"] < floor:
                code, why = "illiquid", EXCLUSION_TEXT["illiquid"]
        if code:
            out["excluded"].append({"symbol": s["symbol"], "code": code, "reason": why})
        else:
            out["setups"].append(s)
    out["selected"] = len(out["setups"])
    if not out["setups"]:
        out["empty_reason"] = f"All {len(merged)} scanner setups failed the eligibility gates."
    return out
