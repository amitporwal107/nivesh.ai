"""python -m nidp.services.bank_scoring [--symbol SYM] [--date YYYY-MM-DD]"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .service import run


async def _runner(symbol=None, target_date=None) -> None:
    try:
        summary = await run(target_date=target_date, symbol=symbol)
        print(f"\nBanks scored: {summary['banks_scored']}  as_of: {summary['as_of_date']}\n")
        print(f"{'Symbol':<14} {'Type':<8} {'Score':>6} {'AQ':>6} {'Prof':>6} "
              f"{'NPA%':>6} {'NNPA%':>6} {'Trend':<11} {'ROE%':>6} {'Cov%':>6}")
        print("-" * 90)
        for r in summary["results"]:
            aq = f"{r['asset_quality_score']:5.1f}" if r["asset_quality_score"] is not None else "  n/a"
            gnpa = f"{r['gnpa_pct']:5.2f}" if r["gnpa_pct"] else "  n/a"
            nnpa = f"{r['nnpa_pct']:5.2f}" if r["nnpa_pct"] else "  n/a"
            roe = f"{r['roe_pct']:5.1f}" if r["roe_pct"] else "  n/a"
            trend = r["gnpa_trend"] or "n/a"
            print(f"{r['symbol']:<14} {r['bank_type']:<8} {r['bank_quality_score']:6.1f} "
                  f"{aq:>6} {r['profitability_score']:6.1f} "
                  f"{gnpa:>6} {nnpa:>6} {trend:<11} {roe:>6} {r['coverage_pct']:6.1f}")
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default=None, help="Run for a single NSE symbol")
    p.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today)")
    a = p.parse_args()
    setup_logging(service="bank_scoring")
    target_date = date.fromisoformat(a.date) if a.date else None
    asyncio.run(_runner(symbol=a.symbol, target_date=target_date))


if __name__ == "__main__":
    main()
