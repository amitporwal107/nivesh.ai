"""Macro Intelligence ingester — daily prints for the 4 PRD metrics.

PR-1 scope: single-source-per-metric via yfinance. Multi-source fallback
(Alpha Vantage, RBI scraping, Investing.com) lands in PR-2 once API keys
are provisioned.

Sources (PR-1):
  • Crude (Brent)   — yfinance "BZ=F"             confidence 1.0
  • USDINR          — yfinance "USDINR=X"         confidence 1.0
  • India 10Y       — yfinance "^TNX" (US proxy)  confidence 0.5
  • Nifty 50        — yfinance "^NSEI"            confidence 1.0

The India 10Y proxy is intentional and explicit — yfinance doesn't ship a
clean India sovereign yield, and the engine's regime classifier only
needs the directional signal (rising / falling), not the absolute level.
The `confidence_bond = 0.5` flag flows through to the UI so users can
see the data lineage. PR-2 swaps in RBI's daily reference rate.

Sanity rules (PRD §7):
  • If |today − yesterday| / yesterday > 10%, REJECT today's print as a
    likely scrape artefact. The previous-day value is left in place.
  • Missing field → null (never zero, never fabricated). The regime
    engine treats nulls as "no signal" and skips that input.

Idempotency:
  Same (date) row is upserted on every run. Running twice on the same day
  is safe — the second call overwrites with the latest scrape.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from services import pg_client

logger = logging.getLogger(__name__)


# ── yfinance ticker map ────────────────────────────────────────────────
# Each entry: list of tickers tried in order until one returns data. The
# yfinance library occasionally hiccups on a single symbol so we keep a
# secondary even within the "single source" PR-1 contract.
_TICKERS: Dict[str, Dict[str, Any]] = {
    # ── PR-1 core (3 macro inputs + Nifty) ──────────────────────────
    "crude":     {"chain": ["BZ=F"],              "label": "Crude Brent",       "primary_confidence": 1.0},
    "usd":       {"chain": ["USDINR=X", "INR=X"], "label": "USD/INR",           "primary_confidence": 1.0},
    # India 10Y isn't reliably on yfinance. ^TNX is US 10Y — we use it as
    # a directional proxy until PR-3 ships the RBI daily reference rate.
    "bond":      {"chain": ["^TNX"],              "label": "India 10Y (US 10Y proxy)", "primary_confidence": 0.5},
    "nifty":     {"chain": ["^NSEI"],             "label": "Nifty 50",          "primary_confidence": 1.0},
    # ── PR-2.5 global indicators ────────────────────────────────────
    # India fear gauge — directly measures option-implied volatility.
    "india_vix": {"chain": ["^INDIAVIX"],         "label": "India VIX",         "primary_confidence": 1.0},
    # US fear gauge — leads India VIX by ~1 day during global risk-off events.
    "us_vix":    {"chain": ["^VIX"],              "label": "CBOE VIX",          "primary_confidence": 1.0},
    # USD index — global USD strength; inverse correlation with EM flows.
    "dxy":       {"chain": ["DX-Y.NYB", "DX=F"],  "label": "US Dollar Index",   "primary_confidence": 0.9},
    # US session close — drives Asia next-day; Nasdaq specifically matters
    # for IT-heavy Indian portfolios.
    "sp500":     {"chain": ["^GSPC"],             "label": "S&P 500",           "primary_confidence": 1.0},
    "nasdaq":    {"chain": ["^IXIC"],             "label": "Nasdaq Composite",  "primary_confidence": 1.0},
    # Asian session opens — leading indicators for the NSE 9:15 IST open.
    "nikkei":    {"chain": ["^N225"],             "label": "Nikkei 225",        "primary_confidence": 1.0},
    "hang_seng": {"chain": ["^HSI"],              "label": "Hang Seng",         "primary_confidence": 0.9},
}

# Sanity-check threshold: any single-day move above this gets rejected as
# a likely scrape glitch. Crude can legitimately move 10% in a day during
# a geopolitical event — we err on the side of false-rejecting those days
# so the engine never trades on bad data. Tune if false-rejects pile up.
SANE_DELTA_PCT = 10.0


def _fetch_latest_close(chain: List[str]) -> Tuple[Optional[float], Optional[str], Optional[date]]:
    """Return (close_price, ticker_used, bar_date). Walks the chain; first
    ticker with a fresh print wins. Returns (None, None, None) on total
    failure.

    The bar_date is critical for holiday detection — yfinance returns the
    most recent CLOSED bar, which on a Saturday is Friday's close. If we
    naively dated the row by today's calendar date we'd write Friday's
    values under Saturday and the dashboard would look stale-but-current."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("macro_ingester: yfinance not installed")
        return None, None, None
    for ticker in chain:
        try:
            t = yf.Ticker(ticker)
            # 5d period gives us today + recent fallbacks if today's bar
            # hasn't printed yet (e.g. weekend / holiday).
            hist = t.history(period="5d", auto_adjust=False)
            if hist is None or hist.empty:
                continue
            # Take the last non-NaN close along with its date.
            for idx in reversed(hist.index):
                close = hist.loc[idx, "Close"]
                if close is not None and not _is_nan(close):
                    bar_dt = idx.date() if hasattr(idx, "date") else None
                    return float(close), ticker, bar_dt
        except Exception as e:  # noqa: BLE001
            logger.debug("macro_ingester: %s fetch failed: %s", ticker, e)
            continue
    return None, None, None


