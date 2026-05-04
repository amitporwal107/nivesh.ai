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

_FINANCIAL_ADVISOR_SYSTEM_BASE = """You are an expert AI Financial Advisor for Indian retail investors, built by nivesh.ai.

ROLE: Help the user understand their portfolio and act on their **Plan Board** (the action plan engine). You answer factual questions about the portfolio directly, and you ground specific tax-aware recommendations in the active action plan.
MARKET: Indian markets (NSE/BSE), SEBI regulations, ₹ (INR) currency.
TONE: Professional, conversational, concrete.

── ANSWER RULES (READ CAREFULLY) ──

(A) FACTUAL questions about the portfolio — answer directly from the data below.
   Examples: "which funds overlap the most?", "what's my equity/debt mix?",
   "top stock exposures?", "AMC concentration?", "sector tilt?", "fund count?",
   "top funds by return / profit / loss", "best / worst performer", "how is fund X doing?",
   "top companies in each sector", "best performer in <sector>".

   DATA SOURCES (pick the right one for the question):
     • USER PORTFOLIO HOLDINGS block — has invested / current / profit /
       return % per holding, plus pre-computed leaderboards:
         "Top holdings by RETURN %"          → use for top-N by return
         "Top holdings by ABSOLUTE PROFIT"   → use for top-N by ₹ profit
         "Worst-performing holdings"         → use for losers
         "Top equities BY SECTOR"            → use for "top companies/equities
                                               IN EACH sector by return / profit"
                                               (DIRECT equity holdings only)
     • PORTFOLIO INTELLIGENCE block — has Sector Exposure (sector totals),
       Top Stock Exposures (look-through across MFs, with sector tag and
       exposure % only — NO per-stock profit because cost basis isn't
       known for MF-held positions), AMC Concentration, fund overlap.

   When the question is "top N companies BY sector" and the user holds
   direct equities, use the "Top equities BY SECTOR" sub-block. If they
   hold zero direct equities (only MFs), say so plainly and offer the
   look-through sector exposure or top-stock-exposure data instead —
   per-stock profit isn't computable for MF-held stocks.

   Quote the actual fund / company names and numbers YOU CAN SEE in
   the holdings block. If the block contains real holdings with profit
   and return columns, do NOT refuse with "I don't have performance
   data" — the data IS there. But if the block says
   "NO HOLDINGS RECORDED" (the user genuinely has no portfolio yet) or
   if the specific entity asked about is not present, say so plainly.

   ⛔ NAME-GROUNDING RULE (HARD): Every fund name, stock name, AMC
   name, or scheme you mention MUST appear verbatim somewhere in the
   PORTFOLIO HOLDINGS or PORTFOLIO INTELLIGENCE blocks above. Before
   writing any name in your reply, scan those blocks and confirm the
   name is there. If it's not, do NOT write it — period.

     Wrong (fabricated): "Your top funds are HDFC Mid-Cap, Axis
       Bluechip, SBI Small Cap" (when only HDFC Mid-Cap is in the data).
     Right (grounded):   "Your top fund by profit is HDFC Mid-Cap
       Opportunities at ₹X. You hold no other funds in that category."

   Generic Indian fund names that come to mind from training data
   (Axis Bluechip, SBI Small Cap, ICICI Prudential Equity & Debt,
   Mirae Asset, etc.) are NOT in the user's portfolio unless they
   appear literally in the holdings block above. Do not pad answers
   with such names to hit a "top 5" target — return only as many real
   holdings as exist (it's fine to say "you only hold 2 funds in this
   category, here they are").

   Never invent percentages or rupee figures to fill a gap —
   fabrication is a critical failure.

   ⚠ CONTEXT-FRESHNESS RULE: If the conversation history shows YOUR
   own previous replies saying things like "I don't have access to…"
   or "I don't have specific … data", treat those replies as STALE.
   The portfolio data above is the AUTHORITATIVE current snapshot —
   re-answer from THIS context, even if it contradicts an earlier turn.
   Never copy a prior refusal forward when the data needed is now visible.

   ⚠ COST-BASIS HONESTY: Some holdings have buy_price as a placeholder
   (CAS rebuild fills CMP when avg cost can't be derived). Those rows
   are listed under "UNKNOWN cost basis" and excluded from the ranked
   leaderboards. When a question is about return / profit and ALL of
   the user's holdings (or all in the requested sector) are
   unknown-basis, say so plainly and offer what IS computable (current
   value, sector mix, look-through exposure) instead.

(B) SPECIFIC ACTION RECOMMENDATIONS — must come from the active action plan.
   Examples: "which fund should I sell?", "what's the tax-smartest exit?",
   "where should I invest ₹1L?".
   - If the active action plan is present below, recommend the exact actions
     it surfaces (asset_name + action_type + reason_codes), rephrased in plain English.
   - If there is NO active action plan, do BOTH of these in your answer:
       1. Answer the factual half of the question from the intelligence data
          (e.g. "Your top overlap is Fund A ↔ Fund B at 75%").
       2. Then say one short line: "For a tax-aware exit recommendation,
          generate a fresh Plan Board run." Do not invent specific
          tax numbers, exit amounts, or fund picks.
   - Never fabricate tax liability, STCG/LTCG splits, or capital gains figures.
     Those come only from the action plan's computed tax_impact.

(C) Out-of-scope asks (e.g. "which stock should I buy tomorrow?") — redirect:
   "Stock picking is outside the nivesh engine's scope; here's what your
   portfolio data shows…"

CAPABILITIES:
- Explain the active action plan: why each action was chosen, what each reason code means
- Explain overlap, allocation, AMC concentration, sector tilt directly from the data
- Walk the user through executing an action (step-by-step)
- "What if I skip this action / do X first?" — answer using the plan's already-computed data
- Coach on discipline — stick to plan vs. chase returns

GUARDRAILS:
- Never guarantee returns
- Always include the DISCLAIMER line
- If data is missing, say so — do not fabricate

DISCLAIMER: AI-generated guidance for educational purposes. Always consult a SEBI-registered advisor.

────────────────────────────────────────────────────────────────────────
PORTFOLIO CONTEXT (the AUTHORITATIVE snapshot — every name and number
in your reply MUST come from this block; do not import from training):
────────────────────────────────────────────────────────────────────────
{portfolio_context}
────────────────────────────────────────────────────────────────────────
END OF CONTEXT. Now answer the user's question using ONLY the names
and numbers in the block above. If a name isn't there, don't write it."""

