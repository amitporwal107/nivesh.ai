# Strategy Lab › Build a trade — the owner's four-step wizard: test cases

Spec: `frontend-v5/e2e/tests/copilot-app-desk-strategy-wizard.spec.ts` (mocked APIs, production build).
Backend: `backend/tests/test_strategy_templates_illustration.py`, `test_desk_paper_trade_check.py`. (The Mongo strategy-instances store and
its tests were reverted on the owner's "one store" decision of 28 Oct: saved structures go into the Strategy Builder's Postgres
tables, whose `strategy_versions` v2 belongs to the strategy-builder session.)
URL: `/v5/app/trader/desk?tab=trade&view=lab&sub=build` (unchanged).

Fixtures: `wizard-catalog.json` is the REAL `GET /api/desk/strategy/templates` body, produced by running
`services/strategy_plan/templates.catalog()` from this branch. `wizard-payoff-bcs.json` and `wizard-payoff-calendar.json`
are REAL `compute_payoff` answers for a NIFTY bull call spread (24500/24700 CE, 25 Nov) and the same legs on two expiries.
Everything else (chain, saved plans, Strategy Builder and AI Trader strategies, the paper book, the check and the POST answers) is an inline
MOCK, not real data, in the route's shape. The clock is fixed at 28 Oct 2026, 10:00 IST.

| ID | Case | Expected |
|---|---|---|
| WZ-1 | Frame | Breadcrumb Trading desk › Trade Desk › Strategy Lab › Build a trade. Eyebrow "STRATEGY LAB · CASH, FUTURES AND OPTIONS"; the headline. Stepper ① Choose template ② Configure ③ Review & adjust ④ Validate & paper-trade, with step 1 current. Provenance TEMPLATE not chosen → STRATEGY INSTANCE — → PAPER TRADE not started. "View underlying on chart" goes to Chart Analysis › Live chart; "Live desk" goes to Paper Trading › Live desk (in-app). |
| WZ-2 | Catalog cards | 13 cards, one per catalog template. Each mini payoff is drawn from that template's `illustration.points` (41 points). Each card shows the intent line, its tags and "n legs · Defined risk" (or the honest risk words). |
| WZ-3 | Intent filter | Bullish / Bearish / Neutral / Income / Hedging show exactly the templates the catalog tags. Volatility shows "No template in the catalog for this intent yet". |
| WZ-4 | Existing strategies | Header "N STRATEGIES · OPEN ONE TO REVIEW AND EDIT", with N the real row count (9). Source pills AI / YOU. Status derived from state: a saved plan cited by an open desk paper trade (`strategy_plan_id`) is PAPER LIVE with that trade's net P/L; another saved plan is SAVED v1. AI Trader stage paper is PAPER LIVE; backtested with passed gates is BACKTEST PASSED; a draft with runs is BACKTESTED; a draft is DRAFT. A Strategy Builder strategy is SAVED: its list reports no runs or version yet. An open AI trade citing nothing is its own AI row. Legs summaries for options and for cash + option; rule sets read "Rule set · no legs". P/L sign colours. Expired contracts are flagged on the row. |
| WZ-5 | No strategies | "No saved or AI strategies yet. Pick a template above." |
| WZ-6 | Configure | Bull call spread → step 2. Spot "NIFTY 24,480 · last close". Expiry chips. ATM builds B 24500 CE · S 24700 CE; OTM anchor 1 moves both one strike; width +1 widens the short. Quick stats come from payoff-v2: max profit ₹8,625, max loss −₹6,375, BE 24,585, reward:risk 1.35 : 1, probability of profit "% (model)". Limit at mid and Next open are disabled with a reason. A Max loss limit of ₹5,000 shows ✗ over. |
| WZ-7 | Leg editor | Rows LEG / SIDE / STRIKE / EXPIRY / LOTS / PRICE / CASH FLOW. The strike stepper moves one listed strike and reprices from the chain. A per-leg expiry chip reprices from that expiry's chain. The legs line formats a calendar ("B 24500 CE 25 Nov · S 24700 CE 30 Dec"); mixed expiries show the engine's "calendar structures are not supported". Lots stepper. Cash flow −₹ for a buy, +₹ for a sell. Side toggle. + Cash / + Future add legs; Clear all legs. |
| WZ-8 | Payoff card | Title "Payoff · nearest expiry 25 Nov — at expiry ·· today", "Spot 24,480", a BE marker, both curves. The scenario slider changes its label and BOTH P/L tiles. It is the only range input (no risk slider). |
| WZ-9 | Summary and Greeks | Net option premium "Debit ₹6,375". Est. costs "₹77 round trip". Margin "Kite login needed" when /api/fno/margin is 503, and the margin figure when it answers. Probability of profit "(model)". Greeks from pre_expiry: delta "+17 sh", theta "−₹51", vega "+₹2". |
| WZ-10 | Checks: allow | ✓ "Within your risk limits. Paper only, no broker order is created." The check POST carries kind strategy, family bull_call_spread, direction bullish and the legs. |
| WZ-11 | Checks: reduce and block | Reduce shows "allows 1 lot per leg (you asked 2)". Block shows ✗ with the service's reasons. A 422 shows the plain refusal. |
| WZ-12 | Chain picker | "+ Call" opens the picker (a dialog, full screen at 390 px) on the leg's expiry. ATM row highlighted, spot marked, R / S wall tags. B adds a buy leg at the chain close; B again adds a lot; S on a put adds a sell put. Added contracts are highlighted. A missing close shows "—" and is disabled. Switching expiry reloads. An old chain is labelled stale. |
| WZ-13 | Save version / Clone | Both are disabled with "Saving arrives with the shared strategy store." (`strategy/instance-store.ts`, typed stubs against the proposed strategy_versions v2). Provenance "unsaved". Edited legs survive steps 3 → 1 → 2 → 3 → 4, with no rebuild unless a step-2 setting is changed by the user. |
| WZ-14 | Start simulated trade | Gates (payoff, build limits, the risk check) must be green. The POST /api/desk/paper-trades carries an Idempotency-Key and source_refs strategy_template (the template it came from, until a saved version exists). Allow sets provenance "open · id" and shows the monitor. Reduce (409) shows "Accept 1 lot per leg?", which rescales the legs. Block (409) shows its reasons. |
| WZ-15 | Open existing → step 3 | Open lands on step 3 with the legs loaded; steps 1 and 2 show done. Provenance shows the row's source ("AI-generated / Bull call spread", the paper trade; "saved plan v1"). A rule set (AI Trader, Strategy Builder) says it has no legs to load. |
| WZ-16 | Expired legs | Step 3 says the legs reference expired contracts and offers "Use the same strikes on 25 Nov" as an explicit button. Pressing it reprices from that chain. |
| WZ-17 | Wording | The wizard's text has no "picks", "suggested" or "recommended". |
| WZ-18 | 390 px | No horizontal page scroll on steps 1, 2, 3 and 4. |
| WZ-19 | Kept flows | `?tp=` still shows the ticket above the wizard. Strategy Builder params open "From an idea"; without them it is folded. The F&O lab's structures (rules-based cards, compare, levels) are folded below; the lab's old `lab=strategies` link opens them (`section=fno`). |
