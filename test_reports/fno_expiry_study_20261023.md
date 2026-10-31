# F&O Stage B2 expiry study: report (2026-10-23)

Scope: research tooling only (`services/fno_backtest/expiry_study.py`, `scripts/run_fno_expiry_study.py`); no product route or screen changed. Test cases: `fno_expiry_study_TESTCASES.md`.

Evidence:
- Backend tests in `nivesh/backend:staging` (`--network none`): `29 passed` (expiry study 10, Stage A backtest 19).
- Real run: `experiment fo-b2-c4295fca6fbf hash 0fc1bf8132facf54 configs tested 1224` on the warehouse export (STF 162,109 rows, 260 sessions); frozen baseline hash verified by the runner before it ran.
- Findings, including the negative results: `docs/FO_STAGE_B2_FINDINGS_20261023.md`. Hypotheses A, B and C are not supported; short build-up near-month is `inconclusive` (permutation p 0.06).

UNVERIFIED: nothing here is validated; the data is one year; no staging HTTP route was touched.

## Verdict: PASS
