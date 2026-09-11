"""Nifty 500/1000 extreme intraday-move analysis.

Finds trading days in a lookback window where a Nifty 500 / Nifty 1000
constituent moved >= --threshold-pct on any of three measures:
  - gap_pct            (open vs prior close)   — "gap up/down at open"
  - intraday_range_pct (high-low vs prior close) — "moved N% intraday"
  - close_chg_pct       (close vs prior close)   — net day change, for context

For each flagged event it joins the T-1 snapshot from nidp.stock_features_daily
(technicals + fundamentals, T-1 so nothing here uses same-day information —
see docs/... look-ahead-bias note in the domain-expert technical-analysis
pillar) and any nidp.corporate_announcements filed in [event_date-1, event_date+1].

It then aggregates which of those T-1 features were common across the event
set, and computes empirical (frequency-based, not ML) probabilities:
  - unconditional per-symbol base rate over --history-years
  - conditional base rate per feature bucket (e.g. RSI>70, vol_z20>2, sector,
    market-cap bucket) pooled across the whole universe, since a single
    symbol's own history is almost always too short to estimate a tail-event
    rate on its own (see caveats printed in the report).

Data source: this repo's real nidp.prices_eod / stock_features_daily /
index_constituents / corporate_announcements tables (NSE bhavcopy-derived —
see backend/nidp/services/bhavcopy/). This script does NOT hit nseindia.com
or any external mirror directly; it reads NIDP's already-ingested, DQ-gated
copy of that same bhavcopy data, per the platform's "read through NIDP, not
around it" convention (.claude/skills/domain-expert-analyst/retrieval-map.md).

Usage:
    python backend/scripts/nifty_extreme_move_analysis.py \
        --index "Nifty 500" --lookback-days 30 --history-years 3 \
        --threshold-pct 10 --output-dir backend/scripts/output

Requires NIDP_POSTGRES_URL (or POSTGRES_URL) in the environment, pointed at
a host that can actually reach the NIDP Postgres instance — this script does
not open any tunnel itself.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))


FEATURE_COLUMNS = [
    "close", "sma20", "sma50", "sma200", "dist_200dma_pct",
    "dist_52w_high_pct", "dist_52w_low_pct", "rsi14", "macd_hist",
    "return_5d_pct", "return_20d_pct", "return_60d_pct", "atr_pct",
    "bb_width", "bb_pos", "avg_volume_20", "vol_z20", "deliv_pct_avg_20",
    "deliv_trend10", "pivot_breakout_flag", "accumulation_score",
    "pe_ttm", "pb", "roe_pct", "debt_to_equity", "sector", "industry",
    "market_cap_bucket", "pe_vs_sector_pct", "sector_median_pe",
    "valuation_signal", "piotroski_score", "altman_z_score",
    "momentum_score", "earnings_decline_flag", "debt_spike_flag",
    "promoter_pledged_pct", "fii_pct_change_qoq",
]

# Buckets used for the pooled conditional-probability table. Kept simple and
# explainable on purpose — see technical-analysis.md: "combine, don't stack;
# a signal is a probability, not a promise."
FEATURE_BUCKETS: dict[str, Any] = {
    "rsi14_overbought": lambda r: (r.get("rsi14") or 0) >= 70,
    "rsi14_oversold": lambda r: (r.get("rsi14") or 100) <= 30,
    "vol_z20_spike": lambda r: (r.get("vol_z20") or 0) >= 2,
    "near_52w_high": lambda r: (r.get("dist_52w_high_pct") or -100) >= -3,
    "near_52w_low": lambda r: (r.get("dist_52w_low_pct") or 100) <= 3,
    "pivot_breakout": lambda r: bool(r.get("pivot_breakout_flag")),
    "high_accumulation": lambda r: (r.get("accumulation_score") or 0) >= 0.7,
    "earnings_decline": lambda r: bool(r.get("earnings_decline_flag")),
    "debt_spike": lambda r: bool(r.get("debt_spike_flag")),
    "small_or_micro_cap": lambda r: r.get("market_cap_bucket") in ("SMALL_CAP", "MICRO_CAP"),
    "overvalued_vs_sector": lambda r: r.get("valuation_signal") == "overvalued",
}


@dataclass
class MoveEvent:
    symbol: str
    company_name: str | None
    sector: str | None
    event_date: dt.date
    prev_close: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    gap_pct: float
    range_pct: float
    close_chg_pct: float
    volume: int | None
    deliv_pct: float | None
    triggers: list[str] = field(default_factory=list)
    t_minus_1_features: dict[str, Any] | None = None
    announcements: list[dict[str, Any]] = field(default_factory=list)


def _resolve_dsn() -> str | None:
    return os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")


async def _connect() -> asyncpg.Connection:
    dsn = _resolve_dsn()
    if not dsn:
        raise RuntimeError(
            "No NIDP_POSTGRES_URL / POSTGRES_URL in environment. "
            "This script reads nidp.prices_eod etc. directly (read-only) — "
            "it needs a DSN that can actually reach that Postgres instance."
        )
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    await conn.execute("SET search_path TO nidp, public")
    return conn


async def check_feed_health(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """DQ gate — per data-quality-governance.md: never trust data you haven't
    checked. Returns rows from nidp.v_feed_status for the feeds this script
    depends on, so the caller can see freshness/verdict before trusting output."""
    rows = await conn.fetch(
        """
        SELECT feed_name, last_success_at, is_stale, dq_verdict
        FROM nidp.v_feed_status
        WHERE feed_name IN ('bhavcopy', 'index_constituents', 'corporate_announcements_nse',
                             'corporate_announcements_bse', 'nse_financials')
        """
    )
    return [dict(r) for r in rows]


async def check_blocking_findings(conn: asyncpg.Connection, hours: int = 24) -> int:
    row = await conn.fetchrow(
        """
        SELECT count(*) AS n
        FROM nidp.validation_findings
        WHERE severity = 'BLOCK' AND created_at > now() - ($1 || ' hours')::interval
        """,
        str(hours),
    )
    return row["n"] if row else 0


async def get_universe(conn: asyncpg.Connection, index_name: str, as_of: dt.date) -> list[dict[str, Any]]:
    """Latest effective constituent list for `index_name` as of `as_of` (or
    earlier — index_constituents is effective-dated, not resnapshotted daily)."""
    row = await conn.fetchrow(
        """
        SELECT max(as_of_date) AS d FROM nidp.index_constituents
        WHERE index_name = $1 AND as_of_date <= $2
        """,
        index_name, as_of,
    )
    if not row or not row["d"]:
        return []
    rows = await conn.fetch(
        """
        SELECT symbol, isin, company_name, industry
        FROM nidp.index_constituents
        WHERE index_name = $1 AND as_of_date = $2
        """,
        index_name, row["d"],
    )
    return [dict(r) for r in rows]


async def find_events(
    conn: asyncpg.Connection,
    symbols: list[str],
    start_date: dt.date,
    end_date: dt.date,
    threshold_pct: float,
) -> list[MoveEvent]:
    if not symbols:
        return []
    rows = await conn.fetch(
        """
        SELECT symbol, as_of_date, prev_close, open_price, high_price, low_price,
               close_price, volume, deliv_pct
        FROM nidp.prices_eod
        WHERE symbol = ANY($1) AND series = 'EQ'
          AND as_of_date BETWEEN $2 AND $3
          AND prev_close IS NOT NULL AND prev_close > 0
        ORDER BY symbol, as_of_date
        """,
        symbols, start_date, end_date,
    )
    events: list[MoveEvent] = []
    for r in rows:
        prev_close = float(r["prev_close"])
        open_price = float(r["open_price"]) if r["open_price"] is not None else None
        high_price = float(r["high_price"]) if r["high_price"] is not None else None
        low_price = float(r["low_price"]) if r["low_price"] is not None else None
        close_price = float(r["close_price"]) if r["close_price"] is not None else None
        if None in (open_price, high_price, low_price, close_price):
            continue

        gap_pct = (open_price - prev_close) / prev_close * 100
        range_pct = (high_price - low_price) / prev_close * 100
        close_chg_pct = (close_price - prev_close) / prev_close * 100

        triggers = []
        if abs(gap_pct) >= threshold_pct:
            triggers.append(f"gap_{'up' if gap_pct > 0 else 'down'}")
        if range_pct >= threshold_pct:
            triggers.append("intraday_range")
        if abs(close_chg_pct) >= threshold_pct:
            triggers.append(f"close_{'up' if close_chg_pct > 0 else 'down'}")
        if not triggers:
            continue

        events.append(
            MoveEvent(
                symbol=r["symbol"], company_name=None, sector=None,
                event_date=r["as_of_date"], prev_close=prev_close,
                open_price=open_price, high_price=high_price, low_price=low_price,
                close_price=close_price, gap_pct=round(gap_pct, 2),
                range_pct=round(range_pct, 2), close_chg_pct=round(close_chg_pct, 2),
                volume=r["volume"], deliv_pct=float(r["deliv_pct"]) if r["deliv_pct"] is not None else None,
                triggers=triggers,
            )
        )
    return events


async def attach_t_minus_1_features(conn: asyncpg.Connection, events: list[MoveEvent]) -> None:
    """T-1 snapshot only — using same-day features would be look-ahead bias
    (the whole point is: what did we know BEFORE the move happened)."""
    cols = ", ".join(FEATURE_COLUMNS)
    for ev in events:
        row = await conn.fetchrow(
            f"""
            SELECT {cols}
            FROM nidp.stock_features_daily
            WHERE symbol = $1 AND as_of_date < $2
            ORDER BY as_of_date DESC
            LIMIT 1
            """,
            ev.symbol, ev.event_date,
        )
        ev.t_minus_1_features = dict(row) if row else None


async def attach_announcements(conn: asyncpg.Connection, events: list[MoveEvent]) -> None:
    for ev in events:
        rows = await conn.fetch(
            """
            SELECT filed_at, subject, event_category, impact_score, sentiment
            FROM nidp.corporate_announcements
            WHERE ticker_symbol = $1
              AND filed_at::date BETWEEN $2 AND $3
            ORDER BY filed_at
            """,
            ev.symbol, ev.event_date - dt.timedelta(days=1), ev.event_date + dt.timedelta(days=1),
        )
        ev.announcements = [dict(r) for r in rows]


async def compute_base_rates(
    conn: asyncpg.Connection,
    symbols: list[str],
    history_start: dt.date,
    history_end: dt.date,
    threshold_pct: float,
) -> dict[str, Any]:
    """Pooled, frequency-based base rate across the full universe + per
    market-cap-bucket / sector — NOT a fitted model. Deliberately simple and
    auditable; see technical-analysis.md overfitting caveat."""
    rows = await conn.fetch(
        """
        SELECT symbol, as_of_date, prev_close, open_price, high_price, low_price, close_price
        FROM nidp.prices_eod
        WHERE symbol = ANY($1) AND series = 'EQ'
          AND as_of_date BETWEEN $2 AND $3
          AND prev_close IS NOT NULL AND prev_close > 0
        """,
        symbols, history_start, history_end,
    )
    per_symbol_days: dict[str, int] = {}
    per_symbol_events: dict[str, int] = {}
    total_days = 0
    total_events = 0
    for r in rows:
        prev_close = float(r["prev_close"])
        if r["open_price"] is None or r["high_price"] is None or r["low_price"] is None:
            continue
        gap_pct = (float(r["open_price"]) - prev_close) / prev_close * 100
        range_pct = (float(r["high_price"]) - float(r["low_price"])) / prev_close * 100
        is_event = abs(gap_pct) >= threshold_pct or range_pct >= threshold_pct
        sym = r["symbol"]
        per_symbol_days[sym] = per_symbol_days.get(sym, 0) + 1
        total_days += 1
        if is_event:
            per_symbol_events[sym] = per_symbol_events.get(sym, 0) + 1
            total_events += 1

    per_symbol_rate = {
        sym: {
            "trading_days": per_symbol_days[sym],
            "events": per_symbol_events.get(sym, 0),
            # Laplace-smoothed rate: raw n_events/n_days is usually 0/small-n
            # for a single symbol on a rare tail event — smoothing avoids
            # reporting a false-confident 0.0% from a handful of clean days.
            "empirical_prob_smoothed": (per_symbol_events.get(sym, 0) + 1) / (per_symbol_days[sym] + 2),
            "empirical_prob_raw": per_symbol_events.get(sym, 0) / per_symbol_days[sym] if per_symbol_days[sym] else None,
        }
        for sym in per_symbol_days
    }
    return {
        "universe_pooled_prob": (total_events / total_days) if total_days else None,
        "universe_total_days": total_days,
        "universe_total_events": total_events,
        "per_symbol": per_symbol_rate,
    }


async def compute_conditional_rates(
    conn: asyncpg.Connection,
    symbols: list[str],
    history_start: dt.date,
    history_end: dt.date,
    threshold_pct: float,
) -> dict[str, dict[str, Any]]:
    """For each feature bucket, P(extreme move on day D | bucket true on day
    D-1), pooled across the universe. This is the empirical basis for
    'predicting the possibility' — a historical base rate for stocks
    currently in that bucket, not a forecast with a confidence interval."""
    price_rows = await conn.fetch(
        """
        SELECT symbol, as_of_date, prev_close, open_price, high_price, low_price
        FROM nidp.prices_eod
        WHERE symbol = ANY($1) AND series = 'EQ'
          AND as_of_date BETWEEN $2 AND $3
          AND prev_close IS NOT NULL AND prev_close > 0
        """,
        symbols, history_start, history_end,
    )
    events_by_symbol_date: dict[tuple[str, dt.date], bool] = {}
    for r in price_rows:
        prev_close = float(r["prev_close"])
        if r["open_price"] is None or r["high_price"] is None or r["low_price"] is None:
            continue
        gap_pct = (float(r["open_price"]) - prev_close) / prev_close * 100
        range_pct = (float(r["high_price"]) - float(r["low_price"])) / prev_close * 100
        events_by_symbol_date[(r["symbol"], r["as_of_date"])] = (
            abs(gap_pct) >= threshold_pct or range_pct >= threshold_pct
        )

    feature_rows = await conn.fetch(
        f"""
        SELECT symbol, as_of_date, {", ".join(FEATURE_COLUMNS)}
        FROM nidp.stock_features_daily
        WHERE symbol = ANY($1) AND as_of_date BETWEEN $2 AND $3
        """,
        symbols, history_start, history_end,
    )

    bucket_counts = {name: {"bucket_days": 0, "bucket_events": 0} for name in FEATURE_BUCKETS}
    for r in feature_rows:
        rd = dict(r)
        # look for the NEXT trading day's event flag relative to this feature row
        # (approximate: same-date map keyed by symbol+date+1 calendar day is not
        # exact for weekends/holidays — this is a known simplification, see
        # report caveats; a precise version should walk trading_day.py's calendar).
        nxt = rd["as_of_date"] + dt.timedelta(days=1)
        key = (rd["symbol"], nxt)
        for _ in range(4):
            if key in events_by_symbol_date:
                break
            nxt += dt.timedelta(days=1)
            key = (rd["symbol"], nxt)
        if key not in events_by_symbol_date:
            continue
        is_event = events_by_symbol_date[key]
        for name, pred in FEATURE_BUCKETS.items():
            try:
                if pred(rd):
                    bucket_counts[name]["bucket_days"] += 1
                    if is_event:
                        bucket_counts[name]["bucket_events"] += 1
            except Exception:
                continue

    result = {}
    for name, c in bucket_counts.items():
        days = c["bucket_days"]
        result[name] = {
            "bucket_days": days,
            "bucket_events": c["bucket_events"],
            "conditional_prob_smoothed": (c["bucket_events"] + 1) / (days + 2),
        }
    return result


def write_report(
    output_dir: Path,
    index_name: str,
    start_date: dt.date,
    end_date: dt.date,
    threshold_pct: float,
    history_start: dt.date,
    history_end: dt.date,
    feed_health: list[dict[str, Any]],
    blocking_findings: int,
    events: list[MoveEvent],
    base_rates: dict[str, Any],
    conditional_rates: dict[str, dict[str, Any]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"extreme_moves_{index_name.replace(' ', '_')}_{stamp}.md"

    lines: list[str] = []
    lines.append(f"# {index_name} — extreme intraday move analysis")
    lines.append("")
    lines.append(f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}")
    lines.append(f"Event window: {start_date} .. {end_date} (threshold >= {threshold_pct}%)")
    lines.append(f"Base-rate history window: {history_start} .. {history_end}")
    lines.append("")
    lines.append("## Data-quality gate (run this turn)")
    lines.append("")
    if not feed_health:
        lines.append(
            "**No rows returned from `nidp.v_feed_status`** for the feeds this "
            "analysis depends on (bhavcopy, index_constituents, corporate_announcements_*, "
            "nse_financials). Treat this report as UNVERIFIED until that's explained."
        )
    else:
        for row in feed_health:
            lines.append(
                f"- `{row['feed_name']}`: last_success_at={row['last_success_at']}, "
                f"is_stale={row['is_stale']}, dq_verdict={row['dq_verdict']}"
            )
    lines.append(f"- BLOCK-severity validation findings (last 24h): {blocking_findings}")
    if blocking_findings:
        lines.append(
            "  **>= 1 BLOCK finding present — some underlying data may be quarantined. "
            "Do not treat this report's numbers as solid without checking `nidp.validation_findings` "
            "for the specific symbols/feeds involved.**"
        )
    lines.append("")

    lines.append(f"## Flagged events ({len(events)})")
    lines.append("")
    if not events:
        lines.append(
            "No constituent of this index crossed the threshold in the window — "
            "either genuinely no such move occurred, or the universe/window/threshold "
            "need adjusting. This is a real result, not an error; a >=10% single-day "
            "move is a tail event even across 500-1000 stocks over one month."
        )
    else:
        lines.append("| Symbol | Date | Triggers | Gap% | Range% | Close chg% | Deliv% | Announcements in window |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for ev in sorted(events, key=lambda e: e.event_date):
            ann = "; ".join(
                f"{a['event_category'] or a['raw_category'] if 'raw_category' in a else a['event_category'] or '?'}"
                for a in ev.announcements
            ) or "—"
            lines.append(
                f"| {ev.symbol} | {ev.event_date} | {', '.join(ev.triggers)} | {ev.gap_pct} | "
                f"{ev.range_pct} | {ev.close_chg_pct} | {ev.deliv_pct if ev.deliv_pct is not None else '—'} | {ann} |"
            )
        lines.append("")

        lines.append("### Common T-1 characteristics across the flagged events")
        lines.append("")
        n = len(events)
        with_features = [e for e in events if e.t_minus_1_features]
        lines.append(f"T-1 feature snapshot available for {len(with_features)}/{n} events.")
        for name, pred in FEATURE_BUCKETS.items():
            hits = sum(1 for e in with_features if pred(e.t_minus_1_features))
            pct = (hits / len(with_features) * 100) if with_features else 0
            lines.append(f"- `{name}`: {hits}/{len(with_features)} ({pct:.0f}%) had this T-1")
        with_ann = sum(1 for e in events if e.announcements)
        lines.append(f"- had >=1 corporate announcement in [-1,+1] day window: {with_ann}/{n} ({with_ann/n*100:.0f}%)")
        lines.append("")

    lines.append("## Base rates (frequency-based, not a fitted model)")
    lines.append("")
    lines.append(
        f"Universe-pooled: {base_rates['universe_total_events']} events over "
        f"{base_rates['universe_total_days']} symbol-trading-days = "
        f"{(base_rates['universe_pooled_prob'] or 0) * 100:.3f}% of symbol-days."
    )
    lines.append(
        "Per-symbol rates use Laplace smoothing (`(events+1)/(days+2)`) because a raw "
        "0/N or 1/N estimate on a rare tail event is not a trustworthy probability — "
        "most single symbols will have 0 or 1 events even over multi-year history, so "
        "per-symbol numbers below should be read as 'no signal this stock is different "
        "from the pool' unless events > ~3-5."
    )
    lines.append("")
    lines.append("## Conditional base rates by T-1 feature bucket (pooled across universe)")
    lines.append("")
    lines.append("| Bucket | Bucket-days | Events (next trading day) | Conditional P (smoothed) | vs. universe pooled |")
    lines.append("|---|---|---|---|---|")
    pooled = base_rates["universe_pooled_prob"] or 0
    for name, c in sorted(conditional_rates.items(), key=lambda kv: -kv[1]["conditional_prob_smoothed"]):
        lift = (c["conditional_prob_smoothed"] / pooled) if pooled else float("nan")
        lines.append(
            f"| `{name}` | {c['bucket_days']} | {c['bucket_events']} | "
            f"{c['conditional_prob_smoothed']*100:.3f}% | {lift:.1f}x |"
        )
    lines.append("")
    lines.append("## Caveats (read before using any number above)")
    lines.append("")
    lines.append(
        "- **Sample size**: a >=10% single-day move is a genuine tail event. One month of "
        "data is nowhere near enough to fit a reliable per-stock probability; the "
        "conditional-bucket table above pools the whole universe over `history-years` "
        "to get usable counts — check `bucket_days`/`bucket_events` before trusting a rate."
    )
    lines.append(
        "- **T-1 join is calendar-day nearest-forward**, not the exact NSE trading calendar "
        "(`nidp.trading_day.py` / `v_market_session` was not used here) — verify against "
        "the real calendar before publishing this as a product feature."
    )
    lines.append(
        "- **Not corporate-action-adjusted**: prices_eod gap/range % are raw, not split/bonus "
        "adjusted (`price_adjuster/`, migration 026). A large 'gap' on an ex-bonus/ex-split day "
        "is a data artifact, not a real move — cross-check `nidp.corporate_actions` before "
        "reporting a flagged event as genuine."
    )
    lines.append(
        "- **Correlation, not causation**: co-occurring T-1 features/announcements are "
        "associations across a small flagged set, not a validated predictive model."
    )
    lines.append(
        "- **Not investment advice**: historical frequency of extreme moves does not predict "
        "any specific future move; frame per `.claude/skills/domain-expert-analyst/sebi-compliance.md`."
    )
    lines.append("")

    report_path.write_text("\n".join(lines))

    csv_path = output_dir / f"extreme_moves_{index_name.replace(' ', '_')}_{stamp}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "event_date", "triggers", "gap_pct", "range_pct", "close_chg_pct", "deliv_pct", "n_announcements"])
        for ev in events:
            w.writerow([ev.symbol, ev.event_date, "|".join(ev.triggers), ev.gap_pct, ev.range_pct, ev.close_chg_pct, ev.deliv_pct, len(ev.announcements)])

    return report_path


async def run(args: argparse.Namespace) -> Path:
    conn = await _connect()
    try:
        end_date = args.end_date or dt.date.today()
        start_date = end_date - dt.timedelta(days=args.lookback_days)
        history_end = end_date
        history_start = end_date - dt.timedelta(days=int(args.history_years * 365.25))

        feed_health = await check_feed_health(conn)
        blocking = await check_blocking_findings(conn)

        universe = await get_universe(conn, args.index, end_date)
        symbols = [u["symbol"] for u in universe]
        name_by_symbol = {u["symbol"]: u["company_name"] for u in universe}
        sector_by_symbol = {u["symbol"]: u["industry"] for u in universe}
        if not symbols:
            raise RuntimeError(
                f"No constituents found in nidp.index_constituents for index_name='{args.index}' "
                f"as_of<= {end_date}. Check the exact index_name value used by the feed "
                f"(e.g. 'Nifty 500' vs 'NIFTY 500') before assuming the universe is empty."
            )

        events = await find_events(conn, symbols, start_date, end_date, args.threshold_pct)
        for ev in events:
            ev.company_name = name_by_symbol.get(ev.symbol)
            ev.sector = sector_by_symbol.get(ev.symbol)

        await attach_t_minus_1_features(conn, events)
        await attach_announcements(conn, events)

        base_rates = await compute_base_rates(conn, symbols, history_start, history_end, args.threshold_pct)
        conditional_rates = await compute_conditional_rates(conn, symbols, history_start, history_end, args.threshold_pct)

        return write_report(
            Path(args.output_dir), args.index, start_date, end_date, args.threshold_pct,
            history_start, history_end, feed_health, blocking, events, base_rates, conditional_rates,
        )
    finally:
        await conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", default="Nifty 500", help="index_name as stored in nidp.index_constituents, e.g. 'Nifty 500' or 'Nifty 1000'")
    p.add_argument("--lookback-days", type=int, default=30, help="calendar days back from --end-date to scan for events")
    p.add_argument("--history-years", type=float, default=3.0, help="years of history for base-rate calibration")
    p.add_argument("--threshold-pct", type=float, default=10.0, help="move threshold in percent")
    p.add_argument("--end-date", type=lambda s: dt.date.fromisoformat(s), default=None, help="YYYY-MM-DD, defaults to today")
    p.add_argument("--output-dir", default=str(REPO_ROOT / "backend" / "scripts" / "output"))
    return p.parse_args(argv)


if __name__ == "__main__":
    ns = parse_args()
    path = asyncio.run(run(ns))
    print(f"Report written: {path}")
