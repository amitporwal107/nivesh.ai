# Market-data source switch (PR-2) — test cases

Branch `feat/market-data-switch` from origin/dev 783d7095. Owner decisions (29 Oct 2026):
- go with the TrueData API once TrueData replies;
- "once TrueData is plugged we can switch off the remaining";
- ONE switch for everything, flipped by a config file in a PR.

Note: these cases were written after the first wiring edit, not before it. The protocol asks for them up front; the
miss is stated here rather than hidden.

The switch is `backend/config/market_data_source.json` (`source`: current | shadow | truedata), resolved by
`backend/nidp/shared/market_data_source.py`. This PR ships it set to `current`, and TrueData is not integrated
(`TRUEDATA_INTEGRATED = False`), so nothing changes on staging.

## Resolver (unit: `nidp/tests/shared/test_market_data_source.py`)
| ID | Configured / conditions | Expected effective | Our replaced feeds | TrueData feeds | Reason |
|---|---|---|---|---|---|
| MS-1 | current | current | on | off | — |
| MS-2 | truedata, TrueData not integrated | current | on | off | TRUEDATA_NOT_INTEGRATED |
| MS-3 | truedata, integrated, no credentials | current | on | off | TRUEDATA_NOT_CONFIGURED |
| MS-4 | truedata, integrated, credentials, licence not confirmed | shadow | on | on | TRUEDATA_LICENCE_NOT_CONFIRMED |
| MS-5 | truedata, integrated, credentials, licence confirmed | truedata (serve truedata) | OFF | on | — |
| MS-6 | shadow, integrated, credentials | shadow | on | on | — |
| MS-7 | everything ready + env MARKET_DATA_SOURCE_FORCE_CURRENT=1 | current | on | off | FORCED_CURRENT_BY_ENV |
| MS-8 | source "nse" (invalid) | current | on | off | INVALID_SOURCE |
| MS-9 | file missing / not JSON | current | on | off | CONFIG_MISSING / CONFIG_UNREADABLE |
| MS-10 | feed_is_on: replaced feed vs delivery, fii_dii, index_constituents | replaced feeds follow the switch; others always on | | | |
| MS-11 | the committed file as shipped | current, no reasons, TRUEDATA_INTEGRATED False | on | off | |

## Wiring (unit)
| ID | Case | Expected |
|---|---|---|
| MS-12 | A NIDP ingester for a replaced feed (index_close) runs while TrueData serves | run finalised SKIPPED with error_class SWITCHED_OFF and the reason; fetch never called |
| MS-13 | Same ingester at `current` | fetch called as before (no behaviour change) |
| MS-14 | A non-replaced feed (delivery) while TrueData serves | runs (fetch called) |
| MS-15 | feed_reconciler feed list while TrueData serves | index_close dropped; bhavcopy, delivery, fii_dii, corporate_announcements, fno_bhavcopy kept |
| MS-14b | NSE bhavcopy and fno_bhavcopy while TrueData serves | keep fetching (never switched off: raw prices, settle, delisted names) |
| MS-16 | dlq_redrive while TrueData serves | entries for switched-off feeds are not re-run and stay PENDING (counted SWITCHED_OFF); others re-run |
| MS-17 | kite_live_feed.start while TrueData serves | returns False, no task started |
| MS-18 | kite_live_feed.start at `current` | starts as before (returns True) |

## Staging (read only, on both VMs, from a scratch copy of this branch)
| ID | Case | Expected |
|---|---|---|
| MS-S1 | App VM, inside the running backend container's image: `python -m nidp.shared.market_data_source` | `effective: current`, `our_feeds_on: true`, reads the file from the backend dir |
| MS-S2 | NIDP VM, with the job runner's Python and environment | same resolution: the NIDP jobs keep running |
| MS-S3 | App VM: `feed_is_on("kite_live_feed")` and the start gate | True: the live feed would start exactly as today |
