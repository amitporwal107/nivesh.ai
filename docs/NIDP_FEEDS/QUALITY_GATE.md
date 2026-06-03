# Product Requirements Document
# NIDP Data Quality Gates

| Field | Value |
|---|---|
| **Document Owner** | NIDP Platform Engineering |
| **Status** | Draft v1.0 |
| **Last Updated** | 2026-05-27 |
| **Target Release** | Q3 2026 |
| **Stakeholders** | NIDP Platform, Nivesh Intelligence, Copilot, SRE |

---

## 1. Executive Summary

NIDP currently ingests 41 data feeds across 4 layers (External Ingestion, AI Classification, Derivation Engines, Portfolio + Intelligence) and produces V3 stock and mutual fund scores that drive the Nivesh Copilot's investment recommendations. While the platform has tactical data quality checks (Great Expectations rules, `dq.validation_findings`, the `dq_ai` CLI, and `amc_urls_drift_check` for URL health), these checks are **scattered, finite, and non-blocking** — bad data routinely propagates from source to user-facing recommendations without intervention.

This PRD proposes a **layered Data Quality Gates system** that places enforcement points at each storage-tier transition in the NIDP architecture. Each gate has the same structure (`verify → record verdict → block or pass → emit metric`) but enforces different invariants appropriate to its position in the pipeline.

**The fundamental shift:** From "detect bad data after it lands" to "prevent bad data from crossing tier boundaries."

### Why now

- **Two feeds are currently broken in production** (`mf_holdings`, `mf_disclosure_snapshot`) and have been silently degrading MF scoring with no automated remediation.
- A new warm-tier (MinIO Parquet) was added to the architecture in 2026; the DuckDB analytics endpoints now read from it with **no integrity verification** on the export.
- The Copilot surfaces V3 scores directly to end users; a single corrupted upstream feed can produce confidently-wrong recommendations.
- 41 feeds with cascading dependencies means manual DQ triage no longer scales.

### Expected outcomes

- **>99.5% reduction** in undetected data corruption reaching the Copilot.
- **Mean Time To Detect (MTTD)** of DQ incidents reduced from hours/days → minutes.
- **Zero V3 score generation** on incomplete or invalid input data.
- **User-visible DQ envelope** in every DaaS API response — Copilot makes degraded-data decisions explicitly, never implicitly.

---

## 2. Problem Statement

### 2.1 Current state pain points

| # | Pain Point | Business Impact |
|---|------------|-----------------|
| 1 | DQ rules are column-level and finite; cross-feed and temporal invariants are unchecked | Silent corruption in derived scores (e.g., MF scores running on 30-day-stale holdings) |
| 2 | DQ failures don't block downstream computation | `v3_scores_engine` happily produces scores from partial or stale inputs |
| 3 | No DQ context flows to the API/Copilot | Copilot confidently recommends based on broken data |
| 4 | New warm tier (Parquet on MinIO) has no export verification | DuckDB analytics endpoints can serve partial/corrupt data |
| 5 | Standby replica integrity is not actively monitored | Read traffic on `:5434` may diverge from primary silently |
| 6 | DQ verdicts and data are in separate tables with no FK linkage | Cannot tell whether a queried row was validated or unvalidated |
| 7 | Threshold-based alerting across 41 feeds = alert fatigue | Engineers ignore or suppress alerts; real incidents are missed |
| 8 | Broken feeds remain broken (e.g., AMC URL drift) without auto-quarantine | Stale data continues feeding scores for weeks |

### 2.2 What this PRD does *not* solve

- **Source data accuracy beyond NIDP's control** — if NSE publishes wrong bhavcopy, that's a NSE problem. NIDP gates ensure we *detect and quarantine*, not correct upstream errors.
- **ML/AI model quality** for `announcement_classifier` and `event_analyzer` — covered separately in the LLM Output Quality PRD.
- **Replacing Great Expectations** — gates use existing GE checks as one input among many.
- **Rewriting feed ingesters** — gates are wrappers around existing services, not replacements.

---

## 3. Goals & Non-Goals

### 3.1 Goals

1. **Block bad data at every storage-tier transition** — no corrupt data crosses a tier boundary unnoticed.
2. **Co-locate gates with the data movement they protect** — no central DQ service bottleneck.
3. **Persist DQ verdicts alongside data** — every row in TimescaleDB traceable to a verdict.
4. **Surface DQ status to API consumers** — Copilot receives explicit data-quality envelope per response.
5. **Replace threshold alerts with SLO/error-budget alerting** — eliminate alert fatigue across 41 feeds.
6. **Auto-quarantine broken feeds** — degraded data routed to DLQ, scoring uses last-known-good with explicit staleness.

