"""Backfill nidp.corporate_announcements (BSE_ANN) from the CIE event store.

WHY

api.bseindia.com has answered HTTP 403 ("Access Denied") from both cloud
egresses — this VM directly AND the app-vm tinyproxy that fixes NSE — since
2026-09-23. It is a cloud-ASN block, so a proxy does not help, and production
holds no BSE filing dated 2026-09-23 or later.

Only the api. host is blocked. The CIE source ``bse_announcements_rss`` reads
www.bseindia.com/data/xml/announcements.xml and kept collecting straight through
the outage, into /app/research/tpd3_forward/events/events.sqlite. This moves
those rows into Postgres.

HOW — REUSE, NOT RE-DERIVE

Each RSS item is turned into a synthetic AnnGetData record and passed through
the PRODUCTION parser (``parser_bse._parse_one_bse``), then written by the
PRODUCTION writer (``writer.upsert_announcements``). Every derived field —
company_name, description, attachment_url, the announcement_id hash — therefore
comes from the same code the live ingester runs.

WHAT THE RSS DOES NOT CARRY, AND WHAT THAT COSTS

  NEWSID      -> announcement_id falls back to sha1(source|scrip|filed_at|subject).
                 Deterministic (re-runs are no-ops) but NOT the id the API would
                 produce for the same filing.
  NEWSSUB     -> BSE's structured label ("Announcement under Regulation 30
                 (LODR)-Credit Rating") is absent. subject is rebuilt as
                 "<Company> - <scrip> - <headline>", so its tail repeats the
                 description; it equals production's subject on ~5% of filings.
  CATEGORYNAME,
  SUBCATNAME  -> raw_category and subcategory are NULL on every row written here.
                 Consumers keyed on those fields (classifier prompt, lifecycle
                 stage from subject, lexical RAG) see these rows differently from
                 API rows. The off-VM API replay (bse_offvm_replay.py) is the
                 full-fidelity remedy; its rows supersede these automatically.
  DT_TM       -> pubDate is the company's SUBMISSION time, not BSE's dissemination
                 time; it is never later than production's filed_at, typically by
                 0-1 s, at most 181 s across production history. Second precision.
  attachment  -> BSE's own notices ("The Exchange has sought clarification from
                 ...") link to the bare AttachLive/ directory. That is not a
                 document: attachment_url is left NULL, as production stores them.

DUPLICATES — REMOVED AUTOMATICALLY

Because the id cannot match the API's, the natural key is (scrip_code,
attachment_url) — 99.8% unique in production BSE_ANN — and, for the NULL-attachment
notices, (scrip_code, filed_at within the 181 s submission→dissemination gap).
This script never inserts a filing production already holds.

The API WILL re-ingest these days without anyone asking: feed_reconciler re-runs
corporate_announcements for every day in its 7-day lookback each morning. Rows
written here carry raw_payload->>'via' = 'cie_bse_rss', and the production writer
(writer.upsert_announcements) deletes any such row the moment an API row for the
same filing is written. No manual cleanup step exists to forget.

SCOPE — measured, not assumed

The RSS carries far more than production ever ingested: mutual-fund and debt
schemes (one NAV PDF is attached to 1,502 scheme scrips). Rows are kept only for
scrips PRODUCTION HAS ACTUALLY INGESTED. Two broader scopes were tried and
rejected on the 2026-09-15..09-22 overlap, where production and the CIE both
hold the data:

  scope                                  recall   precision   debt (9xxxxx) leak
  scrip master UNION production          0.999    0.41        3,432 items
  production-ingested, before window     0.983    0.866       0

nidp.bse_scrip_master_daily is NOT an equity-only proxy: it contains 9xxxxx
debt/NCD/CP instruments (production has ingested zero of those, ever) and ETF /
MF units whose only filings are daily NAVs.

plus every scrip whose ISIN is an equity share (INE....01...) in the scrip
master, so companies that LIST during the window are kept — production ingests a
new listing from its first day (NSE's own BSE listing, 544937, listed 09-24).

  scope (09-15..09-22, days production covers, with a PDF) recall   precision
  production-ingested, before window                       0.983    0.953
  + equity-ISIN scrips in the master          (used)       0.998    0.948

`--compare 2026-09-15 2026-09-22` on the final code, counting the attachment-less
notices too: recall 0.9965, precision 0.9624 (the 3.8% gap is explained below), production never earlier than the
backfill (lag 0-40 s, median 0.5 s); subject agrees 5.2%, category/subcategory 0%.

Precision is measured only on days production covers (at least one production
row): production does not sweep weekends, so a Saturday filing absent from it says
nothing about fidelity (495 of the first run's 729 unmatched items were Sat 09-19 /
Sun 09-20). On covered days 190 of 5,057 in-scope items have no production twin,
and they are production's OWN SWEEP GAPS, not backfill noise: none of their 184
attachments appears anywhere in the table, 104 were filed before 12:00 IST in hours
where production holds almost nothing (09-16 10h: 13 unmatched vs 1 production row;
09-22 09h: 10 vs 1), and only 14 are AGM/voting/SAST filings. Running --write over
days production already covers fills exactly those gaps; Existing skips the rest.

MODES

  --compare FROM TO   no writes. Build rows for days production ALSO holds and
                      match them to production: recall, precision on covered days, and
                      agreement on every field consumers read. Run this first.
  --dry-run FROM TO   no writes. What --write would insert.
  --write   FROM TO   insert, via the production writer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sqlite3
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nidp.shared.storage.pg import get_pool

from .parser_bse import _BSE_ATTACHMENT_BASE, _parse_one_bse
from .writer import upsert_announcements

logger = logging.getLogger(__name__)

CIE_STORE = Path("/app/research/tpd3_forward/events/events.sqlite")
CIE_SOURCE = "bse_announcements_rss"
VIA = "cie_bse_rss"
IST = ZoneInfo("Asia/Kolkata")
_TITLE_SCRIP = re.compile(r"\s*\((\d{5,6})\)\s*$")
# RSS pubDate is the submission time; production's DT_TM is dissemination, up to
# 181.6 s later across 102,440 production rows. Used to pair attachment-less filings.
SUBMISSION_LAG = timedelta(seconds=182)


def _load_cie(since: date, until: date) -> list[dict]:
    """CIE rows published in [since, until], one per (scrip, attachment).

    The store keeps a row per content hash, so the same filing appears once per
    scrip it names; the earliest publication wins. A bare-directory link is not a
    document identity — every notice of a scrip shares it — so those key on time.
    A replaced attachment (same scrip, second and text) collapses to the latest file.
    """
    db = sqlite3.connect(f"file:{CIE_STORE}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT hash, url, title, summary, scrip_code, published_at, first_seen_at FROM raw_events "
        "WHERE source_id = ? AND published_at >= ? AND published_at < ? ORDER BY published_at",
        (CIE_SOURCE, since.isoformat(), (until + timedelta(days=1)).isoformat())).fetchall()
    seen: dict[tuple, dict] = {}
    for r in rows:
        if not r["url"] or not r["scrip_code"]:
            continue
        url = r["url"].strip()
        key = (str(r["scrip_code"]).strip(), url, r["published_at"] if url == _BSE_ATTACHMENT_BASE else None)
        if key not in seen:
            seen[key] = dict(r)
    # BSE sometimes REPLACES a filing's PDF: same scrip, same second, same text, a new
    # file name. The store then holds both links. Keep the one BSE published last —
    # production holds that one; the replaced file is not a separate filing.
    latest: dict[tuple, dict] = {}
    for r in seen.values():
        k = (str(r["scrip_code"]).strip(), r["published_at"], (r["summary"] or "").strip())
        if k not in latest or (r["first_seen_at"] or "") > (latest[k]["first_seen_at"] or ""):
            latest[k] = r
    return list(latest.values())


def _to_api_record(r: dict) -> dict:
    """Shape a CIE RSS row as the AnnGetData record the production parser expects."""
    scrip = str(r["scrip_code"]).strip()
    title = (r["title"] or "").strip()
    company = _TITLE_SCRIP.sub("", title).strip() or title
    headline = (r["summary"] or "").strip()
    ts = datetime.fromisoformat(r["published_at"]).strftime("%Y-%m-%dT%H:%M:%S")   # naive IST
    link = r["url"].strip()
    att = link[len(_BSE_ATTACHMENT_BASE):] if link.startswith(_BSE_ATTACHMENT_BASE) else ""
    return {
        "NEWSID": None, "SCRIP_CD": scrip,
        "NEWSSUB": f"{company} - {scrip} - {headline}" if headline else f"{company} - {scrip}",
        "HEADLINE": headline, "DT_TM": ts, "NEWS_DT": ts, "ATTACHMENTNAME": att,
        # provenance — stored verbatim as raw_payload by the parser
        "via": VIA, "cie_hash": r["hash"], "rss_link": link,
    }


def _build(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        rec = _to_api_record(r)
        p = _parse_one_bse(rec)
        if p is None:
            continue
        link = rec["rss_link"]
        # Keep a link the base did not match (e.g. AttachHis/). The bare AttachLive/
        # directory is BSE's own no-attachment notice: NULL, as production stores it.
        if not p.get("attachment_url") and not link.startswith(_BSE_ATTACHMENT_BASE):
            p["attachment_url"] = link
        out.append(p)
    return out


def is_equity_isin(isin: str | None) -> bool:
    """INE + 4-char issuer + security type '01' (equity shares) + serial + check."""
    return bool(isin) and isin.startswith("INE") and isin[7:9] == "01"


class Existing:
    """Filings production already holds. Attachment-bearing ones by (scrip, url);
    attachment-less ones by scrip + dissemination time, since they share no url."""

    def __init__(self, rows) -> None:
        self.pairs: set[tuple] = set()
        self.bare: dict[str, list[datetime]] = {}
        for r in rows:
            if r["a"]:
                self.pairs.add((r["s"], r["a"]))
            else:
                self.bare.setdefault(r["s"], []).append(r["t"])

    def __contains__(self, b: dict) -> bool:
        if b.get("attachment_url"):
            return (b["scrip_code"], b["attachment_url"]) in self.pairs
        t = b["filed_at"]            # submission: at or before production's dissemination
        return any(t - timedelta(seconds=1) <= p <= t + SUBMISSION_LAG
                   for p in self.bare.get(b["scrip_code"], ()))


async def _scope_and_existing(conn, before: date) -> tuple[set, Existing]:
    # Scrips production ingested BEFORE the window, plus every equity-ISIN scrip in
    # the master so listings inside the window are kept. The master alone is not an
    # equity proxy (9xxxxx debt, ETF/MF units), hence the ISIN security-type test.
    scope = {r["s"] for r in await conn.fetch(
        "SELECT DISTINCT scrip_code AS s FROM nidp.corporate_announcements "
        "WHERE source='BSE_ANN' AND scrip_code IS NOT NULL AND filed_at < $1",
        datetime.combine(before, datetime.min.time(), tzinfo=IST))}
    scope |= {r["s"] for r in await conn.fetch(
        "SELECT DISTINCT ON (scrip_code) scrip_code AS s, isin FROM nidp.bse_scrip_master_daily "
        "ORDER BY scrip_code, as_of_date DESC") if is_equity_isin(r["isin"])}
    existing = Existing(await conn.fetch(
        "SELECT scrip_code AS s, attachment_url AS a, filed_at AS t "
        "FROM nidp.corporate_announcements WHERE source='BSE_ANN' AND scrip_code IS NOT NULL"))
    return scope, existing


async def compare(since: date, until: date) -> dict:
    """Fidelity test on days production ALSO holds. Writes nothing."""
    built = _build(_load_cie(since, until))
    pool = await get_pool()
    async with pool.acquire() as conn:
        scope, _ = await _scope_and_existing(conn, since)
        prod = await conn.fetch(
            "SELECT scrip_code, attachment_url, filed_at, subject, company_name, description, "
            "raw_category, subcategory FROM nidp.corporate_announcements WHERE source='BSE_ANN' "
            "AND raw_payload->>'via' IS DISTINCT FROM $3 AND filed_at >= $1 AND filed_at < $2",
            datetime.combine(since, datetime.min.time(), tzinfo=IST),
            datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=IST), VIA)
    # Production never sweeps weekends: a day it holds nothing for measures nothing.
    covered = {r["filed_at"].astimezone(IST).date() for r in prod}
    in_scope = [b for b in built if b["scrip_code"] in scope
                and b["filed_at"].astimezone(IST).date() in covered]
    # Pair each production row with its backfill twin: by (scrip, url), or for an
    # attachment-less notice by scrip + the submission→dissemination window.
    by_pair = {(b["scrip_code"], b["attachment_url"]): b for b in in_scope if b["attachment_url"]}
    by_scrip_bare: dict[str, list[dict]] = {}
    for b in in_scope:
        if not b["attachment_url"]:
            by_scrip_bare.setdefault(b["scrip_code"], []).append(b)
    pairs, used = [], set()
    for p in prod:
        if p["attachment_url"]:
            b = by_pair.get((p["scrip_code"], p["attachment_url"]))
        else:
            b = next((c for c in by_scrip_bare.get(p["scrip_code"], ()) if id(c) not in used and
                      c["filed_at"] - timedelta(seconds=1) <= p["filed_at"] <= c["filed_at"] + SUBMISSION_LAG), None)
        if b is not None and id(b) not in used:
            used.add(id(b)); pairs.append((p, b))

    def agree(field):
        ok = sum((b[field] or "").strip().lower() == (p[field] or "").strip().lower() for p, b in pairs)
        return round(ok / len(pairs), 4) if pairs else None

    lag = sorted((p["filed_at"] - b["filed_at"]).total_seconds() for p, b in pairs)
    n_bare_prod = sum(1 for p in prod if not p["attachment_url"])
    return {
        "window": f"{since}..{until}", "days_production_covers": len(covered),
        "cie_items_built": len(built), "in_scope_on_covered_days": len(in_scope),
        "production_rows": len(prod), "of_which_attachment_less": n_bare_prod, "matched": len(pairs),
        "recall_of_production": round(len(pairs) / len(prod), 4) if prod else None,
        "precision_vs_production": round(len(pairs) / len(in_scope), 4) if in_scope else None,
        "lag_sec_production_minus_backfill": {"min": lag[0], "median": lag[len(lag) // 2], "max": lag[-1]} if lag else None,
        "company_name_agrees": agree("company_name"),
        "description_agrees": agree("description"),
        # Fields the RSS cannot carry — reported so no one reads the rows as API-identical.
        "subject_agrees": agree("subject"),
        "raw_category_agrees": agree("raw_category"),
        "subcategory_agrees": agree("subcategory"),
    }


async def backfill(since: date, until: date, write: bool) -> dict:
    built = _build(_load_cie(since, until))
    pool = await get_pool()
    async with pool.acquire() as conn:
        scope, existing = await _scope_and_existing(conn, since)
    in_scope = [b for b in built if b["scrip_code"] in scope]
    fresh = [b for b in in_scope if b not in existing]
    # The parser returns an aware datetime normalised to UTC, so .date() alone buckets a
    # 00:00-05:30 IST filing on the previous day. Bucket in IST, as Postgres does.
    by_day = Counter(b["filed_at"].astimezone(IST).date().isoformat() for b in fresh)
    report = {
        "window": f"{since}..{until}", "mode": "write" if write else "dry-run",
        "cie_items_built": len(built), "out_of_scope_dropped": len(built) - len(in_scope),
        "already_in_production": len(in_scope) - len(fresh),
        "to_insert": len(fresh), "by_filed_day": dict(sorted(by_day.items())),
    }
    if write and fresh:
        run_id = uuid.uuid4()
        report["inserted"] = await upsert_announcements(fresh, run_id)
        report["source_run_id"] = str(run_id)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--compare", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    ap.add_argument("since", type=date.fromisoformat)
    ap.add_argument("until", type=date.fromisoformat)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.compare:
        out = asyncio.run(compare(a.since, a.until))
    else:
        out = asyncio.run(backfill(a.since, a.until, write=a.write))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