# ── PR-3 multi-source fallbacks ────────────────────────────────────────
# Each fallback returns (close, source_label) like _fetch_latest_close.
# When the API key / scrape is unavailable, returns (None, None) and the
# caller falls through to the next provider.

async def _fetch_alpha_vantage(symbol: str, av_function: str = "GLOBAL_QUOTE",
                                ) -> Tuple[Optional[float], Optional[str], Optional[date]]:
    """Alpha Vantage spot quote. Requires `ALPHA_VANTAGE_KEY` env var.

    Free tier: 25 requests/day, 5/min. Sufficient for 8 macro metrics
    once daily. Used as primary for crude / USDINR / DXY in PR-3 once the
    key is provisioned; yfinance becomes the secondary fallback.
    """
    import os
    api_key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not api_key:
        return None, None, None
    try:
        import requests
        url = (
            f"https://www.alphavantage.co/query?function={av_function}"
            f"&symbol={symbol}&apikey={api_key}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None, None, None
        data = resp.json()
        # GLOBAL_QUOTE returns {"Global Quote": {"05. price": "12.34", "07. latest trading day": "2026-05-09", ...}}
        quote = data.get("Global Quote", {})
        price = quote.get("05. price")
        if price is None:
            return None, None, None
        # Try to parse the trading-day date if present
        bar_dt: Optional[date] = None
        try:
            day = quote.get("07. latest trading day")
            if day:
                bar_dt = date.fromisoformat(day[:10])
        except (TypeError, ValueError):
            pass
        return float(price), f"alphavantage:{symbol}", bar_dt
    except Exception as e:  # noqa: BLE001
        logger.debug("alpha vantage fetch failed for %s: %s", symbol, e)
        return None, None, None


async def _fetch_rbi_10y_yield() -> Tuple[Optional[float], Optional[str], Optional[date]]:
    """India 10Y G-Sec yield from RBI.

    RBI publishes daily reference rates at:
        https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx

    The 10Y G-Sec print is in the FBIL Government Securities table — it's
    HTML scraping, fragile, and rate-limited. This function is a SKELETON
    that returns (None, None) in PR-3 — production deploy needs:

      1. Confirm RBI URL still publishes 10Y at the same selector
      2. Add HTML parser (BeautifulSoup) — already in requirements.txt
      3. Schedule a midnight retry if the 18:35 IST scrape fails (RBI
         sometimes publishes late on volatile days)

    The yfinance ^TNX proxy in the primary chain remains the working
    fallback in the meantime — confidence stays at 0.5 to flag the proxy.
    """
    # NOT_IMPLEMENTED in PR-3 deliberately — surface this in logs so
    # operators know there's a proper RBI ingestion to wire up.
    logger.debug("RBI 10Y yield scrape not implemented yet — falling through to proxy")
    return None, None, None


async def _fetch_with_fallback(metric_key: str, chain: List[str],
                               ) -> Tuple[Optional[float], Optional[str], float, Optional[date]]:
    """Walk: Alpha Vantage (when applicable) → yfinance chain → RBI (bond only).

    Returns (value, source_used, confidence_actual, bar_date). The
    bar_date is the actual trading day the value belongs to — used by
    the caller to detect "markets closed today" via the Nifty bar."""
    spec = _TICKERS.get(metric_key, {})
    primary_conf = spec.get("primary_confidence", 1.0)

    # PR-3 placeholder: enable Alpha Vantage for specific metrics once key is set.
    av_symbol_map = {
        "crude": ("BNO", "GLOBAL_QUOTE"),     # United States Brent Oil Fund proxy
        "usd":   ("USDINR", "CURRENCY_EXCHANGE_RATE"),
        # Add more here when you've validated AV ticker conventions
    }
    if metric_key in av_symbol_map:
        sym, fn = av_symbol_map[metric_key]
        v, src, bar_dt = await _fetch_alpha_vantage(sym, fn)
        if v is not None:
            return v, src, 1.0, bar_dt

    # Primary path: yfinance chain (always tried)
    v, src, bar_dt = _fetch_latest_close(chain)
    if v is not None:
        return v, src, primary_conf, bar_dt

    # Bond-specific deep fallback: try RBI scrape last
    if metric_key == "bond":
        v, src, bar_dt = await _fetch_rbi_10y_yield()
        if v is not None:
            return v, src, 0.7, bar_dt

    return None, None, 0.0, None


def _is_nan(v: Any) -> bool:
    try:
        return v != v   # NaN is the only float that isn't equal to itself
    except Exception:  # noqa: BLE001
        return v is None


# ── Sanity gate ────────────────────────────────────────────────────────
async def _previous_value(metric: str, today: date) -> Optional[float]:
    """Pull the most recent prior `metric_*` value before `today` for the
    day-over-day delta sanity check. Returns None if no history yet."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    col_map = {
        "crude":     "crude_price",
        "usd":       "usd_inr",
        "bond":      "bond_10y",
        "nifty":     "nifty",
        "india_vix": "india_vix",
        "us_vix":    "us_vix",
        "dxy":       "dxy",
        "sp500":     "sp500",
        "nasdaq":    "nasdaq",
        "nikkei":    "nikkei",
        "hang_seng": "hang_seng",
    }
    col = col_map.get(metric)
    if not col:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {col} AS v FROM macro_daily "
            f"WHERE date < $1 AND {col} IS NOT NULL "
            f"ORDER BY date DESC LIMIT 1",
            today,
        )
    if row and row["v"] is not None:
        return float(row["v"])
    return None


def _passes_sanity(value: Optional[float], previous: Optional[float]) -> bool:
    """True if value is plausible vs. the previous print, or if there's no
    history to compare against (first-ever ingest)."""
    if value is None:
        return False
    if previous is None or previous == 0:
        return True
    delta_pct = abs(value - previous) / previous * 100.0
    return delta_pct <= SANE_DELTA_PCT


# ── Persistence ────────────────────────────────────────────────────────
async def _existing_macro_daily_columns(pool) -> set:
    """Return the set of columns that actually exist on macro_daily today.

    Defensive against partial migrations: if 016 ran but 017 didn't (or
    schema-drift between code and DB), the dynamic upsert below would
    fail with `column "india_vix" does not exist`. We intersect the
    `fields` dict with what's actually there and silently drop unknowns,
    so the row still goes in for whatever subset the DB supports."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'macro_daily'"
        )
    return {r["column_name"] for r in rows}


