"""NIDP unified CLI.

Usage:
    python -m nidp.cli migrate                          # apply pending migrations
    python -m nidp.cli ingest <service> [--date ...]
    python -m nidp.cli list-services                    # show available services
    python -m nidp.cli health                           # quick connectivity check
    python -m nidp.cli backfill --from D --to D ...     # historical ingestion
    python -m nidp.cli snapshot build --date YYYY-MM-DD [--force]
    python -m nidp.cli snapshot status [--date YYYY-MM-DD]
    python -m nidp.cli validate <service> [--date YYYY-MM-DD]
    python -m nidp.cli daas-keygen --owner E --name N --plan free|standard|pro
    python -m nidp.cli daas-keys list
    python -m nidp.cli daas-keys revoke --key-id <uuid>

Per-service entrypoint also works directly:
    python -m nidp.services.bulk_deals --date 2026-05-04
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from nidp.backfill import add_subparser as _add_backfill_subparser, cmd_backfill
from nidp.shared.config import MIGRATIONS_DIR
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

# Service registry — maps CLI name → module path.
SERVICES: dict[str, str] = {
    "bulk_deals":          "nidp.services.bulk_deals.service",
    "block_deals":         "nidp.services.block_deals.service",
    "bhavcopy":            "nidp.services.bhavcopy.service",
    "delivery":            "nidp.services.delivery.service",
    "index_close":         "nidp.services.index_close.service",
    "index_constituents":  "nidp.services.index_constituents.service",
    "fii_dii":             "nidp.services.fii_dii.service",
    "corporate_actions":   "nidp.services.corporate_actions.service",
    "nse_calendar":        "nidp.services.nse_calendar.service",
    "rbi_yields":          "nidp.services.rbi_yields.service",
    "fred_macro":          "nidp.services.fred_macro.service",
    "yfinance_backfill":   "nidp.services.yfinance_backfill.service",
    "amfi_nav":               "nidp.services.amfi_nav.service",
    "amfi_nav_history":       "nidp.services.amfi_nav_history.service",
    "amfi_circulars":         "nidp.services.amfi_circulars.service",
    "mf_disclosure_snapshot": "nidp.services.mf_disclosure_snapshot.service",
    "mf_holdings":            "nidp.services.mf_holdings.service",
    "event_calendar":         "nidp.services.event_calendar.service",
    "nse_financials":         "nidp.services.nse_financials.service",
    "event_analyzer":         "nidp.services.event_analyzer.service",
}

DATE_REQUIRED: set[str] = {"bhavcopy", "delivery", "index_close", "fii_dii"}


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ── Commands ────────────────────────────────────────────────────────
async def cmd_migrate(args: argparse.Namespace) -> int:
    """Apply all .sql files in nidp/migrations/ in name order. Each
    file is run in a single transaction; failures roll back.

    Idempotency is the migration's responsibility (every NIDP migration
    uses CREATE … IF NOT EXISTS / INSERT … ON CONFLICT)."""
    pool = await get_pool()
    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}")
        return 0

    async with pool.acquire() as conn:
        # Bootstrap migrations table — needed before checking applied set
        # (also created by 001_nidp_base.sql, but cheap to ensure).
        await conn.execute("CREATE SCHEMA IF NOT EXISTS nidp")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS nidp.schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                sha256      TEXT
            )
        """)
        applied = {r["filename"] for r in await conn.fetch(
            "SELECT filename FROM nidp.schema_migrations"
        )}

        for f in files:
            if f.name in applied and not args.force:
                print(f"  ✓ {f.name} (already applied)")
                continue
            sql = f.read_text()
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                print(f"  ✅ {f.name} applied")
            except Exception as e:                                 # noqa: BLE001
                print(f"  ❌ {f.name} FAILED: {e}")
                return 1
    return 0


async def cmd_ingest(args: argparse.Namespace) -> int:
    if args.service not in SERVICES:
        print(f"Unknown service: {args.service!r}. "
              f"Try: {', '.join(sorted(SERVICES))}")
        return 2
    if args.service in DATE_REQUIRED and not args.date:
        print(f"Service '{args.service}' requires --date")
        return 2

    mod = importlib.import_module(SERVICES[args.service])
    run_fn = getattr(mod, "run")

    if args.service in DATE_REQUIRED:
        await run_fn(args.date)
    else:
        await run_fn(args.date)  # most services accept Optional[date]
    return 0


