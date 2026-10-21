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

## Sources
Tradomate: [Config](https://tradomate.one/docs/strategy-builder/config/tradomate-config/) · [Commissions](https://tradomate.one/docs/strategy-builder/config/commissions) · [Pyramiding](https://tradomate.one/docs/strategy-builder/config/pyramiding) · [Short Margin](https://tradomate.one/docs/strategy-builder/config/short-margin)
