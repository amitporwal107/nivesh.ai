"""python -m nidp.services.nse_financials [--metrics]"""
from __future__ import annotations
import argparse, asyncio
from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.storage.pg import close_pool
from .service import run


async def _runner() -> None:
    try:
        await run_with_job_log("nse_financials", run, None)
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="nse_financials")
    if a.metrics:
        start_metrics_server()
    asyncio.run(_runner())


if __name__ == "__main__":
    main()
