"""Deterministic chart spec generation.

The LLM does NOT decide chart shape or values — the retrieval layer
produces a `Retrieval` with rows, and this module turns those rows into
a chart spec matching the same schema [`services/copilot_charts.py`]
already validates. The LLM just gets the prose paragraph and the
chart spec rides along separately in the API response.

This is the key win over the previous approach: the chart's labels
and numbers are guaranteed to match the leaderboard the LLM is
describing — no drift, no hallucinated bars.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


def for_concentration(
    rows: List[Dict[str, Any]],
    grouping: str,
    *,
    title: Optional[str] = None,
    highlight_threshold_pct: float = 15.0,
) -> Dict[str, Any]:
    """Donut for AMC / sector / category / asset-class breakdowns
    (where slices represent shares of a whole). For company exposure
    we use a bar chart instead — the top-N companies typically sum to
    much less than 100% of equity (long tail), so a donut is misleading.
    Highlights anything above `highlight_threshold_pct`."""
    title = title or {
        "amc": "AMC concentration (% of MF AUM)",
        "sector": "Sector mix (look-through, % of equity exposure)",
        "category": "Fund category mix (% of MF AUM)",
        "asset_class": "Asset class mix (% of total portfolio)",
        "company": "Top company exposures (look-through, % of equity)",
    }.get(grouping, "Concentration")
    chart_type = "bar" if grouping == "company" else "donut"
    return {
        "type": chart_type,
        "title": title,
        "unit": "%",
        "data": [{"label": r["label"][:32], "value": float(r["value"])}
                 for r in rows[:6 if chart_type == "donut" else 8]],
        "highlight": [r["label"] for r in rows
                      if float(r.get("value") or 0) >= highlight_threshold_pct],
    }


def for_ranking(
    rows: List[Dict[str, Any]],
    metric: str,
    *,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Bar chart for ranking results. Y-axis maps to the metric."""
    if metric == "return":
        title = title or "Top holdings by return %"
        data = [{"label": r["name"][:32], "value": r["return_pct"]} for r in rows[:6]]
        unit = "%"
    elif metric == "profit":
        title = title or "Top holdings by ₹ profit"
        # ₹L (lakhs) for readability when amounts are large
        scale = 1.0
        max_abs = max((abs(r["profit_rs"]) for r in rows), default=0)
        unit = "₹"
        if max_abs >= 100000:
            scale = 1.0 / 100000
            unit = "₹L"
        data = [{"label": r["name"][:32], "value": round(r["profit_rs"] * scale, 2)} for r in rows[:6]]
    elif metric == "loss":
        title = title or "Worst-performing holdings (₹ loss)"
        unit = "₹"
        data = [{"label": r["name"][:32], "value": round(r["profit_rs"], 0)} for r in rows[:6]]
    elif metric == "value":
        title = title or "Largest holdings by current value"
        scale = 1.0 / 100000
        unit = "₹L"
        data = [{"label": r["name"][:32], "value": round(r["current_value_rs"] * scale, 2)}
                for r in rows[:6]]
    else:
        title = title or f"Top holdings by {metric}"
        unit = ""
        data = []

    spec: Dict[str, Any] = {
        "type": "bar",
        "title": title,
        "unit": unit,
        "data": data,
    }
    # Highlight negative bars in red for loss chart
    if metric == "loss":
        spec["highlight"] = [d["label"] for d in data if d["value"] < 0]
    return spec


def for_health(retrieval_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bar of component scores."""
    return {
        "type": "bar",
        "title": "Health components (0-100)",
        "unit": "",
        "data": [{"label": r["component"][:24], "value": r["score"]}
                 for r in retrieval_rows[:6]],
        "highlight": [r["component"] for r in retrieval_rows if r["score"] < 50],
    }


def for_drift(retrieval_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bar chart contrasting current vs target % per asset class.
    Uses the `series` field so the renderer draws side-by-side bars."""
    data: List[Dict[str, Any]] = []
    for r in retrieval_rows:
        data.append({"label": r["asset"], "value": float(r["current_pct"]), "series": "Current"})
        data.append({"label": r["asset"], "value": float(r["target_pct"]), "series": "Target"})
    highlight = [r["asset"] for r in retrieval_rows if r.get("trigger") == "hard"]
    return {
        "type": "stacked_bar",
        "title": "Allocation drift — current vs target (%)",
        "unit": "%",
        "data": data,
        "highlight": highlight,
    }


def for_goals(retrieval_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bar showing on-track % per goal — under 60% is highlighted."""
    return {
        "type": "bar",
        "title": "Goals — on-track %",
        "unit": "%",
        "data": [{"label": r["name"][:24], "value": r["on_track_pct"]}
                 for r in retrieval_rows[:6]],
        "highlight": [r["name"] for r in retrieval_rows if r["on_track_pct"] < 60],
    }
