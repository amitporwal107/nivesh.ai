# OVERRIDE: Desk macro-release calendar backend — UNIT + SCRATCH-DB + LIVE-SOURCE VERIFIED, STAGING HTTP NOT RUN

REASON: The macro calendar routes (DaaS /v1/desk/macro-calendar*, app /api/markets/macro-calendar*) exist only on branch feat/desk-macro-calendar. Staging HTTP verification is blocked until (1) the branch is merged to dev (this session cannot push to dev), (2) migration 164 is applied to the NIDP warehouse and (3) FRED_API_KEY is added to the NIDP environment and the ingester run once. (2) and (3) are shared-staging writes the user has not approved; (3) needs the user's key in a secret store.

Evidence: test_reports/desk_macro_calendar_backend_20261021.md (100 new tests pass; real collection of 380 rows from FRED/Fed/MoSPI/RBI with 0 failures; migration applied twice on a scratch Postgres; real upsert and router SQL run on scratch Postgres).
