"""nidp-mf-disclosure-snapshot — orchestrator.

Walks the per-AMC adapter registry, accumulates snapshot rows, persists
them under (scheme_code, snapshot_date), and runs the diff to emit
mf_scheme_events. AMCs without an implemented adapter are skipped
with a warning; the run finalises PARTIAL when any adapter is missing
or fails.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S, MF_AMC_TOP10
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, time_ingester,
)
from nidp.shared.storage.job_log import JobRun

from .amc_dispatch import ADAPTERS
from .diff import emit_events_from_snapshot
from .writer import upsert_snapshot

logger = logging.getLogger(__name__)

SERVICE_NAME = "mf_disclosure_snapshot"


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    bind_context(service=SERVICE_NAME)
    snapshot_date = target_date or date.today()

    async with JobRun(ingester=SERVICE_NAME, target_date=snapshot_date) as run:
        bind_context(run_id=str(run.run_id))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": DEFAULT_UA}

        # Merge rows by scheme_code so multiple sources (per-AMC AUM/manager +
        # central AMFI TER) combine into one row instead of overwriting each
        # other — the upsert is last-write-wins per (scheme_code, snapshot_date).
        merged: dict[str, dict] = {}

        def _merge(row: dict) -> None:
            code = row.get("scheme_code")
            if not code:
                return
            code = str(code)
            cur = merged.get(code)
            if cur is None:
                merged[code] = dict(row)
                return
            for k, v in row.items():
                if v is not None and cur.get(k) is None:
                    cur[k] = v

        adapters_missing = 0
        adapters_failed = 0
        ter_central = 0
        aaum_central = 0
        factsheet_aum = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                from nidp.shared.archive import archive_raw
                import json as _json
                for amc_id in MF_AMC_TOP10:
                    fn = ADAPTERS.get(amc_id)
                    if fn is None:
                        adapters_missing += 1
                        logger.warning("no adapter registered for amc_id=%s", amc_id)
                        continue
                    try:
                        rows = await fn(session)
                    except Exception as e:                              # noqa: BLE001
                        adapters_failed += 1
                        logger.warning("amc=%s adapter raised: %s: %s",
                                       amc_id, type(e).__name__, e)
                        continue
                    if not rows:
                        # Stub adapters return [] — counted as missing.
                        adapters_missing += 1
                        continue
                    try:
                        archive_raw(SERVICE_NAME, snapshot_date,
                                    f"{amc_id}.parsed.json",
                                    _json.dumps(rows, default=str).encode("utf-8"))
                    except Exception:                                    # noqa: BLE001
                        pass
                    for r in rows:
                        _merge(r)

                # Central AMFI TER pass — the AMFI JSON API publishes TER for the
                # whole universe in one place (per-AMC TER scrapers cover only a
                # couple of houses). This is the authoritative TER source, so it
                # overrides any per-AMC TER while leaving AUM/manager/risk intact.
                try:
                    from .amfi_api import fetch_ter_all_amfi_api
                    ter_map = await fetch_ter_all_amfi_api(session)
                    for code, (r_ter, d_ter) in ter_map.items():
                        row = merged.setdefault(str(code), {
                            "scheme_code": str(code),
                            "source_url": "https://www.amfiindia.com/api/populate-te-rdata-revised",
                        })
                        if r_ter is not None:
                            row["ter_pct"] = r_ter
                        if d_ter is not None:
                            row["ter_pct_direct"] = d_ter
                        if not row.get("source_url"):
                            row["source_url"] = "https://www.amfiindia.com/api/populate-te-rdata-revised"
                    ter_central = len(ter_map)
                    logger.info("mf_disclosure_snapshot: central TER pass merged %d schemes", ter_central)
                except Exception as e:                                  # noqa: BLE001
                    logger.warning("mf_disclosure_snapshot: central TER pass failed: %s: %s",
                                   type(e).__name__, e)

                # Central AMFI AAUM pass — scheme-wise Average AUM (₹ crore) keyed
                # by AMFI code (no name resolution needed). Per-plan AAUM; the
                # scorecard view sums it to fund level for display. Authoritative,
                # so it overrides any per-AMC AUM (only UTI had one).
                try:
                    from .amfi_api import fetch_aaum_all_amfi_api
                    aaum_map = await fetch_aaum_all_amfi_api(session)
                    for code, aum_cr in aaum_map.items():
                        row = merged.setdefault(str(code), {
                            "scheme_code": str(code),
                            "source_url": "https://www.amfiindia.com/api/average-aum-schemewise",
                        })
                        row["aum_inr_crore"] = aum_cr
                        if not row.get("source_url"):
                            row["source_url"] = "https://www.amfiindia.com/api/average-aum-schemewise"
                    aaum_central = len(aaum_map)
                    logger.info("mf_disclosure_snapshot: central AAUM pass merged %d schemes", aaum_central)
                except Exception as e:                                  # noqa: BLE001
                    logger.warning("mf_disclosure_snapshot: central AAUM pass failed: %s: %s",
                                   type(e).__name__, e)

                # Per-AMC factsheet AAUM pass — the AMFI schemewise AAUM API
                # only resolves a fraction of the universe, so each AMC's
                # monthly factsheet PDF backfills the AUM it misses. Fund-level
                # AAUM is written to every plan variant (see factsheet.py).
                # Fills only where the authoritative central pass had nothing,
                # so it never overrides a real AMFI AAUM value.
                try:
                    from .factsheet import FACTSHEET_SOURCES, fetch_factsheet_aum
                    for amc_id in FACTSHEET_SOURCES:
                        fs_rows = await fetch_factsheet_aum(amc_id, session, snapshot_date)
                        for r in fs_rows:
                            row = merged.setdefault(r["scheme_code"], {
                                "scheme_code": r["scheme_code"],
                                "source_url": r.get("source_url"),
                            })
                            if row.get("aum_inr_crore") is None:
                                row["aum_inr_crore"] = r["aum_inr_crore"]
                                if not row.get("source_url"):
                                    row["source_url"] = r.get("source_url")
                                factsheet_aum += 1
                    logger.info("mf_disclosure_snapshot: factsheet AAUM pass filled %d schemes", factsheet_aum)
                except Exception as e:                                  # noqa: BLE001
                    logger.warning("mf_disclosure_snapshot: factsheet AAUM pass failed: %s: %s",
                                   type(e).__name__, e)

            all_rows = list(merged.values())
            n_rows = await upsert_snapshot(all_rows, snapshot_date, run.run_id)
            n_events = await emit_events_from_snapshot(snapshot_date, run.run_id)

            run.rows_fetched = len(all_rows)
            run.rows_inserted = n_rows
            run.metadata["events_emitted"] = n_events
            run.metadata["adapters_missing"] = adapters_missing
            run.metadata["adapters_failed"] = adapters_failed
            run.metadata["ter_central"] = ter_central
            run.metadata["aaum_central"] = aaum_central
            run.metadata["factsheet_aum"] = factsheet_aum

            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="fetched").inc(len(all_rows))
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(n_rows)

            # Status decision (2026-05-21 reclassification):
            #   OK       — every adapter delivered
            #   PARTIAL  — some adapters delivered, some failed/missing
            #   FAILED   — zero rows produced. See mf_holdings/service.py for
            #              the full rationale (project_amc_scrapers_broken.md).
            total_adapters = len(MF_AMC_TOP10)
            no_data = len(all_rows) == 0 or n_rows == 0
            if no_data:
                final = "FAILED"
            elif adapters_missing > 0 or adapters_failed > 0:
                final = "PARTIAL"
            else:
                final = "OK"
            await run.finalize(final, error_message=(
                f"missing={adapters_missing}/{total_adapters} "
                f"failed={adapters_failed} rows={len(all_rows)} "
                f"events={n_events}"
                if final != "OK" else None
            ))
            INGESTER_RUNS.labels(service=SERVICE_NAME, status=final).inc()
            return run.run_id
