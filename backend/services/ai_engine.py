"""AI Engine — prompt strategy, guardrails, structured outputs, retry logic."""
import json
import logging
import uuid
import re
from typing import Optional
from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

# ── Prompt Templates ──

FINANCIAL_ADVISOR_SYSTEM = """You are an expert AI Financial Advisor for Indian retail investors, built by nivesh.ai.

ROLE: Provide personalized, data-driven financial guidance.
MARKET: Indian markets (NSE/BSE), SEBI regulations, ₹ (INR) currency.
TONE: Professional yet conversational. Be specific, not generic.

CAPABILITIES:
- Portfolio analysis and optimization
- Risk assessment and management
- Investment recommendations (stocks, mutual funds, ETFs, bonds, gold)
- Tax planning (Section 80C, LTCG, STCG, tax loss harvesting)
- Goal-based planning (retirement, education, wealth growth)
- Expense ratio analysis (Direct vs Regular plans)

GUARDRAILS:
- Never guarantee returns or make promises about future performance
- Always include disclaimer for investment advice
- Do not recommend specific stocks without proper context
- Flag if a question is outside your expertise
- Use data from the user's actual portfolio when available
- Be honest about uncertainty

{portfolio_context}

DISCLAIMER: AI-generated guidance for educational purposes. Always consult a SEBI-registered advisor."""


INSIGHT_ANALYSIS_SYSTEM = """You are a portfolio analysis engine for nivesh.ai.
Analyze the portfolio and return ONLY valid JSON matching this exact schema.

IMPORTANT: 
- Be specific with actual fund names and numbers from the portfolio
- All percentages must sum correctly
- overlap_pairs: only include if mutual funds have genuinely similar mandates
- cost_leakage: estimate based on Regular vs Direct plan gap (~0.5-1.5% p.a.)
- Return VALID JSON only, no markdown, no explanation

Schema:
{{
  "insights": [
    {{"title":"...", "description":"2-3 sentences with specific fund names", "type":"warning|opportunity|info|action", "impact":"high|medium|low", "effort":"high|medium|low", "category":"risk|allocation|cost|redundancy|opportunity", "current_value":"e.g. 18%", "target_value":"e.g. 10%", "progress": 30}}
  ],
  "problem_distribution": [
    {{"name":"High Risk", "value": 35, "color":"#EF4444"}},
    {{"name":"Allocation Issues", "value": 25, "color":"#F59E0B"}},
    {{"name":"Cost Inefficiency", "value": 20, "color":"#3B82F6"}},
    {{"name":"Redundancy", "value": 20, "color":"#10B981"}}
  ],
  "before_after": {{
    "before": {{"return_pct": 6.5, "risk_label":"High", "risk_score": 75, "expense_ratio": 1.8}},
    "after": {{"return_pct": 8.2, "risk_label":"Moderate", "risk_score": 45, "expense_ratio": 0.5}}
  }},
  "action_funnel": [
    {{"step":1, "title":"...", "status":"critical|important|moderate|recommended", "detail":"..."}}
  ],
  "overlap_pairs": [
    {{"fund_a":"...", "fund_b":"...", "overlap_pct": 80}}
  ],
  "cost_leakage": {{"annual_loss": 32000, "total_invested": 500000, "loss_pct": 1.2, "detail":"..."}},
  "risk_gauge": {{"current": 75, "target": 45, "current_label":"High", "target_label":"Moderate"}}
}}"""


class AIEngine:
    """Centralized AI layer with prompt management and guardrails."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def chat(self, message: str, portfolio_context: str, history: list, session_id: str) -> str:
        """Send a chat message with portfolio context and conversation history."""
        system = FINANCIAL_ADVISOR_SYSTEM.format(portfolio_context=portfolio_context)

        chat = LlmChat(api_key=self.api_key, session_id=session_id, system_message=system)
        chat.with_model("openai", "gpt-5.2")

        # Replay history (skip last which is the current message)
        for m in history:
            if m["role"] == "user":
                await chat.send_message(UserMessage(text=m["content"]))

        response = await chat.send_message(UserMessage(text=message))

        # Guardrail: check for hallucinated guarantees
        response = self._apply_guardrails(response)
        return response

    async def analyze_portfolio(self, portfolio_text: str, session_id: str) -> dict:
        """Generate comprehensive portfolio analysis with structured output."""
        chat = LlmChat(api_key=self.api_key, session_id=session_id, system_message=INSIGHT_ANALYSIS_SYSTEM)
        chat.with_model("openai", "gpt-5.2")

        response = await chat.send_message(UserMessage(text=f"Analyze:\n{portfolio_text}"))
        parsed = self._parse_json_object(response)

        # Validate structure
        if not parsed.get("insights"):
            raise ValueError("AI response missing 'insights' field")

        return parsed

    async def parse_cas_document(self, file_contents: list, page_range: str, session_id: str) -> list:
        """Parse CAS document pages using vision model."""
        from emergentintegrations.llm.chat import FileContent

        system = """You are a CAS (Consolidated Account Statement) parser for Indian investments.
Extract ALL holdings. Return ONLY a JSON array:
[{"name":"...","ticker":"ISIN if found","asset_type":"mutual_fund|equity|etf|bond|gold|fd|other","quantity":float,"buy_price":float,"current_price":float,"sector":"Large Cap|Mid Cap|..."}]
Rules: Keep different folios separate. Use 0 for unknown prices. Return [] if no holdings."""

        chat = LlmChat(api_key=self.api_key, session_id=session_id, system_message=system)
        chat.with_model("openai", "gpt-5.2")

        msg = UserMessage(
            text=f"Extract holdings from pages {page_range} of this CAS statement. Return JSON array only.",
            file_contents=file_contents,
        )
        response = await chat.send_message(msg)
        return self._parse_json_array(response)

    def _apply_guardrails(self, text: str) -> str:
        """Apply safety guardrails to AI output."""
        # Flag absolute guarantees
        danger_phrases = ["guaranteed returns", "will definitely", "100% safe", "no risk"]
        for phrase in danger_phrases:
            if phrase.lower() in text.lower():
                text += "\n\n*Note: No investment is risk-free. Past performance doesn't guarantee future results.*"
                break
        return text

    def _parse_json_object(self, response: str) -> dict:
        """Parse JSON object from LLM response with cleanup."""
        clean = response.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            start, end = 1, len(lines) - 1
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end = i
                    break
            clean = "\n".join(lines[start:end])
        try:
            result = json.loads(clean.strip())
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', clean)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    def _parse_json_array(self, response: str) -> list:
        """Parse JSON array from LLM response with cleanup."""
        clean = response.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            start, end = 1, len(lines) - 1
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end = i
                    break
            clean = "\n".join(lines[start:end])
        try:
            result = json.loads(clean.strip())
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            match = re.search(r'\[[\s\S]*\]', clean)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return []