### 3.2 Non-Goals

- Not building a "DQ platform" with its own UI — uses existing Grafana.
- Not centralizing DQ logic into a service — shared library, not shared service.
- Not introducing new tools — leverages Redpanda, Schema Registry, TimescaleDB, MinIO, Prometheus, Loki, Grafana already in the stack.

---

## 4. Architecture Overview

### 4.1 The 7 Gates

Gates are positioned at the storage-tier transitions defined in the current NIDP architecture:

```
External Source
    │
    ▼
  [Gate 1] Ingestion Gate          (pre-Kafka publish)
    │
    ▼
Redpanda Topics + Schema Registry
    │
    ▼
  [Gate 2] Stream Processing Gate  (Kafka → TimescaleDB)
    │
    ▼
TimescaleDB Primary (:5433)
    │
    ├──► [Gate 3] Snapshot Completion Gate  (pre-derivation engines)
    │       │
    │       ▼
    │     V3 Scores, Features, Fundamentals
    │
    ├──► [Gate 4] Replication Integrity Gate  (Primary → Standby :5434)
    │
    └──► [Gate 5] Warm-Tier Export Gate       (TimescaleDB → MinIO Parquet)
           │
           ▼
         DuckDB Analytics Endpoints
    │
    ▼
  [Gate 6] API Output Gate          (DaaS API → Copilot)
    │
    ▼
Nivesh Copilot → End User

  [Gate 7] Observability Gate       (continuous, cross-cutting)
```

### 4.2 Gate Anatomy

Every gate has the **same internal structure** (implemented as a shared Python library `nidp_dq_gates`):

```
┌─────────────────────────────────────┐
│  1. VERIFY                          │
│     Run gate-specific invariants    │
├─────────────────────────────────────┤
│  2. RECORD VERDICT                  │
│     Persist to dq.gate_verdicts     │
│     with ingest_run_id linkage      │
├─────────────────────────────────────┤
│  3. BLOCK or PASS                   │
│     P0 fail → block, raise          │
│     P1 fail → pass with AMBER       │
│     P2 fail → pass with note        │
├─────────────────────────────────────┤
│  4. EMIT METRIC                     │
│     Prometheus counter + Loki log   │
└─────────────────────────────────────┘
```

### 4.3 Severity Contract

| Severity | Meaning | Gate Action | Example |
|----------|---------|-------------|---------|
| **P0** | Blocks downstream | Stop propagation, raise alert | `bhavcopy` row count < 1500 |
| **P1** | Degrades a domain | Pass but mark AMBER, alert | `mf_holdings` stale > 7 days |
| **P2** | Cosmetic / informational | Pass, log only | Single column null rate slightly elevated |

---

## 5. Gate Specifications

### Gate 1: Ingestion Gate

**Location:** Inside each ingester service, immediately before `producer.send()` to Redpanda.

**Purpose:** Prevent malformed, schema-violating, or structurally invalid messages from entering the topic stream.

**Invariants enforced:**
- Avro schema validation against Schema Registry (existing 23 schemas).
- Trading-day awareness (rejects bhavcopy/delivery on non-trading days unless backfill flag set).
- Row count within trailing 30-day band (configurable per feed).
- Required fields present (e.g., `symbol`, `trade_date` for bhavcopy).
- Source checksum and `ingest_run_id` in message headers.

**Failure behavior:**
- P0 fail → publish to `dq.quarantine.<feed>` topic, do NOT publish to main topic.
- Increment `nidp_dq_gate1_failures_total{feed="bhavcopy", severity="p0"}`.
- Loki structured log with full failure context.

**Success criteria:** 99.9% of valid messages pass gate 1 in < 50ms.

---

### Gate 2: Stream Processing Gate

**Location:** Kafka consumer that writes from Redpanda to TimescaleDB hypertables.

**Purpose:** Enforce referential integrity and cross-message invariants before persistence.

**Invariants enforced:**
- Foreign-key resolution (every `bhavcopy.symbol` exists in `ref.sector_master`; every `mf_nav_daily.scheme_code` exists in `mf_scheme_master`).
- Idempotency (no duplicate writes for same `(primary_key, trade_date)`).
- Cross-message ordering (events processed in source-timestamp order per partition).
- DLQ pattern: failed messages → `dq.dlq.<feed>` topic + `dq.dlq_findings` table.

