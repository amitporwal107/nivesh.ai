"""AI Engine — uses OpenAI SDK directly with cost-optimized model selection.
- gpt-4o: CAS PDF parsing (needs accuracy)
- gpt-4o-mini: Chat, Insights, Analysis (cheap, fast, good quality)
"""
import json
import logging
import re
import base64
from typing import Optional
from openai import AsyncOpenAI

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
Analyze the portfolio and return ONLY valid JSON. Be specific with actual fund names and numbers.

Return VALID JSON only, no markdown, no explanation. Schema:
{{
  "insights": [
    {{
      "title": "Gold Overexposure",
      "severity": "critical|important|optimization|positive",
      "category": "risk|allocation|cost|redundancy|opportunity",
      "summary": "27.3% gold vs recommended 12-15%",
      "why_it_matters": "Reduces long-term equity growth. Adds concentration risk.",
      "action": "Reduce gold by ~12%. Reallocate to equity/debt mix.",
      "expected_impact": "+1.5% CAGR improvement. Risk score: 72 → 48.",
      "rupee_impact": "~₹3.2L additional wealth over 10 years",
      "current_value": "27.3%",
      "target_value": "12-15%"
    }}
  ],
  "problem_distribution": [
    {{"name":"High Risk", "value": 35, "color":"#EF4444"}},
    {{"name":"Allocation Issues", "value": 25, "color":"#F59E0B"}},
    {{"name":"Cost Inefficiency", "value": 20, "color":"#3B82F6"}},
    {{"name":"Redundancy", "value": 20, "color":"#10B981"}}
  ],
  "before_after": {{
    "before": {{"return_pct": 6.5, "risk_label":"High", "risk_score": 75, "expense_ratio": 1.8, "annual_cost": 54000}},
    "after": {{"return_pct": 8.2, "risk_label":"Moderate", "risk_score": 45, "expense_ratio": 0.5, "annual_cost": 15000, "wealth_10y_gain": 1250000}}
  }},
  "action_funnel": [
    {{"step":1, "title":"Exit high-risk positions", "status":"critical", "detail":"Sell Vodafone Idea, penny stocks", "funds_involved": ["Vodafone Idea"], "rupee_impact": "Reduce risk by 15%"}}
  ],
  "do_nothing_scenario": {{
    "annual_cost_leak": 54000,
    "risk_remains": "High (72/100)",
    "ten_year_loss": "₹12.5L in potential returns missed",
    "headline": "If you take no action, you lose ₹54K/year in unnecessary costs alone"
  }},
  "overlap_pairs": [
    {{"fund_a":"...", "fund_b":"...", "overlap_pct": 80}}
  ],
  "cost_leakage": {{"annual_loss": 32000, "total_invested": 500000, "loss_pct": 1.2, "detail":"Regular plans vs Direct"}},
  "risk_gauge": {{"current": 75, "target": 45, "current_label":"High", "target_label":"Moderate"}}
}}

Rules:
- 6-8 insights, each MUST have: title, severity, summary, why_it_matters, action, expected_impact, rupee_impact
- severity: critical (red, immediate action), important (orange), optimization (blue), positive (green)
- problem_distribution: percentages sum to 100
- do_nothing_scenario: realistic cost of inaction
- before_after: include annual_cost in ₹ and wealth_10y_gain
- action_funnel: 3-5 steps with funds_involved and rupee_impact
- Use ACTUAL fund names and numbers from the portfolio"""


CAS_PARSER_SYSTEM = """You are a CAS (Consolidated Account Statement) parser for Indian investments from NSDL/CDSL.
Extract ALL holdings visible. Return ONLY a JSON array. No explanation.

Output format per holding:
[{"name":"Full company/fund name","ticker":"ISIN (INE.../INF...)","asset_type":"equity|mutual_fund|etf|gold|bond|fd|other","quantity":float,"buy_price":float,"current_price":float,"sector":"Large Cap|Mid Cap|Small Cap|Flexi Cap|ELSS|Debt|Hybrid|Gold|Banking|IT|Pharma|Other"}]

