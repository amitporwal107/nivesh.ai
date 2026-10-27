# Functionality Verification Report — Results week (Earnings Surprise & Guidance Tracker P1), backend

- **Branch:** feat/earnings-surprise-tracker (worktree /home/deploy/nivesh-earnings-tracker)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER; backend engineer for P1)
- **Environment:** unit tests in a throwaway `nivesh/backend:staging` container (`--network none`); staging data read-only
  through a temporary overlay of `git archive HEAD backend` in `nivesh-staging-app-backend:/tmp/rw` (removed after use);
  NIDP warehouse read-only SQL. **Not deployed.**
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
`GET /api/desk/results-week` (spec §5), `services/results_week/` (scoring §4a–4c, OI across the coming months §4e, loaders,
build, insert-once store), `scripts/build_results_week.py` + `deploy/nivesh-staging/results-week.cron` (not installed), the
results signal applied at read time to `GET /api/positional/picks` and `/watchlist` (§4d), and `pipeline.universe_for`
returning the union of Chartink hits and fresh bars (TC-B12). Verified here: every unit test case, the staging dry runs for
2026-10-27 (snapshot and live mode) and 2026-10-26, and the warehouse data tests. The live HTTP route (TC-S3 and TC-S1's
HTTP 200) needs a deploy and is UNVERIFIED.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-B1 | scoring | z / verdict at band edges | unit | z=1 in line, 1.01 above, −2 well below | PASS |
| TC-B2 | scoring | unreliable / missing baseline | unit | null + "not rated: no reliable baseline" | PASS |
| TC-B3 | scoring | bank PAT-only; revenue-only | unit | weights renormalise | PASS |
| TC-B4 | scoring | composite renormalisation, coverage, null without surprise+trend | unit | as spec | PASS |
| TC-B5 | scoring | quality flags at thresholds; cash flow not checked | unit | as spec | PASS |
| TC-B6 | scoring | after 15:30 IST → next session; excess vs Nifty by hand | unit | 3.79 pp | PASS |
| TC-B7 | scoring | OI states + thresholds; non-F&O null | unit | as spec | PASS |
| TC-B8 | ideas | F&O / All lists, ties, note, one per symbol, filing-evening renormalisation | unit | as spec | PASS |
| TC-B9 | wording | no forbidden terms; label historical trend | unit + staging | [] | PASS |
| TC-B10 | route | 401 / 422 / 404 / 502 / live + Chartink join | unit (TestClient) | as spec | PASS |
| TC-B11 | job | dry run writes nothing; skip-if-done; insert-once; refusals | unit | as spec | PASS |
| TC-B12 | scanner | universe_for = hits ∪ bars (filtered) | unit | as spec | PASS |
| TC-B13 | failure | DaaS 5xx / Mongo / PG down → block null + gap | unit | rest answers | PASS |
| TC-B14 | scoring | too-wide band not rated (BAJAJ-AUTO / ITCHOTELS from staging) | unit | as spec | PASS |
| TC-B15 | scanner signal §4d | edges, loss→profit, decay from first reaction session, pending, weak, veto, before-limit, failure | unit (TestClient) | as spec | PASS |
| TC-B16 | OI §4e | total vs near month on the roll, rollover vs past, options PCR | unit | as spec | PASS |
| TC-B17 | OI §4c | expiry week: short covering 2 sessions out = 50, 8 out = 75 | unit | as spec | PASS |
| TC-S1 | staging | counts agree with DaaS expectations for the same windows | data (dry run) | equal | PASS (counts) · HTTP 200 UNVERIFIED |
| TC-S2 | staging | MANKIND / APLAPOLLO / SONACOMS YoY PAT = warehouse | data | equal | PASS |
| TC-S3 | staging | 401 without a session over HTTP | api | 401 | UNVERIFIED (needs deploy) |
| TC-S4 | staging | 26 Oct total OI / rollover / Nov PCR = coordinator's warehouse query | data (dry run) | equal | PASS (SONACOMS label note below) |

## API / Endpoint Tests (staging)
- **Endpoint:** `GET /api/desk/results-week` — **UNVERIFIED over HTTP**: the route is not deployed (the running backend has
  no such route; a deploy + process restart is needed). The route's behaviour is covered by TC-B10 (FastAPI TestClient).
