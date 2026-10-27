# Test cases — Phase 3 decision cards, carry-forward tags and Phase 0 follow-ups

- **Branch:** `feat/p3-decision-cards` (worktree `/home/deploy/nivesh-p3-cards`, off origin/dev `ce923426`)
- **Authored:** 2026-10-27, after the API and UI design below and BEFORE implementation.
- **Acceptance standard:** `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` Phase 3 (3.1, 3.2, 3.3, exit gate); owner decisions
  in `docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md` §9; the field matrix in
  `docs/ai_research/guidelines_gap_study_20261027/B_plan_lifecycle_exits.md` §8.

## Design (fixed before the cases)

### Backend
1. **TradePlan carries its evidence and warnings** (`services/strategy_plan/trade_plan.py`, rules version
   `trade-plan-v1.1`). The browser computes nothing, so the plan must carry what the card shows:
   - `evidence`: six keys in a fixed order: `regime`, `trend`, `relative_strength`, `momentum`, `volume`, `structure`.
     Each is `{key, label, status: ok | unavailable, direction, text, as_of, source}`. Cash and futures plans take them from
     the plan builder's evidence ledger. An F&O board idea takes `regime` from the board's measured regime and `trend` from
     its fit factors; the others are `unavailable`, with the reason that the board does not compute them.
   - `warnings`: four keys: `event`, `liquidity`, `concentration`, `correlation`. Each is
     `{key, label, status: flagged | clear | unavailable | at_entry, text}`. Concentration and correlation are
     `at_entry`: they depend on the account, so the account's risk decision checks them at entry (Phase 1). They are not
     put in a plan whose id must be the same for every user.
   - `costs.gap_risk`: the gap and slippage sentence for the plan's segment.
2. **`GET /api/desk/trade-plans/{id}`** lists only the versions the caller may read (their own plans, or plans built by a
   system job), so the newest version a card switches to is one that user can open.
