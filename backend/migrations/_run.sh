#!/usr/bin/env bash
# _run.sh — apply pending nivesh-app SQL migrations.
#
# Tracks applied migrations in public.schema_migrations (filename, applied_at,
# sha256). Each .sql file runs in a single transaction (psql -1). If it
# succeeds, its filename + sha256 is recorded. On failure, the transaction
# rolls back and this script exits non-zero.
#
# Modes:
#   _run.sh              — apply all unapplied migrations (default)
#   _run.sh --bootstrap  — register every existing migration as already applied
#                          WITHOUT executing the SQL. Use once on a database
#                          that was migrated by the old bash loop, so the new
#                          runner doesn't try to re-apply history.
#   _run.sh --force      — re-apply even files already in schema_migrations.
#
# Requires:
#   POSTGRES_URL  env var  postgresql://user:pass@host:port/db
#
# Filename prefix '_' keeps this file out of the *.sql glob.

set -euo pipefail

MIGRATIONS_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="apply"

for arg in "$@"; do
  case "$arg" in
    --bootstrap) MODE="bootstrap" ;;
    --force)     MODE="force" ;;
    -h|--help)
      sed -n '2,22p' "$0"; exit 0 ;;
    *)
      echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if [[ -z "${POSTGRES_URL:-}" ]]; then
  echo "ERROR: POSTGRES_URL is not set" >&2
  exit 1
fi

psql_cmd() { psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 "$@"; }

log() { printf '\033[1;36m[migrate]\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m[migrate]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[migrate]\033[0m %s\n' "$*" >&2; }

# ── 1. Ensure tracking table exists ────────────────────────────────────────
psql_cmd <<'SQL' >/dev/null
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sha256     TEXT
);
SQL

# ── 2. Enumerate files in lexical order ────────────────────────────────────
shopt -s nullglob
files=( "$MIGRATIONS_DIR"/*.sql )
shopt -u nullglob

if [[ ${#files[@]} -eq 0 ]]; then
  log "no .sql files in $MIGRATIONS_DIR"
  exit 0
fi

IFS=$'\n' files=($(printf "%s\n" "${files[@]}" | sort)); unset IFS

# ── 3. Load already-applied set ────────────────────────────────────────────
applied="$(psql_cmd -tAc 'SELECT filename FROM public.schema_migrations')"

# ── 3b. Safety: refuse to run in 'apply' mode if schema_migrations is
# empty BUT the DB already has user tables. This is the fingerprint of a
# database migrated by the old loose runner — re-executing existing files
# could corrupt backfilled data via non-idempotent INSERT/UPDATE/ALTER.
# Operator must explicitly run --bootstrap first (zero risk) or --force
# (eyes-open re-apply).
if [[ "$MODE" == "apply" ]]; then
  applied_n="$(psql_cmd -tAc 'SELECT count(*) FROM public.schema_migrations')"
  if [[ "$applied_n" == "0" ]]; then
    user_tables="$(psql_cmd -tAc "
      SELECT count(*) FROM information_schema.tables
       WHERE table_schema = 'public'
         AND table_type   = 'BASE TABLE'
         AND table_name  != 'schema_migrations'
    ")"
    if [[ "$user_tables" -gt 0 ]]; then
      err "REFUSING TO RUN."
      err ""
      err "schema_migrations is empty, but this database already has"
      err "$user_tables user tables. This looks like a DB that was previously"
      err "migrated by the old loose runner."
      err ""
      err "Running pending migrations now would attempt to re-execute every"
      err "existing .sql file, which can corrupt backfilled data via"
      err "non-idempotent statements (INSERT, UPDATE, ALTER ADD COLUMN)."
      err ""
      err "Run ONCE with --bootstrap to register existing migrations as"
      err "applied WITHOUT executing them:"
      err "    docker compose --profile migrate run --rm migrate --bootstrap"
      err ""
      err "After that, default mode is safe — only new files will run."
      exit 1
    fi
  fi
fi

is_applied() {
  printf '%s\n' "$applied" | grep -qxF "$1"
}

applied_count=0
skipped_count=0
failed_count=0

# ── 4. Process each file according to mode ─────────────────────────────────
for f in "${files[@]}"; do
  fname=$(basename "$f")
  sha=$(sha256sum "$f" | cut -d' ' -f1)

  if [[ "$MODE" == "bootstrap" ]]; then
    if is_applied "$fname"; then
      log "  ✓ $fname (already tracked)"
      skipped_count=$((skipped_count+1))
    else
      psql_cmd -c "INSERT INTO public.schema_migrations (filename, sha256) VALUES ('$fname', '$sha')" >/dev/null
      ok "  ⏺ $fname (bootstrap — marked applied without running)"
      applied_count=$((applied_count+1))
    fi
    continue
  fi

  if is_applied "$fname" && [[ "$MODE" != "force" ]]; then
    log "  ✓ $fname (already applied)"
    skipped_count=$((skipped_count+1))
    continue
  fi

  log "  → $fname applying..."
  if psql "$POSTGRES_URL" -1 -v ON_ERROR_STOP=1 -f "$f"; then
    psql_cmd -c "INSERT INTO public.schema_migrations (filename, sha256)
                 VALUES ('$fname', '$sha')
                 ON CONFLICT (filename) DO UPDATE
                   SET applied_at = NOW(), sha256 = EXCLUDED.sha256" >/dev/null
    ok "  ✅ $fname applied"
    applied_count=$((applied_count+1))
  else
    err "  ❌ $fname FAILED — transaction rolled back"
    failed_count=$((failed_count+1))
    exit 1
  fi
done

echo ""
log "summary: applied=$applied_count  skipped=$skipped_count  failed=$failed_count  mode=$MODE"
