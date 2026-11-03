# Functionality Verification Report — F&O OI reconciliation (bhavcopy D−1 · bhavcopy D · Kite intraday · app)

- **Branch:** feat/fno-oi-reconcile (from origin/dev 5152e19d)
- **Date:** 2026-11-03
- **Author:** Claude (QA engineer + domain/data-trust)
- **Environment:** staging (nivesh-staging-app-backend, nidp_staging through DaaS, the platform Kite login), read only
- **Changed areas:** backend routes/services: yes (new `services/fno_oi_reconcile.py`, new `scripts/reconcile_fno_oi.py`,
  new test, CI allowlist line). No existing route, service or screen changed. frontend src: no.
- **Test cases:** test_reports/fno_oi_reconcile_TESTCASES.md (authored before the code)

## Summary
The owner's seven-line validation framework, built as a read-only reconciliation. It reads the app's own F&O routes
in-process as a system caller: the chain for every expiry and every strike, consolidated, futures, the oi-buildup
daily and intraday bars, and the options intraday pane. It also reads NSE's F&O bhavcopy for the day (D) and the
session before (P) through the data platform, and Kite's candles. It then runs checks C1–C7 and prints PASS / FAIL /
WARN / SKIP per check, with examples. On staging, for HDFCAMC, RELIANCE, TVSMOTOR and SONACOMS (2 → 3 Nov 2026):

- **App figures are right:** previous OI, OI change and chart-vs-chain totals pass for every contract (C1, C3, C6).
- **Small-base % (C4 WARN):** true figures that read as huge moves, e.g. HDFCAMC 2,420 PE +1800% = 3 → 57 lots;
  RELIANCE Dec 1,320 PE +2633% = 3 → 82 lots.
- **Chart month lines (C7 FAIL):** the current/next/far lines don't add up because 3 contract rolls in the window are
  never a bar. The rolls explain the whole gap (0 unexplained). Consolidated passes.
- **Kite vs NSE closing OI (C2 FAIL):** Kite's last candle disagrees with NSE's close on 15–23 contracts per symbol.
  Kite's own quote after the close equals its candle, so the app passes Kite through faithfully. Near-month futures
  read 0.8–8.2% above NSE on all four symbols.
- **Options intraday pane empty (C5 WARN):** blank for 3 of 4 symbols, because one illiquid contract without a candle
  blanks every sum. RELIANCE's pane passes.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 … TC-19 | C1–C7, roll-up | hand-worked fixtures on HDFCAMC's real 2–3 Nov figures | unit | as in TESTCASES | PASS (26 tests, below) |
| TC-6b | C2/C5 | a contract the route lists in `contracts` (no bars) AND `missing` counts once | unit (added after the staging run found it) | one SKIP, n = 2 | PASS |
| TC-20 | staging | HDFCAMC | api | C1, C3 PASS every contract; C4 WARN small bases; C7 FAIL current/next/far, PASS consolidated; C2 Kite differences reported | PASS — see the amendment below |
| TC-21 | staging | RELIANCE, TVSMOTOR, SONACOMS | api | runs end to end, every check has a status | PASS |
| TC-22 | data | independent SQL on nidp.fno_bhavcopy | data | the reconciler's expected figures = SQL | PASS (7 of 7 sampled) |
| TC-23 | safety | writes nothing | review | GET-only routes, ReadOnlyKite, no DB write | PASS |

**Amendment to TC-20.** The TESTCASES row listed 2,440 PE as a WARN. Its base is 3,300 = 11 lots, above the 10-lot
threshold, so the tool correctly did not warn. The written expectation was wrong, not the tool. The four WARNs it
raised are 2,380 PE (6 lots), 2,420 PE (3 lots), Dec 2,360 PE (3 lots) and the chart's far-month future (2 lots).
The threshold is `--small-base-lots`.

## API / Endpoint Tests (staging)

The routes are read in-process inside the running staging backend, the same code the screens call
(`GET /api/fno/{sym}/expiries`, `/chain?expiry=&around=500`, `/chain/consolidated`, `/futures`,
`/futures/oi-buildup?interval=15m&window=4&sessions=2&daily=60`, `/options/intraday?interval=15m&sessions=2&strikes=5`).
The branch is not deployed, so the two new files were piped in on stdin and loaded in memory. Nothing was copied into
the container.

- **Command:** `sudo docker exec -i -w /app/backend nivesh-staging-app-backend python - < boot_four.py` (boot =
  service + script source, base64; runs `main(["--symbols","HDFCAMC,RELIANCE,TVSMOTOR,SONACOMS","--json",tmp])`)
