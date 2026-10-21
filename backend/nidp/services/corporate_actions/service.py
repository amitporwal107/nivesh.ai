"""nidp-corporate-actions service."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import CORPORATE_ACTIONS_URL_ROLLING, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_corporate_actions
from .writer import SOURCE_NAME, upsert_corporate_actions

logger = logging.getLogger(__name__)

# NSE publishes corporate actions per board: main board ("equities"), SME
# ("sme") and ETFs/mutual-fund units ("mf"). ETF unit splits (e.g. GOLDADD,
# IVZINGOLD) and SME bonuses/splits live ONLY under the latter two.
CA_INDEXES = ("equities", "sme", "mf")
CA_REFERER = f"{NSE_WWW}/companies-listing/corporate-filings-actions"
BACKFILL_CHUNK_DAYS = 31
BACKFILL_PAUSE_S = 2.0


def rolling_url(index: str) -> str:
    """Rolling feed (upcoming ex-dates only: ~1 week ahead, nothing historical)."""
    return CORPORATE_ACTIONS_URL_ROLLING.replace("index=equities", f"index={index}")


def range_url(index: str, from_date: date, to_date: date) -> str:
    """Historical window; NSE wants DD-MM-YYYY for both bounds."""
    return (f"{rolling_url(index)}&from_date={from_date:%d-%m-%Y}"
            f"&to_date={to_date:%d-%m-%Y}")


def date_chunks(from_date: date, to_date: date, days: int = BACKFILL_CHUNK_DAYS):
    """Inclusive, gap-free, non-overlapping windows of at most `days` days."""
    if to_date < from_date:
        raise ValueError(f"to_date {to_date} is before from_date {from_date}")
    out, start = [], from_date
    while start <= to_date:
        end = min(start + timedelta(days=days - 1), to_date)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


async def _pace_between_calls() -> None:
    await asyncio.sleep(BACKFILL_PAUSE_S)


class CorporateActionsIngester(BaseIngester):
    SERVICE_NAME = "corporate_actions"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.corporate_actions.v1"
    AVRO_SCHEMA = "corporate_actions_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = CORPORATE_ACTIONS_URL_ROLLING
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=CA_REFERER,
                    extra_headers={"Accept": "application/json"},
                    archive_as=("corporate_actions", target_date, "corporate_actions.json"),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise
        # SME and ETF/MF boards are separate NSE indexes. They are best-effort:
        # the main board above is the required feed, so a failure here is logged
        # (never swallowed silently) and the equities rows still land.
        extra: list = []
        for index in CA_INDEXES[1:]:
            try:
                part, _ = await fetch_bytes(
                    rolling_url(index),
                    referer=CA_REFERER,
                    extra_headers={"Accept": "application/json"},
                    archive_as=("corporate_actions", target_date, f"corporate_actions_{index}.json"),
                )
                extra.extend(_json_rows(part))
            except Exception as e:  # noqa: BLE001
                logger.warning("corporate_actions: %s board fetch failed: %s", index, e)
        if extra:
            body = json.dumps(_json_rows(body) + extra).encode("utf-8")
        return body, url, status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_corporate_actions(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r["symbol"] and r["ex_date"] and r["action_type"]):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_corporate_actions(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['symbol']}|{r['action_type']}|{r['ex_date']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


def _json_rows(body: bytes) -> list:
    """NSE returns a JSON array; an empty board answers {"data":[],"msg":...}."""
    payload = json.loads(body.decode("utf-8-sig", errors="replace") or "[]")
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    if not isinstance(payload, list):
        raise ValueError(f"corporate_actions: expected JSON array, got {type(payload).__name__}")
    return payload


async def backfill(from_date: date, to_date: date,
                   indexes: tuple[str, ...] = CA_INDEXES) -> dict:
    """Load historical corporate actions for [from_date, to_date].

    The rolling feed only lists upcoming ex-dates, so anything that went
    ex before the table existed (or before a missed run) has to come from the
    date-range endpoint. Fails loudly on any fetch error: a silent partial
    backfill would leave some splits unadjusted with no sign of it.
    Idempotent: the writer upserts on (symbol, action_type, ex_date, source).
    """
    run_id = uuid.uuid4()
    fetched = 0
    unique: set[tuple] = set()
    by_type: dict[str, int] = {}
    for start, end in date_chunks(from_date, to_date):
        for index in indexes:
            body, _ = await fetch_bytes(
                range_url(index, start, end),
                referer=CA_REFERER,
                extra_headers={"Accept": "application/json"},
                archive_as=("corporate_actions", start, f"corporate_actions_{index}_{start:%Y%m%d}_{end:%Y%m%d}.json"),
            )
            rows = [r for r in parse_corporate_actions(json.dumps(_json_rows(body)).encode())
                    if r["symbol"] and r["ex_date"] and r["action_type"]]
            await upsert_corporate_actions(rows, run_id)
            fetched += len(rows)
            for r in rows:
                unique.add((r["symbol"], r["action_type"], r["ex_date"]))
                by_type[r["action_type"]] = by_type.get(r["action_type"], 0) + 1
            logger.info("corporate_actions backfill %s %s..%s rows=%d", index, start, end, len(rows))
            await _pace_between_calls()
    summary = {"run_id": str(run_id), "from": str(from_date), "to": str(to_date),
               "fetched": fetched, "unique": len(unique), "by_type": by_type}
    logger.info("corporate_actions backfill done: %s", summary)
    return summary


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await CorporateActionsIngester().run(target_date)
    return job.run_id
