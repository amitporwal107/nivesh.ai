"""Price adjuster — derive nidp.prices_eod_adjusted from prices_eod
and corporate_actions.

Strategy:
    1. Load every row from nidp.prices_eod (or scoped: --since DATE,
       --symbols X,Y,Z) into memory, grouped by symbol.
    2. Load every SPLIT/BONUS/DIVIDEND row from nidp.corporate_actions
       with the structured fields needed to derive a factor.
    3. For each symbol independently:
         a. Build the prev-close lookup dict.
         b. Normalise CA rows → CorpActionEvents (factors computed).
         c. For every price row, compute cumulative_factor and write
            adjusted prices.
    4. Bulk insert into nidp.prices_eod_adjusted via executemany.

Performance: full Nifty 500 × 5 yr ≈ 600k rows × maybe ~3k events.
Done as a single in-process pass on a dev laptop in <30s. For
production scale we can shard by symbol; keep simple for now.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from nidp.shared.storage.pg import get_pool

from .factors import (
    CorpActionEvent,
    build_events,
    cumulative_factors_for_dates,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "NIDP_PRICE_ADJUSTER"


@dataclass
class AdjusterReport:
    run_id: str
    started_at: float
    symbols_processed: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    events_total: int = 0
    events_split: int = 0
    events_bonus: int = 0
    events_dividend: int = 0
    duration_ms: int = 0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "run_id":            self.run_id,
            "symbols_processed": self.symbols_processed,
            "rows_written":      self.rows_written,
            "rows_skipped":      self.rows_skipped,
            "events_total":      self.events_total,
            "events_split":      self.events_split,
            "events_bonus":      self.events_bonus,
            "events_dividend":   self.events_dividend,
            "duration_ms":       self.duration_ms,
            "errors":            self.errors[:20],
        }


async def run(
    *,
    since: Optional[date] = None,
    symbols: Optional[List[str]] = None,
    include_dividends: bool = True,
) -> AdjusterReport:
    """Recompute prices_eod_adjusted for the given scope.

    Args:
        since: only adjust rows with as_of_date >= since. Default None
               = all-history (full rebuild).
        symbols: scope to a list of symbols. Default None = entire
               EQ universe.
        include_dividends: whether to compute tret_close. False is
               faster (no per-symbol prev-close lookups) for use cases
               that only need price-return numbers.
    """
    started = time.monotonic()
    run_id = str(uuid.uuid4())
    report = AdjusterReport(run_id=run_id, started_at=started)

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 1. Load price rows
        prices = await _load_prices(conn, since=since, symbols=symbols)
        # 2. Load corp-action rows
        actions = await _load_actions(conn, symbols=symbols)

    # 3. Build prev-close lookup (used only for dividends).
    prev_close: Dict[Tuple[str, date], float] = {}
    if include_dividends:
        per_symbol_dates: Dict[str, List[Tuple[date, float]]] = defaultdict(list)
        for r in prices:
            per_symbol_dates[r["symbol"]].append((r["as_of_date"], r["close_price"]))
        for sym, lst in per_symbol_dates.items():
            lst.sort(key=lambda t: t[0])
            for i in range(1, len(lst)):
                prev_close[(sym, lst[i][0])] = lst[i - 1][1]

    def _prev_close(symbol: str, ex_date: date) -> Optional[float]:
        # Get close on the trading day strictly before ex_date
        return prev_close.get((symbol, ex_date))

    # 4. Group actions by symbol; build events per symbol
    actions_by_symbol: Dict[str, List[dict]] = defaultdict(list)
    for a in actions:
        actions_by_symbol[a["symbol"]].append(a)

    events_by_symbol: Dict[str, List[CorpActionEvent]] = {}
    for sym, raws in actions_by_symbol.items():
        evts = build_events(raws, _prev_close if include_dividends else lambda s, d: None)
        events_by_symbol[sym] = evts
        report.events_total += len(evts)
        for e in evts:
            if e.action_type == "SPLIT":      report.events_split += 1
            elif e.action_type == "BONUS":    report.events_bonus += 1
            elif e.action_type == "DIVIDEND": report.events_dividend += 1

    # 5. Compute adjusted rows
    prices_by_symbol: Dict[str, List[dict]] = defaultdict(list)
    for r in prices:
        prices_by_symbol[r["symbol"]].append(r)

    output_rows: List[dict] = []
    for sym, rows in prices_by_symbol.items():
        rows.sort(key=lambda r: r["as_of_date"])
        target_dates = [r["as_of_date"] for r in rows]
        events = events_by_symbol.get(sym, [])
        cumfactors = cumulative_factors_for_dates(events, target_dates)
        for r, (cum_pret, cum_tret, last_ex, last_type) in zip(rows, cumfactors):
            close = r["close_price"]
            if close is None or close <= 0:
                report.rows_skipped += 1
                continue
            adj_close = close * cum_pret
            tret_close = close * cum_tret if include_dividends else None
            output_rows.append({
                "symbol":                 sym,
                "as_of_date":             r["as_of_date"],
                "raw_open":               r.get("open_price"),
                "raw_high":               r.get("high_price"),
                "raw_low":                r.get("low_price"),
                "raw_close":              close,
                "raw_volume":             r.get("traded_volume"),
                "adj_open":               _scale(r.get("open_price"), cum_pret),
                "adj_high":               _scale(r.get("high_price"), cum_pret),
                "adj_low":                _scale(r.get("low_price"), cum_pret),
                "adj_close":              round(adj_close, 6),
                "adj_volume":             _scale_volume(r.get("traded_volume"), cum_pret),
                "tret_close":             round(tret_close, 6) if tret_close else None,
                "cumulative_adj_factor":  round(cum_pret, 8),
                "cumulative_tret_factor": round(cum_tret, 8),
                "last_event_ex_date":     last_ex,
                "last_event_type":        last_type,
            })
        report.symbols_processed += 1

    # 6. Bulk insert
    if output_rows:
        report.rows_written = await _upsert_adjusted(output_rows, run_id)

    report.duration_ms = int((time.monotonic() - started) * 1000)
    logger.info("price_adjuster done: %s", report.as_dict())
    return report


def _scale(value: Optional[float], factor: float) -> Optional[float]:
    if value is None:
        return None
    return round(value * factor, 6)


def _scale_volume(volume: Optional[int], factor: float) -> Optional[int]:
    """Volume scales INVERSELY: a 1:1 split doubles share count, so
    historical volumes (in pre-split shares) need to be doubled to
    line up with post-split share counts."""
    if volume is None or factor <= 0:
        return None
    return int(round(volume / factor))


# ── DB helpers ──────────────────────────────────────────────────────
async def _load_prices(conn, *, since: Optional[date], symbols: Optional[List[str]]) -> List[dict]:
    where = ["close_price IS NOT NULL"]
    args: list = []
    if since:
        args.append(since)
        where.append(f"as_of_date >= ${len(args)}::date")
    if symbols:
        args.append(symbols)
        where.append(f"symbol = ANY(${len(args)}::text[])")
    # nidp.prices_eod uses `volume` (not `traded_volume`); alias for
    # consistency with our internal dict shape.
    sql = f"""
        SELECT symbol, as_of_date,
               open_price, high_price, low_price, close_price,
               volume AS traded_volume
          FROM nidp.prices_eod
         WHERE {' AND '.join(where)}
    """
    rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def _load_actions(conn, *, symbols: Optional[List[str]]) -> List[dict]:
    where = ["action_type IN ('SPLIT','BONUS','DIVIDEND')",
             "ex_date IS NOT NULL"]
    args: list = []
    if symbols:
        args.append(symbols)
        where.append(f"symbol = ANY(${len(args)}::text[])")
    sql = f"""
        SELECT symbol, action_type, ex_date,
               face_value_pre, face_value_post,
               ratio, dividend_amount
          FROM nidp.corporate_actions
         WHERE {' AND '.join(where)}
    """
    rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def _upsert_adjusted(rows: List[dict], run_id: str) -> int:
    pool = await get_pool()
    args = [(
        r["symbol"], r["as_of_date"],
        r.get("raw_open"), r.get("raw_high"), r.get("raw_low"),
        r["raw_close"], r.get("raw_volume"),
        r.get("adj_open"), r.get("adj_high"), r.get("adj_low"),
        r["adj_close"], r.get("adj_volume"),
        r.get("tret_close"),
        r["cumulative_adj_factor"], r["cumulative_tret_factor"],
        r.get("last_event_ex_date"), r.get("last_event_type"),
        SOURCE_NAME, run_id,
    ) for r in rows]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.prices_eod_adjusted
                    (symbol, as_of_date,
                     raw_open, raw_high, raw_low, raw_close, raw_volume,
                     adj_open, adj_high, adj_low, adj_close, adj_volume,
                     tret_close,
                     cumulative_adj_factor, cumulative_tret_factor,
                     last_event_ex_date, last_event_type,
                     source, source_run_id, ingested_at)
                VALUES ($1, $2::date,
                        $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12,
                        $13,
                        $14, $15,
                        $16::date, $17,
                        $18, $19, NOW())
                ON CONFLICT (symbol, as_of_date, source) DO UPDATE SET
                    raw_open                = EXCLUDED.raw_open,
                    raw_high                = EXCLUDED.raw_high,
                    raw_low                 = EXCLUDED.raw_low,
                    raw_close               = EXCLUDED.raw_close,
                    raw_volume              = EXCLUDED.raw_volume,
                    adj_open                = EXCLUDED.adj_open,
                    adj_high                = EXCLUDED.adj_high,
                    adj_low                 = EXCLUDED.adj_low,
                    adj_close               = EXCLUDED.adj_close,
                    adj_volume              = EXCLUDED.adj_volume,
                    tret_close              = EXCLUDED.tret_close,
                    cumulative_adj_factor   = EXCLUDED.cumulative_adj_factor,
                    cumulative_tret_factor  = EXCLUDED.cumulative_tret_factor,
                    last_event_ex_date      = EXCLUDED.last_event_ex_date,
                    last_event_type         = EXCLUDED.last_event_type,
                    source_run_id           = EXCLUDED.source_run_id,
                    ingested_at             = NOW()
                """,
                args,
            )
    return len(args)
