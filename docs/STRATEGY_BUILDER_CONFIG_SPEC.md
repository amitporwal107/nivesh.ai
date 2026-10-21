# Nivesh Strategy Builder — Config Specification & Implementation Guide

> **Status:** Requirement captured 2026-10-21 (author: @amit; modelled on Tradomate's `TradomateConfig`). `NiveshConfig` itself is implemented in `backend/services/ai_trader/config.py` (branch `feat/ai-trader-phases-2-5`); the bar engine, `bot_config` table and the three UI screens are not.
> **Related:** [AI_TRADER_BUSINESS_REQUIREMENT.md](AI_TRADER_BUSINESS_REQUIREMENT.md) (the AI trader writes and runs strategies through this builder, see its §10).
> **Design reference:** a 3-screen interactive mockup ("Strategy Builder Config.html", supplied by the product owner) covering Bot details, Code and Backtests. Summarised in §8 below. The HTML bundle itself is not stored in the repo.

## 1. Overview

Nivesh needs a `NiveshConfig` object: one mutable, per-run settings bag that a user's (or the AI trader's) Python strategy fills in a setup hook and then reads on every bar.

Three jobs:
1. **Platform settings** — values the engine reads (symbols, starting capital, commissions, pyramiding, short margin).
2. **User parameters** — arbitrary keys the author adds (e.g. `config.length = 14`).
3. **Shared context** — the same instance is passed as the first argument to the bar handler.

Lifecycle: engine builds default config → calls `strategy_info(config)` once → validates and **freezes** platform fields → calls the decorated handler `handler(config, data)` on every bar.

Tradomate documents only `symbols` and `initial_capital` plus custom keys; the other settings come from its sibling Config pages. Defaults marked "proposed" are Nivesh choices to confirm.

## 2. Field reference

| Field | Type | Default | Set by | Editable in code? | Validation |
|---|---|---|---|---|---|
| `symbols` | `list[str]` | symbols selected in UI | Platform | No, read-only | Non-empty; every symbol in the instrument master |
| `initial_capital` | `float` (INR) | 1,000,000 | Code (`strategy_info`) or UI | Yes, in `strategy_info` only | > 0; cap 10,000,000,000 |
| `commission_pct` | `float` (% of trade value) | 0.0 (proposed) | UI → Bot details | Read-only (proposed) | 0 ≤ x ≤ 5 |
| `pyramiding` | `int` | 0 (proposed) | UI → Bot details | Read-only (proposed) | integer ≥ 0 |
| `short_margin_pct` | `float` (% of position value) | 100.0 (proposed) | UI → Bot details | Read-only (proposed) | 0 < x ≤ 100 |
| custom keys | any JSON-serialisable | — | Code (`strategy_info`) | Yes, in `strategy_info` | valid identifier; must not shadow a built-in; no leading `_` |

### Runtime rules
- **Commission** = `trade_value × commission_pct / 100`, per fill, subtracted from cash at that moment (buy, sell, short, close).
- **Pyramiding** = max extra same-direction entries on top of the first. `0` = one entry per direction (assumption, see open questions); further entry signals are rejected with a reason code (`PYRAMIDING_LIMIT`).
- **Short margin** = `position_value × short_margin_pct / 100` is blocked when a short opens. If unrealised loss consumes the whole blocked margin the engine force-closes the position (`SHORT_MARGIN_DEPLETED`).
- **Capital floor:** if cash would go below 0 the run halts with `INSUFFICIENT_CAPITAL` — "Insufficient capital — raise `initial_capital` in `strategy_info`".

## 3. Example configs

### 3.1 EMA crossover (Nivesh port of the Tradomate example; the original read `config.quantity` without setting it, this version sets it)
```python
import nivesh as nv

def strategy_info(config: nv.NiveshConfig):
    config.initial_capital = 100_000      # built-in
    config.length = 14                    # custom: EMA period
    config.quantity = 10                  # custom: shares per order

@nv.strategy()
def on_bar(config: nv.NiveshConfig, data: nv.NiveshData):
    ema = nv.ta.ema(data.close, timeperiod=config.length)
    if nv.ta.cross_over(data.close, ema):
        nv.enter_long_position_market(quantity=config.quantity, comment="Long")
    if nv.ta.cross_under(data.close, ema):
        nv.enter_short_position_market(quantity=config.quantity, comment="Short")
```

### 3.2 Guards
```python
def strategy_info(config):
    config.initial_capital = 500_000
    config.fast, config.slow = 9, 21
    config.risk_per_trade_pct = 1.0
    config.use_shorts = False

@nv.strategy()
def on_bar(config, data):
    print(config.symbols)          # ['RELIANCE'] read-only
    config.fast = 5                # raises ConfigFrozenError after setup
```

