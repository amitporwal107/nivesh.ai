"""One-off backfill: encrypt the CAS unlock secrets still stored in the clear.

Before services/cas_secrets.py, the consumer onboarding stored the PAN and a
user-entered CAS statement password in plaintext on `user_profiles` (`pan`,
`cas_password`, `cas_pdf_password`) and mirrored them on `gmail_tokens`. This
script rewrites each such row to the encrypted shape (`pan_encrypted`,
`pan_last4`, `cas_pdf_password_encrypted`) and removes the plaintext fields.

Run it AFTER the backend that reads the encrypted fields is deployed and
restarted: the old code reads only the plaintext fields.

Usage (inside the backend container, from /app/backend):
  python -m scripts.encrypt_cas_secrets            # dry run: counts only, writes nothing
  python -m scripts.encrypt_cas_secrets --apply    # encrypt + remove plaintext

It prints counts only, never a value. It is idempotent: a second run finds
nothing to do. It needs PII_ENCRYPTION_KEY (outside a dev APP_ENV,
pii_security refuses to encrypt without it, and the script stops before
writing anything).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Dict

# Make the backend package importable when run as a top-level script.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services import cas_secrets, pii_security  # noqa: E402

COLLECTIONS = ("user_profiles", "gmail_tokens")


def _legacy_filter() -> Dict:
    return {"$or": [{name: {"$exists": True}} for name in cas_secrets.LEGACY_FIELDS]}


async def backfill(db, *, apply: bool) -> Dict[str, Dict[str, int]]:
    """Encrypt every plaintext CAS secret in `COLLECTIONS`. Returns counts per
    collection: rows found with plaintext, rows updated, plaintext rows left."""
    pii_security.encrypt("probe")  # fail before any write when no key is configured
    report: Dict[str, Dict[str, int]] = {}
    for name in COLLECTIONS:
        coll = db[name]
        projection = {"_id": 1, **{f: 1 for f in cas_secrets.LEGACY_FIELDS},
                      cas_secrets.PAN_FIELD: 1, cas_secrets.PDF_PASSWORD_FIELD: 1}
        found = updated = 0
        async for doc in coll.find(_legacy_filter(), projection):
            update = cas_secrets.legacy_update(doc)
            if update is None:
                continue
            found += 1
            if apply:
                res = await coll.update_one({"_id": doc["_id"]}, update)
                updated += res.modified_count
        left = await coll.count_documents(_legacy_filter())
        report[name] = {"plaintext_rows": found, "updated": updated, "plaintext_rows_left": left}
    return report


async def _run(apply: bool) -> None:
    from deps import db  # imported here so --help works without a database
    report = await backfill(db, apply=apply)
    mode = "APPLY" if apply else "DRY RUN (nothing written)"
    print(f"encrypt_cas_secrets — {mode}")
    for name, counts in report.items():
        print(f"  {name}: plaintext rows found={counts['plaintext_rows']} "
              f"updated={counts['updated']} plaintext rows left={counts['plaintext_rows_left']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    asyncio.run(_run(args.apply))


if __name__ == "__main__":
    main()
