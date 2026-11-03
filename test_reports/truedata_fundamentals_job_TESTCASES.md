# TrueData fundamentals NIDP job — test cases (written BEFORE implementation, 2 Nov 2026)

Branch `feat/truedata-fundamentals-job`. Turns the supervised 2 Nov loads (scripts in the session scratchpad,
report `test_reports/truedata_research_data_20261102.md`) into a reviewed NIDP job:

- `backend/nidp/shared/sources/truedata.py` — corporate methods: `result_list(day)`, `balance_sheet(id)`,
  `cash_flow(id, cumulative)`, `pnl(id, cumulative)` with JSON-status classification.
- `backend/nidp/services/truedata_fundamentals/` — pure transform, loader (one transaction, provenance, dry-run,
  rollback), CLI, raw cache, switch gate, rate limit.
- `backend/nidp/migrations/190_truedata_fundamentals_fills.sql` — durable provenance table.
- `deploy/cloudpe/nidp/nidp-staging-truedata-fundamentals.cron` — NOT installed.

Fixtures are SYNTHETIC, shaped like the real payloads (TrueData material is under NDA; nothing raw is committed).
Database tests run on a throwaway `postgres:16-alpine` container with `--network none`.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-01 | client | `result_list(day)` → GET corporate host `getResultList?date=&response=json` with Bearer; returns Records | unit | list of dicts; path/params exact |
| TC-02 | client | JSON failures with HTTP 200: "There is no row at position 0." / "Invalid Period…" / "Invalid Type" / "Records" empty | unit | EMPTY_RESPONSE / INVALID_REQUEST codes, never data |
| TC-03 | client | one-line text failures (quota exceeded, segment not subscribed, auth denied), HTML, non-JSON | unit | RATE_LIMITED / NOT_CONFIGURED / PROVIDER_ERROR / INVALID_PAYLOAD |
| TC-04 | client | `balance_sheet`, `cash_flow(cumulative)`, `pnl(cumulative)` params; 401 → one token refresh; per-host gate spaces calls | unit | right params; one retry; gate sleeps |
| TC-05 | client | no password / token in any error, repr or log line | unit | secrets absent |
| TC-06 | transform | one filing under 4 ids (same file time) and a 1-minute re-file → one; re-file > 45 days → two | unit | keep latest file time, then highest id |
| TC-07 | transform | symbol: `&amp;` unescaped; None / "NOTLISTED" → BSE scrip map; unknown → dropped | unit | resolved or dropped |
| TC-08 | transform | nature: consolidated preferred; standalone only for a company with no consolidated filing | unit | as stated |
| TC-09 | transform | period end: Yearly → FY end; Second quarter (Apr FY) → 30 Sep; Dec-FY H1 → 30 Jun; SME Half yearly ≤120 d → H1 end else FY end; DateOfEndOfReportingPeriod wins | unit | dates exact |
| TC-10 | transform | unit, TCS-like (ratio 1.000) → crore; lakh company (ratio 100) → lakh | unit | unit + how |
| TC-11 | transform | RADICO-like ratio 3.475 → revenue anchor refuses → share-capital anchor → crore; ratio within 1.5x boundary | unit | crore via share capital; 1.5x is the limit |
| TC-12 | transform | no anchor, rounding text "Lakhs" → lakh; no anchor, blank text → row REFUSED ("unit unknown") | unit | refuse, never guess |
| TC-13 | transform | CurrentLiabilities 0 → Liabilities − NoncurrentLiabilities | unit | derived CL |
| TC-14 | transform | bank-format balance sheet (OtherAssetsGroup.Advances > 0) → no balance-sheet offer | unit | skipped, counted |
| TC-15 | transform | identity: assets ≠ equity+liabilities (>1 %), CA > TA, receivables > CA, CFO+CFI+CFF ≠ net before FX → reject with reason | unit | rejected rows listed |
| TC-16 | transform | cash flow: Yearly → offer (capex negative); Second quarter / Half yearly → never offered | unit | H1 CF never loaded |
| TC-17 | transform | finance costs: quarterly P&L (cumulative=false) → offer at quarter end; bank P&L skipped; span not ~3 months rejected; negative rejected; revenue cross-check mismatch rejected | unit | as stated |
| TC-18 | loader (PG) | balance sheet fills ONLY NULL columns, on every row of (symbol, period_end, consolidated) any period_type; a non-NULL value is never overwritten | integration | fill-only |
| TC-19 | loader (PG) | FY balance sheet with NO row for the date → one `annual` row, source `truedata`; H1 with no row → nothing; `equity_share_capital_cr` never written | integration | insert rule |
| TC-20 | loader (PG) | cash flow: no row → insert (source truedata); existing row → only NULL columns filled | integration | fill-only |
| TC-21 | loader (PG) | finance costs: NULL `finance_costs_cr` on the matching quarterly row filled; annual rows / non-NULL / missing rows untouched | integration | fill-only |
| TC-22 | loader (PG) | provenance: one `nidp.truedata_fundamentals_fills` row per touched row with columns_filled, values_written, inserted, unit, unit_how, filing id | integration | complete record |
| TC-23 | loader (PG) | `--dry-run` writes nothing (full table snapshots identical) and reports the same counts a real run then produces | integration | zero writes, counts equal |
| TC-24 | loader (PG) | rollback: load then rollback → tables identical to before (full snapshot); a column another writer changed after our fill is NOT nulled; rollback twice = no-op | integration | exact undo |
| TC-25 | loader (PG) | re-running the same input fills nothing new (idempotent) | integration | 0 fills |
| TC-26 | loader (PG) | an error mid-load leaves nothing written (one transaction) | failure | all-or-nothing |
| TC-27 | migration | 190 applies on a fresh PG and re-applies cleanly (idempotent) | integration | no error |
| TC-28 | job | switch `current` → no TrueData call, no warehouse write except the SKIPPED job_log row; `shadow` → runs; rollback works at any switch setting | unit | gate honoured |
| TC-29 | job | raw cache: cached statements not refetched; the last 3 days' lists always refetched; EMPTY answers cached; RATE_LIMITED not cached; deadline stops fetching and still loads | unit | incremental, bounded |
| TC-30 | job | CLI: `--days --symbols --dry-run --rollback --offline --max-minutes`; return codes 0 / 1 / 2 | unit | parses, codes |
| TC-31 | real data | transform over the real raw files (/home/deploy/nivesh-truedata-raw, read-only) vs the staging rows of the 2 Nov loads | data | identical, or each difference explained |
| TC-32 | real data | finance-cost meaning: TrueData FY `Expenses.NonOperating.InterestExpense` / unit vs our `screener_in_annual` finance_costs_cr, same FY | data | match rate reported; field trusted only if it matches |
| TC-33 | live | a handful of real calls through the new client methods (list, balance sheet, cash flow, P&L) | app | records, no secret printed |
| TC-34 | regression | existing TrueData client + crosscheck tests and DQ suite tests still pass | unit | all pass |