async def cmd_health(_: argparse.Namespace) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval("SELECT 1")
        ts_ext = await conn.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
        )
        nidp_tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nidp'"
        )
    print(f"  Postgres reachable:        {v == 1}")
    print(f"  TimescaleDB extension:     {ts_ext or '(not installed)'}")
    print(f"  Tables in nidp schema:     {nidp_tables}")
    return 0


def cmd_list_services(_: argparse.Namespace) -> int:
    print("Available NIDP services:")
    for name in sorted(SERVICES):
        date_req = "  [date required]" if name in DATE_REQUIRED else ""
        print(f"  - {name}{date_req}")
    return 0


async def cmd_snapshot(args: argparse.Namespace) -> int:
    from nidp.services.snapshot_builder.service import run as build, status as _status
    if args.snap_cmd == "status":
        row = await _status(args.date)
        if not row:
            print("(no snapshot row found)")
            return 0
        for k, v in row.items():
            print(f"  {k}: {v}")
        return 0
    # default → build
    if not args.date:
        print("snapshot build requires --date")
        return 2
    try:
        run_id = await build(args.date, force=args.force)
        print(f"snapshot built: {args.date} run_id={run_id}")
        return 0
    except RuntimeError as e:
        print(f"snapshot build FAILED: {e}")
        return 1


