# Post-Deploy Migration — Production Data Sync

Single source of truth for moving V3 master + primitive + scored data from preview
to a freshly-provisioned production environment.

## Architecture

```
┌─────────────────┐    mirror_pg_to_mongo    ┌──────────────────────┐
│  Preview PG     │ ───────────────────────▶ │   Mongo pg_mirror_*  │
│  (Neon, dev)    │    weekly + on-demand    │   collections (WORM) │
└─────────────────┘                          └──────────┬───────────┘
                                                        │
                                  restore_pg_from_mirrors
                                                        ▼
┌──────────────────┐   post_deploy_migrate     ┌─────────────────────┐
│  Production PG   │ ◀──────────────────────── │   7-phase pipeline  │
│  (Neon, fresh)   │   one-click from Admin UI │                     │
└──────────────────┘                           └─────────────────────┘
```

## The 7-Phase Sequence

Orchestrated by `backend/scripts/post_deploy_migrate.py` and exposed at
`POST /api/admin/datastores/post-deploy-migrate`.

| # | Phase               | Duration | Idempotent | Skippable |
|---|---------------------|----------|-----------|-----------|
| 0 | hydrate_secrets     | <200ms   | ✓         | ✗         |
| 1 | health_check        | <600ms   | ✓         | ✗         |
| 2 | apply_migrations    | <1.5s    | ✓         | ✗         |
| 3 | restore_mirrors     | ~18s     | ✓         | ✗         |
| 4 | replay_scrape_cache | ~5min    | ✓         | ✓ (default: **skipped**) |
| 5 | analytics_sweep     | ~14s     | ✓         | ✓         |
| 6 | v3_rescore          | ~4s      | ✓         | ✓         |
| 7 | smoke_check         | <600ms   | ✓         | ✗         |

**Total (default config):** ~38s end-to-end.

### Phase details

**0 · hydrate_secrets** — Reads `system_config.secrets` from MongoDB and injects
`POSTGRES_URL` + `REDIS_URL` into the process environment. Mongo is the only
durable secret store; every other service reads from here.

**1 · health_check** — Pings Mongo, PG, and Redis to fail fast if a datastore is
unreachable. Prevents partial migrations.

**2 · apply_migrations** — Iterates `backend/migrations/*.sql` in filename order,
executes each via asyncpg (no `psql` binary needed), and tracks applied migrations
in a `schema_migrations` table. Auto-marks "already exists" errors as applied so
re-running against a pre-seeded PG is safe.

**3 · restore_mirrors** — Replays every `pg_mirror_*` Mongo collection into PG
using upsert semantics. Handles natural-key uniqueness (ON CONFLICT) except for
`mutual_fund_holdings` which uses delete-by-instrument-then-insert since its PK
is `id serial`. Coerces JSON-round-tripped datetimes back to the right PG type
(tz-aware vs tz-naive).

Tables restored (all rows):
- `instrument_master`          (~2.4k rows)
- `benchmark_master`           (~34 rows)
- `mutual_fund_metadata`       (~185 rows — includes V3 scored fields)
- `mutual_fund_performance_ratios`  (~210 rows)
- `mutual_fund_holdings`       (~16k rows — latest 180 days)
- `mutual_fund_nav_history`    (~247k rows — last 5 years)
- `mutual_fund_aum_history`    (~210 rows)

**4 · replay_scrape_cache** — Replays `fund_holdings_cache` Mongo mirror through
`pg_writer.persist_scrape`. **Skipped by default** because Phase 3 already ships
a newer snapshot; only enable when Mongo has received fresh scrapes since the
last mirror. Slow (~7s/payload).

**5 · analytics_sweep** — Runs `nav_analytics_sweep.run_analytics_sweep()` to
compute NAV-derived primitives (consistency_score, max_drawdown_pct, downside_
capture_pct) from the NAV history restored in Phase 3.

**6 · v3_rescore** — Invalidates every Redis V3 score key (the cache is ephemeral,
so this is a clean reset) then runs `nav_analytics_sweep.run_v3_rescore()` which
rescores every MF via the V3.1 category-aware engine.

**7 · smoke_check** — Counts instruments, MF metadata, NAV rows, performance
ratios, V3-scored funds, benchmark master, and Moneycontrol-enriched debt funds.
If these line up with preview numbers, the migration was complete.

## Operator Workflow

### Preview environment (where you develop)

Take a fresh snapshot whenever master data changes:

```bash
# CLI
cd /app/backend && python -m scripts.mirror_pg_to_mongo

# Admin UI
Admin → Infra & Data → "Mirror PG → Mongo" button
```

### Production environment (post-deploy)

Run the orchestrator immediately after deploy:

```bash
# CLI
cd /app/backend && python -m scripts.post_deploy_migrate

# Admin UI
Admin → Infra & Data → "Run Post-Deploy Migration" button
```

Skip flags (for faster re-runs when you know a phase is up-to-date):

| Flag              | What it skips                             | When to use                              |
|-------------------|-------------------------------------------|------------------------------------------|
| `--skip-replay`   | Phase 4 (fund_holdings_cache replay)      | Default — Phase 3 already covers this    |
| `--skip-sweep`    | Phase 5 (analytics sweep)                 | Master data hasn't changed               |
| `--skip-rescore`  | Phase 6 (V3 rescore)                      | Weights haven't changed                  |

## What's NOT migrated

User-generated data lives exclusively in MongoDB (persistent across deploys):
- `users`, `sessions`, `holdings`, `action_plans`, `plan_board`
- `cas_uploads`, `portfolio_analysis_cache`
- `fund_holdings_cache` (scrape mirror)
- `system_config` (secrets)

These require **no migration step** — they travel with the Mongo URL.

## Troubleshooting

**Phase 3 fails on `timestamp` mismatch** — the restore script coerces tz-aware
↔ tz-naive automatically; if you hit this, the source column type in PG has
changed. Check `information_schema.columns` and update the coercion map in
`_coerce_for_pg()`.

**Phase 6 fails with `POSTGRES_URL not set`** — Phase 0 didn't hydrate secrets.
Check that `system_config.secrets` in Mongo has a `POSTGRES_URL` entry.

**Production PG empty after Phase 3** — The mirror collections are empty. Run
`mirror_pg_to_mongo` against a populated preview DB first.

## Retention / Storage

The mirror tables roughly total **~40 MB** in Mongo (dominated by NAV history).
Each `mirror_pg_to_mongo` run does a full drop-and-replace per collection, so
storage is constant over time. `pg_mirror_meta` records `mirrored_at` timestamps
for each table so you can detect stale mirrors.
