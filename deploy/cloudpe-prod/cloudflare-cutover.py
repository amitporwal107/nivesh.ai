#!/usr/bin/env python3
"""cloudflare-cutover.py — point the PRODUCTION DNS records at the CloudPe prod VM.

    python3 -I cloudflare-cutover.py plan     [--token-file PATH]
    python3 -I cloudflare-cutover.py apply    --backup FILE --yes [--token-file PATH] [--skip-origin-check]
    python3 -I cloudflare-cutover.py rollback --backup FILE --yes [--token-file PATH]

  plan      (default) GET the records and print current -> target. Changes nothing.
  apply     check the new origin answers over TLS, write the records' current state to --backup FILE
            (must not exist yet), then PATCH only `content` of each A record. proxied/ttl are not sent,
            so they stay as they are.
  rollback  PATCH the records' `content` back to what --backup FILE holds.

Token: first line of --token-file (default: .claude/.cloudflare-api-credentials next to the repo root's
git-ignored files) or env CF_API_TOKEN. Never printed.

Safety (same rules as deploy/cloudpe/cloudflare-cutover.sh, which handles the two STAGING records):
the only records this script can write are the A records named in HOSTS. It stops if a lookup returns
anything but exactly one record, or if a record's content is neither the known old IP nor the new one.
Every other record in the zone (staging, staging-data, ide, tunnels, mail, MX/TXT/CNAME) is never touched.
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ZONE_NAME = "niveshcopilot.com"
API = "https://api.cloudflare.com/client/v4"
NEW_IP = "45.64.105.249"                       # CloudPe prod VM
# name -> the GCP address it pointed at before (both are dead: GCP access is gone)
OLD_IP = {
    "niveshcopilot.com": "34.47.250.214",
    "www.niveshcopilot.com": "34.47.250.214",
    "api.niveshcopilot.com": "34.47.250.214",
    "admin.niveshcopilot.com": "34.47.250.214",
    "assets.niveshcopilot.com": "34.47.250.214",
    "work.niveshcopilot.com": "34.47.250.214",
    "data.niveshcopilot.com": "34.93.60.254",
}
HOSTS = list(OLD_IP)
# Path to probe on the new origin. Any HTTP status counts (the origin only accepts Cloudflare
# addresses, so a 403 from outside still proves nginx is up with TLS).
PROBE = {h: "/api/healthz" for h in HOSTS}
PROBE["data.niveshcopilot.com"] = "/health"
IPV4 = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".claude", ".cloudflare-api-credentials")


def log(msg):
    print(f"[cf-cutover-prod] {msg}")


def fail(msg):
    print(f"[cf-cutover-prod] FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


class CF:
    def __init__(self, token):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token or ""):
            fail("API token missing or has unexpected characters (value not shown).")
        self.token = token

    def call(self, method, path, body=None):
        req = urllib.request.Request(
            API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read().decode())
            except Exception:
                fail(f"Cloudflare API {method} {path}: HTTP {e.code}, non-JSON body.")
        except Exception as e:                                   # network error
            fail(f"Cloudflare API {method} {path}: {type(e).__name__}")
        if not out.get("success"):
            fail(f"Cloudflare API {method} {path}: {json.dumps(out.get('errors'))}")
        return out["result"]


def assert_allowed(host):
    if host not in OLD_IP:
        fail(f"Refusing to touch '{host}' — not one of: {', '.join(HOSTS)}")


def get_record(cf, zone_id, host):
    assert_allowed(host)
    res = cf.call("GET", f"/zones/{zone_id}/dns_records?type=A&name={host}&per_page=100")
    if len(res) != 1:
        fail(f"Expected exactly one A record for {host}, found {len(res)} — refusing.")
    r = res[0]
    if r["name"] != host or r["type"] != "A" or not HEX32.match(r["id"]):
        fail(f"Lookup for {host} returned an unexpected record — refusing.")
    return {k: r.get(k) for k in ("id", "name", "type", "content", "proxied", "ttl")}


def show(label, r):
    log(f"{label} {r['name']}  A  {r['content']}  proxied={r['proxied']}  ttl={r['ttl']}  id={r['id']}")


def origin_answers(host):
    """True if NEW_IP answers over TLS for `host` (any HTTP status)."""
    import http.client
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                              # Origin CA certs are not publicly trusted
    try:
        conn = http.client.HTTPSConnection(NEW_IP, 443, timeout=10, context=ctx)
        conn.request("GET", PROBE[host], headers={"Host": host})
        code = conn.getresponse().status
        log(f"origin {NEW_IP}:443 ({host}) answered HTTP {code}")
        return True
    except Exception as e:
        log(f"WARN origin {NEW_IP}:443 ({host}) did not answer over TLS: {type(e).__name__}")
        return False


def zone_id(cf):
    res = cf.call("GET", f"/zones?name={ZONE_NAME}")
    if len(res) != 1 or res[0]["name"] != ZONE_NAME:
        fail(f"Expected exactly one zone named {ZONE_NAME}, got {len(res)}.")
    return res[0]["id"]


def patch(cf, zid, rec, ip):
    assert_allowed(rec["name"])
    if not IPV4.match(ip) or not HEX32.match(rec["id"]):
        fail(f"Bad id or address for {rec['name']}.")
    out = cf.call("PATCH", f"/zones/{zid}/dns_records/{rec['id']}", {"content": ip})
    if out["name"] != rec["name"] or out["type"] != "A":
        fail(f"PATCH response names a different record: {out['name']}")
    log(f"PATCHed {rec['name']} → {out['content']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="plan", choices=["plan", "apply", "rollback"])
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--backup")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--skip-origin-check", action="store_true")
    a = ap.parse_args()

    tok = os.environ.get("CF_API_TOKEN", "")
    path = a.token_file or (None if tok else DEFAULT_TOKEN_FILE)
    if path:
        try:
            tok = open(path).readline().strip()
        except OSError:
            fail(f"Cannot read token file {path}")
    cf = CF(tok)
    zid = zone_id(cf)
    cur = {h: get_record(cf, zid, h) for h in HOSTS}

    if a.cmd == "plan":
        log(f"Zone {ZONE_NAME} ({zid}) — nothing will be changed.")
        for h in HOSTS:
            show("current:", cur[h])
            c = cur[h]["content"]
            if c == NEW_IP:
                log("  plan: no change (already at the new IP)")
            elif c == OLD_IP[h]:
                log(f"  plan: content {c} → {NEW_IP} (proxied/ttl unchanged)")
            else:
                log(f"  WARN plan: UNEXPECTED content {c} (expected {OLD_IP[h]} or {NEW_IP}) — apply would refuse")
        return

    if not a.yes:
        fail(f"{a.cmd} changes live DNS — re-run with --yes.")
    if not a.backup:
        fail(f"{a.cmd} needs --backup FILE.")

    if a.cmd == "apply":
        if os.path.exists(a.backup):
            fail(f"Backup file {a.backup} already exists — refusing to overwrite it.")
        for h in HOSTS:
            show("current:", cur[h])
            if cur[h]["content"] not in (OLD_IP[h], NEW_IP):
                fail(f"{h} points at {cur[h]['content']}, neither {OLD_IP[h]} nor {NEW_IP} — refusing.")
        if a.skip_origin_check:
            log("WARN skipping the origin check (--skip-origin-check).")
        elif not all([origin_answers(h) for h in HOSTS]):
            fail("New origin not ready — nothing changed. (--skip-origin-check overrides.)")
        fd = os.open(a.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"zone": ZONE_NAME, "zone_id": zid, "captured_at": datetime.now(timezone.utc).isoformat(),
                       "records": [cur[h] for h in HOSTS]}, f, indent=2)
        log(f"Backup written → {a.backup}")
        for h in HOSTS:
            if cur[h]["content"] == NEW_IP:
                log(f"{h} already at {NEW_IP} — no PATCH.")
            else:
                patch(cf, zid, cur[h], NEW_IP)
        for h in HOSTS:
            show("now:    ", get_record(cf, zid, h))
        log(f"Roll back with: python3 -I {sys.argv[0]} rollback --backup {a.backup} --yes")
        return

    # rollback
    try:
        saved = json.load(open(a.backup))
    except Exception:
        fail(f"Cannot read backup file {a.backup}.")
    if saved.get("zone") != ZONE_NAME or not isinstance(saved.get("records"), list):
        fail(f"{a.backup} is not a backup written by this script.")
    by_name = {r["name"]: r for r in saved["records"]}
    if set(by_name) != set(HOSTS):
        fail(f"{a.backup} does not cover exactly the production hosts.")
    for h in HOSTS:
        want = by_name[h]["content"]
        if by_name[h]["id"] != cur[h]["id"]:
            fail(f"Record id for {h} changed since the backup — refusing.")
        if want not in (OLD_IP[h], NEW_IP):
            fail(f"Backup content {want} for {h} is not a known address — refusing.")
        if cur[h]["content"] == want:
            log(f"{h} already at {want} — no PATCH.")
        else:
            patch(cf, zid, cur[h], want)
    for h in HOSTS:
        show("now:    ", get_record(cf, zid, h))


if __name__ == "__main__":
    main()
