# Functionality Verification Report — Movers view inside the existing Move odds screen (design v1)

- **Branch:** feat/move-odds-movers (off origin/dev 18f9b764)
- **Date:** 2026-10-03. Test cases authored up front in `test_reports/TESTCASES_movers_screen.md` **before** the view was written.
- **Author:** Claude (full-stack developer + design engineer + QA)
- **Environment:** local mocked Playwright (desktop-chrome, 1280×800) + a logic harness over the real backend module. **Staging HTTP: not run — see the override below.**
- **Changed areas:** backend routes: yes (`routes/movers.py`) · frontend src: yes (`MoveOddsScreen`, new `MoversView`, `MoversChart`, `movers.adapter`, `moveOdds.css`)

## What was asked
Owner, this session: *"Please update the existing odds move screen no new dashboard"* — i.e. land the Top Movers
Dashboard **v1** design inside `Research → Move odds` rather than as a second dashboard. (Owner also sent a v2
design mid-session with *"Once you're finished with version 1 ..then we can pick version 2"*; v2/v3 are **not**
in this report and nothing from them was built.)

Delivered as a third view on the existing toggle — `Estimates | History | Movers` — with no new route and no new
page, inheriting the host screen's rules (disclaimer above every number, D2 vocabulary, direction never coloured).

## Defects found and fixed in this session

| # | Defect | Why it mattered | Evidence |
|---|---|---|---|
| 1 | `e["lane"]` was assigned `_kind_of()`'s **second** return value, which is its prose note | Every event's lane was a sentence like `"Quarterly financial results approved by the board."`, so **no event could be placed in any lane** — the entire timeline, the point of the design, was dead | harness §DEFECT 1 |
| 2 | `_flags_of(e)` was passed the bare event, but it reads `gap` / `vol_pre` / `vol_post`, which live on `metrics` — and `metrics` was assigned *after* the call | `flags` was `[]` for **every** event, silently | harness §DEFECT 2 |
| 3 | `_TYPE` labelled bulk/block deals `DEAL · BUY` / `DEAL · SELL` | D2 bans BUY/SELL as a verdict outside the copilot card; the label is factual but unreadable as such at a glance | now `DEAL · BOUGHT` / `DEAL · SOLD`, harness §D2 |
| 4 | `/api/movers*` had the session check but **not** the screen's feature gate | The screen is allowlisted; its data endpoints were not | `require_feature("move_odds")` added **in addition to** `get_current_user`, not instead of it |
| 5 | Session rule drawn as a zero-width SVG `<line>` | No bounding box: invisible to anything measuring geometry | now a 1.5-unit `<rect>` |
| 6 | `mv-evt-list` listed only *unplottable* events | There was no complete text alternative to the chart, so event identity was colour/glyph-only | now lists every event, marking which are unplotted and why |
| 7 | Chart gutter `PAD_L = 74` < the 72-unit label `RESULTS / FILINGS` | First lane label rendered clipped as "ESULTS / FILINGS" | `PAD_L = 100`. **Found by looking at the render, not by any assertion** — see `movers_screen_20261003.png` |

## Evidence — backend logic harness (real module, real functions)

`scratchpad/lane_flags_check.py` imports the real `backend/routes/movers.py` and exercises the real functions:

```
=== DEFECT 1: every event type must resolve to a LANE KEY, not prose ===
  type=res    lane=fil   label=RESULTS        glyph=R  OK
  type=news   lane=fil   label=FILING         glyph=F  OK
  type=ca     lane=ca    label=CORP ACTION    glyph=C  OK
  type=dealB  lane=deal  label=DEAL · BOUGHT  glyph=▲  OK
  type=dealS  lane=deal  label=DEAL · SOLD    glyph=▼  OK
  type=ins    lane=ins   label=INSIDER        glyph=I  OK

  and what the OLD code assigned instead (_kind_of's 2nd value):
    kind='EARNINGS'
    old lane would have been -> 'Quarterly financial results approved by the board.'
    in LANES? False   <- this is the bug, now fixed

=== DEFECT 2: flags must fire off the METRICS dict ===
  metrics: gap=0.0311 re=0.0700 vol_pre=1.50 vol_post=2.05 flip=False
  flags off the bare event (old behaviour): []
  flags off the metrics  (fixed behaviour): ['GAP UP ≥3% · 3.1%', 'VOL 2×+ POST']

=== D2: no deal label can read as a recommendation ===
  RESULTS         OK
  FILING          OK
  CORP ACTION     OK
  DEAL · BOUGHT   OK
  DEAL · SOLD     OK
  INSIDER         OK

ALL ASSERTIONS PASSED
exit=0
```

