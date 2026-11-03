# TrueData client, adapter, shadow cross-check and the switch (PR-3) — verification report, 29 Oct 2026

- **Branch:** `feat/truedata-client`, stacked on `feat/market-data-switch` (PR #402). Merge #402 first.
- **Test cases:** `test_reports/truedata_client_TESTCASES.md`, written before the code. The switch cases (SW-1 … SW-7)
  and TC-14b/c were added during the work, also before their code.

## Scope
Owner, 29 Oct 2026:
- "we will use TrueData";
- "please make code changes as required";
- "make sure this is a switch: if we are not going with TrueData we can switch it to the current implementation".

| File | What |
|---|---|
| `backend/nidp/shared/sources/truedata.py` | stdlib-only REST client: token (cached, refreshed once on a 401), per-host rate gate, failures classified into the provider contract's codes, bars, ticks with bid/ask, bhavcopy, symbol master, corporate actions, symbol changes, expiries, index components, option chain with Greeks; NSE → TrueData symbol mapping |
| `backend/services/providers/truedata_adapter.py` | ProviderResult wrapper (provider_id `truedata`); **refuses when the switch is off** |
| `backend/services/providers/contract.py` | `PROVIDER_TRUEDATA = "truedata"` |
| `backend/nidp/services/truedata_crosscheck/` | read-only comparison of TrueData's bhavcopy with NSE's files in the warehouse; **refuses when the switch is off** unless `--evaluation` |
| `backend/nidp/shared/market_data_source.py` | `truedata_is_on()` and `truedata_off_message()`: the one question every TrueData entry point asks |
| `docs/MARKET_DATA_SOURCE_SWITCH.md` | new section "Going back to our current feeds" |
| `.github/workflows/backend-tests.yml` | the two new suites added to the CI allowlist |

**Not in this PR:**
- no route, job or cron uses TrueData;
- the switch file stays `current` and `TRUEDATA_INTEGRATED` stays False;
- the live-quote feed is the next PR (market hours).

## The switch: how to go back to our current feeds
- **Normal way:** a PR setting `"source": "current"`.
- **Emergency way, no PR:** `MARKET_DATA_SOURCE_FORCE_CURRENT=1` in a server's environment.

At `current`:
- every replaced feed runs again;
- the adapter returns DQ_BLOCKED / NOT_CONFIGURED without calling TrueData;
- the cross-check exits with SWITCHED_OFF without reading anything.

NSE's own bhavcopies never stop, whatever the switch says.

## Results

### Unit and regression (backend image, network off; synthetic rows, not vendor data)
```
nidp/tests/shared/test_truedata_client.py + tests/test_truedata_adapter.py      46 passed in 0.84s
regression: tests/test_research_providers.py, test_market_data_switch_live_feed.py, test_kite_live_feed.py,
  nidp/tests/shared/ (incl. test_market_data_source.py with SW-1, SW-2), nidp/tests/services/test_dlq_redrive.py,
  test_feed_reconciler.py, nidp/tests/test_backfill.py, tests/test_truedata_adapter.py      227 passed in 8.66s
```

| Cases | Result |
|---|---|
| TC-1 … TC-15, SM-1 … SM-5, AD-1/2, XC-1/2 | pass |
| SW-1 … SW-7 | pass |
| TC-14b/c | pass |

`tests/test_nivesh_cas_provider.py` fails in the offline image because it calls an external preview host. It is
unrelated to this PR and pre-existing (`socket.gaierror` for `nidp-backfill-ui.preview.emergentagent.com`).

### RC-1: real calls to TrueData with the trial login (app VM, read only)
```
OK   bars RELIANCE eod+delivery: 6 rows; fields=[timestamp, open, high, low, close, volume, oi, delvolume, delpercent]
OK   bars RELIANCE 1min: 15 rows; first 2026-10-28T09:15:00 open 1194.5
OK   ticks RELIANCE bid/ask: 67 rows; fields=[timestamp, ltp, volume, oi, bid, bidqty, ask, askqty]
OK   bhavcopy EQ 2026-10-28: 3820 rows; RELIANCE close=1158; symbol types=['str']
OK   bhavcopy FO 2026-10-28: 12320 rows
OK   symbol master FO RELIANCE: 20 rows; tick_size=0.1 circuit=(1048.4,1281.2) expiry_date=2026-11-23 (company column aligned)
OK   symbol master EQ RELIANCE: 2 rows; isin INE002A01018, company Reliance Industries Limited, tick_size=0.1
OK   corporate actions 20-28 Oct: 71 rows before de-duplication, 53 after (0 exact duplicates left)
OK   symbol changes LTIM: 1 rows; effective_date=2026-02-27 (LTIM -> LTM)
OK   expiries NIFTY: 18 (2026-11-03 … 2031-06-24)
OK   index components NIFTY 50: 50 rows
OK   option chain + Greeks NIFTY 3 Nov: 104 rows (delta, theta, vega, gamma, rho, IV per side)
ERR  bars INFIBEAM (delisted): EMPTY_RESPONSE retryable=False :: TrueData getbars: No data exists for INFIBEAM
ERR  bars NIFTY20022712000CE (2020): IDENTIFIER_NOT_RESOLVED retryable=False :: TrueData getbars: Symbol does not exist
secret in output: False | token in output: False
```
Corporate-action ratios on real rows:
```
split  BSE MIDAAS_BSE     ratio=1.0 suspect=True  | Stock Split From Rs.10/- to Rs.5/-
split  BSE AZADIND_BSE    ratio=1.0 suspect=True  | Stock Split From Rs.10/- to Rs.2/-
split  NSE AZADIND        ratio=5.0 suspect=False | Face Value Split (SubDivision) From Rs 10 To Rs 2
split  BSE JSWDULUX_BSE   ratio=1.0 suspect=True  | Stock Split From Rs.10/- to Rs.1/-
split  NSE JSWDULUX       ratio=10.0 suspect=False| Face Value Split (SubDivision) From Rs 10 To Re 1
bonus  BSE TITANBIO_BSE   ratio=1.25 suspect=False| Bonus issue 1:4
```

### XC-3: real cross-check on the NIDP VM (job runner's Python and `nidp.env`; scratch copy, removed after)
Run with `--evaluation`, because the switch is `current`. The warehouse was read in a read-only transaction; nothing was
written.

| Date | Equity (EQ/BE/BZ/SM/ST) | Traded options | Traded futures | Untraded NSE contracts |
|---|---|---|---|---|
| 28 Oct | 3,404 / 3,404 identical (OHLC + volume), 0 missing | 11,126 / 11,126 identical (close + OI) | 597 / 597 close; **596 / 597 OI** | 23,310, none in TrueData (as expected) |
| 27 Oct | 3,423 / 3,423 identical, 0 missing | 22,245 / 22,245 identical | 651 / 651 close; **650 / 651 OI** | 18,304, none in TrueData |

The one difference, both days:
```
{'contract': 'IDEA26NOVFUT', 'nse_close': 11.93, 'td_close': 11.93, 'nse_oi': 6173152800.0, 'td_oi': 0.0}   (28 Oct)
{'contract': 'IDEA26NOVFUT', 'nse_close': 12.15, 'td_close': 12.15, 'nse_oi': 6189377625.0, 'td_oi': 0.0}   (27 Oct)
```
Warehouse query: the only contracts with OI above 2,147,483,647 (the 32-bit integer limit) on those days are exactly these
two rows. So TrueData most likely cannot carry open interest above that limit.
- **Verdict per run:** DIFFERENT, exit 1. The check did its job.
- **Test case XC-3:** its expectation ("every traded contract equal, as found in the trial") assumed the trial result.
  That result was wrong for this one contract, and the private evaluation note is corrected.

### Staging: the switch keeps TrueData off (read only, scratch copies, removed after)
App VM, inside `nivesh-staging-app-backend` (its Python and environment):
```
resolution: {"configured": "current", "effective": "current", "our_feeds_on": true, "truedata_feeds_on": false, "reasons": []}
truedata_is_on: False | TRUEDATA_INTEGRATED: False
adapter: BLOCKED NOT_CONFIGURED | switched_off: True | TrueData is switched off: market data source is 'current' (backend/config/market_data_source.json)
network calls made: 0
```
NIDP VM, job environment, without `--evaluation`:
```
"market_data_source": "current", "verdict": "SWITCHED_OFF",
"message": "TrueData is switched off: market data source is 'current' (backend/config/market_data_source.json)"
exit=2
```

### Staging API endpoints
This PR adds or changes **no API endpoint**: no route calls the adapter or the cross-check yet, and the only change to
a shared app file is one new constant (`PROVIDER_TRUEDATA`). So there is no endpoint to curl. The staging evidence
above is:
- an in-process run inside the running staging backend container (its Python and environment);
- a job-environment run on the NIDP VM.

The branch is not deployed; it reaches staging only after the merge to dev.

## Findings for TrueData (added to the questions for them)
1. Open interest above 2,147,483,647 comes back as 0 (IDEA Nov future, 27 and 28 Oct).
2. Corporate actions:
   - identical rows repeat (the client drops exact duplicates);
   - BSE split rows carry ratio 1 where the NSE row carries 5 or 10 (the client flags them `ratio_suspect`).

## UNVERIFIED
- **Shadow and truedata modes on real servers:** proved only in unit tests (SW-4, MS-4 … MS-6). The code still refuses
  them on staging (`TRUEDATA_INTEGRATED = False`), by design until the live feed is verified.
- **TrueData rate limits** under sustained load: the gate spaces calls by 1.1 s per host. Their documents disagree
  (10, 3 and 1 request/s).
- **Licence:** TrueData's written answer on education/simulation use and display is still awaited. The switch's licence
  flag stays false.

## Verdict: PASS