CRITICAL RULES:
1. Extract EVERY holding — equities, mutual funds, ETFs, SGBs, gold bonds. Do NOT skip any.
2. For ISIN: use the INE/INF code exactly as shown
3. For asset_type: stocks/shares = "equity", scheme/fund/SIP = "mutual_fund", ETF = "etf", SGB/Gold = "gold"
4. For buy_price: use "Avg Cost Per Unit" or "Cost Value / Units" if shown. If only current NAV/price shown, use that as buy_price too. NEVER use 0.
5. For current_price: use "Market Price" or "NAV" or "Value / Units"
6. For quantity: use "No. of Shares" or "No. of Units" or "Balance Units"
7. Keep different folios as SEPARATE entries (same fund, different folio = separate holdings)
8. If a page has no holdings (just transactions/notes), return []
9. Do NOT include transaction history, only current holdings/balances"""


# Model choices — cost optimized
MODEL_EXPENSIVE = "gpt-4o"       # For CAS parsing (needs accuracy) ~$2.50/1M input
MODEL_CHEAP = "gpt-4o-mini"      # For chat & insights ~$0.15/1M input


class AIEngine:
    """Centralized AI layer using OpenAI SDK directly."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat(self, message: str, portfolio_context: str, history: list, session_id: str) -> str:
        """Send a chat message with portfolio context. Uses gpt-4o-mini (cheap)."""
        system = FINANCIAL_ADVISOR_SYSTEM.format(portfolio_context=portfolio_context)

        messages = [{"role": "system", "content": system}]

        # Add conversation history
        for m in history:
            messages.append({"role": m["role"], "content": m["content"][:1000]})

        # Add current message
        messages.append({"role": "user", "content": message})

        try:
            response = await self.client.chat.completions.create(
                model=MODEL_CHEAP,
                messages=messages,
                max_tokens=1500,
                temperature=0.7,
            )
            text = response.choices[0].message.content
            return self._apply_guardrails(text)
        except Exception as e:
            logger.error(f"OpenAI chat failed: {e}")
            raise

    async def analyze_portfolio(self, portfolio_text: str, session_id: str) -> dict:
        """Generate comprehensive portfolio analysis. Uses gpt-4o-mini (cheap)."""
        try:
            response = await self.client.chat.completions.create(
                model=MODEL_CHEAP,
                messages=[
                    {"role": "system", "content": INSIGHT_ANALYSIS_SYSTEM},
                    {"role": "user", "content": f"Analyze:\n{portfolio_text}"},
                ],
                max_tokens=3000,
                temperature=0.3,
            )
            text = response.choices[0].message.content
            parsed = self._parse_json_object(text)

            if not parsed.get("insights"):
                raise ValueError("AI response missing 'insights' field")
            return parsed
        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}")
            raise

    async def parse_cas_text(self, text: str, session_id: str) -> list:
        """Parse CAS text content using gpt-4o (accurate)."""
        try:
            response = await self.client.chat.completions.create(
                model=MODEL_EXPENSIVE,
                messages=[
                    {"role": "system", "content": CAS_PARSER_SYSTEM},
                    {"role": "user", "content": f"Extract all holdings from this CAS statement. Return JSON array only.\n\n{text[:15000]}"},
                ],
                max_tokens=4000,
                temperature=0.1,
            )
            result = response.choices[0].message.content
            return self._parse_json_array(result)
        except Exception as e:
            logger.error(f"OpenAI CAS text parse failed: {e}")
            raise

    async def parse_cas_images(self, image_data_list: list, page_range: str, session_id: str) -> list:
        """Parse CAS images using gpt-4o vision (accurate)."""
        content = [{"type": "text", "text": f"Extract holdings from pages {page_range} of this CAS statement. Return JSON array only."}]

        for img_data in image_data_list:
            if isinstance(img_data, bytes):
                b64 = base64.b64encode(img_data).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
                })
            elif isinstance(img_data, str) and img_data.startswith("http"):
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img_data, "detail": "high"},
                })

        try:
            response = await self.client.chat.completions.create(
                model=MODEL_EXPENSIVE,
                messages=[
                    {"role": "system", "content": CAS_PARSER_SYSTEM},
                    {"role": "user", "content": content},
                ],
                max_tokens=4000,
                temperature=0.1,
            )
            result = response.choices[0].message.content
            return self._parse_json_array(result)
        except Exception as e:
            logger.error(f"OpenAI CAS image parse failed: {e}")
            raise

    async def parse_cas_document(self, file_contents: list, page_range: str, session_id: str) -> list:
        """Legacy compatibility — routes to parse_cas_images."""
        # Convert emergentintegrations FileContent to image data
        image_data = []
        for fc in file_contents:
            if hasattr(fc, 'url'):
                image_data.append(fc.url)
            elif hasattr(fc, 'data'):
                image_data.append(fc.data)
        return await self.parse_cas_images(image_data, page_range, session_id)

    def _apply_guardrails(self, text: str) -> str:
        danger_phrases = ["guaranteed returns", "will definitely", "100% safe", "no risk"]
        for phrase in danger_phrases:
            if phrase.lower() in text.lower():
                text += "\n\n*Note: No investment is risk-free. Past performance doesn't guarantee future results.*"
                break
        return text

    def _parse_json_object(self, response: str) -> dict:
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