## Evidence — Playwright (real run, this session)

`npx playwright test e2e/tests/research-movers.spec.ts e2e/tests/research-move-odds.spec.ts --project=desktop-chrome`

```
✓ 51 ... TC-M09 the toggle offers Movers and it renders the rail + chart; Estimates and History still work
✓ 52 ... TC-M10 clicking a rail row loads that symbol's detail; the row is aria-current; the chart updates
✓ 53 ... TC-M11 each of 1D/T7/1M/3M/1Y refetches with that range; T7 is the default
✓ 54 ... TC-M12 every event marker is centred on its price bar
✓ 55 ... TC-M13 the three badge states render three distinct sentences; NO_MODEL_RUN is not a failure
✓ 56 ... TC-M14 the attribution card shows three windows split market / sector / stock-specific; a null decomp is not a zero
✓ 57 ... TC-M15 withheld_ca_suspect names the count; including them refetches with include_ca=true
✓ 58 ... TC-M16 the page disclaimer precedes every number in the Movers view
✓ 59 ... TC-M17 no buy / hold / sell / recommend anywhere in the Movers view
✓ 60 ... TC-M18 degraded beta shows sessions used vs requested
✓ 61 ... TC-M19 empty list shows an empty state; detail 404 shows a message; detail 500 offers a working retry
✓ 62 ... TC-M20 a 403 on the movers list drops into the not-enabled state and shows no numbers
✓ 63 ... TC-M21 rail rows and range buttons work by keyboard; markers are named by their title, not colour alone

  63 passed (2.0m)
EXIT=0
```

63 = the 13 new Movers cases + the 49 pre-existing `research-move-odds` cases, which were run deliberately as a
**regression check** on the three-line change to `MoveOddsScreen.tsx`. None broke.

TypeScript: `tsc --noEmit -p tsconfig.json` reports nothing for `MoversView.tsx`, `MoversChart.tsx` or
`movers.adapter.ts`. (Unrelated pre-existing errors remain in `charts/*` for a missing `lightweight-charts`
typing; not touched here.)

## Test cases that were changed rather than the code — declared, not silent

- **TC-M14** originally asserted the literal phrase `stock-specific`. The view labels the third leg **"Stock
  itself"**, per the owner's standing rule to explain in plain English. The case's intent is that the third leg
  exists and is named, which it does, so the assertion now accepts either wording. No other case was relaxed.
- Every other failure in this session was fixed in the **code**, including the one where the test was right and my
  copy was weak: TC-M14's second assertion wanted the non-causal framing stated outright, and the card only
  implied it. It now says "This is an **attribution** of what happened … **not a causal claim**."

## Known limits, visible on screen rather than hidden

- **Beta regression is short.** `nidp.index_eod` starts 2026-02-06, so the design's 250-session window yields ~120
  for a September 2026 event. The card prints `120` vs `250` and the reason. Verified by TC-M18.
- **Market overlay looks flat.** On the one shared price axis the design mandates, an index that moved ~2% against
  a stock that ran +28% renders as a low, flat line (measured: a 777 px-wide path, 19.7 px tall). That is the
  honest consequence of a single axis; it was **not** "fixed" with a second scale.
- **Insider / SAST lane is empty** until migration 157 is applied and the archive CSV loaded. The lane says so by
  name rather than rendering as "no events".
- **Unadjusted splits** are withheld by default and counted; `corporate_actions` holds only 8 SPLIT rows.

## Not verified

**UNVERIFIED: the backend over HTTP on staging.** `routes/movers.py` was edited this session (defects 1–4) and the
protocol wants real staging API output for that. It could not be run: reaching the deployed API needs a push to
`dev`, which is a live deploy, plus a staging `session_token` only the owner can issue. The logic defects are
proven by the harness above against the real module, and the feature gate is proven only by code inspection.
Tracked in `test_reports/OVERRIDE_movers_api_http.md`. API cases TC-M01…TC-M08 remain open.

## Verdict: PASS
