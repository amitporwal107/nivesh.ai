"""NiveshConfig: the frozen per-run settings bag of docs/STRATEGY_BUILDER_CONFIG_SPEC.md (reference class, §4.1).

Lifecycle: build with platform/UI values, run `strategy_info(config)` once, validate, freeze, then read-only.
Only `initial_capital` may be written in code (spec Q1, assumption B2 in docs/prd/AI_TRADER_PHASES_2_5.prd.md)."""
from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Optional

SCHEMA_VERSION = 1
BUILTINS = {"symbols", "initial_capital", "commission_pct", "pyramiding", "short_margin_pct"}
CODE_WRITABLE = {"initial_capital"}

# Defaults for a strategy the AI creates (assumption B2): a realistic per-side cost, one entry per direction.
AI_DEFAULTS = {"initial_capital": 1_000_000.0, "commission_pct": 0.05, "pyramiding": 0, "short_margin_pct": 100.0}

# The ONE source of the ranges of spec section 2 / section 8b.2. `validate()` reads them, the DB CHECK
# constraints of backend/migrations/024_strategy_config.sql mirror them, and
# GET /api/strategy-builder/config-schema derives its JSON Schema from them, so the frontend cannot reject a
# different set of inputs than the backend (spec section 4.4). A bound is named after its JSON Schema keyword:
# `exclusive_minimum` is the spec's `> 0`, `minimum`/`maximum` are its inclusive bounds. The messages are part
# of the contract (PRD section 5 wants the field named), so each field carries its own rather than sharing one.
# `scale` is the decimal places the NUMERIC column of migration 024 holds. Postgres ROUNDS a finer value into
# the column (0.004 -> 0.00), which can then break that column's own CHECK, so the class refuses the extra
# digits itself rather than letting the write fail; the served JSON Schema turns it into `multipleOf`.
FIELD_RANGES: Dict[str, Dict[str, Any]] = {
    "initial_capital": {"json_type": "number", "py_types": (int, float),
                        "exclusive_minimum": 0.0, "maximum": 1e10,
                        "scale": 2,                      # NUMERIC(18,2)
                        "type_message": "initial_capital must be a number",
                        "range_message": "initial_capital out of range",
                        "scale_message": "initial_capital must have at most 2 decimal places"},
    "commission_pct": {"json_type": "number", "py_types": (int, float),
                       "minimum": 0.0, "maximum": 5.0,
                       "scale": 4,                       # NUMERIC(6,4)
                       "type_message": "commission_pct must be a number",
                       "range_message": "commission_pct out of range",
                       "scale_message": "commission_pct must have at most 4 decimal places"},
    "pyramiding": {"json_type": "integer", "py_types": (int,),
                   # The maximum is the column's own domain: pyramiding is SMALLINT in migration 024, and
                   # SMALLINT tops out at 32767. Above it asyncpg refuses the argument outright, so an
                   # unbounded class here would turn a user's typo into a 500.
                   "minimum": 0, "maximum": 32767,
                   "type_message": "pyramiding must be an integer",
                   "range_message": "pyramiding must be between 0 and 32767"},
    "short_margin_pct": {"json_type": "number", "py_types": (int, float),
                         "exclusive_minimum": 0.0, "maximum": 100.0,
                         "scale": 2,                     # NUMERIC(5,2)
                         "type_message": "short_margin_pct must be a number",
                         "range_message": "short_margin_pct out of range",
                         "scale_message": "short_margin_pct must have at most 2 decimal places"},
}


def out_of_range(field: str, value: Any) -> bool:
    """True when `value` breaks one of FIELD_RANGES[field]'s bounds. Assumes the type check already passed."""
    r = FIELD_RANGES[field]
    # NaN compares False against every bound and would slip through; inf fits no column. Neither is a
    # quantity, and both reach this class from a JSON body (`json.loads` accepts NaN and Infinity).
    if isinstance(value, float) and not math.isfinite(value):
        return True
    if "minimum" in r and value < r["minimum"]:
        return True
    if "exclusive_minimum" in r and value <= r["exclusive_minimum"]:
        return True
    if "maximum" in r and value > r["maximum"]:
        return True
    if "exclusive_maximum" in r and value >= r["exclusive_maximum"]:
        return True
    return False


def exceeds_scale(field: str, value: Any) -> bool:
    """True when `value` carries more decimal places than FIELD_RANGES[field]'s column holds.

    Assumes the type and range checks already passed (a non-finite float has no exponent to read).
    """
    scale = FIELD_RANGES[field].get("scale")
    if scale is None:
        return False
    return -Decimal(str(value)).as_tuple().exponent > scale


class ConfigFrozenError(AttributeError):
    pass


class ConfigValidationError(ValueError):
    pass