### 3.3 Stored form (persisted per bot; custom keys live under `custom`, exposed flat on the object)
```json
{ "schema_version": 1, "symbols": ["RELIANCE"], "initial_capital": 100000,
  "commission_pct": 0.03, "pyramiding": 0, "short_margin_pct": 20,
  "custom": { "length": 14, "quantity": 10 } }
```

## 4. Implementation guide

Four pieces: `NiveshConfig` SDK class, `bot_config` table, "Bot details" form, engine hooks reading the frozen config.

### 4.1 SDK class (reference implementation)
```python
BUILTINS = {"symbols", "initial_capital", "commission_pct", "pyramiding", "short_margin_pct"}
CODE_WRITABLE = {"initial_capital"}

class ConfigFrozenError(AttributeError): ...
class ConfigValidationError(ValueError): ...

class NiveshConfig:
    def __init__(self, symbols, initial_capital=1_000_000.0, commission_pct=0.0,
                 pyramiding=0, short_margin_pct=100.0, custom=None):
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_data", {
            "symbols": tuple(symbols), "initial_capital": float(initial_capital),
            "commission_pct": float(commission_pct), "pyramiding": int(pyramiding),
            "short_margin_pct": float(short_margin_pct)})
        object.__setattr__(self, "_custom", dict(custom or {}))

    def __getattr__(self, name):
        if name in self._data: return self._data[name]
        if name in self._custom: return self._custom[name]
        raise AttributeError(f"config has no option '{name}' — set it in strategy_info")

    def __setattr__(self, name, value):
        if self._frozen: raise ConfigFrozenError("config is read-only after strategy_info")
        if name in BUILTINS:
            if name not in CODE_WRITABLE:
                raise ConfigFrozenError(f"'{name}' is set by the platform / Bot details")
            self._data[name] = value
        elif name.startswith("_"): raise ConfigValidationError("custom keys cannot start with '_'")
        else: self._custom[name] = value

    def validate(self):
        d = self._data
        if not d["symbols"]: raise ConfigValidationError("symbols is empty")
        if not (0 < d["initial_capital"] <= 1e10): raise ConfigValidationError("initial_capital out of range")
        if not (0 <= d["commission_pct"] <= 5): raise ConfigValidationError("commission_pct out of range")
        if d["pyramiding"] < 0: raise ConfigValidationError("pyramiding must be >= 0")
        if not (0 < d["short_margin_pct"] <= 100): raise ConfigValidationError("short_margin_pct out of range")
        import json; json.dumps(self._custom)   # custom values must be serialisable

    def freeze(self): object.__setattr__(self, "_frozen", True)
    def to_dict(self): return {**self._data, "symbols": list(self._data["symbols"]), "custom": dict(self._custom)}
```

### 4.2 Run lifecycle (engine)
1. Load bot row; build `NiveshConfig` from UI-saved values and selected symbols.
2. Import the user module in the **sandbox**; call `strategy_info(config)` once (timeout 2 s).
3. `config.validate()`, then `config.freeze()`; persist `config.to_dict()` with the run.
4. Initialise the broker simulator: `cash = initial_capital`.
5. Per bar call `handler(config, data)`.
6. On every fill deduct commission; on short entry block margin; check pyramiding count before accepting an entry; halt if cash < 0.

### 4.3 Storage (PostgreSQL)
`bot_config(bot_id uuid PK→bots, schema_version smallint=1, symbols text[], initial_capital numeric(18,2), commission_pct numeric(6,4), pyramiding smallint, short_margin_pct numeric(5,2), updated_at timestamptz)`.
Also store the **resolved config JSON (incl. `custom`) on each `backtest_runs` row** so runs are reproducible after the bot is edited.

### 4.4 "Bot details" UI
Numeric inputs for initial capital (INR), commission (%), pyramiding (integer stepper, min 0), short margin (%); inline validation using the same ranges as `validate()`; **one JSON Schema shared by frontend and backend**; symbols from the symbol picker, shown read-only in editor hints; help text: initial capital set in `strategy_info` overrides the field for that run.

### 4.5 Editor support
Ship type stubs (`nivesh.pyi`) so `config.` autocompletes built-ins; lint warning when the handler reads a custom key that `strategy_info` never assigns.

## 5. API contract

