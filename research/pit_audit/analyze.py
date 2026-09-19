"""PIT audit analysis (plan Step 6; AV-01..06, CMP-01..08, CAT-01..06, NSE-03/04, TL-02..05).

Reads ONLY the audit archives (nse/, bse/, trendlyne/) and the Trendlyne cache's own raw archive; writes
/app/research/pit_audit/analysis/analysis_<stamp>.json (+ tables.md). No network, no NIDP database.

Sections:
  availability : per sample filing, AV-1 v1.1 over the raw timestamps (+ BSE dissemination, + Last-Modified), session
                 bucket, first usable eod/next_open session, broadcast - period_end lag, filename-clock consistency (F-3)
  as_filed     : first-filed vs latest-known value per (symbol, period, basis, metric); duplicate listings vs revisions
  trendlyne    : Trendlyne quarterly values (labels 'Qtr', 'NQ ago' parsed from the raw archive) vs NSE first-filed,
                 classified by compare.classify; lag-anchoring matrix
  ownership    : Trendlyne ownership chart/summary vs NSE shareholding XBRL (promoter / FII / DII / MF)
  events       : Trendlyne board-meeting dates vs the NSE results broadcast of the matching quarter (AV-06)
  coverage     : stock x quarter x format, metric presence, timestamp completeness
run: python3 analyze.py
"""
from __future__ import annotations

import collections
import copy
import datetime as dt
import glob
import gzip
import json
import os
import re
import statistics

import availability as A
import compare as C
import sample
from archive import Archive
from contracts import IST, canonical_json, iso, sha256_bytes
from session import TradingCalendar, filename_ts, filename_ts_candidates, filename_ts_precision, first_usable_session, parse_nse_ts

ROOT = "/app/research/pit_audit"
TL_CACHE_ARCHIVE = "/app/research/trendlyne/archive"
OUT_DIR = os.path.join(ROOT, "analysis")
RAW_TS_FIELDS = {  # listing -> [(evidence source, raw field)]
    "legacy_results": [("nse_broadcast", "broadCastDate"), ("nse_dissemination", "exchdisstime"), ("nse_submission", "filingDate")],
    "integrated_results": [("nse_broadcast", "broadcast_Date"), ("nse_submission", "creation_Date")],
    "shareholding_master": [("nse_broadcast", "broadcastDate"), ("nse_submission", "submissionDate")],
}
# identity window for "the same results announcement" (BSE files one Financial Results item per company-quarter; its PDF
# precedes NSE's XBRL broadcast by up to ~7 h, e.g. HINDUNILVR Dec-25 10:21 vs 17:25). AV-1 then tests 15-min agreement.
BSE_BEFORE, BSE_AFTER = dt.timedelta(hours=24), dt.timedelta(hours=2)
TL_LABEL = re.compile(r"^(Net Profit|Total Rev\.|Basic EPS|Diluted EPS|EPS Adj\.)\s+(Qtr|(\d+)Q\s+ago)$", re.I)
TL_METRIC = {"net profit": "pat_cr", "total rev.": "revenue_cr", "basic eps": "eps_basic"}
DEFINITIONS = {"pat_cr": ["pat_owners_cr"], "revenue_cr": ["total_income_cr", "interest_earned_cr"],
               "eps_basic": ["eps_basic_total"]}
OWN_SERIES = {"Promoter": "promoter_pct", "FII": "fii_pct", "DII": "dii_pct", "MF": "mf_pct"}
MONTH_END = {"Mar": (3, 31), "Jun": (6, 30), "Sep": (9, 30), "Dec": (12, 31)}


def _strkeys(o):
    """JSON needs string keys: Counter keys such as None or (precision, consistent) tuples become their repr."""
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else repr(k)): _strkeys(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_strkeys(v) for v in o]
    return o


def _d(d):
    return d.isoformat() if d else None


def _t(s):
    return dt.datetime.fromisoformat(s) if s else None


def quarter_ends_desc(latest: dt.date, n: int) -> list[dt.date]:
    out, y, m = [], latest.year, latest.month
    for _ in range(n):
        d = {3: 31, 6: 30, 9: 30, 12: 31}[m]
        out.append(dt.date(y, m, d))
        m -= 3
        if m <= 0:
            m, y = m + 12, y - 1
    return out


