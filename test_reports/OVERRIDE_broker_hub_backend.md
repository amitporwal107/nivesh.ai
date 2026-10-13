# OVERRIDE — Broker hub backend

REASON: Three things remain unverified on staging. (1) The storage-failure fix (PR #209) and the Motilal Oswal and ICICI Direct sign-in code (branch `feat/broker-hub-motilal-icici`) are unit-tested only; they reach staging when their PRs are merged into `dev`. (2) Neither Motilal Oswal nor ICICI Direct has been connected with a live account: that needs each broker's app key and secret set on staging, the staging server's IP registered on the app, and a login from the user. (3) The only account connected so far is an empty Zerodha account, so the mapping of real holdings and positions rows has never been compared with a broker's own app. To finish: merge the PRs, set the keys, connect each broker, and run the live checks L1–L3 in `test_reports/broker_hub_motilal_icici_20261014_0425.md` and L7 in `test_reports/broker_hub_staging_20261014_0355.md`.

- **Date:** 2026-10-14
- **Verified live on staging so far:** Zerodha sign-in from Settings, encrypted storage, Sync now, positions read, Remove and reconnect (empty account; counts matched Zerodha's own SDK).
- **Not verified:** any other broker live; a non-empty account; whether one app key can sign in other customers at ICICI Direct or Motilal Oswal; the daily 17:30 IST job running; logout ending broker sessions on staging.
- **This is not a pass.** Resolve before merge to `main`.
