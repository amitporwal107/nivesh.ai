# Test Cases (authored UP FRONT) — MF Holdings Canonical Dedupe + Coverage

- **Branch:** fix/mf-holdings-dedupe (from feat/provider-foundations)
- **Date authored:** 2026-10-23 (before implementation)
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Scope:** the data-integrity defect in `nidp.mf_holdings_monthly` — one holding stored once
  per plan/option variant and SUMMED downstream (4.0x), plus the measured coverage ratio that
  the inflation was hiding. Canonical dedupe layer, deltas on a constant panel, real measured
  `coverage_pct`, and a reconciliation test.
- **Out of scope (explicitly):** any score, ranking or predictive model; the Smart Money
  scanner/router SQL (`daas_api/routers/smart_money.py`, `backend/routes/markets_smart_money.py`);
  anything under `frontend-v5/`.

## Acceptance-criteria trace

| # | User's acceptance criterion | Covered by |
|---|---|---|
| 1 | Resolve the 4.03x duplication at the source/canonicalisation layer | TC-1..TC-6, TC-13 |
| 2 | EXPLAIN (quantify) the 0.54x coverage ratio — do not inflate it | TC-10, TC-11, TC-12 |
| 3 | Validate AMC-level holdings against source disclosures where possible | TC-8, TC-9 |
| 4 | Reconcile scheme-level holdings without double-counting share classes or duplicates | TC-4, TC-5, TC-6, TC-7, TC-13 |
| 5 | Confirm aggregates are consistent with published AMC totals where available | TC-9, TC-13, TC-14 |
| 6 | Preserve source provenance, reporting period, ingestion timestamp | TC-15 |
| 7 | Historical backfills must not alter published snapshots without an auditable correction | TC-16, TC-17 |

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | canonical key | `Axis Children's Fund - Direct Plan - Growth Option` and its 7 sibling variants | unit | All 8 rows map to ONE base scheme `axis children's fund`; one canonical row | PENDING |
| TC-2 | canonical key | Name with a trailing plan and no option (`Axis Nifty Capital Markets Index Fund - Direct Plan`) | unit/edge | Plan suffix stripped; Direct and Regular collapse to one key | PENDING |
| TC-3 | canonical key | Option-only name with no plan word (`Axis Liquid Fund - Growth Option`, `- Daily IDCW Option`) | unit/edge | Collapse to `axis liquid fund` | PENDING |
| TC-4 | canonical key | Case-only difference (`ADITYA BIRLA SUN LIFE ARBITRAGE FUND - ...` vs `Aditya Birla ...`) | unit/edge | Same key (rule is case-insensitive) | PENDING |
| TC-5 | canonical key | A fund name that merely CONTAINS "Regular"/"Growth" mid-name, not as a plan/option suffix | unit/failure | Name is NOT truncated (no over-merge) | PENDING |
| TC-6 | canonical key | Two sources for one AMC-month (`QUANT_DISCLOSURE_ADVISORKHOJ` + `QUANT_MF_PORTFOLIO_XLSX`), the second keyed by scheme NAME not AMFI code | unit+data | Both resolve to amc `quant` and the same base scheme → ONE canonical row, not two | PENDING |
| TC-7 | leg class | Arbitrage short futures leg (`ICICI Bank Ltd.-OCT2026`, negative quantity) and written options (`... (CALL Option)`) | unit | Classified `derivative`, excluded from the share count, COUNTED and reported — never netted into shares, never silently dropped | PENDING |
| TC-8 | data trust | Implied price (`market_value_inr / quantity`) vs the EQ/BE close on the month's last session | data | ≥ 99% of priced equity-leg rows within 0.3%; nothing beyond 5% | PENDING |
| TC-9 | AMC validation | Per-source median implied/close, 2026-09 | data | Every source's median = 1.0000 (the AMC's own valuation reproduces the traded close) | PENDING |
| TC-10 | coverage | Measured coverage per stock = canonical shares ÷ (`total_shares` × `mf_pct`) | data | Nifty 500, 2026-09: median ratio in [0.40, 0.75] — the real figure, NOT 100.00 | PENDING |
| TC-11 | coverage | Stocks where `shareholding_pattern` does not disclose both inputs | edge/failure | coverage is NULL with a stated basis — never 0, never 100 | PENDING |
| TC-12 | coverage | Quantified explanation of the shortfall | data | AMC-count gap stated from the warehouse (11 indexed of 56 registered) + named absentees; scheme-level gap inside indexed AMCs stated per AMC | PENDING |
| TC-13 | reconciliation (CI) | Deduped-vs-expected ratio per stock on a committed fixture of REAL staging rows | unit (CI) | ≥ 90% of names have ratio ≤ 1.05 (we hold 11 of 56 AMCs, so the honest bound is "never exceeds the disclosed MF holding"); dedupe factor ≈ 4 | PENDING |
| TC-14 | reconciliation (CI) | The SAME assertion run on the naive summed figure | unit/regression | FAILS (ratio > 1.05 for most names) — proves the fix changes the outcome | PENDING |
| TC-15 | provenance | Canonical row for a multi-variant fund | data | Carries sources[], source_urls[], reporting month, published_at/source_observed_at, max(ingested_at), known_from + basis; variant scheme codes retained | PENDING |
| TC-16 | restatement audit | A backfill re-writes an already-published (scheme, month, isin) quantity | unit+data | The change is recorded in `nidp.mf_holdings_restatements` (old → new, when, which run) — never a silent overwrite | PENDING |
| TC-17 | restatement audit | Re-ingest that writes the SAME quantity | edge | No restatement row (only real changes are logged) | PENDING |
| TC-18 | deltas | Deltas computed on canonical rows | data | One delta row per (amc, base scheme, isin, month) — not one per plan variant | PENDING |
| TC-19 | deltas | Constant panel: a fund newly indexed this month | edge/failure | Excluded from the constant-panel net delta and marked `panel_entry`; coverage expansion cannot read as buying | PENDING |
| TC-20 | deltas | Naive figure kept for audit | data | `naive_*_shares` columns carry the pre-dedupe sum so the inflation stays auditable | PENDING |
| TC-21 | migration | Apply migrations 182/183 twice | idempotency | Second run is a no-op (`CREATE ... IF NOT EXISTS` / `CREATE OR REPLACE`) | PENDING |
| TC-22 | no regression | `nidp.v_smart_money_coverage_by_date` after `coverage_pct` changes meaning | data | Reads the relabelled `subsignal_coverage_pct`, so its published number keeps its meaning | PENDING |

## Tolerance statement (TC-13, the deliverable)

The reconciliation asserts a ONE-SIDED bound, which is the only honest one for this dataset:

* We index 11 AMCs of the 56 in `nidp.mf_amc_master`, so the canonical share count for a stock
  **must not exceed** the all-AMC figure the company disclosed. Bound: `ratio <= 1.05`
  (5% headroom for the reporting-date mismatch between a month-end portfolio and a quarter-end
  shareholding filing).
* Required pass fraction: **≥ 90%** of names with both sides available.
* It must NOT assert `ratio ≈ 1`: that would only be true with full AMC coverage, and forcing it
  would mean inflating the numerator — the failure this task exists to remove.

## Verification constraints known up front

* The staging warehouse is **READ-ONLY** for this agent. Migrations 182/183 are therefore
  authored and their view bodies verified by running the identical SQL as read-only CTE chains
  against real staging data; the DDL itself is NOT applied here (declared UNVERIFIED in the
  report, with the apply command stated).
* `nidp.mf_holdings_deltas` cannot be rewritten from here for the same reason: the new service
  SQL is verified by running its SELECT half read-only and comparing counts.