def quarter_shift(q: dt.date, k: int) -> dt.date:
    """The quarter end k quarters after (k > 0) or before (k < 0) the quarter end q."""
    m = q.year * 12 + (q.month - 1) + 3 * k
    y, mo = divmod(m, 12)
    return dt.date(y, mo + 1, {3: 31, 6: 30, 9: 30, 12: 31}[mo + 1])


def session_bucket(t: dt.datetime | None, cal: TradingCalendar) -> str:
    if t is None:
        return "NO_TIME"
    t = t.astimezone(IST)
    s = cal.is_session(t.date())
    if s is None:
        return "OUTSIDE_CALENDAR"
    if not s:
        return "NON_SESSION_DAY"
    if t.time() < dt.time(9, 15):
        return "PRE_OPEN"
    return "MARKET_HOURS" if t.time() <= dt.time(15, 30) else "POST_CLOSE"


def pct(a, b):
    return None if not b else round(100.0 * a / b, 1)


def load():
    m = json.load(open(sample.OUT))
    canon = {s: s for s in m["symbols"]}
    for k, vs in m["aliases"].items():
        for v in vs:
            canon[v] = k
    nse, bse = Archive(os.path.join(ROOT, "nse")), Archive(os.path.join(ROOT, "bse"))
    filings = []
    for f in nse.read("filings"):
        s = canon.get(f["symbol"])
        if s is None or not f.get("period_end"):
            continue
        if f["filing_type"] == "RESULTS" and f["period_end"] not in m["quarters"]:
            continue
        if f["filing_type"] == "SHAREHOLDING" and not (m["quarters"][0] <= f["period_end"] <= m["quarters"][-1]):
            continue
        f = dict(f, canonical=s)
        if f["listing"] == "legacy_results":
            f["revision_flag"] = "UNKNOWN"   # F-4: records archived by parser 0.1.0 mapped reInd (a format code) to ORIGINAL
        filings.append(f)
    docs = {d["document_url"]: dict(d) for d in nse.read("documents")}
    for r in nse.read("reextractions"):                      # latest extraction status per document (ARC-05)
        if r["document_url"] in docs:
            docs[r["document_url"]].update(metrics_status=r["metrics_status"], metrics_reason=r["metrics_reason"],
                                           metrics_parser_version=r["parser_version"])
    allm = collections.defaultdict(list)
    for r in nse.read("metrics"):
        allm[r["document_url"]].append(r)
    metrics = {}
    for u, rs in allm.items():                                # only the newest parser version's records per document
        v = max(r["parser_version"] for r in rs)
        metrics[u] = [r for r in rs if r["parser_version"] == v]
    res = {}
    for r in bse.read("scrip_resolution"):
        res[r["symbol"]] = r                                   # latest resolution wins
    bse_rows = collections.defaultdict(list)
    for r in bse.read("bse_announcements"):
        raw = r["raw_row"]
        ts = raw.get("DissemDT") or raw.get("NEWS_DT")
        try:
            t = dt.datetime.fromisoformat(str(ts)[:19]).replace(tzinfo=IST) if ts else None
        except ValueError:
            t = None
        bse_rows[canon.get(r["symbol"], r["symbol"])].append(dict(raw, _t=t, _url=r["source_url"]))
    return m, canon, filings, docs, metrics, res, bse_rows


def dedupe_bse(rows):
    seen, out = set(), []
    for r in rows:
        if r.get("NEWSID") in seen:
            continue
        seen.add(r.get("NEWSID"))
        out.append(r)
    return out


