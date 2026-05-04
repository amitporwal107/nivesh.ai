"""Per-ingester rule registry.

Each ingester registers its rule list at import time:

    from nidp.shared.validation import register
    register("bhavcopy", [
        CountAtLeastRule(...),
        NoNullsRule(...),
    ])

The runner looks up rules by ingester name. Empty list = no
validation (still records a PASSED validation_runs row).
"""
from __future__ import annotations

from typing import Iterable

from .rules import Rule

REGISTRY: dict[str, list[Rule]] = {}


def register(ingester: str, rules: Iterable[Rule]) -> None:
    REGISTRY.setdefault(ingester, []).extend(rules)


def get_rules(ingester: str) -> list[Rule]:
    return list(REGISTRY.get(ingester, []))


def all_ingesters() -> list[str]:
    return sorted(REGISTRY.keys())


def reset() -> None:
    """Test hook."""
    REGISTRY.clear()
