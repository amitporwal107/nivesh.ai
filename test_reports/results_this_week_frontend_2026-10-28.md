# Functionality Verification Report — Results This Week (P1.5): Watchlist block + per-stock results file (frontend)

- **Branch:** feat/results-week-watchlist-ui (from origin/dev 18b4870d), worktree /home/deploy/nivesh-results-file-ui
- **Date:** 2026-10-28 (IST, run just after midnight)
- **Author:** Claude (Design Engineer + Full Stack Developer + QA Engineer, frontend)
- **Environment:** production build (`vite build`, base /v5/) served by `vite preview` in the Playwright 1.47 container, mocked APIs (`pw.copilot-app.config.ts`); one test renders a REAL staging capture. Not deployed to staging.
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**
- **Spec:** docs/EARNINGS_SURPRISE_TRACKER.md §9 (branch feat/results-week-file, commit e0553edf); backend PR #381 (head 9e2cd445) field notes from the coordinator.

## Summary
The Watchlist page (`/v5/app/page/watchlist`) gains a **"Results This Week"** block (`data-testid="results-this-week"`) right after the
AI scanner watchlist: this week's results names from `GET /api/desk/results-week`, F&O | All (F&O = `fno: true`), ordered by the ideas
order of that list where the stock has a place, then the earnings score, then the meeting date. Each row: symbol + name (icon),
date · status, verdict pill (vs historical trend), earnings score, signal (ideas order), the AI scanner's results booster chip
(`results_signal` joined by symbol from `GET /api/positional/watchlist` + `/picks`; none → nothing), F&O before → after
(`fno_track`; across a monthly expiry the route's rollover reading, uncoloured, with spot and the carry; the note on hover),
reaction vs Nifty and the filing-analysis sentiment band. Cards on a phone. An older list route without `fno_track` hides that part.

Each row opens the **results file** (drawer, `data-testid="results-file"`) from `GET /api/desk/results-week/stock/{symbol}?date=`:
Preview (lines, expected ranges, last 4 quarters, past reactions, positioning) · Pre-result filings · The result — early commentary
on the unaudited result (items: summary, positives, negatives, amounts, open questions, band + impact + confidence, filing link) +
Results sentiment · Post-result · Analyst views (a "Not connected" state with the route's note) · Cash & F&O tracker (rel −5 … +5;
rel 0 highlighted; expiry-day chip + carry vs usual; next-month premium; PCR; before vs after; the route's notes) · Scores (verdict,
earnings score and its parts, technical, ideas-order signal and parts, results booster). Loading, error (Retry) and 404
`no_results_meeting` states; Scores still read the list's row when the file fails. Missing data says "not available" /
"not analysed", never 0. Commentary text is the route's (stored filing analyses); none is written by the screen.

The desk's **Events › Results week** opens the same file from each row (`File ›`, `results-week-file-{SYM}`) and from its
existing drawer (`Results file ›`, `results-week-drawer-file`); nothing was removed from the view or the drawer.

Files: `screens/workspace/ResultsThisWeek.tsx` (new), `screens/tradingdesk/resultsweek/ResultsFile.tsx` (new),
`.../resultsweek/results-file-data.ts` (new), `.../resultsweek/results-week-data.ts` (fno_track + Snap reader, exported helpers),
`.../resultsweek/ResultsWeekView.tsx` + `ResultsWeekDrawer.tsx` (file actions), `screens/Watchlist.tsx` (mount + header line),
`e2e/tests/copilot-app-results-this-week.spec.ts` (new).

## Test Cases
> Authored after the API + UI design (contract §9 + the coordinator's field notes), before the spec run. MOCK fixtures in the §9 /
> backend shapes (symbols MOCK*), except TC-W14 (REAL staging capture).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-W1 | Watchlist | Block placement, title + week, counts, basis, ideas note | e2e | after `ai-scanner-watchlist`, before the research watchlist; "Results This Week · Mon 26 Oct – Sat 31 Oct"; `?date=2026-10-27` | PASS |
| TC-W2 | Watchlist | F&O / All toggle and order | e2e | F&O = MOCKA, MOCKU1, MOCKD, MOCKX, MOCKP, MOCKE; All = MOCKA, MOCKB, MOCKU2, MOCKX, MOCKD, MOCKP, MOCKU1, MOCKE; idea outside the week never a row | PASS |
| TC-W3 | Watchlist | Cells and missing values | e2e | verdict / score / signal / reaction / sentiment per row; pending "figures pending" + "not ordered"; upcoming "not declared yet"; no 0 for missing | PASS |
| TC-W4 | Watchlist | Results booster join | e2e | MOCKA "Strong results +5" from the scanner row; none for MOCKD / MOCKU1; opening the chip does not open the file | PASS |
| TC-W5 | Watchlist | F&O before → after | e2e | "Long build-up · spot +4.49% · OI +9.60%"; expiry window → rollover text, `data-comparable=false`, no build-up word, note as title; upcoming "So far" + after "results not declared yet" | PASS |
| TC-W6 | Results file | Every section, in order, with the route's content | e2e | 7 sections in contract order; coverage note; preview lines / ranges / quarters (newest first) / past / positioning; items with positives, negatives, amounts, open questions, link; sentiment; post empty; analyst not connected; track rel −5…0, rel 0 highlighted, expiry carry −1.0 pp, PCR / premium; before vs after; notes (expiry note shown once); scores; Escape returns focus | PASS |
| TC-W7 | Results file | Missing parts | e2e/edge | non-F&O: no futures columns, cash-only note; partial answer (no preview / commentary / track): "not available"; upcoming: no rel 0, "so far", "results not declared yet" | PASS |
| TC-W8 | Results file | 404 / error | failure | 404 `no_results_meeting` → plain sentence; 500 → error + Retry recovers; Scores from the row in both | PASS |
| TC-W9 | Watchlist | List loading / error | failure | gated → `rtw-loading`; 502 → `rtw-error`; Retry recovers | PASS |
| TC-W10 | Watchlist | Older list route (no `fno_track`) | edge | F&O before → after hidden (no `rtw-fno-*`), rest unchanged | PASS |
| TC-W11 | Watchlist | Wording (SEBI) | e2e | no pick / recommend / buy / sell / beat the Street; disclaimer present | PASS |
| TC-W12 | Events › Results week | Open the file from the drawer and from a row | e2e | drawer → `Results file ›` → file (drawer closed); row `File ›` → file without the drawer; existing drawer content intact | PASS |
| TC-W13 | Phone 390 | Cards, file, no sideways page scroll | e2e | no page overflow on list (both universes) and file; before/after stacked; drawer inside 390 px | PASS |
| TC-W14 | Watchlist | REAL staging capture (27 Oct, pre-`fno_track`) | contract | F&O / All counts and first ≤ 20 rows = the fixture's own ideas order; part hidden; no page error; no overflow | PASS |

Regression (unchanged specs, same run): results week (Events view + ideas), results-week contract (REAL capture), AI scanner results
chip, results today/tomorrow, AI scanner watchlist, watchlists, workspace (Watchlist page), screens.

## API / Endpoint Tests (staging)
Not applicable to this change: no backend route or service was edited here. The backend (`GET /api/desk/results-week/stock/{symbol}`,
`fno_track`) is PR #381 on feat/results-week-file, with its own report `test_reports/results_this_week_backend_20261028.md` (pytest
168 passed; staging dry run). The shapes coded against were read from that branch (`services/results_week/stock.py`, `track.py`).

## UI / Playwright Tests
- **Command** (Docker, no network; Playwright 1.47; production build with `VITE_BASE=/v5/`, preview on :5174):
  `npx tsc --noEmit -p tsconfig.json && vite build && vite preview & npx playwright test --config pw.copilot-app.config.ts <9 specs>`
- **Output (real, unedited excerpts):**
```
tsc OK
✓ built in 25.91s
Running 125 tests using 3 workers
  4 skipped
  121 passed (2.0m)
```
  Passed per spec (count of ✓ lines): copilot-app-results-this-week 14 · copilot-app-results-week 8 · copilot-app-results-week-contract 2 ·
  copilot-app-desk-results-signal 3 · copilot-app-desk-results-today 7 · copilot-app-ai-watchlist 14 · copilot-app-watchlists 21 ·
  copilot-app-workspace 26 · copilot-app-screens 26. ✘ lines: 0. Skipped: the 4 screenshot tests (2 here, 2 in results-week), which run only
  with RTW_SHOTS / RW_SHOTS in a networked run.
```
✓   25 … copilot-app-results-this-week.spec.ts:256:3 › … › TC-W1 the block sits right after the AI scanner watchlist; title, week, counts, basis (994ms)
✓   26 … :270:3 › … › TC-W2 F&O | All toggle and the order: ideas order of that list, then earnings score, then date (1.0s)
✓   27 … :286:3 › … › TC-W3 cells: date · status, verdict, earnings score, signal, reaction, sentiment; missing says so (1.3s)
✓   28 … :313:3 › … › TC-W4 results booster: the scanner row's results_signal joined by symbol; none → nothing (1.2s)
✓   29 … :326:3 › … › TC-W5 F&O before → after: fno_track text and spot / OI %; across an expiry the rollover reading, uncoloured (1.1s)
✓   30 … :347:3 › … › TC-W6 a row opens the results file: every section in order, with the route's commentary (1.5s)
✓   31 … :446:3 › … › TC-W7 missing parts say not available / not analysed, never 0 (non-F&O file; a partial answer) (1.6s)
✓   32 … :496:3 › … › TC-W8 the file's 404 (no results meeting) and error states; Retry recovers; Scores still from the row (3.9s)
✓   33 … :516:3 › … › TC-W9 list loading and error states; Retry recovers (3.8s)
✓   34 … :536:3 › … › TC-W10 an older list route without fno_track hides the F&O before → after part (875ms)
✓   35 … :545:3 › … › TC-W11 wording on the block: ideas for review, no advice words (775ms)
✓   36 … :560:3 › Results This Week — REAL staging list capture (desktop 1440) › TC-W14 the block renders the real 27 Oct body: F&O order = the fixture's ideas.fno among its F&O rows; no page error (933ms)
✓   37 … :592:3 › … Events › Results week opens the same file › TC-W12 from the row drawer's Results file action and from a row's File button; nothing removed (2.0s)
✓   38 … :622:3 › Results This Week — phone 390 › TC-W13 cards, no horizontal page scroll on the list or the file; the track scrolls inside its own box (1.4s)
```
  (Lines shortened with "…" for the repeated path/describe prefix; full log kept in the session scratchpad, rtw-run5.log.)
- **Bugs the run caught and fixed before this report:** "2 analysises" (plural) in Results sentiment; the track table's last two columns
  were cut off in a 760 px drawer (drawer now 880 px, tighter cells); before/after boxes cramped side by side on a phone (now stacked);
  the expiry note printed twice (shown once, beside the after reading).
- **Screenshots** (networked run, fonts loaded; looked at): 1440 and 390 of the list, the file's top, the result section, the tracker and
  Scores — `rtw-shots2/` in the session scratchpad.

## Data Correctness (staging)
- TC-W14 renders the REAL staging body of `GET /api/desk/results-week?date=2026-10-27` (`e2e/fixtures/results_week_staging_20261027.json`,
  committed earlier with the contract spec): the block's counts and order are checked against that body's own `results` / `ideas`.
- The stock route's REAL body is not rendered here (no JSON capture exists; the route is not deployed). Its field names and value shapes were
  checked against the backend code and the coordinator's staging dry-run printout (MANKIND / BAJAJ-AUTO / HEROMOTOCO / ITCHOTELS in the
  backend report); the MOCK fixtures copy those shapes and sentence formats, not their figures.

## UNVERIFIED
- UNVERIFIED: the screens against the live staging routes — needs backend PR #381 and this PR merged and deployed (frontend image rebuild),
  then a signed-in check of `/v5/app/page/watchlist` and one results file (e.g. MANKIND: before long build-up, after "rollover 92.6 % vs its
  usual 93.6 % (normal)", commentary pre 3 / results 3, sentiment moderately positive 88).
- UNVERIFIED: a REAL `results-stock-v1` body through `readResultsFile` — add a captured staging body as a contract fixture once the route
  is deployed.
- The results booster joins only stocks present on the AI scanner's rows (the scanner reads its top rows + every signalled stock, §4d); a
  results name outside them shows no chip, by design.

## Inputs required from user
- none

## Verdict: PASS