- **pytest (new + affected suites):**
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-earnings-tracker:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest tests/test_results_week.py tests/test_results_signal.py tests/test_positional_scan_universe.py tests/test_positional_engine.py tests/test_positional_desk_fields.py tests/test_scanner_bar_integrity.py tests/test_strategy_ideas.py tests/test_chartink_picks.py tests/test_chartink_strategy.py tests/test_chartink_desk.py tests/test_regime_fit.py tests/test_ai_watchlist.py tests/test_events_calendar_routes.py tests/test_event_ai_insight.py -q -p no:cacheprovider`
  - Output: `544 passed, 4 warnings in 50.24s`
  - New files verbose: `81 passed, 2 warnings in 7.03s` (tests/test_results_week.py, tests/test_results_signal.py, the 3 TC-B12 tests)
  - Result: PASS
- **CI allowlist (all 251 files of `.github/workflows/backend-tests.yml`, incl. the 2 new ones):**
  - Output: `3 failed, 6651 passed, 28 skipped, 15 warnings in 210.69s (0:03:30)`
  - The 3 failures (`test_cas_api_client.py::test_sandbox_parse_and_map`, `::test_convenience_helper_returns_list`,
    `test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches`) need outbound network (`Sandbox call failed — check
    network / keys`; `Cannot connect to host www.nseindia.com:443 … Temporary failure in name resolution`) and fail the same
    on the base commit e832ecb1 in the same container: `3 failed, 19 passed, 2 warnings in 15.80s`. Not caused by this branch.

## Staging dry runs (read-only overlay; `--dry-run` writes nothing)
Overlay: `git -C /home/deploy/nivesh-earnings-tracker archive HEAD backend | sudo docker exec -i nivesh-staging-app-backend sh -c 'rm -rf /tmp/rw && mkdir -p /tmp/rw && tar -x -C /tmp/rw'`; removed afterwards (`/tmp/rw removed`).

**2026-10-27, snapshot mode** — `python -m scripts.build_results_week --dry-run --date 2026-10-27 --signals --symbols …` at 19:00 IST:
```
[INFO] chartink refresh (dry run: nothing fetched, nothing written): users=1 scans_ok=0 scans_failed=0 per_user=[{'user_id_hash': 'a5530afb', 'would_run': 14}]
[INFO] built 2026-10-27 in 6.8 s
[ERROR] 2026-10-27 would be refused: the F&O build-up for 2026-10-27 is not loaded (it has None, 0 rows). Nothing written; a later run builds the day
exit=4
COUNTS {"declared": 35, "declared_pending": 80, "upcoming": 381, "above": 2, "in_line": 10, "below": 0, "not_rated": 23} partial False
WINDOWS [{"from": "2026-10-26", "to": "2026-10-28", "ok": true, "as_of": "2026-10-27", "counts": {"declared_figures": 35, "declared_pending": 80, "upcoming": 125}, "count": 240},
         {"from": "2026-10-29", "to": "2026-10-31", "ok": true, "as_of": "2026-10-27", "counts": {"declared_figures": 0, "declared_pending": 0, "upcoming": 256}, "count": 256}]
