"""Policy-impact agent node (Nivesh Copilot) — R5-B foundation.

Answers tax / trade / budget policy questions (PL-1 GST, PL-2 anti-dumping,
PL-5 Budget, PL-6 US tariffs) of the form "how does <policy> affect <sector>" /
"which companies are affected by <policy>".

DATA-TRUST DESIGN (the whole point of this node):
- The policy → sector mapping is the analytical, hallucination-prone part. It is
  therefore grounded in a CURATED, sourced rule set (`_POLICY_RULES`) — editorial
  content, versioned in code — and NEVER inferred by an LLM. The answer is built
  DETERMINISTICALLY from the matched rule + a real company list pulled from the NIDP
  screener (existing infra) for the affected sector. No LLM writes the policy claim,
  so it cannot fabricate one.
- Every answer is a DIRECTIONAL mapping, not a claim about the specific current
  notification, and is caveated: verify the exact scope/rate at source; sector
  membership ≠ per-company material impact; the precise sub-segment is a subset of
  the broader sector shown (the known granularity gap).
- If NO curated rule matches, the node says so plainly and does NOT invent a
  policy → company mapping.

The curated rule CONTENT here is a small, directional starter set. Authoring the
full, current, sub-segment-precise mapping + live policy-source ingestion is the
domain-curated follow-on (see test_reports/PRD_r5b_policy_intelligence.md).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_core.messages import AIMessage

from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)


# ── Curated policy → sector impact rules (directional, sourced) ──────────────
# Each rule: keyword regex that identifies the policy in a query, the affected
# nidp sector_master.sector value (what the screener filters on), the precise
# sub-segment the policy is really about, the DIRECTIONAL impact, a plain-English
# rationale, and a source pointer. `direction` is 'positive' | 'negative' |
# 'conditional' (depends on cut vs hike / scope). These are economic directional
# relationships, deliberately NOT specific-current-event claims.
_POLICY_RULES = [
    {
        "id": "antidumping_steel",
        "kw": r"anti[\s-]?dumping|safeguard\s+dut\w*",
        "needs": r"steel|metal",
        "subject": "steel",
        "sector": "Metals",
        "direction": "positive",
        "rationale": ("An anti-dumping / safeguard duty raises the landed cost of imported steel, "
                      "shifting demand toward domestic producers — directionally POSITIVE for "
                      "domestic steel makers. Downstream steel USERS (autos, capital goods) face "
                      "higher input costs — directionally negative for them."),
        "source": "DGTR final finding + CBIC customs notification",
    },
    {
        "id": "antidumping_generic",
        "kw": r"anti[\s-]?dumping|safeguard\s+dut\w*",
        "needs": None,
        "subject": "the affected commodity",
        "sector": None,   # unknown commodity → no company list, directional principle only
        "direction": "positive",
        "rationale": ("An anti-dumping / safeguard duty on imports of a commodity is directionally "
                      "POSITIVE for domestic producers of that commodity (import competition eases) "
                      "and negative for domestic industries that consume it as an input."),
        "source": "DGTR final finding + CBIC customs notification",
    },
    {
        "id": "import_tariff_pharma_export",
        "kw": r"tariffs?|import\s+dut\w*|trade\s+barrier",
        "needs": r"pharma|drug|generic|us\b|american|export",
        "subject": "Indian pharma exporters",
        "sector": "Healthcare",
        "direction": "negative",
        "rationale": ("A foreign (e.g. US) import tariff on Indian goods raises the price of those "
                      "goods abroad, pressuring Indian EXPORTERS' volumes/margins in that market — "
                      "directionally NEGATIVE for India-listed exporters with high revenue exposure "
                      "to that geography."),
        "source": "USTR / foreign customs notification + company export-mix disclosures",
    },
    {
        "id": "gst_auto",
        "kw": r"\bgst\b",
        "needs": r"auto|vehicle|car|component",
        "subject": "auto & auto-component makers",
        "sector": "Automobile",
        "direction": "conditional",
        "rationale": ("A GST rate CUT on a product lowers its price and lifts demand — directionally "
                      "POSITIVE for its makers; a rate HIKE does the opposite. Confirm whether the "
                      "specific change is a cut or a hike, and exactly which products/HSN codes it "
                      "covers, before drawing a conclusion."),
        "source": "GST Council decision + CBIC rate notification",
    },
    {
        "id": "gst_generic",
        "kw": r"\bgst\b",
        "needs": None,
        "subject": "makers of the affected product",
        "sector": None,
        "direction": "conditional",
        "rationale": ("A GST rate CUT lifts demand for a product (positive for its makers); a HIKE "
                      "curbs it (negative). Impact hinges on which products/HSN codes the change "
                      "covers and whether it is a cut or a hike."),
        "source": "GST Council decision + CBIC rate notification",
    },
    {
        "id": "budget_renewables",
        "kw": r"union\s+budget|budget\b|\bpli\b|production[\s-]?linked|subsid\w*",
        "needs": r"renewable|solar|wind|green|clean\s+energy|power",
        "subject": "renewable-energy companies",
        "sector": "Power",
        "direction": "positive",
        "rationale": ("A Budget capex push, PLI allocation, or subsidy for renewables improves demand "
                      "visibility and project economics — directionally POSITIVE for renewable-energy "
                      "players. The magnitude depends on the specific allocation and its beneficiaries."),
        "source": "Union Budget documents + scheme notification",
    },
]


def _match_rule(text: str) -> Optional[dict]:
    """Return the most specific curated rule whose keyword AND (if set) 'needs'
    context appear in the query. Specific rules (with a 'needs' filter) are
    preferred over their generic fallback."""
    t = text or ""
    specific, generic = None, None
    for rule in _POLICY_RULES:
        if not re.search(rule["kw"], t, re.IGNORECASE):
            continue
        if rule["needs"] is None:
            generic = generic or rule
        elif re.search(rule["needs"], t, re.IGNORECASE):
            specific = specific or rule
    return specific or generic


async def _sector_company_examples(sector: Optional[str], limit: int = 12) -> list[str]:
    """Pull real Nifty-500 company tickers in `sector` from the NIDP screener
    (existing infra). Best-effort — returns [] if the sector is unknown or the
    source is unreachable, and the node still gives the directional answer."""
    if not sector:
        return []
    try:
        import importlib
        intel = importlib.import_module("services.copilot_tools.stock_intelligence")
        fetched = await intel.nidp_stock_screener(sector=sector, universe="Nifty 500", limit=limit)
        rows = fetched.get("rows") or []
        out = []
        for r in rows:
            sym = r.get("symbol") or r.get("ticker")
            if sym:
                out.append(str(sym))
        return out
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("policy: sector company fetch failed for %s: %s", sector, exc)
        return []


_DEFLECTION = (
    "I don't have a curated impact mapping for that specific policy, and I don't infer "
    "policy → company links from scratch — that would be guesswork, which I won't present "
    "as fact. I can currently give the DIRECTIONAL impact for: anti-dumping / safeguard "
    "duties, import & export tariffs, GST rate changes, and Budget / PLI sector pushes. "
    "For anything else, please check the source directly (DGTR, CBIC, GST Council, or the "
    "Union Budget documents)."
)


def _build_answer(rule: dict, companies: list[str]) -> str:
    dir_label = {
        "positive": "directionally POSITIVE",
        "negative": "directionally NEGATIVE",
        "conditional": "conditional (depends on the specifics — see below)",
    }.get(rule["direction"], rule["direction"])

    lines = [
        f"**{rule['subject'].capitalize()} — directional policy impact**",
        "",
        rule["rationale"],
        "",
        f"Net read: {dir_label}.",
    ]
    if rule["sector"] and companies:
        shown = ", ".join(companies[:12])
        lines += [
            "",
            f"{rule['sector']}-sector names in the Nifty 500 (illustrative, not a buy list): {shown}.",
        ]
    lines += [
        "",
        "⚠️ This is a **directional, curated mapping — not a claim about the specific current "
        f"notification**. Verify the exact scope, products/rate and effective date in the "
        f"{rule['source']}. Sector membership does not mean each company is materially affected, "
        f"and the precise sub-segment (\"{rule['subject']}\") is a subset of the broader "
        f"{rule['sector'] or 'sector'} shown — company-level exposure needs its own check.",
    ]
    return "\n".join(lines)


async def policy_node(state: CopilotState) -> dict:
    """Grounded, deterministic policy-impact answer (no LLM writes the mapping)."""
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "",
    )

    rule = _match_rule(user_msg)
    if rule is None:
        answer_text = _DEFLECTION
        tool_results = [ToolResult(
            ok=True, tool_name="policy_impact",
            summary="No curated policy→sector rule matched — honest deflection (no invention).",
        )]
    else:
        companies = await _sector_company_examples(rule.get("sector"))
        answer_text = _build_answer(rule, companies)
        tool_results = [ToolResult(
            ok=True, tool_name="policy_impact",
            summary=(f"Curated policy rule '{rule['id']}' → sector={rule.get('sector')} "
                     f"direction={rule['direction']} ({len(companies)} example names)"),
            data={"rule_id": rule["id"], "sector": rule.get("sector"),
                  "direction": rule["direction"], "source": rule["source"]},
            rows=[{"symbol": c} for c in companies],
        )]

    response = AgentResponse(
        agent=AgentName.POLICY,
        text=answer_text,
        widget_type=WidgetType.NONE,
        widget_data={},
        tool_results=tool_results,
    )
    return {
        "tool_results": tool_results,
        "response": response,
        "messages": [AIMessage(content=answer_text)],
    }
