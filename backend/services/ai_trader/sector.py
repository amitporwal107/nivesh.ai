"""Sector rotation table as Evidence (PRD F3): each sector index's relative strength against NIFTY 500, ranked.
Relative strength is research.charting.regime.relative_strength (simple-return difference), unchanged."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import _research
from .evidence import UNCALIBRATED_CONFIDENCE, Evidence, unavailable

SKILL = "market_intelligence"
BENCHMARK = "NIFTY 500"
NOT_SECTORS = {"NIFTY_500", "NIFTY_50", "INDIA_VIX", "BREADTH_UNIVERSE", "NIFTY_MIDCAP_150", "NIFTY_SMLCAP_250"}
WINDOWS = (20, 60)


def sector_index_names(ctx) -> List[str]:
    folder = Path(ctx.DEFAULT_INDEX_HISTORY_DIR)
    return sorted(p.stem.replace("_", " ") for p in folder.glob("NIFTY_*.csv") if p.stem not in NOT_SECTORS)


def sector_rotation(as_of: str) -> List[Evidence]:
    """One Evidence per sector index, ranked by 20-session relative strength (rank 1 = strongest). A sector whose
    window cannot be measured is returned UNAVAILABLE and left out of the ranking."""
    ctx, regime, _rw, _rs = _research.load()
    import pandas as pd

    ts = pd.Timestamp(as_of).normalize()
    bench = ctx.load_index_history(BENCHMARK)
    rows: List[Dict[str, Any]] = []
    out: List[Evidence] = []
    for name in sector_index_names(ctx):
        src = [{"name": f"research/index_history/data/{name.replace(' ', '_')}.csv", "timestamp": as_of}]
        rs = regime.relative_strength(ctx.load_index_history(name), bench, ts, windows=WINDOWS)
        r20, r60 = rs["rs_20"], rs["rs_60"]
        if r20.status != "OK":
            out.append(unavailable(SKILL, None, as_of, "20d", f"{name} relative strength", r20.reason, src))
            continue
        rows.append({"name": name, "rs_20": r20.value, "rs_60": r60.value if r60.status == "OK" else None, "src": src})

    rows.sort(key=lambda r: r["rs_20"], reverse=True)
    total = len(rows)
    ranked: List[Evidence] = []
    for i, r in enumerate(rows, start=1):
        leading = r["rs_20"] > 0
        improving = r["rs_60"] is not None and r["rs_20"] > r["rs_60"]
        ranked.append(Evidence(
            skill=SKILL, symbol=None, as_of=as_of, horizon="20d",
            observation=f"{r['name']} is rank {i} of {total} sectors; 20-session return minus {BENCHMARK}: "
                        f"{r['rs_20'] * 100:+.2f} pts.",
            interpretation=("Leading the market" if leading else "Lagging the market")
                           + (" and improving versus its 60-session trend." if improving else "."),
            confidence=UNCALIBRATED_CONFIDENCE, decision_impact="supports" if leading else "opposes",
            sources=r["src"], conditions=["Rank changes with every session's close."],
            data={"sector": r["name"], "rank": i, "of": total, "rs_20": r["rs_20"], "rs_60": r["rs_60"]},
        ))
    return ranked + out
