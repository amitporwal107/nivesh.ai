"""Keyword-based intent classifier for the Copilot.

Fast (<1ms), deterministic, no LLM call. Covers the 90% of queries the
chat sees in practice; falls through to `generic` for anything else
(which still goes to the LLM with a small portfolio summary).

We deliberately avoid an LLM-based classifier here because:
  • Latency budget on chat is already tight.
  • Intent classification on short user messages is a textbook keyword job.
  • A miss just degrades to `generic` — which still answers; it doesn't fail.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Intent:
    name: str
    # Slot fillers extracted from the message.
    metric: Optional[str] = None       # "return" | "profit" | "loss" | "value"
    n: int = 5                         # how many results requested
    grouping: Optional[str] = None     # "sector" | "amc" | "category"
    chart_requested: bool = False
    raw: str = ""                      # original message
    extras: Dict[str, Any] = field(default_factory=dict)


# Keyword tables — order matters: more specific first.
_RANK_TRIGGERS = re.compile(
    r"\b(top|best|worst|highest|lowest|biggest|largest|smallest|"
    r"underperform\w*|losers?|winners?|leaders?|laggards?)\b",
    re.IGNORECASE,
)
_METRIC_RETURN = re.compile(r"\b(return|returns|cagr|xirr|performance|growth)\b", re.IGNORECASE)
_METRIC_PROFIT = re.compile(r"\b(profit|profits|gain|gains|p&?l|pnl|absolute)\b", re.IGNORECASE)
_METRIC_LOSS = re.compile(r"\b(loss|losses|losing|down|red|underperform\w*)\b", re.IGNORECASE)
_METRIC_VALUE = re.compile(r"\b(value|aum|holding[s]? size|exposure|allocation)\b", re.IGNORECASE)

_GROUPING_SECTOR = re.compile(
    r"\b(sector|sectors|industr\w+|"
    r"\bIT\b|pharma|banking|finance|fmcg|energy|infra|auto|metal|cement|"
    r"telecom|media)\b",
    re.IGNORECASE,
)
_GROUPING_AMC = re.compile(r"\b(amc|fund\s*house|amcs|fund-?house)\b", re.IGNORECASE)
_GROUPING_CATEGORY = re.compile(
    r"\b(categor(?:y|ies)|large\s*cap|mid\s*cap|small\s*cap|flexi\s*cap|"
    r"value\s*fund|balanced\s*fund|index\s*fund)\b",
    re.IGNORECASE,
)
_GROUPING_ASSET_CLASS = re.compile(
    r"\b(asset\s*class(?:es)?|equity\s+vs|debt\s+vs|gold\s+vs|"
    r"asset\s*allocation|asset\s*mix|class\s+breakdown)\b",
    re.IGNORECASE,
)
# Match "company-wise breakdown", "top companies by exposure", "company
# concentration" — but deliberately NOT bare "stocks" (that goes to
# ranking via _RANK_TRIGGERS, e.g. "top 5 stocks by return"). When users
# say "company" they almost always mean look-through across MFs.
_GROUPING_COMPANY = re.compile(
    r"\b(compan(?:y|ies)|securit(?:y|ies)|"
    r"stock\s+(?:concentration|exposure|breakdown|wise|mix)|"
    r"holdings?\s+by\s+(?:name|stock|company))\b",
    re.IGNORECASE,
)

_CONCENTRATION = re.compile(r"\b(concentration|concentrated|exposure|distribut\w+|breakdown|split|mix)\b", re.IGNORECASE)
_OVERLAP = re.compile(r"\b(overlap|overlapping|duplicate|redundan\w+|similar funds?)\b", re.IGNORECASE)
_TAX = re.compile(r"\b(tax|ltcg|stcg|harvest\w+|capital gains?|82e|80c)\b", re.IGNORECASE)
_GOALS = re.compile(
    r"\b(goal|goals|on\s+track|retirement|education\s+fund|"
    r"goal\s+progress|sip\s+(?:gap|status|adequacy)|"
    r"target\s+(?:amount|corpus|date)|"
    r"will\s+i\s+(?:reach|achieve|meet))\b",
    re.IGNORECASE,
)
_HEALTH = re.compile(r"\b(health\s*score|grade|risk drivers?|portfolio score)\b", re.IGNORECASE)
# "Where should I invest ₹X" / "deploy fresh money" / "improve
# diversification" — distinct from `_PLAN`. The user is NOT asking for
# a full rebalance; they're asking which underweight bucket should
# receive new capital. Routing this to `_PLAN` returns the entire
# saved plan (incl. EXITs), which buries the actual answer; routing
# to `generic` makes the LLM count holdings (the bug we just hit:
# "you have only 5 gold holdings, add gold" — when gold is +17pp
# overweight). Dedicated intent + retriever fixes both failures.
_INVEST_FRESH = re.compile(
    r"\b("
    # "where should I invest / put / deploy / allocate / add / park"
    r"where\s+(?:should|can|do|to|might)\s+i?\s*"
    r"(?:invest|put|deploy|allocate|add|park|place)|"
    # "where should it / this / that go"
    r"where\s+(?:should|do)\s+(?:it|this|that|the\s+money)\s+go|"
    # "have ₹X to invest" / "₹X to deploy"
    r"(?:to\s+invest|to\s+deploy|to\s+allocate|to\s+park)|"
    # "(invest|deploy|allocate|park) fresh/new/extra money"
    r"(?:invest|deploy|allocate|park)\s+(?:fresh|new|extra|surplus|additional|more)\s+(?:money|cash|capital|funds?|amount)|"
    # "add fresh/new money"
    r"add\s+(?:fresh|new|more|extra)\s+(?:money|cash|funds?)|"
    # "improve (my) diversification / allocation / balance"
    r"improve\s+(?:my\s+)?(?:diversification|allocation|balance|spread)|"
    # "top up my portfolio" / "diversify my portfolio"
    r"top\s*[-\s]*up\s+(?:my\s+)?portfolio|"
    r"diversify\s+(?:my\s+)?portfolio|"
    # "(₹X|amount) to invest / deploy"
    r"\d+\s*(?:lakh|l|cr|crore|k|thousand)?\s+to\s+(?:invest|deploy|put|allocate)"
    r")\b",
    re.IGNORECASE,
)

# Allocation drift / target-vs-current questions. Stays distinct from
# `_PLAN` (which means "give me actions") and `_CONCENTRATION` (which
# means "show me the breakdown") — drift is specifically about the
# gap between where you ARE and where you SHOULD BE.
_DRIFT = re.compile(
    r"\b("
    r"on\s+target|target\s+allocation|target\s+vs\s+current|"
    r"allocation\s+(?:drift|deviation|gap|mismatch)|"
    r"am\s+i\s+(?:on\s+target|aligned|over\s+exposed|over[\s-]?weight|under[\s-]?weight)|"
    r"how\s+far\s+(?:am\s+i\s+)?(?:off|from)\s+target|"
    r"(?:over|under)\s*(?:weight|exposed|allocated)"
    r")\b",
    re.IGNORECASE,
)
_PLAN = re.compile(
    r"\b("
    r"action\s*plan|plan\s*board|recommend\w*|next\s+steps?|"
    r"what\s+should\s+i\s+do|"
    r"actions?\s+(?:to\s+take|i\s+should\s+take|to\s+do|recommended|needed|required)|"
    r"top\s+\d*\s*actions?|"  # "top 3 actions" goes to plan, not ranking
    r"fix\s+(?:my|the|this)\s+portfolio|"
    r"how\s+(?:can|do|should)\s+i\s+(?:fix|improve|rebalance|optimi[sz]e)|"
    r"rebalance(?:\s+my\s+portfolio)?|"
    r"optimi[sz]e\s+my\s+portfolio|"
    r"clean\s*up\s+my\s+portfolio"
    r")\b",
    re.IGNORECASE,
)

_MF = re.compile(
    r"\b("
    # Explicit MF terms
    r"mutual\s+fund|mutual\s+funds|mf\b|sip\b|nav\b|"
    r"scheme\b|amfi|amc\b|"
    # Product types
    r"index\s+fund|etf\b|elss|nfo\b|"
    r"flexi\s*cap|multi\s*cap|"
    r"direct\s+plan|regular\s+plan|growth\s+option|idcw|dividend\s+option|"
    # Risk metrics in fund context (Sharpe alone also triggers)
    r"sharpe\s+ratio|sortino|max\s+draw|"
    # Fund-specific actions
    r"fund\s+(?:performance|return|compare|overlap|recommendation|house|manager)|"
    r"top\s+(?:fund|scheme|sip|mf)|best\s+(?:fund|scheme|sip)|"
    r"compare\s+(?:fund|scheme|mf|sip)|overlap\b|"
    # Common fund name fragments that users type
    r"bluechip|blue\s*chip|flexi\s*cap|"
    r"mirae|quant\s+(?:fund|small|flex)|parag\s+parikh|"
    r"axis\s+(?:blue|long|small|mid|flex)|hdfc\s+(?:top|mid|small|flex)|"
    r"sbi\s+(?:blue|contra|small|flex|magnum)|icici\s+pru|nippon|kotak\s+(?:flex|small)"
    r")\b",
    re.IGNORECASE,
)

# Second-pass check for "large/mid/small cap funds" (not bare stocks) context
_MF_CATEGORY = re.compile(
    r"\b(large|mid|small|multi|flexi)\s*[\-\s]?cap\s+(?:fund|scheme|mf|sip|mutual|invest)",
    re.IGNORECASE,
)

_FUNDAMENTAL = re.compile(
    r"\b("
    r"fundamental(?:s|ly|al\s+analysis|s?\s+strong|s?\s+weak)?|"
    r"pe\s*ratio|pe\b|p/e|price[\s-]to[\s-]earnings?|"
    r"pb\b|p/b|price[\s-]to[\s-]book|"
    r"roe\b|return\s+on\s+equity|"
    r"debt[\s-]to[\s-]equity|d/e\s*ratio|leverage|"
    r"piotroski|altman|z[\s-]score|f[\s-]score|"
    r"undervalued|overvalued|fairly[\s-]valued|valuation|"
    r"revenue\s+growth|profit\s+growth|pat\s+growth|eps\s+growth|"
    r"promoter\s+holding|fii\s+buying|dii\s+buying|shareholding|"
    r"financially\s+(?:strong|weak|sound|healthy)|"
    r"quality\s+(?:stock|company|business)"
    r")\b",
    re.IGNORECASE,
)

_TECHNICAL = re.compile(
    r"\b("
    r"technical(?:s|ly|al\s+analysis|s?\s+strong|s?\s+weak)?|"
    r"rsi|macd|moving\s+average|sma|ema|bollinger|atr|"
    r"chart(?:\s+says?|pattern|signal)?|"
    r"momentum|breakout|oversold|overbought|"
    r"support|resistance|trend(?:ing)?|"
    r"buy\s+signal|sell\s+signal|technically"
    r")\b",
    re.IGNORECASE,
)

_STRESS_TEST = re.compile(
    r"\b("
    r"stress\s*test|stress\s+scenario|crash\s+scenario|"
    r"what\s+if\s+(?:market|nifty|sensex|equity|portfolio)\s+(?:crashes?|falls?|drops?|tanks?)|"
    r"covid\s*(?:crash|scenario|2020)?|gfc\b|2008[\s\-]+(?:style|crash|crisis|scenario)|"
    r"rate\s+shock|simulate\s+(?:crash|drop|fall|scenario)|"
    r"portfolio\s+(?:under|in\s+a)\s+(?:crash|crisis|downturn)|"
    r"market\s+crash|bear\s+market\s+(?:impact|scenario|simulation)|"
    r"(?:how\s+much|what)\s+(?:would|will)\s+i\s+lose|"
    r"downside\s+(?:risk|scenario)|tail\s+risk"
    r")\b",
    re.IGNORECASE,
)

_PORTFOLIO_PERF = re.compile(
    r"\b("
    r"(?:my\s+)?(?:portfolio|overall)\s+(?:xirr|return|cagr|performance|gain|growth)|"
    r"xirr\b|"
    r"how\s+(?:is|are)\s+(?:my|the)\s+(?:portfolio|investments?)\s+(?:doing|performing|growing)|"
    r"(?:total|overall|net)\s+(?:return|gain|profit|xirr|cagr)\s+(?:on\s+)?(?:my\s+)?(?:portfolio|investments?)|"
    r"portfolio\s+(?:performance|summary|health|snapshot|breakdown|analytics)"
    r")\b",
    re.IGNORECASE,
)

# Regex to capture a stock symbol mentioned in technical queries
# Matches uppercase 2-10 letter tokens that look like NSE symbols
_STOCK_SYMBOL = re.compile(r"\b([A-Z]{2,10}(?:BANK|FIN|IND|LTD|AUTO)?)\b")

_CHART_REQUEST = re.compile(
    r"\b(show|chart|plot|graph|visuali[sz]e|compare|breakdown|donut|pie|bar)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\btop\s*(\d+)\b|\b(\d+)\s*(?:funds?|stocks?|companies|holdings?)\b", re.IGNORECASE)


def _extract_n(text: str, default: int = 5) -> int:
    m = _NUMBER.search(text)
    if m:
        for g in m.groups():
            if g and g.isdigit():
                n = int(g)
                if 1 <= n <= 50:
                    return n
    return default


def _extract_metric(text: str) -> Optional[str]:
    # Order: profit (most specific) > loss > value > return (catch-all)
    if _METRIC_LOSS.search(text):
        return "loss"
    if _METRIC_PROFIT.search(text):
        return "profit"
    if _METRIC_VALUE.search(text):
        return "value"
    if _METRIC_RETURN.search(text):
        return "return"
    return None


def _extract_grouping(text: str) -> Optional[str]:
    # Asset class first (most specific phrasing). Then company / sector /
    # amc / category. Company before sector because "company in pharma"
    # should resolve to company, not sector.
    if _GROUPING_ASSET_CLASS.search(text):
        return "asset_class"
    if _GROUPING_COMPANY.search(text):
        return "company"
    if _GROUPING_SECTOR.search(text):
        return "sector"
    if _GROUPING_AMC.search(text):
        return "amc"
    if _GROUPING_CATEGORY.search(text):
        return "category"
    return None


def _extract_symbols(text: str) -> List[str]:
    """Extract likely NSE stock symbols from user message.

    Only tokens that look like ticker symbols are kept: 3-12 uppercase letters,
    not in the English stopword set.
    """
    _STOPWORDS = {
        # articles, prepositions, pronouns
        "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN",
        "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM",
        "HIS", "HOW", "ITS", "MAY", "NOW", "OLD", "OWN", "SAY", "SHE",
        "TWO", "USE", "WAY", "WHO", "YES", "YET", "ANY", "HAD", "LET",
        "PUT", "TOO", "SET", "NEW", "WHO", "MAN", "WHY", "GOT", "DID",
        "LET", "FAR", "FEW", "FUN", "GOD", "HIT", "HOT", "JOB", "KEY",
        # financial / query words that are not tickers
        "RSI", "SMA", "EMA", "ATR", "MACD", "VWAP", "ADX", "OBV",
        "BUY", "SELL", "TOP", "LOW", "HIGH", "OPEN", "CLOSE",
        "WHAT", "DOES", "SHOW", "GIVE", "TELL", "KNOW", "LOOK", "FIND",
        "GOOD", "BEST", "WELL", "ALSO", "JUST", "EVEN", "THAN", "THEN",
        "INTO", "OVER", "WITH", "FROM", "THIS", "THAT", "THEY", "THEM",
        "HAVE", "WILL", "BEEN", "WERE", "WHEN", "MUCH", "EACH", "LIKE",
        "SOME", "MAKE", "VERY", "MORE", "ONLY", "BOTH", "BACK", "MOST",
        "SAID", "MANY", "SAME", "TAKE", "COME", "WENT", "COME", "GOES",
        "ABOUT", "AFTER", "AGAIN", "ALONG", "AMONG", "BEING", "BELOW",
        "COULD", "DOING", "EVERY", "FIRST", "FOUND", "GOING", "GREAT",
        "MIGHT", "NEVER", "OTHER", "RIGHT", "SHALL", "SINCE", "STILL",
        "THERE", "THOSE", "THREE", "TODAY", "UNDER", "UNTIL", "USING",
        "WATCH", "WHERE", "WHICH", "WHILE", "WHOSE", "WOULD", "YEARS",
        "ABOVE", "BASED", "BREAK", "CARRY", "CHECK", "CHOSE", "CLEAR",
        "EARLY", "FALSE", "GIVEN", "HAPPY", "HEAVY", "LATER", "LIGHT",
        "LOWER", "MAJOR", "MEANS", "MOVED", "OFTEN", "ORDER", "PLACE",
        "POINT", "POWER", "PRICE", "READY", "SMALL", "SOUND", "SPACE",
        "SPENT", "STAND", "START", "STOCK", "STUDY", "THING", "THINK",
        "TRADE", "TRUST", "TREND", "USUAL", "VALUE", "WATCH", "WORLD",
        "STRONG", "SIGNAL", "MARKET", "SECTOR", "BUYING", "STRONG",
        "ASKING", "CHARTS", "MOVING", "SAYING", "SEEING", "TRYING",
        "BEARISH", "BULLISH", "BREAKOUT", "OVERBOUGHT", "OVERSOLD",
        "ANALYSIS", "INDICATOR", "MOMENTUM", "TECHNICALLY",
        "COMPARE", "BETWEEN", "VERSUS", "AGAINST", "STOCKS", "FUNDS",
        "RATIO", "SCORE", "PEERS", "GROWTH", "REVENUE", "BUYING",
        "SIGNAL", "PIOTROSKI", "ALTMAN", "PROFIT", "EQUITY", "DEBT",
        "HOLDING", "SECTOR", "MARKET", "COMPANY", "ANALYSIS",
    }
    tokens = _STOCK_SYMBOL.findall(text.upper())
    return [t for t in tokens if t not in _STOPWORDS and len(t) >= 3]


def classify_intent(message: str) -> Intent:
    """Top-level entry point. Returns an Intent with name + slots."""
    msg = (message or "").strip()
    chart = bool(_CHART_REQUEST.search(msg))

    # ── 0a. MF performance / analytics questions ─────────────────────
    # Must fire before fundamental — "Sharpe ratio of this fund" → MF,
    # not fundamental (Sharpe in stock context is rare).
    if _MF.search(msg) or _MF_CATEGORY.search(msg):
        symbols = _extract_symbols(msg)
        return Intent(
            name="mf_analysis",
            chart_requested=chart,
            raw=msg,
            extras={"symbols": symbols},
        )

    # ── 0b. Fundamental analysis questions ───────────────────────────
    # Must fire before technical so "Is RELIANCE fundamentally strong?"
    # routes to fundamentals, not the technical intent.
    if _FUNDAMENTAL.search(msg):
        symbols = _extract_symbols(msg)
        return Intent(
            name="fundamental_analysis",
            chart_requested=chart,
            raw=msg,
            extras={"symbols": symbols},
        )

    # ── 0b. Technical analysis questions ─────────────────────────────
    if _TECHNICAL.search(msg):
        symbols = _extract_symbols(msg)
        return Intent(
            name="technical_analysis",
            chart_requested=chart,
            raw=msg,
            extras={"symbols": symbols},
        )

    # ── 0d. Portfolio XIRR / overall performance ──────────────────────
    # Must fire before ranking — "how is my portfolio performing" should
    # return overall XIRR, not a ranked list of individual holdings.
    if _PORTFOLIO_PERF.search(msg):
        return Intent(name="portfolio_perf", chart_requested=False, raw=msg)

    # ── 0e. Stress test / crash scenario ─────────────────────────────
    if _STRESS_TEST.search(msg):
        # Extract scenario keyword
        msg_l = msg.lower()
        if "gfc" in msg_l or "2008" in msg_l:
            scenario = "gfc_2008"
        elif "rate" in msg_l and ("shock" in msg_l or "hike" in msg_l):
            scenario = "rate_shock"
        else:
            scenario = "covid_2020"
        return Intent(
            name="stress_test",
            chart_requested=False,
            raw=msg,
            extras={"scenario": scenario},
        )

    # ── 1. Concentration / breakdown questions ────────────────────────
    # Tells us "show me my X distribution" — answer with a single
    # grouping query. Charts almost always make sense here.
    if _CONCENTRATION.search(msg) or chart:
        grouping = _extract_grouping(msg)
        if grouping in ("amc", "sector", "category", "asset_class", "company"):
            return Intent(
                name="concentration",
                grouping=grouping,
                chart_requested=True,  # always render a chart for concentration
                raw=msg,
            )

    # ── 2a. "Where to invest fresh money?" — must fire before _PLAN
    # because "improve diversification" / "deploy fresh money" should
    # surface ONLY the underweight bucket recommendation, not the full
    # plan (which would mix EXITs with the answer).
    if _INVEST_FRESH.search(msg):
        # Try to pull out the ₹ amount the user mentioned
        m = re.search(
            r"(?:₹|rs\.?|rupees?)\s*([\d,]+(?:\.\d+)?)\s*(?:lakh|l|k|crore|cr|thousand)?",
            msg, re.IGNORECASE,
        )
        amount = None
        if m:
            try:
                raw_num = float(m.group(1).replace(",", ""))
                tail = msg[m.end(1):m.end(1) + 6].lower().strip()
                if tail.startswith(("lakh", "l ", "lakhs")) or tail == "l":
                    amount = raw_num * 100_000
                elif tail.startswith(("crore", "cr")):
                    amount = raw_num * 10_000_000
                elif tail.startswith("k"):
                    amount = raw_num * 1_000
                else:
                    amount = raw_num
            except Exception:  # noqa: BLE001
                pass
        return Intent(
            name="invest_fresh",
            chart_requested=False,
            raw=msg,
            extras={"amount_rs": amount},
        )

    # ── 2. Action-plan / "what should I do" questions ─────────────────
    # MUST fire before ranking — "top 3 actions I should take" matches
    # both _RANK_TRIGGERS ("top") and _PLAN ("actions I should take");
    # the user wants the action plan, not a ranking of holdings.
    if _PLAN.search(msg):
        return Intent(name="plan", chart_requested=False, raw=msg)

    # ── 3. Ranking questions ──────────────────────────────────────────
    # "Top N funds by Y" / "best performer" / "worst loss" / "stocks in
    # the red" — also fires when a metric is named without a rank-trigger
    # word, since "which holdings are in loss" still wants ranked output.
    metric_implies_rank = bool(
        _METRIC_LOSS.search(msg) or _METRIC_PROFIT.search(msg)
    )
    if _RANK_TRIGGERS.search(msg) or metric_implies_rank:
        metric = _extract_metric(msg) or "profit"  # default to profit if not specified
        grouping = _extract_grouping(msg)
        return Intent(
            name="ranking",
            metric=metric,
            n=_extract_n(msg, 5),
            grouping=grouping,
            chart_requested=chart,
            raw=msg,
        )

    # ── 3. Overlap / redundancy ───────────────────────────────────────
    if _OVERLAP.search(msg):
        return Intent(name="overlap", chart_requested=chart, raw=msg)

    # ── 4. Tax ────────────────────────────────────────────────────────
    if _TAX.search(msg):
        return Intent(name="tax", chart_requested=chart, raw=msg)

    # ── 5. Allocation drift / on-target check ─────────────────────────
    # Must fire BEFORE goals — "am I on target?" / "how far am I off
    # target?" should ask the deviation engine, not the goals retriever.
    if _DRIFT.search(msg):
        return Intent(name="drift", chart_requested=chart or True, raw=msg)

    # ── 6. Goals ──────────────────────────────────────────────────────
    if _GOALS.search(msg):
        return Intent(name="goals", chart_requested=chart, raw=msg)

    # ── 6. Health / scorecard ─────────────────────────────────────────
    if _HEALTH.search(msg):
        return Intent(name="health", chart_requested=chart, raw=msg)

    # ── 8. Fallback ───────────────────────────────────────────────────
    # Generic conversational queries — give the LLM a tiny portfolio
    # summary so it can still answer "explain this fund" / "what does
    # XIRR mean for me" without hallucinating names.
    return Intent(name="generic", chart_requested=chart, raw=msg)
