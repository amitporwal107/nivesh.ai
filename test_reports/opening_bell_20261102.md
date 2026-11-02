# Functionality Verification Report — Opening Bell (morning market video, 5 languages)

- **Branch:** feat/closing-bell-ai-focus (worktree /home/deploy/nivesh-wt-closing-bell)
- **Date:** 2026-11-02 (test cases) — evidence added as it is obtained
- **Author:** Claude (Full Stack Developer + QA + Domain Expert)
- **Environment:** staging app VM (CloudPe), staging desk as the read-only bot, NIDP DaaS, TrueData REST, NSE public pre-open
- **Changed areas:** backend routes/services: no (backend/scripts only) · frontend src: yes (MarketCommentary `?show=opening`,
  editions.ts per show, Homepage Opening Bell card) · tools/closing_bell (pipeline)

## Summary
Owner ask (2 Nov): "create a commentary on market opening bell just like closing one … provide anticipated moves today".
Owner decisions: publish ~9:10 IST after the pre-open; "anticipated moves" = data-based ranges and levels (India VIX
range, option-OI support/resistance, option-implied moves for results-day stocks), never calls; no global cues (not in
the TrueData plan). Same pipeline as the Closing Bell, `--kind opening`, two phases: phase A (~07:30) builds everything
from the previous session's data; phase B (09:08) adds the pre-open and re-renders only the cold open and the pre-open
segment.

## Test Cases (authored before implementation)

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| OB-1 | levels | Max put-OI strike at/below spot = support; max call-OI strike at/above spot = resistance; PCR = ΣPE OI / ΣCE OI; max pain minimises option-holder payout | unit | exact values on a hand-built chain |
| OB-2 | levels | VIX range = close × VIX/100/√365, lo/hi rounded | unit | 23,440.80 × 15.5% / √365 = 190.1 pts |
| OB-3 | levels | Expiry day: ATM straddle (CE+PE close at the strike nearest spot) only when the chain's expiry is the edition date | unit | present on expiry day, absent otherwise |
| OB-4 | implied | Results-today implied move = ATM straddle / spot × 100 for each F&O name due today, nearest expiry named | unit | % and expiry traced |
| OB-5 | pre-open | Indicated Nifty = prev close × Σ w·(IEP/prev) over the 50 constituents (desk weights); dropped if < 45 of 50 found | unit | value + coverage; none when too few |
| OB-6 | pre-open | Stale pre-open (NSE timestamp date ≠ edition date) is refused (hold) unless the test-only flag is set | unit/failure | held, reason names the stale date |
| OB-7 | pre-open | F&O advances/declines, top 3 gap-ups/downs, after-bell filers' and AI-list names' pre-open moves | unit | from NSE rows only |
| OB-8 | script | Every number in all 5 languages is traced to cards (checks.py), required SEBI phrases present in every language, no "picks/target price" | unit | checks ok |
| OB-9 | script | Wording is for the morning ("today's Top 10 ideas", "On Monday, the Nifty closed…"), never "tonight" | unit | no "tonight" in EN text |
| OB-10 | script | Levels framed as ranges priced by the options market, "not forecasts" in every language | unit | phrase present |
| OB-11 | segments | Same segment list in phase A and phase B (pre-open segment present as a placeholder in phase A) | unit | ids equal |
| OB-12 | build | Phase B re-renders only s0 + the pre-open segment; English audio and ticker are built over the whole programme (no music/ticker jump) | integration | media checks pass; durations = timeline |
| OB-13 | build | Closing Bell unchanged: 28 existing unit tests still pass; closing script for the 27 Oct fixture byte-identical before/after | regression | identical |
| OB-14 | publish | Opening editions go to /downloads/opening-bell/<date>/ with their own index.json; closing index untouched | integration | files + index |
| OB-15 | e2e | Dry run on staging for 3 Nov (prev session 2 Nov, stale pre-open allowed by test flag): every desk screen loads as the bot, 5 language videos, checks pass | e2e | DRY RUN ok |
| OB-16 | live | 3 Nov 09:08 phase B publishes by ~09:15; numbers cross-checked vs NSE/warehouse | live | published + cross-check |

Page test cases (added with the page support on 2 Nov ~21:50, before its Playwright run; spec
`frontend-v5/e2e/tests/homepage-market-commentary-opening.spec.ts`, fixtures = real dry-run publish output):

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| OB-17 | page | `/v5/market-commentary?show=opening`: title, player files under /downloads/opening-bell/, headlines, levels line, transcript | e2e | exact files + counts from fixtures |
| OB-18 | page | Show switch moves between the two shows; Closing Bell stays the default (no levels line there) | e2e | URLs + titles |
| OB-19 | page | [hi] language switch keeps `?show=opening`, Hindi video file, Hindi levels line, Hindi transcript | e2e | exact |
| OB-20 | page | No morning edition (404) → morning empty notice, no player | e2e | notice |
| OB-21 | home | Homepage Opening Bell card opens the latest morning edition; hidden when none; Closing Bell card unchanged | e2e | card + link |

## Evidence
(added below as each case runs)

