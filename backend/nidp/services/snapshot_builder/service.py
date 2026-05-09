"""Snapshot orchestrator.

Sequence:
    1. Preflight — check no BLOCK validation findings, hard-required
       domains present.
    2. Build market_daily_snapshot.
    3. Build stock_daily_snapshot.
    4. Update nidp.daily_snapshot.snapshot_status = READY.
    5. Emit SnapshotReadyV1 on the bus.

Idempotent: re-running for the same date overwrites both snapshot
tables in single transactions and produces a fresh build_run_id.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import time_ingester, INGESTER_RUNS, INGESTER_ROWS
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import get_pool

from .market_builder import build_market
from .preconditions import preflight
from .stock_builder import build_stocks

logger = logging.getLogger(__name__)

SERVICE_NAME = "snapshot_builder"
SNAPSHOT_TOPIC = "nidp.snapshot_ready.v1"
SNAPSHOT_SCHEMA = "snapshot_ready_v1"


async def _mark_daily_snapshot_status(
    conn, target_date: date, status: str, run_id: uuid.UUID,
) -> None:
    """Upsert nidp.daily_snapshot — the per-date readiness marker that
    downstream feature/signal services key on."""
    await conn.execute(
        """
        INSERT INTO nidp.daily_snapshot (
            as_of_date, snapshot_status,
            prices_eod_ready, delivery_ready, index_eod_ready,
            fii_dii_ready, corp_actions_ready, bulk_deals_ready,
            block_deals_ready, rbi_yields_ready,
            built_at, build_run_ids
        ) VALUES (
            $1::date, $2,
            (SELECT EXISTS(SELECT 1 FROM nidp.prices_eod    WHERE as_of_date=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.delivery_data WHERE as_of_date=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.index_eod     WHERE as_of_date=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.fii_dii_flows WHERE as_of_date=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.corporate_actions WHERE ex_date>=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.bulk_deals    WHERE as_of_date=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.block_deals   WHERE as_of_date=$1::date)),
            (SELECT EXISTS(SELECT 1 FROM nidp.rbi_yields    WHERE as_of_date=$1::date)),
            NOW(), ARRAY[$3]::uuid[]
        )
        ON CONFLICT (as_of_date) DO UPDATE SET
            snapshot_status     = EXCLUDED.snapshot_status,
            prices_eod_ready    = EXCLUDED.prices_eod_ready,
            delivery_ready      = EXCLUDED.delivery_ready,
            index_eod_ready     = EXCLUDED.index_eod_ready,
            fii_dii_ready       = EXCLUDED.fii_dii_ready,
            corp_actions_ready  = EXCLUDED.corp_actions_ready,
            bulk_deals_ready    = EXCLUDED.bulk_deals_ready,
            block_deals_ready   = EXCLUDED.block_deals_ready,
            rbi_yields_ready    = EXCLUDED.rbi_yields_ready,
            rebuilt_at          = NOW(),
            build_run_ids       = nidp.daily_snapshot.build_run_ids || EXCLUDED.build_run_ids
        """,
        target_date, status, run_id,
    )


async def run(target_date: date, *, force: bool = False) -> uuid.UUID:
    """Build the snapshot for `target_date`.

    `force=True` skips the BLOCK precondition (use only when manually
    overriding after triage)."""
    bind_context(service=SERVICE_NAME, target_date=target_date.isoformat())

    async with JobRun(ingester=SERVICE_NAME, target_date=target_date) as run_:
        bind_context(run_id=str(run_.run_id))
        with time_ingester(SERVICE_NAME):
            pool = await get_pool()
            async with pool.acquire() as conn:
                # 1. Preflight
                pre = await preflight(conn, target_date)
                if not pre.ok and not force:
                    msg = "snapshot preflight FAILED: " + "; ".join(pre.reasons[:3])
                    await _mark_daily_snapshot_status(
                        conn, target_date, "INCOMPLETE", run_.run_id,
                    )
                    await run_.finalize(
                        "FAILED",
                        error_message=msg[:2000],
                        error_class="PRECONDITION",
                    )
                    INGESTER_RUNS.labels(
                        service=SERVICE_NAME, status="FAILED",
                    ).inc()
                    raise RuntimeError(msg)
                if not pre.ok and force:
                    logger.warning(
                        "snapshot %s: forcing build despite %d preflight issue(s)",
                        target_date, len(pre.reasons),
                    )

                # 2. Market
                market = await build_market(conn, target_date, run_.run_id)

                # 3. Stocks
                stocks = await build_stocks(conn, target_date, run_.run_id)

                # 4. Mark daily_snapshot READY
                await _mark_daily_snapshot_status(
                    conn, target_date, "READY", run_.run_id,
                )

            run_.rows_inserted = market.rows + stocks.rows
            INGESTER_ROWS.labels(
                service=SERVICE_NAME, kind="inserted",
            ).inc(market.rows + stocks.rows)

            # 5. Emit SnapshotReadyV1
            bus = get_bus()
            domains_present: list[str] = []
            for dom in ("prices_eod", "delivery_data", "index_eod",
                        "fii_dii_flows", "corporate_actions",
                        "bulk_deals", "block_deals", "rbi_yields"):
                async with pool.acquire() as conn2:
                    has = await conn2.fetchval(
                        f"SELECT EXISTS(SELECT 1 FROM nidp.{dom} "
                        f" WHERE {'as_of_date' if dom != 'corporate_actions' else 'ex_date'} "
                        f" {'=' if dom != 'corporate_actions' else '>='} $1::date)",
                        target_date,
                    )
                if has:
                    domains_present.append(dom)

            cf_payload = [
                {"domain": cf.domain, "as_of_date": cf.as_of.isoformat(),
                 "lag_days": cf.lag_days}
                for cf in market.carry_forward
            ]
            warnings = list(market.warnings) + list(stocks.warnings) + pre.reasons

            await bus.publish(
                SNAPSHOT_TOPIC,
                key=target_date.isoformat(),
                value={
                    "as_of_date": target_date.isoformat(),
                    "build_run_id": str(run_.run_id),
                    "stock_rows_built": stocks.rows,
                    "market_built": bool(market.rows),
                    "domains_present": domains_present,
                    "domains_carried_forward": cf_payload,
                    "warnings": warnings[:20],
                    "built_at": datetime.now(timezone.utc).isoformat(),
                },
                schema_name=SNAPSHOT_SCHEMA,
            )
            await bus.flush(60.0)

            run_.metadata["market_rows"] = market.rows
            run_.metadata["stock_rows"] = stocks.rows
            run_.metadata["carry_forward"] = cf_payload
            await run_.finalize("OK")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="OK").inc()
            return run_.run_id


async def status(target_date: Optional[date] = None) -> dict:
    """Return readiness state for the requested date (or latest)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if target_date is not None:
            row = await conn.fetchrow(
                "SELECT * FROM nidp.daily_snapshot WHERE as_of_date = $1::date",
                target_date,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM nidp.daily_snapshot ORDER BY as_of_date DESC LIMIT 1",
            )
    return dict(row) if row else {}
