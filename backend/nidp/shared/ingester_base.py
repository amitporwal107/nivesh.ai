"""BaseIngester contract.

Every per-source service subclasses BaseIngester and implements:
    - SERVICE_NAME      class-attr, used for logs/metrics/topic
    - SOURCE_NAME       class-attr, registered in nidp.source_registry
    - KAFKA_TOPIC       class-attr, e.g. 'nidp.bulk_deals.v1'
    - AVRO_SCHEMA       class-attr, e.g. 'bulk_deals_v1' (file in contracts/)
    - async fetch(target_date) -> bytes
    - parse(body) -> list[dict]   (sync — pure, testable)
    - validate(rows) -> list[dict] (sync — drops/flags rows)
    - async persist(rows, run) -> int (rows inserted)

The base class wraps:
    - JobRun lifecycle (RUNNING → OK/FAILED/PARTIAL)
    - Raw archive write (sha256 dedup)
    - Prometheus timing
    - JSON log context binding
    - Kafka emit of IngestionCompleted event

Subclasses get free retry/observability without re-implementing the
loop. Failure isolation: an unhandled exception in fetch/parse/persist
fails the run cleanly, leaving no half-written facts (rows are
batched in a single transaction).
"""
from __future__ import annotations

import abc
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from nidp.shared.bus import get_bus
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, time_ingester,
)
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.raw_archive import store as store_raw
from nidp.shared.validation import run_validation as _run_validation
from nidp.shared.validation.rules import FailureClass

logger = logging.getLogger(__name__)


