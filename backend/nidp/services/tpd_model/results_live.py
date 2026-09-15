"""Evening capture of the session's results filings straight from NSE, for the v4 results-print block.

The warehouse's results feed reaches most filings days to weeks after they are broadcast (measured 2026-09-15:
27 of 1,217 after-close filings in Aug-Sep 2026 were in staging by 22:30 the same evening), so the print block
would be empty live while complete in backfilled history. This module reads NSE's integrated-filing listing for T,
keeps filings broadcast in the print window (09:15, 20:30] IST, parses each XBRL for the quarter's revenue, profit
and EPS, and merges them into the financials frame only where no stamped warehouse row exists.

    python -m nidp.services.tpd_model.results_live --date YYYY-MM-DD --out <csv> --cache <dir>
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import logging
import re
import time as _time
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .event_gate import IST, cutoff_ist
from .results_print import FREEZE_CUTOFF, OPEN

logger = logging.getLogger(__name__)
LISTING = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&from_date={d}&to_date={d}"
           "&type=Integrated%20Filing-%20Financials&size=500")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
LIVE_COLUMNS = ["symbol", "period_end", "consolidated", "revenue_from_ops_cr", "pat_cr", "eps_basic", "broadcast_at"]


def parse_listing(payload) -> pd.DataFrame:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    out = []
    for r in rows:
        link = r.get("xbrl") or ""
        if not r.get("broadcast_Date") or not link.startswith("http") or link.endswith("/-"):
            continue
        out.append({"symbol": r["symbol"], "broadcast_at": pd.Timestamp(datetime.strptime(r["broadcast_Date"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)),
                    "period_end": pd.Timestamp(datetime.strptime(r["qe_Date"].title(), "%d-%b-%Y")) if r.get("qe_Date") else pd.NaT,
                    "consolidated": str(r.get("consolidated", "")).lower().startswith("consolidated"), "audited": r.get("audited"), "xbrl": link})
    return pd.DataFrame(out, columns=["symbol", "broadcast_at", "period_end", "consolidated", "audited", "xbrl"])


def in_print_window(listing: pd.DataFrame, T: date) -> pd.DataFrame:
    lo, hi = pd.Timestamp(cutoff_ist(T, at=OPEN)), pd.Timestamp(cutoff_ist(T, at=FREEZE_CUTOFF))
    return listing[(listing["broadcast_at"] > lo) & (listing["broadcast_at"] <= hi)]


def _tag(xml: str, tag: str, ctx: str = "OneD") -> Optional[str]:
    m = re.search(r"<[A-Za-z0-9\-]+:" + re.escape(tag) + r'(?=[\s>])[^>]*contextRef="' + ctx + r'"[^>]*>\s*([^<]+?)\s*<', xml)
    return m.group(1) if m else None


def _num(xml: str, *tags: str, scale: float = 1.0) -> float:
    for t in tags:
        v = _tag(xml, t)
        if v is not None:
            try:
                return float(v.replace(",", "")) / scale
            except ValueError:
                continue
    return float("nan")


def parse_xbrl(xml: str) -> Optional[dict]:
    if not xml or "<?xml" not in xml[:200]:
        return None
    end = _tag(xml, "DateOfEndOfReportingPeriod")
    if not end:
        return None
    nature = (_tag(xml, "NatureOfReportStandaloneConsolidated") or "").lower()
    return {"period_end": pd.Timestamp(end), "consolidated": nature.startswith("consolidated"),
            "revenue_from_ops_cr": _num(xml, "RevenueFromOperations", scale=1e7),
            "pat_cr": _num(xml, "ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations", scale=1e7),
            "eps_basic": _num(xml, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations")}


def merge_live(financials: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    """Append live rows for (symbol, period_end, consolidated) keys the warehouse has no stamped row for."""
    fin = financials.copy()
    fin["source_live"] = 0
    if live is None or live.empty:
        return fin
    stamped = fin[pd.to_datetime(fin["broadcast_at"], utc=True).notna()]
    have = set(zip(stamped["symbol"], pd.to_datetime(stamped["period_end"]), stamped["consolidated"].astype(bool)))
    add = live[[(s, pd.Timestamp(p), bool(c)) not in have for s, p, c in zip(live["symbol"], live["period_end"], live["consolidated"])]].copy()
    add["period_type"] = "quarterly"
    add["source_live"] = 1
    add["broadcast_at"] = pd.to_datetime(add["broadcast_at"], utc=True)
    fin["broadcast_at"] = pd.to_datetime(fin["broadcast_at"], utc=True)
    return pd.concat([fin, add], ignore_index=True, sort=False)


def _opener():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", UA), ("Accept", "application/json, text/xml, */*")]
    return op


def _get(op, url: str, referer: str, timeout: int = 60, tries: int = 3) -> bytes:
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Referer": referer})
            with op.open(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — retried, then raised
            last = e
            _time.sleep(2 * (k + 1))
    raise last


def capture(T: date, cache: Path, delay_s: float = 0.4) -> tuple[pd.DataFrame, dict]:
    """Live rows for filings broadcast in T's print window, plus capture statistics for the manifest."""
    op = _opener()
    try:
        op.open(urllib.request.Request("https://www.nseindia.com/"), timeout=20).read()
    except Exception:  # noqa: BLE001 — the API answers without the home-page cookie from this host
        pass
    listing = parse_listing(json.loads(_get(op, LISTING.format(d=T.strftime("%d-%m-%Y")), "https://www.nseindia.com/companies-listing/corporate-integrated-filing")))
    window = in_print_window(listing, T)
    cache.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for _, f in window.iterrows():
        path = cache / f["xbrl"].rsplit("/", 1)[-1]
        try:
            if not path.exists():
                path.write_bytes(_get(op, f["xbrl"], "https://www.nseindia.com/"))
                _time.sleep(delay_s)
            parsed = parse_xbrl(path.read_text(errors="replace"))
        except Exception as e:  # noqa: BLE001 — recorded per filing, the capture continues
            failed.append({"symbol": f["symbol"], "xbrl": f["xbrl"], "error": f"{type(e).__name__}: {e}"})
            continue
        if parsed is None or not np.isfinite(parsed["pat_cr"]):
            failed.append({"symbol": f["symbol"], "xbrl": f["xbrl"], "error": "unparseable or no profit figure"})
            continue
        rows.append({"symbol": f["symbol"], "broadcast_at": f["broadcast_at"], **parsed})
    live = pd.DataFrame(rows, columns=LIVE_COLUMNS)
    stats = {"date": str(T), "listed": int(len(listing)), "in_print_window": int(len(window)), "parsed": int(len(live)),
             "failed": failed, "symbols": int(live["symbol"].nunique()) if len(live) else 0}
    return live, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True); ap.add_argument("--out", type=Path, required=True); ap.add_argument("--cache", type=Path, required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    live, stats = capture(date.fromisoformat(a.date), a.cache)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    live.to_csv(a.out, index=False)
    Path(str(a.out) + ".stats.json").write_text(json.dumps(stats, indent=1, default=str))
    logger.info("results capture %s: listed %d, in window %d, parsed %d, failed %d", a.date, stats["listed"], stats["in_print_window"], stats["parsed"], len(stats["failed"]))
    return 0 if not stats["failed"] or stats["parsed"] else 7


if __name__ == "__main__":
    raise SystemExit(main())
