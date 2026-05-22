"""Migration runner.

Discovers ``NNN_*.sql`` files alongside this module, applies any whose
filename isn't already recorded in ``portfolio_ingestion.schema_migrations``,
and records what it applied (with sha-256 of the file content) so re-runs
are no-ops and content drift is detectable.

CLI:
    PI_POSTGRES_URL=postgresql://user:pass@host:5432/db \\
        python -m portfolio_ingestion.db.migrations.runner up
    python -m portfolio_ingestion.db.migrations.runner status
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from ..pool import get_pool, reset_pool_for_test
from ...config import get_settings
from ...logging_setup import configure as configure_logging

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent
FILENAME_RE = re.compile(r"^(\d{3,})_[a-z0-9_]+\.sql$")

SCHEMA_MIGRATIONS_DDL = """
CREATE SCHEMA IF NOT EXISTS portfolio_ingestion;
CREATE TABLE IF NOT EXISTS portfolio_ingestion.schema_migrations (
    filename    TEXT PRIMARY KEY,
    sha256      VARCHAR(64) NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclasses.dataclass(frozen=True)
class Migration:
    filename: str
    path: Path
    sha256: str

    @property
    def version(self) -> int:
        m = FILENAME_RE.match(self.filename)
        if not m:
            raise ValueError(f"Bad migration filename: {self.filename}")
        return int(m.group(1))


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Return migrations in ascending version order."""
    out: list[Migration] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".sql":
            continue
        if not FILENAME_RE.match(path.name):
            log.warning("Skipping unrecognised migration filename: %s", path.name)
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append(Migration(filename=path.name, path=path, sha256=sha))
    out.sort(key=lambda m: m.version)
    return out


async def _ensure_migration_table(conn: "asyncpg.Connection") -> None:
    await conn.execute(SCHEMA_MIGRATIONS_DDL)


async def _already_applied(conn: "asyncpg.Connection") -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT filename, sha256 FROM portfolio_ingestion.schema_migrations"
    )
    return {r["filename"]: r["sha256"] for r in rows}


async def apply_pending(directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply all pending migrations; return their filenames in order."""
    pool = await get_pool()
    applied_now: list[str] = []
    async with pool.acquire() as conn:
        await _ensure_migration_table(conn)
        applied = await _already_applied(conn)
        migrations = discover_migrations(directory)
        if not migrations:
            log.warning("No migration files found in %s", directory)
            return applied_now

        for mig in migrations:
            if mig.filename in applied:
                if applied[mig.filename] != mig.sha256:
                    raise RuntimeError(
                        f"Drift detected for {mig.filename}: "
                        f"stored sha256={applied[mig.filename]!r} "
                        f"file sha256={mig.sha256!r}"
                    )
                log.info("Skipping already-applied %s", mig.filename)
                continue

            log.info(
                "Applying migration %s (sha=%s...)",
                mig.filename,
                mig.sha256[:8],
                extra={"eventType": "MIGRATION_APPLY"},
            )
            sql = mig.path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO portfolio_ingestion.schema_migrations "
                    "(filename, sha256) VALUES ($1, $2)",
                    mig.filename,
                    mig.sha256,
                )
            applied_now.append(mig.filename)
    return applied_now


async def status(directory: Path = MIGRATIONS_DIR) -> list[tuple[str, bool]]:
    """Return [(filename, applied)] for every discovered migration."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_migration_table(conn)
        applied = await _already_applied(conn)
        return [(m.filename, m.filename in applied) for m in discover_migrations(directory)]


# ── CLI ────────────────────────────────────────────────────────────────────

async def _async_main(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    if not settings.postgres_url:
        log.error("PI_POSTGRES_URL is not set.")
        return 2

    try:
        if args.command == "up":
            applied = await apply_pending()
            if not applied:
                log.info("No pending migrations.")
            else:
                log.info("Applied: %s", ", ".join(applied))
            return 0
        if args.command == "status":
            rows = await status()
            for fn, ok in rows:
                print(f"{'✓' if ok else ' '} {fn}")
            return 0
        log.error("Unknown command: %s", args.command)
        return 2
    finally:
        from ..pool import close_pool

        await close_pool()
        reset_pool_for_test()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="portfolio_ingestion.db.migrations.runner")
    parser.add_argument("command", choices=["up", "status"])
    args = parser.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