- **Output (status lines, unedited; 50 s):**
```
HDFCAMC  2026-11-02 -> 2026-11-03  overall FAIL
  C1 PASS Previous-day closing OI matches the previous session's bhavcopy  (pass 187, fail 0, warn 0, skip 0)
  C2 FAIL Current closing OI matches the current session's bhavcopy  (pass 199, fail 15, warn 0, skip 1)
  C3 PASS OI change = current OI - previous OI  (pass 377, fail 0, warn 0, skip 0)
  C4 WARN OI change % = change / previous OI x 100  (pass 183, fail 0, warn 4, skip 0)
  C5 WARN Intraday OI change matches the intraday snapshot differences  (pass 4, fail 0, warn 1, skip 0)
  C6 PASS Chart totals match the option chain  (pass 21, fail 0, warn 0, skip 0)
  C7 FAIL Increase and decrease segments sum to the net OI movement  (pass 5, fail 3, warn 0, skip 0)
RELIANCE  2026-11-02 -> 2026-11-03  overall FAIL
  C1 PASS Previous-day closing OI matches the previous session's bhavcopy  (pass 250, fail 0, warn 0, skip 0)
  C2 FAIL Current closing OI matches the current session's bhavcopy  (pass 255, fail 23, warn 0, skip 0)
  C3 PASS OI change = current OI - previous OI  (pass 503, fail 0, warn 0, skip 0)
  C4 WARN OI change % = change / previous OI x 100  (pass 245, fail 0, warn 5, skip 0)
  C5 PASS Intraday OI change matches the intraday snapshot differences  (pass 5, fail 0, warn 0, skip 0)
  C6 PASS Chart totals match the option chain  (pass 21, fail 0, warn 0, skip 0)
  C7 FAIL Increase and decrease segments sum to the net OI movement  (pass 7, fail 3, warn 0, skip 0)
TVSMOTOR  2026-11-02 -> 2026-11-03  overall FAIL
  C1 PASS Previous-day closing OI matches the previous session's bhavcopy  (pass 133, fail 0, warn 0, skip 0)
  C2 FAIL Current closing OI matches the current session's bhavcopy  (pass 141, fail 18, warn 0, skip 2)
  C3 PASS OI change = current OI - previous OI  (pass 269, fail 0, warn 0, skip 0)
  C4 WARN OI change % = change / previous OI x 100  (pass 132, fail 0, warn 1, skip 0)
  C5 WARN Intraday OI change matches the intraday snapshot differences  (pass 4, fail 0, warn 1, skip 0)
  C6 PASS Chart totals match the option chain  (pass 21, fail 0, warn 0, skip 0)
  C7 FAIL Increase and decrease segments sum to the net OI movement  (pass 5, fail 3, warn 0, skip 0)
SONACOMS  2026-11-02 -> 2026-11-03  overall FAIL
  C1 PASS Previous-day closing OI matches the previous session's bhavcopy  (pass 146, fail 0, warn 0, skip 0)
  C2 FAIL Current closing OI matches the current session's bhavcopy  (pass 155, fail 17, warn 0, skip 2)
  C3 PASS OI change = current OI - previous OI  (pass 295, fail 0, warn 0, skip 0)
  C4 WARN OI change % = change / previous OI x 100  (pass 145, fail 0, warn 1, skip 0)
  C5 WARN Intraday OI change matches the intraday snapshot differences  (pass 4, fail 0, warn 1, skip 0)
  C6 PASS Chart totals match the option chain  (pass 21, fail 0, warn 0, skip 0)
  C7 FAIL Increase and decrease segments sum to the net OI movement  (pass 5, fail 3, warn 0, skip 0)
SUMMARY: HDFCAMC FAIL, RELIANCE FAIL, TVSMOTOR FAIL, SONACOMS FAIL
EXIT 3
```
- **Examples from the same run (unedited):**
```
      WARN [chain] 2026-11-23 2420 PE expected 1,800.00 got 1,800.00  - true but misleading: 3 lots -> 57 lots (OI 900 -> 17,100, a base under 10 lots)
      WARN [chain] 2026-12-29 1320 PE expected 2,633.30 got 2,633.30  - true but misleading: 3 lots -> 82 lots (OI 1,500 -> 41,000, a base under 10 lots)
      FAIL [chart] chart daily current (2026-11-23): 2026-08-07 .. 2026-11-03 expected 238,500 got -18,762,000  - increases +2,565,000, decreases -21,327,000 = -18,762,000; the line moved +238,500; 3 contract roll(s) worth +19,000,500 are never a bar (2026-08-26 2026-08-25->2026-09-29 +6,046,800, 2026-09-30 2026-09-29->2026-10-27 +6,398,400, 2026-10-28 2026-10-27->2026-11-23 +6,555,300)
      FAIL [kite] 2026-11-23 2420 PE expected 17,100 got 16,800  - Kite's last candle on 2026-11-03 (15:30) vs NSE's closing OI
      WARN [kite] options pane sums  - no sums at all: 104 of 104 CE/PE rows are null because 16 of 22 contracts lack a candle at some time (HDFCAMC26NOV2340PE, HDFCAMC26NOV2360PE, HDFCAMC26NOV2380PE, HDFCAMC26NOV2400PE, HDFCAMC26NOV2420PE, HDFCAMC26NOV2440CE and 10 more)
```
- **Near-month futures, Kite vs NSE (from the run's JSON):** HDFCAMC 6,889,200 vs Kite 6,944,100 (+0.8%) · RELIANCE
  137,000,500 vs 148,239,000 (+8.2%) · TVSMOTOR 6,683,775 vs 6,818,525 (+2.0%) · SONACOMS 12,923,750 vs 13,308,400 (+3.0%).
- **Result:** PASS. The tool runs end to end on real staging data and its verdicts are confirmed independently below.
  The FAIL / WARN statuses are the data findings it exists to surface; they are not failures of the tool.

- **pytest** (staging image, branch mounted read only, network off):
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-wt-fno-oi-recon:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest tests/test_fno_oi_reconcile.py -q -p no:cacheprovider`
  - Output: `26 passed, 1 warning in 0.80s`
  - Result: PASS. The first run had 1 failure (`KeyError: 'expected'` in TC-9): the test was wrong, because a finding with
    no % on either side leaves the fields out by design. Fixed in the test.

## Data Correctness (staging)

- **SQL on nidp.fno_bhavcopy (3 Nov vs 2 Nov), independent of the tool:**
```
 HDFCAMC  | 2026-11-23 | FUT | 7006500 | 6889200 |  -117300 | 300
 HDFCAMC  | 2027-01-25 | FUT |     600 |    2100 |     1500 | 300
 RELIANCE | 2026-11-23 | 1280 CE | 5660500 | 4916000 | -744500 | 500
 RELIANCE | 2026-12-29 | 1320 PE |    1500 |   41000 |   39500 | 500
 SONACOMS | 2026-11-23 |  880 PE |  367500 |  377300 |    9800 | 1225
 TVSMOTOR | 2026-11-23 | 4300 CE |  251825 |  218400 |  -33425 | 175
```
  Each equals the tool's expected figure: 6,889,200; far +250% (2 → 7 lots); 4,916,000; +2,633.3% (3 → 82 lots);
  377,300; 218,400. Earlier in the session the same SQL over all 26 HDFCAMC Nov contracts in the owner's screenshot
  showed NSE's change_in_oi = OI(3 Nov) − OI(2 Nov) exactly. Result: PASS.
- **Kite's own quote after the close (ReadOnlyKite, 17:16–17:24 IST), to place the C2 Kite FAILs:**
```
token_status ok
NFO:HDFCAMC26NOVFUT oi 6944100 last_trade_time 2026-11-03 15:39:59 timestamp 2026-11-03 17:16:11
NFO:HDFCAMC26NOV2420PE oi 16800 last_trade_time 2026-11-03 15:39:30 timestamp 2026-11-03 17:21:39
NFO:HDFCAMC26NOV2400CE oi 102300 last_trade_time 2026-11-03 15:39:49 timestamp 2026-11-03 17:21:39
NFO:RELIANCE26NOV1280CE oi 4928000 last_trade_time 2026-11-03 15:39:56 timestamp 2026-11-03 17:23:57
NFO:TVSMOTOR26NOV4300CE oi 219100 last_trade_time 2026-11-03 15:39:55 timestamp 2026-11-03 17:24:39
NFO:SONACOMS26NOV880PE oi 374850 last_trade_time 2026-11-03 15:39:01 timestamp 2026-11-03 17:24:13
```
  Every quote OI equals the Kite candle the tool compared, so the app passes Kite through faithfully. The disagreement
  is between Kite's final OI and NSE's bhavcopy. It is not a stale earlier day: RELIANCE's Kite 148.24M is above NSE's
  30 Oct, 2 Nov and 3 Nov closes alike. **UNVERIFIED:** why Kite's end-of-day OI differs from NSE's file (the exchange's
  intraday OI broadcast vs its final figure is a likely reason, not proven).

## Not verified / follow-ups
- **UNVERIFIED:** whether any screen subtracts NSE's previous close from Kite's live OI during market hours. With
  today's numbers that would flip RELIANCE's sign: Kite 148.24M − NSE 2 Nov 141.12M = +7.1M "added", while NSE says
  −4.1M. A grep of routes/fno.py, routes/live_quotes.py, services/kite_live_feed and services/fno_* found none; the
  frontend was not checked.
- Not scheduled. A nightly run after the 22:15 IST bhavcopy (`--symbols` list, exit code 3 on a FAIL) is a separate,
  approved step.
- The screen fixes this report points at are NOT made, pending the owner: lots next to the % (C4), the Consolidated
  default or roll markers on the 1D/1W futures pane (C7), and carrying OI forward in the options pane (C5).

## Inputs required from user
- none (in-process system caller; no session token used for the run)

## Verdict: PASS
