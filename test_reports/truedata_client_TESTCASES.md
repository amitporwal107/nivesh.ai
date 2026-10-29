# TrueData client (PR-3) — test cases, written before the code

Branch `feat/truedata-client`, stacked on `feat/market-data-switch` (PR #402). Owner, 29 Oct 2026:
- "we will use TrueData";
- after the trial evaluation: "please make code changes as required".

Scope of this PR:
- a stdlib-only TrueData REST client (`nidp/shared/sources/truedata.py`);
- an app provider adapter on the existing contract (`services/providers/truedata_adapter.py`);
- a read-only shadow cross-check of TrueData's bhavcopy against NSE's files in our warehouse
  (`python -m nidp.services.truedata_crosscheck`).

The live-quote gateway is PR-4, tested during market hours. Nothing here changes what users see, and nothing is
scheduled. `TRUEDATA_INTEGRATED` stays False.

## Client (unit, fake transport: `nidp/tests/shared/test_truedata_client.py`)
The fixtures are SYNTHETIC rows in TrueData's documented formats. They are not vendor data.

| ID | Case | Expected |
|---|---|---|
| TC-1 | Credentials from env TRUEDATA_USERNAME / TRUEDATA_PASSWORD; none configured | NOT_CONFIGURED error, no network call |
| TC-2 | Token: first call POSTs the form (grant_type=password) and caches the token until shortly before `expires_in` | one auth call for many requests; refreshed once expired |
| TC-3 | A 401 on a data call | token refreshed once, request retried once; a second 401 → AUTH_EXPIRED |
| TC-4 | "No data exists for X" | EMPTY_RESPONSE |
| TC-5 | "Symbol does not exist" | IDENTIFIER_NOT_RESOLVED |
| TC-6 | "API calls quota exceeded" / HTTP 429 | RATE_LIMITED (retryable) |
| TC-7 | "Segment not subscribed" / "Authorization has been denied" | NOT_CONFIGURED (entitlement), not retryable |
| TC-8 | An HTML 404 page | PROVIDER_ERROR naming the path |
| TC-9 | Rate gate: two calls to the same host | the second waits until `min_interval` has passed |
| TC-10 | bars(): CSV → records with typed fields; `eod` vs `1min` timestamps; `delivery=True` adds delvolume/delpercent | parsed; the from/to format is yymmddTHH:MM:SS |
| TC-11 | ticks(bidask=True) | records with bid, bidqty, ask, askqty |
| TC-12 | bhavcopy('EQ'/'FO', date) | records (symbolid, symbol, timestamp, OHLC, volume, oi) |
| TC-13 | symbol_master(): the credentials go in TrueData's query string | the URL never appears in an error message or a log line; the F&O header with one more column than the rows is aligned (company dropped) |
| TC-14 | corporate_actions(ex_from, ex_to) | records with the ratio as a float and the dates parsed; BSE rows (`_BSE`) flagged with exchange=BSE |
| TC-15 | Secrets: no error message, repr or log line contains the password or the token | asserted over every error path |

## Symbol mapping (unit)
| ID | Case | Expected |
|---|---|---|
| SM-1 | option NIFTY 2026-11-03 23000 CE | `NIFTY26110323000CE` |
| SM-2 | strike with decimals (RELIANCE 1080.5 PE) | `RELIANCE2611231080.5PE` |
| SM-3 | future RELIANCE expiry 2026-11-23 | `RELIANCE26NOVFUT` |
| SM-4 | continuous NIFTY month 1 / 2 | `NIFTY-I` / `NIFTY-II` |
| SM-5 | index "Nifty 50" (warehouse name) | `NIFTY 50` |

## Adapter (unit: `tests/test_truedata_adapter.py`)
| ID | Case | Expected |
|---|---|---|
| AD-1 | Successful bars | ProviderResult with provider_id `truedata`, records, DQ_OK, a source_timestamp |
| AD-2 | Client error | ProviderResult with the error code, retryable flag and DQ status (EMPTY / BLOCKED); never a raised exception to the caller |

## Shadow cross-check (unit + real)
| ID | Case | Expected |
|---|---|---|
| XC-1 | Compare function on synthetic NSE and TrueData rows | counts: matched, close/volume/OI equal, missing on either side, mismatches listed |
| XC-2 | F&O: the TrueData symbol is built from NSE ticker, expiry, strike and type; only traded NSE contracts are expected in TrueData | as measured in the trial: untraded contracts not counted as missing |
| XC-3 | Real run, read only: `python -m nidp.services.truedata_crosscheck --date 2026-10-28` on the NIDP VM with the job environment and the trial credentials | equity: every EQ/BE/BZ/SM/ST row equal; F&O: every traded contract equal (as found in the trial). No warehouse writes. |

## Real calls from the app VM (integration, read only)
| ID | Case | Expected |
|---|---|---|
| RC-1 | Client against TrueData with the trial login: token; bars RELIANCE eod and 1min; ticks with bid/ask; bhavcopy EQ/FO; symbol master F&O RELIANCE; corporate actions for a week; symbol changes LTIM; option chain with Greeks | every call parses into records. Errors are classified, never raw. |

## The switch governs TrueData (added 29 Oct, before the code; owner: "make sure this is a switch: if we are not going with TrueData we can switch it to the current implementation")
`backend/config/market_data_source.json` (PR #402) stays the one switch. These cases make every TrueData entry point in this
PR obey it, and prove the way back.
| ID | Case | Expected |
|---|---|---|
| SW-1 | Rollback: the file goes from `truedata` (everything ready) back to `current` | our replaced feeds on again, TrueData off, no reasons |
| SW-2 | Emergency rollback without a PR: `MARKET_DATA_SOURCE_FORCE_CURRENT=1` while the file says `truedata` | effective current; `truedata_is_on()` False |
| SW-3 | Adapter at `current` (or not integrated, or forced current) | ProviderResult DQ_BLOCKED / NOT_CONFIGURED, meta `switched_off` with the reason; the TrueData client is never called |
| SW-4 | Adapter at `shadow` / `truedata` | calls TrueData as in AD-1 |
| SW-5 | Cross-check CLI at `current` without `--evaluation` | prints verdict SWITCHED_OFF, exit 2, no TrueData call, no warehouse read |
| SW-6 | Cross-check CLI with `--evaluation` (manual trial evaluation, read only) | runs; the report states `mode: evaluation (switch is current)` |
| SW-7 | The committed switch file, as shipped with this PR | still `current`; `TRUEDATA_INTEGRATED` still False; `truedata_is_on()` False |

## Corporate-action data quality (found in the real calls, RC-1)
| ID | Case | Expected |
|---|---|---|
| TC-14b | TrueData repeats identical corporate-action rows (seen: the same BSE buy-back three times) | exact duplicates dropped; the count is not inflated |
| TC-14c | A split / bonus / consolidation row with ratio 1 (seen on BSE split rows; the NSE row of the same split carries 5 or 10) | flagged `ratio_suspect = True`, never silently used as "no adjustment" |
