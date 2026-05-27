# NIDP Data Quality Gates — Extended Rules Catalogue
## Configurable via Great Expectations

| Field | Value |
|---|---|
| **Document Type** | Engineering Reference / Companion to PRD |
| **Status** | Draft v1.0 |
| **Last Updated** | 2026-05-27 |
| **Audience** | NIDP Platform Engineers, Data Engineers |
| **Companion Doc** | NIDP DQ Gates PRD |

---

## 1. How This Document Works

This document extends the 7 gates defined in the NIDP DQ Gates PRD with **concrete, runnable rules** for every relevant feed in the NIDP catalogue. Every rule is expressed in two forms:

1. **Plain-English invariant** — what the rule asserts.
2. **Great Expectations configuration** — the runnable form (YAML + Python).

### 1.1 Why Great Expectations

Great Expectations (GE) is your existing DQ tool. It provides:
- Declarative expectations (rules) as YAML/JSON.
- Built-in column, multi-column, and SQL-based expectations.
- A pluggable framework for custom expectations.
- Checkpoint runs that emit standardized validation results.

The gap is that today your rules are **column-level and finite**. This document fills that gap by:
- Adding **multi-column row-level invariants** (e.g., OHLC sanity).
- Adding **cross-table referential rules** (e.g., delivery ⊆ bhavcopy symbols).
- Adding **temporal/drift rules** (e.g., NAV change distribution within trailing window).
- Adding **output-layer semantic rules** (e.g., V3 score reconciliation).

### 1.2 Configuration model

All rules are configurable via three YAML files per feed:

```
nidp_dq_gates/
├── config/
│   ├── feeds/
│   │   ├── bhavcopy.yaml          # Feed-level params (SLA, severity, thresholds)
│   │   ├── delivery.yaml
│   │   └── ...
│   ├── expectations/
│   │   ├── bhavcopy.json          # GE expectation suite
│   │   ├── delivery.json
│   │   └── ...
│   └── gates/
│       ├── gate1_ingestion.yaml   # Which expectations run at gate 1
│       ├── gate2_stream.yaml
│       └── ...
```

This means **engineers tune rules by editing YAML**, not by changing code. A new threshold ships as a config PR, not a code release.

### 1.3 Rule severity (carried from PRD)

| Severity | Action | Use For |
|----------|--------|---------|
| **P0** | Block + alert | Data corruption that breaks scores |
| **P1** | Pass with AMBER + alert | Degraded but usable data |
| **P2** | Pass with note | Cosmetic / informational |

---

## 2. Shared Configuration Schema

Every feed has a `feeds/<feed>.yaml` with this schema:

```yaml
# Example: config/feeds/bhavcopy.yaml
feed:
  name: bhavcopy
  table: nidp.bhavcopy
  owner: nidp-platform
  
sla:
  freshness:
    expected_arrival: "17:45 IST"
    grace_period_minutes: 30
    trading_days_only: true
  completeness:
    min_rows: 1800
    max_rows: 2200
    band_from_history_days: 30
    band_tolerance_pct: 2.0

severity_overrides:
  # Override default severity for specific rules
  ohlc_sanity: P0
  zero_volume_rate: P2
  
gates:
  enabled_at: [gate1, gate2, gate3, gate7]
  
dependencies:
  # Cross-feed references
  symbol_master: ref.sector_master
  
notifications:
  p0_channel: pagerduty:nidp-oncall
  p1_channel: slack:#nidp-dq
  p2_channel: log_only
```

---

## 3. Gate 1 — Ingestion Gate Rules

**Where it runs:** Inside each ingester service, before publishing to Redpanda.
**Speed budget:** < 50ms per message batch.
**Failure action:** Route to `dq.quarantine.<feed>` topic; do not publish to main.

