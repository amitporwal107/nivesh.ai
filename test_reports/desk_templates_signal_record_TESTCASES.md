# Test cases — desk first-wave templates + signal record route

- **Branch:** feat/desk-templates-signal-record (base origin/dev)
- **Date:** 2026-10-27 (authored before implementation)
- **Scope:** backend only. (1) `services/strategy_plan/templates.py`: covered call, bull put spread, bear call spread,
  protective put, collar (owner's first wave, docs/AUTONOMOUS_PAPER_AGENTS_WORKFLOW.md §2/§10; iron condor already
  exists). (2) `GET /api/positional/signals/{symbol}/record?date=YYYY-MM-DD` (routes/positional.py).

## Design decisions the cases pin

- The underlying leg of covered call / protective put / collar is **cash shares** (lots × lot_size, so the short
  call is fully covered), priced at the chain's spot (the bhavcopy underlying price). A long future is NOT used:
  the risk gate's additional F&O check (`gate.defined_risk_failures`, flag `fno_risk_gate`) refuses a long future
  with a short call and no long put as `unhedged_future`.
- Every catalog entry states its risk shape (`risk.max_loss`: `defined` | `to_zero` | `unbounded`, plus a note).
  Covered call is `to_zero` (the shares' risk); protective put and collar are `defined` (the put floors the loss)
  but hold the shares' full value.
- No price is invented: a strike or a side without a close raises `TemplateError` (`no_strike` / `no_premium`).

## Templates (T) — unit, MOCK chain (round numbers, worked by hand)

| ID | Scenario | Expected |
|----|----------|----------|
| T-1 | covered_call: buy lots×lot_size shares at spot + sell 1 OTM call | legs (cash buy, call sell); max_profit = (K − spot + premium) × units; max_loss = −(spot − premium) × units (price 0); breakeven spot − premium; profit not unbounded |
| T-2 | covered_call strike at/below spot | TemplateError `strike_not_otm` |
| T-3 | bull_put_spread: buy lower put, sell higher put | net credit; max_profit = credit × units; max_loss = −(width − credit) × units; breakeven short − credit |
| T-4 | bull_put_spread strikes reversed | TemplateError `strike_order` |
| T-5 | bear_call_spread: sell lower call, buy higher call | net credit; max_profit = credit × units; max_loss = −(width − credit) × units; breakeven short + credit |
| T-6 | bear_call_spread strikes reversed | TemplateError `strike_order` |
| T-7 | protective_put: shares + long put | max_loss = −(spot − K + premium) × units; profit unbounded; breakeven spot + premium |
| T-8 | collar: shares + long put + short OTM call | max_loss = −(spot − Kp + net debit) × units; max_profit = (Kc − spot − net debit) × units; bounded both ways |
| T-9 | collar put ≥ call, or call not OTM | TemplateError `strike_order` / `strike_not_otm` |
| T-10 | a strike missing from the chain / a side with no close | TemplateError `no_strike` / `no_premium` (never guessed) |
| T-11 | every template result carries the engine's numbers; payoff-v2 | `catalog()` calculation_version == payoff-v2; template numbers equal `compute_payoff` on the same legs (net figures include statutory costs) |
| T-12 | catalog lists exactly the public template functions; each leg's strike_param is a function argument; non-option legs have none; each entry has a risk shape | route test |
| T-13 | the built legs' (instrument, side, option_type) match the catalog's legs | route test |

## Payoff route and paper-trade path (P)

| ID | Scenario | Expected |
|----|----------|----------|
| P-1 | `POST /api/desk/strategy/payoff` with each new template's legs | 200, `valid: true`, no `undefined_risk_not_supported` |
| P-2 | a naked short call / naked short put (control) | still `undefined_risk_not_supported` (no loosening) |
| P-3 | each template's legs converted to the paper-trade leg shape pass `desk_strategy_trades.clean_leg` and `check_defined_risk`, family in FAMILIES | no DeskInputError |

## Risk service (R) — `services/risk_gate/service.decide` on a MOCK snapshot

| ID | Scenario | Expected |
|----|----------|----------|
| R-1 | each new structure: check `defined_risk` | pass, no reason |
| R-2 | each new structure with `fno_additional` on: no defined-risk failure code (naked_short_call / naked_short_put / unhedged_future / futures_only) | none |
| R-3 | covered call built on a long future instead of shares | `fno_additional` → `unhedged_future` (documents why shares are used; rule unchanged) |
| R-4 | control: naked short call, naked short put | `defined_risk` fails (`unbounded_loss`, `naked_short_put`) |
| R-5 | the service's outcome on the full-lot covered call at the default profile | recorded as found (sizing checks may block; not a defined-risk refusal); reported, rule not changed |

## Signal record route (S) — `GET /api/positional/signals/{symbol}/record?date=`

| ID | Scenario | Expected |
|----|----------|----------|
| S-1 | signal with 2 earlier revisions | 200; `current` (revision, levels, stop_method, setup, computed_at); `revisions` ascending from history; each has `changes` [{field, from, to}] vs the revision that replaced it; `revision_count` = 3 |
| S-2 | signal with no history | 200; `revisions: []`; current revision 1 |
| S-3 | no live row and no history | 404 |
| S-4 | history only (the live row was removed by a day rewrite) | 200; `current: null`; `state.live: false`; the history rows as stored |
| S-5 | migration 025 missing (`signal_history_ready` false) | 503 |
| S-6 | no database pool | 503 |
| S-7 | bad date | 400 |
| S-8 | signed out | 401 |
| S-9 | read-only: POST/PUT/DELETE | 405; every SQL issued is a SELECT |
| S-10 | symbol is upper-cased and trimmed | the SQL receives the upper-case symbol |
| S-11 | staging, read-only (docker exec, SELECT only) | the route's reader on a real symbol/date returns the stored row; history count matches a direct COUNT |

## Regression

- tests/test_strategy_payoff.py, test_payoff_cost_card.py, test_strategy_plan_templates_route.py,
  test_risk_service.py, test_risk_gate*.py, test_positional_*.py, then the full CI allowlist
  (dev's known network-only failures: test_cas_api_client ×2, test_nidp_stamp_broadcast_at).
