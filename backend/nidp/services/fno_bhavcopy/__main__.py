"""python -m nidp.services.fno_bhavcopy --date YYYY-MM-DD [--metrics]"""
from __future__ import annotations
import argparse, asyncio
from datetime import date as _date

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from .service import run


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD trading day")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="fno_bhavcopy")
    if a.metrics:
        start_metrics_server()
    asyncio.run(run(_date.fromisoformat(a.date)))


if __name__ == "__main__":
    main()