| Method & path | Body / response | Errors |
|---|---|---|
| `GET /bots/{id}/config` | stored config JSON (3.3) | 404 |
| `PUT /bots/{id}/config` | Bot details built-ins; validated against shared schema | 422 field-level |
| `POST /bots/{id}/backtests` | starts a run; response includes `resolved_config` after `strategy_info` | 422 config invalid, 400 `strategy_info` error |
| `GET /backtests/{run_id}` | results + frozen `resolved_config` | 404 |

## 6. Edge cases

| Case | Expected behaviour |
|---|---|
| `strategy_info` missing | run with UI values only |
| user sets `config.symbols` | `ConfigFrozenError` pointing to the symbol picker |
| custom key shadows a built-in | rejected; only `initial_capital` is code-writable |
| handler reads unset key | `AttributeError` naming the key |
| handler writes config | `ConfigFrozenError`; keep per-run state elsewhere |
| non-serialisable custom value | validation error before bar 1 |
| `initial_capital` string/negative | validation error before bar 1 |
| cash < 0 | run halts, insufficient-capital error |
| short loss consumes margin | position force-closed, reason code logged |
| entry beyond pyramiding limit | order rejected with reason code; run continues |

## 7. Test checklist
- [ ] Defaults applied when Bot details blank
- [ ] `initial_capital` override in `strategy_info` beats UI value for that run
- [ ] Read-only built-ins raise on write
- [ ] Config frozen before bar 1
- [ ] Commission deducted on every fill type
- [ ] Pyramiding 0, 1, 3 accept exactly 1, 2, 4 same-direction entries
- [ ] Short margin block and force-close at full depletion
- [ ] Resolved config saved with each run; re-runs reproduce results
- [ ] Frontend and backend share one schema and reject the same inputs

## 8. Design reference (mockup summary)
Three screens inside a "Strategies › EMA Crossover" shell with tabs Bot details / Code / Backtests, dark-first Nivesh V5 design system:
1. **Bot details** — symbol chips (validated against instrument master), initial capital (₹, INR), commission %, pyramiding stepper with "N allowed · next rejected" slots, short margin %; inline errors; "Run backtest" disabled while any field is invalid; right-hand sticky **Resolved config** panel (Fields/JSON toggle, source pill per field: Platform / Bot details / Code) and a 4-step lifecycle strip (NiveshConfig → strategy_info → validate·freeze → on_bar).
2. **Code** — `strategy.py` editor, `config.` autocomplete showing type + source tag + doc, wavy-underline lint on unset key `config.quantity` with a quick-fix, Problems panel, live "Config hints" (read-only / writable / custom keys).
3. **Backtests** — run list; each run stores its frozen config; states: Completed (net return, drawdown, trades, commission), Halted (`INSUFFICIENT_CAPITAL` with bar/date, links to the line and Bot details), Didn't start (`ConfigFrozenError`, no config frozen); equity curve, engine events with reason codes, and a "Bot details changed since this run" drift panel with *Re-run as frozen* / *New run*.

## 8b. Design reference — exact rules and copy extracted from the mockup

Section 8 summarises the three screens. This section records what only the interactive mockup carried: the field
ownership badges, the validation ranges, and the user-facing wording. It is transcribed from the mockup's own
validation function and rendered strings, so a developer can build the screens without the mockup file.

**The mockup HTML itself is not in the repo and cannot be reproduced from the conversation it was pasted into**
(it is a self-extracting bundle with the webfonts inlined as base64). This section plus section 8 is the record.
The design tokens it uses are the committed Nivesh V5 set (`--mint`, `--amber`, `--danger`, `--indigo`,
Instrument Serif display / Inter Tight sans / JetBrains Mono).

### 8b.1 Field ownership badges (shown top-right of each field)

| Field | Badge | Meaning |
|---|---|---|
| `symbols` | **Platform · read-only in code** | set by the symbol picker only |
| `initial_capital` | **Overridable in code** | `strategy_info` may assign it; the field is the fallback |
| `commission_pct` | **Read-only in code** | Bot details only |
| `pyramiding` | **Read-only in code** | Bot details only |
| `short_margin_pct` | **Read-only in code** | Bot details only |

### 8b.2 Validation — ranges and exact messages

| Field | Rule | Message on failure |
|---|---|---|
| `symbols` | at least one chip | `Pick at least one symbol. The engine needs something to trade.` |
| `symbols` | chip must exist in instrument master | `{SYM} isn't in the instrument master. Check the NSE symbol.` |
| `symbols` | no duplicate chip | `{SYM} is already selected.` |
| `initial_capital` | parses as a number | `Enter an amount in rupees, like 1,00,000.` |
| `initial_capital` | `> 0` | `Initial capital must be above ₹0.` |
| `initial_capital` | `<= 10_000_000_000` | `Maximum is ₹1,000 Cr (10,000,000,000).` |
| `commission_pct` | parses as a number | `Enter a percentage from 0 to 5.` |
| `commission_pct` | `0 <= x <= 5` | `Commission must be between 0% and 5%.` |
| `short_margin_pct` | parses as a number | `Enter a percentage above 0, up to 100.` |
| `short_margin_pct` | `0 < x <= 100` | `Short margin must be above 0% and at most 100%.` |
| `pyramiding` | integer stepper, floor 0 | not reachable — the stepper cannot produce an invalid value |

