"""python -m nidp.services.dlq_redrive [--limit N]

Reprocess PENDING dq.dlq_findings entries. Idempotent and safe to run on
a schedule — already-REPLAYED/DROPPED rows are never re-touched.
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging

from .service import redrive


def main() -> None:
    p = argparse.ArgumentParser(prog="dlq_redrive")
    p.add_argument("--limit", type=int, default=None,
                   help="Max PENDING entries to process (default 200 / NIDP_DLQ_REDRIVE_LIMIT).")
    args = p.parse_args()

    setup_logging(service="dlq_redrive")
    report = asyncio.run(redrive(limit=args.limit))
    print(f"dlq_redrive: processed={report['processed']} replayed={report['REPLAYED']} "
          f"pending={report['PENDING']} investigating={report['INVESTIGATING']} "
          f"dropped={report['DROPPED']}")


if __name__ == "__main__":
    main()
