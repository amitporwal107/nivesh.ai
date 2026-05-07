"""python -m nidp.services.nse_financials [--metrics]"""
from __future__ import annotations
import argparse, asyncio
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from .service import run


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="nse_financials")
    if a.metrics:
        start_metrics_server()
    asyncio.run(run(None))


if __name__ == "__main__":
    main()