While any field is invalid: the **Bot details** tab shows an error-count badge, and **Run backtest** is disabled
with the tooltip `Fix the highlighted fields first`.

### 8b.3 Live help text under each field (recomputed as the user types)

- `initial_capital` — the value rendered in lakh/crore (`₹10.00 L`), suffixed `· default` when it equals ₹10,00,000.
- `commission_pct` — `₹{pct × 1000} on every ₹1,00,000 traded, charged on each buy, sell, short and close.`
- `short_margin_pct` — `₹{pct × 1000} blocked per ₹1,00,000 short. The position force-closes if losses use up the block.`
- `pyramiding` = 0 — `One entry per direction. The next same-direction signal is rejected with PYRAMIDING_LIMIT.`
- `pyramiding` = N > 0 — `Up to {N+1} same-direction entries. The next signal is rejected with PYRAMIDING_LIMIT.`
- `pyramiding` stepper caption — `{N+1} allowed · next rejected`, drawn as N+1 filled slot ticks plus one dashed red tick.
- Code-override callout (indigo, shown when `strategy_info` assigns `initial_capital`) —
  `strategy_info sets initial_capital = 100_000, so runs start with ₹1,00,000. This field applies when code doesn't set it.`
  with a link to the assigning line.

### 8b.4 Resolved config panel

Sticky, right-hand. A **Fields | JSON** toggle. Each row is key, value, and a source pill — `Platform`,
`Bot details`, or `Code` — with an optional note under the value (`Bot details ₹10,00,000 · line 4 overrides`,
`custom key`). The JSON view emits `schema_version: 1` and nests user keys under `custom`. Footer:
`Saved with every backtest run, so results can be reproduced after you edit the bot.`

Above it, the 4-step lifecycle strip, each step carrying a state tone:

| Step | Label | Sub-label |
|---|---|---|
| 01 | `NiveshConfig(…)` | `defaults + Bot details` |
| 02 | `strategy_info(config)` | `sets 3 keys` |
| 03 | `validate() · freeze()` | `passes` / `{N} errors` |
| 04 | `on_bar(config, data)` | `every bar · read-only` / `blocked` |

### 8b.5 Code screen

- Autocomplete row = key, type, source tag (`Platform`, `Code · line 4`, `Bot details`, `Custom`), with a one-line
  doc beneath and the footer `Frozen inside on_bar · writes raise ConfigFrozenError`.
- Lint: amber wavy underline at **every** read site of a key `strategy_info` never assigns. Problems panel entry —
  title `config.quantity is never set`, rule `unset-config-key · lines 12, 15`, body
  `on_bar reads it, but strategy_info never assigns it. The run would stop with an AttributeError on the first signal.`,
  action `Quick fix · set it in strategy_info`. After the fix the inserted line is highlighted and Problems reads `Clear`.
- Config hints panel, grouped `Read-only in code` / `Writable in strategy_info` / `Custom keys`, showing the live
  Bot details values so the two tabs never disagree.

### 8b.6 Backtests screen — the three run states