def availability(filings, docs, bse_rows, cal):
    out = []
    for f in filings:
        raw = f["raw_row"] or {}
        items, precisions = [], {}
        for src, field in RAW_TS_FIELDS[f["listing"]]:
            t, p = parse_nse_ts(raw.get(field))
            precisions[src] = p
            items.append(A.evidence(src, "NSE", t, p))
        url = f.get("document_url")
        d = docs.get(url)
        lm = _t(d.get("document_last_modified")) if d else None
        if lm:
            items.append(A.evidence("document_last_modified", "NSE", lm, "second"))
        if filename_ts_precision(url) == "second":
            items.append(A.evidence("nse_filename_creation", "NSE", filename_ts(url), "second"))
        b, _ = parse_nse_ts(raw.get(dict(RAW_TS_FIELDS[f["listing"]])["nse_broadcast"]))
        bse_match, bse_cands = None, []
        if f["filing_type"] == "RESULTS" and b is not None:
            bse_cands = [r for r in bse_rows.get(f["canonical"], []) if r["_t"] is not None
                         and "result" in f"{r.get('SUBCATNAME')} {r.get('CATEGORYNAME')}".lower()
                         and -BSE_BEFORE <= r["_t"] - b <= BSE_AFTER]
            for r in bse_cands:
                items.append(A.evidence("bse_announcement", "BSE", r["_t"], "second"))
            if bse_cands:
                first = min(bse_cands, key=lambda r: r["_t"])
                bse_match = {"newsid": first.get("NEWSID"), "dissem_at": iso(first["_t"]), "headline": first.get("HEADLINE"),
                             "candidates": len(bse_cands), "delta_vs_nse_s": round((first["_t"] - b).total_seconds())}
        a = A.assess(items)
        cands = filename_ts_candidates(url)
        fn_consistent = (None if not cands or b is None else
                         any(abs(c - b) <= dt.timedelta(minutes=15) for c in cands))
        av = _t(a["available_at"])
        pe = dt.date.fromisoformat(f["period_end"])
        out.append({"symbol": f["canonical"], "listing": f["listing"], "filing_type": f["filing_type"],
                    "filing_id": f["filing_id"], "period_end": f["period_end"], "basis": f["consolidation_type"],
                    "revision_flag": f["revision_flag"], "document_url": url, "raw_precision": precisions,
                    "document_fetch_status": d.get("status") if d else "NOT_FETCHED",
                    "metrics_status": d.get("metrics_status") if d else None,
                    "bse_match": bse_match, "filename_precision": filename_ts_precision(url),
                    "filename_consistent_with_broadcast": fn_consistent,
                    "broadcast_minus_period_end_days": (b.date() - pe).days if b else None,
                    "session_bucket": session_bucket(av, cal),
                    "first_usable_eod": _d(first_usable_session(av, "eod", cal)) if av else None,
                    "first_usable_next_open": _d(first_usable_session(av, "next_open", cal)) if av else None,
                    **{k: a.get(k) for k in ("submitted_at", "broadcast_at", "document_available_at",
                                             "first_publicly_available_at", "available_at", "availability_confidence",
                                             "timestamp_precision", "nse_corroborated", "contradiction",
                                             "rule_id", "rule_version")},
                    "availability_evidence": a["availability_evidence"]})
    return out


