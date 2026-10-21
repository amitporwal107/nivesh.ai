# OVERRIDE — Provider foundations (Kite Connect + Trendlyne MCP, docs/charting.md §32 Phase A)

REASON: Staging endpoint verification is deferred. The branch `feat/provider-foundations` is not pushed or checked out on staging, the backend container has not been recreated to pick up TRENDLYNE_MCP_URL, and the Kite key/secret and access token are not yet where the staging backend reads them; all three need the user's go-ahead. To finish: deploy the branch to staging, supply the Kite credentials to the backend, run TC-34..TC-39 in `test_reports/provider_foundations_20261012.md` before the Kite token expires (~06:00 IST 2026-10-13), and set that report's verdict.

Status: IN PROGRESS — not a pass. Unit tests (79 passed) and a live adapter-level run against Trendlyne are recorded in the report; both adapters have been run against the live providers from a throwaway container, but no `/api/research/providers/*` call has been made on staging.

Date: 2026-10-12 · Branch: feat/provider-foundations
