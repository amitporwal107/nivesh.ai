# Top Movers — live staging verification (2026-10-03)

Commit under test: `e9decc18` on `dev` (staging redeploys from dev). Data: real staging NIDP, window 2026-09-01..30.
Session: a real staging `session_token` supplied by the owner (not stored here).

## Real findings from the live run (each one invisible to the mocked tests)
| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | Every `/api/movers*` route 500: `relation "nidp.tpd_runs" does not exist` — SQL ran on the APP db | backend log | SQL moved to DaaS router; app route is a proxy (`4c6505b4`) |
| 2 | asyncpg-only: `$2 - 10` inferred integer; unused `$1` in the odds query | real-DB run: `date >= integer`, `could not determine data type of parameter $1` | `::date` casts, renumbered (`4c6505b4`) |
| 3 | Detail panel "unexpected response shape": `impact_score` is a label (`low/medium/high`), schema said number | zod issues on the live JSON | schema accepts string (`4732fc74`) |
| 4 | Every event marker off-chart: `bar_index` 234..242 on a 10-bar chart | live JSON | index relative to plotted slice (`e9decc18`) |

## Live API (curl, real cookie) — all 200
`/api/movers` 3.2 s (100 movers, 10 CA-suspect withheld) · `/calibration` 0.6 s (population 8,972; over-prediction 0.853) ·
`/flag-lift` 0.8 s (7,436 rows; gap2/gap3 WEAK, vol2/vol3/flip/leak/d1 DECORATION) · `/flagged` 0.2 s (1 of 7) ·
`/ATALREAL?session=2026-09-08` 0.3 s (10 bars, 14 events all placed after fix) · `/ATALREAL/analysis` 0.2 s.
Error paths: no cookie 401 · to<from 400 · window>400d 400 · unknown symbol 404 · bad head 422 · bad direction 422.
All six responses validate against the frontend zod schemas (ListC, DetailC, AnalysisC, FlaggedC, CalibrationC, FlagLiftC).

## Live UI (Playwright against https://staging.niveshcopilot.com:8443)
`movers.live.spec.ts`: 1 passed. 100 rail rows, 0 detail errors, 0 non-200 `/api/movers*` responses, 0 page errors;
chart (10 candles), volume, 5 lanes, session line, odds lane, attribution, regression, calibration, flag-lift all present.
Screenshot: `movers_live_20261003.png`. Mocked suites: 24 passed. pytest: 52 passed.

## NOT verified (so this report carries no PASS verdict)
- **403 for a non-allowlisted user** on the live path — no second account available. Covered only by the mocked TC-M20.
- **Design fidelity** vs `Top Movers Dashboard - All Versions (1).html` v4 (byte-identical to the zip's v4): header headline + 3 stat
  tiles, Copilot event-analysis panel, event & deal log table, "Odds move model" side panel are not built as designed; the flag-lift
  is a table not the per-decile strip. Calibration x-axis labels overlap. The insider note exposes an internal script path.
- Full TC-M01..M08 / TC-V01..V13 matrix was not re-walked case by case against live; the above is a spot-check of the same behaviours.
- Data only: ranking against the owner's real top-movers list is still outstanding.

---

# Addendum: the v4 design port, verified live (commit `4e73bb15` on dev, staging)

The Movers view was rebuilt region by region to the owner's v4 design (`Top Movers Dashboard - All Versions (1).html`; its v4 is byte-identical
to the zip's v4, SHA `ff19f87033c0`): top bar, rail, hero, chart, market & sector sensitivity, Copilot event analysis, flag lift, event & deal log,
odds-model panel. Screenshot of the live page: `movers_v4_live_20261003.png`.

## Live evidence (staging, real cookie, window 2026-09-01..30)
- Live Playwright (`movers.live.spec.ts`, temporary, not committed): **1 passed**. 100 rail rows (91 with company names), all `/api/movers*` responses 200
  (list, detail, analysis, calibration, flag-lift, flagged), **0 page errors, 0 console errors**, 0 detail errors. Pinning an event works live
  (`aria-pressed=true`, `/analysis` refetch); switching to Flagged mode works (1 row: RATNAVEER).
- API additions verified over HTTP: flag-lift returns `by_decile` x10 per flag + `decile_base`; list/detail/flagged carry `name` (sector_master; null for ETFs);
  detail carries `move_day` (ATALREAL: vol_pre 1.25, vol_post 0.24, DOWN, net -0.628%, flags GAP DN, LEAK) — the Copilot card shows VOL PRE 1.3x / VOL POST 0.2x, no 'needs 25 sessions'.
- Local: tsc clean; Playwright 36 passed (mocked, real-shaped data: existing suites updated + 12 new TC-U01..U12); pytest 52 passed; real-DB run of the DaaS router.

## Defects found by the QA agents and fixed (each invisible to the earlier static renders)
chart header card covering candles; pin did not drive the header; Escape did not unpin; markers spilled over the lane label; sub-rupee axis labels repeated;
edge pills clipped; internal script path shown in the insider lane; calibration error had no retry (TC-U11); top bar 62px vs 58px; rail heading wrapped;
unicode minus vs hyphen; unpadded date; chart collapsed to 14px at 390px (layout now stacks below 900px; sensitivity card scrolls inside itself).

## Still NOT verified / known differences (so there is no PASS verdict)
- 403 for a non-allowlisted user on the live path (no second account). Mocked TC-M20 only.
- Not compared pixel-for-pixel on the live page: the fidelity diff was done at 1440px on an in-app render with the design's own fonts, with real-shaped mocks.
- Rail: 9 of 100 movers have no company name (ETFs etc. are not in nidp.sector_master); they show turnover instead.
- Flag lift: no focus-event chip / ring (our card is window-wide). Thin cells (<5 firings) are faded, which the design does not do.
- Chart is ~30px taller than the design (extra `<details>` event table) and is SVG, not canvas. The default header card still sits over the left-most candles, as in the design.
- The host page caps the view at 1272px, so the main column is 972px at a 1440px window (design: 1092px).
- The date-window controls strip is not in the design (the design is fixed to one month).
- Owner's real top-movers list comparison still outstanding.
