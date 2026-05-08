"""One-shot prod reset: wipe portfolio data + caches + onboarding flags
for every non-admin user, leaving the two seed founders intact so
onboarding can be re-tested.

Calls the existing audited admin endpoint:
    POST /api/admin/users/{user_id}/reset-portfolio

Auth: pass the session cookie via --cookie or PROD_SESSION_TOKEN env var.

Usage:
    PROD_SESSION_TOKEN=xxx python scripts/reset_prod_user_data.py [--dry-run]
    python scripts/reset_prod_user_data.py --cookie xxx [--invalidate-sessions]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

PROD_BASE = "https://portfolio-plan-board.emergent.host"
KEEP_EMAILS = {"priyankamantri@gmail.com", "aporwal107@gmail.com"}


def _norm(e: Optional[str]) -> str:
    return (e or "").strip().lower()


def _request(method: str, url: str, token: str, timeout: int = 60) -> Tuple[int, str]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Cookie", f"session_token={token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body
    except Exception as e:
        return 0, f"REQUEST_ERROR: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookie", help="session_token cookie value (or set PROD_SESSION_TOKEN)")
    ap.add_argument("--base", default=PROD_BASE)
    ap.add_argument("--dry-run", action="store_true", help="list targets, do not call reset")
    ap.add_argument("--invalidate-sessions", action="store_true",
                    help="also force-logout each non-admin user")
    ap.add_argument("--sleep", type=float, default=0.25,
                    help="delay between calls (s) to be gentle on the API")
    args = ap.parse_args()

    token = args.cookie or os.environ.get("PROD_SESSION_TOKEN")
    if not token:
        print("ERROR: provide --cookie or PROD_SESSION_TOKEN", file=sys.stderr)
        return 2

    print(f"-> listing users from {args.base}/api/admin/users")
    status, body = _request("GET", f"{args.base}/api/admin/users", token, timeout=30)
    if status != 200:
        print(f"ERROR: list users failed: status={status} body={body[:400]}", file=sys.stderr)
        return 3

    try:
        payload = json.loads(body)
    except Exception as e:
        print(f"ERROR: response was not JSON: {e}\nbody={body[:400]}", file=sys.stderr)
        return 3

    if isinstance(payload, list):
        users = payload
    elif isinstance(payload, dict):
        users = payload.get("users") or []
    else:
        users = []

    if not users:
        print("ERROR: empty user list — cookie may be unauthorized or response shape unexpected",
              file=sys.stderr)
        print(f"raw: {str(payload)[:400]}", file=sys.stderr)
        return 4

    keep: List[Dict[str, Any]] = []
    targets: List[Dict[str, Any]] = []
    for u in users:
        email = _norm(u.get("email"))
        if email in KEEP_EMAILS:
            keep.append(u)
        else:
            targets.append(u)

    print(f"\nTotal users: {len(users)}")
    print(f"Keep ({len(keep)}):")
    for u in keep:
        print(f"  - {u.get('email')}  {u.get('user_id')}  is_admin={u.get('is_admin')}")
    print(f"\nReset ({len(targets)}):")
    for u in targets:
        print(f"  - {u.get('email')}  {u.get('user_id')}")

    if not keep:
        print("\nABORT: neither admin email found in user list. Refusing to proceed.",
              file=sys.stderr)
        return 5

    if args.dry_run:
        print("\n--dry-run set, exiting without changes.")
        return 0

    print(f"\n-> resetting {len(targets)} users...")
    summary = {"ok": 0, "fail": 0, "total_docs": 0, "redis_keys": 0}
    failures: List[str] = []

    for i, u in enumerate(targets, 1):
        uid = u.get("user_id")
        email = u.get("email")
        status, body = _request(
            "POST", f"{args.base}/api/admin/users/{uid}/reset-portfolio", token, timeout=120
        )
        if status == 200:
            try:
                jb = json.loads(body)
                td = sum((jb.get("deleted_per_collection") or {}).values())
                rk = jb.get("redis_keys_cleared") or 0
            except Exception:
                td, rk = 0, 0
            summary["ok"] += 1
            summary["total_docs"] += td
            summary["redis_keys"] += rk
            print(f"  [{i}/{len(targets)}] OK  {email}  docs={td} redis={rk}")
        else:
            summary["fail"] += 1
            failures.append(f"{email}: status={status} {body[:200]}")
            print(f"  [{i}/{len(targets)}] FAIL {email}  status={status} {body[:200]}")

        if args.invalidate_sessions:
            s2, b2 = _request(
                "POST", f"{args.base}/api/admin/users/{uid}/invalidate-sessions", token, timeout=30
            )
            if s2 != 200:
                print(f"     (invalidate-sessions failed for {email}: status={s2} {b2[:120]})")

        if args.sleep:
            time.sleep(args.sleep)

    print("\n=== SUMMARY ===")
    print(f"  ok:     {summary['ok']}")
    print(f"  fail:   {summary['fail']}")
    print(f"  docs:   {summary['total_docs']}")
    print(f"  redis:  {summary['redis_keys']}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
