# Desk audit wave 1: test cases (written before the fixes)

Source: `docs/desk_redesign_20261027/AUDIT_live_vs_design_20261028.md`, chunks **F1**, **B1** and **B3**.
Branch: `fix/desk-audit-wave1` (from `origin/dev` 48556220).

**Owner rules that apply:**
- Wording says "ideas" or "candidates", never "pick(s)", "recommended" or "suggested".
- Sizes come from the risk service's `account_size`.
- The minimum reward : risk is 1.5. Paper only.

**Out of scope:** Chart Analysis › Live chart and Strategy Lab › Build a trade. Other agents are rebuilding those.

## Frontend: Playwright with mocked APIs (`e2e/tests/copilot-app-desk-audit-wave1.spec.ts`)

| ID | View | Scenario | Expected |
|---|---|---|---|
| W-1 | AI Scanner › Ranked candidates | A stock that only the scanner's picks route has (stage EARLY_BREAKOUT) | The setup reads "Scanner idea · early breakout". No visible text in the scanner list contains "pick". |
| W-2 | AI Scanner › Signal library (Chartink) | The Chartink candidates list, with one stock and its strategies | The title, subtitle, Wait list and footnote use "candidates" or "ideas". No visible text in the section contains "pick". |
| W-3 | Market Overview › idea drawer ("Full card ›") | The drawer for a cash idea whose scanner setup is known | The subtitle is "name · sector · Near breakout · scan of …". It never contains "[object Object]". |
| W-4 | Market Overview › index strip | `/api/markets/home` gives NIFTY a value with `change` and `change_pct` null | The change line gives the reason ("Day change not reported…"), not "— (—)". A tile that has a change still shows "+152.30 (+0.68%)". |
| W-5 | Market Overview › idea drawer › Evidence | The volume evidence text has raw floats ("1.2966179010676246x … 1734.5622804300003 Cr") and the regime text names `macro_engine.classify_desk_regime` | It reads "1.30x … 1,734.56 Cr", and no module name, route or file path is shown. |
| W-6 | Ranked candidates, Market Overview, Risk Desk | Sources line, partial-load notes, index error line | No "GET /api", no "services/…", no ".py" and no ".decide" appears in the page text. |
| W-7 | Market Desk › Smart Money, Copilot dock, Market Intelligence | The views render | No leftover section numbers ("06 · Smart Money Movement", "04 · AI Event intelligence", "06 · Conversational intelligence"). Smart Money's F&O section has no "Options & futures lab · NSE F&O" eyebrow and no "Build, test and understand option trades." headline. |
| W-8 | Risk Desk › Decision log | One decision's reasons hold the same message twice, once as `target_required` and once as `TARGET_REQUIRED` | The message is shown once. |
| W-9a | Market Overview › Strategy that fits | The preferred covered call has `account_size.status = not_sizable` | The line says "1 lot, not sized to your account" and gives the risk service's reason. |
| W-9b | Market Overview › Strategy that fits | The preferred cash strategy has `account_size.status = sized`, 34 shares | The line says "34 shares, sized to your account", not the plan's 1-share legs. |
| W-9c | Market Overview › idea drawer | The cash plan's `account_size` is sized (34 shares), and its `risk_flags` hold "Sizing is incomplete … 1 share", "Reward : risk is judged before costs here…" and "Sizing needs …" | None of the three is shown under Other flags. Another flag on the same plan is still shown. |
| W-10 | Signal library › a Chartink candidate's strategies | One strategy is a `candidate` at 0.19 : 1 net. Another is a `candidate` at 1.64 : 1. | The first shows "Below your 1.5 minimum", not "Viable". The second shows "Viable". The header counts "1 viable of 2". |

## Backend: pytest, no network

`backend/tests/test_desk_audit_wave1_b1.py` and `backend/tests/test_desk_audit_wave1_b3.py` are both in the CI allowlist.

| ID | Area | Scenario | Expected |
|---|---|---|---|
| B1-1 … B1-9 | `/api/markets/ownership/reaction` (data platform) and `GET /api/desk/idea-scorecard` | See `test_desk_audit_wave1_b1.py` | The coverage SQL binds no unused parameter, so there is no 500 from the data platform and no 502 from the app. The scorecard opens only `result.json`, lists the three study docs as references, and never returns 500. |
| B3-1 | `GET /api/markets/home` | The live snapshot gives NIFTY a value with `change_pct` null. The tape has an end-of-day value and change. | The tile keeps the tape's value, change and date. It never shows a value with a null change. This was the root cause of "— (—)". |
| B3-2 | `GET /api/markets/home` | The live snapshot has both a value and a change | It still replaces the tape tile, so this case does not regress. |
| B3-3 | `ideas.build_ideas(…, sizer=)` | Ideas with a preferred covered call, a preferred cash strategy, and no preferred strategy | `account_size` is attached to the preferred strategy only. The sizer receives that strategy's own TradePlan. It is never called for an idea with no preferred strategy. A sizer that raises gives `status: unavailable`, and the ideas still return. |
| B3-4 | `ideas.build_ideas` without a sizer (the AI-watchlist job) | — | No `account_size` key is added, so the stored lists keep their shape. |
| B3-5 | `ideas.strategies_of` | A candidate at 0.19 net, a candidate at 1.64 net, a candidate with net null and gross 2.0, and a no_trade | `min_reward_risk` is 1.5 and `meets_min_reward_risk` is false, true, true and None, in that order. |
| B3-6 | Plain words | `plan_sizing.BASIS` and the `/api/risk/status` `scope` | Neither contains "services/", ".py" or ".decide". |
| B3-7 | `POST /api/desk/strategy/ideas` (route) | `build_ideas` is stubbed and `plan_sizing.size_for` is stubbed | The route passes a sizer that calls `plan_sizing.size_for(db, tp, user_id)` for the signed-in user. |

## Runs (real output goes in `desk_audit_wave1_20261028.md`)
- `tsc` and the production build.
- The new spec, plus desk-shell, desk-market-overview, desk-trade-desk, desk-market-desk, desk-risk-desk, desk-top10, desk-decision-cards, desk-scanner and desk-chartink*. `PWEXTRA=--workers=2`. A failure counts only if it repeats.
- Backend: the new files, then the full CI allowlist, in Docker with `--network none`.
- Staging: read-only probes only.
