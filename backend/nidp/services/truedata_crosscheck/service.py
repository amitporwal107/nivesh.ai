"""TrueData's daily bhavcopy against NSE's own files in our warehouse (nidp.prices_eod, nidp.fno_bhavcopy).

READ ONLY: the warehouse is read inside a read-only transaction (Postgres refuses any write) and nothing is stored. It
answers one question per trading day: does TrueData carry the same prices as the exchange? On the trial (28 Oct 2026)
every equity row and every traded F&O contract matched; this check makes that a repeatable measurement before any
TrueData data is used.

What is compared, and why:
  * equity: series EQ, BE, BZ, SM, ST by symbol, on open, high, low, close and volume;
  * F&O: close and open interest, for contracts that TRADED on NSE that day. TrueData's bhavcopy lists traded
    contracts only, so an untraded NSE contract is "not expected", never "missing". The TrueData name is built from
    NSE's ticker, expiry, strike and type (nidp.shared.sources.truedata.option_symbol / future_symbol). Volume is not
    compared: the two sources count it in different units for F&O.
  * TrueData's continuous futures (NIFTY-I, -II, -III) and index rows are left out of the "extra" counts.
A past date is only comparable while no corporate action has happened since: TrueData adjusts past bhavcopies.

The market-data switch decides whether it runs: at `current` (backend/config/market_data_source.json, or forced with
MARKET_DATA_SOURCE_FORCE_CURRENT=1) it stops before reading the warehouse or calling TrueData, verdict SWITCHED_OFF.
`evaluation=True` (CLI --evaluation) is the one exception: a manual, read-only trial measurement, never scheduled.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td

EQUITY_SERIES = ("EQ", "BE", "BZ", "SM", "ST")
PRICE_TOLERANCE = 0.006          # rupees: both sources publish to the paisa
SAMPLE = 20
_CONTINUOUS = ("-I", "-II", "-III")
INT32_MAX = 2_147_483_647        # TrueData reports open interest above this as 0 (IDEA Nov future, 27/28 Oct 2026)


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _same_price(a: Any, b: Any) -> bool:
    fa, fb = _f(a), _f(b)
    return fa is not None and fb is not None and abs(fa - fb) < PRICE_TOLERANCE


def _same_int(a: Any, b: Any) -> bool:
    fa, fb = _f(a), _f(b)
    return int(fa or 0) == int(fb or 0)


def _is_index_row(row: Dict[str, Any]) -> bool:
    return str(row.get("symbolid") or "").startswith("2")     # TrueData index ids are 2xxxxxxxx (trial)


def compare_equity(nse_rows: Iterable[Dict[str, Any]], td_rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    td_rows = list(td_rows)
    securities = {str(r["symbol"]): r for r in td_rows if r.get("symbol") and not _is_index_row(r)}
    nse = [r for r in nse_rows if r.get("series") in EQUITY_SERIES]
    nse_symbols = {str(r["symbol"]) for r in nse}
    by_series: Dict[str, Dict[str, int]] = {}
    missing: List[str] = []
    mismatches: List[Dict[str, Any]] = []
    for r in nse:
        s = by_series.setdefault(r["series"], {"nse": 0, "found": 0, "close_equal": 0, "all_equal": 0})
        s["nse"] += 1
        t = securities.get(str(r["symbol"]))
        if t is None:
            missing.append(f"{r['symbol']} ({r['series']})")
            continue
        s["found"] += 1
        diffs = [f for f, a, b in (("open", r["open_price"], t.get("open")), ("high", r["high_price"], t.get("high")),
                                   ("low", r["low_price"], t.get("low")), ("close", r["close_price"], t.get("close")))
                 if not _same_price(a, b)]
        if not _same_int(r.get("volume"), t.get("volume")):
            diffs.append("volume")
        s["close_equal"] += "close" not in diffs
        s["all_equal"] += not diffs
        if diffs and len(mismatches) < SAMPLE:
            mismatches.append({"symbol": r["symbol"], "series": r["series"], "fields": diffs,
                               "nse_close": _f(r["close_price"]), "td_close": _f(t.get("close")),
                               "nse_volume": _f(r.get("volume")), "td_volume": _f(t.get("volume"))})
    total = sum(s["nse"] for s in by_series.values())
    equal = sum(s["all_equal"] for s in by_series.values())
    return {
        "nse_rows": total, "found": sum(s["found"] for s in by_series.values()), "all_equal": equal,
        "by_series": by_series, "missing_count": len(missing), "missing_sample": missing[:SAMPLE],
        "mismatch_count": total - equal - len(missing), "mismatch_sample": mismatches,
        "td_index_rows": sum(1 for r in td_rows if _is_index_row(r)),
        "td_extra_securities": sum(1 for s in securities if s not in nse_symbols),
        "verdict": "EQUAL" if total and equal == total else ("NO_NSE_DATA" if not total else "DIFFERENT"),
    }


def fno_td_symbol(r: Dict[str, Any]) -> Optional[str]:
    kind, expiry = r.get("instrument_type"), r.get("expiry_date")
    if not isinstance(expiry, date):
        return None
    if kind in ("IDO", "STO"):
        strike = _f(r.get("strike_price"))
        return None if strike is None else td.option_symbol(r["ticker_symbol"], expiry, strike, r["option_type"])
    if kind in ("IDF", "STF"):
        return td.future_symbol(r["ticker_symbol"], expiry)
    return None


def compare_fno(nse_rows: Iterable[Dict[str, Any]], td_rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    td_by = {str(r["symbol"]): r for r in td_rows if r.get("symbol")}
    out = {k: {"traded": 0, "found": 0, "close_equal": 0, "oi_equal": 0, "both_equal": 0} for k in ("options", "futures")}
    untraded = untraded_in_td = 0
    missing: List[str] = []
    mismatches: List[Dict[str, Any]] = []
    overflow: List[Dict[str, Any]] = []
    overflow_count = 0
    nse_keys = set()
    for r in nse_rows:
        key = fno_td_symbol(r)
        if key is None:
            continue
        nse_keys.add(key)
        if (_f(r.get("traded_volume")) or 0) <= 0:
            untraded += 1
            untraded_in_td += key in td_by
            continue
        part = out["options" if r["instrument_type"] in ("IDO", "STO") else "futures"]
        part["traded"] += 1
        t = td_by.get(key)
        if t is None:
            if len(missing) < SAMPLE:
                missing.append(key)
            continue
        part["found"] += 1
        close_ok = _same_price(r.get("close_price"), t.get("close"))
        oi_ok = _same_int(r.get("open_interest"), t.get("oi"))
        part["close_equal"] += close_ok
        part["oi_equal"] += oi_ok
        part["both_equal"] += close_ok and oi_ok
        if close_ok and oi_ok:
            continue
        row = {"contract": key, "nse_close": _f(r.get("close_price")), "td_close": _f(t.get("close")),
               "nse_settle": _f(r.get("settle_price")), "nse_oi": _f(r.get("open_interest")), "td_oi": _f(t.get("oi"))}
        if close_ok and (row["nse_oi"] or 0) > INT32_MAX and not row["td_oi"]:
            overflow_count += 1                                   # the known TrueData limit, not a new difference
            if len(overflow) < SAMPLE:
                overflow.append(row)
        elif len(mismatches) < SAMPLE:
            mismatches.append(row)
    traded = sum(p["traded"] for p in out.values())
    exact = all(p["found"] == p["traded"] == p["both_equal"] for p in out.values())
    return {
        **out, "untraded_not_expected": untraded, "untraded_present_in_td": untraded_in_td,
        "missing_count": traded - sum(p["found"] for p in out.values()), "missing_sample": missing,
        "mismatch_sample": mismatches, "oi_overflow_count": overflow_count, "oi_overflow_sample": overflow,
        "unexplained_mismatch_count": sum(p["found"] - p["both_equal"] for p in out.values()) - overflow_count,
        "td_extra": sum(1 for s in td_by if s not in nse_keys and not s.endswith(_CONTINUOUS)),
        "td_continuous_rows": sum(1 for s in td_by if s.endswith(_CONTINUOUS)),
        "verdict": "NO_NSE_DATA" if not traded else ("EQUAL" if exact else "DIFFERENT"),
    }


_EQ_SQL = ("SELECT symbol, series, open_price, high_price, low_price, close_price, volume FROM nidp.prices_eod "
           "WHERE as_of_date = $1 AND series = ANY($2::text[])")
_FO_SQL = ("SELECT instrument_type, ticker_symbol, expiry_date, strike_price, option_type, close_price, settle_price, "
           "open_interest, traded_volume FROM nidp.fno_bhavcopy WHERE as_of_date = $1")


async def read_nse(day: date) -> Dict[str, List[Dict[str, Any]]]:
    """NSE's rows for `day`, read in a READ ONLY transaction."""
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            eq = [dict(r) for r in await conn.fetch(_EQ_SQL, day, list(EQUITY_SERIES))]
            fo = [dict(r) for r in await conn.fetch(_FO_SQL, day)]
    return {"eq": eq, "fo": fo}