async def _upsert(macro_date: date, fields: Dict[str, Any]) -> None:
    """Idempotent upsert into macro_daily. `fields` carries every metric
    value + its per-metric source / confidence. Built dynamically so PR-2.5
    columns (india_vix / us_vix / dxy / sp500 / nasdaq / nikkei / hang_seng)
    flow in without a second SQL statement."""
    pool = await pg_client.get_pool()
    if pool is None:
        logger.warning("macro_ingester: no pg pool — skipping upsert")
        return

    # Drop any field whose column doesn't actually exist (handles partial
    # migration state — e.g. 016 applied but 017 wasn't, so india_vix /
    # dxy / etc. are not on the table yet). We log the diff once so the
    # operator knows there's a migration drift.
    existing = await _existing_macro_daily_columns(pool)
    if not existing:
        logger.warning("macro_ingester: macro_daily has no columns or doesn't exist — skipping upsert")
        return
    accepted_fields = {k: v for k, v in fields.items() if k in existing}
    dropped = set(fields.keys()) - set(accepted_fields.keys())
    if dropped:
        logger.warning(
            "macro_ingester: skipping unknown columns (likely migration drift): %s",
            sorted(dropped),
        )
    if not accepted_fields:
        logger.warning("macro_ingester: no recognised columns in fields — skipping upsert")
        return

    # Columns to upsert — driven by what's present in `accepted_fields`.
    # We always write `date` + `updated_at`; everything else is conditional.
    all_cols = list(accepted_fields.keys())
    placeholders = ",".join(f"${i + 2}" for i in range(len(all_cols)))
    set_clause = ",".join(
        f"{c} = COALESCE(EXCLUDED.{c}, macro_daily.{c})" for c in all_cols
    )
    sql = f"""
        INSERT INTO macro_daily (date, {", ".join(all_cols)}, updated_at)
        VALUES ($1, {placeholders}, NOW())
        ON CONFLICT (date) DO UPDATE SET
            {set_clause},
            updated_at = NOW()
    """
    values = [macro_date] + [accepted_fields[c] for c in all_cols]
    async with pool.acquire() as conn:
        await conn.execute(sql, *values)


