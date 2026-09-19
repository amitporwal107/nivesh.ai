# Track 1 — frozen scope v3

**Status: FROZEN** at the commit that adds this file. Owner approval 2026-09-19 (after the sealed H-A run exposed ETF
opening prints and the over-broad band rule). Supersedes v2 only where listed; everything else in v1/v2 stands.
**Not retroactive:** the sealed H-B run started 2026-09-19 08:29 IST under v2 completes under v2.

## Decisions recorded here
- **H-A is CLOSED** as a hypothesis (owner, 2026-09-19): its sealed "pass" came from untradeable ETF opening prints;
  on stocks alone it was fragile (`sealed/HA_VALIDATION_RESULT.md`). In Track 1 H-A is kept only as a **reference
  column** (the section-8 opportunity-cost comparison for H-B) — never shown or treated as a trade candidate.
- The final-test slice (2023-01 → 2024-07) remains sealed.

## Changes from v2
| # | Item | v3 definition |
|---|---|---|
| 1 | **ETFs excluded** | Live: exclude where `nidp.security_reference_daily.is_etf` is true for the session (published 07:30 IST on the session date). Historical data without that table: exclude where the Kite instrument name contains "ETF" |
| 2 | **Circuit-band exclusion uses each stock's own band** (replaces the ±0.25pp rule) | Live: exclude only if the stock HAS a price band for the session (`band_raw` ≠ "No Band") **and** its open is at the lower band price: `|O − P0_raw × (1 − band)| ≤ max(Rs 0.05, 0.05% × O)`. Stocks with **No Band** (F&O) are never excluded by this rule |
| 3 | Historical fallback (no band data) | Exclude only if the 09:15 five-minute bar is **locked** (its low equals the open) **and** the open is within 0.25pp of a standard band (5/10/20%). Knowable at 09:20, so it applies to H-B (09:45 entry) only |
| 4 | Band data missing on a live session | The signal is recorded with `band_status = UNKNOWN` and **not traded** (reported in the exception list) — never inferred |
| 5 | Watchlist | Shows the most recent known band as *indicative*; the outcome job always uses the session's own band row |

Everything else — universe (EQ, Rs 5 cr 20-day value), gap ≤ −3%, H-B 09:45 confirmation, exits, 5-position cap,
cost model v1, UNRESOLVED handling, write-once outputs, report layout — is unchanged from v1/v2.

> **H-B candidate confirmation rule — operational test, not validated edge.**