| State | Banner | Headline | Body |
|---|---|---|---|
| Completed | — | net return, max drawdown, trades (`2 entries rejected`), commission paid (`76 fills at 0.05%`) | equity curve vs initial capital, 0% dashed baseline |
| Halted | `INSUFFICIENT_CAPITAL · bar 172 · 14 Sep 2022` | `Insufficient capital — raise initial_capital in strategy_info` | quantifies need vs cash (`needed ₹25,623 (10 × ₹2,561 plus ₹13 commission) and cash was ₹24,911`); actions `Open strategy.py · line 4`, `Edit Bot details`; chart draws a dashed amber vertical at the halt bar |
| Didn't start | `ConfigFrozenError · strategy.py line 6` | `'symbols' is set by the platform / Bot details` | the offending line inline with a red wavy underline; `Symbols come from the symbol picker. Code can read them as config.symbols but can't change them.`; actions `Open symbol picker`, `Go to line 6`; and a dashed placeholder where the config panel would be: `No config was frozen. The run stopped at step 02, before validation, so there is nothing to reproduce.` |

Engine events table — date, title, reason code, plain-English explanation. Codes the mockup shows:
`PYRAMIDING_LIMIT`, `SHORT_MARGIN_DEPLETED`, `INSUFFICIENT_CAPITAL`.

Frozen config panel per run: `Run N · resolved config`, `Frozen before bar 1`, `Schema v1`. Below it, a drift panel
when the bot has changed since the run — `Bot details changed since this run`, each changed key as `from → to`,
`Re-running uses the frozen values above. Start a new run to use the current Bot details.`, actions
`Re-run as frozen` / `New run`. With no drift: `Matches the current Bot details.`

### 8b.7 Gap the mockup does not cover: `max_positions`

Position sizing shipped to `dev` on 2026-10-21 (section 10c of the Phases 2–5 PRD) sizes each entry to a slot of
`current_equity / max_positions`. **`max_positions` is not a `NiveshConfig` field and the mockup has no control for
it.** Today:

- `backend/routes/strategy_builder.py:74` exposes `max_positions: int = 10` as a request-body field, passed through
  at line 632 — so the existing DSL Strategy Builder *can* set it per request.
- `backend/routes/ai_trader.py:479` calls the runner without it, so **every AI Trader backtest silently uses 10**.
- `backend/services/strategy_engine/backtest.py:114` holds the default `max_positions: int = 10`.

Since slot size is what decides position size, and position size is what makes the return and drawdown promotion
gates bind at all, this is a user-visible control that currently has no home in the design. It needs either a sixth
Bot details field or an explicit, documented decision to fix it at 10. **Open question, not decided.**

## 9. Answers taken 2026-10-21 (ASSUMPTIONS, not owner-confirmed)

Taken so Phases 2 to 5 could be built; each is one constant so it can be changed in one place. The product owner has
not confirmed them. They are recorded as B2 in [prd/AI_TRADER_PHASES_2_5.prd.md](prd/AI_TRADER_PHASES_2_5.prd.md).

1. **Settable in code?** No. Only `initial_capital` is code-writable, as in Tradomate. The other built-ins come from
   Bot details and raise `ConfigFrozenError` on a write. Implemented in `backend/services/ai_trader/config.py`
   (`CODE_WRITABLE = {"initial_capital"}`).
2. **Defaults for an AI strategy:** `commission_pct = 0.05` (percent per side), `pyramiding = 0`,
   `short_margin_pct = 100.0`, `initial_capital = 1,000,000`. In `config.AI_DEFAULTS`.
3. **Pyramiding 0** means one entry per direction. A further same-direction entry is refused with
   `PYRAMIDING_LIMIT`; the run continues.
4. **Indian charge structure:** not in the bar engine yet. The DSL backtester has its own per-side cost model, so
   `commission_pct` is applied there, and the dated Indian charge stack (`research/costs/engine.py`) is used by the
   Phase 1 pattern validation, where the exact paisa matters. Revisit when a bar-level engine exists.
5. **`cross_over` argument order:** still open, and not needed yet. The AI writes JSON DSL strategies, which have no
   `cross_over` call. This is only a question for the Python-sandbox path, which was not built.

## 9b. Open questions (still unanswered)
1. Should `commission_pct`, `pyramiding`, `short_margin_pct` also be settable in code, or UI-only (as in Tradomate)?
2. Defaults for commission, pyramiding, short margin (Tradomate publishes none).
3. Does pyramiding 0 mean "one entry only" or "pyramiding off, unlimited re-entries after close"? This doc assumes one entry per direction.
4. Should commission model Indian charges (brokerage + STT + exchange fees + GST + stamp duty) instead of one flat %? (`research/costs/engine.py` already has a dated cost engine.)
5. Argument order of Nivesh's `cross_over` (Tradomate goes long when EMA crosses over close; confirm intended semantics).
6. **`max_positions` has no home.** Position sizing (merged 2026-10-21) sizes each entry to `equity / max_positions`,
   but it is not a `NiveshConfig` field and the Bot details mockup has no control for it. The DSL Strategy Builder
   accepts it per request (default 10); the AI Trader never passes it, so it is always 10. Should it become a sixth
   Bot details field, or be fixed at 10 by decision? See section 8b.7.

## Sources
Tradomate: [Config](https://tradomate.one/docs/strategy-builder/config/tradomate-config/) · [Commissions](https://tradomate.one/docs/strategy-builder/config/commissions) · [Pyramiding](https://tradomate.one/docs/strategy-builder/config/pyramiding) · [Short Margin](https://tradomate.one/docs/strategy-builder/config/short-margin)
