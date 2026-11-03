# Proposal: the shared strategy store, v2 (strategy_versions schema 2 + save API)

Date: 2026-10-28 · Status: **PROPOSAL for review** by the Strategy Lab wizard session (nivesh-ai-39) and the owner. Nothing here is
built yet. · Context: owner decision D1 (REVIEW.md §7): everything that can be backtested lives in the Strategy Builder's
PostgreSQL tables, including the wizard's saved structures. Code facts below are from `origin/dev` 5d5466c1.

## 1. Principles
- **Additive only.** DSL v1 documents, the existing routes and their answers keep working unchanged. A v2 document is
  told apart by `definition.schema_version == "2"`. The old `dsl_version` column stays `'1'` for v1 rows.
- **Immutable versions.** A version row is never updated. A change is a new row (`version_no + 1`). A database trigger enforces
  it; today it is only a convention.
- **One validator, server-side.** Legs 1..`MAX_STRATEGY_LEGS` (= 4, `services/strategy_limits.py`, PR #392). Unknown fields
  are refused (`extra="forbid"`). The wizard's caps are kept: 200 strategies per user, 50 versions per strategy.
- **Errors carry their field.** 422 `{code, problems: [{field, code, message}]}`, the desk's shape, so each issue can be
  shown next to its field (PRD §13.3).
- **Owner only.** Not owned → 404, never 403 (the rule of PR #390). Clone is also allowed from a public template.

## 2. Migration (one new `backend/nidp/migrations/NNN_strategy_store_v2.sql`, idempotent)
| Table | Change |
|---|---|
| `strategies` | widen the CHECK to `asset_class IN ('STOCK','MF','FNO','MIXED')`; add `source TEXT NOT NULL DEFAULT 'user'` CHECK in (`user`,`ai`,`template`,`clone`,`plan`); `template_id TEXT`; `underlying TEXT`; `cloned_from UUID` (no FK, so a source can be archived) |
| `strategy_versions` | add `schema_version TEXT NOT NULL DEFAULT '1'`; `parent_version_id UUID REFERENCES strategy_versions(id)`; `change_summary TEXT`; `source_prompt TEXT`; `model_provenance JSONB`; `field_status JSONB`; `idempotency_key TEXT` with `UNIQUE (strategy_id, idempotency_key)`; a trigger refusing UPDATE of `definition`, `strategy_id`, `version_no`, `created_by`, `schema_version` (only `is_active` may change) |
| `strategy_runs` | unchanged here (status work is PR #391; queue and status machine come in Phase 2) |

Existing rows: `schema_version` defaults to '1', `source` to 'user'. Nothing is rewritten. (The 3 staging runs and their
strategies stay valid.)

## 3. The v2 document (`strategy_versions.definition`)
```jsonc
{
  "schema_version": "2",
  "name": "NIFTY bull call spread",
  "market": "NSE",
  "underlying": {"symbol": "NIFTY", "kind": "index"},          // kind: index | stock
  "template_id": "bull_call_spread",                           // or null for a hand-built structure
  "timeframe": "1d",                                           // MVP: "1d" only (D4)
  "legs": [                                                    // 1..4
    {
      "leg_id": "L1",
      "instrument": "CALL",                                    // STOCK | FUTURE | CALL | PUT
      "side": "BUY",                                           // BUY | SELL
      "lots": 1,                                               // shares for STOCK legs: {"shares": n} instead
      "lot_size_at_save": 65,                                  // as read from the chain when saved
      "expiry": {"rule": "specific", "date": "2026-11-25"},    // rule: specific | nearest_weekly | nearest_monthly | next_monthly | same_as:<leg_id>
      "strike": {"rule": "fixed", "value": 25500},             // rule: fixed | atm | atm_offset_points (value) | atm_offset_strikes (value)
      "entry_price_at_save": {"value": 182.4, "source": "NSE F&O bhavcopy close, 2026-10-27"},   // optional; never used as a backtest fill
      "relationship": null                                     // e.g. {"covers": "L0"} for a covered call
    }
  ],
  "entry": {"mode": "market_plus_slippage", "slippage_pct_per_side": 0.05, "cost_model": "desk-cost-v2"},
                                                               // the wizard's EntryAssumption; mode: market_plus_slippage | limit_at_mid | next_open.
                                                               // Phase 1 adds "signal": {"type": "rule", "tree": …} beside it
  "build": {"rule": "atm", "anchor": 0, "width": 2, "delta": null, "lots": 1},
                                                               // the wizard's BuildConfig (rule: atm | otm | itm | delta | manual; anchor = strike steps
                                                               // from ATM; width = strikes between spread legs; delta = target |Δ|), kept beside the
                                                               // resolved legs so a clone or re-open can rebuild by rule
  "build_constraints": {"max_loss_rs": null, "max_capital_rs": null, "stop_underlying": null},
                                                               // the wizard's BuildConstraints: typed, not risk policy (the risk service still decides)
  "exit": {"profit_target_pct_of_net_debit": null, "stop_loss_pct_of_net_debit": null, "time_exit_sessions": null, "close_before_expiry_sessions": 1},
  "sizing": {"capital_rs": null, "max_loss_rs": null}
}
```
**Wizard types → v2 (agreed with the wizard session, 2026-10-28 ~06:25 IST):**
- `WLeg {kind, side, optionType, strike, expiry, lots, price, priceSource}` → leg:
  - `instrument` = kind + optionType (cash→STOCK, future→FUTURE, option+call→CALL, option+put→PUT);
  - `side` upper-cased;
  - `strike.value` with `rule: "fixed"`; `expiry.date` with `rule: "specific"`;
  - `lots` (or `{"shares": n}` for cash);
  - `entry_price_at_save` = `{value: price, source: priceSource}`;
  - `lot_size_at_save` from the chain.
- `BuildConfig` → `build`.
- `BuildConstraints` → `build_constraints`.
- `EntryAssumption` → `entry`.
- **Enabled entry modes:** today only `market_plus_slippage`. `limit_at_mid` needs bid/ask, which the EOD chain lacks. `next_open` is valid for backtests, but the paper route records a structure at once.
Notes:
- **Concrete or rule-based legs.** The wizard saves concrete legs (`specific` expiry, `fixed` strike), so a structure is kept exactly as laid out. The Copilot and backtests use rules (`nearest_monthly`, `atm_offset_points`). Both forms validate.
- **Converting for a backtest.** A backtest of a concrete structure needs rules. The Phase 2 engine derives them relative to the chain on the save date (e.g. fixed 25500 when ATM was 25000 → `atm_offset_points: 500`) and shows the conversion before the run. It never guesses silently.
- **Leg-field mapping.** The old instance-store leg fields map one to one: `kind`→`instrument`, `lots`, `lot_size`→`lot_size_at_save`, `entry_price` + `price_source`→`entry_price_at_save`, `expiry`→`expiry.date`, `strike`→`strike.value`, `option_type`→ folded into `instrument`.
- **Unlimited-loss structures (D2).** They can be saved as drafts, but validation marks them `blocking_for: ["backtest", "paper"]` with code `unlimited_loss`. The existing defined-risk guard in `strategy_plan/model.py` and `desk_strategy_trades.check_defined_risk` decides this, so nothing new is invented.

## 4. API (all under `/api/strategy-builder`, the existing module; nothing new at the top level)
| Method + path | Body | Answer | Notes |
|---|---|---|---|
| `POST /strategies` (exists) | `{name, description?, asset_class, source?, template_id?, definition}` + header `Idempotency-Key` | 201 `{strategy_id, version_id, version_no: 1}` | v1 bodies unchanged; v2 when `definition.schema_version == "2"`. A replayed key returns the first answer |
| `POST /strategies/{id}/versions` (new) | `{definition, parent_version_id, change_summary?}` + `Idempotency-Key` | 201 `{version_id, version_no, diff: [{path, before, after}]}` | 409 `stale_parent` when `parent_version_id` is not the active version (two tabs saving at once). The diff is computed by the server, field by field |
| `POST /strategies/{id}/clone` (new) | `{name?, version_id?}` | 201 `{strategy_id, version_id, version_no: 1}` | `source: "clone"`, `cloned_from` set; from your own strategy or a public template |
| `GET /strategies` (exists, extended additively) | `?include=summary` | each row adds `source, template_id, underlying, asset_class, latest_version{id, version_no, created_at}, last_backtest{run_id, status, finished_at, version_no, is_current_version}, paper_live{open: n}` | without `include` the answer is today's, byte for byte |
| `GET /strategies/{id}/versions` (new) | — | `[{version_id, version_no, created_at, change_summary, parent_version_id, schema_version}]` | newest first |
| `GET /strategies/{id}` (exists) | — | unchanged + `schema_version` | |
| `PATCH /strategies/{id}` (exists) | | unchanged for v1; **refuses v2** with 422 `use_versions_route` | so v2 always gets parent checks and a diff |

**Status words for "Existing strategies · AI and yours"**, derived in this order, never stored:
1. `PAPER LIVE`: an open desk paper trade cites a version of the strategy. Today desk paper trades cite a TradePlan (`plan_ref.plan_id` / `trade_plan_id`), not a strategy version. So:
   - `POST /api/desk/paper-trades` gains an optional `strategy_version_id` (validated: it must exist and belong to the caller), stored on the trade. It is null for every existing trade, and existing bodies are unchanged.
   - The summary joins `desk_paper_trades` (Mongo, `status: open`, `strategy_version_id IN <this strategy's version ids>`) to the strategy.
   - The wizard sends the field once the store returns a version id.
2. `BACKTEST FAILED`: the latest run is FAILED.
3. `BACKTESTED`: the latest run is OK on the current version.
4. `STALE`: the latest OK run is on an older version.
5. `DRAFT`: no runs.

The wizard design's **"BACKTEST PASSED"** needs a pass rule (minimum trades, net expectancy > 0 after costs, …). None exists yet, so it's an open question for the owner (Q3). Until then show `BACKTESTED`.

## 5. What the wizard calls (to stub `instance-store.ts` against)
| Wizard action | Call |
|---|---|
| Save (first time) | `POST /strategies` with `source: "user"` (or `"ai"` for an AI idea opened in the wizard), `asset_class` `FNO`/`MIXED`, v2 `definition` |
| Save as new version | `POST /strategies/{id}/versions` with the `parent_version_id` the wizard loaded |
| Clone | `POST /strategies/{id}/clone` |
| Step 1 list | `GET /strategies?include=summary` |
| Open existing → Step 3 | `GET /strategies/{id}` (active version) or a specific version from `/versions` |

## 6. Tests to be written before implementation (Phase 1.1)
- Each v1 route answers byte-for-byte as today: a recorded-response comparison on the existing tests.
- v2 create, version, clone, list and summary.
- 5 legs refused; unknown field refused; 4 KB `build_constraints` cap; 200 / 50 caps.
- 409 stale parent; an idempotent replay returns the same id.
- The trigger refuses an UPDATE of `definition`.
- Not owned → 404.
- A clone of a public template is owned by the caller.
- An unlimited-loss draft is saved with `blocking_for`.
- `paper_live` counts only open trades whose `strategy_version_id` is one of the strategy's versions.
- `POST /api/desk/paper-trades`:
  - today's bodies (no `strategy_version_id`) answer exactly as before;
  - an unknown or not-owned `strategy_version_id` → 422 with field `strategy_version_id`.
- The wizard's `WLeg` / `BuildConfig` / `BuildConstraints` / `EntryAssumption` samples round-trip into v2 and back unchanged.
- The migration runs twice without error, and the 3 staging rows still read.

## 7. Open questions
1. ~~**(wizard)** The shape of `build_constraints` and the entry assumption.~~ **Answered** (2026-10-28 ~06:25 IST): the types are in §3, now typed sub-schemas.
2. ~~**(wizard)** The source of an AI idea.~~ **Answered:**
   - an AI idea is `source: "ai"` with provenance `{kind: "ai_idea", plan_id, scan_date, signal_ref}`;
   - a template is `source: "template"` + `template_id`;
   - re-opening a saved strategy keeps its source and sets `parent_version_id`;
   - a clone is `source: "clone"` + `cloned_from`.
   - The wizard shows only the status words the list returns, and "BACKTEST PASSED" stays hidden.
3. **(owner)** What "BACKTEST PASSED" means. Proposed until decided: not shown; `BACKTESTED` instead.
4. **(owner)** Can unlimited-loss structures be saved as drafts (marked not backtestable / not paper-tradable), or refused at save? Proposed: saved and marked.