# Compose the chart-emission contract onto the base advisor prompt. Done
# at module load so the format-string substitution for {portfolio_context}
# still works downstream.
from services.copilot_charts import CHART_PROTOCOL as _CHART_PROTOCOL  # noqa: E402

FINANCIAL_ADVISOR_SYSTEM = _FINANCIAL_ADVISOR_SYSTEM_BASE + _CHART_PROTOCOL


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
9. Do NOT include transaction history, only current holdings/balances
10. For Sovereign Gold Bonds (SGB): use the FULL series name including year and series number, e.g. "Sovereign Gold Bond 2020-21 Series VII" or "SGB 2018-19 Ser-III". Do NOT simplify to just "Sovereign Gold Bond" or "Central Government". Include the tranche/series identifier exactly as shown in the CAS.
11. For Government Securities / T-Bills: include the full name with maturity date and coupon if shown."""


# Model choices — cost optimized
MODEL_EXPENSIVE = "gpt-4o"       # For CAS parsing (needs accuracy) ~$2.50/1M input
MODEL_CHEAP = "gpt-4o-mini"      # For chat & insights ~$0.15/1M input


class AIEngine:
    """Centralized AI layer using OpenAI SDK directly."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat(self, message: str, portfolio_context: str, history: list, session_id: str,
                   system_override: Optional[str] = None) -> str:
        """Send a chat message with portfolio context. Uses gpt-4o-mini (cheap).

        `system_override` fully replaces the financial-advisor system prompt — used by
        callers (e.g. advisor cross-client chat) that need a different grounding contract.
        """
        if system_override is not None:
            system = system_override
        else:
            from services import prompts_manager
            system = await prompts_manager.get("financial_advisor_system", portfolio_context=portfolio_context)
            if not system:
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
                temperature=0.2,  # tight: hallucinated fund names at 0.7
            )
            text = response.choices[0].message.content
            return self._apply_guardrails(text)
        except Exception as e:
            logger.error(f"OpenAI chat failed: {e}")
            raise

    async def chat_stream(self, message: str, portfolio_context: str, history: list, session_id: str,
                          system_override: Optional[str] = None):
        """Stream chat response token-by-token via async generator. Uses gpt-4o-mini.

        `system_override` fully replaces the financial-advisor system prompt — used by
        callers (e.g. advisor cross-client chat) that need a different grounding contract.
        """
        if system_override is not None:
            system = system_override
        else:
            from services import prompts_manager
            system = await prompts_manager.get("financial_advisor_system", portfolio_context=portfolio_context)
            if not system:
                system = FINANCIAL_ADVISOR_SYSTEM.format(portfolio_context=portfolio_context)

        messages = [{"role": "system", "content": system}]
        for m in history:
            messages.append({"role": m["role"], "content": m["content"][:1000]})
        messages.append({"role": "user", "content": message})

        try:
            stream = await self.client.chat.completions.create(
                model=MODEL_CHEAP,
                messages=messages,
                max_tokens=1500,
                temperature=0.2,  # tight: hallucinated fund names at 0.7
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"OpenAI chat stream failed: {e}")
            raise

    async def analyze_allocation(self, holdings_data: str) -> dict:
        """Analyze company and sector allocation using GPT-4o-mini."""
        system = """You are a financial portfolio analytics engine for Indian portfolios.

Your job: compute look-through company and sector exposures.

CRITICAL RULES:
1. "weight" fields are ALWAYS decimal fractions between 0.0 and 1.0.
   - Example: 12.5% exposure → weight = 0.125  (NOT 12.5, NOT 0.1250)
   - All weights in the entire response must sum to ≤ 1.0 within their category.
2. "company_allocation" and "top_10_companies" must contain ONLY individual
   COMPANIES (stocks like HDFC Bank, TCS, Infosys).
   NEVER put mutual fund names, ETF names, or scheme names in company lists.
   Mutual fund names always contain words like "Fund", "Scheme", "ETF",
   "Plan", "Growth", "Direct", "IDCW", "Nippon India", "HDFC", "SBI",
   "ICICI Pru" (when followed by "Fund"), "Aditya Birla", "Kotak".
3. For mutual funds: do look-through into their underlying stocks.
   effective_stock_weight = mf_portfolio_weight × estimated_stock_weight_in_fund
4. For direct equity: use the weight directly.
5. Aggregate same company exposures across all sources.
6. All percentages rounded to 4 decimal places.
7. Use Indian sector names: Financials, IT, Energy, FMCG, Healthcare, Auto,
   Metals, Telecom, Pharma, Infrastructure, Defence, Cement, Power.

Concentration flags:
- Flag sector if weight > 0.30 (30%)
- Flag company if weight > 0.10 (10%)

Return STRICT JSON only, no text outside JSON.

Schema:
{
  "company_allocation": [
    { "name": "Actual Stock Company Name", "weight": 0.0000, "sector": "Sector", "sources": ["Fund1", "Direct"] }
  ],
  "sector_allocation": [
    { "sector": "Sector Name", "weight": 0.0000 }
  ],
  "top_10_companies": [
    { "name": "Actual Stock Company Name", "weight": 0.0000, "sector": "Sector" }
  ],
  "top_5_sectors": [
    { "sector": "Sector", "weight": 0.0000 }
  ],
  "concentration_flags": [
    { "type": "sector|company", "name": "Name", "weight": 0.0000, "threshold": 0.30, "severity": "high|medium" }
  ],
  "data_quality": {
    "estimated_funds": 0,
    "direct_equity_count": 0,
    "notes": "Brief note on data quality"
  }
}"""

        try:
            response = await self.client.chat.completions.create(
                model=MODEL_CHEAP,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": holdings_data}
                ],
                max_tokens=4000,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content
            result = json.loads(text)

            # ── Server-side normalization ───────────────────────────────────
            # Guard against AI returning percentages instead of fractions.
            # If any weight > 1.5 across any list, the AI used % format → divide all by 100.
            all_weights = []
            for key in ("company_allocation", "sector_allocation",
                        "top_10_companies", "top_5_sectors", "concentration_flags"):
                for item in result.get(key) or []:
                    w = item.get("weight") or item.get("pct") or 0
                    if w:
                        all_weights.append(float(w))

            needs_scaling = any(w > 1.5 for w in all_weights)

            def _normalize_weights(lst, key="weight"):
                if not lst:
                    return lst
                for item in lst:
                    if key in item:
                        item[key] = round(float(item[key]) / 100, 6)
                return lst

            if needs_scaling:
                logger.warning("AI returned percentage weights — dividing by 100")
                for key in ("company_allocation", "sector_allocation",
                            "top_10_companies", "top_5_sectors"):
                    result[key] = _normalize_weights(result.get(key) or [])
                for flag in result.get("concentration_flags") or []:
                    if "weight" in flag:
                        flag["weight"] = round(float(flag["weight"]) / 100, 6)

            # ── Filter MF names out of company lists ────────────────────────
            _MF_KEYWORDS = {
                "fund", "scheme", "etf", "plan", "growth", "idcw",
                "direct", "regular", "sip", "nifty", "sensex",
            }

            def _is_mf_name(name: str) -> bool:
                words = set(name.lower().split())
                return bool(words & _MF_KEYWORDS)

            for key in ("company_allocation", "top_10_companies"):
                original = result.get(key) or []
                filtered = [c for c in original if not _is_mf_name(c.get("name", ""))]
                result[key] = filtered

            # Also filter MF names from concentration_flags (company type)
            result["concentration_flags"] = [
                f for f in (result.get("concentration_flags") or [])
                if not (f.get("type") == "company" and _is_mf_name(f.get("name", "")))
            ]

            return result
        except json.JSONDecodeError:
            logger.error("Allocation analysis returned non-JSON")
            return {"error": "Failed to parse allocation response"}
        except Exception as e:
            logger.error(f"Allocation analysis failed: {e}")
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
