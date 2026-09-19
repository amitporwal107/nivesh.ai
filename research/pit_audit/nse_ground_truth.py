"""NSE ground truth for the PIT audit (NSE-01..06, ARC-01..05, OPS-03, OPS-05).

Steps (run separately; the proxy is used ONLY by `listings`, per the owner's minimal-proxy decision):
  listings  : results listings (legacy Reg-33 until Mar-2025, Integrated Filing from Jan-2025) for ALL symbols in
              <=30-day broadcast windows + the shareholding master for each sample symbol. Via nse_fetcher (cookie
              prime, pacing, proxy). Stops proxy use after 2 consecutive 403/429.
              run: NSE_HTTPS_PROXY=http://10.160.0.5:3128 python3 nse_ground_truth.py listings
  documents : XBRL for the sample's filings in the 8 audit quarters, DIRECT from nsearchives via plain_http (no proxy),
              + one HEAD for Last-Modified; metric extraction (xbrl_extract / nse_shareholding.parser).
              run: python3 nse_ground_truth.py documents
Every request is logged to the `requests` archive; every raw payload is stored as a sha256-named artifact; records
keep the complete raw row. Nothing touches NIDP databases, archives or services.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time

BACKEND = "/app/.claude/worktrees/paper-engine/backend"
sys.path.insert(0, BACKEND)

import sample  # noqa: E402
import shp_extract as S  # noqa: E402
import xbrl_extract as X  # noqa: E402
from archive import Archive  # noqa: E402
from contracts import IST, filing_record, iso, metric_record, sha256_bytes  # noqa: E402
from session import filename_ts, filename_ts_precision, parse_nse_ts  # noqa: E402

N = "https://www.nseindia.com"
LEGACY = N + "/api/corporates-financial-results?index=equities&period=Quarterly&from_date={f}&to_date={t}"
LEGACY_REF = N + "/companies-listing/corporate-filings-financial-results"
INTEG = N + "/api/integrated-filing-results?index=equities&from_date={f}&to_date={t}&type=Integrated%20Filing-%20Financials&size=10000"
INTEG_REF = N + "/companies-listing/corporate-integrated-filing"
SHP = N + "/api/corporate-share-holdings-master?index=equities&symbol={s}"
SHP_REF = N + "/companies-listing/corporate-filings-shareholding-pattern"
LEGACY_RANGE = (dt.date(2024, 10, 1), dt.date(2025, 3, 31))
INTEG_RANGE = (dt.date(2025, 1, 1), dt.date(2026, 9, 19))
PROXY_PACE_S, DIRECT_PACE_S = 2.5, 0.4


def windows(start: dt.date, end: dt.date, days: int = 30):
    a = start
    while a <= end:
        b = min(a + dt.timedelta(days=days - 1), end)
        yield a, b
        a = b + dt.timedelta(days=1)


def _rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "records", "rows"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []


def _ts(v):
    t, _ = parse_nse_ts(v)
    return iso(t)


def _created(url):
    """Only an unambiguous (24-hour) filename time is stored; 12-hour names stay in raw_row (F-3)."""
    return iso(filename_ts(url)) if filename_ts_precision(url) == "second" else None


def has_document(url) -> bool:
    """NSE lists "<base>/-" when a filing has no XBRL: a listing fact, not a download."""
    u = str(url or "").strip()
    return u.lower().startswith("http") and not u.endswith("/-")


def _basis(v) -> str | None:
    v = (v or "").strip().lower()
    return {"consolidated": "CONSOLIDATED", "non-consolidated": "STANDALONE", "standalone": "STANDALONE"}.get(v)


def quarter_start(period_end: dt.date) -> dt.date:
    m = period_end.month - 2
    y = period_end.year + (m <= 0 and -1 or 0)
    return dt.date(y, m + 12 if m <= 0 else m, 1)


def legacy_record(r: dict, source_url: str, retrieved: str) -> dict:
    pe, _ = parse_nse_ts(r.get("toDate"))
    ps, _ = parse_nse_ts(r.get("fromDate"))
    # F-4: legacy `reInd` is NOT a revision flag - it is the results format (N Ind-AS, F NBFC, A non-Ind-AS/bank; it
    # tracks `bank`/`indAs` exactly), so this listing carries no revision indicator: order by broadcast instead.
    return filing_record(symbol=(r.get("symbol") or "").strip().upper(), isin=r.get("isin"), exchange="NSE",
                         listing="legacy_results", filing_id=str(r.get("seqNumber") or "") or None,
                         period_start=ps.date().isoformat() if ps else None, period_end=pe.date().isoformat() if pe else None,
                         filing_type="RESULTS", statement_type=f"{r.get('period')}/{r.get('cumulative')}",
                         consolidation_type=_basis(r.get("consolidated")), submitted_at=_ts(r.get("filingDate")),
                         broadcast_at=_ts(r.get("broadCastDate")), exchange_disseminated_at=_ts(r.get("exchdisstime")),
                         document_created_at=_created(r.get("xbrl")), revised_at=None,
                         revision_flag="UNKNOWN", retrieved_at=retrieved,
                         source_url=source_url, document_url=(r.get("xbrl") or None), raw_row=r)


def integrated_record(r: dict, source_url: str, retrieved: str) -> dict:
    pe, _ = parse_nse_ts(r.get("qe_Date"))
    sub = (r.get("type_Sub") or "").strip()
    return filing_record(symbol=(r.get("symbol") or "").strip().upper(), isin=None, exchange="NSE",
                         listing="integrated_results", filing_id=str(r.get("seq_Id") or "") or None,
                         period_start=quarter_start(pe.date()).isoformat() if pe else None,
                         period_end=pe.date().isoformat() if pe else None, filing_type="RESULTS",
                         statement_type=r.get("type"), consolidation_type=_basis(r.get("consolidated")),
                         submitted_at=_ts(r.get("creation_Date")), broadcast_at=_ts(r.get("broadcast_Date")),
                         exchange_disseminated_at=None, document_created_at=_created(r.get("xbrl")),
                         revised_at=_ts(r.get("revised_Date")),
                         revision_flag="ORIGINAL" if sub.lower() == "original" else ("REVISED" if sub else "UNKNOWN"),
                         retrieved_at=retrieved, source_url=source_url, document_url=(r.get("xbrl") or None), raw_row=r)


def shareholding_record(r: dict, source_url: str, retrieved: str) -> dict:
    pe, _ = parse_nse_ts(r.get("date"))
    rev = (r.get("revisedData") or "").strip().upper()
    return filing_record(symbol=(r.get("symbol") or "").strip().upper(), isin=r.get("isin"), exchange="NSE",
                         listing="shareholding_master", filing_id=str(r.get("recordId") or "") or None,
                         period_start=None, period_end=pe.date().isoformat() if pe else None, filing_type="SHAREHOLDING",
                         statement_type=r.get("desc"), consolidation_type=None,
                         submitted_at=_ts(r.get("submissionDate")), broadcast_at=_ts(r.get("broadcastDate")),
                         exchange_disseminated_at=None, document_created_at=None, revised_at=_ts(r.get("revisionDate")),
                         revision_flag={"N": "ORIGINAL", "Y": "REVISED"}.get(rev, "UNKNOWN"), retrieved_at=retrieved,
                         source_url=source_url, document_url=(r.get("xbrl") or None), raw_row=r)


class RequestLog:
    def __init__(self, arc: Archive, step: str):
        self.arc, self.step, self.consecutive_block, self.aborted = arc, step, 0, False
        self.counts = {"request_count": 0, "successful_count": 0, "failed_count": 0, "rate_limit_count": 0,
                       "proxy_request_count": 0, "direct_request_count": 0}

    def record(self, kind, url, via_proxy, status, body, t0, error=None, extra=None):
        self.counts["request_count"] += 1
        self.counts["proxy_request_count" if via_proxy else "direct_request_count"] += 1
        ok = status == 200 and body is not None
        self.counts["successful_count" if ok else "failed_count"] += 1
        # match the HTTP status only: a bare "403"/"429" substring also occurs inside URLs and attachment UUIDs
        blocked = status in (403, 429) or bool(error and re.search(r"\b(?:status|HTTP) (?:403|429)\b", error))
        if blocked:
            self.counts["rate_limit_count"] += 1
        self.consecutive_block = self.consecutive_block + 1 if blocked else 0
        if via_proxy and self.consecutive_block >= 2:
            self.aborted = True
        h = sha256_bytes(body) if body is not None else None
        self.arc.append("requests", [dict({"step": self.step, "kind": kind, "url": url, "via_proxy": via_proxy,
                                           "status": status, "bytes": len(body) if body is not None else None,
                                           "sha256": h, "elapsed_s": round(time.time() - t0, 3),
                                           "retrieved_at": iso(dt.datetime.now(IST)), "error": error,
                                           "note": "nse_fetcher/plain_http internal retries are not observable"},
                                          **(extra or {}))])
        return h


async def step_listings(arc: Archive):
    from nidp.shared.sources import nse_fetcher as F
    if not os.environ.get("NSE_HTTPS_PROXY"):
        raise SystemExit("listings needs NSE_HTTPS_PROXY (the NSE API blocks this VM's IP)")
    m = json.load(open(sample.OUT))
    log = RequestLog(arc, "listings")
    jobs = [("legacy_results", LEGACY.format(f=a.strftime("%d-%m-%Y"), t=b.strftime("%d-%m-%Y")), LEGACY_REF)
            for a, b in windows(*LEGACY_RANGE)]
    jobs += [("integrated_results", INTEG.format(f=a.strftime("%d-%m-%Y"), t=b.strftime("%d-%m-%Y")), INTEG_REF)
             for a, b in windows(*INTEG_RANGE)]
    syms = sorted(set(m["symbols"]) | {a for v in m["aliases"].values() for a in v})
    jobs += [("shareholding_master", SHP.format(s=s), SHP_REF) for s in syms]
    print(f"listings budget (estimated): {len(jobs)} proxy requests, paced >= {PROXY_PACE_S}s")
    try:
        for kind, url, ref in jobs:
            if log.aborted:
                arc.append("requests", [{"step": "listings", "kind": kind, "url": url, "status": "BLOCKED_NOT_SENT"}])
                continue
            t0 = time.time()
            body, status, err = None, None, None
            try:
                body, status = await F.fetch_bytes(url, referer=ref)
            except Exception as e:  # recorded, never swallowed: the failure is in the request log and the summary
                err = f"{type(e).__name__}: {str(e)[:200]}"
            h = log.record(kind, url, True, status, body, t0, err)
            if body is not None and status == 200:
                arc.store_artifact(body, ".json")
                try:
                    rows = _rows(json.loads(body))
                except (ValueError, UnicodeDecodeError) as e:
                    arc.append("parse_errors", [{"url": url, "sha256": h, "error": str(e)[:200]}])
                    rows = []
                retrieved = iso(dt.datetime.now(IST))
                build = {"legacy_results": legacy_record, "integrated_results": integrated_record,
                         "shareholding_master": shareholding_record}[kind]
                recs = [build(r, url, retrieved) for r in rows if isinstance(r, dict)]
                if kind == "integrated_results":
                    recs = [r for r in recs if r["statement_type"] == "Integrated Filing- Financials"]
                arc.append("filings", recs)
                print(f"{kind:20s} {url[-60:]} -> {len(recs)} records")
            else:
                print(f"{kind:20s} {url[-60:]} -> FAILED status={status} err={err}")
            await asyncio.sleep(PROXY_PACE_S)
    finally:
        await F.close()
    print("listings counts:", log.counts, "aborted:", log.aborted)
    arc.append("run_summaries", [dict({"step": "listings", "finished_at": iso(dt.datetime.now(IST)), "aborted": log.aborted,
                                       "planned": len(jobs)}, **log.counts)])


async def _head_last_modified(url: str):
    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.head(url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}) as r:
                lm = r.headers.get("Last-Modified")
                return r.status, lm
    except Exception as e:
        return None, f"ERROR {type(e).__name__}: {str(e)[:120]}"


def _http_date(s):
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).astimezone(IST)
    except (TypeError, ValueError):
        return None


def metric_records(f: dict, body: bytes, url: str, h: str, retrieved: str):
    """(metrics_status, reason, metric records) for one filing document, with the CURRENT extractor/parser version."""
    recs, reason = [], None
    if f["filing_type"] == "RESULTS":
        pe = dt.date.fromisoformat(f["period_end"])
        ps = dt.date.fromisoformat(f["period_start"]) if f.get("period_start") else quarter_start(pe)
        r = X.extract(body, ps, pe)
        status, reason = r["status"], r.get("reason")
        for row in r["rows"]:
            for metric in X.METRICS:
                recs.append(metric_record(symbol=f["symbol"], filing_id=f["filing_id"], period_start=ps.isoformat(),
                                          period_end=pe.isoformat(), context_role=f"CURRENT:{row['context']}",
                                          metric_name=metric, metric_value=row.get(metric),
                                          unit="INR crore" if metric in X.MONETARY else "INR per share",
                                          consolidation_type=row.get("basis"), document_url=url, document_sha256=h,
                                          retrieved_at=retrieved))
        return status, reason, recs
    r = S.extract(body)                     # audit-side SHP reader (DEF-8 / DEF-9 in the NIDP parser)
    status, reason = r["status"], r.get("reason")
    if r["status"] in ("OK", "UNRESOLVED"):
        for metric, v in r["values"].items():
            recs.append(metric_record(symbol=f["symbol"], filing_id=f["filing_id"], period_start=None,
                                      period_end=f["period_end"], context_role=f"SHAREHOLDING:{r['format']}",
                                      metric_name=metric, metric_value=v if r["status"] == "OK" else None,
                                      unit="percent of shares", consolidation_type=None, document_url=url,
                                      document_sha256=h, retrieved_at=retrieved))
    return status, reason, recs


def step_reextract(arc: Archive):
    """ARC-05: recompute every document's metrics from its stored artifact with the current extractor (no network).
    New records carry the new parser_version; nothing is overwritten - analysis reads the latest version per document."""
    from contracts import PARSER_VERSION
    fil = {}
    for f in arc.read("filings"):
        if f.get("document_url"):
            fil.setdefault(f["document_url"], f)
    docs = {d["document_url"]: d for d in arc.read("documents") if d.get("status") == 200 and d.get("sha256")}
    counts, out = {"documents": 0, "records": 0, "missing_artifact": 0}, []
    for url, d in sorted(docs.items()):
        path = arc.artifact_path(d["sha256"], ".xml")
        if not os.path.exists(path):
            counts["missing_artifact"] += 1
            continue
        with open(path, "rb") as fh:
            body = fh.read()
        if sha256_bytes(body) != d["sha256"]:
            raise RuntimeError(f"artifact {d['sha256']} does not match its hash")
        status, reason, recs = metric_records(fil[url], body, url, d["sha256"], d["retrieved_at"])
        arc.append("metrics", recs)
        out.append({"document_url": url, "metrics_status": status, "metrics_reason": reason, "parser_version": PARSER_VERSION})
        counts["documents"] += 1
        counts["records"] += len(recs)
    arc.append("reextractions", out)
    arc.append("run_summaries", [dict({"step": "reextract", "parser_version": PARSER_VERSION,
                                       "finished_at": iso(dt.datetime.now(IST))}, **counts)])
    print("reextract:", counts, PARSER_VERSION)


async def step_documents(arc: Archive, limit: int | None = None):
    from nidp.shared.sources import plain_http
    if os.environ.get("NSE_HTTPS_PROXY"):
        raise SystemExit("documents must run WITHOUT NSE_HTTPS_PROXY (downloads go direct)")
    m = json.load(open(sample.OUT))
    want = set(m["symbols"]) | {a for v in m["aliases"].values() for a in v}
    q_lo, q_hi = m["quarters"][0], m["quarters"][-1]
    seen_docs = {r["document_url"] for r in arc.read("documents")}
    filings = [f for f in arc.read("filings") if f["symbol"] in want and has_document(f.get("document_url"))
               and f.get("period_end")
               and (f["period_end"] in m["quarters"] if f["filing_type"] == "RESULTS" else q_lo <= f["period_end"] <= q_hi)]
    uniq = {}
    for f in filings:
        uniq.setdefault(f["document_url"], f)
    todo = [f for u, f in sorted(uniq.items()) if u not in seen_docs][: limit or None]
    print(f"documents budget (estimated): {len(todo)} GET + {len(todo)} HEAD direct requests "
          f"({len(uniq)} unique documents in scope, {len([u for u in uniq if u in seen_docs])} already archived)")
    log = RequestLog(arc, "documents")
    for i, f in enumerate(todo):
        url, t0 = f["document_url"], time.time()
        body, status, err = None, None, None
        try:
            body, status = await plain_http.fetch_bytes(url, label="pit-audit")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
        h = log.record("document", url, False, status, body, t0, err, {"filing_id": f["filing_id"], "symbol": f["symbol"]})
        hs, lm = await _head_last_modified(url)
        lm_ts = _http_date(lm) if lm and not str(lm).startswith("ERROR") else None
        doc = {"document_url": url, "filing_id": f["filing_id"], "symbol": f["symbol"], "listing": f["listing"],
               "status": status, "sha256": h, "error": err, "head_status": hs, "last_modified_raw": lm,
               "document_last_modified": iso(lm_ts), "retrieved_at": iso(dt.datetime.now(IST)), "metrics_status": None}
        if body is not None and status == 200:
            arc.store_artifact(body, ".xml")
            doc["metrics_status"], doc["metrics_reason"], recs = metric_records(f, body, url, h, doc["retrieved_at"])
            arc.append("metrics", recs)
        arc.append("documents", [doc])
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(todo)} documents; counts {log.counts}")
        await asyncio.sleep(DIRECT_PACE_S)
    print("documents counts:", log.counts)
    arc.append("run_summaries", [dict({"step": "documents", "finished_at": iso(dt.datetime.now(IST)), "planned": len(todo)},
                                      **log.counts)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["listings", "documents", "reextract"])
    ap.add_argument("--root", default="/app/research/pit_audit/nse")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    arc = Archive(a.root)
    if a.step == "reextract":
        step_reextract(arc)
        return
    asyncio.run(step_listings(arc) if a.step == "listings" else step_documents(arc, a.limit))


if __name__ == "__main__":
    main()