### 3.1 Universal rules (apply to every feed)

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G1-U-001` | Schema matches Schema Registry | Avro deserialization (built-in) | P0 |
| `G1-U-002` | Required headers present (`ingest_run_id`, `source_checksum`, `source_timestamp`) | Custom expectation `expect_kafka_headers_to_be_present` | P0 |
| `G1-U-003` | Source timestamp not in future | `expect_column_values_to_be_between` | P0 |
| `G1-U-004` | Source timestamp not older than 7 days | `expect_column_values_to_be_between` | P1 |
| `G1-U-005` | Trading-day alignment (for trading-day feeds) | Custom expectation `expect_date_to_be_trading_day` | P0 |
| `G1-U-006` | Row count within trailing 30-day band | `expect_table_row_count_to_be_between` with dynamic bounds | P0 |

**GE config example (`expectations/_universal_gate1.json`):**

```json
{
  "expectation_suite_name": "gate1_universal",
  "expectations": [
    {
      "expectation_type": "expect_column_values_to_be_between",
      "kwargs": {
        "column": "source_timestamp",
        "min_value": {"$datetime": "now-7d"},
        "max_value": {"$datetime": "now"}
      },
      "meta": {"severity": "P0", "rule_id": "G1-U-003"}
    },
    {
      "expectation_type": "expect_date_to_be_trading_day",
      "kwargs": {
        "column": "trade_date",
        "exchange": "NSE",
        "allow_backfill_flag": true
      },
      "meta": {"severity": "P0", "rule_id": "G1-U-005"}
    }
  ]
}
```

### 3.2 Feed-specific rules — bhavcopy (feed #1)

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G1-BHV-001` | `symbol` not null and ≤ 20 chars | `expect_column_values_to_not_be_null` + `expect_column_value_lengths_to_be_between` | P0 |
| `G1-BHV-002` | All OHLC prices > 0 | `expect_column_values_to_be_between(min=0.01)` × 4 | P0 |
| `G1-BHV-003` | `volume >= 0` | `expect_column_values_to_be_between(min=0)` | P0 |
| `G1-BHV-004` | OHLC row sanity: `low <= open,close <= high` | `expect_multicolumn_values_to_satisfy_condition` | P0 |
| `G1-BHV-005` | Symbol count between 1800 and 2200 | `expect_table_row_count_to_be_between` | P0 |
| `G1-BHV-006` | Zero-volume rate < 1% of symbols | `expect_column_value_counts_to_be_between` | P2 |
| `G1-BHV-007` | Symbol cardinality drift < 2% vs previous trading day | Custom `expect_column_cardinality_to_match_window` | P1 |

**GE config:**

```yaml
# expectations/bhavcopy_gate1.yaml
expectations:
  - type: expect_column_values_to_not_be_null
    column: symbol
    severity: P0
    rule_id: G1-BHV-001
    
  - type: expect_multicolumn_values_to_satisfy_condition
    columns: [open, high, low, close]
    condition: "low <= open AND low <= close AND open <= high AND close <= high"
    severity: P0
    rule_id: G1-BHV-004
    
  - type: expect_table_row_count_to_be_between
    min_value: ${feeds.bhavcopy.sla.completeness.min_rows}  # interpolated
    max_value: ${feeds.bhavcopy.sla.completeness.max_rows}
    severity: P0
    rule_id: G1-BHV-005
```

### 3.3 Feed-specific rules — delivery (feed #2)

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G1-DLV-001` | `deliv_per` between 0 and 100 | `expect_column_values_to_be_between` | P0 |
| `G1-DLV-002` | `deliv_qty >= 0` | `expect_column_values_to_be_between(min=0)` | P0 |
| `G1-DLV-003` | `deliv_qty <= ttl_trd_qnty` | `expect_column_pair_values_a_to_be_less_than_or_equal_to_b` | P0 |
| `G1-DLV-004` | Date is T+1 of a trading day | Custom `expect_date_to_be_t_plus_n_trading_day` | P0 |

### 3.4 Feed-specific rules — amfi_nav (feed #16)

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G1-NAV-001` | `nav > 0` | `expect_column_values_to_be_between(min=0.0001)` | P0 |
| `G1-NAV-002` | Scheme code matches AMFI format (6-digit) | `expect_column_values_to_match_regex("^[0-9]{6}$")` | P0 |
| `G1-NAV-003` | Daily NAV change within category-specific band | Custom `expect_nav_change_within_category_band` | P0 |
| `G1-NAV-004` | Scheme count ≥ 98% of previous day | Custom `expect_row_count_to_be_within_pct_of_previous` | P1 |
| `G1-NAV-005` | No duplicate `(scheme_code, nav_date)` | `expect_compound_columns_to_be_unique` | P0 |

**Custom expectation example — NAV change band:**

```python
# nidp_dq_gates/expectations/expect_nav_change_within_category_band.py
class ExpectNavChangeWithinCategoryBand(ColumnMapExpectation):
    """
    Asserts daily NAV change is within category-specific bounds:
    - Equity funds: ±10%
    - Debt funds: ±2%
    - Liquid funds: ±0.1%
    """
    
    default_kwarg_values = {
        "category_bands": {
            "EQUITY": 0.10,
            "DEBT": 0.02,
            "LIQUID": 0.001,
            "HYBRID": 0.05,
        }
    }
    
    map_metric = "column_pair.nav_pct_change_within_category_band"
```

```yaml
# expectations/amfi_nav_gate1.yaml
- type: expect_nav_change_within_category_band
  column_pair: [nav, previous_nav]
  category_column: scheme_category
  category_bands:
    EQUITY: 0.10
    DEBT: 0.02
    LIQUID: 0.001
    HYBRID: 0.05
  severity: P0
  rule_id: G1-NAV-003
```

### 3.5 Feed-specific rules — nse_financials (feed #11)

