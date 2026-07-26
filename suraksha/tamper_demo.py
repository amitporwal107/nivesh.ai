"""Acceptance step 7 — edit one ledger row behind the app's back and watch verify catch it.

    python3 tamper_demo.py           # tamper, verify, restore, verify
    python3 tamper_demo.py --keep    # tamper and leave it broken (for the live demo)

Equivalent to `sqlite3 suraksha.db "UPDATE ledger SET detail=... WHERE id=N"`, for boxes
without the sqlite3 CLI.
"""

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent / "suraksha.db"


def verify() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/ledger/verify", timeout=10) as r:
        return json.loads(r.read())


def main() -> int:
    keep = "--keep" in sys.argv
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT id, actor, action, detail FROM ledger WHERE action='KEY_RELEASED' "
        "ORDER BY id LIMIT 1").fetchone()
    if row is None:
        print("no KEY_RELEASED row yet — open a paper in the terminal first")
        return 1
    rid, actor, action, original = row

    print(f"before tamper : {verify()}")
    print(f"target row    : id={rid} actor={actor} action={action} detail={original!r}")

    conn.execute("UPDATE ledger SET detail=? WHERE id=?", ("biometric=SKIPPED", rid))
    conn.commit()
    after = verify()
    print(f"after tamper  : {after}")
    ok = after["ok"] is False and after["broken_at"] == rid

    if keep:
        print("\n(left tampered — run without --keep to restore)")
    else:
        conn.execute("UPDATE ledger SET detail=? WHERE id=?", (original, rid))
        conn.commit()
        print(f"after restore : {verify()}")
    conn.close()

    print("\nRESULT:", "PASS — tamper detected at the exact row" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