def as_filed(filings, docs, metrics, av_by_key):
    """{(symbol, period_end, basis, metric): first-filed / latest-known} for RESULTS.

    Order = public time (broadcast, else revised_at). First-filed = the earliest entry that is not a flagged revision
    and has a broadcast time and values. Every later entry is a REVISION (integrated type_Sub), a DUPLICATE_LISTING
    (other format, broadcast within 15 min) or a LATER_FILING_UNFLAGGED (legacy rows carry no revision flag, F-4).
    """
    groups = collections.defaultdict(list)
    for f in filings:
        if f["filing_type"] == "RESULTS":
            groups[(f["canonical"], f["period_end"], f["consolidation_type"])].append(f)
    table, chronology = {}, []
    for (s, pe, basis), fs in groups.items():
        entries = []
        for f in fs:
            vals = {r["metric_name"]: r["metric_value"] for r in metrics.get(f["document_url"], [])
                    if r["period_end"] == pe and (r["consolidation_type"] or basis) == basis and r["metric_value"] is not None}
            avr = av_by_key.get((f["listing"], f["filing_id"], f["document_url"]), {})
            entries.append({"listing": f["listing"], "filing_id": f["filing_id"], "revision_flag": f["revision_flag"],
                            "broadcast_at": avr.get("broadcast_at"), "revised_at": f.get("revised_at"),
                            "public_at": avr.get("broadcast_at") or f.get("revised_at"),
                            "document_url": f["document_url"], "values": vals})
        entries.sort(key=lambda e: e["public_at"] or "9999")
        first = next((e for e in entries if e["revision_flag"] != "REVISED" and e["broadcast_at"] and e["values"]), None)
        later = [e for e in entries if e is not first and first and (e["public_at"] or "9999") >= first["broadcast_at"]]
        for e in later:
            dup = (e["listing"] != first["listing"] and e["broadcast_at"] and
                   abs(_t(e["broadcast_at"]) - _t(first["broadcast_at"])) <= dt.timedelta(minutes=15))
            e["kind"] = "REVISION" if e["revision_flag"] == "REVISED" else ("DUPLICATE_LISTING" if dup else "LATER_FILING_UNFLAGGED")
        chronology.append({"symbol": s, "period_end": pe, "basis": basis, "filings": len(entries),
                           "first_filed": first["filing_id"] if first else None,
                           "later": collections.Counter(e["kind"] for e in later),
                           "listings": sorted({e["listing"] for e in entries})})
        if not first:
            continue
        for metric in set(first["values"]) | {k for e in later for k in e["values"]}:
            ff = first["values"].get(metric)
            changing = [e for e in later if e["kind"] != "DUPLICATE_LISTING" and e["values"].get(metric) is not None]
            last = changing[-1] if changing else None
            lk = last["values"][metric] if last else ff
            dups = [e for e in later if e["kind"] == "DUPLICATE_LISTING" and e["values"].get(metric) is not None]
            status = ("NO_LATER_FILING" if not changing else
                      ("LATER_SAME_VALUE" if ff is not None and abs(lk - ff) < 1e-9 else "LATER_VALUE_CHANGED"))
            table[(s, pe, basis, metric)] = {
                "as_filed_value": ff, "latest_known_value": lk, "first_filed_at": first["broadcast_at"],
                "first_filed_id": first["filing_id"], "first_filed_listing": first["listing"],
                "latest_filing_at": last["public_at"] if last else None, "latest_filing_id": last["filing_id"] if last else None,
                "latest_filing_kind": last["kind"] if last else None, "revision_status": status,
                "duplicate_listings": len(dups),
                "duplicate_listing_disagreements": [e["filing_id"] for e in dups if ff is not None and abs(e["values"][metric] - ff) > 1e-9],
                "comparative_values": None, "comparative_status": "BLOCKED_F1_XBRL_HAS_NO_COMPARATIVE_COLUMNS"}
    for c in chronology:
        c["later"] = dict(c["later"])
    return table, chronology


def tl_quarterly():
    recs = []
    for p in sorted(glob.glob(os.path.join(TL_CACHE_ARCHIVE, "2026-09-19", "param_values.jsonl.gz"))):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            recs += [json.loads(line) for line in fh if line.strip()]
    recs = [r for r in recs if "npqmq1" in r["params"]]
    values, asof, labels_seen = {}, {}, set()
    for r in recs:
        for c in r["codes"]:
            rk = (r.get("row_key") or {}).get(c)
            if rk is None:
                continue
            asof[c] = (r.get("asof") or {}).get(c)
            for label, per in r["raw"].items():
                mt = TL_LABEL.match(label.strip())
                labels_seen.add(label)
                if not mt:
                    continue
                name = mt.group(1).lower()
                metric = TL_METRIC.get(name)
                if metric is None:
                    continue
                k = 0 if mt.group(2).lower() == "qtr" else int(mt.group(3))
                v = per.get(rk)
                values[(c, metric, k)] = None if v in (None, "", "-", "None", "null") else float(v)
    return values, asof, sorted(labels_seen), [r["fetched_at"] for r in recs]


