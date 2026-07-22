"""Re-parse already-parsed documents through the CURRENT parse path.

Why: a code change to the parser (e.g. the vision financial-results extraction in
service._results_table_pages) only affects documents parsed AFTER it ships. Existing
docs keep whatever text the old parser stored — for scanned results filings that is
garbled numbers. This driver re-runs `_parse_one` over a doc_type so those docs pick
up the new extraction and their chunks are rewritten clean.

Idempotent: `_parse_one` OVERWRITES the doc's chunks (store_parse_result replaces
them), so a re-run only re-does work — never duplicates. The new chunks land with
NULL embeddings, so the normal embed pass / drain re-embeds them automatically.

Resumable: each processed doc_id is appended to a per-shard done-file and skipped on
restart. Sharded like the other vm/ backfills (disjoint hash slice of doc_id).

Runs the DEPLOYED service.py; if dev-repo is stale it falls back to /tmp/service_new.py
so a backfill isn't blocked waiting for the checkout to sync.

Env:
  REPARSE_DOC_TYPE   doc_type to re-parse                 (default financial_results)
  REPARSE_SINCE_DAYS filed_at >= now()-N days; 0/"" = all (default 90)
  REPARSE_SHARDS     parallel-worker fan-out              (default 1)
  REPARSE_SHARD      this worker's slice 0..SHARDS-1       (default 0)
  REPARSE_DONE_FILE  checkpoint path                       (default /tmp/reparse_done_<shard>.txt)
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "/opt/nidp/dev-repo/nivesh.ai/backend")

DOC_TYPE = os.environ.get("REPARSE_DOC_TYPE", "financial_results")
SHARDS = int(os.environ.get("REPARSE_SHARDS", "1"))
SHARD = int(os.environ.get("REPARSE_SHARD", "0"))
_sd = os.environ.get("REPARSE_SINCE_DAYS", "90").strip()
SINCE_DAYS = int(_sd) if _sd and _sd != "0" else None
DONE_FILE = os.environ.get("REPARSE_DONE_FILE", f"/tmp/reparse_done_{SHARD}.txt")

# Same column shape _parse_one expects (mirrors db._FETCH_PENDING_SQL), but selects
# ALREADY-PARSED docs of one type — the exact inverse of the pending queue. subject/
# subcategory come from the announcement join (used only for re-classification).
_FETCH_SQL = """
SELECT d.doc_id, d.source_url, d.ticker_symbol, d.isin, d.scrip_code, d.company_name,
       d.doc_type, ca.subject, ca.subcategory
  FROM nidp.documents d
  LEFT JOIN nidp.corporate_announcements ca
         ON ca.announcement_id = d.announcement_id
        AND ca.source          = d.announcement_source
 WHERE d.doc_type = $1
   AND d.parse_status = 'parsed'
   AND ($2::int IS NULL OR d.filed_at >= now() - make_interval(days => $2::int))
   -- positive-modulo hash shard (same idiom as the parse/embed backfills)
   AND mod(mod(hashtext(d.doc_id::text), $3::int) + $3::int, $3::int) = $4::int
 ORDER BY d.filed_at DESC NULLS LAST
"""


def _load_parse_one():
    """The deployed `_parse_one`, or the /tmp/service_new.py one if dev-repo is stale.

    `_RESULTS_MIN_SIGNALS` marks the vision-enabled build — the whole point of the
    backfill, so refuse to run the OLD parser (which would just rewrite the same
    garbled text and burn downloads for nothing)."""
    from nidp.services.document_parser import service as svc
    if hasattr(svc, "_RESULTS_MIN_SIGNALS"):
        return svc._parse_one
    import importlib.util
    import nidp.services.document_parser  # ensure the parent package is imported
    path = "/tmp/service_new.py"
    if not os.path.exists(path):
        raise SystemExit(
            "deployed service.py lacks the vision build and /tmp/service_new.py is "
            "absent — refusing to re-parse with the old parser (no-op churn).")
    spec = importlib.util.spec_from_file_location(
        "nidp.services.document_parser.service", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nidp.services.document_parser.service"] = mod
    spec.loader.exec_module(mod)
    if not hasattr(mod, "_RESULTS_MIN_SIGNALS"):
        raise SystemExit("/tmp/service_new.py is also the old parser — aborting.")
    return mod._parse_one


async def main() -> int:
    from nidp.shared.storage import pg

    parse_one = _load_parse_one()

    done: set[str] = set()
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE) as fh:
            done = {ln.strip() for ln in fh if ln.strip()}

    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_SQL, DOC_TYPE, SINCE_DAYS, SHARDS, SHARD)
    targets = [dict(r) for r in rows if str(r["doc_id"]) not in done]
    print(f"[s{SHARD}/{SHARDS}] {DOC_TYPE}: {len(rows)} in slice, "
          f"{len(done)} already done, {len(targets)} to re-parse "
          f"(since_days={SINCE_DAYS})", flush=True)

    total = 0
    errors = 0
    t0 = time.time()
    with open(DONE_FILE, "a") as df:
        for doc in targets:
            did = str(doc["doc_id"])
            try:
                await parse_one(doc)
            except Exception as e:  # noqa: BLE001 — one bad doc must not stop the run
                errors += 1
                print(f"  reparse error doc={did}: {type(e).__name__}: {e}", flush=True)
            # checkpoint even on error: _parse_one records its own failure status, and
            # re-trying a genuinely-broken doc every restart would stall the backfill.
            df.write(did + "\n")
            df.flush()
            done.add(did)
            total += 1
            if total % 25 == 0:
                el = time.time() - t0
                print(f"  [s{SHARD}/{SHARDS}] re-parsed {total}/{len(targets)} "
                      f"({total / max(el, 1) * 3600:,.0f}/hr) errors={errors}", flush=True)

    await pg.close_pool()
    print(f"\ndone: re-parsed {total} {DOC_TYPE} docs in "
          f"{(time.time() - t0) / 60:.1f} min (errors={errors})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
