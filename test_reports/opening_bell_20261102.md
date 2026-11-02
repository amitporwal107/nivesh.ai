# Functionality Verification Report — Opening Bell (morning market video, 5 languages)

- **Branch:** feat/closing-bell-ai-focus (worktree /home/deploy/nivesh-wt-closing-bell)
- **Date:** 2026-11-02 (test cases) — evidence added as it is obtained
- **Author:** Claude (Full Stack Developer + QA + Domain Expert)
- **Environment:** staging app VM (CloudPe), staging desk as the read-only bot, NIDP DaaS, TrueData REST, NSE public pre-open
- **Changed areas:** backend routes/services: no (backend/scripts only) · frontend src: no (page support is a follow-up)

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