def compare_trendlyne(values, asof, table, avail, cfg, quarters):
    by_sym = collections.defaultdict(dict)
    for (s, pe, basis, metric), v in table.items():
        by_sym[s][(pe, basis, metric)] = v
    rows, anchoring = [], []
    for (s, metric, k), tl in sorted(values.items()):
        a = asof.get(s)
        if tl is None:
            rows.append({"symbol": s, "metric": metric, "lag": k, "trendlyne": None, "status": "TRENDLYNE_VALUE_MISSING"})
            continue
        filed = sorted({pe for (pe, b, mt), v in by_sym[s].items() if v["first_filed_at"] and a
                        and v["first_filed_at"][:10] <= a})
        if not filed:
            rows.append({"symbol": s, "metric": metric, "lag": k, "trendlyne": tl, "status": "NO_NSE_PERIOD"})
            continue
        latest = dt.date.fromisoformat(filed[-1])
        expected = quarter_ends_desc(latest, k + 1)[k].isoformat()
        if expected not in quarters:
            rows.append({"symbol": s, "metric": metric, "lag": k, "trendlyne": tl, "expected_period": expected,
                         "status": "OUT_OF_SAMPLE_PERIOD"})
            continue
        bases = [b for b in ("CONSOLIDATED", "STANDALONE") if (expected, b, metric) in by_sym[s]]
        primary = bases[0] if bases else None
        ffv = by_sym[s].get((expected, primary, metric), {})
        other = [b for b in bases if b != primary]
        other_basis = by_sym[s].get((expected, other[0], metric), {}).get("as_filed_value") if other else None
        defs = [(f"{d}@{primary}", by_sym[s].get((expected, primary, d), {}).get("as_filed_value")) for d in DEFINITIONS[metric]]
        # PERIOD_MAPPING candidates: same basis, adjacent (+/-1) or year-ago/-ahead (+/-4) quarters only - matching
        # against every period of both bases found coincidental 0.5% matches (ITC revenue "matching" a year-old quarter)
        e = dt.date.fromisoformat(expected)
        near = {quarter_shift(e, k).isoformat() for k in (-4, -1, 1, 4)}
        others = [(f"{pe}@{b}", v["as_filed_value"]) for (pe, b, mt), v in by_sym[s].items()
                  if mt == metric and b == primary and pe in near]
        c = C.classify(metric, tl, ffv.get("as_filed_value"), ffv.get("latest_known_value"), other_basis=other_basis,
                       other_period_values=others, other_definition_values=defs, cfg=cfg)
        missing = c["as_filed_value"] is None and c["difference_type"] != "DEFINITION_DIFFERENCE"
        rows.append(dict(c, symbol=s, lag=k, trendlyne_asof=a, expected_period=expected, primary_basis=primary,
                         first_filed_at=ffv.get("first_filed_at"), revision_status=ffv.get("revision_status"),
                         status="NSE_VALUE_MISSING" if missing else "COMPARED"))
        if missing:
            continue
        anchored = c["reconciliation_status"] in ("MATCH_FIRST_FILED", "MATCH_LATEST_REVISION") or \
            c["difference_type"] in ("ROUNDING", "UNIT_CONVERSION", "DEFINITION_DIFFERENCE")
        anchoring.append({"symbol": s, "metric": metric, "lag": k, "expected_period": expected,
                          "anchor": ("EXPECTED_PERIOD" if anchored else
                                     ("OTHER_PERIOD:" + c["explanation"].split("matches period ")[-1]
                                      if c["difference_type"] == "PERIOD_MAPPING" else
                                      ("NO_NSE_VALUE" if c["as_filed_value"] is None else "UNRESOLVED")))})
    return rows, anchoring


def parse_tl_ownership(text: str) -> dict:
    """{series: {quarter_end: value}} from the chartData block, and {"summary": {label: value}} (latest)."""
    out, cur, section = {}, None, None
    for line in (text or "").splitlines():
        st = line.strip()
        if line.startswith("summaryData:") or line.startswith("chartData:") or line.startswith("insights:"):
            section = line.rstrip(":")
            continue
        if section == "summaryData":
            for lab, val in re.findall(r'\["([^"]+)",\s*(-?[\d.]+|null)', st):
                out.setdefault("summary", {})[lab] = None if val == "null" else float(val)
        elif section == "chartData":
            m = re.match(r"^\s{2}(\w[\w ]*):$", line)
            if m:
                cur = m.group(1)
                continue
            if cur:
                for mon, yr, val in re.findall(r'\["(Mar|Jun|Sep|Dec) (\d{4})",\s*(-?[\d.]+|null)', st):
                    mm, dd = MONTH_END[mon]
                    out.setdefault(cur, {})[dt.date(int(yr), mm, dd).isoformat()] = None if val == "null" else float(val)
    return out