### OB-1 / OB-3 data cross-check against the desk (staging, 2 Nov 2026 21:50 IST)
`cards_open.chain_levels()` on the live NIDP DaaS chain `/fno/NIFTY/chain` (as_of 2026-11-02, expiry 2026-11-03),
command `python3 -c "... cards_open.chain_levels(chain) ..."`, real output:
```
{"spot": 23440.8, "expiry": "2026-11-03", "as_of": "2026-11-02", "sup": 23000.0, "sup_oi": 14450085.0, "res": 24000.0, "res_oi": 12449840.0, "pcr": 1.67, "max_pain": 23250.0, "atm": 23450.0, "straddle": 179.45, "straddle_pct": 0.8}
```
The desk's own NIFTY card (F&O lab › NIFTY & BANKNIFTY, recorded as the bot in the same minute) reads: "Spot sits between
the 23,000 put wall and the 24,000 call wall", Put-call ratio · OI 1.67, Max pain 23,250, "expected move … ±179.45".
All five figures agree (support, resistance, PCR, max pain, ATM straddle). **PASS** (independent implementations agree).

### Recorder: levels scene on the live desk (o3)
`rec.py o3` as the bot (15-min session, revoked: `{"revoked": 1}`): first run missed (F&O lab is far down the Smart
Money page; the OI panel lists strikes near the money only). Fixed: jump to `desk-fno-indices`, point at the shown
strike nearest each level (logged when not exact). Second run: `o3: 397 frames, misses 0`; frames show the NIFTY card,
then the OI bars. **PASS**

### OB-15 staging dry run for 3 Nov (2 Nov 23:17 – 3 Nov 00:15 IST) — three runs, two real bugs found and fixed
Command (scratch roots, not published, test-only stale pre-open):
`sudo CB_MIN_FREE_GB=7 CB_ROOT_OPEN=<scratch>/ob/root_dry CB_ROOT=<scratch>/cb_tonight/root CB_BACKEND_SCRIPT=/tmp/closing_bell_open.py python3 tools/closing_bell/pipeline.py --kind opening --phase both --date 2026-11-03 --allow-stale-preopen --dry-run --keep-work`

