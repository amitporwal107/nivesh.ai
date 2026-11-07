# Scoring v2.1 + wider universe — test cases (package 5, parts A and C)

Written before the code (7 Nov 2026). Continues the numbering of docs/autodesk/TESTCASES.md "Scoring v2" (AD-SC-01..15); kept in
this file so parallel work does not collide on TESTCASES.md. Part B (shadow scores on Scanner / Trace / Day) is deferred.
Types: U unit · I integration (stub market data, TEST DATA — not real market data) · E e2e (Playwright, mocked API,
`// MOCK — not real data`) · S study / real-data run (read-only, throwaway DB).

| ID | T | Case | Expected |
|---|---|---|---|
| AD-SC-16 | U | Registry lists v2.1 | `v21-positional` is SHADOW, same weights as v2 (45/30/15/10, sum 100); v1 still the only ACTIVE; default shadow list = v2-positional + v21-positional; `AUTODESK_SCORING_SHADOW=""` turns both off; `=v2-positional` runs only v2 |
| AD-SC-17 | U | v2.1 moves setup A to context | a bar where setup A fires: v2 lists SETUP_A_ACCUMULATION in `signals`; v2.1 lists it in `context_signals`, not `signals`, and its signal-quality points come from the remaining entry signals only (never more than v2's) |
| AD-SC-18 | U | v2.1 has no bearish penalty | a bullish candidate with a bearish warning: v2 total = v2.1 total − 10 (same inputs); v2.1 still lists the warning in `warnings`; no `bearish_warning` component in v2.1 |
| AD-SC-19 | U | v2 is unchanged | the v2 score, band, components and rules string (`v2-positional-2026-11-05`) are identical before/after the refactor on the AD-SC-06..10 series; v2.1 rules string is version-pinned (`v21-positional-2026-11-07`) and different |
| AD-SC-20 | U | v2.1 no look-ahead | score at bar t from the full series equals the score from the series cut at t (as AD-SC-05) |
| AD-SC-21 | I | Both shadow scores per signal | with default shadow settings every stock signal carries `shadow_scores` = [v2-positional, v21-positional], both `status=SHADOW`; index signals carry none |
| AD-SC-22 | I | v1 identical with 0, 1 or 2 shadows | v1 `signal_score`, breakdown, zone, targets, selection order identical with shadow "", "v2-positional", and both |
| AD-SC-23 | I | Scan report blocks | `shadow` keeps the v2 block shape (version, rules, candidates…) and gains `shadow.versions = {version: block}` with one block per running version; a v2.1-only run puts v2.1 in the top-level block; old readers (no `versions` key) still parse |
| AD-SC-24 | I | Shadow failure is isolated | one version's scorer raising is recorded under errors for that version; v1 signals and the other version are unchanged |
| AD-SC-25 | I | Features computed once per stock | scoring two versions reads bars once and builds indicator features once per stock (call count = stocks, not 2×stocks) |
| AD-SC-26 | I | Universe NIFTY500 / TOTAL_MARKET | with `universe=NIFTY500` the scan covers that index's members (stub constituents), `universe_size` = member count, report `universe` names it; a member with no bars is listed in suppressed with a reason |
| AD-SC-27 | I | Non-F&O stocks scan as cash only | in a named universe a non-F&O member can give BREAKOUT / TREND_CONTINUATION (bullish, CASH, `fno_eligible=false`); a bearish setup on it yields no signal; an F&O member keeps futures segments |
| AD-SC-28 | I | FNO default unchanged | `universe=FNO` (and absent) scans exactly the F&O list as before; index futures (NIFTY…) only in FNO; named universes exclude them |
| AD-SC-29 | I | Unknown universe is refused | `universe=BOGUS` fails the scan task with a clear error; it never silently scans F&O under another name |
| AD-SC-30 | I | Constituents unavailable | the constituents read fails → scan fails visibly (no silent fallback to F&O) |
| AD-SC-31 | I | Cap lifted only for named universes | `SimulationConfig(universe=TOTAL_MARKET)` with no symbols creates (754-style large universe); explicit `symbols` > 50 still refused |
| AD-SC-32 | I | Survivorship caveat | results of a NIFTY500 / TOTAL_MARKET simulation list the "today's members … survivorship bias" limitation; an FNO simulation does not; an explicit symbols list does not |
| AD-SC-33 | E | Studio New simulation chips | `setup-uni-FNO`, `setup-uni-NIFTY500`, `setup-uni-TOTAL_MARKET`, `setup-uni-SYMBOLS` are enabled; picking NIFTY500 posts `universe: "NIFTY500"` with no symbols; the survivorship caveat text is shown for index universes and hidden for F&O |
| AD-SC-34 | E | Request contract | the posted simulation body for each universe matches frontend-v5/e2e/fixtures/autodesk/requests/*.json and backend `test_ui_request_contracts.py` accepts it |
| AD-SC-35 | S | TOTAL_MARKET real-data replay (1–2 sessions, throwaway DB) | signal counts, both shadow versions recorded, error_count, scan seconds vs the F&O scan (expect ≈ 3×); NOT deployed |
| AD-SC-36 | S | Narrative vocabulary | no new agent-written text contains buy, sell, stop loss, SL, target, entry, exit, accumulate, book profit, upside, price target, recommend, pick (AD-92) |

## Part B — shadow scores in the desk web app (written before the code, 7 Nov 2026)
Shadow scores live in the stored signal body (`body.shadow_scores`, a list of ShadowScore: version, score, band, tier, primary_signal,
signals, context_signals, warnings, components, reasons). Every shadow label reads "shadow — not used for selection". Fixtures are
`// MOCK — not real data`; no sample scores are drawn when a signal has none.

| ID | T | Case | Expected |
|---|---|---|---|
| AD-SC-37 | E | Scanner row chip | each signal row whose body has `shadow_scores` shows one chip per version in version order, text `v2 77.5 · Strong` / `v2.1 77.5 · Strong`, next to the v1 score; the v1 score, rank and order are unchanged; a signal with no shadow_scores (index signal, older row) shows no chip |
| AD-SC-38 | E | Scanner expanded row | opening a row shows a "Shadow scoring — not used for selection" section: per version the score, band, tier, primary signal, entry/context signals, warnings, and the component list (dimension, points of weight, reason); v2.1 shows no bearish_warning component; a version with `score: null` shows its `reasons` ("not scored") |
| AD-SC-39 | E | Scanner without shadow data | rows from before package 5 (no `shadow_scores`) open as today: no shadow section content except one line "No shadow score stored with this signal."; no console errors |
| AD-SC-40 | E | Phone cards | at 390×844 the chip and the section render in the card, no horizontal overflow |
| AD-SC-41 | E | Studio Agent trace | the AI Trader signal step's payload gains one row per shadow version (`shadow v2-positional · not used for selection`, value `77.5 · Strong · TIER_1 · primary RS_BREAKOUT`); steps for signals without shadow scores are unchanged |
| AD-SC-42 | E | Studio Trading day | Day shows no per-signal score today, so nothing is added there (recorded, not skipped) |
| AD-SC-43 | E | Existing specs | all existing scanner / trace / day specs still pass unchanged (v1 is untouched) |