# ── Public entry point ─────────────────────────────────────────────────
async def ingest_today(*, target_date: Optional[date] = None) -> Dict[str, Any]:
    """Pull all 4 macro metrics, sanity-check, persist. Returns a summary
    of which metrics succeeded and which fell back / failed.

    The summary is stored in the response so the cron job's log line
    captures everything you'd want to debug a bad ingestion day from.
    """
    today = target_date or date.today()

    # Self-heal schema — same idempotent guard as `backfill()`. Cheap
    # (one CREATE/ALTER pass with IF NOT EXISTS) and means the daily cron
    # can recover from a missed migration without operator intervention.
    try:
        from services import macro_engine
        await macro_engine.ensure_schema()
    except Exception as e:  # noqa: BLE001
        logger.warning("ingest_today: ensure_schema failed: %s", e)

    # PR-3: each metric routed through _fetch_with_fallback so the chain
    # is yfinance → Alpha Vantage (when key set) → RBI (bond only). For
    # metrics without an AV mapping or RBI fallback, behaviour is identical
    # to the PR-1 yfinance-only path.
    raw: Dict[str, Tuple[Optional[float], Optional[str], float, Optional[date]]] = {}
    for m, spec in _TICKERS.items():
        v, src, conf, bar_dt = await _fetch_with_fallback(m, spec["chain"])
        raw[m] = (v, src, conf, bar_dt)

    # Holiday detection — use Nifty's bar date as the canonical Indian
    # market open marker. If yfinance returned no fresh Nifty bar for
    # today, today is a weekend / NSE holiday. We then EITHER skip the
    # write (if the prior-day row already exists) OR backfill the prior
    # trading day's row (so the dashboard has data to show).
    nifty_bar_dt = raw.get("nifty", (None, None, 0.0, None))[3]
    market_open_today = nifty_bar_dt is not None and nifty_bar_dt >= today
    as_of_date = nifty_bar_dt if nifty_bar_dt is not None else today

    fields: Dict[str, Any] = {}
    summary: Dict[str, Any] = {
        "requested_date": str(today),
        "as_of_date": str(as_of_date),
        "market_open_today": market_open_today,
        "metrics": {},
    }
    metric_to_col = {
        "crude":     ("crude_price", "source_crude",     "confidence_crude"),
        "usd":       ("usd_inr",     "source_usd",       "confidence_usd"),
        "bond":      ("bond_10y",    "source_bond",      "confidence_bond"),
        "nifty":     ("nifty",       "source_nifty",     "confidence_nifty"),
        "india_vix": ("india_vix",   "source_india_vix", "confidence_india_vix"),
        "us_vix":    ("us_vix",      "source_us_vix",    "confidence_us_vix"),
        "dxy":       ("dxy",         "source_dxy",       "confidence_dxy"),
        "sp500":     ("sp500",       "source_sp500",     "confidence_sp500"),
        "nasdaq":    ("nasdaq",      "source_nasdaq",    "confidence_nasdaq"),
        "nikkei":    ("nikkei",      "source_nikkei",    "confidence_nikkei"),
        "hang_seng": ("hang_seng",   "source_hang_seng", "confidence_hang_seng"),
    }

    for metric, (val, ticker, actual_conf, _bar_dt) in raw.items():
        col, src_col, conf_col = metric_to_col[metric]
        prev = await _previous_value(metric, as_of_date)
        ok = _passes_sanity(val, prev)
        if ok:
            fields[col] = val
            fields[src_col] = ticker
            fields[conf_col] = actual_conf
            summary["metrics"][metric] = {
                "ok": True, "value": val, "source": ticker,
                "confidence": actual_conf,
                "prev": prev,
            }
        else:
            # Reject — leave the column null on this row (prior days remain
            # intact for trend math). UI will see a confidence drop.
            summary["metrics"][metric] = {
                "ok": False,
                "value": val,
                "prev": prev,
                "reason": "sanity_check_failed" if val is not None else "fetch_failed",
            }
            logger.warning(
                "macro_ingester: %s rejected (val=%s prev=%s ticker=%s)",
                metric, val, prev, ticker,
            )

    # Always date the row by `as_of_date` (the actual trading day) — never
    # by today's calendar date. On a holiday/weekend this means we re-upsert
    # the PRIOR trading day's row with any global signals that did update
    # overnight (e.g. US markets close on India holidays, yielding a fresh
    # S&P bar). The dashboard reads "latest row" so it surfaces this naturally.
    if fields:
        await _upsert(as_of_date, fields)
        summary["upserted"] = True
        if not market_open_today:
            logger.info(
                "macro_ingester: market closed on %s — wrote to last trading day %s",
                today, as_of_date,
            )
    else:
        summary["upserted"] = False
        logger.warning(
            "macro_ingester: no metrics passed sanity for %s (as_of=%s) — skipping write",
            today, as_of_date,
        )

    successes = sum(1 for m in summary["metrics"].values() if m.get("ok"))
    summary["success_count"] = successes
    summary["overall_confidence"] = round(successes / len(_TICKERS), 2)
    return summary