Run 1 — **FAILED** in phase A (real bug: the timeline probe globbed `s*_*.mp3`, so the morning's o1..o5 clips were never measured):
```
2026-11-02 23:18:31 script checks ok: 346 numbers
2026-11-02 23:20:49 RESULT FAILED 2026-11-03: phase A timeline: ...
KeyError: 'en/o1_0'
EXIT 2
```
Run 2 — **HELD** by the media check (o5 = the results week with nothing to point at on the sign-off beats: a still page):
```
2026-11-02 23:36:47 phase A ok in 901s
2026-11-02 23:36:48 script checks ok: 468 numbers
2026-11-02 23:46:22 RESULT HELD 2026-11-03: o5: only 4 frames for 17.0 s
EXIT 3
```
Run 2 also showed `results_today` empty: the desk's `/api/desk/results-week?date=2026-11-03` answers **422** the evening
before (future date) and can answer 503 before its first live build in the morning. The previous session's stored week
(already in the bundle) lists 3 Nov: 178 companies, F&O: BAJAJFINSV, LUPIN, SBIN, SOLARINDS.

Fixes (commit fcd1c40b + the phase-drift guard below): timeline glob `*_*.mp3`; results fallback to the previous session's
stored week, and a named gap when neither has the day; `act_o5` glides the cursor on beats with no focus; `trim_work`
(publish left ~180 MB of work videos per edition); alias "Solar Industries India" → "Solar Industries" (an alias is final;
closing cards for 27 Oct differ only in `movers.Nifty 100.sectors[6].up.name 'Solar' -> 'Solar Industries'`); implied-move
wording "results included" (a stock's nearest expiry is monthly); `CB_MIN_FREE_GB` (floor 7, default 8).

Run 3 — **DRY RUN ok**:
```
2026-11-02 23:51:10 collect (previous session + chains + MCX)
2026-11-02 23:51:31 script checks ok: 370 numbers
2026-11-03 00:02:38 bot session revoked: {"revoked": 1}
2026-11-03 00:06:58 phase A ok in 962s
2026-11-03 00:06:58 pre-open: {"timestamp": "02-Nov-2026 09:09:31", "fo": 218, "all": 2411, "adv": 152, "dec": 45, "stale": true}
2026-11-03 00:06:59 script checks ok: 492 numbers
2026-11-03 00:10:08 final (ticker + audio over the whole programme)
2026-11-03 00:15:33 DRY RUN ok in 1477s; not published.
EXIT 0
```
Footage per scene (raw/<sid>/index.json): o1 285 frames / 54.25 s · o2 752 / 95.0 · o3 340 / 83.75 · o4 1010 / 129.25 ·
o5 515 / 24.25 (was 4); no warm errors. `checks_media.json` `{"ok": true, "fails": []}`. Media per language:
```
media.json    {"duration":412.25,"width":1920,"height":1080,"has_audio":true,"lufs":-14.1,"timeline_total":412.25}
media_hi.json {"duration":412.3, ... "lufs":-14.0,"timeline_total":412.25}
media_ta.json {"duration":412.3, ... "lufs":-14.2,"timeline_total":412.25}
media_mr.json {"duration":412.3, ... "lufs":-14.1,"timeline_total":412.25}
media_gu.json {"duration":412.3, ... "lufs":-14.1,"timeline_total":412.25}
```
Frame sheet of the English video (1 frame / 34 s) viewed: headlines, previous session box, pre-open box (23,637 +0.84%),
ranges & levels over the desk's F&O OI bars, AI lists, results calendar; ticker on every frame. Not published:
`ls /opt/nivesh-staging/downloads/opening-bell` → "No such file or directory". **PASS**

Data cross-checks on this run (OB-2, OB-4, OB-5, independent recomputation from the raw inputs):
- VIX range: 23,440.80 × 15.5 / 100 / √365 = 190.2 pts → cards `pts 190, lo 23,251, hi 23,631`.
- Indicated Nifty from the raw NSE rows × desk weights: `cover 50 of 50 ratio 1.00836 indicated 23637 pct 0.84` = cards
  `{'ind': 23637, 'pct': 0.84, 'cover': 50, 'of': 50}` (stale 2 Nov pre-open, test flag only).
- Implied moves (ATM straddle / spot, 23 Nov expiry): SBIN 49.55 / 987.0 = 5.0%, BAJAJFINSV 88.6 / 1,691.49 = 5.2%,
  SOLARINDS 1,475.95 / 19,433.89 = 7.6%.
- Previous session vs warehouse: `nidp.index_eod` 2026-11-02 Nifty 50 23,440.80 +1.68%, Smallcap 250 16,991.00 +1.35%,
  India VIX 15.50 +1.29%; `nidp.fii_dii_flows` FII 3,114.68 / DII −392.20 Cr = cards (FII +₹3,115 Cr, DII −₹392 Cr).
- MCX crude 9,116 −8.3% in this run is a **live bar** (collected 23:22 while MCX trades to 23:55); the 06:30 run reads the
  settled bar. Not a code fault; noted so the figure is not quoted.

### OB-12 phase-drift guard (added after run 3)
Phase B re-voices only s0 + o2; the rest keep their phase-A voices, so phase B now holds if their text changed (a deploy
between 06:30 and 09:08 could do that). On the real 3 Nov scripts (phase A without pre-open, re-generated from the run-3
bundle, vs run 3's phase B script): `phase_a_drift → []`. Unit test `test_phase_b_holds_when_reused_text_changed`.

### OB-8 … OB-14 unit tests
`python3 -m unittest discover -s tools/closing_bell/tests` → `Ran 46 tests ... OK` (28 closing + trim test, 17 opening).
New wording re-checked on run 3's real bundle: `checks.py script` → `{"ok": true, "numbers_checked": 370, "traced": 149, "fails": [], "data_fails": []}`.

### OB-17 … OB-21 Playwright (frontend)
Fixtures `frontend-v5/e2e/fixtures/opening-bell/` = `publish.py` output of run 3 into a scratch destination
(index.json + transcript*.json, 6 sections / 35 cues). Build + run in `mcr.microsoft.com/playwright:v1.47.0-jammy`,
`--network none`, `vite build` + `vite preview` (VITE_BASE=/v5/), `npx playwright test --project=unauthenticated` on the
new spec plus both existing commentary specs (regression):
```
  ✓  16 … homepage-market-commentary-opening.spec.ts:42:3 › OB-17 ?show=opening: title, player files, headlines, levels disclaimer, transcript (736ms)
  ✓  17 … homepage-market-commentary-opening.spec.ts:62:3 › OB-18 the show switch moves between the two shows; the Closing Bell stays the default (946ms)
  ✓  18 … homepage-market-commentary-opening.spec.ts:76:3 › OB-19 [hi] the language switch keeps the morning show and shows the Hindi levels line (895ms)
  ✓  19 … homepage-market-commentary-opening.spec.ts:87:3 › OB-20 no morning edition yet → the morning empty notice, no player (690ms)
  ✓  20 … homepage-market-commentary-opening.spec.ts:94:3 › OB-21 homepage: the Opening Bell card opens the latest morning edition; hidden when none (1.2s)
  -   4 … homepage-market-commentary-daily.spec.ts:95:3 › TC-15 the real built edition plays for its published length, with audio
  -  14 … homepage-market-commentary-daily.spec.ts:185:3 › TC-23 [hi] the real Hindi edition plays with audio
  2 skipped
  27 passed (19.8s)
```
(TC-15 / TC-23 skip by design without network; they play the real staging media.) **PASS**

### Not covered by this verdict
- **OB-16 live** (3 Nov 09:08 phase B + publish): runs tomorrow from `cb_tonight/run_open_3nov_v2.sh`; reported separately.
  Measured phase B time is ~8.5 min (00:06:58 → 00:15:33), so the edition lands about **09:17**, just after the 9:15 open.
- Native-speaker review of the TA/MR/GU wording (owner action).

Scope of the verdict below: OB-1 … OB-15 and OB-17 … OB-21 (code, staging dry run, page).

## Verdict: PASS
