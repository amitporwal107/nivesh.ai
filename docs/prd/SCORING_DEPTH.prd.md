# PRD — Scoring Depth (Equity + Mutual Fund)

**Status:** IN PROGRESS · **Owner:** Data Platform · **Created:** 2026-06-23
**Source analysis:** live queries against prod NIDP (`localhost:5433`) on 2026-06-23.

---

## 1. Problem

Scoring **breadth** is solved — stocks cover ~100% of the tradable NSE set (2,275
scored), MF covers 99.7% (14,357 / 14,403). The problem is **depth**: each instrument
is scored on only a fraction of its primitives, so the engine renormalises weights over
whatever is present (no minimum-coverage gate — `v3_scores_engine/service.py:40-48`) and
silently degrades score *reliability*.

Measured depth (latest scored date):

| Pillar | Avg coverage | Worst sub-areas |
|---|---|---|
| Stock quality / health | **55.7%** | fundamentals (nse_financials), shareholding QoQ, accumulation |
| MF quality | 70.0% | debt: yield_vs_category, credit_quality |
| MF health | **22.6%** | aum_stability (100% missing), expense_trend (96.5%), concentration/turnover (~58%) |

Per-primitive missing-% (universe-wide), the gaps that drive the averages:

- **Stock**: accumulation_score 100%, revenue_3y_cagr 96.6%, promoter/FII/DII QoQ ~92%,
  roce/roe/pe/de/margins 78–81% (only 611 of 2,275 scored stocks have any fundamentals).
- **MF**: aum_stability 100%, expense_trend 96.5%, downside_protection 67.6%,
  concentration 57.9%, turnover 57.6%; debt credit_quality / yield_vs_category missing
  for all 4,652 debt schemes.

### Root-cause headline
Most "failing" feeds share **one** infra cause: `XMinioStorageFull` (object store hit its
min-free threshold on 2026-06-19) took out `nse_shareholding`, `amfi_nav`, `bulk_deals`,
`corporate_actions`, `fii_dii`, `fno_bhavcopy`, `rbi_yields` simultaneously — and froze
stock scores at the 06-19 snapshot. Root disk is 95% full (2.8 GB free). **SD-01 is the
single most schedule-critical task; nothing else verifies until it clears.**

---

## 2. Acceptance criteria

Each task is DONE only when a **before/after query against the real coverage views** is
shown (not "merged"): `avg quality/health coverage_pct` and the relevant per-primitive
missing-%. Targets are directional, bounded by real data availability (see §5 ceilings).

---

## 3. Task register (priority decided)

Priority = (depth impact) × (1/effort), blockers first. Effort: S ≤1d, M 2–3d, L 4–6d.

### P0 — Blockers (unfreeze ingestion)

**SD-01 · Remediate MinIO storage-full** — *P0 · Infra · S*
Root disk 95% full trips MinIO's min-free guard → 7 feeds failing since 06-19.
Reclaim space (unused docker images ≈1.85 GB; expire old raw archives) or grow the volume;
re-run the 7 ingesters. *Deletion on prod — requires explicit go-ahead.*
**Depends on:** none. **Blocks:** SD-03…SD-13.
**DoD:** `v_feed_status` OK + `consecutive_failures=0` for the 7 feeds; stock `as_of_date` advances to current.

**SD-02 · Repair AMC URL drift** — *P0 · Full-stack · M*
`amc_urls_drift_check` failed 17× — hdfc, icici_pru, absl, amfi:ter, amfi:risk have zero
healthy source candidates. Re-point drifted URLs / refresh the candidate list.
**Depends on:** none. **Blocks:** SD-06, SD-09, SD-13.
**DoD:** drift-check OK; `AMFI MF Holdings`/`Disclosure` leave PARTIAL.

### P1 — Quick wins

**SD-03 · Equity fundamentals — TTM-doubling fix landed; cash is a source ceiling** — *P1 · Full-stack · S*
**Correction after grounding:** the XBRL instant/duration separation is **already in the
working tree** (`nse_financials/parser.py:296-317`, 46-line uncommitted change — same intent
as migration 100). The cash tag *is* mapped (`parser.py:86`). Cash is still 7/611 **not**
because of a parser bug but because **NSE quarterly XBRL filings do not carry
`CashAndCashEquivalents`** — a data-availability ceiling. Action: (a) commit the staged
parser fix; (b) source cash/ST-debt/capex from the Screener balance/cashflow backfill path
(`backfill_screener_balance_cashflow.py`), not the quarterly XBRL.
**Depends on:** SD-01 (re-ingest to repopulate). **Blocks:** SD-08.
**DoD:** TTM no longer doubles (ROE/PE sane); cash/ST-debt fill via Screener path, not XBRL.

**SD-04 · Persist `ytm_pct` / `maturity_date` in MF holdings writer** — *P1 · Full-stack · S · ✅ DONE (code) 2026-06-23*
Parser emitted both keys; `mf_holdings/writer.py` INSERT dropped them → 0/242,614 populated,
starving debt-fund health (credit_concentration, liquidity, yield_vs_category). Added both to
INSERT/VALUES/ON CONFLICT. **Verified**: 15-param INSERT validated against the real table in a
rolled-back txn; values persist. Committed to `dev` (a5c1d43). **Remaining:** holdings
re-ingest to backfill historical rows (gated on SD-01).
**Depends on:** SD-01 (re-ingest). **Blocks:** SD-10, SD-11.

### P2 — Structural feeds (biggest levers)

