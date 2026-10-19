"""Per-persona framing instructions injected into every specialist agent's system prompt.

The framing string is a 1–3 line preamble that tells the LLM how to adapt tone,
depth, and reference points for the user. Specialist nodes (portfolio, mf, risk,
goal, stock, market, recommendation) call `frame_for_persona(state.persona)` and
prepend the result to their base system prompt.

A question asked from the Smart trading desk's own Copilot (chat.py: body `surface: "trading_desk"`)
carries `state.desk_persona` ("trader" or "investor", the desk's wording switch). For those, the
framing adds the answer structure of the desk PRD §9.4 (docs/smart_trader) and, for "investor",
plain wording. It is an instruction to the model, not a template: a part with no data is left out.
"""
from __future__ import annotations

from typing import Optional


# Map every PersonaType.value to a framing block.
# Trader sub-types (swing/intraday/options) collapse into the active_trader framing.
_FRAMING: dict[str, str] = {
    "beginner_investor": (
        "User profile: Salaried Beginner Investor. "
        "Explain in plain language, avoid jargon, and use Fixed Deposit as the reference yardstick when discussing returns. "
        "Recommend one action at a time; do not overwhelm with options."
    ),
    "mutual_fund_investor": (
        "User profile: Mutual Fund Focused Investor. "
        "Go deep on fund-level analysis: scheme overlap, expense ratio (direct vs regular), category fit, manager tenure, AUM trend. "
        "Frame recommendations in terms of fund replacements, SIP optimisation, and category gaps."
    ),
    "stock_investor": (
        "User profile: Direct Equity Investor. "
        "Lead with valuation (P/E, P/B, ROE) and fundamentals; cite sector views and concentration when relevant. "
        "Be specific about which positions to add, hold, or exit."
    ),
    "active_trader": (
        "User profile: Active Trader (swing / intraday / options). "
        "Emphasise realised P&L, momentum, sector rotation, and position sizing. "
        "Be terse and decisive; avoid long-horizon framing."
    ),
    "swing_trader": (
        "User profile: Swing Trader. "
        "Emphasise short-to-medium holding period setups, momentum, sector rotation, risk-reward ratios, and stop-loss discipline."
    ),
    "intraday_trader": (
        "User profile: Intraday Trader. "
        "Emphasise same-day setups, volatility, liquidity, and strict risk management. Do not give long-horizon advice."
    ),
    "options_trader": (
        "User profile: Options Trader. "
        "Acknowledge derivatives context; focus on Greeks, IV, position sizing, and risk management. Do not recommend speculative naked positions."
    ),
    "hni_investor": (
        "User profile: High Net Worth Investor. "
        "Use a multi-asset framing across equity, debt, gold, international, and alternatives. "
        "Tax efficiency, estate planning, and PMS/AIF considerations are first-class concerns."
    ),
    "retirement_planner": (
        "User profile: Retirement Planner. "
        "Lead with income-stability, withdrawal-rate safety, and inflation protection. "
        "Bias toward downside risk and debt allocation; flag any aggressive positioning."
    ),
    "parents_planning": (
        "User profile: Parent Planning for Children. "
        "Frame every answer around the linked education or marriage goal: goal-progress, shortfall, and time-horizon. "
        "Surface insurance overlays for goal protection where relevant."
    ),
    "tax_saver": (
        "User profile: Tax-Conscious Investor. "
        "Apply a tax-impact lens to every recommendation. "
        "Cite STCG / LTCG implications, the ₹1.25L LTCG exemption, indexation, and harvest-vs-hold trade-offs."
    ),
    "conservative_investor": (
        "User profile: Conservative Investor. "
        "Lead with capital preservation and downside risk. "
        "Use FD as the comparable yardstick; favour debt and hybrid options over high-volatility equity."
    ),
    "nri_investor": (
        "User profile: NRI / Global Investor. "
        "Acknowledge currency exposure (INR vs base currency), geographic allocation, and NRI-specific tax treatment (TDS, DTAA, Section 195). "
        "Discuss India vs global allocation trade-offs."
    ),
    "mfd_advisor": (
        "User profile: MFD / Financial Advisor (acting on behalf of a client). "
        "Be analytically rigorous; surface tax-aware, suitability-driven recommendations the advisor can defend to the client."
    ),
    "retail_investor": (
        "User profile: Retail Investor. "
        "Use clear, accessible language. Balance depth with brevity; avoid over-personalised assumptions."
    ),
}


# Fallback framing when persona is unknown / not set.
_DEFAULT_FRAMING = _FRAMING["retail_investor"]


# The desk's two wordings (TRADER / INVESTOR switch in the desk header).
DESK_PERSONAS = ("trader", "investor")

# Smart trading desk PRD §9.4: the answer structure, "where applicable".
DESK_ANSWER_STRUCTURE = (
    "This question was asked from the Smart trading desk. Where it applies, answer in this order, "
    "each part under a short bold label: "
    "1) Direct answer: one or two sentences. "
    "2) Evidence: the figures the tools returned, each with its source. "
    "3) As of: the date or time of those figures; say 'end of day' or 'delayed' where true, and never call a figure live unless the tool says it is. "
    "4) Bullish factors and bearish factors. "
    "5) Key uncertainties. "
    "6) What would invalidate this view. "
    "7) Sources: only the sources the tools returned; never invent a citation. "
    "8) Where to look: the desk tab with the underlying analysis (Overview, AI Scanner, Market Intelligence, "
    "Chart Analysis or Portfolio & Risk), naming the stock where there is one. "
    "Leave out a part that does not apply or has no data, and say plainly when data is missing or stale; "
    "never fill a part with a guess. Keep facts and your interpretation apart. "
    "A rules-based scanner score is not a probability, and the move-odds model's probabilities are for the next session only. "
    "Explain evidence and risk; do not tell the user to buy or sell, and Nivesh cannot place orders."
)

DESK_PLAIN_WORDING = (
    "The user chose plain wording on the desk: avoid jargon, explain any technical term in a few words, "
    "and prefer everyday phrases (for example '50-day average' rather than 'SMA 50')."
)


def frame_for_persona(persona: Optional[str], desk_persona: Optional[str] = None) -> str:
    """Return the framing preamble for a persona code.

    Unknown or None personas fall back to the retail-investor framing so the
    LLM still receives a sensible tone instruction. `desk_persona` ("trader" or
    "investor") is set only for questions from the Smart trading desk's Copilot;
    it adds the desk's answer structure (PRD §9.4), and plain wording for "investor".
    Any other value is ignored.
    """
    base = _FRAMING.get(persona, _DEFAULT_FRAMING) if persona else _DEFAULT_FRAMING
    if desk_persona not in DESK_PERSONAS:
        return base
    parts = [base, DESK_ANSWER_STRUCTURE]
    if desk_persona == "investor":
        parts.append(DESK_PLAIN_WORDING)
    return "\n\n".join(parts)


def known_personas() -> list[str]:
    """All persona codes that have explicit framing (for tests and admin tooling)."""
    return list(_FRAMING.keys())
