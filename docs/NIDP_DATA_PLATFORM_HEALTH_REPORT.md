# NIDP Data Platform — Current-State Health Report

**Generated:** 2026-05-21 04:30 UTC (10:00 IST)
**Author:** Claude (read-only investigation; no production state was mutated)

---

## Scope and confidence

What I could verify from this dev container:

- **Data freshness** — direct queries to the live NIDP TimescaleDB via the public DAAS API (`https://data.niveshcopilot.com/daas/v1/*`) with the internal API key. The numbers below are the **actual current state** of the warehouse, not estimates.
- **NSE archive URLs** — directly tested the bhavcopy/fno/index_close/delivery URLs against `nsearchives.nseindia.com` for the missed dates. Results below.
- **Cron schedule** — read from [backend/nidp/deploy/vm/nidp.cron](../backend/nidp/deploy/vm/nidp.cron) (the repo file that is deployed to `/etc/cron.d/nidp` on `nidp-stack-vm`).
- **Ingester code** — read from [backend/nidp/services/*](../backend/nidp/services/) and [backend/nidp/shared/sources/nse_fetcher.py](../backend/nidp/shared/sources/nse_fetcher.py).

What I could **not** verify (requires `gcloud compute ssh nidp-stack-vm` access, which the harness blocked for read-only diagnostics — pending re-authorization):

- Per-ingester `nidp.job_log` rows for 5/19+5/20 — the only place that tells us **why** a specific job failed.
- Whether the deployed `/etc/cron.d/nidp` matches the repo file.
- Container status (running / restarting / OOM-killed / stopped) on the VM.
- `docker logs` for the announcement classifier and bhavcopy services.

**Everything in §1–3 is verified fact. §4 is hypothesis explicitly waiting on VM-side confirmation.**

---

## 1. Executive Summary — verified freshness

Today is **Thu 2026-05-21**. The last completed trading session was **Wed 2026-05-20**. There are no holidays in 5/19–5/21 per `nidp.nse_holidays`.

| Tier | Datasets | Last `as_of_date` |
|------|----------|-------------------|
| ✅ Fresh | fii_dii_flows, bulk_deals, mf_nav_daily, corporate_announcements (raw ingest), fred_macro, portfolio sync (3 users) | 2026-05-20 (or current) |
| ✅ Future-dated by design | corporate_actions (next ex-date) | 2026-06-10 |
| 🔴 2 trading-day gap | **prices_eod, prices_eod_adjusted, index_eod, delivery_data, fno_bhavcopy** | 2026-05-18 |
| 🔴 2 trading-day gap (downstream of above) | stock_features_daily (TI engine), market_daily_snapshot, stock_daily_snapshot | 2026-05-18 |
| 🔴 10-day gap | analytics.market_snapshot, graph.correlations, dq.quality_scores, features.stock_features_daily | 2026-05-11 |
| 🔴 12+ hour backlog | corporate_announcements **classification** (200/200 most recent unclassified) | n/a |
| 🟡 1 missed weekly publish | rbi_yields (weekly Friday cadence) | 2026-05-08 (missed 5/15) |
| 🟥 Never landed | mf_holdings_monthly (0 rows), mf_scheme_events (0), mf_scheme_disclosure_snapshot (0), intel entity_links (0), intel normalized_events (0), DAAS signals (0), shareholding_pattern (200 rows, single quarter) | — |

---

## 2. The 2026-05-11 freeze pattern (verified)

Multiple independent signals all point to the same date. This is a real pattern, not coincidence:

| Signal | Last activity | Source |
|--------|--------------|--------|
| All backfill runs ever (3 total) | 2026-05-11 19:29 UTC | `/v1/backfill/runs` |
| All replay runs ever (5 total) | 2026-05-11 20:19 UTC | `/v1/replay/runs` |
| Last DQ proposal generated | 2026-05-10 19:52 UTC | `/v1/dq/diagnostics` |
| Last DQ expectation promoted | 2026-05-10 20:21 UTC | `/v1/dq/expectations/active` |
| Last DQ score computed | 2026-05-15 23:15 UTC (`target_date = 2026-05-11`) | `/v1/intelligence/dq/scores` |
| `analytics.market_snapshot` last row | 2026-05-11 | catalog |
| `graph.correlations` last row | 2026-05-11 | catalog |
| `features.stock_features_daily` last row | 2026-05-11 | catalog |
| `ref.security_master` last update | 2026-05-15 23:15 UTC | catalog (the one outlier) |
| Core ingesters (`fii_dii`, `bulk_deals`, `amfi_nav`, raw announcements, portfolio sync) | 2026-05-20 — still firing | catalog |

**The split is informative:** the cron-driven base ingesters that write to `nidp.*` schema kept running through 2026-05-20. Everything that writes to the **enrichment schemas** (`analytics.*`, `graph.*`, `dq.*`, `features.*`) — and all admin actions (backfill, replay, proposal accept) — stopped on 2026-05-11.

The freeze is **scoped to the enrichment / orchestration layer**, not the base ingesters. Even an unauthorized actor who simply stopped one set of cron entries or one container would produce exactly this pattern. We can't distinguish between "selective container failure" and "intentional pause" without `nidp.job_log` and `docker ps` history.

---

## 3. Per-failure investigation — what's verified and what isn't

### 3.1 The 4 NSE bhavcopy/delivery/index/fno feeds stuck at 2026-05-18

**Verified facts:**

| Feed | Cron line | URL pattern | Direct URL test for 5/19+5/20 |
|------|-----------|-------------|-------------------------------|
| `bhavcopy` | `0 19 * * 1-5` | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | **HTTP 200, 188k / 189k bytes** |
| `fno_bhavcopy` | `30 19 * * 1-5` | `nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | **HTTP 200, 1.4M / 1.4M bytes** |
| `index_close` | `0 19 * * 1-5` | `nsearchives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv` | **HTTP 200, 15.7k / 15.6k bytes** |
| `delivery` | `30 10 * * 2-6` | `nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv` | **HTTP 200, 364k / 364k bytes** |

**What this rules out:**
- NSE did **not** change URLs on 5/19. The files exist and are downloadable from a non-VM IP with the same browser-style User-Agent and Referer that [nse_fetcher.py](../backend/nidp/shared/sources/nse_fetcher.py) uses.
- The URL builders in [backend/nidp/shared/config.py:65-167](../backend/nidp/shared/config.py#L65-L167) and the cutover-date logic in [backend/nidp/services/bhavcopy/service.py:34-37](../backend/nidp/services/bhavcopy/service.py#L34-L37) are not the bug.

**What this leaves on the table** (cannot distinguish without VM access):
- Cron entries for these specific services disabled or commented on the deployed `/etc/cron.d/nidp`.
- The bhavcopy/fno/index_close/delivery containers stopped or crashed (`docker ps -a` would show).
- Fetcher succeeded but the parse/persist step failed (`nidp.job_log.error_message` would show).
- NSE returning a different error code from the VM's outbound IP than from this dev container's IP (Akamai geo-fencing or rate-limit).
- The `nidp.market_session_state` table is stuck and the ingester is re-targeting 5/18, producing no new rows. (Mitigated by the 24h fallback in `v_market_session` view, but worth confirming.)

Sister ingesters on the **same cron line** that hit JSON APIs (`fii_dii` on 19:30, `bulk_deals` on 19:30) ran successfully on 5/19 and 5/20 — so the cron daemon itself is firing.

### 3.2 Intelligence orchestrator frozen since 2026-05-11

**Verified facts:** §2 above. 7 distinct intel-layer signals all stop at 2026-05-11; only `ref.security_master` advanced (to 2026-05-15).

**What we don't know:** which container or cron entry drives the enrichment schemas (`analytics.*`, `graph.*`, `dq.*`, `features.*`). The repo cron file has an `intelligence_layer` entry at `23:20 weekday`, but whether it's deployed and whether the container exits clean or errors is VM-side.

### 3.3 Announcement classifier — 12+ hour backlog

**Verified facts:**
- Raw `corporate_announcements` ingest is fresh: last `filed_at = 2026-05-21 04:09 UTC`.
- Of the 200 most recent rows (5/20 16:22 UTC → 5/21 04:09 UTC), **0 have `classification_run_at` set**. All `symbol` and `category` fields are null.
- Cron entry: `*/30 * * * *` (every 30 min). Should have run ~24 times in the window.

**What we don't know:** whether the classifier container is running, what its logs say, whether it's hitting the Anthropic Haiku API and being rate-limited or auth-rejected.

### 3.4 block_deals on 5/19+5/20 — likely sparse, not broken

Per-day count probe:

| Date | bulk_deals | block_deals |
|------|------------|-------------|
| 5/06 | 81 | **0** |
| 5/13 | 125 | **0** |
| 5/15 | 73 | **0** |
| 5/19 | 98 | **0** |
| 5/20 | 82 | **0** |

`block_deals` already had multiple 0-row days while infra was healthy. The pattern is consistent with sparse data, not broken ingester. Cannot confirm from outside.

### 3.5 rbi_yields — weekly Friday publish, missed 2026-05-15

Date-range probe (4/15 → 5/21) shows 13 rows across 3 distinct dates: 2026-04-24, 2026-05-01, 2026-05-08 — all **Fridays**, 4–5 rows per date (different tenors). RBI publishes weekly; daily cron is a polling pattern. Missed publication: 2026-05-15.

### 3.6 MF intelligence chain — never operational

| Table | Rows | Cron expectation |
|-------|------|------------------|
| `mf_holdings_monthly` | 0 | `0 11 12 * *` IST (12th of month) |
| `mf_scheme_disclosure_snapshot` | 0 | `0 10 12 * *` IST |
| `mf_scheme_events` | 0 | derived from circulars |
| `mf_amfi_circulars` | 1 | `0 9 * * *` IST daily |

These tables are zero rows total, not "missed last month" — suggests the ingesters either crash on first run or write to a different table. The 2026-05-12 monthly window passed with no rows landing.

### 3.7 Data-quality observations

| Observation | Severity | Mitigation that exists today |
|-------------|----------|------------------------------|
| `market_daily_snapshot.nifty50_close = 6,015.86` on 2026-05-08 (off by ~3.9×) | High | None — no DQ expectation on this dataset |
| `prices_eod.close_price = 2456.5 > high_price` (DQ diagnostic 2026-05-10) | High | LLM-proposed expectation generated, never accepted |
| Only 4 DQ expectations active across 35 datasets (all on `fii_dii_flows`) | Med | Per `/v1/dq/expectations/active` |

---

## 4. Cron inventory (from repo — may differ from deployed VM file)

From [backend/nidp/deploy/vm/nidp.cron](../backend/nidp/deploy/vm/nidp.cron). All weekday entries Mon–Fri unless noted; all IST.

| Time | Service(s) |
|------|------------|
| 06:00 (1st of month) | nse_calendar |
| 06:30 weekday | event_calendar |
| 07:00 Sunday | nse_equity_master |
| 09:00 daily | amfi_circulars |
| 09–16 weekday */5min | event_day_poller |
| 09–23 weekday */10min | corporate_announcements_nse, corporate_announcements_bse |
| 10:30 Tue–Sat | delivery (T+1) |
| every 15 min | document_parser |
| every 30 min (all days) | announcement_classifier |
| 19:00 weekday | **bhavcopy, index_close, d1_prep** |
| 19:30 weekday | fii_dii, bulk_deals, block_deals, **fno_bhavcopy** |
| 20:00 daily | corporate_actions |
| 20:00 weekday | amfi_nav, intelligence, event_calendar |
| 20:30 weekday | rbi_yields, nse_financials, mf_analytics_engine |
| 21:00 daily | fred_macro, nse_shareholding |
| 22:00 weekday | snapshot_builder |
| 22:30 weekday | price_adjuster, quality_gate |
| 22:35 weekday | technical_indicator_engine |
| 23:00 weekday | portfolio_holdings_sync |
| 23:05 weekday | fundamental_engine |
| 23:10 weekday | portfolio_transactions_sync |
| 23:15 weekday | portfolio_goals_sync |
| 23:20 weekday | intelligence_layer |
| 23:30 weekday | portfolio_intelligence_sync |
| 23:50 weekday | mf_derived_refresh |
| 10:00 + 11:00 (12th of month) | mf_disclosure_snapshot, mf_holdings |

**Caveat:** the deployed `/etc/cron.d/nidp` on `nidp-stack-vm` may differ. Historically it lagged the repo (memory note: TI engine wasn't in the deployed file until 2026-05-20). Confirm with:

```bash
gcloud compute ssh ubuntu@nidp-stack-vm --zone=asia-south1-a --tunnel-through-iap \
  --command='sudo diff /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron /etc/cron.d/nidp'
```

---

## 5. Action plan

Separated by what I can do from this dev environment vs. what needs VM access.

### 5.1 Doable now from this dev env (no VM access needed)

| # | Action | What it accomplishes | Authorization needed |
|---|--------|----------------------|----------------------|
| A1 | Promote the DQ expectation `prices_eod.close_price BETWEEN low_price AND high_price` (per the LLM proposal from 5/10) via `POST /v1/dq/expectations/active` | Catches `close > high` rows like the one DQ found on 5/10 going forward | Yes — writes to `dq.expectations_active` |
| A2 | Add `market_daily_snapshot.nifty50_close BETWEEN 15000 AND 35000` via the same endpoint | Catches sanity errors like the 6,015.86 row on 5/8 | Yes — writes to `dq.expectations_active` |
| A3 | Add similar range expectations to `index_eod`, `mf_nav_daily` | Broaden DQ coverage from the current 4 rules on 1 dataset | Yes — writes to `dq.expectations_active` |

### 5.2 Needs VM access (gcloud SSH) — read-only diagnostics first

Run before any destructive action. None of these write or restart anything:

```bash
PATH=/root/google-cloud-sdk/bin:$PATH

# D1. Container roster — which services are running / restarting / stopped
gcloud compute ssh ubuntu@nidp-stack-vm --zone=asia-south1-a --tunnel-through-iap \
  --command='docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | head -50'

# D2. Actual errors for the 4 stuck ingesters + classifier since 5/18
gcloud compute ssh ubuntu@nidp-stack-vm --zone=asia-south1-a --tunnel-through-iap \
  --command='docker exec $(docker ps --format "{{.Names}}" | grep -m1 postgres) psql -U nidp -At -F"|" -c "
    SELECT ingester, status, target_date, started_at, COALESCE(error_message,'\'''\'')
      FROM nidp.job_log
     WHERE ingester IN ('\''bhavcopy'\'','\''fno_bhavcopy'\'','\''index_close'\'','\''delivery'\'','\''announcement_classifier'\'')
       AND started_at > '\''2026-05-18'\''
     ORDER BY started_at DESC LIMIT 100"'

# D3. Intelligence-layer activity since the 5/11 freeze
gcloud compute ssh ubuntu@nidp-stack-vm --zone=asia-south1-a --tunnel-through-iap \
  --command='docker exec $(docker ps --format "{{.Names}}" | grep -m1 postgres) psql -U nidp -At -F"|" -c "
    SELECT service, status, started_at, COALESCE(error_message,'\'''\'')
      FROM nidp.job_log
     WHERE service IN ('\''intelligence_layer'\'','\''intelligence'\'','\''dq_ai'\'',
                       '\''quality_gate'\'','\''event_analyzer'\'',
                       '\''portfolio_intelligence_sync'\'')
       AND started_at > '\''2026-05-10'\''
     ORDER BY started_at DESC LIMIT 100"'

# D4. Deployed cron vs repo
gcloud compute ssh ubuntu@nidp-stack-vm --zone=asia-south1-a --tunnel-through-iap \
  --command='sudo diff /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron /etc/cron.d/nidp'

# D5. Classifier logs (if container exists)
gcloud compute ssh ubuntu@nidp-stack-vm --zone=asia-south1-a --tunnel-through-iap \
  --command='docker logs --since 6h $(docker ps -a --format "{{.Names}}" | grep -i announcement_classifier | head -1) 2>&1 | tail -100'
```

### 5.3 Needs VM access — destructive fixes (confirm before each)

Once D1–D5 tell us the root cause, the fixes are:

| # | Fix | Pre-req | Risk |
|---|-----|---------|------|
| F1 | Restart stopped containers (`docker restart …`) | D1 shows them stopped | Low — these were supposed to be running anyway |
| F2 | Re-enable disabled cron entries on `/etc/cron.d/nidp` | D4 shows them disabled | Low |
| F3 | Manually trigger missed runs: `sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh bhavcopy --date 2026-05-19` (and 5/20) for each broken service | D2 confirms run is needed | Low — idempotent upserts; safe to re-run |
| F4 | Re-run the derived chain after F3: `price_adjuster` → `technical_indicator_engine` → `fundamental_engine` → `snapshot_builder` | F3 succeeded | Low — same idempotent pattern |
| F5 | Restart intelligence orchestrator (whichever container D3 implicates) | D3 result | Med — pulls data into enrichment schemas |
| F6 | UPDATE `nidp.market_daily_snapshot SET nifty50_close = (SELECT close FROM nidp.index_eod WHERE index_name='NIFTY 50' AND as_of_date='2026-05-08') WHERE as_of_date='2026-05-08'` | A2 expectation added (so we know future bad rows fire) | **DB write — confirm before running** |
| F7 | Investigate why MF monthly jobs never wrote rows (D2-style query for `mf_holdings` / `mf_disclosure_snapshot` service history) | None | None until we know |

---

## 6. Probe recipes — re-runnable

```bash
export KEY=$NIDP_DAAS_API_KEY
BASE=https://data.niveshcopilot.com/daas

# Catalog (master freshness table — 35 datasets in one call)
curl -sS -H "X-API-Key: $KEY" $BASE/v1/catalog | jq '.datasets[] | {name, last_at, rows}'

# Backfill + replay history (use --http1.1 to avoid HTTP/2 PROTOCOL_ERROR on loops)
curl -sS --http1.1 -H "X-API-Key: $KEY" "$BASE/v1/backfill/runs?limit=30"
curl -sS --http1.1 -H "X-API-Key: $KEY" "$BASE/v1/replay/runs?limit=30"

# DQ engine state
curl -sS --http1.1 -H "X-API-Key: $KEY" "$BASE/v1/dq/diagnostics?limit=10"
curl -sS --http1.1 -H "X-API-Key: $KEY" "$BASE/v1/dq/expectations/active?limit=50"
curl -sS --http1.1 -H "X-API-Key: $KEY" "$BASE/v1/intelligence/dq/scores?limit=20"

# Sanity-test that NSE archives are reachable (rules out URL bugs)
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
for d in 20260519 20260520; do
  curl -sS -o /dev/null -w "bhavcopy $d %{http_code} %{size_download}\n" \
    -A "$UA" -H "Referer: https://www.nseindia.com/all-reports" \
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_${d}_F_0000.csv.zip"
done

# Classifier backlog (raw vs classified count)
curl -sS --http1.1 -H "X-API-Key: $KEY" "$BASE/v1/announcements?limit=200" | \
  jq '[.data[]|select(.classification_run_at==null)] | length'
```
