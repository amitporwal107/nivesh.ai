"""python -m nidp.quality.replay — Historical Replay CLI.

Examples:
    python -m nidp.quality.replay \\
        --start-date 2026-02-01 \\
        --end-date   2026-05-10 \\
        --domains    all \\
        --policy-version v1 \\
        --parallel   8 \\
        --inject-failures false \\
        --reset      true

    python -m nidp.quality.replay --start-date 2026-04-01 \\
        --end-date 2026-04-30 --policy-version legacy --domains mf,equity
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Any

import asyncpg

from .engine import ReplayConfig, run_replay


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_bool(s: str) -> bool:
    return str(s).lower() in ("1", "true", "yes", "on", "y")


def _parse_domains(s: str) -> list:
    if not s or s.lower() in ("all", "*"):
        return ["mf", "equity"]
    return [d.strip() for d in s.split(",") if d.strip()]


async def _amain(args: argparse.Namespace) -> int:
    dsn = (
        os.environ.get("NIDP_PG_DSN")
        or os.environ.get("NIDP_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or "postgresql://postgres:postgres@localhost:5433/nidp"
    )
    cfg = ReplayConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        domains=_parse_domains(args.domains),
        policy_version=args.policy_version,
        parallel=args.parallel,
        inject_failures=_parse_bool(args.inject_failures),
        reset_data=_parse_bool(args.reset),
        initiated_by=args.initiated_by or os.environ.get("USER") or "cli",
        failure_seed=args.failure_seed,
        failure_rate=args.failure_rate,
        skip_weekends=not args.include_weekends,
    )

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=max(args.parallel * 2, 4))
    try:
        result: dict[str, Any] = await run_replay(pool, cfg)
    finally:
        await pool.close()

    print(json.dumps(result, indent=2, default=str))
    if result.get("status") != "SUCCESS":
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        prog="nidp.quality.replay",
        description="NIDP 90-Day Historical Quality Replay & Backtesting",
    )
    p.add_argument("--start-date", required=True, type=_parse_date,
                   help="Inclusive start date (YYYY-MM-DD)")
    p.add_argument("--end-date",   required=True, type=_parse_date,
                   help="Inclusive end date (YYYY-MM-DD)")
    p.add_argument("--domains", default="all",
                   help="Comma-separated: 'mf,equity', or 'all' (default: all)")
    p.add_argument("--policy-version", default="v1",
                   help="Scoring policy in audit.policy_versions (default: v1)")
    p.add_argument("--parallel", type=int, default=4,
                   help="Concurrent (date,domain) workers (default: 4)")
    p.add_argument("--inject-failures", default="false",
                   help="true|false (default: false)")
    p.add_argument("--failure-seed", type=int, default=None,
                   help="Deterministic injection seed (optional)")
    p.add_argument("--failure-rate", type=float, default=0.10,
                   help="Per-defect injection probability (default: 0.10)")
    p.add_argument("--reset", default="false",
                   help="Wipe quality_scores/exception_queue/etc for window (default: false)")
    p.add_argument("--initiated-by", default=None,
                   help="Caller identifier (default: $USER)")
    p.add_argument("--include-weekends", action="store_true",
                   help="Disable weekend skipping (default: skip)")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    )
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