### Added 3 Nov 2026 (owner rules of 3 Nov), written before implementing them

Owner: "keep on staging.. on prod please use our snapshot data" and "do not use words like buy, stop loss, target".
The environment gate is the shared `backend/nidp/shared/deploy_env.py` (`truedata_load_gate(conn)`), kept
byte-identical with PR #455: staging only when the database written to is `nidp_staging` and no production signal is
present (NIDP_HOME=/opt/nidp, NIDP_ENV/APP_ENV prod|production); NIDP_ENV=staging alone is not trusted.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-35 | env gate | staging database, no production signal | unit | the job runs as before |
| TC-36 | env gate | any production signal (database `nidp`, NIDP_HOME=/opt/nidp, NIDP_ENV or APP_ENV prod/production) | unit | refused: no TrueData call, no warehouse write, no job_log row |
| TC-37 | env gate | unknown or conflicting signals (other database; NIDP_ENV=staging on a non-staging database) | unit | refused: no TrueData call, no data write; one SKIPPED job_log row, error_class NOT_STAGING |
| TC-38 | env gate | `--rollback` in staging, production and unknown environments | unit | allowed everywhere |
| TC-39 | deploy | production's NIDP cron is generated from `nidp-staging.cron` only; this job's cron file is separate and staging-only | unit | job absent from the prod cron source |
| TC-40 | CI | the "Backend unit tests (allowlist)" list, run in one image on this branch and on untouched origin/dev | regression | no failure the branch adds |
| TC-41 | wording | every string this PR adds: no buy / sell / stop loss / target / entry / exit / accumulate / upside / recommend | review | none (TrueData field names excepted) |

Out of scope for this PR (UNVERIFIED until after merge): the job running on the staging NIDP VM (needs merge, deploy
of migration 190, and the owner installing the cron file). Steps to verify then are listed in the final report.
