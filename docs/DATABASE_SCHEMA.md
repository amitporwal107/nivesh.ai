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

Strategy Builder / the shared strategy store (app database `public`; `backend/nidp/migrations/020`, `115`,
`backend/migrations/024`, `026`): `strategies` (owner, `asset_class` STOCK | MF | FNO | MIXED, `source` user | ai |
template | clone | plan, `template_id`, `underlying`, `cloned_from`), `strategy_versions` (immutable rows — trigger
`trg_strategy_versions_immutable`, only `is_active` changes; `schema_version` '1' equity DSL | '2' legs document,
`parent_version_id`, `change_summary`, Copilot provenance columns, per-strategy `idempotency_key`), `strategy_runs`
(BACKTEST/LIVE, status RUNNING | OK | FAILED with `error_message`), `strategy_trades`, `strategy_audit`, `strategy_config`,
`user_universes`. Migration 026 is applied by the `app-migrate` profile (deploy with `run_migrations=true`), not by a merge.

## Nivesh MongoDB — collections (full list §6.3)
`users`, `holdings`, `portfolio_snapshots`, `action_plans`, `plan_history`, `chat_sessions`,
`portfolio_intelligence_signals`, `pg_mirror_*` (WORM mirrors for post-deploy restore),
`fund_holdings_cache`, `system_config` (secrets + flags).

Broker hub: `broker_accounts` (one row per connected broker login; the session token is stored
encrypted in `api_key_encrypted` / `extras_encrypted`, the client id only as a hash and a masked
form), `broker_oauth_states` (sign-in attempts, 10-minute life), `broker_sync_snapshots` (one
immutable record per holdings sync, at most 90 per account; indexes on `snapshot_id` unique and
`(user_id, broker_account_id, synced_at desc)`). Holdings rows read from a broker carry
`broker_account_id`, `broker`, `source` (`broker_native` | `openalgo` | `broker_export`) and `isin`.

F&O IV history: `fno_iv_history` (one document per underlying and session, `_id` `"<UNDERLYING>:<YYYY-MM-DD>"`,
upserted; index `(underlying, date desc)` created by the recorder). Fields: `underlying, date, as_of, calc_version
(fno-atm-iv-v1), source, rate_pct, method (recorded | backfill, first write), recorded_at, computed_at` and
`buckets.{near_month,next_month}` = `expiry, days_to_expiry, atm_strike, spot, future_settle, forward, forward_basis,
call_iv, call_iv_price, put_iv, put_iv_price, atm_iv, reason`. Written only by `backend/scripts/record_iv_history.py`
(nightly cron documented in the script, not installed); see `backend/services/fno_iv_history.py`. A session that was
not read has no document; nothing is interpolated.

Desk trade plans and lifecycle (Phase 2.1 / 2.2): `trade_plans` — one TradePlan per `_id` = `plan_id` (`"tp_"` + a hash of
its content, `backend/services/strategy_plan/trade_plan.py`), inserted once; `owners[]` (who built it; a `system:` owner is
readable by everyone), `lineage_key` + `version` + `supersedes` + `revalidation{ok, problems, after_approval}` for a changed
plan of the same instrument / family / day, `events[]` (REJECTED records of refused opens). `desk_paper_trades` and
`ai_trader_tickets` gain `state` and append-only `transitions[]` (`backend/services/trade_lifecycle.py`); trades also
`plan_ref`, `trade_plan_id`, `plan_levels`, `exit_plan.options` (strategy_levels premium stop / T1 / T2, stored, evaluated
by the exits work), `rolled_from` / `rolled_to`. Backfill for older documents: `backend/scripts/backfill_trade_lifecycle.py`
(dry run by default).

Postgres migration 025: `positional_signals.revision`, `positional_signals.stop_method` (JSONB) and
`positional_signals_history` (a scanner re-run or day rewrite keeps the row it replaces; PK
`(nse_symbol, signal_date, revision)`).

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
