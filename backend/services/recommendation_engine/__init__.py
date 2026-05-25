"""
recommendation_engine — pluggable signal-based recommendation pipeline.

Phase 0: scaffolding only. engine_pipeline.enabled=False in rules_config
means _apply_action_rules() still runs the legacy sequential rule body.

Public API (stable across phases):
  context.RecommendationContext
  context.EngineSignal
  context.HoldingWeight
  base_engine.BaseEngine
"""
from services.recommendation_engine.context import (
    EngineSignal,
    HoldingWeight,
    RecommendationContext,
)
from services.recommendation_engine.base_engine import BaseEngine

__all__ = [
    "BaseEngine",
    "EngineSignal",
    "HoldingWeight",
    "RecommendationContext",
]
