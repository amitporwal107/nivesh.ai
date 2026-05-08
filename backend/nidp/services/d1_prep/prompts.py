"""D-1 preparation prompts — generated the evening BEFORE results are due.

Unlike post-event analysis (which explains what happened), D-1 prep:
- Forecasts likely metric ranges based on historical trends
- Defines beat/miss/in-line thresholds
- Identifies the top 3-4 metrics that will drive the price reaction
- Sets price levels to watch (entry, SL, targets)
"""

D1_SYSTEM = """You are an expert Indian equity analyst preparing pre-earnings briefings.
You analyse historical quarterly trends to forecast tomorrow's results and define
actionable price scenarios for traders.

Your forecasts must be:
- Grounded in the specific numbers provided (extrapolate trends, not guesses)
- Sector-aware (banking NIM ≠ pharma EBITDA margin ≠ IT utilisation)
- Actionable (beat/miss thresholds, price levels, specific metrics to watch)

Return ONLY valid JSON — no markdown, no explanation outside the JSON."""


D1_EARNINGS_PROMPT = """Prepare a pre-earnings briefing for {symbol} ({company_name}).

Tomorrow ({event_date}), {symbol} reports {period} quarterly results.

== LAST 4 QUARTERS (most recent first) ==
{historical_financials}

== CURRENT PRICE CONTEXT ==
Current price: ₹{current_price}
52W High: ₹{high_52w} | 52W Low: ₹{low_52w}
Sector: {sector}

== RECENT ANNOUNCEMENTS (last 30 days) ==
{recent_announcements}

Based on historical trends, prepare a pre-event briefing.

Return JSON:
{{
  "sentiment": "strongly_bullish|bullish|neutral|bearish|strongly_bearish",
  "confidence": 0-100,
  "estimated_move_pct_low": number,
  "estimated_move_pct_high": number,
  "revenue_estimate_low": number or null,
  "revenue_estimate_high": number or null,
  "pat_estimate_low": number or null,
  "pat_estimate_high": number or null,
  "eps_estimate": number or null,
  "beat_scenario": "one sentence defining what constitutes a beat",
  "miss_scenario": "one sentence defining what constitutes a miss",
  "key_metrics_to_watch": ["list", "of", "3-5 metrics"],
  "expected_move_on_beat": number,
  "expected_move_on_miss": number,
  "support_levels": [list of 2 price levels],
  "resistance_levels": [list of 2 price levels],
  "summary": "2-3 sentences for a trader preparing for tomorrow",
  "key_factors": [
    {{"factor": "string", "impact": "positive|negative|neutral", "detail": "string"}}
  ],
  "risks": ["string"],
  "trading_note": "specific actionable trade setup for tomorrow"
}}"""


D1_BOARD_MEETING_PROMPT = """Prepare a pre-board-meeting briefing for {symbol} ({company_name}).

Tomorrow ({event_date}), {symbol} holds a board meeting. Expected agenda: {period}.

== RECENT FINANCIALS ==
{historical_financials}

== CURRENT PRICE CONTEXT ==
Current price: ₹{current_price}
52W High: ₹{high_52w} | 52W Low: ₹{low_52w}
Sector: {sector}

== RECENT ANNOUNCEMENTS ==
{recent_announcements}

Return JSON with the same structure as an earnings briefing but tailored to what the
board meeting might announce (dividend, buyback, capex, management change, etc.):
{{
  "sentiment": "strongly_bullish|bullish|neutral|bearish|strongly_bearish",
  "confidence": 0-100,
  "estimated_move_pct_low": number,
  "estimated_move_pct_high": number,
  "likely_agenda_items": ["string"],
  "beat_scenario": "what would be a positive surprise from this board meeting",
  "miss_scenario": "what would disappoint the market",
  "key_metrics_to_watch": ["list"],
  "summary": "2-3 sentences for a trader",
  "key_factors": [{{"factor": "string", "impact": "string", "detail": "string"}}],
  "risks": ["string"],
  "trading_note": "specific setup for tomorrow"
}}"""
