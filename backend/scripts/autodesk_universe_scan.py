"""Read-only real-data scan timing for the desk universes (AD-SC-35). Runs the REAL AI Trader over the point-in-time market
view for each universe and prints one JSON document (counts, shadow blocks, seconds). No database, no writes, no secrets.

  usage (container from the staging backend image, worktree mounted read-only, DaaS env passed in):
    python scripts/autodesk_universe_scan.py FNO NIFTY500 TOTAL_MARKET
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "autodesk_universe_scan")
os.environ.setdefault("OPENAI_API_KEY", "placeholder")


async def scan(universe: str) -> dict:
    from autodesk import contracts as C
    from autodesk.agents.ai_trader import AITrader
    from autodesk.agents.base import AgentContext
    from autodesk.market.pit import PitMarketView
    from autodesk.market.calendar import next_session_for

    now = datetime.now(timezone.utc)
    view = PitMarketView(now)
    agent = AITrader()
    sd = next_session_for(now)
    ctx = AgentContext(tenant_id="t-scan", account={"account_id": "ACC-SCAN"}, policy={}, market=agent.restrict(view), as_of=now,
                       workflow_id="WF-SCAN", inputs={"session_date": sd.isoformat(), "universe": universe, "symbols": None,
                                                      "min_score": "50"})
    task = C.TaskSpec(workflow_id="WF-SCAN", tenant_id="t-scan", account_id="ACC-SCAN", to_agent=C.TASK_OWNER[C.TaskType.SCAN_MARKET],
                      task_type=C.TaskType.SCAN_MARKET, required_output_schema=C.TASK_OUTPUT_SCHEMA[C.TaskType.SCAN_MARKET])
    t0 = time.monotonic()
    res = await agent.run(task, ctx)
    secs = round(time.monotonic() - t0, 1)
    rep = C.ScanReport.model_validate(res.output)
    sh = rep.shadow or {}
    calls = view.tool_calls()
    return {"universe": universe, "scan_seconds": secs, "session_date": sd.isoformat(), "universe_size": rep.universe_size,
            "scanned": rep.scanned, "signals": len(rep.signals), "by_segment": dict(Counter(s.segment.value for s in rep.signals)),
            "by_category": dict(Counter(s.category.value for s in rep.signals)),
            "fno_eligible_signals": sum(1 for s in rep.signals if s.fno_eligible),
            "both_shadow_scores": sum(1 for s in rep.signals if len(s.shadow_scores) == 2),
            "signals_with_shadow": sum(1 for s in rep.signals if s.shadow_scores),
            "suppressed": len(rep.suppressed), "suppressed_reasons": Counter(
                (x["reason"].split(" ")[0] + " " + x["reason"].split(" ")[1]) if " " in x["reason"] else x["reason"]
                for x in rep.suppressed).most_common(5),
            "tool_calls": len(calls), "failed_calls": sum(1 for c in calls if not getattr(c, "ok", True)),
            "regime_missing": (rep.regime or {}).get("missing"),
            "shadow": {v: {k: b[k] for k in ("rules", "scored", "with_entry_signal", "error_count", "bands")} |
                       {"top5": [(c["instrument"], c["score"], c["band"]) for c in b["candidates"][:5]]}
                       for v, b in (sh.get("versions") or {}).items()}}


async def main() -> None:
    out = []
    for u in sys.argv[1:] or ["FNO"]:
        try:
            out.append(await scan(u))
        except Exception as e:  # noqa: BLE001 — reported, not hidden
            out.append({"universe": u, "error": f"{type(e).__name__}: {str(e)[:300]}"})
        print(json.dumps(out[-1], default=str), flush=True)


asyncio.run(main())