**Failure behavior:**
- P0 fail → route to DLQ, do NOT write to TimescaleDB, do NOT commit Kafka offset.
- Consumer commits offset only after both write AND verdict persisted (transactional).
- Auto-retry policy: 3 attempts with exponential backoff, then permanent DLQ.

**Success criteria:** Zero ghost writes (rows in TimescaleDB without a corresponding `dq.gate_verdicts` entry).

---

### Gate 3: Snapshot Completion Gate ⭐ *Highest priority*

**Location:** Extends existing `snapshot_builder` service preflight.

**Purpose:** Block derivation engines (`feature_snapshotter`, `technical_indicator_engine`, `fundamental_engine`, `v3_scores_engine`) from running on incomplete input.

**Invariants enforced:**
- All P0 input feeds for date D have landed AND passed gates 1 + 2.
- Row counts within band per feed.
- No outstanding DLQ messages for date D.
- Cross-feed consistency:
  - `count(bhavcopy.symbol) ≈ count(delivery.symbol)` within ±2%.
  - `index_constituents` universe is a superset of scored stocks.
  - `shareholding_pattern` percentages sum to 100 ± 0.5%.
- TimescaleDB primary-standby replication lag = 0.
- Last `corporate_actions` check within 24 hours.

**Failure behavior:**
- P0 fail → **derivation chain does not start**. Status: "Waiting on `<feed>`".
- Emit `nidp_snapshot_blocked_total{reason="bhavcopy_missing"}`.
- Grafana dashboard shows a single "Daily Chain Status" panel: GREEN / BLOCKED.

**Success criteria:**
- **Zero V3 scores generated from incomplete input** (currently measured: unknown, expected meaningful baseline).
- 99% of trading days complete all gates by 19:30 IST.

---

### Gate 4: Replication Integrity Gate

**Location:** Cron job on `nivesh-app-vm`, monitoring streaming replication from `:5433` → `:5434`.

**Purpose:** Ensure read-only standby (`nidp-postgres-standby :5434`) remains consistent with primary.

**Invariants enforced:**
- WAL lag < 30 seconds (continuous, every 60s probe).
- Daily row-count parity on 5 critical hypertables:
  - `bhavcopy`, `mf_nav_daily`, `v3_stock_scores_daily`, `portfolio_holdings`, `corporate_announcements`.
