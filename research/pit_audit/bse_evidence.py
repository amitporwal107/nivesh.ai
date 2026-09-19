"""BSE announcement evidence for AV-1 (AV-01, NSE-04): the only operator independent of NSE.

For each sample symbol: resolve the BSE scrip code by ISIN (one scrip-master request), then fetch the BSE "Result"
announcements for the audit window, DIRECT (BSE does not block this VM; no proxy). Every request is logged to the
`requests` archive, every payload stored as a sha256 artifact, every announcement row archived raw as `bse_announcements`.
Matching an announcement to an NSE filing happens in analyze.py, never here.

run: python3 bse_evidence.py [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, "/app/.claude/worktrees/paper-engine/backend")

import sample  # noqa: E402
from archive import Archive  # noqa: E402
from contracts import IST, iso  # noqa: E402
from nse_ground_truth import RequestLog, windows  # noqa: E402

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api"
SCRIP_MASTER = BSE_API + "/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
ANN = BSE_API + "/AnnSubCategoryGetData/w"
REF = "https://www.bseindia.com/"
WINDOW = (dt.date(2024, 10, 1), dt.date(2026, 9, 19))
WINDOW_DAYS = 92
PACE_S = 1.0


def ann_url(scrip: str, a: dt.date, b: dt.date, page: int) -> str:
    return ANN + "?" + urlencode({"pageno": page, "strCat": "Result", "strPrevDate": a.strftime("%Y%m%d"),
                                  "strToDate": b.strftime("%Y%m%d"), "strscrip": scrip, "strSearch": "P",
                                  "strType": "C", "subcategory": ""})


def sample_isins(nse: Archive, symbols: set[str]) -> dict:
    out: dict = {}
    for f in nse.read("filings"):
        if f["symbol"] in symbols and f.get("isin"):
            out.setdefault(f["symbol"], set()).add(f["isin"].strip().upper())
    return {s: sorted(v) for s, v in out.items()}


def _table(payload) -> list:
    if isinstance(payload, dict):
        for k in ("Table", "data", "Data"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return payload if isinstance(payload, list) else []


async def _get(log: RequestLog, arc: Archive, kind: str, url: str, extra=None):
    from nidp.shared.sources.bse_fetcher import fetch_bytes
    t0, body, status, err = time.time(), None, None, None
    try:
        body, status = await fetch_bytes(url, referer=REF)
    except Exception as e:  # recorded in the request log and the run summary, never swallowed
        err = f"{type(e).__name__}: {str(e)[:200]}"
    h = log.record(kind, url, False, status, body, t0, err, extra)
    if body is not None and status == 200:
        arc.store_artifact(body, ".json")
        try:
            return json.loads(body), h
        except (ValueError, UnicodeDecodeError) as e:
            arc.append("parse_errors", [{"url": url, "sha256": h, "error": str(e)[:200]}])
    return None, h


async def main(limit: int | None):
    nse = Archive("/app/research/pit_audit/nse")
    arc = Archive("/app/research/pit_audit/bse")
    m = json.load(open(sample.OUT))
    syms = sorted(set(m["symbols"]) | {a for v in m["aliases"].values() for a in v})
    isins = sample_isins(nse, set(syms))
    log = RequestLog(arc, "bse")
    master, _ = await _get(log, arc, "scrip_master", SCRIP_MASTER)
    by_isin, by_sym = {}, {}
    for r in _table(master):
        i = str(r.get("ISIN_NUMBER") or "").strip().upper()
        if i:
            by_isin.setdefault(i, []).append(r)
        by_sym.setdefault(str(r.get("scrip_id") or "").strip().upper(), []).append(r)
    resolution = []
    for s in syms:
        hits, method = [r for i in isins.get(s, []) for r in by_isin.get(i, [])], "ISIN_EXACT"
        if not hits:  # NSE legacy rows can carry a pre-split ISIN (ONGC INE213A01011 vs BSE INE213A01029): accept the
            # BSE row only when the SYMBOL matches AND (the issuer prefix matches, or NSE gave no ISIN at all)
            issuers = {i[:7] for i in isins.get(s, [])}
            hits = [r for r in by_sym.get(s, []) if not issuers or str(r.get("ISIN_NUMBER") or "")[:7].upper() in issuers]
            method = "SYMBOL+ISIN_ISSUER" if issuers else "SYMBOL_ONLY"
        codes = sorted({str(r.get("SCRIP_CD")) for r in hits})
        resolution.append({"symbol": s, "isins": isins.get(s, []), "bse_codes": codes,
                           "bse_isins": sorted({str(r.get("ISIN_NUMBER")) for r in hits}), "method": method if codes else None,
                           "status": "OK" if len(codes) == 1 else ("NOT_FOUND" if not codes else "AMBIGUOUS")})
    arc.append("scrip_resolution", resolution)
    done = {x["symbol"] for x in arc.read("bse_announcements")}
    todo = [r for r in resolution if r["status"] == "OK" and r["symbol"] not in done][: limit or None]
    wins = list(windows(*WINDOW, days=WINDOW_DAYS))
    print(f"bse budget (estimated): 1 master + {len(todo)} scrips x {len(wins)} windows x >=1 page "
          f"= >= {1 + len(todo) * len(wins)} direct requests; unresolved: "
          f"{[(r['symbol'], r['status']) for r in resolution if r['status'] != 'OK']}")
    for r in todo:
        code = r["bse_codes"][0]
        for a, b in wins:
            page = 1
            while page <= 10:
                url = ann_url(code, a, b, page)
                payload, h = await _get(log, arc, "announcements", url, {"symbol": r["symbol"], "scrip": code})
                rows = _table(payload)
                arc.append("bse_announcements", [{"symbol": r["symbol"], "scrip": code, "source_url": url,
                                                  "payload_sha256": h, "retrieved_at": iso(dt.datetime.now(IST)),
                                                  "raw_row": x} for x in rows if isinstance(x, dict)])
                await asyncio.sleep(PACE_S)
                total = None
                if isinstance(payload, dict) and isinstance(payload.get("Table1"), list) and payload["Table1"]:
                    total = payload["Table1"][0].get("ROWCNT")
                if not rows or total is None or page * 50 >= int(total):
                    break
                page += 1
        print(f"{r['symbol']:12s} {code} done; counts {log.counts}")
    print("bse counts:", log.counts)
    arc.append("run_summaries", [dict({"step": "bse", "finished_at": iso(dt.datetime.now(IST)),
                                       "scrips": len(todo), "windows": len(wins)}, **log.counts)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    asyncio.run(main(ap.parse_args().limit))
