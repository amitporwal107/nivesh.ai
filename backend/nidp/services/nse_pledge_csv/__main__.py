"""CLI for the manual NSE SAST pledged-data CSV drop.

    # look before you write — reports match rate and the pledge distribution
    python -m nidp.services.nse_pledge_csv --file CF-SAST-Pledged-Data-19-Aug-2026.csv --dry-run

    # write the pledge columns into the shareholding rows that already exist
    python -m nidp.services.nse_pledge_csv --file CF-SAST-Pledged-Data-19-Aug-2026.csv

Download the file from
https://www.nseindia.com/companies-listing/corporate-filings-pledged-data
(the API behind it is IP-blocked for this platform — see service.py).

Run --dry-run first. It is the only chance to see the resolved/unresolved split and
the pledge distribution before anything is written, and an unresolved list that is
suddenly large is how a changed file format announces itself.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from nidp.shared.logging_setup import setup_logging


def _args(argv=None):
    p = argparse.ArgumentParser(prog="nse_pledge_csv", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", required=True,
                   help="path to CF-SAST-Pledged-Data-<DD-Mon-YYYY>.csv")
    p.add_argument("--dry-run", action="store_true",
                   help="parse, resolve and report — write nothing")
    p.add_argument("--insert-missing", action="store_true",
                   help="also create pledge-only rows for symbols with no shareholding "
                        "row at that quarter. Off by default: such a row becomes the "
                        "symbol's latest in v_shareholding_latest and carries no "
                        "FII/DII, so it would hide the previous quarter's flows.")
    p.add_argument("--no-refresh-features", action="store_true",
                   help="skip pushing the pledge into stock_features_daily "
                        "(the daily feature_snapshotter run would do it anyway)")
    return p.parse_args(argv)


async def main(argv=None) -> int:
    a = _args(argv)
    setup_logging("nse_pledge_csv")
    logger = logging.getLogger(__name__)

    from nidp.services.nse_pledge_csv.service import run
    try:
        result = await run(a.file, dry_run=a.dry_run,
                           insert_missing=a.insert_missing,
                           refresh_features=not a.no_refresh_features)
    except Exception:
        logger.exception("nse_pledge_csv: unhandled error")
        return 1

    print(json.dumps(result, indent=2, default=str))
    if result.get("unresolved"):
        # Loud on stderr, not buried in the JSON: names that did not resolve are
        # companies whose pledge silently did not land.
        print(f"WARNING: {result['unresolved']} company name(s) did not resolve to a "
              f"NIDP symbol; their pledge was NOT written. First few: "
              f"{result.get('unresolved_sample')}", file=sys.stderr)
    return 0 if result.get("status") in ("OK", "DRY_RUN") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
