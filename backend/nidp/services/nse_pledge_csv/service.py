"""Ingest a manually-downloaded NSE SAST pledged-data CSV into shareholding_pattern.

Companion to ``nse_pledge_data``, which fetches the same figures from
``/api/corporate-pledgedata``. That endpoint 403s this platform's egress at the IP
level (verified 2026-08-19 from two networks, with browser UA, primed cookies and a
correct Referer), so the file is downloaded by hand and dropped here. Both services
are kept: if the block ever lifts, the API path resumes on its own.

Measured on nidp_staging 2026-08-19, BEFORE this ran: ``promoter_pledged_pct`` and
``promoter_pledged_to_total_pct`` were NULL in all 8,955 rows of
``nidp.shareholding_pattern``. Promoter pledge is not "thin" in this platform, it is
absent, so this is the only path that makes it exist.

Three choices here are deliberate and each one is a decision not to break something:

**1. It UPDATEs existing rows; it does not add a new ``source``.**
``v_shareholding_latest`` ranks with ``ROW_NUMBER() OVER (PARTITION BY symbol ORDER
BY period_end DESC)`` — no tiebreak on ``source``. Two rows sharing a
(symbol, period_end) therefore make "latest" a coin flip, which the DQ suite already
flags as a tripwire (``single_source_per_key``). A pledge-only row carries no
fii_pct/dii_pct, so on the flips where it won the FII/DII QoQ signals would silently
go dark for that symbol. Writing the pledge columns into the rows that already exist
avoids the whole class of problem.

**2. Rows for symbols with no shareholding row at that quarter are NOT inserted by
default** (``--insert-missing`` opts in). Same reason: a newly-inserted quarter
becomes rn=1 for that symbol and hides the previous quarter's FII/DII behind a row
that has none.

**3. The UPDATE touches ONLY the three pledge columns.** Not ``source_run_id`` — that
would attribute a row's FII/DII data (1,981 of the 2,281 rows at 2026-06-30) to a
pledge run that never produced it. Not ``ingested_at`` — bumping it would make the
shareholding feed read as freshly ingested when it was not, and a feed that reports
healthy while stale is the exact failure this platform keeps hitting.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from nidp.shared.storage.pg import get_pool

from .parser import SOURCE_NAME, normalise_company_name, parse_sast_csv, pledge_stats

logger = logging.getLogger(__name__)

# stock_features_daily.promoter_pledged_pct is fed from
# shareholding_pattern.promoter_pledged_to_total_pct — see
# populate_stock_features_extended (migrations 029/053/070/091). The feature column's
# NAME says "of promoter", its VALUE is "of total shares". That mismatch is
# pre-existing; this service matches the platform's behaviour rather than quietly
# introducing a second, incompatible meaning for the same column.
_FEATURE_SOURCE_COLUMN = "promoter_pledged_to_total_pct"


def build_name_index(sm_rows: Iterable[Any]) -> Tuple[Dict[str, str], List[str]]:
    """Normalised company name -> symbol, plus the names too ambiguous to use.

    A normalised name that maps to more than one symbol is dropped rather than
    resolved arbitrarily: attaching one company's pledge to another company's symbol
    is worse than reporting no pledge for either.
    """
    index: Dict[str, str] = {}
    collisions: set[str] = set()
    for row in sm_rows:
        name = (row["company_name"] or "").strip()
        key = normalise_company_name(name)
        if not key:
            continue
        existing = index.get(key)
        if existing and existing != row["symbol"]:
            collisions.add(key)
            continue
        index[key] = row["symbol"]
    for key in collisions:
        index.pop(key, None)
    return index, sorted(collisions)


def resolve_symbols(rows: List[Dict[str, Any]], index: Dict[str, str]):
    """Attach a symbol to each parsed row. Returns (resolved, unresolved_names)."""
    resolved: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    for row in rows:
        symbol = index.get(row["name_key"])
        if not symbol:
            unresolved.append(row["company_name"])
            continue
        resolved.append({**row, "symbol": symbol})
    return resolved, sorted(unresolved)


async def run(csv_path: str, *, dry_run: bool = False,
              insert_missing: bool = False,
              refresh_features: bool = True) -> Dict[str, Any]:
    """Parse the dropped CSV and merge its pledge columns into shareholding_pattern."""
    run_id = uuid.uuid4()
    path = Path(csv_path)
    if not path.is_file():
        return {"status": "FAILED", "reason": f"no such file: {csv_path}"}

    text = path.read_text(encoding="utf-8-sig", errors="replace")
    parsed = parse_sast_csv(text)
    logger.info("nse_pledge_csv: %s — %s", path.name, parsed.summary)

    if not parsed.rows:
        return {"status": "FAILED", "reason": "no usable rows parsed", "file": path.name}
    if parsed.period_end is None:
        return {"status": "FAILED", "reason": "could not derive period_end (no BROADCAST DATE)",
                "file": path.name}

    stats = pledge_stats(parsed.rows)
    # Degeneracy check, same rule the screener's availability gate uses: a column
    # that is 100% populated with one repeated value reads as covered and screens
    # nothing. Refuse to write a file that carries no signal.
    if stats["distinct_values"] < 2:
        return {"status": "FAILED", "file": path.name,
                "reason": f"pledge column is degenerate — {stats['with_pledge_pct']} values, "
                          f"{stats['distinct_values']} distinct",
                "pledge_stats": stats}

    pool = await get_pool()
    async with pool.acquire() as conn:
        sm_rows = await conn.fetch(
            "SELECT symbol, company_name FROM nidp.sector_master "
            "WHERE company_name IS NOT NULL")
    index, collisions = build_name_index(sm_rows)
    resolved, unresolved = resolve_symbols(parsed.rows, index)

    result: Dict[str, Any] = {
        "status": "OK",
        "run_id": str(run_id),
        "file": path.name,
        "source": SOURCE_NAME,
        "period_end": parsed.period_end.isoformat(),
        "parsed_rows": len(parsed.rows),
        "ambiguous_csv_names": parsed.duplicate_names,
        "ambiguous_master_names": len(collisions),
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "unresolved_sample": unresolved[:20],
        "pledge_stats": stats,
    }
    if not resolved:
        result["status"] = "FAILED"
        result["reason"] = "no company name resolved to a NIDP symbol"
        return result

    if dry_run:
        result["status"] = "DRY_RUN"
        return result

    symbols = [r["symbol"] for r in resolved]
    pledged_pct = [r["promoter_pledged_pct"] for r in resolved]
    pledged_total_pct = [r["promoter_pledged_to_total_pct"] for r in resolved]
    pledged_shares = [r["pledged_shares"] for r in resolved]
    arrays = (symbols, pledged_pct, pledged_total_pct, pledged_shares, parsed.period_end)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # One statement over unnest()ed arrays rather than per-row round trips:
            # the command tag then gives the honest number of rows actually written,
            # which is the figure this run is judged on. executemany() reports none.
            #
            # Every row at this (symbol, period_end) is updated regardless of source.
            # Updating all of them — not only NSE_SHP — is what keeps the pledge value
            # identical whichever row v_shareholding_latest happens to pick.
            updated = _rowcount(await conn.execute("""
                UPDATE nidp.shareholding_pattern s
                   SET promoter_pledged_pct          = COALESCE(u.pp, s.promoter_pledged_pct),
                       promoter_pledged_to_total_pct = COALESCE(u.pt, s.promoter_pledged_to_total_pct),
                       pledged_shares                = COALESCE(u.ps, s.pledged_shares)
                  FROM unnest($1::text[], $2::numeric[], $3::numeric[], $4::bigint[])
                       AS u(sym, pp, pt, ps)
                 WHERE s.symbol = u.sym AND s.period_end = $5::date
            """, *arrays))

            inserted = 0
            if insert_missing:
                inserted = _rowcount(await conn.execute("""
                    INSERT INTO nidp.shareholding_pattern
                        (symbol, period_end, promoter_pledged_pct,
                         promoter_pledged_to_total_pct, pledged_shares,
                         source, source_run_id, ingested_at)
                    SELECT u.sym, $5::date, u.pp, u.pt, u.ps, $6::text, $7::uuid, NOW()
                      FROM unnest($1::text[], $2::numeric[], $3::numeric[], $4::bigint[])
                           AS u(sym, pp, pt, ps)
                     WHERE NOT EXISTS (
                        SELECT 1 FROM nidp.shareholding_pattern s
                         WHERE s.symbol = u.sym AND s.period_end = $5::date)
                """, *arrays, SOURCE_NAME, run_id))

    result["rows_updated"] = updated
    result["rows_inserted"] = inserted

    if updated == 0 and inserted == 0:
        # Not an error the caller should have to infer from a zero: the CSV parsed
        # and resolved, but no shareholding row exists for that quarter to carry it.
        result["status"] = "FAILED"
        result["reason"] = (
            f"no shareholding_pattern row exists at period_end={parsed.period_end} "
            f"for any of the {len(resolved)} resolved symbols; "
            f"re-run with --insert-missing to create pledge-only rows")
        return result

    if refresh_features:
        result["features_updated"] = await _refresh_features(pool)

    logger.info("nse_pledge_csv: done run=%s updated=%d inserted=%d unresolved=%d",
                run_id, updated, inserted, len(unresolved))
    return result


def _rowcount(tag: str) -> int:
    """asyncpg returns the command tag ('UPDATE 2244'); the count is its last word."""
    parts = (tag or "").split()
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0


async def _refresh_features(pool) -> int:
    """Push the pledge into the column the screener actually reads.

    Deliberately one column on one date, not a call to
    ``populate_stock_features_extended`` — that function rewrites ~20 columns for the
    whole universe from fundamentals and prices, which is a far larger blast radius
    than a pledge ingest has any business taking. The daily feature_snapshotter run
    reconciles everything else on its own schedule.
    """
    async with pool.acquire() as conn:
        as_of = await conn.fetchval(
            "SELECT MAX(as_of_date) FROM nidp.stock_features_daily")
        if as_of is None:
            return 0
        return _rowcount(await conn.execute(f"""
            UPDATE nidp.stock_features_daily f
               SET promoter_pledged_pct = v.{_FEATURE_SOURCE_COLUMN}
              FROM nidp.v_shareholding_latest v
             WHERE v.symbol = f.symbol
               AND f.as_of_date = $1::date
               AND v.{_FEATURE_SOURCE_COLUMN} IS NOT NULL
               AND f.promoter_pledged_pct IS DISTINCT FROM v.{_FEATURE_SOURCE_COLUMN}
        """, as_of))
