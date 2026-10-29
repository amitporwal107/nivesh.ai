# Market-data source switch (PR-2) — verification report, 29 Oct 2026

Branch `feat/market-data-switch` from origin/dev 783d7095. Test cases: `test_reports/market_data_switch_TESTCASES.md`.
They were written after the first wiring edit, not before; that is stated there.

## Scope
Owner decisions (29 Oct 2026):
- go with the TrueData API once TrueData replies;
- "once TrueData is plugged we can switch off the remaining";
- ONE switch for everything, flipped by a config file in a PR.

This PR adds the switch and its gates and wires our replaced feeds to it: NIDP bhavcopy, fno_bhavcopy, index_close and
corporate_actions, and the app's Kite live feed. It ships set to `current` with `TRUEDATA_INTEGRATED = False`, so
nothing changes on staging. The TrueData ingesters and live adapter are built against TrueData's documentation and a
trial once they reply (see `docs/MARKET_DATA_SOURCE_SWITCH.md`).

## Changed
| File | Change |
|---|---|
| `backend/config/market_data_source.json` | The switch: `source` current / shadow / truedata, `truedata_licence_confirmed`, who and why |
| `backend/nidp/shared/market_data_source.py` | Resolver with gates (env force-current, not integrated, no credentials, licence not confirmed), `feed_is_on`, CLI |
| `backend/nidp/shared/ingester_base.py` | A replaced feed records SKIPPED / `SWITCHED_OFF` with the reason when TrueData serves |
| `backend/nidp/services/feed_reconciler/service.py` | Does not heal switched-off feeds |
| `backend/nidp/services/dlq_redrive/service.py` | Leaves switched-off feeds' entries PENDING (counted `SWITCHED_OFF`) |
| `backend/services/kite_live_feed/feed.py` | `start()` does not start the Kite live feed when TrueData serves live quotes |
| `docs/MARKET_DATA_SOURCE_SWITCH.md` | How to flip, what goes off, the safety gates, the TrueData steps |
| `.github/workflows/backend-tests.yml` | The two new suites added to the CI allowlist |

## Results

### Unit
```
nidp/tests/shared/test_market_data_source.py   16 passed  (MS-1 … MS-16)
tests/test_market_data_switch_live_feed.py      2 passed  (MS-17, MS-18)
18 passed in 1.19s
```

### Regression (existing suites for every touched file)
```
tests/test_kite_live_feed.py, nidp/tests/services/test_dlq_redrive.py, nidp/tests/services/test_feed_reconciler.py,
nidp/tests/test_backfill.py, nidp/tests/shared/*  →  123 passed, 0 failed
```

### Staging, read only, both VMs (scratch copy of this branch; live code untouched; scratch removed after)
MS-S1, app VM, inside `nivesh-staging-app-backend` (its Python and environment): `python -m nidp.shared.market_data_source`
```
"configured": "current", "effective": "current", "serve_from": "current",
"our_feeds_on": true, "truedata_feeds_on": false, "reasons": []
```
MS-S3, app VM:
```
feed_is_on(kite_live_feed) = True
start() has switch gate = True
```
So the live feed starts exactly as today.

MS-S2, NIDP VM, with the job runner's own Python (`/opt/nidp-staging/venv`) and `nidp.env`: the same resolution, plus
```
feeds on: {'bhavcopy': True, 'fno_bhavcopy': True, 'index_close': True, 'corporate_actions': True, 'delivery': True}
reconciler feeds: ['bhavcopy', 'delivery', 'index_close', 'fii_dii', 'corporate_announcements', 'fno_bhavcopy']
```
That matches today's list: nothing is switched off.

## UNVERIFIED (by design until TrueData is integrated)
- **Shadow and truedata modes on real servers:** proved only in unit tests. The TrueData side does not exist yet, so
  the code refuses those modes on staging (`TRUEDATA_NOT_INTEGRATED`).
- **After merge:** the app backend picks up the file once it restarts (bind-mount; see the staging deploy timing note).
  The NIDP jobs pick it up once `/opt/nidp/dev-repo` is refreshed. At `current`, neither changes behaviour.

## Verdict: PASS
