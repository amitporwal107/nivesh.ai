# Paper Trading v2 — UI builder B test cases (03 Capital allocation · 04 Portfolio risk · 05 Real-time P&L)

Spec: `docs/scanner_paper_trading/UI_DESIGN_V2.md` §2.03, §2.04, §2.05, §3, §5, §6, §7.
Code: `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/paper/{Allocation,Risk,Pnl,policy,b-parts,api-b}.tsx|ts`.
Playwright: `frontend-v5/e2e/tests/copilot-app-desk-paper-v2-b.spec.ts` (every body `// MOCK — not real data`, shapes per §7
and the existing routes read from code), plus the reworked `copilot-app-desk-pnl.spec.ts` and `copilot-app-desk-pnl-exits.spec.ts`.
Real-body render against staging: the integrator's (SPT_REAL_DIR pattern).

Written before the spec. Each case names what it proves; "draft" = the one shared policy draft (§3).

| ID | Area | Case | Expected |
|---|---|---|---|
| PV2-B-UI-01 | Allocation | The view renders from data: eyebrow, synthesis from the template, prose, 4 KPIs (min 200), policy card, bucket card with legend, sector, F&O margin vs max loss, "Allocation changes · ranked by ₹ impact" | Synthesis "₹X is deployed. {bucket} uses a% of it but carries b% of open risk." with the amber span; KPI values = the mocked account; changes numbered 01…, ordered by \|₹\|, mint reduce / danger block; no "Recommended" |
| PV2-B-UI-02 | Policy | One draft across views: change a bucket on Allocation, open 04 by its chip, change a risk field, go back | Both changes still in the draft; the pill says "Policy vN+1 · draft" on both views; the changes line names the other panel's change |
| PV2-B-UI-03 | Policy | Save policy writes ONE version | One PUT to `/api/v1/paper/accounts/{id}/policy` with `expected_version` = vN and `values` = exactly the changed keys of both panels; the pill returns to "Policy v(N+1) · saved"; "Saved as policy v…" |
| PV2-B-UI-04 | Policy | Discard / Defaults | Discard → every field back to the saved value, pill saved, Save + Discard dimmed (disabled, opacity .35); Defaults → this panel's fields go to null (the default shown), Save sends `null` for an overridden field |
| PV2-B-UI-05 | Policy | Version pill states | Saved: mint `data-state=saved` "Policy v7 · saved"; draft: amber "Policy v8 · draft" |
| PV2-B-UI-06 | Allocation | Bucket cap + reserve | Typing a bucket above 100 − the other two clamps it (capped note); reserve = 100 − the three, read-only, amber under 5 % |
| PV2-B-UI-07 | Risk | Halt ≤ restricted | "Halt threshold must sit above the restricted threshold." shown; Save disabled; no PUT sent |
| PV2-B-UI-08 | Policy | 403 admin_required | The problem box names the loosened fields by their labels; nothing saved; pill still draft |
| PV2-B-UI-09 | Policy | 409 version_conflict | The box offers Reload; Reload re-reads the policy and the draft becomes the new saved version |
| PV2-B-UI-10 | Policy | 422 | The box names the field ("Daily loss limit %: …") |
| PV2-B-UI-11 | Policy | Admin picker | An admin sees the user-id picker; Load reads `GET /api/admin/spt/{uid}/policy`; Save is disabled until a reason is given; it PUTs `/api/admin/spt/{uid}/policy` with the reason; a non-admin sees no picker |
| PV2-B-UI-12 | Risk | Limit bars from the draft | Lowering "Daily loss limit %" in the draft turns the daily-loss row NEAR LIMIT then BREACH before any save; the synthesis changes to "1 limit breached: Daily loss." |
| PV2-B-UI-13 | Risk | Correlation | ρ ≥ 0.70 cells are danger (`data-hot`); the diagonal is bg-3 "1.00"; a null cell shows "—"; notes listed; "≥0.70 = concentrated" |
| PV2-B-UI-14 | Risk | Stress scenarios | The existing three (gap, sector shock, market −3/−5) and the named five (Nifty −2 %, sector gap −3 %, correlated stops, gap beyond stops +25 %, IV +10 pts) each with ₹ and its assumption |
| PV2-B-UI-15 | Risk | F&O net Greeks | "F&O · 2 strategies · net Greeks"; "Sum of max loss · ₹…"; delta tile lists the per-structure split; max loss rows flagged NEAR LIMIT / BREACH against the draft per-strategy limit; the partial one says "Unhedged · hedge leg pending"; scenario P&L summed; "Scenarios are assumptions, not forecasts." |
| PV2-B-UI-16 | Risk | F&O structure caps | Gate on: mint "GATE ON FOR YOUR ACCOUNT", Remaining computed; gate off: amber pill, the off note, Remaining "—"; ₹ prefix on Capital at risk; Defined risk only Yes/No; collapses with the chevron; footer "RISK CONTROLS · RULES-BASED · FNO-RISK-V1"; the read-only note says no route changes the caps |
| PV2-B-UI-17 | P&L | Header | Serif total = summary net; "+x.xx% of equity"; pill "● Streaming · N ticks" on the stream, "Polling · every 3 s" when polling |
| PV2-B-UI-18 | P&L | KPIs | Unrealized "n equity · k F&O strategies"; Realized net of costs "n closed today · net of costs"; Open risk remaining "x% of equity"; Daily loss used "of X% limit" |
| PV2-B-UI-19 | P&L | Curve + P&L by strategy | SVG with a dashed zero line, axis "09:15 · HH:MM NOW · 15:30"; groups by setup type, F&O spreads as one row |
| PV2-B-UI-20 | P&L | Open positions table | Columns Instrument · Avg entry · LTP · Qty · Stop → Target · Position in plan · R · Unrealized; the marker at (LTP−stop)/(target−stop); R; F&O legs are not table rows |
| PV2-B-UI-21 | P&L | F&O strategy cards | Filled: "FILLED · HEDGED" mint; partial: "PARTIALLY FILLED · UNHEDGED" amber, a PENDING leg, Filled "0/75" amber, the amber note; Details opens the detail with Simulate exit for the whole structure |
| PV2-B-UI-22 | P&L | Paper / Live switch | Live sends `mode=LIVE`; broker rows; "Initiate exit" only explains; nothing posted |
| PV2-B-UI-23 | P&L | Row actions survive (§5) | Modify risk PATCHes the desk levels; Simulate exit on a desk row POSTs the desk close; on a scanner row POSTs `/api/v1/paper/positions/{id}/exit` (and never the desk close) |
| PV2-B-UI-24 | P&L | Exit alerts | The banner on Paper with "Show the live positions…"; on Live the Exit watch section and the row chip "Exit watch · Stop hit" |
| PV2-B-UI-25 | P&L | Closed trades | Section at the bottom; the period goes to the route; Journal opens the desk trade's journal; a trade not in the desk book says so |
| PV2-B-UI-26 | All | Empty states | No structures / no sectors / no positions / no allocation change: each says what is missing |
| PV2-B-UI-27 | All | Failures | Account read fails → problem with Retry; fno-structures 404 → the P&L view falls back to the snapshot's structure lines and says so |
| PV2-B-UI-28 | All | Compliance lint | No recommend / pick / suggest in the three views' text, labels or titles |
| PV2-B-UI-29 | All | 390 px | No sideways page scroll on the three views; tables scroll inside their cards |

Reworked existing specs (kept MOCK labels; behaviours re-pointed to the new view): see the spec headers of
`copilot-app-desk-pnl.spec.ts` and `copilot-app-desk-pnl-exits.spec.ts` for every assertion kept, moved and dropped.
