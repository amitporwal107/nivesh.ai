#!/usr/bin/env python3
"""
cloudflare_dns_migrate.py — repoint Cloudflare DNS A records from old IPs to new IPs.

Reads the API token and settings from a config file (never from the command line,
never printed). Default is a DRY RUN that only shows the plan.

Usage:
  python3 cloudflare_dns_migrate.py                       # dry run: show what would change
  python3 cloudflare_dns_migrate.py --apply               # change records (backup written first)
  python3 cloudflare_dns_migrate.py --rollback <backup>   # restore IPs from a backup file
  python3 cloudflare_dns_migrate.py --config <path> ...   # default: ~/.config/nivesh/cloudflare.env

Config file (KEY=VALUE, keep it outside the repo, readable only by you):
  CF_API_TOKEN=<token with Zone:DNS:Edit + Zone:Zone:Read for the zone>
  CF_ZONE_NAME=niveshcopilot.com
  IP_MAP=34.47.250.214=45.64.105.88,34.93.60.254=45.64.105.224
  SKIP_NAMES=ide.niveshcopilot.com          # optional, comma-separated FQDNs left untouched

Only A records whose current IP is a key in IP_MAP are changed, and only their IP:
name, proxied, TTL and comment stay as they are. MX/TXT/CNAME/AAAA are never touched.
Standard library only (no pip install needed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("CF_API_BASE", "https://api.cloudflare.com/client/v4")
DEFAULT_CONFIG = os.path.join(os.path.expanduser("~"), ".config", "nivesh", "cloudflare.env")


class CloudflareError(RuntimeError):
    pass


def load_config(path: str) -> dict[str, str]:
    if not os.path.isfile(path):
        sys.exit(f"Config file not found: {path}\nCreate it from deploy/cloudpe/cloudflare.env.example")
    if os.name == "posix":
        mode = os.stat(path).st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            sys.exit(f"Refusing to read {path}: it is readable by others. Run: chmod 600 {path}")
    cfg: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            # Drop full-line comments and " # ..." trailing comments.
            line = re.sub(r"(^|\s)#.*$", "", raw).strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("CF_API_TOKEN", "CF_ZONE_NAME", "IP_MAP"):
        if not cfg.get(key):
            sys.exit(f"Missing {key} in {path}")
    return cfg


def parse_ip_map(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pair in filter(None, (p.strip() for p in text.split(","))):
        if "=" not in pair:
            sys.exit(f"Bad IP_MAP entry {pair!r}: expected OLD_IP=NEW_IP")
        old, new = (s.strip() for s in pair.split("=", 1))
        mapping[old] = new
    if not mapping:
        sys.exit("IP_MAP is empty")
    return mapping


class Cloudflare:
    def __init__(self, token: str):
        self._token = token

    def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.load(exc)
            except ValueError:
                raise CloudflareError(f"{method} {path}: HTTP {exc.code}") from exc
        if not payload.get("success"):
            errors = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in payload.get("errors", []))
            raise CloudflareError(f"{method} {path} failed: {errors or 'unknown error'}")
        return payload

    def zone_id(self, name: str) -> str:
        result = self.request("GET", "/zones", {"name": name})["result"]
        if not result:
            raise CloudflareError(f"Zone {name!r} not found or token has no access to it")
        return result[0]["id"]

    def a_records(self, zone_id: str) -> list[dict]:
        records, page = [], 1
        while True:
            payload = self.request("GET", f"/zones/{zone_id}/dns_records",
                                   {"type": "A", "per_page": 100, "page": page})
            records.extend(payload["result"])
            info = payload.get("result_info") or {}
            if page >= info.get("total_pages", 1):
                return records
            page += 1

    def set_ip(self, zone_id: str, record_id: str, ip: str) -> dict:
        return self.request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", body={"content": ip})["result"]


def print_plan(rows: list[tuple[str, str, str, str]]) -> None:
    width = max([len(r[0]) for r in rows] + [4])
    print(f"  {'NAME':<{width}}  {'CURRENT':<15}  {'NEW':<15}  ACTION")
    for name, cur, new, action in rows:
        print(f"  {name:<{width}}  {cur:<15}  {new:<15}  {action}")


def migrate(cf: Cloudflare, cfg: dict[str, str], apply: bool) -> int:
    ip_map = parse_ip_map(cfg["IP_MAP"])
    skip = {s.strip().lower() for s in cfg.get("SKIP_NAMES", "").split(",") if s.strip()}
    zone = cf.zone_id(cfg["CF_ZONE_NAME"])
    print(f"Token OK: can read zone {cfg['CF_ZONE_NAME']}")
    records = cf.a_records(zone)
    print(f"Zone {cfg['CF_ZONE_NAME']}: {len(records)} A record(s)")

    changes, rows = [], []
    for rec in sorted(records, key=lambda r: r["name"]):
        name, cur = rec["name"], rec["content"]
        if cur not in ip_map:
            rows.append((name, cur, "-", "unchanged (IP not in IP_MAP)"))
        elif name.lower() in skip:
            rows.append((name, cur, "-", "SKIPPED (SKIP_NAMES)"))
        else:
            rows.append((name, cur, ip_map[cur], "UPDATE" if apply else "would update"))
            changes.append(rec)
    print_plan(rows)

    if not changes:
        print("Nothing to change.")
        return 0
    if not apply:
        print(f"\nDRY RUN: {len(changes)} record(s) would change. Re-run with --apply to change them.")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.abspath(f"cloudflare-dns-backup-{cfg['CF_ZONE_NAME']}-{stamp}.json")
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump({"zone": cfg["CF_ZONE_NAME"], "zone_id": zone,
                   "records": [{"id": r["id"], "name": r["name"], "content": r["content"]} for r in changes]},
                  fh, indent=2)
    print(f"\nBackup of original IPs: {backup}")

    failed = 0
    for rec in changes:
        new_ip = ip_map[rec["content"]]
        try:
            result = cf.set_ip(zone, rec["id"], new_ip)
            print(f"  OK    {rec['name']}: {rec['content']} -> {result['content']} (proxied={result.get('proxied')})")
        except CloudflareError as exc:
            failed += 1
            print(f"  FAIL  {rec['name']}: {exc}", file=sys.stderr)
    print(f"\n{len(changes) - failed} updated, {failed} failed.")
    if failed:
        print(f"To undo the successful ones: --rollback {backup}", file=sys.stderr)
    return 1 if failed else 0


def rollback(cf: Cloudflare, path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    failed = 0
    for rec in data["records"]:
        try:
            result = cf.set_ip(data["zone_id"], rec["id"], rec["content"])
            print(f"  OK    {rec['name']} -> {result['content']}")
        except CloudflareError as exc:
            failed += 1
            print(f"  FAIL  {rec['name']}: {exc}", file=sys.stderr)
    print(f"{len(data['records']) - failed} restored, {failed} failed.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"config file (default {DEFAULT_CONFIG})")
    parser.add_argument("--apply", action="store_true", help="actually change records (default: dry run)")
    parser.add_argument("--rollback", metavar="BACKUP_JSON", help="restore IPs from a backup written by --apply")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cf = Cloudflare(cfg["CF_API_TOKEN"])
    try:
        # No /user/tokens/verify call: account-owned tokens (cfat_...) are verified
        # under /accounts/<id>/ instead. The zone lookup proves the token works.
        return rollback(cf, args.rollback) if args.rollback else migrate(cf, cfg, args.apply)
    except CloudflareError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