class NiveshConfig:
    def __init__(self, symbols, initial_capital: float = 1_000_000.0, commission_pct: float = 0.0,
                 pyramiding: int = 0, short_margin_pct: float = 100.0, custom: Optional[Dict[str, Any]] = None):
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_data", {
            "symbols": tuple(symbols), "initial_capital": initial_capital, "commission_pct": commission_pct,
            "pyramiding": pyramiding, "short_margin_pct": short_margin_pct})
        object.__setattr__(self, "_custom", dict(custom or {}))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._data:
            return self._data[name]
        if name in self._custom:
            return self._custom[name]
        raise AttributeError(f"config has no option '{name}': set it in strategy_info")

    def __setattr__(self, name, value):
        if self._frozen:
            raise ConfigFrozenError("config is read-only after strategy_info")
        if name in BUILTINS:
            if name not in CODE_WRITABLE:
                # Spec section 6 row 2 asks the symbols error to point the author at the picker. Section 4.1's
                # reference wording does not; the two disagree, and the more useful message wins.
                if name == "symbols":
                    raise ConfigFrozenError("'symbols' comes from the symbol picker, not from code")
                raise ConfigFrozenError(f"'{name}' is set by the platform or in Bot details, not in code")
            self._data[name] = value
        elif name.startswith("_"):
            raise ConfigValidationError("custom keys cannot start with '_'")
        elif not name.isidentifier():
            raise ConfigValidationError(f"custom key {name!r} is not a valid identifier")
        else:
            self._custom[name] = value

    def validate(self) -> None:
        d = self._data
        if not d["symbols"]:
            raise ConfigValidationError("symbols is empty")
        # Spec section 2 types this list[str]. Whether each symbol EXISTS belongs to the picker and the instrument
        # master (section 4.4), which a pure class cannot reach, but the type needs nothing but the value in hand, and
        # to_dict() would otherwise persist the junk with the run.
        not_symbols = [x for x in d["symbols"] if not isinstance(x, str) or not x.strip()]
        if not_symbols:
            raise ConfigValidationError(f"symbols must be non-empty strings: {not_symbols}")
        # Types for every field first, then the ranges, both driven by FIELD_RANGES: a bound and the schema the
        # UI validates against then cannot drift apart. A bool passes isinstance(int) in Python, so it is excluded
        # explicitly — True is not a quantity the author chose.
        for field in FIELD_RANGES:
            v = d[field]
            if isinstance(v, bool) or not isinstance(v, FIELD_RANGES[field]["py_types"]):
                raise ConfigValidationError(FIELD_RANGES[field]["type_message"])
        for field in FIELD_RANGES:
            if out_of_range(field, d[field]):
                raise ConfigValidationError(FIELD_RANGES[field]["range_message"])
        # Last, the stored column's decimal places: a value inside the range can still be finer than
        # NUMERIC(_, scale), and postgres would round it (0.004 -> 0.00) into a CHECK violation. Refusing
        # it here keeps "the class accepts it" and "the column holds it" the same statement.
        for field in FIELD_RANGES:
            if exceeds_scale(field, d[field]):
                raise ConfigValidationError(FIELD_RANGES[field]["scale_message"])
        # All three of section 2's rules for a custom key, not only the two __setattr__ happens to reach: a key can
        # also arrive through the constructor, from the stored `custom` blob of section 4.3, and a key that is not an
        # identifier could never be read back as config.<name>.
        # Identifier first: the shadow check below reads the key as a string, and a non-string key from the stored
        # blob would otherwise raise AttributeError instead of a validation error.
        unreadable = [k for k in self._custom if not (isinstance(k, str) and k.isidentifier())]
        if unreadable:
            raise ConfigValidationError(f"custom keys must be valid identifiers: {unreadable}")
        bad = [k for k in self._custom if k in BUILTINS or k.startswith("_")]
        if bad:
            raise ConfigValidationError(f"custom keys shadow built-ins or start with '_': {bad}")
        try:
            json.dumps(self._custom)
        except (TypeError, ValueError) as e:
            raise ConfigValidationError(f"custom values must be JSON-serialisable: {e}") from e

    def freeze(self) -> None:
        object.__setattr__(self, "_frozen", True)

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **self._data, "symbols": list(self._data["symbols"]),
                "custom": dict(self._custom)}


def resolve(symbols: Iterable[str], ui: Optional[Dict[str, Any]] = None,
            strategy_info: Optional[Callable[[NiveshConfig], None]] = None) -> NiveshConfig:
    """Spec section 4.2 steps 1 to 3: build from platform and UI values, run `strategy_info` once, validate, freeze.

    An unknown key in `ui` is refused rather than dropped: a setting the caller believed they had chosen must never
    disappear in silence. Only the four Bot details built-ins may be supplied here; `symbols` is a separate argument
    because it comes from the picker, and a custom key belongs in `strategy_info`.
    """
    ui = dict(ui or {})
    settable = BUILTINS - {"symbols"}
    unknown = sorted(k for k in ui if k not in settable)
    if unknown:
        raise ConfigValidationError(f"unknown Bot details field(s): {unknown}; settable here: {sorted(settable)}")
    values = {**AI_DEFAULTS, **ui}
    cfg = NiveshConfig(symbols, values["initial_capital"], values["commission_pct"], values["pyramiding"],
                       values["short_margin_pct"])
    if strategy_info is not None:
        strategy_info(cfg)
    cfg.validate()
    cfg.freeze()
    return cfg
