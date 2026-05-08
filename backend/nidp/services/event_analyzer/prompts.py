"""System and user prompts for the corporate event AI analyzer."""

SYSTEM = """You are an expert Indian equity analyst with deep knowledge of NSE/BSE markets.
You analyse corporate events and their likely impact on stock prices using historical data,
sector context, and market patterns.

Your analysis must be:
- Grounded in the specific numbers provided (not generic)
- Comparative (vs previous quarters, vs estimates, vs peers)
- Actionable (clear signal with reasoning)
- Concise (traders need to act fast)

Return ONLY valid JSON — no markdown, no explanation outside the JSON."""

EARNINGS_PROMPT = """Analyse this quarterly earnings event for {symbol} ({company_name}).

== CURRENT QUARTER RESULTS ({period}) ==
{current_financials}

== PREVIOUS 4 QUARTERS (for comparison) ==
{historical_financials}

== RECENT ANNOUNCEMENTS (last 30 days) ==
{recent_announcements}

== PRICE CONTEXT ==
Current price: ₹{current_price}
52W High: ₹{high_52w} | 52W Low: ₹{low_52w}
Sector: {sector}

Analyse:
1. QoQ and YoY revenue/PAT/EPS growth — beat or miss?
2. Margin trends (EBITDA margin, PAT margin)
3. Key positives and negatives
4. Historical price reaction to similar results
5. Estimated price impact

Return JSON:
{{
  "sentiment": "strongly_bullish|bullish|neutral|bearish|strongly_bearish",
  "confidence": 0-100,
  "estimated_move_pct_low": number,
  "estimated_move_pct_high": number,
  "summary": "2-3 sentence summary for a trader",
  "key_factors": [
    {{"factor": "string", "impact": "positive|negative|neutral", "detail": "string"}}
  ],
  "risks": ["string"],
  "historical_comparison": {{
    "yoy_pat_growth_pct": number or null,
    "qoq_pat_growth_pct": number or null,
    "yoy_revenue_growth_pct": number or null,
    "margin_trend": "expanding|stable|contracting|unknown"
  }},
  "trading_note": "one sentence for swing/positional traders"
}}"""

ANNOUNCEMENT_PROMPT = """Analyse this corporate event for {symbol} ({company_name}).

== EVENT ==
Type: {event_type}
Date: {event_date}
Details: {announcement_text}

== RECENT FINANCIALS ==
{recent_financials}

== PRICE CONTEXT ==
Current price: ₹{current_price}
Sector: {sector}

Event type context:
{event_type_context}

Return JSON:
{{
  "sentiment": "strongly_bullish|bullish|neutral|bearish|strongly_bearish",
  "confidence": 0-100,
  "estimated_move_pct_low": number,
  "estimated_move_pct_high": number,
  "summary": "2-3 sentence summary for a trader",
  "key_factors": [
    {{"factor": "string", "impact": "positive|negative|neutral", "detail": "string"}}
  ],
  "risks": ["string"],
  "trading_note": "one sentence for swing/positional traders"
}}"""

# Context snippets for each of the 20 event types injected into the prompt
EVENT_TYPE_CONTEXT = {
    "quarterly_results": "Earnings beats drive 5-15% rallies in strong stocks. Misses cause 5-10% drops. Key metrics: PAT growth, revenue growth, margin expansion/contraction, EPS vs estimates.",
    "dividend":          "Dividend announcements are usually positive for stable companies. High yield attracts income investors. Stock adjusts down by ~dividend amount on ex-date.",
    "bonus":             "Bonus issues improve liquidity and retail participation. Psychologically positive. Price adjusts proportionally (1:1 bonus → price halves). Usually bullish sentiment.",
    "split":             "Stock splits improve affordability and liquidity. Often bullish in momentum stocks. Price adjusts mathematically.",
    "buyback":           "Buybacks reduce outstanding shares, improve EPS, signal management confidence. Particularly bullish when buyback price > market price.",
    "board_meeting":     "Board meeting outcomes vary. Key outcomes: dividend declaration, capex approval, merger/demerger. Analyse the specific resolution.",
    "order_win":         "Large order wins are critical for IT, defence, infra, railways, EPC. Improve revenue visibility and investor confidence. Often cause momentum rallies.",
    "merger_acquisition":"M&A impact depends on deal quality. Synergy benefits and market expansion are positive. Expensive acquisitions or high debt are negative. Check acquisition price vs book value.",
    "promoter_buying":   "Promoter buying is a strong bullish signal showing management confidence in the business.",
    "promoter_selling":  "Heavy promoter selling pressures stock. Can be neutral (personal liquidity) or negative (lack of confidence). Check quantum and pattern.",
    "shareholding":      "Rising FII/DII ownership is bullish. Falling promoter holding signals caution. Increased retail in falling stocks can be risky.",
    "rights_issue":      "Rights issues raise capital. Positive for growth/debt reduction. Negative signal if company is under financial stress.",
    "qip":               "QIP/preferential allotment signals strong investor interest. Positive for growth capital. Watch for dilution concerns.",
    "debt_reduction":    "Debt reduction is very bullish for leveraged companies — lowers interest burden, improves financial stability and valuation multiples.",
    "credit_rating":     "Rating upgrades lower borrowing costs and attract institutional buyers. Downgrades cause selling pressure.",
    "regulatory":        "Regulatory approvals can cause major rallies — especially USFDA approvals (pharma), RBI licenses (NBFC), government clearances (defence/telecom).",
    "management":        "CEO/management changes are critical. Strong appointments are positive. Sudden resignations raise governance concerns.",
    "litigation":        "Accounting fraud, SEBI investigations, tax raids destroy investor confidence quickly. Often causes sustained selling.",
    "delisting":         "Delisting announcements push price toward the offer price. Creates arbitrage opportunity if offer price > market price.",
    "index_change":      "Index inclusions trigger passive fund buying and increased liquidity (bullish). Exclusions cause forced selling (bearish short-term).",
    "pledge_change":     "Pledge increases signal promoter financial stress (negative). Pledge reductions signal improving health (positive). Critical for midcaps/smallcaps.",
    "insolvency":        "Bankruptcy/insolvency is severely negative. Massive price crash, delisting risk, equity dilution likely.",
    "other":             "Analyse the specific event details and their likely impact on business fundamentals and investor sentiment.",
}