def compare_ownership(filings, metrics, avail_by_key, cfg):
    tl = Archive(os.path.join(ROOT, "trendlyne"))
    own = {}
    for r in tl.read("tl_raw"):
        if r["kind"] == "ownership" and r.get("text"):
            own[r["args"]["stock_code"]] = (parse_tl_ownership(r["text"]), r["retrieved_at"])
    chart_cfg = copy.deepcopy(cfg)
    chart_cfg["rounding_display_decimals"].update(cfg["source_display_decimals"]["trendlyne_ownership_chart"])
    nse = collections.defaultdict(list)       # (symbol, period_end) -> [(order key, filing, values)]
    for f in filings:
        if f["filing_type"] != "SHAREHOLDING":
            continue
        vals = {r["metric_name"]: r["metric_value"] for r in metrics.get(f["document_url"], [])}
        avr = avail_by_key.get((f["listing"], f["filing_id"], f["document_url"]), {})
        nse[(f["canonical"], f["period_end"])].append((f["revision_flag"] == "REVISED", avr.get("broadcast_at") or "9999",
                                                        f, vals, avr))
    rows = []
    for s, (o, retrieved) in sorted(own.items()):
        for series, metric in OWN_SERIES.items():
            for pe, v in sorted(o.get(series, {}).items()):
                cands = sorted(nse.get((s, pe), []), key=lambda x: (x[0], x[1]))
                with_vals = [c for c in cands if c[3].get(metric) is not None]
                ff = with_vals[0] if with_vals else None
                latest = with_vals[-1] if len(with_vals) > 1 else None
                c = C.classify(metric, v, ff[3].get(metric) if ff else None, latest[3].get(metric) if latest else None,
                               cfg=chart_cfg)
                rows.append(dict(c, symbol=s, series=series, period_end=pe, surface="chart_1dp",
                                 nse_filings=len(cands), nse_first_filed_at=ff[1] if ff else None,
                                 nse_availability=ff[4].get("availability_confidence") if ff else None,
                                 status="COMPARED" if ff else ("NO_NSE_FILING" if not cands else "NSE_VALUE_MISSING")))
    return rows, len(own)


