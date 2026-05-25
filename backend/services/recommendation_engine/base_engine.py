"""
BaseEngine ABC.

Every engine inherits from this class.

Contract:
- generate() is pure: no I/O, no DB, no external calls.
- generate() never raises: errors are caught by safe_generate().
- Engines are stateless: do not mutate ctx or self.
- Registration: append YourEngine() to ENGINE_REGISTRY in orchestrator.py.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)


class BaseEngine(ABC):
    """Abstract base for all recommendation signal generators."""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable engine identifier. Used in logs and signal_id."""
        ...

    @property
    def enabled_config_key(self) -> str:
        """
        Dot-path into rules_cfg that enables/disables this engine.

        If empty string (default), the engine is always enabled.
        Example: "rule_5_equity_floor.enabled"
        """
        return ""

    def is_enabled(self, ctx: RecommendationContext) -> bool:
        """Return False if admin has disabled this engine via rules_config."""
        key = self.enabled_config_key
        if not key:
            return True
        parts = key.split(".")
        node = ctx.rules_cfg
        for part in parts:
            if not isinstance(node, dict):
                return True          # key path broken → default enabled
            node = node.get(part)
            if node is None:
                return True          # key missing → default enabled
        return bool(node)

    @abstractmethod
    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        Produce recommendation signals from context.

        Must be pure: no side-effects, no I/O, no mutation of ctx.
        """
        ...

    def safe_generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        Wrapper called by the orchestrator.

        Checks is_enabled(), calls generate(), catches all exceptions.
        A crashing engine produces zero signals — it never crashes the pipeline.
        """
        if not self.is_enabled(ctx):
            logger.debug("[%s] disabled by config — skipping", self.engine_name)
            return []
        try:
            signals = self.generate(ctx)
            logger.debug("[%s] emitted %d signal(s)", self.engine_name, len(signals))
            return signals
        except Exception as exc:
            logger.exception("[%s] generate() raised unexpectedly: %s", self.engine_name, exc)
            return []
