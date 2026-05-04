"""Shared chart-block protocol for Copilot-style responses.

Tells the LLM how to emit structured chart specs inside its markdown
output, and validates / sanitises the response server-side. The
frontend (`parseCopilotChartBlocks` + `ChartBlock`) renders the
fenced ```chart``` blocks as Recharts visuals.

Used by:
  - `routes/copilot.py`           (legacy MFD copilot endpoint)
  - `routes/chat.py`              (Nivesh Copilot chat — `/chat/send`,
                                   `/chat/stream`)
  - `services/ai_engine.py`       (single-portfolio system prompt)

Schema is intentionally narrow (4 chart types, single-series with
optional `series` field for stacking) so the prompt + parser stay
simple in v1.
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# Appended to the Copilot/Chat/Advisor system prompts. Tells the model
# WHEN to emit a chart and exactly WHAT shape it must take.
CHART_PROTOCOL = (
    "\n\n── CHART PROTOCOL ──\n"
    "You may emit visual charts inside your markdown answer. Embed them as "
    "fenced code blocks with language `chart` containing valid JSON.\n\n"
    "WHEN TO EMIT:\n"
    "  • The user explicitly asks to 'show', 'chart', 'plot', 'graph', "
    "'visualise', or 'compare' something — ALWAYS emit a chart.\n"
    "  • You are answering a comparative/distribution question (top exposures, "
    "AMC / sector / category / asset-class breakdown, allocation drift, "
    "performance over time) AND ≥ 2 numeric data points are visible in the "
    "PORTFOLIO INTELLIGENCE / CONTEXT block above.\n"
    "  • If the data needed isn't in the context, do NOT fabricate it — "
    "answer in prose and skip the chart.\n\n"
    "SCHEMA (strict — invalid blocks are dropped server-side):\n"
    "  type: \"bar\" | \"donut\" | \"line\" | \"stacked_bar\"\n"
    "  title: string (≤ 60 chars)\n"
    "  unit: optional string (e.g. \"%\", \"₹L\", \"₹Cr\")\n"
    "  x_label / y_label: optional strings\n"
    "  data: array of {label: string, value: number, series?: string} — "
    "MIN 2, MAX 6 points; for stacked_bar / multi-series line, `series` groups them.\n"
    "  highlight: optional array of label strings rendered in warning color "
    "(use this for over-concentration, e.g. AMCs above the 15% threshold).\n\n"
    "RULES:\n"
    "  • At most 2 chart blocks per response.\n"
    "  • `value` must be a plain number — no %, no commas, no ₹ symbol.\n"
    "  • Always keep your prose answer alongside; charts are ADDITIVE, never a replacement.\n"
    "  • Wrap exactly like this (no language alias, no JSON5, no comments):\n"
    "```chart\n"
    "{\"type\":\"bar\",\"title\":\"AMC concentration\",\"unit\":\"%\","
    "\"data\":[{\"label\":\"HDFC\",\"value\":31.2},{\"label\":\"Nippon\",\"value\":27.5},"
    "{\"label\":\"Axis\",\"value\":14.0}],\"highlight\":[\"HDFC\",\"Nippon\"]}\n"
    "```\n"
)


_CHART_BLOCK_RE = re.compile(r"```chart\s*\n(?P<body>.*?)```", re.DOTALL)
_VALID_CHART_TYPES = {"bar", "donut", "line", "stacked_bar"}
_MAX_CHART_POINTS = 6


def validate_chart_blocks(text: str) -> Dict[str, Any]:
    """Parse every ```chart``` block in `text`, validate the JSON, and
    rewrite any malformed block to a plain ```text``` fence (so the
    frontend parser doesn't choke on it). Returns
        {clean_text, valid_count, invalid_specs}
    so the caller can both ship the cleaned response and log bad specs
    for prompt iteration.
    """
    invalid: List[Dict[str, Any]] = []
    valid = 0

    def _validate(match: "re.Match[str]") -> str:
        nonlocal valid
        body = match.group("body").strip()
        try:
            spec = json.loads(body)
        except Exception as e:  # noqa: BLE001
            invalid.append({"reason": f"json: {e}", "body": body[:400]})
            return f"```text\n{body}\n```"
        if not isinstance(spec, dict):
            invalid.append({"reason": "not an object", "body": body[:400]})
            return f"```text\n{body}\n```"
        ctype = spec.get("type")
        if ctype not in _VALID_CHART_TYPES:
            invalid.append({"reason": f"bad type {ctype!r}", "body": body[:400]})
            return f"```text\n{body}\n```"
        data = spec.get("data")
        if not isinstance(data, list) or len(data) < 2:
            invalid.append({"reason": "data missing or < 2 points", "body": body[:400]})
            return f"```text\n{body}\n```"
        if len(data) > _MAX_CHART_POINTS:
            spec["data"] = data[:_MAX_CHART_POINTS]
            data = spec["data"]
        for i, pt in enumerate(data):
            if not isinstance(pt, dict) or "label" not in pt or "value" not in pt:
                invalid.append({"reason": f"data[{i}] missing label/value", "body": body[:400]})
                return f"```text\n{body}\n```"
            try:
                pt["value"] = float(pt["value"])
            except Exception:  # noqa: BLE001
                invalid.append({"reason": f"data[{i}].value not numeric", "body": body[:400]})
                return f"```text\n{body}\n```"
        valid += 1
        return "```chart\n" + json.dumps(spec, separators=(",", ":")) + "\n```"

    cleaned = _CHART_BLOCK_RE.sub(_validate, text)
    return {"clean_text": cleaned, "valid_count": valid, "invalid_specs": invalid}


async def log_invalid_chart_specs(db, user_id: str, model: str, route: str,
                                    invalid: List[Dict[str, Any]]) -> None:
    """Persist bad chart specs to a Mongo collection so we can iterate
    the prompt. Best-effort — logging never blocks the response."""
    if not invalid:
        return
    try:
        await db.copilot_chart_invalid.insert_one({
            "user_id": user_id,
            "model": model,
            "route": route,
            "specs": invalid[:5],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:  # noqa: BLE001
        pass
