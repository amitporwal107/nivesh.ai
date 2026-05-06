"""python -m nidp.services.index_close --date YYYY-MM-DD [--metrics]"""
from __future__ import annotations
import argparse, asyncio
from datetime import date, datetime
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from .service import run


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_d, default=date.today())
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="index_close")
    if a.metrics: start_metrics_server()
    asyncio.run(run(a.date))


if __name__ == "__main__":
    main()