DECLARED METRICS {"pat": {"baseline too uncertain": 18, "no reliable baseline": 17}, "revenue": {"no reliable baseline": 15, "baseline too uncertain": 7, "rated": 12, "the filed figure is not in the stored results yet": 1}}
EARNINGS SCORE {"n": 27, "bands": {"above": 18, "in_line": 8, "below": 1}}
WORDING [] BODY KB 1642.7
```
Exit 4 is the designed refusal (the 27 Oct F&O bhavcopy lands ~22:15 IST); the build itself succeeded.
- **TC-S1:** declared 35 = 35 + 0; pending 80 = 80 + 0; upcoming 381 = 125 + 256 — equal to the DaaS windows' own counts. PASS.
- Verdict breakdown (declared with figures): above 2 · in line 10 · below 0 · not rated 23. No declared PAT band passes the
  0.35 half-width limit, so every verdict rests on revenue where it is rated (12 of 35).

**2026-10-27, live mode** (`--live`, as the route builds): `built 2026-10-27 in 11.4 s`; OI falls back to 26 Oct, labelled:
`OI build-up for 2026-10-27 is not loaded yet (the F&O bhavcopy lands ~22:15 IST): showing 2026-10-26`; wording `[]`.

**Results signal (§4d) as of 27 Oct 19:00 IST** (`seconds 3.9`, gaps `[]`; 69 strong, 16 weak). Filed 26 / 27 Oct:
```
MANKIND +10.0 [figures, filed 26 Oct 20:59 IST, session 0] · Q2 FY27 PAT +40.0 % YoY, revenue +17.3 %, EBITDA margin +207 bps (filed 26 Oct)
SONACOMS +10.0 [figures, filed 26 Oct 18:35 IST, session 0] · Q2 FY27 PAT +29.1 % YoY, revenue +34.3 %, EBITDA margin -275 bps (filed 26 Oct)
APLAPOLLO +10.0 [figures, filed 26 Oct 17:54 IST, session 0] · Q2 FY27 PAT +26.7 % YoY, revenue +34.5 %, EBITDA margin -33 bps (filed 26 Oct) · revenue above historical trend
AEGISVOPAK, ANTELOPUS, AVANTEL, BRIGHOTEL, ERIS, ITCHOTELS, LUMAXIND, MACPOWER, SUPREMEIND, VIDHIING, VINEETLAB +10.0 [figures, session 0]
TATACONSUM +5.0 [filing_analysis, filed 26 Oct 16:56 IST, session 0] · Filing analysis: moderately positive, confidence 80 % (figures not filed yet)
PAYTM +5.0 [filing_analysis, filed 26 Oct 20:54 IST, session 0] · Filing analysis: moderately positive, confidence 80 % (figures not filed yet)
ACUTAAS, JUBLINGREA, LEAPIND, MOREPENLAB, ONESOURCE, TATACAP, WEWORK +5.0 [filing_analysis, session 0]
AEQUS -5.0 · DALBHARAT -5.0 · MARUTI -5.0 [filing_analysis, session 0] · Filing analysis: moderately negative (figures not filed yet)
```
ATHERENERG has no signal: figures are stored (loss → profit, revenue +62.9 %, margin +1552 bps) but the other-income red flag
vetoes it (other income 4977 % of a barely positive PBT) — the rule as written.

**2026-10-26, snapshot mode** (`--dry-run --date 2026-10-26`): `built 2026-10-26 in 11.2 s`, `exit=0`, `dry run: nothing written`.

## Data Correctness (staging)
- **TC-S2** — `cat <<'EOF' | ~/.config/nivesh/nidp-psql.sh` (read-only) on `nidp.nse_financials_quarterly`, consolidated, quarterly:
  ```
    symbol   | pat_q2fy27 | pat_q2fy26 | pat_yoy_pct | rev_yoy_pct
   APLAPOLLO |   382.0000 |   301.5400 |        26.7 |        34.5
   MANKIND   |   716.0000 |   511.5100 |        40.0 |        17.3
   SONACOMS  |   223.0000 |   172.7700 |        29.1 |        34.3
  ```
  Dry-run rows: MANKIND `yoy {'revenue': 17.3, 'ebitda': 27.1, 'pat': 40.0}`, APLAPOLLO `{'revenue': 34.5, … 'pat': 26.7}`,
  SONACOMS `{'revenue': 34.3, … 'pat': 29.1}`. Equal. PASS.
- **TC-S4** — 26 Oct dry run vs the coordinator's warehouse query:
  ```
  MANKIND   long_buildup 100 | total 1s OI 9.6 spot 4.49 | rollover 83.4 range 81.2–91.5 within | next prem 0.78 range 0.32–0.65 above | Nov PCR 0.71 -> 0.43
  APLAPOLLO long_buildup 100 | total 1s OI 2.66 spot 2.17 | rollover 79.5 range 77.5–92.0 within | Nov PCR 0.47 -> 0.48
  SONACOMS  no_clear_signal 50 | total 1s OI -1.22 spot 3.86 | rollover 79.1 range 64.3–91.4 within | Nov PCR 0.65 -> 0.67
  IEX  short covering (expiry week: open interest falls as contracts close) 50 | OI -8.22 spot 2.27
  CDSL short covering (expiry week: …) 50 | OI -8.8 spot 0.63 ·  LODHA short covering (expiry week: …) 50 | OI -9.0 spot 1.77
  ```
  All figures match (spot from the cash close: MANKIND 4.49 vs the coordinator's 4.47 from the bhavcopy underlying). SONACOMS:
  −1.22 % total OI is under the 2 % threshold, so it reads "no clear signal", not the "short covering" in the coordinator's
  note. PASS.

## Inputs required from user
- none for these checks. Deploy approval is needed for TC-S3 / TC-S1 HTTP.

## UNVERIFIED (stated explicitly)
- UNVERIFIED: `GET /api/desk/results-week` over HTTP on staging (TC-S1 HTTP 200, TC-S3 401) — the backend is not deployed;
  after merge it needs a deploy and a backend process restart (bind-mounted code is not the running process).
- UNVERIFIED: the nightly job storing a day — never run without `--dry-run` (no writes to shared staging); the cron file
  `deploy/nivesh-staging/results-week.cron` is NOT installed (owner's go-ahead needed).
- UNVERIFIED: the scanner routes' adjusted order on staging over HTTP (unit-tested with TestClient; the signal list itself was
  computed on staging data above).
- UNVERIFIED: live-route latency in the running server (dry-run builds took 6.8–11.4 s; the route waits ≤ 45 s, then serves
  the previous build or 503 building).

## Verdict: PASS