**SD-05 · Expand equity fundamentals universe** — *P2 · Full-stack · L*
Only 611/2,275 scored stocks have fundamentals; backfill is Nifty-500-only
(`backfill_screener.py:40` → `v_nifty500_members`). Add Nifty Midcap 100 (then Smallcap 100)
backfill views; ingest an NSE symbol master for discovery.
**Depends on:** SD-01. **Blocks:** SD-08. **DoD:** fundamentals 611 → ~1,200–1,500 symbols.

**SD-06 · Repair broken AMC holdings scrapers** — *P2 · Full-stack · L*
Holdings on only 1,515/14,403 schemes (10.5%), 2 mo stale. Fix icici_pru, kotak, axis, mirae
(Playwright/captcha) + absl (Azure CDN egress) in `mf_holdings/amc_dispatch.py`.
**Depends on:** SD-01, SD-02. **Blocks:** SD-10.
**DoD:** holdings coverage materially > 10.5%; concentration/turnover missing-% < 58%.

### P3 — Derived / compute

**SD-07 · Shareholding QoQ backfill + YoY fallback** — *P3 · Full-stack · M*
QoQ change missing 92%; `v_shareholding_latest` (`migrations/025:65-111`) NULLs deltas when
prior quarter absent. Backfill prior quarters; add YoY fallback.
**Depends on:** SD-01. **DoD:** governance primitives 8% → ~70–80%.

**SD-08 · 3Y CAGR quarterly fallback** — *P3 · Full-stack · M*
revenue/eps 3Y CAGR missing 80–96%; `populate_stock_features_v3` (`migrations/089`) is
annual-only. Add quarterly-derived fallback.
**Depends on:** SD-03, SD-05. **DoD:** growth primitives ~4% → 50–70%.

**SD-09 · AUM monthly series + aum_stability OLS** — *P3 · Full-stack · M*
aum_stability 100% missing (20% of MF health weight); only point-in-time AUM exists. New
`mf_scheme_aum_monthly` aggregate → OLS slope into `mf_derived_analytics`.
**Depends on:** SD-02. **DoD:** aum_stability 0 → 50%+ (grows with history).

**SD-10 · Debt credit_concentration + liquidity from holdings** — *P3 · Full-stack · M*
0% today (30%+20% of debt health). Issuer-top-5 and liquid-asset SQL in `mf_derived_analytics`.
**Depends on:** SD-04, SD-06. **DoD:** debt health pillar 16% → ~50%+.

**SD-11 · Category-median YTM benchmark** — *P3 · Full-stack · S–M*
yield_vs_category missing for all 4,652 debt funds. Build `mf_category_ytm_rolling`.
**Depends on:** SD-04, SD-10. **DoD:** debt yield_vs_category 0 → near-full.

**SD-12 · Wire `accumulation_score` detector** — *P3 · Full-stack · M*
100% missing — hard-coded `None` at `technical_indicator_engine/calculator.py:266`; real logic
unwired in `positional_engine/accumulation_detector.py`. **Decision: wire it** (adds a real
volume/delivery signal used by all sector profiles). Invoke detector after `compute_features()`
in `technical_indicator_engine/service.py:~252`; add to upsert tuple.
**Depends on:** SD-01 (delivery-volume data). **DoD:** accumulation_score populated ~100%.

### P4 — Ceiling-limited

**SD-13 · expense_trend 3y TER delta** — *P4 · Full-stack · S + time*
Missing 96.5%; no 3-year TER history exists (snapshots started recently). Wire 3y TER delta;
either source a historical TER series or accept gradual fill.
**Depends on:** SD-02. **DoD:** logic live; coverage rises only as history lengthens.

---

## 4. Dependency graph & waves

```
SD-01 (MinIO) ──┬─> SD-03 ──> SD-08
                ├─> SD-05 ──> SD-08
                ├─> SD-07
                ├─> SD-12
                └─> SD-04 ──> SD-10 ──> SD-11
SD-02 (URLdrift)┬─> SD-06 ──> SD-10
                ├─> SD-09
                └─> SD-13
```

| Wave | Tasks | Rationale |
|---|---|---|
| 1 | SD-01, SD-02 | Unblock ingestion (SD-01 first/broadest). |
| 2 | SD-03, SD-04 | Quick-win code fixes (SD-04 code done). |
| 3 | SD-05, SD-06 | Two biggest structural levers; parallel. |
| 4 | SD-07, SD-09, SD-12 | Compute tasks needing only Wave-1 feeds. |
| 5 | SD-08, SD-10, SD-11 | Depend on Wave-3 outputs. |
| 6 | SD-13 | Ceiling-limited; lowest urgency. |

**Critical path:** `SD-01 → SD-04 → SD-10 → SD-11` (MF debt) and `SD-01 → SD-05 → SD-08`
(equity growth). SD-01 gates both.

---

## 5. Honest ceilings (depth we cannot manufacture now)

- **Stock cash / ST-debt / capex** — absent from NSE quarterly XBRL; only the Screener
  balance/cashflow path can supply them. Not a parser bug.
- **expense_trend (SD-13)** — needs a 3-year TER lookback we don't have; fills only as
  snapshot history accrues, unless a historical TER series is sourced.
- **aum_stability (SD-09)** — improves over months as monthly AUM accumulates; early fits
  are short-window.
- **Symbol fundamentals (SD-05)** — ultimately bounded by Screener/NSE filing availability;
  true small-caps stay sparse.

---

## 6. Deployment & verification rules

- Code reaches prod via `git push` (branch `dev`) → fetch/reset on the VM. Never direct,
  never to `main`.
- No task is "done" without real before/after coverage-view output in the same report.
- SD-01 (prod disk deletion) and any re-ingest/migration require explicit go-ahead before
  execution.
