"""CLI entry-point for AI-assisted data quality.

Examples:
  python -m nidp.services.dq_ai analyze --run-id <uuid>
  python -m nidp.services.dq_ai propose --dataset prices_eod --sample-size 1000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from . import diagnostics, expectation_author


async def _analyze(run_id: str) -> None:
    out = await diagnostics.analyze_run(run_id)
    print(json.dumps(out, indent=2, default=str))


async def _propose(dataset: str, sample_size: int, failure_days: int) -> None:
    out = await expectation_author.propose_expectations(
        dataset, sample_size=sample_size, failure_history_days=failure_days,
    )
    print(json.dumps(
        {k: v for k, v in out.items() if k != "raw_proposals"},
        indent=2, default=str,
    ))


def main() -> None:
    setup_logging(service="dq_ai")
    p = argparse.ArgumentParser(prog="python -m nidp.services.dq_ai")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_a = sub.add_parser("analyze", help="Run smell analyzer on a validation run")
    p_a.add_argument("--run-id", required=True)

    p_p = sub.add_parser("propose", help="Generate AI expectation proposals for a dataset")
    p_p.add_argument("--dataset", required=True)
    p_p.add_argument("--sample-size", type=int, default=1000)
    p_p.add_argument("--failure-days", type=int, default=30)

    a = p.parse_args()
    try:
        if a.cmd == "analyze":
            asyncio.run(_runner(_analyze(a.run_id)))
        elif a.cmd == "propose":
            asyncio.run(_runner(_propose(a.dataset, a.sample_size, a.failure_days)))
        else:
            p.print_help()
            sys.exit(2)
    except Exception as e:                  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


async def _runner(coro) -> None:
    try:
        await coro
    finally:
        await close_pool()


if __name__ == "__main__":
    main()
