"""Replay BSE announcement history fetched OFF the VM through the production pipeline.

Pairs with bse_offvm_fetch.py, which a user runs on a non-cloud network (the only
place api.bseindia.com still answers) and which saves, per day, exactly the bytes
the production ingesters' fetch() would have returned.

REPLAY, NOT RE-IMPLEMENTATION

The two replay classes subclass the production ingesters and override ONLY
fetch(), which returns the saved bytes instead of calling the network. Everything
downstream is the production BaseIngester.run path, unchanged: the content guard
that rejects bot-block pages, raw archive, parse(), validate(), upsert, validation
and the job log. Rows therefore get genuine NEWSID-based announcement_ids plus
CATEGORYNAME and SUBCATNAME.

WHY THE REPLAY RUNS UNDER ITS OWN INGESTER NAMES

Both feed-health checks (deploy/vm/health_check.sh and feed_health_check) take the
latest status='OK' row per job_log.ingester. Replaying under
'corporate_announcements_bse' would write fresh OK rows and make the dead live feed
look healthy — the same silent failure that hid this outage for two days. So the
replay is 'corporate_announcements_bse_replay' / '..._bse_subcat_replay', and the
live ingester's health keeps telling the truth.

SUPERSEDING THE RSS STOPGAP

Rows written earlier by backfill_bse_from_cie.py (raw_payload->>'via' =
'cie_bse_rss') could not carry NEWSID, so their announcement_id differs from the
API's. The production writer deletes such a row in the same transaction that
writes its API twin (writer.SUPERSEDE_RSS_SQL), so a replay needs no extra step.
--supersede-rss runs the same predicate over the whole table, for API rows that
were written before the writer did this. Dry-run reports the count first.

USAGE (on nidp-stack-vm, after copying the fetched folder over)

  python -m nidp.services.corporate_announcements.bse_offvm_replay DIR --dry-run
  python -m nidp.services.corporate_announcements.bse_offvm_replay DIR --write
  python -m nidp.services.corporate_announcements.bse_offvm_replay DIR --write --supersede-rss
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from nidp.shared.storage.pg import get_pool

from .service import BseAnnouncementsIngester, BseSubcategoryAnnouncementsIngester
from .writer import COUNT_RSS_TWINS_SQL, COUNT_TWINS_OF_ROWS_SQL, SUPERSEDE_RSS_SQL, retire_rss_rows

logger = logging.getLogger(__name__)

REPLAY_URL = "offvm-replay://{kind}/{day}"   # recorded as the job's source_url


class _Replay:
    """Returns saved bytes from fetch(); inherits everything else from production."""

    def __init__(self, body: bytes, source_url: str) -> None:
        super().__init__()
        self._body, self._source_url = body, source_url

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        return self._body, self._source_url, 200


class ReplayCoarse(_Replay, BseAnnouncementsIngester):
    SERVICE_NAME = "corporate_announcements_bse_replay"


class ReplaySubcat(_Replay, BseSubcategoryAnnouncementsIngester):
    SERVICE_NAME = "corporate_announcements_bse_subcat_replay"


REPLAYERS = {"coarse": ReplayCoarse, "subcat": ReplaySubcat}
ORDER = ("coarse", "subcat")    # subcat runs second so its SUBCATNAME enriches the same ids


class ManifestError(Exception):
    pass


def load(dirpath: Path, kinds: tuple[str, ...], since: Optional[date],
         until: Optional[date]) -> list[tuple[str, date, bytes, dict]]:
    """Verified (kind, day, body, meta), in replay order.

    Reads the per-day .json sidecars, each carrying its own sha256, rather than one
    manifest.json: parallel Cloud Run tasks writing a single manifest over GCS would
    race, while a sidecar is written by exactly one task. Refuses anything whose
    bytes do not match their sidecar.
    """
    items, bad = [], []
    for kind in kinds:
        for side in sorted((dirpath / kind).glob("*.json")) if (dirpath / kind).exists() else []:
            m = json.loads(side.read_text())
            day = date.fromisoformat(m["date"])
            if (since and day < since) or (until and day > until):
                continue
            binf = dirpath / kind / f"{day}.bin"
            body = binf.read_bytes() if binf.exists() else b""
            if hashlib.sha256(body).hexdigest() != m["sha256"] or len(body) != m["bytes"]:
                bad.append(f"{kind}/{day}")
                continue
            items.append((kind, day, body, m))
    if bad:
        raise ManifestError(f"{len(bad)} files fail their sha256 — re-copy them: {bad[:10]}")
    return sorted(items, key=lambda t: (t[1], ORDER.index(t[0])))


async def _existing_ids(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT announcement_id FROM nidp.corporate_announcements "
            "WHERE source='BSE_ANN' AND announcement_id = ANY($1::text[])", ids)
    return {r["announcement_id"] for r in rows}


async def dry_run(items) -> dict:
    per_day, total, already = [], 0, 0
    twins: list[tuple] = []          # (scrip, filed_at, attachment) of rows that carry a NEWSID
    for kind, day, body, meta in items:
        rows = REPLAYERS[kind](body, "").parse(body, day)
        have = await _existing_ids([r["announcement_id"] for r in rows])
        per_day.append((str(day), kind, len(rows), len(have)))
        total += len(rows); already += len(have)
        twins += [(r["scrip_code"], r["filed_at"], r["attachment_url"]) for r in rows
                  if (r.get("raw_payload") or {}).get("NEWSID")]
    retire = 0
    if twins:
        pool = await get_pool()
        async with pool.acquire() as conn:
            retire = await conn.fetchval(COUNT_TWINS_OF_ROWS_SQL, *map(list, zip(*twins)))
    return {"files": len(items), "rows_parsed": total, "already_in_db": already,
            "new_rows": total - already, "rss_rows_the_replay_would_retire": retire,
            "first": per_day[:3], "last": per_day[-3:]}


async def write(items) -> dict:
    status, fetched, inserted = Counter(), 0, 0
    failed = []
    for kind, day, body, meta in items:
        run = await REPLAYERS[kind](body, REPLAY_URL.format(kind=kind, day=day)).run(target_date=day)
        st = getattr(run, "status", "UNKNOWN")
        status[f"{kind}:{st}"] += 1
        fetched += run.rows_fetched
        inserted += run.rows_inserted
        if st not in ("OK", "SKIPPED"):
            failed.append(f"{kind}/{day}:{st}")
    return {"runs": dict(status), "rows_fetched": fetched, "rows_upserted": inserted,
            "failed": failed[:20], "n_failed": len(failed)}


async def supersede_rss(apply: bool) -> int:
    """Whole-table sweep with the writer's own predicate. The writer already does
    this per batch; the sweep catches API rows written before that existed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not apply:
            return await conn.fetchval(COUNT_RSS_TWINS_SQL)
        async with conn.transaction():
            return await retire_rss_rows(conn, SUPERSEDE_RSS_SQL)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    ap.add_argument("--kinds", default="coarse,subcat")
    ap.add_argument("--from", dest="since", type=date.fromisoformat)
    ap.add_argument("--to", dest="until", type=date.fromisoformat)
    ap.add_argument("--supersede-rss", action="store_true",
                    help="after --write, delete cie_bse_rss rows the API version now covers")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    kinds = tuple(k.strip() for k in a.kinds.split(",") if k.strip())
    items = load(a.dir, kinds, a.since, a.until)
    print(json.dumps(asyncio.run(_run(a, items)), indent=1, default=str))


async def _run(a, items) -> dict:
    # ONE event loop: the pg pool binds to the loop that created it, so a second
    # asyncio.run() would fail on "attached to a different loop".
    out: dict = {"mode": "write" if a.write else "dry-run", "dir": str(a.dir)}
    if a.dry_run:
        out.update(await dry_run(items))
        out["rss_rows_with_api_twins_already_in_db"] = await supersede_rss(apply=False)
    else:
        out.update(await write(items))
        if a.supersede_rss:
            out["rss_rows_superseded"] = await supersede_rss(apply=True)
    return out


if __name__ == "__main__":
    main()