async def run(day: date, client: Optional[td.TrueDataClient] = None,
              nse: Optional[Dict[str, List[Dict[str, Any]]]] = None, *, evaluation: bool = False,
              switch=None) -> Dict[str, Any]:
    resolution = (switch or mds.resolve)()
    report: Dict[str, Any] = {"date": day.isoformat(), "source": td.PROVIDER_ID, "writes": "none (read only)",
                              "market_data_source": resolution.effective}
    if not mds.truedata_is_on(resolution):
        if not evaluation:
            return {**report, "verdict": "SWITCHED_OFF", "message": mds.truedata_off_message(resolution)}
        report["mode"] = f"evaluation (switch is {resolution.effective})"
    client = client or td.TrueDataClient()
    nse = nse if nse is not None else await read_nse(day)
    for segment, compare, rows in (("EQ", compare_equity, nse["eq"]), ("FO", compare_fno, nse["fo"])):
        key = "equity" if segment == "EQ" else "fno"
        try:
            td_rows = await asyncio.to_thread(client.bhavcopy, segment, day)
        except td.TrueDataError as e:
            report[key] = {"verdict": "TRUEDATA_ERROR", "error_code": e.code, "message": e.message,
                           "nse_rows": len(rows)}
            continue
        report[key] = {"td_rows": len(td_rows), **compare(rows, td_rows)}
    verdicts = {report[k]["verdict"] for k in ("equity", "fno")}
    report["verdict"] = "EQUAL" if verdicts == {"EQUAL"} else (
        "DIFFERENT" if "DIFFERENT" in verdicts else "NOT_COMPARED")
    return report