3. **AI watchlist**
   - `shape_day` stores `notes.scan_basis`: the scanner's engine version, price basis and data-quality status
     (`ideas.selection.scan_basis`, #355).
   - The route adds `carried` to an entry that has been on more than one consecutive stored list:
     `{sessions, from, first{list_date, entry, stop, target, plan_id, basis}, today{...}}`. Display only.
4. **`job_runs.SCHEDULES["positional_engine"]`** uses the staging cron (Mon–Fri 19:45 and 21:45 IST). The scanner's own
   statuses are mapped in `health()`, so `GET /api/admin/risk/jobs/positional_engine` answers.

### Frontend
- **One component**, `tradingdesk/decision/DecisionCard.tsx`, with a `row` variant (one line plus an expander) and a
  `full` variant. The plan view hook, `usePlanView` (`decision/plan-view.ts`), takes the row's plan:
  - reads `GET /api/desk/trade-plans/{plan_id}` (React Query key `["copilot","desk","trade-plan",id]`, shared by every
    view) for the derived lifecycle status and the versions;
  - switches to the newest readable version and says so;
  - when a newer plan names an older one in `supersedes`, invalidates the older plan's cached reading;
  - reads the paper account for the equity basis (only when the plan carries no `risk_pct_of_equity`);
  - takes the risk decision from ONE seam, `riskDecisionFor(planResponse)`, which reports "pending" until Phase 1.
- **Action gate.** `planActionGate(view)` is the single "may this be paper traded" answer. The card's action line and
  every button use it: Top 10 and watchlist cash (`PlanPaperTrade`), F&O (`IdeaActions`) and the Builder
  (`PlanActions`). It returns null or the reason. Reasons: the plan is not stored; the plan is not eligible (with its
  reasons); the plan changed since the row was built; the risk decision blocks.
- Surfaces:
  - Top 10 stock and F&O rows, AI watchlist cash and F&O rows, and the Top-by-regime cards use the `row` card.
  - The lab focus panel, the Builder's selected candidate and the paper-trade record use the `full` card.
- **Carry-forward tags.**
  - AI watchlist rows read `carried`.
  - Top 10 rows look up the newest stored list (`useAiWatchlist(null)`, already cached by the watchlist hook) by symbol.
    They show its `carried` (or "on the list of <date>") with the first day's levels next to this row's plan levels.
- **Phase 0 follow-ups.**
  - The F&O idea POST sends `Idempotency-Key` (`useSubmissionKey`).
  - The comments and the e2e mock say 22:45 IST.
  - The day block shows `notes.scan_basis`.

## Cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| BE-1 | TradePlan | A cash plan from the plan builder carries `evidence` (6 keys, in order) and `warnings` (4 keys) | unit | Each key is present. An `unavailable` ledger item stays `unavailable` with its reason. No portfolio rupee values. The plan id is still a content digest (validate() passes). |
| BE-2 | TradePlan | An F&O board idea's plan | unit | `regime` comes from the board regime (label, as_of); `trend` from the fit factor. RS, momentum, volume and structure are `unavailable` with a reason. Concentration and correlation are `at_entry`. |
| BE-3 | TradePlan | `costs.gap_risk` on cash and options plans | unit | A non-empty sentence that names the slippage per side (cash) or end-of-day premiums (options). |
| BE-4 | route | `GET /trade-plans/{id}` when another user's plan is a newer version in the same lineage | api (TestClient) | The other user's version is not in `versions`. The caller's own and system versions are. |
| BE-5 | AI watchlist | `shape_day` stores `notes.scan_basis` from the ideas answer; a day without it reads `null` | unit | Equal to `ideas.selection.scan_basis`. |
| BE-6 | AI watchlist | Route `carried` for an entry on 3 consecutive stored days (with a holiday gap), and for a new entry | api (TestClient) | `sessions` 3; `from` is the first day; `first` holds the first day's plan levels and `today` the list day's. A new entry has no `carried`. F&O uses the plan's underlying stop and target and its net premium. |
| BE-7 | job health | `GET /api/admin/risk/jobs/positional_engine` | api (TestClient) | 200 with health. The statuses map as follows: `ok` → ok; `calendar_not_ready` → unhealthy alert; `refused_*` → failed; `skipped_no_bars` → no_data; `skipped_done` → ok; no run → never_run. The cron file's lines equal the schedule. |
| BE-8 | contract | `contract-decision-card.json` (cash sized, F&O, Builder plan, stored day) is what the backend builds | contract | For one cash `plan_id`, the ideas route, the Builder, the stored day and `GET /trade-plans/{id}` carry identical entry, stop, targets, size and risk. The fixture's F&O plan equals the board's. |
| BE-9 | regression | Existing contract tests (`test_trade_plan_contract.py`, `test_fno_idea_paper_trade_contract.py`) with the regenerated `contract-trade-plan-paper.json` | contract | Pass. |
| BE-10 | safety | `tests/test_order_path_guard.py` | unit | Passes; nothing places an order. |
| UI-1 | Top 10 stock (cash) | Row shows the compact card | e2e | One line: Entry (order type) · Stop (method) · Targets in R · Size · Risk · Est. costs · Horizon · plan id. Status pill, provisional badge, "Risk check: pending". The expander shows every 3.1 field. A missing field reads "unavailable" with the reason. |
| UI-2 | Top 10 F&O (options) | Row card from the F&O plan | e2e | Lots × lot size, ₹ risk, premium stop in the exit plan, the "Provisional" badge distinct from an approved badge. |
| UI-3 | AI watchlist | Cash and F&O rows show the card for the stored plan | e2e | Same fields as UI-1 and UI-2. |
| UI-4 | Lab focus | Full card under the focus panel | e2e | Every section is visible without an expander. |
| UI-5 | Builder | Full card for the selected candidate's plan (cash and futures) | e2e | Every section. A futures plan shows lots and lot size. |
| UI-6 | Paper-trade detail | The record shows the plan the trade cites (`GET /trade-plans/{id}`) | e2e | Full card; derived status "open". |
| UI-7 | 3.2 consistency | The same `plan_id` on Top 10, watchlist and Builder (cash), and on Top 10, watchlist, lab focus and Top-by-regime (F&O) | e2e | Identical entry, stop, targets, quantity and risk text (`data-*` values equal). |
| UI-8a | state: empty | The idea has no plan (`trade_plan: null`) | e2e | "No trade plan" with the route's reason; no card and no action. |
| UI-8b | state: stale | `data_as_of.price` is before `reference_session`; regime older than the price | e2e | "Stale data" marker with both dates. |
| UI-8c | state: rejected | `eligibility.state` REJECTED with reasons | e2e | Status "rejected", a rejection explanation, and the action disabled with the reason. |
| UI-8d | state: provisional | No risk decision (Phase 1 pending) | e2e | Amber "Provisional · risk check pending" badge; "Risk check: pending". |
| UI-8e | state: approved | A `risk_decision` (Phase 1 shape, MOCK) with `outcome: allow`, and a derived lifecycle status "approved" | e2e | Mint "Risk-approved" badge, visually distinct (`data-approval`). Status reads from the lifecycle. |
| UI-8f | state: risk block | A `risk_decision` with `outcome: block` | e2e | Action disabled; the reason quotes the decision's reasons. |
| UI-9 | 3.2 change | Top 10 re-rank returns version 2 (`supersedes` v1); the watchlist row still holds v1 | e2e | The watchlist card shows v2's stop with "Plan changed: version 2". Its action is disabled with the reason. |
| UI-10 | equity | The plan has `risk_rs` but no `risk_pct_of_equity` | e2e | The % comes from `GET /api/desk/paper-account` cash, with the basis labelled. Paper account unreadable → "unavailable". |
| UI-11 | mobile | 390 px: row card collapsed and expanded on Top 10 and the watchlist | e2e | No horizontal page scroll; the expander works. |
| UI-12 | carry-forward | Watchlist row with `carried`; Top 10 row whose symbol is on the newest stored list | e2e | "On the list 3 sessions · carried from 22 Oct". First-day vs today's entry, stop and target. New ideas show no tag. |
| UI-13 | P0 (a) | F&O idea "Paper trade" | e2e | Sends `Idempotency-Key` (UUID). A retry after a failure reuses it; the next submission after a success gets a new key. |
| UI-14 | P0 (b) | Empty watchlist | e2e | Reads "22:45 IST". |
| UI-15 | P0 (c) | Day block with `notes.scan_basis`, and without it | e2e | Engine version, price basis and data-quality status are shown, or "Scan basis: not recorded for this day". |
| UI-16 | wording | Cards | e2e | No "pick", "recommended" or "suggested". The "not a prediction" note is on the card. No confidence or edge language for the rank or score. |
| REG-1 | regression | Every spec in the run set on the branch vs plain origin/dev | e2e | No case fails on the branch and passes on dev. desk-lab TC-7 and TC-34 are rerun alone if they fail. |

## Addendum (2026-10-27, after Phase 1 #363 merged into origin/dev mid-task; coordinator's instruction)

The risk seam is wired to the real service instead of "Risk check: pending":
- **BE-11 (added):** `GET /api/desk/trade-plans/{id}` returns `risk_decision`, the user's newest universal-risk decision
  on a submission citing the plan (allow / reduce / block), or null. A desk validation refusal is not a risk decision.
- **UI-8d:** "Provisional · no risk decision yet".
- **UI-8e:** "Risk-approved" only on a real ALLOW under the current limits version (UI-8e2: other limits → provisional).
- **UI-8f, UI-8f2, UI-8g:** a block disables the action only while it applies.
- **UI-10:** % of equity uses `GET /api/risk/profile`'s paper equity, not the paper account's cash.
