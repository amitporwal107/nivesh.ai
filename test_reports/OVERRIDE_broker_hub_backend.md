# OVERRIDE — Broker hub backend (branch `feat/broker-hub`)

REASON: Staging verification is deferred because the code is not on staging and cannot be exercised there yet. It is uncommitted on `feat/broker-hub` (worktree `/home/deploy/nivesh-broker-hub`); staging deploys only from `dev`, and a session cannot push to `dev`. A real end-to-end check also needs things only the user can supply: Nivesh's developer-app keys for at least one broker with the staging callback URL registered at that broker, a real broker login, and a staging `session_token`. To finish: commit and push the branch, merge it into `dev`, set the broker app keys on staging, then run the endpoint and data checks listed in `test_reports/broker_hub_backend_20261013_1900.md` (TC-41 and the two staging sections) and replace this override with a report ending in the PASS verdict.

- **Date:** 2026-10-13
- **Status of the work:** IN PROGRESS. 738 unit tests pass in the staging backend image (788 in the same image with Fenix installed), using stubbed HTTP and an in-memory database. The whole app imports with the new routes registered. Nothing has been run against a live broker, the staging API or the staging database.
- **Not connectable today, by the brokers' own rules:** Groww (no redirect sign-in) and ICICI Direct (personal API keys, third-party use prohibited). Angel One is built but its multi-client permission is unconfirmed.
- **This is not a pass.** Resolve before merge to `main`.