# ── Recording (NR-1 … NR-6 in test_reports/truedata_live_dq_TESTCASES.md) ─────────────────────────────────────────

INGESTER = "truedata_crosscheck"
RULES = ("truedata.call_failed", "truedata.eq_missing", "truedata.eq_mismatch", "truedata.fo_missing",
         "truedata.fo_mismatch", "truedata.fo_oi_overflow")


def _finding(rule: str, severity: str, failure_class: str, message: str, expected: Any = None, actual: Any = None,
             sample: Any = None) -> Dict[str, Any]:
    return {"rule_name": rule, "severity": severity, "failure_class": failure_class, "message": message,
            "expected": None if expected is None else str(expected), "actual": None if actual is None else str(actual),
            "sample_rows": sample}


def findings_from_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The report as DQ findings, using the validation vocabulary (severity INFO/WARN/ERROR/CRITICAL, failure class
    INFO/FIX/BLOCK). A TrueData call that failed on a day NSE has data BLOCKs TrueData for that date; a real price, volume
    or OI difference is an ERROR to fix with TrueData; the known OI limit is a WARN for information."""
    out: List[Dict[str, Any]] = []
    for key, seg in (("equity", "EQ"), ("fno", "FO")):
        part = report.get(key) or {}
        if part.get("verdict") == "TRUEDATA_ERROR" and part.get("nse_rows"):
            out.append(_finding("truedata.call_failed", "CRITICAL", "BLOCK",
                                f"TrueData {seg} bhavcopy failed: {part.get('error_code')} ({part.get('message')})",
                                expected=f"{part.get('nse_rows')} NSE rows compared", actual=part.get("error_code")))
    eq = report.get("equity") or {}
    if eq.get("missing_count"):
        out.append(_finding("truedata.eq_missing", "ERROR", "FIX",
                            f"{eq['missing_count']} NSE equity rows absent from TrueData's bhavcopy",
                            expected=eq.get("nse_rows"), actual=eq.get("found"), sample=eq.get("missing_sample")))
    if eq.get("mismatch_count"):
        out.append(_finding("truedata.eq_mismatch", "ERROR", "FIX",
                            f"{eq['mismatch_count']} equity rows differ from NSE (open/high/low/close/volume)",
                            expected=0, actual=eq["mismatch_count"], sample=eq.get("mismatch_sample")))
    fo = report.get("fno") or {}
    if fo.get("missing_count"):
        out.append(_finding("truedata.fo_missing", "ERROR", "FIX",
                            f"{fo['missing_count']} traded NSE contracts absent from TrueData's bhavcopy",
                            expected=0, actual=fo["missing_count"], sample=fo.get("missing_sample")))
    if fo.get("unexplained_mismatch_count"):
        out.append(_finding("truedata.fo_mismatch", "ERROR", "FIX",
                            f"{fo['unexplained_mismatch_count']} traded contracts differ from NSE on close or OI",
                            expected=0, actual=fo["unexplained_mismatch_count"], sample=fo.get("mismatch_sample")))
    if fo.get("oi_overflow_count"):
        out.append(_finding("truedata.fo_oi_overflow", "WARN", "INFO",
                            f"{fo['oi_overflow_count']} contract(s) with OI above {INT32_MAX:,} reported as 0 by TrueData "
                            "(known limit): use NSE's OI for these", expected="NSE OI", actual=0,
                            sample=fo.get("oi_overflow_sample")))
    return out


def validation_status(findings: List[Dict[str, Any]]) -> str:
    """Same rule as nidp.shared.validation.runner._classify_status."""
    if not findings:
        return "PASSED"
    if any(f["failure_class"] == "BLOCK" for f in findings):
        return "FAILED"
    if any(f["severity"] in ("ERROR", "CRITICAL") for f in findings):
        return "PARTIAL"
    return "PASSED"


def needs_alert(findings: List[Dict[str, Any]]) -> bool:
    return any(f["severity"] in ("ERROR", "CRITICAL") for f in findings)


def coverage_note(report: Dict[str, Any]) -> Dict[str, Any]:
    eq, fo = report.get("equity") or {}, report.get("fno") or {}
    return {"verdict": report.get("verdict"), "mode": report.get("mode"),
            "equity": {k: eq.get(k) for k in ("td_rows", "nse_rows", "found", "all_equal", "missing_count",
                                              "mismatch_count")},
            "fno": {"td_rows": fo.get("td_rows"), "options": fo.get("options"), "futures": fo.get("futures"),
                    "missing_count": fo.get("missing_count"), "oi_overflow_count": fo.get("oi_overflow_count"),
                    "unexplained_mismatch_count": fo.get("unexplained_mismatch_count")}}


def skip_reason(report: Dict[str, Any]) -> Optional[str]:
    if report.get("verdict") == "SWITCHED_OFF":
        return "SWITCHED_OFF"
    parts = [report.get("equity") or {}, report.get("fno") or {}]
    if all(p.get("verdict") == "NO_NSE_DATA" or (p.get("verdict") == "TRUEDATA_ERROR" and not p.get("nse_rows"))
           for p in parts):
        return "NO_NSE_DATA"
    return None


def alert_text(report: Dict[str, Any], findings: List[Dict[str, Any]]) -> tuple:
    subject = f"[NIDP] TrueData cross-check {report['date']}: {validation_status(findings)}"
    lines = [f"TrueData's bhavcopy vs NSE's files for {report['date']}.", ""]
    for f in findings:
        lines.append(f"- {f['severity']} {f['rule_name']}: {f['message']}")
    lines += ["", "Details: nidp.validation_findings (ingester truedata_crosscheck). TrueData does not serve users "
                  "while the switch is on current/shadow; at truedata, MARKET_DATA_SOURCE_FORCE_CURRENT=1 switches back."]
    return subject, "\n".join(lines)


async def record(report: Dict[str, Any], day: date, notifier=None) -> Dict[str, Any]:
    """Write the run to nidp.job_log (+ source_registry, so it shows on the feed status page), nidp.validation_runs and
    nidp.validation_findings; alert on ERROR/CRITICAL findings. Returns what was written."""
    import json as _json
    import uuid as _uuid
    from nidp.shared.storage.job_log import JobRun
    from nidp.shared.storage.pg import get_pool

    reason = skip_reason(report)
    async with JobRun(INGESTER, target_date=day) as run:
        if reason:
            msg = report.get("message") or "no NSE rows loaded for this date; nothing to compare"
            await run.finalize("SKIPPED", error_message=msg[:500], error_class=reason)
            return {"job_status": "SKIPPED", "reason": reason, "findings": [], "alerted": False}
        findings = findings_from_report(report)
        status = validation_status(findings)
        eq, fo = report.get("equity") or {}, report.get("fno") or {}
        run.rows_fetched = int(eq.get("td_rows") or 0) + int(fo.get("td_rows") or 0)
        run.metadata = coverage_note(report)
        validation_id = _uuid.uuid4()
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO nidp.validation_runs (validation_id, job_run_id, ingester, asset, target_date, "
                    "started_at, finished_at, status, rules_run, rules_failed, findings_count, notes) "
                    "VALUES ($1, $2, $3, $3, $4, NOW(), NOW(), $5, $6, $7, $8, $9)",
                    validation_id, run.run_id, INGESTER, day, status, len(RULES),
                    len({f["rule_name"] for f in findings}), len(findings),
                    _json.dumps(coverage_note(report), default=str))
                for f in findings:
                    await conn.execute(
                        "INSERT INTO nidp.validation_findings (finding_id, validation_id, job_run_id, ingester, "
                        "target_date, rule_name, severity, failure_class, message, expected, actual, sample_rows, "
                        "detected_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, NOW())",
                        _uuid.uuid4(), validation_id, run.run_id, INGESTER, day, f["rule_name"], f["severity"],
                        f["failure_class"], f["message"][:2000], f["expected"], f["actual"],
                        _json.dumps(f["sample_rows"], default=str) if f["sample_rows"] is not None else None)
        failed = any(f["failure_class"] == "BLOCK" for f in findings)
        await run.finalize("FAILED" if failed else "OK",
                           error_message=None if not failed else "TrueData call failed (see validation_findings)",
                           error_class="TRUEDATA_CALL_FAILED" if failed else None)
    alerted = False
    if needs_alert(findings):
        if notifier is None:
            from nidp.shared.notify import notify as notifier
        subject, body = alert_text(report, findings)
        try:
            alerted = bool(notifier(subject, body))
        except Exception as exc:                                                        # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("truedata cross-check alert not sent: %s", type(exc).__name__)
    return {"job_status": "FAILED" if failed else "OK", "validation_status": status, "findings": findings,
            "alerted": alerted, "validation_id": str(validation_id), "job_run_id": str(run.run_id)}
