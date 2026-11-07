# Functionality Verification Report — TrueData fundamentals: no unit from the filing's rounding text

- **Branch:** `fix/truedata-unit-no-rounding-fallback` (from origin/dev 6d30a7f7)
- **Date:** 2026-11-03
- **Author:** Claude (full-stack developer + QA)
- **Environment:** offline (backend image `nivesh/backend:staging`, `--network none`). The real raw TrueData cache was mounted read-only. References were exported read-only from `nidp_staging`.
- **Changed areas:** backend services: yes (`nidp/services/truedata_fundamentals/transform.py`, an NIDP job, not an app route). Frontend src: no.

## Summary
`unit_for` decided a filing's unit from (1) the revenue anchor, (2) the share-capital anchor, (3) the filing's own `LevelOfRoundingUsedInFinancialStatements` text, else (4) refused. Step 3 is removed.

A filing whose company has no revenue or share-capital anchor is now REFUSED. The reason reads, for example, `unit unknown (no revenue or share-capital anchor (filing rounding text 'Millions' is not trusted))`. When `infer_units` left an anchor note, that note is kept in the reason.

Other changes:
- `ROUNDING_WORDS` is deleted.
- The module docstring is updated, and so is row TC-12 of `truedata_fundamentals_job_TESTCASES.md`.
- The dated report `truedata_fundamentals_job_20261103.md` is a historical record and is left as written.

Nothing else in the transform, plan or loader changed.

## Test Cases
Authored before the fix: `test_reports/truedata_unit_fallback_fix_TESTCASES.md`.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| UF-01 | transform | no anchor; text "Millions" / "Lakhs" / "Crores" / "Thousands" / "Actual" | unit | refused, reason quotes the untrusted text | PASS |
| UF-02 | transform | no anchor, blank text; no anchor plus a RADICO-like mismatch note | unit | refused; the note is kept | PASS |
| UF-03 | transform | `build()`: anchorless company, every statement says "Millions" | unit | 0 offers; BS, CF and FC refused | PASS |
| UF-04 | transform | `build()`: anchored company whose text says "Lakhs" | unit | loads in crore (the anchor), values unchanged | PASS |
| UF-05 | transform | SWIGGY-like pre-IPO H1: capital 13,440.1 vs anchor 261, text "Millions" | unit | still refused by the capital guard | PASS |
| UF-06 | job | whole job with a fake client and warehouse, anchorless "Millions" company | unit | warehouse handed 0 offers; status OK; reasons listed | PASS |
| UF-07 | loader (PG) | anchorless "Millions" company plus anchored company, loaded into a real Postgres | integration | anchored rows written; anchorless: 0 changed, 0 inserted, 0 provenance | PASS |
| UF-08 | code | no unit is decided from the rounding text | review | the field is read only to quote it | PASS |
| UF-09 | regression | TrueData test files, PG tests, CI allowlist | regression | all pass | PASS (see the full-allowlist note) |
| UF-10 | real data | origin/dev transform vs branch transform over the real raw files | data | only the rounding-text offers disappear; named companies as expected | PASS |

## API / Endpoint Tests (staging)
No app route changed; this is a NIDP batch job's pure transform. The job is not deployed or scheduled, and this PR deploys nothing. pytest evidence follows. Every run used `nivesh/backend:staging` with `--network none` and the worktree mounted read-only.

**The four test files without a DSN:**
`python -m pytest nidp/tests/services/test_truedata_fundamentals_{transform,service,pg}.py nidp/tests/shared/test_truedata_corporate.py -q -p no:cacheprovider -rs`
```
104 passed, 10 skipped in 0.89s
```
The 10 skips were all `NIDP_TDF_PG_DSN not set (needs a throwaway Postgres)`.

**PG tests.** Run on a throwaway `postgres:16-alpine` (`--network none`, network shared with the test container) with `NIDP_TDF_PG_DSN`, as documented in the test file:
```
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc18_to_tc22_fill_only_inserts_provenance PASSED [ 10%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc23_dry_run_writes_nothing_and_matches_the_real_run PASSED [ 20%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc24_rollback_restores_exactly_and_is_idempotent PASSED [ 30%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc24_rollback_keeps_a_value_another_writer_set_since PASSED [ 40%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc24_rollback_refuses_a_non_uuid PASSED [ 50%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc25_same_input_twice_writes_nothing_new PASSED [ 60%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc26_error_mid_load_leaves_nothing PASSED [ 70%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_uf07_anchorless_millions_company_writes_nothing_anchored_company_loads PASSED [ 80%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_read_references_shares_from_market_cap_and_close_on_its_date PASSED [ 90%]
nidp/tests/services/test_truedata_fundamentals_pg.py::test_tc35_to_tc37_gate_reads_current_database PASSED [100%]
============================== 10 passed in 2.19s ==============================
```