XBRL parsing is fragile — these rules catch silent parser breaks.

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G1-FIN-001` | Revenue in plausible Nifty 500 range (1 to 500000 cr) | `expect_column_values_to_be_between` | P0 |
| `G1-FIN-002` | `total_debt >= 0` (XBRL sign check) | `expect_column_values_to_be_between(min=0)` | P0 |
| `G1-FIN-003` | `interest_expense >= 0` | `expect_column_values_to_be_between(min=0)` | P0 |
| `G1-FIN-004` | Quarter date is a real quarter-end | `expect_column_values_to_match_regex` (`^.*(03-31|06-30|09-30|12-31)$`) | P0 |
| `G1-FIN-005` | EPS reconciles with PAT/shares within 5% | Custom `expect_eps_to_reconcile` | P1 |

### 3.6 Feed-specific rules — nse_shareholding (feed #12)

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G1-SHR-001` | Promoter + FII + DII + Public + Others = 100 ± 0.5% | Custom `expect_columns_sum_to_value` | P0 |
| `G1-SHR-002` | All shareholding columns between 0 and 100 | `expect_column_values_to_be_between` × N | P0 |
| `G1-SHR-003` | `promoter_pledged <= promoter_total` | `expect_column_pair_values_a_to_be_less_than_or_equal_to_b` | P0 |
| `G1-SHR-004` | Promoter holding change QoQ < 10% (unless corp action exists) | Custom cross-feed rule | P1 |

### 3.7 Other feeds — rule index

