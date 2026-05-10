"""nidp.quality.replay — Historical Data Quality Replay & Backtesting Engine.

CLI:
    python -m nidp.quality.replay \\
        --start-date 2026-02-01 \\
        --end-date   2026-05-10 \\
        --domains    all \\
        --policy-version v1 \\
        --parallel   8 \\
        --inject-failures false \\
        --reset      true

The engine walks every trading day in the [start, end] range, re-runs
the existing quality_gate pipeline (Great Expectations + consistency
checks + scoring + gate decision + certification + quarantine) under a
named scoring policy, and persists per-date outcomes into
`audit.replay_runs` / `audit.replay_dates` / `audit.replay_statistics`.

Policies are versioned in `audit.policy_versions` and exchanged by
threading their weights through `compute_quality_score_with_policy()`.
"""
from .engine import (
    ReplayConfig,
    ReplayEngine,
    run_replay,
    list_trading_days,
)
from .policy import ScoringPolicy, get_policy, list_policies

__all__ = [
    "ReplayConfig", "ReplayEngine", "run_replay", "list_trading_days",
    "ScoringPolicy", "get_policy", "list_policies",
]