**Final tree, the four files with the DSN set** (nothing skipped; rerun after the last formatting edit):
```
114 passed in 3.45s
```

**The new tests catch the defect.** The same tests were run with origin/dev's `transform.py` mounted read-only over the branch's (`grep -c ROUNDING_WORDS` = 2 in the mounted file), with `-k "uf0 or tc12"`:
```
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_tc12_uf01_no_anchor_is_refused_the_rounding_text_is_never_a_unit[Millions]
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_tc12_uf01_no_anchor_is_refused_the_rounding_text_is_never_a_unit[Lakhs]
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_tc12_uf01_no_anchor_is_refused_the_rounding_text_is_never_a_unit[Crores]
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_tc12_uf01_no_anchor_is_refused_the_rounding_text_is_never_a_unit[Thousands]
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_tc12_uf01_no_anchor_is_refused_the_rounding_text_is_never_a_unit[Actual]
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_tc12_uf02_no_anchor_blank_text_and_anchor_note_kept
FAILED nidp/tests/services/test_truedata_fundamentals_transform.py::test_uf03_build_anchorless_millions_company_offers_nothing
FAILED nidp/tests/services/test_truedata_fundamentals_service.py::test_uf06_job_hands_the_warehouse_nothing_for_an_anchorless_millions_company
FAILED nidp/tests/services/test_truedata_fundamentals_pg.py::test_uf07_anchorless_millions_company_writes_nothing_anchored_company_loads
9 failed, 3 passed, 81 deselected in 1.14s
```
The 3 that pass on both trees are the regression guards: UF-04, UF-05, and anchored-unit-wins. On the branch, all 12 pass:
```
====================== 12 passed, 81 deselected in 0.81s =======================
```

**CI "Backend unit tests (allowlist)", the TrueData files.** These are the 9 allowlisted files whose names contain `truedata`, run with CI's env and flags (`python -m pytest -q -p no:cacheprovider <files>`) on the final tree:
```
227 passed, 18 skipped, 3 warnings in 8.81s
```

**CI allowlist, all 311 files:** this ran once the sparse worktree also held `frontend-v5/e2e/fixtures`, `research` and `docs`, which some allowlisted
tests read. It used the same image, env and flags:
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
3 failed, 9108 passed, 52 skipped, 16 warnings in 319.22s (0:05:19)
```
**The 3 failures are pre-existing and unrelated.** These two files were run with origin/dev's copies of all 4 changed backend files mounted read-only over the branch's (`grep -c ROUNDING_WORDS` = 2, so it is origin/dev's transform):
```
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
3 failed, 19 passed, 2 warnings in 17.14s
```
The result is the same 3 on the branch tree (`3 failed, 19 passed`). None of these files imports the TrueData job.

## UI / Playwright Tests
Not applicable: no frontend change.

## Data Correctness

### UF-10: the job's transform over the real raw files, origin/dev vs this branch (read-only)
**Inputs:**
- Raw files: `/home/deploy/nivesh-truedata-raw` (`lists`, `pl`, `al`, `cf`, `plq`), mounted read-only.
- References: exported from `nidp_staging` (`current_database()` = `nidp_staging`, 2026-11-03 12:42 IST) inside `BEGIN READ ONLY … ROLLBACK`. They used the same SELECTs as `loader.read_references`: the universe, the BSE map, revenue rows, and market cap / close.

**Method:**
- A supervised fetch was still adding quarter P&Ls to the raw cache during this check: `plq` went from 15,570 to 15,965 files.
- So both transforms ran in ONE process. Every raw answer was read once and memoized, and both saw identical payloads.
- Both used `T.build`, with every filing as the window and finance costs on.
- Offer values were compared by hash. No vendor payload is printed.
```
snapshot: statements read 42044 missing 6617 | filings 19957 companies 2299 | same filings: True
references: known 2633 bse 2472 revenue rows 26109 with shares 2124
offers before {'balance_sheet': 8501, 'cash_flow': 4114, 'finance_costs': 9279} after {'balance_sheet': 8430, 'cash_flow': 4096, 'finance_costs': 9279}
offers gone 89 {('balance_sheet', 'lakh', 'filing rounding'): 64, ('balance_sheet', 'million', 'filing rounding'): 3, ('balance_sheet', 'crore', 'filing rounding'): 4, ('cash_flow', 'lakh', 'filing rounding'): 16, ('cash_flow', 'crore', 'filing rounding'): 2}
   every gone offer took its unit from the rounding text: True
   offers before whose unit came from the rounding text: 89 | after: 0
