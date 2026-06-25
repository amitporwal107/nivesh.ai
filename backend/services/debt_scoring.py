"""Debt MF scorer — executes the governed debt scoring model.

Reads config/debt_scoring_model.yaml (the faithful encoding of the Investment
team's debt scoring workbook) and scores a debt scheme from its NIDP primitives.
Parameters whose data isn't available today (the disclosure-bound ones) are
skipped; the remaining weight is redistributed and a coverage % is reported, so
the score is honest about how much of the model it could actually evaluate.

Ranking is WITHIN one SEBI category (compare like with like), per the model.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "debt_scoring_model.yaml")


@lru_cache(maxsize=1)
def _model() -> Dict[str, Any]:
    with open(_MODEL_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def reload() -> None:
    _model.cache_clear()


def _weight_set(sub_category: str) -> Dict[int, float]:
    m = _model()
    sub = (sub_category or "").lower()
    for rule in m.get("category_weight_map", []):
        if rule["match"] in sub:
            return {int(k): float(v) for k, v in m["weight_sets"][rule["set"]].items()}
    return {int(k): float(v) for k, v in m["weight_sets"]["default"].items()}


def _score_value(value: Optional[float], direction: str, thresholds: List[float]) -> Optional[int]:
    """Map a raw value to a 1-5 sub-score via the rubric thresholds [t5,t4,t3,t2]."""
    if value is None:
        return None
    v = float(value)
    if direction == "up":
        for s, t in zip((5, 4, 3, 2), thresholds):
            if v >= t:
                return s
        return 1
    for s, t in zip((5, 4, 3, 2), thresholds):  # down: lower is better
        if v <= t:
            return s
    return 1


def _grade(composite_5: float) -> str:
    for band in _model().get("grade_bands", []):
        if composite_5 >= float(band["min"]):
            return band["label"]
    return "D Avoid"


def score_fund(primitives: Dict[str, Any], sub_category: str) -> Dict[str, Any]:
    """Score one debt scheme. `primitives` is a v_v3_mf_primitives row (dict)."""
    m = _model()
    weights = _weight_set(sub_category)
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    num = 0.0          # sum(weight * score)
    cov_weight = 0.0   # sum(weight) over scored params

    for p in m["parameters"]:
        pid = int(p["id"])
        w = weights.get(pid, 0.0)
        raw = None
        if p.get("available") and p.get("source"):
            raw = primitives.get(p["source"])
            if p["key"] == "max_drawdown_3y" and raw is not None:
                raw = abs(float(raw))   # model uses drawdown magnitude
        score = _score_value(raw, p["direction"], p["thresholds"]) if raw is not None else None
        if score is None:
            missing.append(p["key"])
        else:
            num += w * score
            cov_weight += w
        rows.append({"key": p["key"], "label": p["label"], "weight": round(w, 3),
                     "raw": raw, "score": score})

    composite_5 = round(num / cov_weight, 2) if cov_weight > 0 else None
    return {
        "sub_category": sub_category,
        "composite_5": composite_5,
        "composite_100": round(composite_5 / 5 * 100, 1) if composite_5 is not None else None,
        "grade": _grade(composite_5) if composite_5 is not None else None,
        "coverage_pct": round(cov_weight * 100, 0),   # fraction of model weight evaluated
        "parameters": rows,
        "missing": missing,
        "model_version": m.get("meta", {}).get("version"),
    }


def rank_peers(funds: List[Dict[str, Any]], sub_category: str) -> List[Dict[str, Any]]:
    """Score + rank a peer set within ONE SEBI category (highest composite = rank 1)."""
    scored = []
    for f in funds:
        s = score_fund(f, sub_category)
        s["scheme_name"] = f.get("scheme_name")
        scored.append(s)
    scored.sort(key=lambda x: (x["composite_5"] is not None, x["composite_5"] or 0), reverse=True)
    for i, s in enumerate(scored, 1):
        s["rank"] = i
    return scored