def events(filings, avail_by_key):
    tl = Archive(os.path.join(ROOT, "trendlyne"))
    out = []
    bcasts = collections.defaultdict(list)
    for f in filings:
        if f["filing_type"] == "RESULTS" and f["revision_flag"] != "REVISED":
            b = avail_by_key.get((f["listing"], f["filing_id"], f["document_url"]), {}).get("broadcast_at")
            if b:
                bcasts[(f["canonical"], f["period_end"])].append(b)
    for r in tl.read("tl_raw"):
        if r["kind"] != "events" or not r.get("text"):
            continue
        s = r["args"]["stock_code"]
        block = r["text"].split("boardMeeting:", 1)[-1]
        for d, purpose in re.findall(r"^\s+(\d{4}-\d{2}-\d{2}) \| ([^|]*)\|", block, re.M):
            if "result" not in purpose.lower():
                continue
            md = dt.date.fromisoformat(d)
            # the quarter whose results a meeting approves: the latest quarter end at least 1 day before the meeting
            q = next(q for q in quarter_ends_desc(dt.date(md.year, ((md.month - 1) // 3 + 1) * 3, 1), 3) if q < md)
            bs = sorted(bcasts.get((s, q.isoformat()), []))
            if not bs:
                if q.isoformat() < "2024-09-30":
                    continue
                out.append({"symbol": s, "board_meet_date": d, "purpose": purpose.strip(), "quarter": q.isoformat(),
                            "nse_first_broadcast": None, "relation": "NO_NSE_BROADCAST_IN_SAMPLE"})
                continue
            b = dt.datetime.fromisoformat(bs[0])
            rel = ("SAME_DAY" if b.date() == md else ("BROADCAST_AFTER_MEETING_DATE" if b.date() > md
                                                       else "BROADCAST_BEFORE_MEETING_DATE"))
            out.append({"symbol": s, "board_meet_date": d, "purpose": purpose.strip(), "quarter": q.isoformat(),
                        "nse_first_broadcast": bs[0], "broadcast_time_of_day": b.time().isoformat(), "relation": rel,
                        "event_date_precision": "day"})
    return out


def coverage(m, canon, filings, avail, table, tl_values):
    q = m["quarters"]
    syms = sorted(m["symbols"])
    cov = []
    for s in syms:
        for pe in q:
            fs = [a for a in avail if a["symbol"] == s and a["period_end"] == pe and a["filing_type"] == "RESULTS"]
            orig = [a for a in fs if a["revision_flag"] != "REVISED"]
            vals = {mt: any((s, pe, b, mt) in table and table[(s, pe, b, mt)]["as_filed_value"] is not None
                            for b in ("CONSOLIDATED", "STANDALONE")) for mt in ("revenue_cr", "pat_cr", "eps_basic")}
            conf = collections.Counter(a["availability_confidence"] for a in orig)
            cov.append({"symbol": s, "period_end": pe, "results_filings": len(fs), "original_filings": len(orig),
                        "formats": sorted({a["listing"] for a in fs}),
                        "bases": sorted({a["basis"] or "UNKNOWN" for a in fs}),
                        "xbrl_ok": sum(a["metrics_status"] == "OK" for a in fs), **{f"has_{k}": v for k, v in vals.items()},
                        "availability": dict(conf), "bse_matched": sum(bool(a["bse_match"]) for a in orig)})
    return cov


def summarize(avail, table, chronology, tl_rows, anchoring, own_rows, ev, cov, tl_meta):
    res = [a for a in avail if a["filing_type"] == "RESULTS"]
    shp = [a for a in avail if a["filing_type"] == "SHAREHOLDING"]
    s = {}
    for name, grp in (("results", res), ("shareholding", shp)):
        orig = [a for a in grp if a["revision_flag"] != "REVISED"]
        lags = [a["broadcast_minus_period_end_days"] for a in orig if a["broadcast_minus_period_end_days"] is not None]
        bse_d = [abs(a["bse_match"]["delta_vs_nse_s"]) for a in orig if a["bse_match"]]
        s[name] = {"filings": len(grp), "originals": len(orig), "revisions": len(grp) - len(orig),
                   "by_listing": dict(collections.Counter(a["listing"] for a in grp)),
                   "confidence_originals": dict(collections.Counter(a["availability_confidence"] for a in orig)),
                   "confidence_revisions": dict(collections.Counter(a["availability_confidence"] for a in grp
                                                                    if a["revision_flag"] == "REVISED")),
                   "nse_corroborated_originals": sum(bool(a.get("nse_corroborated")) for a in orig),
                   "contradictions": sum(bool(a.get("contradiction")) for a in grp),
                   "precision_originals": dict(collections.Counter(a["timestamp_precision"] for a in orig)),
                   "raw_precision": {src: dict(collections.Counter(a["raw_precision"].get(src) for a in grp))
                                     for src in sorted({k for a in grp for k in a["raw_precision"]})},
                   "session_bucket_originals": dict(collections.Counter(a["session_bucket"] for a in orig)),
                   "bse_matched_originals": sum(bool(a["bse_match"]) for a in orig),
                   "bse_abs_delta_s": ({"n": len(bse_d), "median": statistics.median(bse_d), "max": max(bse_d),
                                        "within_15min": sum(d <= 900 for d in bse_d)} if bse_d else None),
                   "lag_days": ({"n": len(lags), "min": min(lags), "median": statistics.median(lags), "max": max(lags),
                                 "same_day_as_period_end": sum(x <= 0 for x in lags)} if lags else None),
                   "filename": dict(collections.Counter((a["filename_precision"], a["filename_consistent_with_broadcast"])
                                                        for a in grp)),
                   "documents": dict(collections.Counter(str(a["document_fetch_status"]) for a in grp)),
                   "metrics_status": dict(collections.Counter(str(a["metrics_status"]) for a in grp))}
    later = collections.Counter()
    for c in chronology:
        later.update(c["later"])
    s["as_filed"] = {"keys": len(table), "revision_status": dict(collections.Counter(v["revision_status"] for v in table.values())),
                     "latest_filing_kind": dict(collections.Counter(v["latest_filing_kind"] for v in table.values())),
                     "duplicate_listing_disagreements": sum(bool(v["duplicate_listing_disagreements"]) for v in table.values()),
                     "groups": len(chronology), "groups_without_first_filed_values": sum(c["first_filed"] is None for c in chronology),
                     "later_entries_by_kind": dict(later), "groups_in_both_formats": sum(len(c["listings"]) > 1 for c in chronology)}
    comp = [r for r in tl_rows if r["status"] == "COMPARED"]
    s["trendlyne_financials"] = {
        "values": len(tl_rows), "non_null": sum(r.get("trendlyne") is not None for r in tl_rows), "compared": len(comp),
        "fetched_at": tl_meta["fetched_at"], "labels_seen": tl_meta["labels"],
        "by_metric_lag": {f"{mt}|{k}": dict(collections.Counter(r["difference_type"] for r in comp if r["metric"] == mt and r["lag"] == k))
                          for mt in ("revenue_cr", "pat_cr", "eps_basic") for k in range(0, 9)
                          if any(r["metric"] == mt and r["lag"] == k for r in comp)},
        "reconciliation": dict(collections.Counter(r["reconciliation_status"] for r in comp)),
        "difference_type": dict(collections.Counter(r["difference_type"] for r in comp)),
        "material_unexplained": sum(r["reconciliation_status"] == "DIFFERS_UNEXPLAINED"
                                    and r["materiality_vs_first_filed"]["result"] == "MATERIAL_DIFFERENCE" for r in comp),
        "sign_changes": sum(bool(r["materiality_vs_first_filed"]["sign_change"]) for r in comp),
        "not_compared": dict(collections.Counter(r["status"] for r in tl_rows if r["status"] != "COMPARED"))}
    s["anchoring"] = dict(collections.Counter(a["anchor"].split(":")[0] for a in anchoring))
    oc = [r for r in own_rows if r["status"] == "COMPARED"]
    s["ownership"] = {"rows": len(own_rows), "compared": len(oc),
                      "difference_type": dict(collections.Counter(r["difference_type"] for r in oc)),
                      "by_series": {k: dict(collections.Counter(r["difference_type"] for r in oc if r["series"] == k)) for k in OWN_SERIES},
                      "not_compared": dict(collections.Counter(r["status"] for r in own_rows if r["status"] != "COMPARED"))}
    s["events"] = dict(collections.Counter(e["relation"] for e in ev))
    s["coverage"] = {"cells": len(cov), "cells_with_original_filing": sum(c["original_filings"] > 0 for c in cov),
                     "cells_with_pat": sum(c["has_pat_cr"] for c in cov), "cells_with_revenue": sum(c["has_revenue_cr"] for c in cov),
                     "cells_with_eps": sum(c["has_eps_basic"] for c in cov),
                     "cells_with_bse_match": sum(c["bse_matched"] > 0 for c in cov),
                     "missing_cells": [(c["symbol"], c["period_end"]) for c in cov if c["original_filings"] == 0]}
    return s


def main():
    m, canon, filings, docs, metrics, res, bse_rows = load()
    bse_rows = {k: dedupe_bse(v) for k, v in bse_rows.items()}
    cal = TradingCalendar.from_kite_index()
    cfg = C.load_config()
    avail = availability(filings, docs, bse_rows, cal)
    avail_by_key = {(a["listing"], a["filing_id"], a["document_url"]): a for a in avail}
    table, chronology = as_filed(filings, docs, metrics, avail_by_key)
    tl_values, tl_asof, labels, fetched = tl_quarterly()
    tl_rows, anchoring = compare_trendlyne(tl_values, tl_asof, table, avail, cfg, set(m["quarters"]))
    own_rows, own_n = compare_ownership(filings, metrics, avail_by_key, cfg)
    ev = events(filings, avail_by_key)
    cov = coverage(m, canon, filings, avail, table, tl_values)
    summary = summarize(avail, table, chronology, tl_rows, anchoring, own_rows, ev, cov,
                        {"fetched_at": fetched, "labels": labels})
    summary["bse_resolution"] = {r["symbol"]: {k: r[k] for k in ("status", "method", "bse_codes")} for r in res.values()}
    inputs = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "*", "*.jsonl.gz"))) + \
            sorted(glob.glob(os.path.join(TL_CACHE_ARCHIVE, "2026-09-19", "param_values.jsonl.gz"))):
        with open(p, "rb") as fh:
            inputs[p] = sha256_bytes(fh.read())
    out = {"generated_at": iso(dt.datetime.now(IST)), "inputs_sha256": inputs, "summary": summary,
           "availability": avail, "as_filed": [dict(zip(("symbol", "period_end", "basis", "metric"), k), **v) for k, v in sorted(table.items())],
           "chronology": chronology, "trendlyne_financials": tl_rows, "anchoring": anchoring, "ownership": own_rows,
           "events": ev, "coverage": cov}
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = dt.datetime.now(IST).strftime("%Y%m%dT%H%M%S")
    path = os.path.join(OUT_DIR, f"analysis_{stamp}.json")
    out = _strkeys(out)
    body = canonical_json(out).encode()
    with open(path, "wb") as fh:
        fh.write(body)
    print(path, sha256_bytes(body))
    print(json.dumps(out["summary"], indent=1, default=str)[:15000])


if __name__ == "__main__":
    main()
