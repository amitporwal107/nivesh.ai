"""Move odds — Diagnostics section (owner decision 2026-09-17 ~12:10 IST, decisions-log): the four rejected entry setups,
shown as research results only. The numbers come from the committed snapshot move_odds_setup_diagnostics.json, generated
from the pre-registered backtest by docs/ai_research/tpd3/entry_setups/make_page_diagnostics.py; nothing is computed here.
A missing or malformed snapshot yields None so the route answers 503 instead of showing partial numbers."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
SNAPSHOT = Path(__file__).with_name("move_odds_setup_diagnostics.json")
ORDER = ["A", "B", "C", "D"]
STATUSES = {"not_validated", "research_only_insufficient_sample"}


def _valid(d: dict) -> bool:
    if not re.fullmatch(r"[0-9a-f]{64}", str(d.get("source_sha256", ""))):
        return False
    study = d.get("study") or {}
    if not all(isinstance(study.get(k), str) for k in ("first_signal_day", "last_signal_day", "universe", "exits", "rule", "baseline")):
        return False
    setups = d.get("setups")
    if not isinstance(setups, list) or [s.get("id") for s in setups] != ORDER:
        return False
    for s in setups:
        if s.get("status") not in STATUSES or not all(isinstance(s.get(k), str) and s[k] for k in ("name", "status_label", "headline", "research_status", "explanation")):
            return False
        trades = s.get("trades")
        if not isinstance(trades, list) or [t.get("trade") for t in trades] != ["5%", "10%"]:
            return False
        for t in trades:
            if t.get("validation") != "failed" or not isinstance(t.get("trades"), int) or not isinstance(t.get("baseline_mean_net"), (int, float)):
                return False
            if t["trades"] > 0 and not isinstance(t.get("mean_net"), (int, float)):
                return False
    return True


def load_setup_diagnostics(path: Path = SNAPSHOT) -> Optional[dict]:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        logger.warning("move-odds diagnostics snapshot unreadable (%s): %s", path, e)
        return None
    if not isinstance(d, dict) or not _valid(d):
        logger.warning("move-odds diagnostics snapshot failed validation (%s)", path)
        return None
    return {k: v for k, v in d.items() if not k.startswith("_")}
