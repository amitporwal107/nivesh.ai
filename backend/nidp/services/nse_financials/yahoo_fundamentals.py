"""Balance-sheet and cash-flow backfill from Yahoo Finance.

Screener.in cannot supply working capital: its balance-sheet table stops at
Total Liabilities / Total Assets with no current-asset breakdown, so current_ratio,
receivable days and inventory days are uncomputable from it at any depth.

Yahoo's fundamentals-timeseries endpoint carries exactly those fields, needs no
crumb/cookie, and keys on the plain NSE symbol + ".NS" -- no slug or numeric-id
mapping. It also reports capex directly, where the Screener path could only derive
it as CFO - free cash flow.

Source:  https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{SYM}.NS
Writes:  nidp.nse_financials_cashflow          (CFO / CFI / CFF / capex)
         nidp.nse_financials_quarterly annual  (current assets+liabilities, inventory,
                                                receivables, payables, cash, debt)
Values arrive in base INR and are converted to crore (/1e7), matching every other
nidp financial column.

Usage:
    python -m nidp.services.nse_financials.yahoo_fundamentals
    python -m nidp.services.nse_financials.yahoo_fundamentals --symbols RELIANCE,TCS
    python -m nidp.services.nse_financials.yahoo_fundamentals --dry-run --concurrency 2
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, Optional

import aiohttp

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool
from .writer import upsert_balance_sheet, upsert_cashflow

logger = logging.getLogger(__name__)

_BASE = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_TIMEOUT = aiohttp.ClientTimeout(total=45)

# Yahoo series -> the nidp column it fills. Annual only: Yahoo returns at most two
# quarterly balance-sheet periods and no quarterly cash flow at all.
_CASHFLOW_FIELDS = {
    "annualOperatingCashFlow": "cfo_cr",
    "annualInvestingCashFlow": "cfi_cr",
    "annualFinancingCashFlow": "cff_cr",
    "annualCapitalExpenditure": "capex_cr",
}
_BALANCE_FIELDS = {
    "annualCurrentAssets": "current_assets_cr",
    "annualCurrentLiabilities": "current_liabilities_cr",
    "annualInventory": "inventory_cr",
    "annualAccountsReceivable": "trade_receivables_cr",
    "annualAccountsPayable": "trade_payables_cr",
    "annualCashAndCashEquivalents": "cash_and_equiv_cr",
    "annualTotalDebt": "long_term_debt_cr",
}
_TYPES = ",".join(list(_CASHFLOW_FIELDS) + list(_BALANCE_FIELDS))

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


async def fetch_yahoo_fundamentals(symbol: str) -> Optional[dict[str, Any]]:
    """Fetch the fundamentals timeseries for one NSE symbol. None if unavailable."""
    url = (
        f"{_BASE}/{symbol}.NS?symbol={symbol}.NS&type={_TYPES}"
        "&period1=1420070400&period2=2000000000"
    )
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
                async with s.get(url) as r:
                    if r.status in _RETRY_STATUSES:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    if r.status != 200:
                        logger.debug("yahoo: %s returned HTTP %s", symbol, r.status)
                        return None
                    return await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.debug("yahoo: %s attempt %d failed: %s", symbol, attempt + 1, exc)
            await asyncio.sleep(2 * (attempt + 1))
    return None


def parse_yahoo_fundamentals(symbol: str, payload: dict) -> tuple[list[dict], list[dict]]:
    """Split the timeseries payload into (cashflow_rows, balance_rows), one per year.

    Yahoo reports capex as a negative outflow; nidp.nse_financials_cashflow documents
    capex_cr the same way ("negative = outflow"), so the sign is passed through as-is.
    Returns ([], []) when the payload carries no usable series.
    """
    results = (payload.get("timeseries") or {}).get("result") or []
    cash: dict[str, dict] = {}
    bal: dict[str, dict] = {}
    for series in results:
        stype = (series.get("meta") or {}).get("type") or []
        if not stype:
            continue
        name = stype[0]
        target_cash = _CASHFLOW_FIELDS.get(name)
        target_bal = _BALANCE_FIELDS.get(name)
        if not target_cash and not target_bal:
            continue
        for point in series.get(name) or []:
            if not point:
                continue
            as_of = point.get("asOfDate")
            raw = (point.get("reportedValue") or {}).get("raw")
            if not as_of or raw is None:
                continue
            value_cr = round(float(raw) / 1e7, 4)     # base INR -> crore
            bucket = cash if target_cash else bal
            bucket.setdefault(as_of, {"period_end": as_of, "consolidated": True})
            bucket[as_of][target_cash or target_bal] = value_cr

    cash_rows = [r for r in cash.values() if any(k in r for k in _CASHFLOW_FIELDS.values())]
    for r in cash_rows:
        cfo, cfi, cff = r.get("cfo_cr"), r.get("cfi_cr"), r.get("cff_cr")
        if None not in (cfo, cfi, cff):
            r["net_change_cash_cr"] = round(cfo + cfi + cff, 4)
    bal_rows = [r for r in bal.values() if any(k in r for k in _BALANCE_FIELDS.values())]
    logger.info(
        "parse_yahoo_fundamentals: %s -- %d cash-flow years, %d balance-sheet years",
        symbol, len(cash_rows), len(bal_rows),
    )
    return cash_rows, bal_rows


async def _process_one(symbol: str, sem: asyncio.Semaphore, delay_ms: int, dry_run: bool) -> dict:
    async with sem:
        payload = await fetch_yahoo_fundamentals(symbol)
        await asyncio.sleep(delay_ms / 1000)
        if not payload:
            return {"symbol": symbol, "outcome": "not_found"}
        cash_rows, bal_rows = parse_yahoo_fundamentals(symbol, payload)
        if not cash_rows and not bal_rows:
            return {"symbol": symbol, "outcome": "no_data"}
        if dry_run:
            return {"symbol": symbol, "outcome": "dry_run",
                    "cf": len(cash_rows), "bs": len(bal_rows)}
        cf = sum(1 for r in cash_rows if await upsert_cashflow(symbol, r, source="yahoo_finance"))
        bs = sum(1 for r in bal_rows if await upsert_balance_sheet(symbol, r, source="yahoo_finance"))
        logger.info("yahoo_fund: %-14s %d cf_years  %d bs_years", symbol, cf, bs)
        return {"symbol": symbol, "outcome": "ok", "cf": cf, "bs": bs}


async def _load_symbols(conn, override: Optional[list[str]]) -> list[str]:
    if override:
        return [s.strip().upper() for s in override if s.strip()]
    rows = await conn.fetch(
        "SELECT DISTINCT symbol FROM nidp.nse_financials_quarterly ORDER BY symbol"
    )
    return [r["symbol"] for r in rows]


async def run(symbols: Optional[list[str]] = None, concurrency: int = 2,
              delay_ms: int = 500, dry_run: bool = False) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        targets = await _load_symbols(conn, symbols)
    logger.info("yahoo_fund: starting -- %d symbols, concurrency=%d, dry_run=%s",
                len(targets), concurrency, dry_run)
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(_process_one(s, sem, delay_ms, dry_run) for s in targets))
    summary: dict[str, int] = {}
    for r in results:
        summary[r["outcome"]] = summary.get(r["outcome"], 0) + 1
    summary["cf_years"] = sum(r.get("cf", 0) for r in results)
    summary["bs_years"] = sum(r.get("bs", 0) for r in results)
    logger.info("yahoo_fund: done -- %s", summary)
    return summary


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Yahoo Finance balance-sheet + cash-flow backfill")
    p.add_argument("--symbols", default=None, help="comma-separated NSE symbols")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--delay-ms", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    syms = a.symbols.split(",") if a.symbols else None
    try:
        asyncio.run(run(symbols=syms, concurrency=a.concurrency,
                        delay_ms=a.delay_ms, dry_run=a.dry_run))
    finally:
        asyncio.run(close_pool())


if __name__ == "__main__":
    main()