- Daily checksum parity (xxhash of sample partitions).
- `pg_is_in_recovery() = true` on standby (verifies it hasn't been promoted accidentally).

**Failure behavior:**
- P0 fail (lag > 30s OR row drift > 0) → DaaS API routes reads back to primary, alert SRE.
- P1 fail (checksum drift) → ticket, investigate within 24h.

**Success criteria:** 99.99% replication-integrity uptime measured over 30-day windows.

---

### Gate 5: Warm-Tier Export Gate

**Location:** Inside `parquet_exporter` service (00:30 IST cron).

**Purpose:** Prevent partial or corrupt Parquet files from being read by DuckDB analytics endpoints.

**Invariants enforced:**
- Write-then-verify with atomic rename pattern:
  1. Export to `parquet/stock_features_daily/year=Y/month=M/_tmp/*.parquet`
  2. Verify row count matches source TimescaleDB query (±0 tolerance).
  3. Verify schema (column names, types, partition keys).
  4. Sample 100 random rows, round-trip through DuckDB, compare to source.
  5. Verify Parquet file is valid and readable.
  6. Atomic `mv _tmp/ → final/`.
- DuckDB only reads from finalized partitions (`_tmp/` excluded via glob pattern).

**Failure behavior:**
- P0 fail → `_tmp/` files deleted, partition remains at previous version, alert.
- Daily reconciliation report posted to `#nidp-dq` Slack channel.

**Success criteria:** Zero DuckDB query failures due to partial Parquet reads.

---

### Gate 6: API Output Gate ⭐ *User-facing*

**Location:** DaaS API middleware on every `/v1/*` endpoint.

**Purpose:** Surface data freshness and quality to API consumers (primarily the Copilot) so they can make informed decisions on degraded data.

**DQ Envelope (response header + body):**

```json
{
  "data": { ... endpoint payload ... },
  "data_quality": {
    "as_of_date": "2026-05-27",
    "data_freshness_seconds": 1847,
    "dq_status": "AMBER",
    "degraded_feeds": [
      {
        "feed": "mf_holdings",
        "last_successful_run": "2026-04-27T22:30:00+05:30",
        "staleness_days": 30,
        "impact": "MF concentration metrics are stale"
      }
    ],
    "snapshot_id": "snap_2026-05-27_abc123",
    "gate_verdict_uri": "/v1/dq/verdict/snap_2026-05-27_abc123"
  }
}
```

**Copilot consumption logic:**

| `dq_status` | Copilot Behavior |
|-------------|------------------|
| **GREEN** | Normal operation, recommendations served. |
| **AMBER** | Disclose staleness in response ("based on data as of X, MF holdings 30 days stale"). |
| **RED** | Refuse specific recommendations, fall back to general guidance + transparency about why. |

**Success criteria:**
- 100% of DaaS responses include the `data_quality` envelope.
- 100% of Copilot user-facing recommendations check `dq_status` before generating.

---

### Gate 7: Observability Gate

**Location:** Prometheus + Grafana, cross-cutting.

**Purpose:** Replace threshold-based alerts with SLO + error-budget alerts to eliminate fatigue across 41 feeds.

**SLOs defined per feed:**

| SLO Type | Target | Example |
|----------|--------|---------|
| **Freshness** | 99% of trading days within window | `bhavcopy` lands by 17:45 IST |
| **Completeness** | 99.5% of expected rows present | `mf_nav_daily` ≥ 4500 schemes |
| **Validity** | 99.9% of rows pass schema + sanity | `nse_financials` accounting identity |
| **Referential** | 99.9% of cross-feed joins resolve | Every `delivery.symbol` exists in `bhavcopy` |

**Alerting strategy:**
- **Fast burn** (2% budget in 1h) → PagerDuty.
- **Slow burn** (10% budget in 24h) → Jira ticket.
- **No threshold alerts** — error budgets only.

**Dashboards:**
- "Daily Chain Status" (single-pane status of all 7 gates for current trading day).
- "Feed Health Matrix" (41 feeds × 4 SLO dimensions, color-coded).
- "DQ Verdict Drill-Down" (per `ingest_run_id` lineage).

---

## 6. Data Model Changes

### 6.1 New tables in `dq` schema

| Table | Purpose |
|-------|---------|
| `dq.gate_verdicts` | Every gate invocation: gate_id, feed, ingest_run_id, verdict, severity, details, timestamp |
| `dq.dlq_findings` | Messages quarantined at gate 1 or 2, with replay capability |
| `dq.feed_sla` | Per-feed SLO definitions (freshness window, row count band, severity weights) |
| `dq.feed_signatures` | Daily statistical fingerprint per feed (row count, null rates, min/max, cardinality) for drift detection |
| `dq.snapshot_status` | Per-date status of the snapshot completion gate (gate 3) |

### 6.2 Modified tables

- `nidp.*` tables (all hypertables) gain a `dq_verdict_id` FK column → `dq.gate_verdicts.id`.
- Backfill plan: NULL for historical rows, NOT NULL constraint enforced for new rows post-cutover.

---

## 7. Success Metrics

### 7.1 Primary KPIs

| Metric | Baseline (today) | Target (Q4 2026) | Measurement |
|--------|------------------|------------------|-------------|
| **Undetected DQ incidents per quarter** | Unknown (likely 5-10) | < 1 | Manual incident review + auto-reports |
| **MTTD for DQ incidents** | Hours to days | < 5 minutes | Time from data corruption to gate alert |
| **V3 scores generated on incomplete input** | Unknown | 0 | Gate 3 block rate vs successful runs |
| **DaaS responses with DQ envelope** | 0% | 100% | API instrumentation |
| **Copilot DQ-aware responses** | 0% | 100% | Copilot logs |
| **Alert volume per week** | Unknown (likely high) | < 10 actionable | PagerDuty + Jira intake |

### 7.2 Secondary KPIs

- **Replication lag P99** < 30 seconds.
- **Parquet export integrity failures** = 0.
- **DLQ message replay success rate** > 95%.
- **Engineer time spent on DQ triage** reduced by 60% (survey).

---

## 8. Rollout Plan

### 8.1 Phased delivery — 6 months

| Phase | Duration | Gates Delivered | Why this order |
|-------|----------|-----------------|----------------|
| **Phase 1** | Weeks 1–4 | **Gate 3** (Snapshot Completion) | Highest leverage: blocks bad scores from ever being computed. Extends existing `snapshot_builder`, cheapest to build. |
| **Phase 2** | Weeks 5–8 | **Gate 5** (Warm-Tier Export) | New warm tier has zero protection today; risk is rising fast as DuckDB endpoints get traffic. |
| **Phase 3** | Weeks 9–14 | **Gate 6** (API Output) + Copilot integration | Protects users immediately. Requires Copilot team partnership. |
| **Phase 4** | Weeks 15–22 | **Gate 1** (Ingestion) + **Gate 2** (Stream) | Largest engineering investment; requires touching every ingester. |
| **Phase 5** | Weeks 23–26 | **Gate 4** (Replication) + **Gate 7** (SLO migration) | Polish, optimize alerting, decommission legacy threshold alerts. |

### 8.2 Risk-mitigated rollout per gate

Every gate follows the same rollout pattern:

1. **Shadow mode** (2 weeks): gate runs, records verdicts, but never blocks. Compare verdicts to existing behavior.
2. **Canary** (1 week): gate blocks for 1 low-risk feed (e.g., `fred_macro`).
3. **Progressive enable** (2 weeks): expand to all feeds in severity tiers (P2 first, P0 last).
4. **Full enforcement** (ongoing).

### 8.3 Quick wins (Week 1)

These should ship before the formal Phase 1 begins:
- Fix `mf_holdings` and `mf_disclosure_snapshot` (broken AMC URLs) — 0% MF coverage today.
- Wire `amc_urls_drift_check` FAILED state to block `mf_analytics_engine` (manual gate 3 prototype).
- Add `dq_status` field to existing DaaS responses as a static "GREEN" placeholder — establishes the contract, Copilot team can start integrating.

---

## 9. Dependencies

### 9.1 Cross-team dependencies

| Team | Dependency | Risk |
|------|------------|------|
| **Copilot** | Integration with Gate 6 DQ envelope | Medium — requires Copilot prompt/logic changes |
| **SRE** | Grafana dashboard ownership, PagerDuty routing | Low — extends existing setup |
| **Nivesh Intelligence** | Acceptance of Gate 3 blocking behavior (no scores on bad data) | Medium — must agree "no score" > "stale score" |
| **Data Engineering** | Touches every ingester for Gate 1 | High — coordination across 24 services |

### 9.2 Technical dependencies

- Schema Registry must remain operational (existing — Confluent on `:8081`).
- Redpanda enterprise license expires 2026-06-03 — either renew or downgrade before Phase 4.
- TimescaleDB retention policy (migration 075) — activate after gate 5 has 1 week clean export history.

---

## 10. Open Questions

1. **Backfill policy:** When a gate is enabled in enforcement mode, do we re-validate historical data? Proposed: no — gates apply forward-only. Historical data carries an implicit "unverified" flag.
2. **Cross-tenant isolation:** Today NIDP is single-tenant. If multi-tenant in future, do gates need per-tenant verdicts? Proposed: design for it now (verdicts include tenant_id), enforce later.
3. **AI classification DQ:** Where does `announcement_classifier` confidence fit? Proposed: separate PRD for LLM Output Quality, but Gate 6 envelope includes a `classification_confidence_floor` field.
4. **Cost:** Each gate adds compute + storage. Estimated +5% TimescaleDB storage (verdict tables) and +2% compute. Acceptable?

---

## 11. Appendices

### 11.1 Glossary

- **Gate:** A code-enforced quality checkpoint at a storage-tier transition.
- **Verdict:** The recorded outcome of a gate invocation (PASS / FAIL with severity).
- **DLQ:** Dead-letter queue — Kafka topic + table for messages that failed gate 1 or 2.
- **DQ envelope:** Metadata block in API responses describing data freshness and quality.
- **Snapshot ID:** Immutable identifier for a daily market data snapshot (gate 3 output).
- **Error budget:** SLO-based alerting concept; budget consumed by failures determines alert urgency.

### 11.2 Related documents

- NIDP Master Data Feed Catalogue (2026-05-27)
- NIDP Infrastructure Architecture (post-session)
- V3 Scoring Framework Specification
- (Future) LLM Output Quality PRD for `announcement_classifier` and `event_analyzer`

### 11.3 Approval

| Role | Name | Status |
|------|------|--------|
| Engineering Lead | TBD | Pending |
| Product | TBD | Pending |
| SRE | TBD | Pending |
| Copilot Lead | TBD | Pending |

---

*End of document.*
