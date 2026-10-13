# OVERRIDE — Broker hub backend

REASON: Two things remain unverified. (1) The fix on branch `fix/broker-hub-storage-failure` (refuse a sign-in when the session token cannot be stored; return a code instead of a 500 when the save fails) is unit-tested only and is not on staging until its PR is merged into `dev`. (2) The only broker account connected on staging so far is an empty Zerodha account, so the mapping of real holdings and positions rows has never been compared with a broker's own app. To finish: merge the fix PR, then connect an account that holds something and compare its holdings and positions with the broker's app, as listed under L7 in `test_reports/broker_hub_staging_20261014_0355.md`.

- **Date:** 2026-10-14
- **Verified live on staging (2026-10-13 22:18–22:21 UTC):** Zerodha sign-in from Settings, encrypted storage of the session, Sync now, live positions read, Remove and reconnect. Counts from the hub's reader matched Zerodha's own SDK (0 holdings, 0 positions; the user confirmed the account is empty).
- **Not verified:** any broker other than Zerodha; a non-empty account; the daily 17:30 IST job running; logout ending broker sessions on staging.
- **This is not a pass.** Resolve before merge to `main`.