async def cmd_validate(args: argparse.Namespace) -> int:
    """Run validation rules against the most recent successful run for
    the given (service, date). Useful for ad-hoc audits without
    re-ingesting."""
    from nidp.shared.validation import run_validation
    if args.service not in SERVICES:
        print(f"Unknown service: {args.service!r}")
        return 2
    # Trigger import-side-effect so the registry is populated.
    importlib.import_module(f"nidp.services.{args.service}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        target = args.date
        row = await conn.fetchrow(
            """
            SELECT run_id FROM nidp.job_log
             WHERE ingester = $1
               AND ($2::date IS NULL OR target_date = $2::date)
               AND status IN ('OK','PARTIAL')
             ORDER BY started_at DESC LIMIT 1
            """,
            args.service, target,
        )
    if not row:
        print(f"no successful run found for {args.service}"
              f"{' on ' + target.isoformat() if target else ''}")
        return 1
    run_id = row["run_id"]
    summary = await run_validation(
        ingester=args.service, target_date=target, job_run_id=run_id,
    )
    print(f"  status:          {summary.status}")
    print(f"  rules_run:       {summary.rules_run}")
    print(f"  rules_failed:    {summary.rules_failed}")
    print(f"  findings:        {summary.findings_count}")
    print(f"  has BLOCK:       {summary.has_block}")
    for f in summary.findings[:10]:
        print(f"   - [{f.severity.value}/{f.failure_class.value}] "
              f"{f.rule_name}: {f.message}")
    return 0 if not summary.has_block else 1


async def cmd_daas_keygen(args: argparse.Namespace) -> int:
    """Mint a new DaaS API key. The cleartext token is printed once
    here and never stored — the DB only retains its SHA-256 hash."""
    from nidp.services.daas_api import keys as daas_keys
    expires_at = None
    if args.expires_in_days:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        expires_at = _dt.now(tz=_tz.utc) + _td(days=args.expires_in_days)
    try:
        out = await daas_keys.issue_key(
            name=args.name,
            owner_email=args.owner,
            plan=args.plan,
            rate_limit_rpm=args.rpm,
            daily_quota=args.daily_quota,
            expires_at=expires_at,
            notes=args.notes,
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2
    print("─" * 64)
    print("  ✅ DaaS API key issued. STORE THIS TOKEN NOW — it will not be shown again.")
    print("─" * 64)
    print(f"  token:        {out['token']}")
    print(f"  key_id:       {out['key_id']}")
    print(f"  prefix:       {out['key_prefix']}")
    print(f"  name:         {out['name']}")
    print(f"  owner:        {out['owner_email']}")
    print(f"  plan:         {out['plan']}")
    print(f"  rpm:          {out['rate_limit_rpm']}")
    print(f"  daily_quota:  {out['daily_quota'] or 'unlimited'}")
    print(f"  created_at:   {out['created_at']}")
    print(f"  expires_at:   {out['expires_at'] or 'never'}")
    print("─" * 64)
    return 0


async def cmd_daas_keys(args: argparse.Namespace) -> int:
    from nidp.services.daas_api import keys as daas_keys
    if args.daas_cmd == "list":
        rows = await daas_keys.list_keys()
        if not rows:
            print("(no keys)")
            return 0
        for r in rows:
            mark = " " if r["status"] == "active" else "✗"
            print(f"  {mark} [{r['plan']:8s}] {r['key_prefix']}…  "
                  f"{r['name']:25s}  {r['owner_email']:30s}  "
                  f"rpm={r['rate_limit_rpm']}  quota={r['daily_quota'] or '∞'}  "
                  f"last_used={r['last_used_at'] or '—'}")
        return 0
    if args.daas_cmd == "revoke":
        ok = await daas_keys.revoke_key(key_id=args.key_id)
        print(f"  {'✓ revoked' if ok else '— already revoked or not found'}: {args.key_id}")
        return 0 if ok else 1
    print(f"unknown daas-keys subcommand: {args.daas_cmd}")
    return 2


# ── Entrypoint ──────────────────────────────────────────────────────
def main() -> None:
    setup_logging(service="nidp-cli")

    p = argparse.ArgumentParser(prog="nidp")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_mig = sub.add_parser("migrate", help="Apply pending DB migrations.")
    p_mig.add_argument("--force", action="store_true", help="Re-apply even if already in schema_migrations.")

    p_ing = sub.add_parser("ingest", help="Run an ingester.")
    p_ing.add_argument("service", help="Service name (see list-services).")
    p_ing.add_argument("--date", type=_parse_date, default=None)

    sub.add_parser("list-services", help="Show available services.")
    sub.add_parser("health",        help="Connectivity + schema check.")

    _add_backfill_subparser(sub)

    p_snap = sub.add_parser("snapshot", help="Snapshot engine (build / status).")
    snap_sub = p_snap.add_subparsers(dest="snap_cmd", required=True)
    p_snap_build = snap_sub.add_parser("build", help="Build the daily snapshot for --date.")
    p_snap_build.add_argument("--date", type=_parse_date, required=True)
    p_snap_build.add_argument("--force", action="store_true",
                              help="Build even if preflight fails.")
    p_snap_status = snap_sub.add_parser("status", help="Show readiness for a date.")
    p_snap_status.add_argument("--date", type=_parse_date, default=None)

    p_val = sub.add_parser("validate",
                           help="Run validation rules against the most recent successful run.")
    p_val.add_argument("service")
    p_val.add_argument("--date", type=_parse_date, default=None)

    p_kg = sub.add_parser("daas-keygen", help="Issue a new DaaS API key.")
    p_kg.add_argument("--name", required=True, help="Human label, e.g. 'AcmeCorp prod'.")
    p_kg.add_argument("--owner", required=True, help="Owner email (for revocation contact).")
    p_kg.add_argument("--plan", default="free",
                      choices=["free", "standard", "pro", "internal"],
                      help="Tier — controls default rpm + daily quota.")
    p_kg.add_argument("--rpm", type=int, default=None,
                      help="Override rpm cap (defaults to plan).")
    p_kg.add_argument("--daily-quota", type=int, default=None,
                      help="Override daily quota (defaults to plan; 0 = unlimited).")
    p_kg.add_argument("--expires-in-days", type=int, default=None,
                      help="Auto-expire after N days; default = never.")
    p_kg.add_argument("--notes", default=None)

    p_dk = sub.add_parser("daas-keys", help="List or revoke DaaS API keys.")
    p_dk_sub = p_dk.add_subparsers(dest="daas_cmd", required=True)
    p_dk_sub.add_parser("list", help="List all keys with status + last-used.")
    p_dk_rev = p_dk_sub.add_parser("revoke", help="Revoke by key_id.")
    p_dk_rev.add_argument("--key-id", required=True)

    args = p.parse_args()

    if args.cmd == "list-services":
        sys.exit(cmd_list_services(args))

    handler = {
        "migrate":     cmd_migrate,
        "ingest":      cmd_ingest,
        "health":      cmd_health,
        "backfill":    cmd_backfill,
        "snapshot":    cmd_snapshot,
        "validate":    cmd_validate,
        "daas-keygen": cmd_daas_keygen,
        "daas-keys":   cmd_daas_keys,
    }[args.cmd]

    try:
        rc = asyncio.run(_runner(handler, args))
    finally:
        try:
            asyncio.run(close_pool())
        except Exception:                                          # noqa: BLE001
            pass
    sys.exit(rc)


async def _runner(handler, args):
    return await handler(args)


if __name__ == "__main__":
    main()
