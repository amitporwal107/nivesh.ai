# DATABASE_SCHEMA.md — Nivesh.ai / NIDP

> Canonical detail: `TECHNICAL_ARCHITECTURE.md` §6 (full schema map).
> Honesty rule: migration files are the ultimate truth. Verify against the live DB before
> claiming a column/table exists. Mark unbuilt `PLANNED`.

## Three databases
| DB | Host:Port | Name | Engine / ext | Migrations |
|---|---|---|---|---|
| NIDP market data | `nidp-stack-vm:5433` | `nidp` | TimescaleDB (PG16) + `timescaledb` + `pgvector` | 83 SQL files (`001_…` → `083_…`) |
| Nivesh analytics | `nivesh-app-vm:5432` | `nivesh_prod` | PostgreSQL 16 + `uuid-ossp` + `pg_trgm` | 25+ |
| Nivesh user data | `nivesh-app-vm:27017` | `nivesh_prod` | MongoDB 7 | — |

## NIDP TimescaleDB — schemas (full map in §6.1)
`nidp` (operational + hypertables: `prices_eod`, `delivery_data`, `index_eod`,
`fii_dii_flows`, `corporate_actions`, bulk/block deals, `rbi_yields`, `fred_macro_observations`,
plus snapshots, fundamentals, `stock_features_daily`, MF tables, `v3_*_scores_daily`, events,
bank scoring) · `ref` (security_master) · `dq` (gate_verdicts, dlq_findings, feed_sla,
snapshot_status) · `features` · `graph` · `events` · `analytics` (stock_card, sector_snapshot,
fund_category_rank, 4 materialized views) · `portfolio` (bridged user snapshots) · `audit` ·
`monitoring` (container_health).

## Nivesh PostgreSQL — key tables (full list §6.2)
`instrument_master`, `mutual_fund_metadata` (incl. `quality_score`, `health_score`,
`exit_score_baseline`, `add_score_baseline`, `v3_scored_at`), `mutual_fund_nav_history`,
`mutual_fund_aum_history`, `mutual_fund_performance_ratios`, `mutual_fund_holdings`,
`benchmark_master`, `scrape_audit_log`, `nav_analytics_job_log`, `schema_migrations`.

## Nivesh MongoDB — collections (full list §6.3)
`users`, `holdings`, `portfolio_snapshots`, `action_plans`, `plan_history`, `chat_sessions`,
`portfolio_intelligence_signals`, `pg_mirror_*` (WORM mirrors for post-deploy restore),
`fund_holdings_cache`, `system_config` (secrets + flags).

## Conventions
snake_case tables/columns · UUID PKs (`uuid-ossp`) on app PG · timestamps UTC · money as
`NUMERIC`, never float · NAV `NUMERIC(12,4)`.

## Migration rules (hard)
- Forward-only; write `IF NOT EXISTS`. Never edit an applied migration.
- App: `python -m scripts.post_deploy_migrate`; manual `psql $POSTGRES_URL -f <file>.sql`.
- NIDP: run via `deploy/vm/deploy.sh`; check applied with
  `psql $NIDP_POSTGRES_URL -c "SELECT filename FROM nidp.schema_migrations ORDER BY applied_at;"`.
- `alembic downgrade` ONLY after taking a PG snapshot. Destructive changes need sign-off.
- A migration isn't "done" until it ran against a real DB and the output is shown.

## Data-correctness verification (for QA + dev "data test")
```sql
-- feed freshness / failures
SELECT source_name, last_success_at, consecutive_failures FROM nidp.v_feed_status;
-- DQ blockers in last 24h (must be empty to claim healthy)
SELECT ingester, rule_name, severity, message FROM nidp.validation_findings
  WHERE severity='BLOCK' AND created_at > NOW() - INTERVAL '24h';
-- V3 score freshness
SELECT fund_name, quality_score, health_score, v3_scored_at FROM mutual_fund_metadata
  WHERE v3_scored_at > NOW() - INTERVAL '24h' ORDER BY quality_score DESC LIMIT 10;
```