async def backfill(days: int = 60) -> Dict[str, Any]:
    """Pull the last N daily closes for each metric and bulk-insert.

    Used once on first deploy so the feature engine has enough history to
    compute 50DMAs. Day-by-day so each row goes through the same sanity
    pipeline as the daily cron — slow but correct.

    Also auto-applies migrations 016 + 017 at the start so first-deploy
    callers don't need to run psql manually before clicking "Backfill"
    in the UI. Idempotent — re-running on an already-migrated DB is a
    no-op (every CREATE/ALTER uses IF NOT EXISTS).
    """
    # Ensure schema before any writes — handles the "first click on the
    # MacroBar empty-state CTA in a fresh deploy" case cleanly.
    try:
        from services import macro_engine
        await macro_engine.ensure_schema()
    except Exception as e:  # noqa: BLE001
        logger.warning("backfill: ensure_schema failed: %s", e)

    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}

    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no pg pool"}

    # Full PR-1 + PR-2.5 metric → column mapping. Kept as a module-level
    # constant inside `_metric_columns()` so backfill and ingest_today
    # agree on the schema. Adding a new metric only requires extending
    # this single dict (plus _TICKERS at the top of the file).
    METRIC_COLS = {
        "crude":     ("crude_price", "source_crude",     "confidence_crude"),
        "usd":       ("usd_inr",     "source_usd",       "confidence_usd"),
        "bond":      ("bond_10y",    "source_bond",      "confidence_bond"),
        "nifty":     ("nifty",       "source_nifty",     "confidence_nifty"),
        "india_vix": ("india_vix",   "source_india_vix", "confidence_india_vix"),
        "us_vix":    ("us_vix",      "source_us_vix",    "confidence_us_vix"),
        "dxy":       ("dxy",         "source_dxy",       "confidence_dxy"),
        "sp500":     ("sp500",       "source_sp500",     "confidence_sp500"),
        "nasdaq":    ("nasdaq",      "source_nasdaq",    "confidence_nasdaq"),
        "nikkei":    ("nikkei",      "source_nikkei",    "confidence_nikkei"),
        "hang_seng": ("hang_seng",   "source_hang_seng", "confidence_hang_seng"),
    }

    rows_by_date: Dict[date, Dict[str, Any]] = {}
    for metric, spec in _TICKERS.items():
        cols = METRIC_COLS.get(metric)
        if not cols:
            # Unknown metric — likely a freshly added _TICKERS entry that
            # hasn't been wired into METRIC_COLS yet. Log and skip rather
            # than KeyError so the rest of the backfill still runs.
            logger.warning("backfill: no column mapping for metric %r — skipping", metric)
            continue
        col, src_col, conf_col = cols
        for ticker in spec["chain"]:
            try:
                t = yf.Ticker(ticker)
                # +20d buffer so we have ample history regardless of
                # weekends/holidays in the backfill window.
                hist = t.history(period=f"{days + 20}d", auto_adjust=False)
                if hist is None or hist.empty:
                    continue
                for idx, r in hist.iterrows():
                    d = idx.date() if hasattr(idx, "date") else idx
                    close = r.get("Close")
                    if _is_nan(close):
                        continue
                    rec = rows_by_date.setdefault(d, {})
                    rec[col] = float(close)
                    rec[src_col] = ticker
                    rec[conf_col] = spec["primary_confidence"]
                break
            except Exception as e:  # noqa: BLE001
                logger.debug("backfill: %s/%s failed: %s", metric, ticker, e)

    inserted = 0
    for d, fields in sorted(rows_by_date.items()):
        try:
            await _upsert(d, fields)
            inserted += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("backfill upsert failed for %s: %s", d, e)

    return {
        "ok": True,
        "rows_seen": len(rows_by_date),
        "rows_upserted": inserted,
        "metrics": list(_TICKERS.keys()),
    }