class BaseIngester(abc.ABC):
    SERVICE_NAME: str = ""               # e.g. "bulk_deals"
    SOURCE_NAME: str = ""                # e.g. "NSE_BULK"
    KAFKA_TOPIC: str = ""                # e.g. "nidp.bulk_deals.v1"
    AVRO_SCHEMA: str = ""                # filename stem under contracts/
    INGESTION_COMPLETED_TOPIC: str = "nidp.ingestion_completed.v1"
    INGESTION_COMPLETED_SCHEMA: str = "ingestion_completed_v1"

    # ── Hooks subclasses implement ──────────────────────────────────
    @abc.abstractmethod
    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        """Returns (body, source_url, http_status)."""

    @abc.abstractmethod
    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]: ...

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        """Default: pass-through. Override to drop bad rows.
        Returns (kept_rows, dropped_count)."""
        return rows, 0

    @abc.abstractmethod
    async def persist(self, rows: list[dict], run: JobRun) -> int: ...

    # Optional override: custom "completed" event payload.
    def build_completion_event(
        self, run: JobRun, target_date: Optional[date], rows_inserted: int,
    ) -> dict:
        return {
            "service": self.SERVICE_NAME,
            "source": self.SOURCE_NAME,
            "run_id": str(run.run_id),
            "target_date": target_date.isoformat() if target_date else None,
            "rows_fetched": run.rows_fetched,
            "rows_inserted": rows_inserted,
            "rows_skipped": run.rows_skipped,
            "artifact_path": run.artifact_path,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Orchestration loop ──────────────────────────────────────────
    async def run(self, target_date: Optional[date] = None) -> JobRun:
        bind_context(
            service=self.SERVICE_NAME,
            target_date=target_date.isoformat() if target_date else None,
        )

        async with JobRun(
            ingester=self.SERVICE_NAME,
            target_date=target_date,
        ) as run:
            bind_context(run_id=str(run.run_id))
            with time_ingester(self.SERVICE_NAME):
                try:
                    # 1. Fetch
                    body, source_url, http_status = await self.fetch(target_date)
                    run.source_url = source_url
                    if not body:
                        await run.finalize("SKIPPED", error_message="empty body")
                        INGESTER_RUNS.labels(
                            service=self.SERVICE_NAME, status="SKIPPED",
                        ).inc()
                        return run

                    # 2. Archive (raw bytes — replay substrate)
                    archive_id, abs_path = await store_raw(
                        ingester=self.SERVICE_NAME,
                        target_date=target_date,
                        source_url=source_url,
                        body=body,
                        http_status=http_status,
                        content_type=_guess_content_type(source_url),
                        metadata={"size": len(body)},
                    )
                    run.artifact_path = str(abs_path)

                    # 3. Parse
                    parsed_rows = self.parse(body, target_date)
                    run.rows_fetched = len(parsed_rows)
                    INGESTER_ROWS.labels(
                        service=self.SERVICE_NAME, kind="fetched",
                    ).inc(len(parsed_rows))

                    if not parsed_rows:
                        await run.finalize("SKIPPED", error_message="no rows in source")
                        INGESTER_RUNS.labels(
                            service=self.SERVICE_NAME, status="SKIPPED",
                        ).inc()
                        return run

                    # 4. Validate
                    kept, dropped = self.validate(parsed_rows)
                    run.rows_skipped = dropped
                    INGESTER_ROWS.labels(
                        service=self.SERVICE_NAME, kind="skipped",
                    ).inc(dropped)

                    # 5. Persist (with run-tag so revoke is one DELETE)
                    rows_inserted = await self.persist(kept, run)
                    run.rows_inserted = rows_inserted
                    INGESTER_ROWS.labels(
                        service=self.SERVICE_NAME, kind="inserted",
                    ).inc(rows_inserted)

                    # 6. Validate persisted facts (DQ engine)
                    validation = await _run_validation(
                        ingester=self.SERVICE_NAME,
                        target_date=target_date,
                        job_run_id=run.run_id,
                    )
                    run.metadata["validation_id"] = str(validation.validation_id)
                    run.metadata["validation_status"] = validation.status
                    run.metadata["findings_count"] = validation.findings_count
                    run.metadata["has_block"] = validation.has_block

                    # 7. Emit completion event (only if no BLOCK finding;
                    # downstream consumers must NOT see data we just
                    # condemned).
                    if not validation.has_block:
                        bus = get_bus()
                        payload = self.build_completion_event(
                            run, target_date, rows_inserted,
                        )
                        payload["validation_status"] = validation.status
                        payload["findings_count"] = validation.findings_count
                        await bus.publish(
                            self.INGESTION_COMPLETED_TOPIC,
                            key=str(run.run_id),
                            value=payload,
                            schema_name=self.INGESTION_COMPLETED_SCHEMA,
                            headers={"service": self.SERVICE_NAME},
                        )
                        await bus.flush(5.0)
                    else:
                        logger.error(
                            "ingester %s validation BLOCKED — completion "
                            "event SUPPRESSED (run_id=%s)",
                            self.SERVICE_NAME, run.run_id,
                        )

                    # 8. Final status reflects both ingestion + validation
                    if validation.has_block:
                        final_status = "FAILED"
                    elif validation.status == "PARTIAL" or dropped > 0:
                        final_status = "PARTIAL"
                    elif validation.status == "ERROR":
                        final_status = "PARTIAL"
                    else:
                        final_status = "OK"
                    await run.finalize(
                        final_status,
                        error_message=(
                            f"BLOCK validation: {validation.findings_count} finding(s)"
                            if validation.has_block else None
                        ),
                        error_class="VALIDATE" if validation.has_block else None,
                    )
                    INGESTER_RUNS.labels(
                        service=self.SERVICE_NAME, status=final_status,
                    ).inc()
                    return run

                except Exception as e:                             # noqa: BLE001
                    logger.exception("ingester %s failed", self.SERVICE_NAME)
                    INGESTER_RUNS.labels(
                        service=self.SERVICE_NAME, status="FAILED",
                    ).inc()
                    raise


def _guess_content_type(url: str) -> str:
    p = urlsplit(url).path.lower()
    if p.endswith(".csv"):  return "text/csv"
    if p.endswith(".zip"):  return "application/zip"
    if p.endswith(".xls"):  return "application/vnd.ms-excel"
    if p.endswith(".xlsx"): return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if p.endswith(".json"): return "application/json"
    if p.endswith(".xml"):  return "application/xml"
    return "application/octet-stream"
