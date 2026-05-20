# NIDP Data Lake Fix — Post-Deploy Verification

PR `feat/nidp-data-lake-fixes` wires three previously-dark engines into the nightly cron and adds an MF look-through view. This is the runbook for verifying the fixes are landing real data **before** anyone builds the Exit/Review scoring engine on top of them.

## What changed

| Change | File |
|---|---|
| `mf_analytics_engine` added to cron at 20:30 IST Mon-Fri | `backend/nidp/deploy/vm/nidp.cron` + `setup_schedules.sh` |
| `technical_indicator_engine` added to cron at 22:35 IST Mon-Fri | same |
| `fundamental_engine` added to cron at 23:05 IST Mon-Fri | same |
| `populate_stock_price_features()` SQL call wired into TI engine | `services/technical_indicator_engine/service.py` |
| Migration 059 — `nidp.v_mf_lookthrough_quality` view | `nidp/migrations/059_*.sql` |
| `run(target_date)` adapters on all 3 engines for backfill orchestrator | `services/*/service.py` |
| `feed_health_check` extended with depth diagnostics | `services/feed_health_check/__main__.py` |

## Post-deploy checklist (operator)

### 1. Apply migration 059

```bash
sudo -u nidp psql -d nidp -f /opt/nidp/repo/backend/nidp/migrations/059_nidp_mf_lookthrough_quality.sql
```

Confirm:

```bash
sudo -u nidp psql -d nidp -c "SELECT filename FROM nidp.schema_migrations ORDER BY filename DESC LIMIT 3;"
```
Must list `059_nidp_mf_lookthrough_quality.sql`.

### 2. Reload cron

```bash
sudo cp /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron /etc/cron.d/nidp
sudo systemctl reload cron
sudo crontab -u nidp -l | grep -E "mf_analytics_engine|technical_indicator_engine|fundamental_engine"
```
Must show all three engine lines.

### 3. Wait one trading-day evening, then run three SQL sanity checks

**Check A — `analytics.fund_category_rank` has fresh rows:**

```sql
SELECT as_of_date, COUNT(*) AS schemes
  FROM analytics.fund_category_rank
 WHERE as_of_date >= CURRENT_DATE - INTERVAL '3 days'
 GROUP BY as_of_date
 ORDER BY as_of_date DESC;
```

Expected: ≥ 10 000 schemes for the most recent weekday. If 0 rows, `mf_analytics_engine` didn't fire — check `nidp.job_log WHERE ingester = 'mf_analytics_engine'`.

**Check B — `stock_features_daily` has populated Piotroski + volatility for NIFTY 500:**

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(piotroski_score)   AS has_piotroski,
    COUNT(altman_z_score)    AS has_altman,
    COUNT(volatility_1y_pct) AS has_vol_1y,
    COUNT(max_drawdown_1y_pct) AS has_drawdown,
    COUNT(return_252d_pct)   AS has_return_252d
  FROM nidp.stock_features_daily
 WHERE as_of_date = CURRENT_DATE - INTERVAL '1 day';
```

Expected after both engines have run + the day has ≥ 252 bars of price history:
- `has_piotroski / rows >= 0.80` (some symbols lack quarterly financials → NULL)
- `has_altman / rows >= 0.80`
- `has_vol_1y / rows >= 0.80` for symbols with ≥ 60 bars of adj-close
- `has_return_252d / rows >= 0.80`

If `has_piotroski` is 0: `fundamental_engine` didn't run. Check the job_log.
If `has_vol_1y` is 0: the SQL function `populate_stock_price_features` is failing — check the TI engine log for `ti_engine_price_features_error`.

**Check C — `v_mf_lookthrough_quality` returns rows with reasonable coverage:**

```sql
SELECT
    COUNT(*) AS schemes,
    AVG(coverage_pct)::numeric(5,1) AS avg_coverage,
    COUNT(*) FILTER (WHERE coverage_pct >= 60) AS schemes_above_60,
    COUNT(*) FILTER (WHERE lookthrough_pe IS NOT NULL)   AS has_pe,
    COUNT(*) FILTER (WHERE lookthrough_piotroski IS NOT NULL) AS has_piotroski
  FROM nidp.v_mf_lookthrough_quality;
```

Expected (for top-10 AMC equity funds with current month's disclosure):
- `schemes >= 500`
- `avg_coverage >= 65%` (M+10 reporting lag is the main drag)
- `schemes_above_60 / schemes >= 0.70`
- `has_piotroski` is the limiting factor — only populated for stocks whose `fundamental_engine` row also has a Piotroski score.

If `schemes` is 0: holdings table (`mf_holdings_monthly`) hasn't been refreshed this month yet, OR sector_master ISIN map is empty.
If `has_piotroski` is 0 but `has_pe > 0`: `fundamental_engine` hasn't run yet for the latest stock_features date.

### 4. (Optional) Run depth report

```bash
sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh feed_health_check
```

The JSON output's `depth_checks` field will tell you how far back each table goes — useful before deciding how aggressive a backfill to run.

### 5. (Optional) One-shot backfill

If checks A or B show `< 252 bars` per symbol, run a backfill of the last 90 days of the derived engines so the Action Matrix has continuity:

```bash
sudo -u nidp python -m nidp.cli backfill \
  --services technical_indicator_engine,fundamental_engine,mf_analytics_engine \
  --from $(date -d '90 days ago' +%F) \
  --to $(date -d 'yesterday' +%F)
```

This is idempotent — re-running picks up where a prior run left off via `nidp.job_log`.

**Heavier prerequisite:** if `nidp.prices_eod` itself is shallow (< 365 days), backfill bhavcopy first:

```bash
sudo -u nidp python -m nidp.cli backfill --services bhavcopy \
  --from $(date -d '1 year ago' +%F) --to $(date -d 'yesterday' +%F)
```

## Failure modes & remediation

| Symptom | Likely cause | Fix |
|---|---|---|
| `mf_analytics_engine` not in `job_log` after 21:00 IST | cron didn't reload | `sudo systemctl reload cron`, check `/var/log/syslog` for cron parse errors |
| `populate_stock_price_features` returns 0 rows | `prices_eod_adjusted` empty for target_date | confirm `price_adjuster` ran successfully at 22:30 |
| `v_mf_lookthrough_quality` has 0 rows but `mf_holdings_monthly` is fresh | ISIN mismatch — `sector_master.isin` not joined | run `nse_equity_master` to refresh ISIN mappings |
| `fundamental_engine` row in job_log = FAILED with "no symbols" | TI engine didn't run first / row count = 0 for target date | re-run TI engine for the date manually |

## When to declare the data lake "green"

All three SQL checks above pass with the expected thresholds for **two consecutive trading days**. After that, the next phase (`exit_score_engine.py` + `consolidation_score_engine.py`) becomes safe to build on top — every factor input the scoring engine reads is now populated by a scheduled job, not silently NULL.
