"""Gate 5 — Warm-Tier Export Gate.

Implements the verify-then-rename pattern for Parquet exports:

  1. Export to   parquet/{table}/year=Y/month=M/_tmp/{date}.parquet
  2. Verify row count matches source TimescaleDB query (G5-EXP-001)
  3. Verify Parquet file is valid and readable (G5-EXP-004)
  4. Atomic rename: move _tmp/{date}.parquet → {date}.parquet
  5. On failure: delete _tmp file, record FAIL verdict, raise

This module is called from parquet_exporter/service.py for each table.
Gate verdicts are written to dq.gate_verdicts.
"""
from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

GATE_ID   = 5
GATE_NAME = "warm_tier_export"


class ParquetExportGate:
    """Verify a Parquet table + key against a known expected row count.

    Usage::

        gate = ParquetExportGate(s3, bucket, conn)
        await gate.verify_and_finalize(
            table="stock_features_daily",
            tmp_key="parquet/.../year=2026/month=05/_tmp/2026-05-27.parquet",
            final_key="parquet/.../year=2026/month=05/2026-05-27.parquet",
            expected_rows=1987,
            export_date=date(2026, 5, 27),
        )
    """

    def __init__(self, s3, bucket: str, conn=None) -> None:
        self._s3     = s3
        self._bucket = bucket
        self._conn   = conn   # asyncpg connection for verdict persistence (optional)

    async def verify_and_finalize(
        self,
        table: str,
        tmp_key: str,
        final_key: str,
        expected_rows: int,
        export_date: date,
        job_run_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Run all Gate 5 checks. On success: rename tmp→final. On failure: delete tmp."""
        checks: list[dict] = []
        verdict_ok = True

        # ── G5-EXP-004: file is valid and readable ────────────────────────
        row_count_actual, read_err = self._read_parquet_row_count(tmp_key)
        if read_err:
            checks.append({
                "name": "G5-EXP-004",
                "passed": False,
                "severity": "P0",
                "message": f"Parquet file not readable: {read_err}",
            })
            verdict_ok = False
        else:
            checks.append({
                "name": "G5-EXP-004",
                "passed": True,
                "severity": "P0",
                "message": f"Parquet file valid, {row_count_actual} rows",
            })

            # ── G5-EXP-001: row count matches source ─────────────────────
            if row_count_actual != expected_rows:
                checks.append({
                    "name": "G5-EXP-001",
                    "passed": False,
                    "severity": "P0",
                    "message": (
                        f"Row count mismatch: parquet={row_count_actual} "
                        f"source={expected_rows}"
                    ),
                    "details": {
                        "parquet_rows": row_count_actual,
                        "expected_rows": expected_rows,
                    },
                })
                verdict_ok = False
            else:
                checks.append({
                    "name": "G5-EXP-001",
                    "passed": True,
                    "severity": "P0",
                    "message": f"Row count matches source: {expected_rows}",
                    "details": {"rows": expected_rows},
                })

        # ── Act on verdict ────────────────────────────────────────────────
        if verdict_ok:
            # Atomic rename: copy to final key, delete tmp
            self._rename_object(tmp_key, final_key)
            verdict = "PASS"
            severity = "OK"
            logger.info(
                "gate5[%s] PASS: %d rows verified → %s",
                table, expected_rows, final_key,
            )
        else:
            # Delete tmp — do not expose corrupt/partial file
            self._delete_object(tmp_key)
            verdict = "FAIL"
            severity = "P0"
            logger.error(
                "gate5[%s] FAIL: checks=%s — tmp deleted, partition unchanged",
                table,
                [c["message"] for c in checks if not c["passed"]],
            )

        # ── Persist verdict ───────────────────────────────────────────────
        if self._conn is not None:
            await self._persist(
                table=table,
                checks=checks,
                verdict=verdict,
                severity=severity,
                export_date=export_date,
                job_run_id=job_run_id,
            )

        if not verdict_ok:
            raise RuntimeError(
                f"Gate 5 FAIL for {table}/{export_date}: "
                + "; ".join(c["message"] for c in checks if not c["passed"])
            )

        return {"table": table, "verdict": verdict, "rows": expected_rows, "key": final_key}

    # ── Parquet helpers ───────────────────────────────────────────────────────

    def _read_parquet_row_count(self, key: str) -> tuple[int, Optional[str]]:
        """Download tmp object and count rows via pyarrow. Returns (count, error)."""
        try:
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError:
            return 0, "pyarrow not installed"
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
            buf  = io.BytesIO(resp["Body"].read())
            pf   = pq.ParquetFile(buf)
            return pf.metadata.num_rows, None
        except Exception as exc:                                    # noqa: BLE001
            return 0, str(exc)

    def _rename_object(self, src_key: str, dst_key: str) -> None:
        """Copy src → dst then delete src (S3 has no atomic rename)."""
        self._s3.copy_object(
            Bucket=self._bucket,
            CopySource={"Bucket": self._bucket, "Key": src_key},
            Key=dst_key,
        )
        self._s3.delete_object(Bucket=self._bucket, Key=src_key)

    def _delete_object(self, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:                                    # noqa: BLE001
            logger.warning("gate5: failed to delete tmp %s: %s", key, exc)

    # ── Verdict persistence ───────────────────────────────────────────────────

    async def _persist(
        self,
        table: str,
        checks: list[dict],
        verdict: str,
        severity: str,
        export_date: date,
        job_run_id: Optional[uuid.UUID],
    ) -> None:
        verdict_id = uuid.uuid4()
        details    = {"checks": checks}
        try:
            await self._conn.execute(
                """
                INSERT INTO dq.gate_verdicts
                    (id, gate_id, feed, target_date, job_run_id,
                     verdict, severity, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                verdict_id,
                GATE_ID,
                table,
                export_date,
                job_run_id,
                verdict,
                severity,
                json.dumps(details),
            )
        except Exception as exc:                                    # noqa: BLE001
            logger.error("gate5: verdict persist failed: %s", exc)
