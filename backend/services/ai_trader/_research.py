"""Lazy import of the research package, which sits at the repository root beside backend/ (same rule as
routes/research_chart.py: appended to sys.path only when it is there; otherwise the caller gets ResearchUnavailable)."""
from __future__ import annotations

import sys
from pathlib import Path


class ResearchUnavailable(RuntimeError):
    pass


def load():
    root = Path(__file__).resolve().parents[3]
    if (root / "research" / "charting" / "regime.py").is_file() and str(root) not in sys.path:
        sys.path.append(str(root))
    try:
        from research.charting import context, regime, research_window, resample
    except Exception as e:  # noqa: BLE001 - any import failure means the engine cannot answer
        raise ResearchUnavailable(str(e)) from e
    return context, regime, research_window, resample
