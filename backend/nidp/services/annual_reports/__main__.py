"""python -m nidp.services.annual_reports [--latest-only] [--limit N]

Sweeps BSE AnnualReport_New across the equity universe (ref.security_master) and
registers each annual-report PDF in nidp.documents (doc_type='annual_report',
parse_status='pending') for the document_parser to ingest. Idempotent
(ON CONFLICT source_url DO NOTHING), so the weekly AGM-season cron only picks up
newly-filed reports.

  --latest-only   register only each company's most recent annual report
  --limit N       cap the universe to the first N companies (testing)
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging

from .service import run_once


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--latest-only", action="store_true",
                   help="register only each company's most recent annual report")
    p.add_argument("--limit", type=int, default=0,
                   help="cap the universe to the first N companies (testing)")
    a = p.parse_args()
    setup_logging(service="annual_reports")
    asyncio.run(run_once(latest_only=a.latest_only, limit=a.limit))


if __name__ == "__main__":
    main()
