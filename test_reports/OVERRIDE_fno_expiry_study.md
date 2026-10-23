# OVERRIDE: fno_expiry_study (Stage B2 research tooling)

REASON: The edited files are offline research code (backend/services/fno_backtest/expiry_study.py, backend/scripts/run_fno_expiry_study.py) and their tests. No API route, no response shape and no frontend file changed, so there is no staging endpoint or Playwright screen to exercise. It is not "blocked"; the gate's staging-API and Playwright evidence does not apply.

What was verified instead (this session): 29 backend tests passed in nivesh/backend:staging; one real run on the warehouse export, experiment fo-b2-c4295fca6fbf, 1,224 configurations, frozen baseline hash checked. Report: test_reports/fno_expiry_study_20261023.md. Findings: docs/FO_STAGE_B2_FINDINGS_20261023.md.

UNVERIFIED: nothing is validated; no staging HTTP route was touched.
