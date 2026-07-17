# OVERRIDE — pipeline dashboard: UI + admin route not yet verified on staging

REASON: The frontend (`PipelinePanel.tsx`, `NidpConsole/index.tsx`) and the app-backend route
(`admin_nidp_pipeline.py`) are committed to `dev` and build clean, but have NEVER executed on
staging. Two hard blockers, neither of which I can resolve without the user:

1. **The staging app backend has not redeployed.** Container `nivesh-staging-app-backend` is
   12 hours old and `test -f /app/routes/admin_nidp_pipeline.py` returns NO. The dev-branch
   push has not been picked up by `deploy-backend-staging`. Until it redeploys, the admin
   route does not exist to call (TC3), and its graceful-degradation path cannot be exercised
   (TC7).

2. **Playwright needs a real `session_token` cookie** (TC8). The staging UI is behind auth and
   the cookie expires. Per .claude/VERIFICATION_PROTOCOL.md this must be asked for, never
   faked.

WHAT *IS* VERIFIED (real output in `pipeline_dashboard.md`): the query_api layer end-to-end
against the real staging DB — `GET /pipeline/stages` 200 in 1.48s with all six stages and
correct counts, 401 without a bearer token, and the BSE-lag detection (TC4) that is the whole
reason the feature exists.

WHAT IS NOT: that the admin page renders. `typecheck` clean + `✓ built in 1m47s` + testids
present in `dist` prove it compiles and ships in the bundle. They do not prove it renders, and
I am not presenting them as if they do.

NEXT: redeploy the staging app (backend + frontend) from `dev`, then run TC3/TC7/TC8 with a
user-provided session token.