| Feed | Rule Family | Key Rules |
|------|-------------|-----------|
| `fno_bhavcopy` (#3) | OI sanity | `oi >= 0`, contract count vs symbol coverage, IV bounds |
| `index_close` (#4) | Index plausibility | Index value > 0, day-over-day change < 15%, index_name in known set |
| `index_constituents` (#5) | Membership integrity | Symbol resolves in master, weight sums to ≈100 per index |
| `nse_equity_master` (#6) | Master ref integrity | ISIN format `^IN[A-Z0-9]{10}$`, unique on ISIN |
| `fii_dii` (#7) | Flow sanity | Buy/sell ≥ 0, magnitudes < ₹50,000 cr, date = recent trading day |
| `bulk_deals` (#8) | Trade plausibility | qty > 0, price > 0, qty × price within feasibility |
| `block_deals` (#9) | Trade plausibility | Trade value ≥ ₹5 cr (definition), price within day's H/L |
| `corporate_actions` (#10) | Action sanity | `ex_date >= announcement_date`, ratio format valid |
| `event_calendar` (#13) | Forward window | Date between today and today+90d, event_type in taxonomy |
| `corporate_announcements_*` (#14, #15) | Announcement integrity | Non-null text, classification fields valid taxonomy, source ∈ {nse, bse} |
| `amfi_circulars` (#18) | Circular plausibility | Date not future, circular_no unique |
| `mf_holdings` (#19, BROKEN) | Portfolio sanity | Weights sum to 100, ISINs resolve in master |
| `mf_disclosure_snapshot` (#20, BROKEN) | Disclosure sanity | TER ∈ [0, 3], AUM > 0, risk_category ∈ SEBI taxonomy |
| `rbi_yields` (#21) | Yield plausibility | Yield ∈ [0, 20], tenor ∈ known set |
| `fred_macro` (#22) | Series sanity | Series_id ∈ 8 curated set, value plausibility per series |
| `yfinance_backfill` (#23) | OHLCV sanity | Same as bhavcopy, applied historically |

---

## 4. Gate 2 — Stream Processing Gate Rules

**Where it runs:** Kafka consumer that writes from Redpanda → TimescaleDB.
**Speed budget:** < 200ms per message.
**Failure action:** Route to `dq.dlq.<feed>` topic + `dq.dlq_findings` table; do not commit Kafka offset.

### 4.1 Universal rules

| Rule ID | Invariant | GE Expectation | Severity |
|---------|-----------|----------------|----------|
| `G2-U-001` | Idempotency: no duplicate (PK, timestamp) | `expect_compound_columns_to_be_unique` | P0 |
| `G2-U-002` | Source-timestamp monotonic per partition | Custom `expect_timestamps_monotonic_per_partition` | P1 |
| `G2-U-003` | `ingest_run_id` is a valid UUID | `expect_column_values_to_match_regex` | P0 |
| `G2-U-004` | Foreign keys resolve (feed-specific) | SQL-based `UnexpectedRowsExpectation` | P0 |

### 4.2 Referential integrity rules (cross-feed)

This is where Great Expectations' **SQL-based expectations** are critical.

#### Rule G2-REF-001: bhavcopy.symbol must exist in sector_master

```yaml
- type: unexpected_rows_expectation
  rule_id: G2-REF-001
  severity: P0
  unexpected_rows_query: |
    SELECT b.symbol, b.trade_date 
    FROM nidp.bhavcopy b
    LEFT JOIN ref.sector_master sm ON b.symbol = sm.symbol
    WHERE b.trade_date = '{batch_date}'
      AND sm.symbol IS NULL
  max_unexpected_rows: 0
```

#### Rule G2-REF-002: delivery.symbol ⊆ bhavcopy.symbol (same date)

```yaml
- type: unexpected_rows_expectation
  rule_id: G2-REF-002
  severity: P0
  unexpected_rows_query: |
    SELECT d.symbol
    FROM nidp.delivery d
    LEFT JOIN nidp.bhavcopy b 
      ON d.symbol = b.symbol AND d.trade_date = b.trade_date
    WHERE d.trade_date = '{batch_date}'
      AND b.symbol IS NULL
  max_unexpected_rows: 5  # tolerance for late-arriving symbols
```

#### Rule G2-REF-003: mf_nav_daily.scheme_code must exist in mf_scheme_master

```yaml
- type: unexpected_rows_expectation
  rule_id: G2-REF-003
  severity: P0
  unexpected_rows_query: |
    SELECT n.scheme_code
    FROM nidp.mf_nav_daily n
    LEFT JOIN nidp.mf_scheme_master m ON n.scheme_code = m.scheme_code
    WHERE n.nav_date = '{batch_date}'
      AND m.scheme_code IS NULL
  max_unexpected_rows: 0
```

#### Rule G2-REF-004: portfolio_holdings.isin must exist in sector_master OR mf_scheme_master

```yaml
- type: unexpected_rows_expectation
  rule_id: G2-REF-004
  severity: P1
  unexpected_rows_query: |
    SELECT ph.isin, ph.user_id
    FROM nidp.portfolio_holdings ph
    LEFT JOIN ref.sector_master sm ON ph.isin = sm.isin
    LEFT JOIN nidp.mf_scheme_master ms ON ph.isin = ms.isin
    WHERE ph.snapshot_date = '{batch_date}'
      AND sm.isin IS NULL
      AND ms.isin IS NULL
  max_unexpected_rows: 0
```

#### Rule G2-REF-005: index_constituents.symbol must exist in nse_equity_master

```yaml
- type: unexpected_rows_expectation
  rule_id: G2-REF-005
  severity: P0
  unexpected_rows_query: |
    SELECT ic.symbol, ic.index_name
    FROM nidp.index_constituents ic
    LEFT JOIN ref.sector_master sm ON ic.symbol = sm.symbol
    WHERE sm.symbol IS NULL
  max_unexpected_rows: 0
```

### 4.3 Cross-feed value consistency

#### Rule G2-CONS-001: corporate_actions ↔ bhavcopy price gap reconciliation

When a split/bonus exists, the price gap should match the ratio.

```yaml
- type: unexpected_rows_expectation
  rule_id: G2-CONS-001
  severity: P0
  unexpected_rows_query: |
    WITH price_pairs AS (
      SELECT 
        b1.symbol, b1.trade_date,
        b1.close AS close_today,
        b2.close AS close_prev,
        ABS(b1.close - b2.close) / b2.close AS gap_pct
      FROM nidp.bhavcopy b1
      JOIN nidp.bhavcopy b2 
        ON b1.symbol = b2.symbol
        AND b2.trade_date = b1.trade_date - INTERVAL '1 trading day'
      WHERE b1.trade_date = '{batch_date}'
    )
    SELECT pp.*
    FROM price_pairs pp
    LEFT JOIN nidp.corporate_actions ca
      ON pp.symbol = ca.symbol
      AND ca.ex_date = pp.trade_date
    WHERE pp.gap_pct > 0.20
      AND ca.symbol IS NULL  -- gap of >20% with no corporate action explanation
  max_unexpected_rows: 0
```

---

## 5. Gate 3 — Snapshot Completion Gate Rules

**Where it runs:** `snapshot_builder` preflight, before derivation engines.
**Speed budget:** < 60 seconds total.
**Failure action:** Block derivation chain; emit "Waiting on `<feed>`" status.

### 5.1 Feed presence rules

Implemented as one rule per critical feed:

```yaml
# config/gates/gate3_snapshot.yaml
required_feeds:
  - feed: bhavcopy
    rule_id: G3-PRES-001
    severity: P0
    expectation:
      type: expect_table_row_count_to_be_between
      kwargs:
        min_value: 1800
        max_value: 2200
        filter: "trade_date = '{snapshot_date}'"
        
  - feed: delivery
    rule_id: G3-PRES-002
    severity: P0
    expectation:
      type: expect_table_row_count_to_be_between
      kwargs:
        min_value: 1700  # delivery may be slightly less than bhavcopy
        max_value: 2200
        filter: "trade_date = '{snapshot_date}'"
        
  - feed: index_close
    rule_id: G3-PRES-003
    severity: P0
    expectation:
      type: expect_table_row_count_to_be_between
      kwargs:
        min_value: 20  # min indices to expect
        filter: "trade_date = '{snapshot_date}'"
        
  - feed: fii_dii
    rule_id: G3-PRES-004
    severity: P0
    expectation:
      type: expect_table_row_count_to_be_between
      kwargs:
        min_value: 1
        max_value: 1  # exactly one row per day
        filter: "trade_date = '{snapshot_date}'"
        
  - feed: corporate_actions
    rule_id: G3-PRES-005
    severity: P1
    expectation:
      type: expect_table_to_have_freshness_within
      kwargs:
        max_age_hours: 24
```

### 5.2 Cross-feed consistency rules

#### Rule G3-CONS-001: bhavcopy ↔ delivery symbol coverage

```yaml
- rule_id: G3-CONS-001
  severity: P0
  expectation:
    type: unexpected_rows_expectation
    kwargs:
      unexpected_rows_query: |
        WITH counts AS (
          SELECT 
            (SELECT COUNT(DISTINCT symbol) FROM nidp.bhavcopy 
             WHERE trade_date = '{snapshot_date}') AS bhav_count,
            (SELECT COUNT(DISTINCT symbol) FROM nidp.delivery 
             WHERE trade_date = '{snapshot_date}') AS dlv_count
        )
        SELECT * FROM counts
        WHERE ABS(bhav_count - dlv_count)::FLOAT / bhav_count > 0.02
      max_unexpected_rows: 0
```

#### Rule G3-CONS-002: Replication lag must be zero

```yaml
- rule_id: G3-CONS-002
  severity: P0
  expectation:
    type: unexpected_rows_expectation
    kwargs:
      data_source: nidp_primary
      unexpected_rows_query: |
        SELECT client_addr, replay_lag
        FROM pg_stat_replication
        WHERE replay_lag > INTERVAL '5 seconds'
      max_unexpected_rows: 0
```

#### Rule G3-CONS-003: No outstanding DLQ messages

```yaml
- rule_id: G3-CONS-003
  severity: P0
  expectation:
    type: unexpected_rows_expectation
    kwargs:
      unexpected_rows_query: |
        SELECT feed, COUNT(*) AS dlq_count
        FROM dq.dlq_findings
        WHERE batch_date = '{snapshot_date}'
          AND status = 'PENDING'
        GROUP BY feed
        HAVING COUNT(*) > 0
      max_unexpected_rows: 0
```

### 5.3 Snapshot integrity rules

#### Rule G3-INT-001: All shareholding percentages sum to 100

```yaml
- rule_id: G3-INT-001
  severity: P1
  expectation:
    type: unexpected_rows_expectation
    kwargs:
      unexpected_rows_query: |
        SELECT symbol, 
               (promoter_pct + fii_pct + dii_pct + public_pct + others_pct) AS total_pct
        FROM nidp.shareholding_pattern
        WHERE quarter_end = (SELECT MAX(quarter_end) FROM nidp.shareholding_pattern)
          AND ABS((promoter_pct + fii_pct + dii_pct + public_pct + others_pct) - 100) > 0.5
      max_unexpected_rows: 0
```

---

## 6. Gate 4 — Replication Integrity Gate Rules

**Where it runs:** Cron job on `nivesh-app-vm`, monitors `:5433 → :5434`.
**Frequency:** Lag check every 60s; parity checks daily.
**Failure action:** Route reads to primary; alert SRE.

### 6.1 Continuous rules

| Rule ID | Invariant | Implementation | Severity |
|---------|-----------|----------------|----------|
| `G4-CONT-001` | `replay_lag < 30s` | `pg_stat_replication` query | P0 |
| `G4-CONT-002` | Standby is in recovery mode | `pg_is_in_recovery() = true` | P0 |
| `G4-CONT-003` | WAL position advances every minute | LSN delta check | P1 |

```yaml
# gate4_continuous.yaml
- rule_id: G4-CONT-001
  severity: P0
  schedule: "*/1 * * * *"  # every minute
  expectation:
    type: unexpected_rows_expectation
    kwargs:
      data_source: nidp_primary
      unexpected_rows_query: |
        SELECT client_addr, replay_lag
        FROM pg_stat_replication
        WHERE replay_lag > INTERVAL '30 seconds'
      max_unexpected_rows: 0
```

### 6.2 Daily parity rules (one per critical hypertable)

```yaml
- rule_id: G4-PAR-001
  severity: P0
  schedule: "0 6 * * *"  # daily at 06:00 IST
  description: bhavcopy row count parity primary vs standby
  expectation:
    type: custom_dual_source_row_count
    kwargs:
      primary_query: "SELECT COUNT(*) FROM nidp.bhavcopy WHERE trade_date >= CURRENT_DATE - 30"
      standby_query: "SELECT COUNT(*) FROM nidp.bhavcopy WHERE trade_date >= CURRENT_DATE - 30"
      max_drift_rows: 0
      
- rule_id: G4-PAR-002
  description: mf_nav_daily checksum parity (sample)
  expectation:
    type: custom_dual_source_checksum
    kwargs:
      sample_query: |
        SELECT scheme_code, nav_date, nav
        FROM nidp.mf_nav_daily
        WHERE nav_date >= CURRENT_DATE - 7
        ORDER BY scheme_code, nav_date
      checksum_fn: xxhash64
      max_drift_rows: 0
```

The 5 critical hypertables per PRD: `bhavcopy`, `mf_nav_daily`, `v3_stock_scores_daily`, `portfolio_holdings`, `corporate_announcements`.

---

## 7. Gate 5 — Warm-Tier Export Gate Rules

**Where it runs:** `parquet_exporter` service.
**Speed budget:** Verification adds ≤ 10% to export time.
**Failure action:** Delete `_tmp/`, do not finalize partition.

### 7.1 Pre-finalization rules

```yaml
# gate5_parquet_export.yaml
- rule_id: G5-EXP-001
  severity: P0
  description: Row count in tmp Parquet matches source query
  expectation:
    type: custom_parquet_row_count_match
    kwargs:
      tmp_path: "s3://nidp-raw/parquet/{table}/year={y}/month={m}/_tmp/"
      source_query: "SELECT COUNT(*) FROM nidp.{table} WHERE {partition_filter}"
      tolerance: 0
      
- rule_id: G5-EXP-002
  severity: P0
  description: Parquet schema matches TimescaleDB column types
  expectation:
    type: custom_parquet_schema_match
    kwargs:
      tmp_path: "s3://nidp-raw/parquet/{table}/year={y}/month={m}/_tmp/"
      source_table: "nidp.{table}"
      
- rule_id: G5-EXP-003
  severity: P0
  description: Sample round-trip via DuckDB matches source within tolerance
  expectation:
    type: custom_parquet_sample_roundtrip
    kwargs:
      tmp_path: "s3://nidp-raw/parquet/{table}/year={y}/month={m}/_tmp/"
      source_query: "SELECT * FROM nidp.{table} WHERE {partition_filter} LIMIT 100"
      duckdb_query: "SELECT * FROM read_parquet('{tmp_path}/*.parquet') LIMIT 100"
      numeric_tolerance: 0.0001
      
- rule_id: G5-EXP-004
  severity: P0
  description: All Parquet files in tmp are valid and readable
  expectation:
    type: custom_parquet_validity
    kwargs:
      tmp_path: "s3://nidp-raw/parquet/{table}/year={y}/month={m}/_tmp/"
```

### 7.2 Post-finalization rules (daily reconciliation)

```yaml
- rule_id: G5-REC-001
  severity: P1
  schedule: "0 7 * * *"  # post-export reconciliation
  description: DuckDB query results match TimescaleDB for last 7 days
  expectation:
    type: custom_warm_hot_reconciliation
    kwargs:
      tables: [stock_features_daily, nse_financials_quarterly]
      lookback_days: 7
      compare_columns: [row_count, sum_numeric_cols, distinct_pk_count]
      max_drift_pct: 0.01
```

---

## 8. Gate 6 — API Output Gate Rules

**Where it runs:** DaaS API middleware on every `/v1/*` response.
**Speed budget:** < 20ms per response.
**Failure action:** Set `dq_status: RED`; payload still served but Copilot must respect status.

### 8.1 Response-envelope assembly rules

These are not blocking — they assemble the `data_quality` envelope by querying gate verdicts.

| Rule ID | Logic | Output |
|---------|-------|--------|
| `G6-ENV-001` | Look up all feed verdicts for `as_of_date` | `degraded_feeds[]` |
| `G6-ENV-002` | Compute `data_freshness_seconds` from latest source timestamp | `data_freshness_seconds` |
| `G6-ENV-003` | Aggregate severities to overall `dq_status` | `GREEN`/`AMBER`/`RED` |
| `G6-ENV-004` | Verify `snapshot_id` matches a successful `dq.snapshot_status` entry | If not, force `RED` |

**Aggregation logic:**

```python
def compute_dq_status(verdicts: List[GateVerdict]) -> str:
    if any(v.severity == "P0" and v.passed is False for v in verdicts):
        return "RED"
    if any(v.severity == "P1" and v.passed is False for v in verdicts):
        return "AMBER"
    return "GREEN"
```

### 8.2 Per-endpoint freshness rules

```yaml
# gate6_api.yaml
endpoints:
  - path: /v1/stock/v3-scores/{symbol}
    required_feeds: [bhavcopy, delivery, nse_financials_quarterly, shareholding_pattern]
    max_staleness_hours:
      bhavcopy: 24
      delivery: 48
      nse_financials_quarterly: 2160  # 90 days
      shareholding_pattern: 2160
    severity_override:
      bhavcopy: P0
      nse_financials_quarterly: P1
      
  - path: /v1/intelligence/portfolio/{user_id}/snapshot
    required_feeds: [portfolio_holdings, mf_nav_daily, v3_mf_scores_daily]
    max_staleness_hours:
      portfolio_holdings: 24
      mf_nav_daily: 24
      v3_mf_scores_daily: 24
```

---

## 9. Gate 7 — Observability Gate (SLO Rules)

**Where it runs:** Prometheus + Grafana, continuous.
**Failure action:** Burn-rate alerts to PagerDuty (fast) or Jira (slow).

### 9.1 SLO definitions per feed

```yaml
# gate7_slos.yaml
slos:
  - feed: bhavcopy
    objectives:
      - type: freshness
        target: 0.99
        window: 30d
        condition: "arrival_time <= 17:45 IST on trading days"
      - type: completeness
        target: 0.995
        window: 30d
        condition: "row_count BETWEEN 1800 AND 2200"
      - type: validity
        target: 0.999
        window: 30d
        condition: "all P0 gate1 rules pass"
      - type: referential
        target: 0.999
        window: 30d
        condition: "all gate2 referential rules pass"
        
  - feed: amfi_nav
    objectives:
      - type: freshness
        target: 0.99
        window: 30d
        condition: "arrival_time <= 23:00 IST"
      - type: completeness
        target: 0.995
        window: 30d
        condition: "scheme_count >= 4500"
```

### 9.2 Burn-rate alert config

```yaml
alerts:
  - name: bhavcopy_freshness_fast_burn
    slo: bhavcopy.freshness
    burn_rate: 14.4    # 2% budget in 1h
    window: 1h
    severity: pager
    channel: pagerduty:nidp-oncall
    
  - name: bhavcopy_freshness_slow_burn
    slo: bhavcopy.freshness
    burn_rate: 1.0     # 10% budget in 24h
    window: 24h
    severity: ticket
    channel: jira:NIDP
```

---

## 10. Custom Expectations Required

The following custom expectations need to be implemented in `nidp_dq_gates/expectations/`. Each one is a Python class extending GE base classes.

| Expectation | Base Class | Used By |
|-------------|------------|---------|
| `expect_kafka_headers_to_be_present` | `BatchExpectation` | Gate 1 universal |
| `expect_date_to_be_trading_day` | `ColumnMapExpectation` | Gate 1 universal |
| `expect_date_to_be_t_plus_n_trading_day` | `ColumnMapExpectation` | Gate 1 delivery |
| `expect_nav_change_within_category_band` | `ColumnPairMapExpectation` | Gate 1 amfi_nav |
| `expect_columns_sum_to_value` | `MulticolumnMapExpectation` | Gate 1 shareholding |
| `expect_row_count_to_be_within_pct_of_previous` | `BatchExpectation` | Gate 1 amfi_nav |
| `expect_eps_to_reconcile` | `MulticolumnMapExpectation` | Gate 1 financials |
| `expect_timestamps_monotonic_per_partition` | `BatchExpectation` | Gate 2 universal |
| `expect_column_cardinality_to_match_window` | `BatchExpectation` | Gate 1 bhavcopy |
| `custom_parquet_row_count_match` | `BatchExpectation` | Gate 5 |
| `custom_parquet_schema_match` | `BatchExpectation` | Gate 5 |
| `custom_parquet_sample_roundtrip` | `BatchExpectation` | Gate 5 |
| `custom_parquet_validity` | `BatchExpectation` | Gate 5 |
| `custom_warm_hot_reconciliation` | `BatchExpectation` | Gate 5 |
| `custom_dual_source_row_count` | `BatchExpectation` | Gate 4 |
| `custom_dual_source_checksum` | `BatchExpectation` | Gate 4 |
| `expect_table_to_have_freshness_within` | `BatchExpectation` | Gate 3 |

### 10.1 Custom expectation template

```python
# nidp_dq_gates/expectations/expect_columns_sum_to_value.py
from great_expectations.expectations.expectation import MulticolumnMapExpectation
from great_expectations.expectations.metrics import MulticolumnMapMetricProvider

class ColumnsSumToValue(MulticolumnMapMetricProvider):
    condition_metric_name = "multicolumn_values.sum_equals_value"
    condition_domain_keys = ("batch_id", "table", "column_list")
    condition_value_keys = ("target_value", "tolerance")
    
    @multicolumn_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column_list, target_value, tolerance, **kwargs):
        row_sum = column_list.sum(axis=1)
        return (row_sum - target_value).abs() <= tolerance


class ExpectColumnsSumToValue(MulticolumnMapExpectation):
    """
    Asserts the sum of values in specified columns equals a target value (± tolerance).
    
    Example: 
      expect_columns_sum_to_value(
        column_list=["promoter_pct", "fii_pct", "dii_pct", "public_pct", "others_pct"],
        target_value=100,
        tolerance=0.5
      )
    """
    map_metric = "multicolumn_values.sum_equals_value"
    success_keys = ("column_list", "target_value", "tolerance", "mostly")
    default_kwarg_values = {"tolerance": 0.0, "mostly": 1.0}
```

---

## 11. Configuration Hot-Reload

A key design goal: **change a threshold without redeploying code**.

Implementation:

```yaml
# config/runtime.yaml
hot_reload:
  enabled: true
  watch_paths:
    - config/feeds/
    - config/expectations/
    - config/gates/
  reload_interval_seconds: 60
  validate_on_reload: true
  rollback_on_invalid: true
```

The `nidp_dq_gates` library watches the config directory, validates new YAML on change, and atomically swaps the rule set. Invalid YAML → keep previous rules + alert.

---

## 12. Rule Coverage Matrix

Quick reference: which gates have rules for which feeds.

| Feed | G1 | G2 | G3 | G4 | G5 | G6 | G7 |
|------|----|----|----|----|----|----|----|
| bhavcopy | ✅ 7 rules | ✅ refs | ✅ presence | ✅ parity | ✅ export | ✅ score endpoint | ✅ all SLOs |
| delivery | ✅ 4 rules | ✅ refs | ✅ presence | — | — | ✅ score endpoint | ✅ all SLOs |
| fno_bhavcopy | ✅ 3 rules | ✅ refs | ✅ presence | — | — | — | ✅ freshness |
| index_close | ✅ 3 rules | ✅ refs | ✅ presence | — | — | ✅ benchmark | ✅ all SLOs |
| index_constituents | ✅ 2 rules | ✅ refs | — | — | — | — | ✅ freshness |
| nse_equity_master | ✅ 3 rules | ✅ refs | — | — | — | — | ✅ freshness |
| fii_dii | ✅ 4 rules | — | ✅ presence | — | — | ✅ macro | ✅ all SLOs |
| bulk_deals | ✅ 3 rules | ✅ refs | — | — | — | — | ✅ freshness |
| block_deals | ✅ 3 rules | ✅ refs | — | — | — | — | ✅ freshness |
| corporate_actions | ✅ 3 rules | ✅ refs | ✅ presence | — | — | — | ✅ freshness |
| nse_financials | ✅ 5 rules | ✅ refs | ✅ freshness | — | ✅ export | ✅ score endpoint | ✅ all SLOs |
| nse_shareholding | ✅ 4 rules | ✅ refs | ✅ integrity | — | — | ✅ score endpoint | ✅ all SLOs |
| event_calendar | ✅ 2 rules | — | — | — | — | — | ✅ freshness |
| corporate_announcements_* | ✅ 3 rules | — | — | — | — | — | ✅ freshness |
| amfi_nav | ✅ 5 rules | ✅ refs | ✅ presence | ✅ parity | — | ✅ MF endpoint | ✅ all SLOs |
| amfi_nav_history | ✅ 2 rules | ✅ refs | — | — | — | — | ✅ freshness |
| amfi_circulars | ✅ 2 rules | — | — | — | — | — | ✅ freshness |
| mf_holdings | ✅ 3 rules | ✅ refs | — | — | — | ✅ MF endpoint | ✅ all SLOs |
| mf_disclosure_snapshot | ✅ 3 rules | — | — | — | — | ✅ MF endpoint | ✅ all SLOs |
| rbi_yields | ✅ 2 rules | — | — | — | — | — | ✅ freshness |
| fred_macro | ✅ 2 rules | — | — | — | — | — | ✅ freshness |
| portfolio_holdings | — | ✅ refs | — | ✅ parity | — | ✅ portfolio | ✅ all SLOs |
| portfolio_transactions | — | ✅ refs | — | — | — | ✅ portfolio | ✅ freshness |
| portfolio_goals | — | — | — | — | — | ✅ portfolio | ✅ freshness |
| v3_stock_scores_daily | — | — | ✅ output | ✅ parity | ✅ export | ✅ score endpoint | ✅ all SLOs |
| v3_mf_scores_daily | — | — | ✅ output | — | — | ✅ MF endpoint | ✅ all SLOs |

---

## 13. Implementation Checklist

- [ ] Set up `nidp_dq_gates` Python package with config loader + hot reload.
- [ ] Implement the 17 custom expectations listed in Section 10.
- [ ] Create `config/feeds/*.yaml` for all 26 ingested feeds (one per feed).
- [ ] Create `config/expectations/*.yaml` referenced above.
- [ ] Create `config/gates/gate*.yaml` for each of the 7 gates.
- [ ] Wire Gate 1 into ingester base class (touches 24 services).
- [ ] Wire Gate 2 into Kafka consumer base.
- [ ] Extend `snapshot_builder` with Gate 3 rule runner.
- [ ] Create Gate 4 cron jobs on `nivesh-app-vm`.
- [ ] Extend `parquet_exporter` with Gate 5 verify-then-rename.
- [ ] Add Gate 6 middleware to DaaS API.
- [ ] Define Prometheus recording rules for Gate 7 SLOs.
- [ ] Build Grafana dashboards: "Daily Chain Status", "Feed Health Matrix", "DQ Verdict Drill-Down".
- [ ] Document config schema in `nidp_dq_gates/docs/CONFIG.md`.

---

*End of document.*