offers added 0 | offers present in both but different (filing, unit, how or values): 0
units before {'crore': 2077, 'million': 1} after {'crore': 2077, 'million': 1} | identical unit per company: True
REFUSED for no anchor ('unit unknown') before: {'statements': 666, 'filings': 456, 'companies': 132, 'by kind': {'finance_costs': 387, 'balance_sheet': 198, 'cash_flow': 81}}
REFUSED for no anchor ('unit unknown') after:  {'statements': 756, 'filings': 513, 'companies': 133, 'by kind': {'balance_sheet': 269, 'cash_flow': 100, 'finance_costs': 387}}
filings newly refused: 57 companies: 52
   newly refused statements by rounding text quoted: {'Lakhs': 55, 'Crores': 4, 'Millions': 3}
all other reject reasons identical before/after: False ( 4258 before, 4257 after )
   other rejects whose reason changed: 1 | each is now 'unit unknown (...)' + the SAME old reason: True | their old reason types: {'no CFO': 1}
   rejects that exist only after: 89 (each a gone offer: True )

== the four companies (balance sheet / cash flow; 2024-09-30 for SWIGGY)
  before MANYAVAR OFFER  balance_sheet 2024-09-30 filing 2304026 unit million | filing rounding 'Millions'
  after  MANYAVAR REFUSE balance_sheet 2024-09-30 filing 2304026 | unit unknown (no revenue or share-capital anchor (filing rounding text 'Millions' is not trusted))
  before VIMTALABS OFFER  balance_sheet 2024-09-30 filing 2265974 unit million | filing rounding 'Millions'
  after  VIMTALABS REFUSE balance_sheet 2024-09-30 filing 2265974 | unit unknown (no revenue or share-capital anchor (filing rounding text 'Millions' is not trusted))
  before KICL OFFER  balance_sheet 2024-09-30 filing 2290059 unit million | filing rounding 'Millions'
  after  KICL REFUSE balance_sheet 2024-09-30 filing 2290059 | unit unknown (no revenue or share-capital anchor (filing rounding text 'Millions' is not trusted))
  before SWIGGY REFUSE balance_sheet 2024-09-30 filing 2218681 | share capital 13440.1 vs anchor 261 (unit may differ from the anchor filing)
  after  SWIGGY REFUSE balance_sheet 2024-09-30 filing 2218681 | share capital 13440.1 vs anchor 261 (unit may differ from the anchor filing)

== must be unchanged: every offer (incl. finance costs) identical before/after
  TCS: offers before 15 after 15 identical True | rejects identical True (1) | unit [(('TCS', 'Consolidated'), 'crore', 'revenue anchor (annual row) ratio 1')]
  RELIANCE: offers before 15 after 15 identical True | rejects identical True (1) | unit [(('RELIANCE', 'Consolidated'), 'crore', 'revenue anchor (annual row) ratio 1.019')]
  RADICO: offers before 7 after 7 identical True | rejects identical True (9) | unit [(('RADICO', 'Consolidated'), 'crore', 'share-capital anchor (rupees per unit 1.001e+07)')]
```
**Reading:**
- Before the fix, the job would have offered **89 statements** (71 balance sheets, 18 cash flows) whose unit came only from the rounding text:
  - 80 in lakh;
  - 3 in million (MANYAVAR, VIMTALABS, KICL, all 2024-09-30);
  - 6 in crore.
- After the fix, all 89 are refused. 0 offers were added, and 0 offers were changed (filing, unit, how and values).
- Refusals for "no anchor" grew as follows:
  - statements: 666 → 756 (+90: the 89 offers, plus one cash flow already refused for "no CFO" that now also cites the unit);
  - filings: 456 → 513;
  - companies: 132 → 133.
- Finance costs did not change: 387 refused before and after. That path never read the rounding text.
- MANYAVAR's half-year cash flow, the ₹7.9 cr example, was never offered by the job: half-year cash flows are not loaded (`cf_half_year_not_loaded`). Its 2024-09-30 balance sheet was offered in million, and is now refused.
- Why 89 and not 149: the brief's 149 rows came from the supervised scripts of 2 Nov (`td_transform.py`). The 89 here is the merged job's transform on today's raw cache with today's references. These are different pipelines, so the counts differ; this report does not reconcile the two.

### No writes
- No warehouse write, no deploy, no cron change.
- The staging reference export ran inside `BEGIN READ ONLY … ROLLBACK`.
- A read-only check on the NIDP VM confirmed that no cron file references `truedata_fundamentals`. `grep -l truedata_fundamentals /etc/cron.d/*` returned `grep_rc=1`; the files present are `nidp-staging`, `nidp-staging-db-snapshot`, `nidp-staging-truedata` and two `.bak` files.

## Inputs required from user
none

## Verdict: PASS
