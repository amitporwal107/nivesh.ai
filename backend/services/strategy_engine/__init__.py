"""Strategy Builder engine — multi-asset strategy authoring + execution.

Public surface:
    dsl                — DSL parser + validator
    compiler_stock     — DSL → SQL for stock universes
    backtest           — historical sweep
    runner             — daily live execution (Phase 3)
    scoring_stock      — composite scoring (Phase 2)
    scoring_mf         — wraps services/v3_scoring (Phase 2)
"""
from . import dsl  # noqa: F401
