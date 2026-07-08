"""Pure regex routing table for the copilot intent classifier.

Extracted from intent.py so the deterministic fast path (the ~90% of queries that
never hit the LLM) is importable and unit-testable WITHOUT pulling in
langchain/langgraph (which `intent.py` and `schemas.py` require). intent.py
consumes :func:`match_agent` and maps the returned agent key onto AgentName.

Agent keys are the string values of schemas.AgentName (kept in sync there) so the
two layers agree without this module importing the enum.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Agent keys — mirror schemas.AgentName values.
MARKET = "market_analyst"
STOCK = "stock_analyst"
MF = "mf_analyst"
PORTFOLIO = "portfolio_analyst"
RISK = "risk_analyst"
GOAL = "goal_planner"
RECOMMENDATION = "recommendation"
BACKTEST = "backtest_analyst"


# Historical "what-if" backtest — "if I'd invested ₹10L in X and Y 3 years ago,
# what's it worth today?". Must be checked FIRST: it shares vocabulary with
# PORTFOLIO ("invested", "returns") and the stock-lookup gate ("returns",
# "cagr", "performance"), all of which would otherwise grab these queries.
# Anchored on a counterfactual-investment cue + a past-horizon / value-today cue
# so plain "my portfolio returns" (no "X years ago" / "if I'd invested") still
# falls through to PORTFOLIO.
_P_BACKTEST = re.compile(
    r"\bback[\s-]?test\b|"
    r"\bif\s+i\s*(?:'d|\s+had|\s+have|\s+would\s+have)?\s+(?:invested|put|bought|started)\b|"
    r"\bwhat\s+if\s+i\s+(?:had\s+)?(?:invested|put|bought)\b|"
    r"\bhad\s+i\s+(?:invested|bought|put)\b|"
    r"\b(?:invest(?:ed|ing)?|put|bought)\b[^.?!]{0,60}\b\d+\s*(?:year|yr|y)s?\s+(?:ago|back|earlier)\b|"
    r"\b\d+\s*(?:year|yr|y)s?\s+(?:ago|back|earlier)\b[^.?!]{0,60}\b(?:invest|worth|return|grown)\b|"
    r"\bwould\s+(?:it|that|this|they|my\s+\w+)\s+(?:be\s+worth|have\s+(?:grown|given|returned|made))\b|"
    r"\bhow\s+much\s+would[^.?!]{0,40}(?:be\s+worth|have\s+(?:grown|returned|made))\b|"
    r"\bgrown\s+to\s+(?:today|now)\b",
    re.IGNORECASE,
)

_P_MARKET = re.compile(
    r"\b(market|nifty|sensex|nse|bse|fiis?|diis?|macro|rbi|inflation|gdp|"
    r"index|sectoral|sector\s+performance|breadth|advance.decline|vix|"
    r"flows?|fiis?.diis?|foreign\s+inflow|domestic\s+flow|today.s\s+market|"
    r"market\s+(?:outlook|update|summary|today|open|close|movement)|"
    # commodities / FX
    r"gold\s+(?:price|outlook)|silver\s+price|crude|brent|"
    r"dollar\s+index|\bdxy\b|usd[\s-]?inr|rupee|"
    # global markets
    r"us\s+markets?|global\s+(?:markets?|cues)|asian\s+markets?|european\s+markets?|"
    r"dow|nasdaq|s&p|gift\s+nifty|"
    # macro events / calendar / themes
    r"repo\s+rate|g[\s-]?sec|10[\s-]?year\s+yield|\bcpi\b|\biip\b|\bpmi\b|\bfed\b|budget\s+impact|"
    r"economic\s+(?:events|calendar)|what\s+should\s+i\s+watch|watch\s+tomorrow|"
    r"market\s+summary|hot\s+theme|greedy\s+or\s+fearful)\b",
    re.IGNORECASE,
)

_P_STOCK = re.compile(
    r"\b((?:what|how|analyse|analyze|tell me about|research|buy|sell|hold)\s+"
    r"(?:is\s+)?[A-Z]{2,10}\b|"
    r"technical\s+(?:analysis|view|setup|signal|chart|indicator)|"
    r"fundamentals?\s+(?:of|for)|"
    r"pe\s+ratio|pb\s+ratio|roe|eps|revenue|pat|ebitda|"
    r"rsi|macd|sma|ema|support|resistance|breakout|"
    r"[A-Z]{2,10}\s+(?:stock|share|equity|target|price))\b",
    re.IGNORECASE,
)

_P_MF = re.compile(
    r"\b(mutual\s+funds?|mf\b|scheme|nav|amc|fund\s+house|"
    r"sip|lump\s*sum|invest\s+in\s+(?:a\s+)?fund|"
    r"top\s+funds?|best\s+funds?|fund\s+comparison|compare\s+funds?|"
    r"overlap\s+(?:between|of|in)\s+(?:my\s+)?funds?|"
    r"(?:large|mid|small)\s*cap\s+(?:mutual\s+)?funds?|flexi\s*cap|"
    r"index\s+fund|elss|debt\s+fund|liquid\s+fund|"
    r"direct\s+plan|regular\s+plan|switch\s+to\s+direct|"
    r"expense\s+ratio|ter\b|fund\s+manager|"
    r"too\s+many\s+(?:mutual\s+)?funds?|sip\s+allocation|"
    # Single-fund card prompts (summary + overview/returns/holdings/peers tabs).
    r"(?:overview|returns?|holdings?|ratios?|peers?|full\s+analysis|allocation)\s+of\s+\w|"
    r"compare\s+.+\bwith\s+its\s+peers|\bwith\s+its\s+peers\b|"
    r"balanced\s+advantage|blue\s*chip|start\s+a?\s*sip\s+in)\b",
    re.IGNORECASE,
)

# Fund overlap / consolidation questions must reach mf_analyst (which renders
# the fund_consolidation / fund_overlap / overlap_severity widgets), NOT
# portfolio_analyst — _P_PORTFOLIO greedily matches "overlap". Checked FIRST.
_P_FUND_OVERLAP = re.compile(
    r"too many (?:mutual )?funds?|how many (?:mutual )?funds?|"
    r"(?:fix|reduce|cut|trim|too much|significant\w*)\s+(?:the\s+)?overlap|"
    r"overlap\w*\s+(?:in|between|of|among|significan)\s*(?:my\s+)?funds?|"
    r"(?:my |fund\s+)?funds?\s+overlap\w*|"
    r"(?:are|do)\s+my\s+funds?\s+overlap|"
    r"consolidat\w*\s+(?:my\s+)?(?:funds?|portfolio)",
    re.IGNORECASE,
)

# Cap-category education ("large-cap vs flexi-cap vs mid-cap", "which category").
# Must reach mf_analyst (renders the cap_education widget). Handles hyphenated
# forms that _P_MF's `\s*cap` patterns miss. Checked FIRST.
_P_CAP = re.compile(
    r"(?:large|mid|small|flexi|multi)[\s-]?cap.{0,40}\b(?:vs|versus|or)\b.{0,40}(?:large|mid|small|flexi|multi)[\s-]?cap|"
    r"which\s+(?:cap|category|type\s+of\s+fund)|"
    r"difference\s+between\s+(?:large|mid|small|flexi)[\s-]?cap",
    re.IGNORECASE,
)

# Per-stock OWNERSHIP / shareholding questions (FII/DII/promoter holding, pledge,
# shareholding pattern). Must beat _P_MARKET — which matches the bare tokens
# "fii"/"dii" and would otherwise route "FII/DII holding in <stock>" to the
# market analyst (market-wide flows only → no per-stock data → "couldn't
# retrieve"). Requires an ownership noun (holding/stake/ownership/shareholding/
# pledge) so genuine market-flow questions ("what did FII/DII do today?",
# "FII/DII flows") still fall through to _P_MARKET. Checked before _P_MARKET.
_P_STOCK_OWNERSHIP = re.compile(
    r"\b(?:fii|dii|promoter|institutional|foreign|public|domestic)\s+(?:holding|stake|ownership)|"
    r"\bshareholding(?:\s+pattern)?\b|"
    r"\bpromoter\s+pledg|\bpledged?\s+shares?",
    re.IGNORECASE,
)

_P_PORTFOLIO = re.compile(
    r"\b((?:my\s+)?portfolio|my\s+investments?|my\s+holdings?|"
    r"xirr|portfolio\s+(?:return|performance|summary|health|snapshot)|"
    r"rebalance|rebalancing|drift|concentration|overlap(?:ping)?|"
    r"which\s+(?:sectors?|funds?|stocks?|holdings?|positions?)\s+(?:should|to)\s+(?:i|we)\s+(?:trim|exit|sell|reduce|book|remove|cut|drop|hold|keep)|"
    r"(?:trim|exit|book\s+profit\s+(?:in|on)|cut|reduce|sell)\s+(?:my\s+)?(?:sectors?|funds?|stocks?|holdings?|positions?)|"
    r"tax(?:[\s-]+loss)?[\s-]+harvest(?:ing)?|harvest\s+loss|loss[\s-]+harvest(?:ing)?|"
    r"capital\s+gains?|ltcg|stcg|tax\s+liability|tax(?:.|-)?efficien|"
    r"idcw|growth\s+plan|growth\s+(?:vs|or)\s+idcw|"
    r"stress\s+test|portfolio\s+under\s+(?:crash|crisis)|"
    r"covid\s*crash|2008\s*crash|rate\s+shock|"
    r"fd\b|fixed\s+deposit|beat\s+fd|vs\s+fd|better\s+than\s+fd|"
    r"unrealized\s+(?:capital\s+)?gains?|unrealised\s+(?:capital\s+)?gains?|"
    r"realized\s+(?:vs|or)\s+unrealized|realised\s+(?:vs|or)\s+unrealised|"
    r"p\s*&\s*l|pnl|p_and_l|profit\s+and\s+loss|"
    r"earmark(?:ed)?|currency\s+exposure|india(?:.|-)?focus|"
    # AMC / sector / company / fund-wise allocation drill-down (the user's
    # portfolio, not live market sectors — anchored on allocation nouns so
    # "which sector is up today" still routes to market_analyst).
    r"(?:sector|amc|fund[\s-]?house|company|companies|fund[\s-]?wise)\s+(?:allocation|concentration|exposure|breakdown|distribution|weight|split|mix)|"
    r"(?:allocation|concentration|exposure|distribution)\s+(?:of|by|across|per|within)\s+(?:sector|amc|compan|fund)|"
    r"highest\s+(?:sector|amc|company|fund)?\s*(?:allocation|concentration|exposure)|"
    r"which\s+(?:sector|amc|fund\s*house)\s+(?:has|have|do\s+i|am\s+i|holds?|is\s+(?:my\s+)?(?:highest|biggest|largest))|"
    r"(?:how\s+much|what)\s+(?:would|will)\s+i\s+(?:lose|gain))\b",
    re.IGNORECASE,
)

_P_RISK = re.compile(
    r"\b(risk\s+(?:profile|suitability|capacity|tolerance|level|score|assessment|exposure|rating)|"
    r"portfolio\s+risk|my\s+risk|too\s+(?:much|aggressive|risky)|"
    r"how\s+risk(?:y)?|risk(?:y|ier)?\s+(?:is|am|right\s+now)|"
    r"is\s+my\s+portfolio\s+(?:too\s+)?risky|how\s+much\s+risk|"
    r"var\b|value\s+at\s+risk|volatility|drawdown|beta|"
    r"am\s+i\s+(?:over|under)(?:weight|invested|exposed)|"
    r"risk(?:y|ier)?\s+(?:stocks?|funds?|portfolio)|"
    r"safe(?:r|ty)?\s+(?:investment|option|fund|choice)|"
    r"manage\s+risk|risk\s+management|risk\s+reward|"
    r"market\s+(?:falls?|drops?|crash(?:es)?)\s*\d*\s*%?|"
    r"what\s+if\s+(?:markets?|nifty|sensex)\s+(?:falls?|drops?|crash(?:es)?)|"
    r"downside\s+(?:risk|protect|in)|max(?:imum)?\s+drawdown|"
    r"diversif(?:y|ied|ication))\b",
    re.IGNORECASE,
)

_P_GOAL = re.compile(
    r"\b(goal|goals|retirement|education(?:\s+(?:fund|corpus|cost|goal))?|corpus|target\s+amount|"
    r"on\s+track|sip\s+(?:gap|needed|required|adequacy)|sip\s+sufficient|"
    r"will\s+i\s+(?:reach|achieve|meet)|"
    r"shortfall|monthly\s+income|withdrawal\s+rate|safe\s+withdrawal|"
    r"annuit(?:y|ies)|preserve\s+capital|preserve\s+wealth|"
    r"inflation\s+protect|protect.+against\s+inflation|"
    r"child(?:ren)?\s+education|higher\s+education|"
    r"running\s+out\s+of\s+money|long(?:.|-)?term\s+wealth|"
    r"how\s+much\s+(?:should|do)\s+i\s+(?:invest|save|need))\b",
    re.IGNORECASE,
)

# Stock screener — the Query Builder / composer emit "Screen [bucket] stocks
# where …". Must win over _P_STOCK (which matches the keyword "roe"/"pe" and
# would mis-resolve "ROE" as a ticker) and over _P_CAP ("large cap"). Checked
# FIRST. "screen stocks?" alone (the old _P_RECOMMENDATION clause) missed
# "Screen large cap stocks" because of the words in between.
_P_SCREENER = re.compile(
    r"\bstock\s+screener\b|"
    r"\bscreener\b|"
    r"\bscreen(?:\s+\w+){0,4}\s+stocks?\b|"          # screen [≤4 words] stocks
    r"\bscreen\s+(?:large|mid|small|micro)[\s-]?cap\b",
    re.IGNORECASE,
)

_P_RECOMMENDATION = re.compile(
    r"\b(recommend|recommendation|suggest|what\s+(?:should|can)\s+i\s+(?:buy|invest)|"
    r"what\s+stocks?\s+should\s+(?:i|we)\s+(?:buy|invest)|"
    r"where\s+(?:should|can)\s+i\s+invest|screen\s+stocks?|screener|"
    r"top\s+stocks?|best\s+stocks?|fresh\s+investment|new\s+investment|"
    r"deploy\s+(?:money|capital|funds?)|invest\s+(?:fresh|new|\d)|"
    r"pms\b|aif\b|estate\s+planning|tax\s+treat(?:y|ies)|dtaa|"
    r"swing\s+trading|position\s+size|trading\s+discipline|"
    r"international\s+etfs?|us\s+etfs?|global\s+(?:fund|etf|allocation|diversif)|"
    r"undervalued\s+(?:stocks?|funds?)|valuation\s+metrics?|"
    r"safe\s+investment\s+option|annuity\s+(?:vs|or))\b",
    re.IGNORECASE,
)


# "Build me a portfolio" / "create my portfolio" → the in-chat builder wizard
# (routes to the recommendation node, which short-circuits to a portfolio_builder
# seed widget). Anchored on a build-verb + "portfolio"/"investing" so a plain
# "my portfolio" still routes to portfolio_analyst.
_P_BUILDER = re.compile(
    r"\b(?:build|create|design|set\s*up|make|start|begin)\s+(?:me\s+)?(?:a\s+|my\s+|my\s+first\s+|an?\s+)?"
    r"(?:portfolio|investment\s+plan|investing)\b"
    r"|\bportfolio\s+builder\b"
    r"|\bhelp\s+me\s+(?:build|create|start)\s+(?:a\s+)?(?:portfolio|investing|investment\s+plan)\b"
    r"|\binvest\s+from\s+scratch\b",
    re.IGNORECASE,
)


# "Build a (quality) strategy" / "strategy lab" → the in-chat Strategy Lab
# workbench (recommendation node short-circuits to a strategy_lab seed widget).
# Checked BEFORE _P_BUILDER/_P_SCREENER so "build a strategy" doesn't fall through.
_P_STRATEGY_LAB = re.compile(
    r"\b(?:build|create|design|make|start|open|launch)\s+(?:me\s+)?(?:a\s+|an?\s+|my\s+)?"
    r"(?:[a-z]+\s+){0,2}strateg(?:y|ies)\b"
    r"|\bstrateg(?:y|ies)\s+(?:lab|builder|workbench)\b"
    r"|\bstrategy\s+lab\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Entity-aware stock-lookup gate
# ---------------------------------------------------------------------------
# Routine single-stock lookups (price, P/E, ROE, RSI, dividend, returns, beta …)
# share metric words with the market/risk/MF nodes, so a flat keyword regex can't
# place them. This gate routes to the stock analyst when a stock metric/analysis
# cue is present AND the subject is a stock — excluding fund/portfolio phrasings
# and index subjects, so "{fund} returns", "my portfolio beta" and "Nifty
# support/resistance" are NOT captured. It runs after the high-priority specific
# patterns but before RISK/PORTFOLIO/MF/MARKET (whose shared words would
# otherwise mis-grab a stock query, e.g. "{stock} beta" → risk, "market cap" →
# market).

_FUND_HINT = re.compile(
    r"\b(mutual\s+funds?|funds?|scheme|\bnav\b|\bamc\b|elss|\betf\b|\bsip\b|"
    r"expense\s+ratio|\w+\s+cap\s+fund|index\s+fund|debt\s+fund|liquid\s+fund)\b",
    re.IGNORECASE,
)
_PORT_HINT = re.compile(r"\b(my|our)\b|portfolio|holdings", re.IGNORECASE)
_INDEX_SUBJECT = re.compile(
    r"\b(nifty|sensex|bank\s*nifty|india\s+vix|\bvix\b|midcap|smallcap|"
    r"sector(?:al)?\s+index)\b",
    re.IGNORECASE,
)

# Stock metric / analysis vocabulary (broad — only ever consulted inside the
# gate, so breadth is safe). Slash-tolerant so "P/E" matches a typed "pe".
_STOCK_CUE = re.compile(
    r"\bp\s*/?\s*e\b|\bp\s*/?\s*b\b|\bp\s*/?\s*s\b|\bpeg\b|ev\s*/?\s*ebitda|"
    r"enterprise\s+value|market\s+cap|price[\s-]*to[\s-]*(?:book|sales|earnings)|"
    r"intrinsic\s+value|fair\s+value|over\s*valued|under\s*valued|"
    r"\broe\b|\broce\b|\broic\b|return\s+on\s+(?:equity|capital)|"
    r"(?:operating|ebitda|net|gross|profit)\s+margins?|\bmargins?\b|asset\s+turnover|"
    r"revenue\s+growth|profit\s+growth|earnings\s+growth|\beps\b|"
    r"income\s+statement|balance\s+sheet|cash\s*flow|\bfcf\b|quarterly\s+results|"
    r"debt[\s-]*to[\s-]*equity|\bd\s*/?\s*e\b|net\s+debt|total\s+debt|debt[\s-]?free|"
    r"interest\s+coverage|current\s+ratio|quick\s+ratio|cash\s+reserves|"
    r"dividend|payout|buyback|ex[\s-]?date|"
    r"support|resistance|moving\s+average|\bdma\b|\brsi\b|\bmacd\b|bollinger|"
    r"pivot|chart\s+pattern|52[\s-]?week|all[\s-]?time\s+(?:high|low)|\bohlc\b|"
    r"circuit|face\s+value|lot\s+size|delivery\s*%|short\s+interest|"
    r"\bbeta\b|volatil|drawdown|\bcagr\b|\breturns?\b|performance|"
    r"\bvs\b|versus|compared\s+to|\btrend\b|bullish|bearish|"
    r"price\s+target|target\s+price|analyst|consensus|upgrade|downgrade|"
    r"business\s+model|competitors?|market\s+share|\bmoat\b|management|segments?|"
    r"\besg\b|governance|auditor|stock\s+split|bonus\s+issue|rights\s+issue|"
    r"demerger|spin[\s-]?off|promoter|\bprice\b|today.s\s+(?:open|high|low)|volume",
    re.IGNORECASE,
)

# The subset that is stock-ONLY (never applies to indices/portfolio), so it can
# fire even when no symbol resolves and there's no index subject — covers real
# tickers outside the curated resolver universe (e.g. "PERSISTENT P/E").
_STOCK_ONLY_CUE = re.compile(
    r"\bp\s*/?\s*e\b|\bp\s*/?\s*b\b|\bpeg\b|ev\s*/?\s*ebitda|enterprise\s+value|"
    r"market\s+cap|\broe\b|\broce\b|\beps\b|dividend\s+yield|payout\s+ratio|"
    r"interest\s+coverage|debt[\s-]*to[\s-]*equity|promoter|buyback|"
    r"income\s+statement|balance\s+sheet|\bfcf\b|free\s+cash\s+flow|"
    r"business\s+model|competitors?|\bmoat\b|stock\s+split|bonus\s+issue",
    re.IGNORECASE,
)


def _is_stock_lookup(text: str) -> bool:
    """True when the query is a single-stock metric/analysis lookup that should
    route to the stock analyst (see module note above)."""
    if _FUND_HINT.search(text) or _PORT_HINT.search(text):
        return False
    if not _STOCK_CUE.search(text):
        return False
    # Subject must be a stock, not an index — resolve the named entity.
    try:
        from services.copilot_tools.symbol_resolver import resolve_symbol
        resolved = bool(resolve_symbol(text).symbol)
    except Exception:  # noqa: BLE001 — never let resolution break routing
        resolved = False
    if resolved:
        return True
    # No resolvable stock: fire only for stock-ONLY vocab with no index subject.
    if _INDEX_SUBJECT.search(text):
        return False
    return bool(_STOCK_ONLY_CUE.search(text))


# Pattern → agent mapping (priority order — first match wins).
# BUILDER before PORTFOLIO so "build me a portfolio" → builder (not portfolio_analyst)
# STOCK_OWNERSHIP before MARKET so "FII/DII holding in <stock>" → stock_analyst
# RISK before PORTFOLIO so "portfolio risk" → risk_analyst
# MARKET before STOCK so "What is Nifty?" → market_analyst (not stock_analyst)
_PRE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (_P_BACKTEST,         BACKTEST),        # "if I'd invested … N years ago" → backtest (before PORTFOLIO/STOCK grab "invested"/"returns")
    (_P_STRATEGY_LAB,     RECOMMENDATION),  # "build a strategy" / "strategy lab" → Strategy Lab workbench (before BUILDER/SCREENER)
    (_P_BUILDER,          RECOMMENDATION),  # "build me a portfolio" → builder wizard (before PORTFOLIO grabs "portfolio")
    (_P_SCREENER,         RECOMMENDATION),  # "Screen [bucket] stocks where …" → screener (before STOCK grabs "roe")
    (_P_CAP,              MF),       # cap-category education → mf (cap_education widget) before others
    (_P_FUND_OVERLAP,     MF),       # fund overlap/consolidation → mf (widgets) before PORTFOLIO grabs "overlap"
    (_P_STOCK_OWNERSHIP,  STOCK),    # per-stock FII/DII/promoter holding → stock (before MARKET grabs "fii"/"dii")
]
# The entity-aware stock-lookup gate runs HERE — between _PRE and _POST.
_POST_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (_P_RISK,             RISK),
    (_P_GOAL,             GOAL),
    (_P_PORTFOLIO,        PORTFOLIO),
    (_P_RECOMMENDATION,   RECOMMENDATION),
    (_P_MF,               MF),
    (_P_MARKET,           MARKET),
    (_P_STOCK,            STOCK),
]
# Full table (PRE + POST) for reference/introspection.
PATTERNS: List[Tuple[re.Pattern, str]] = _PRE_PATTERNS + _POST_PATTERNS


def match_agent(text: str) -> Optional[str]:
    """Return the agent key for the first matching rule, or None if nothing
    matches (the caller then falls back to the LLM classifier)."""
    if not text:
        return None
    for pattern, agent in _PRE_PATTERNS:
        if pattern.search(text):
            return agent
    if _is_stock_lookup(text):
        return STOCK
    for pattern, agent in _POST_PATTERNS:
        if pattern.search(text):
            return agent
    return None
