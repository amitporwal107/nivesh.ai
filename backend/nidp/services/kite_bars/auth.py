"""Daily Kite access-token handshake.

Kite's access_token expires ~06:00 IST and renewal needs an interactive Zerodha login, so
this is run by a human once a day:

    python -m nidp.services.kite_bars.auth --login       # prints the URL to open
    python -m nidp.services.kite_bars.auth --exchange    # prompts for the request_token

The request_token is read from a prompt, never from argv — argv is visible to other
processes on this VM. The resulting access_token is written to TOKEN_FILE with mode 600
and is never printed.
"""
from __future__ import annotations

import argparse
import os
import stat

from .client import exchange_request_token, login_url

TOKEN_FILE = "/root/.kite-access-token"


def save_token(token: str, path: str = TOKEN_FILE) -> None:
    """Write the access token 0600, owner-only."""
    with open(path, "w") as fh:
        fh.write(token.strip())
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def read_token(path: str = TOKEN_FILE) -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Kite daily access-token handshake")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--login", action="store_true", help="print the login URL to open in a browser")
    g.add_argument("--exchange", action="store_true", help="prompt for request_token and save the access_token")
    g.add_argument("--status", action="store_true", help="report whether a token file exists (never prints it)")
    a = p.parse_args(argv)

    if a.login:
        print(login_url())
        print("\nLog in, then copy the request_token from the redirect URL and run:")
        print("  python -m nidp.services.kite_bars.auth --exchange")
        return 0

    if a.status:
        t = read_token()
        print(f"token file {TOKEN_FILE}: {'present, len ' + str(len(t)) if t else 'absent/empty'}")
        return 0 if t else 1

    rt = input("request_token: ").strip()
    if not rt:
        raise SystemExit("no request_token given")
    session = exchange_request_token(rt)
    tok = (session.get("access_token") or "").strip()
    if not tok:
        raise SystemExit(f"no access_token in response (keys: {sorted(session)})")
    save_token(tok)
    print(f"saved to {TOKEN_FILE} (mode 600); user={session.get('user_id', '?')}; expires ~06:00 IST tomorrow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
