"""Which Research Copilot answer a question asks for (Wave 1, owner 2 Nov 2026: "complete the partial built first").

docs/research_copilot/RESEARCH_COPILOT_REQUIREMENTS.md, categories 2, 3, 6, 7, 8, 13 and the runnable half of 14. Deterministic
patterns only, no LLM. The shared resolver (intents.resolve_intent) calls `research_intent`:

    a named stock       after the trade questions (still valid, book profits, position size, entry/stop/target, "a buy now")
                        and before the market-intelligence event chips
    the thread's stock  when the question names none but is company-shaped ("What is the current ratio?"), before the
                        market-wide answers. A market-wide question ("which stocks…", "find stocks…") is never a company question.

    financial_trend   revenue, EBITDA, PAT, margins, EPS, ROE/ROCE over quarters and fiscal years
    valuation_view    P/E, P/B, EV/EBITDA, "expensive or cheap", premium/discount, the P/E range, growth scenarios
    ownership_trend   promoter / FII / DII / MF holding over quarters, pledge level, which fund houses moved
    peer_compare      two or more companies, or one company against its sector peers
    company_risks     debt, interest cover, liquidity, cash flow vs profit, receivables, working capital, pledge, red flags

Deliberately NOT a visual answer (None, so the chat takes its usual LangGraph path):
    a research thesis, an investment case or a research report   (category 15/26, not built; "Build a research thesis for
                        TCS" used to reach trade_validity because of a bare "thesis")
    causal questions ("why did margins fall?", "what is driving growth?") and segment questions: they need the filings' text,
                        not a numbers card, and a card would read as the answer to "why"

Ownership, trend vs event (decided 2 Nov 2026): a question about a holding's LEVEL or DIRECTION over quarters ("has promoter
holding increased?", "promoter holding over time", "is smart money accumulating this stock?", "which funds entered?") is
ownership_trend (nidp.shareholding_pattern + disclosed MF holdings). A question about a DISCLOSURE ("pledge change", SAST,
insider trades, ownership filings, disclosures, announcements) stays with event_intelligence's Ownership chip, the filings feed.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

RESEARCH_INTENTS = ("financial_trend", "valuation_view", "ownership_trend", "peer_compare", "company_risks")
MAX_COMPARE = 5                     # companies one comparison names at most (the subject plus four)
MAX_QUARTERS = 12
MAX_YEARS = 10

# Metric acronyms that the symbol resolver would otherwise pass through as tickers (probed 2 Nov 2026: EV, FCF, GNPA, NIM, TTM
# came back as symbols). intents.NOT_A_STOCK carries them.
METRIC_WORDS = frozenset({"EV", "FCF", "GNPA", "NNPA", "NPA", "NIM", "TTM", "CASA", "CRAR", "EBIT", "PBT", "CAGR", "OPM", "NPM",
                          "QOQ", "YOY", "CFO", "EPS", "PAT", "ROE", "ROCE", "ROA", "EBITDA", "CAPEX"})

# ── wording that gets no visual answer ───────────────────────────────────────
_THESIS = re.compile(
    r"\b(research|investment|complete|full|detailed|bull(ish)?\s+(and|&|vs)\s+bear(ish)?)\s+(thesis|case|report)\b|"
    r"\b(build|write|create|prepare|generate|draft|make)\s+(me\s+)?(a|an|the|my)?\s*(\w+\s+){0,2}(thesis|research\s+report)\b|"
    r"\bthesis\s+(for|on|of|about)\b(?!.{0,40}\b(still|weaken\w*|intact|valid|broken|changed)\b)|"
    r"\bresearch\s+report\b|\bbull\s+case\b.{0,40}\bbear\s+case\b|\bbear\s+case\b.{0,40}\bbull\s+case\b", re.I)
_CAUSAL = re.compile(
    r"^\s*(why\b|what\s+(caused|causes|drove|drives|explains|led\s+to)\b)|\bwhat\s+(is|are)\s+driving\b|\bwhy\s+(did|is|are|does|has|have)\b|"
    r"\bsegments?\b|\bsegment[- ]wise\b|\b(in)?organic\b|\bacquisition[- ]driven\b", re.I)
_CAUSAL_KEEP = re.compile(r"\btrad(e|es|ing)\s+at\s+a\s+(premium|discount)\b", re.I)
# Not about a company at all (a fund, the user's own book, the market).
_NOT_COMPANY = re.compile(
    r"\b(debt|liquid|index|equity|hybrid|elss|gilt|overnight|flexi\s*cap|small\s*cap|mid\s*cap|large\s*cap)\s+funds?\b|\bsip\b|\bnav\b|"
    r"\bmy\s+(portfolio|holdings?|investments?)\b", re.I)
# Only for the thread's stock: a question about the market, or a list of stocks, is not about the stock in the thread.
_MARKET_WIDE = re.compile(
    r"\b(which|what)\s+(other\s+)?(stocks?|companies|shares|names|sectors?|industries)\b|"
    r"\b(find|list|show|screen|scan)\s+(me\s+)?(all\s+)?(the\s+)?(stocks?|companies|shares)\b|"
    r"\b(stocks?|companies|shares)\s+(with|where|that|having|whose)\b|\bacross\s+(the\s+)?(market|sectors?|industries)\b|"
    r"\b(the\s+)?(market|nifty|sensex|bank\s*nifty|economy|gdp)\b", re.I)

# Feed wording ("Show promoter holding changes", "any pledge this week?") is the market-wide event feed's, unless the question
# points at the company or asks for a trend window ("this company", "over 4 quarters").
_FEED = re.compile(r"\b(today|tonight|this\s+week|last\s+week|this\s+month)\b|\b(changes|updates|disclosures|filings|announcements)\b", re.I)
_DEICTIC = re.compile(r"\b(this|that|the)\s+(company|stock|share|counter|scrip|business|firm)\b|\b(it|its|it's)\b", re.I)
_WINDOW = re.compile(r"\bover\s+(time|the\s+(last|past)|\d+|two|three|four|five|eight)\b|\b\d+\s+quarters?\b|\bquarter[- ]on[- ]quarter\b", re.I)

# ── the five answers ─────────────────────────────────────────────────────────
_PEER_NOUN = re.compile(
    r"\bpeers?\b|\bpeer\s+group\b|\bcompetitors?\b|\bcompetition\b|\brivals?\b|\bcompeting\s+(companies|firms|players)\b|"
    r"\b(sector|industry)\s+(peers|average|median|players)\b|\brelative\s+to\s+(its\s+)?(peers|sector|industry)\b|"
    r"\bother\s+(companies|players|firms)\s+in\b", re.I)
# "Which has better margins?" / "Compare RADICO and …" (the second name not recognised): a comparison of one company and its peers.
_COMPARE = re.compile(r"\bwhich\s+(company|one|of\s+(them|these|those|the\s+\w+))\b|\bwhich\s+has\b|\bcompare[sd]?\b|\bcomparison\b|"
                      r"\bvs\.?(?=\s)|\bversus\b|\bbetter\s+than\b", re.I)
_WHICH = re.compile(r"\bwhich\s+(company|one|of\s+(them|these|those|the\s+\w+))\b|\bwhich\s+has\b", re.I)
_HOLDER = (r"(?:promoters?|promoter\s+group|fiis?|fpis?|foreign\s+(?:institutional\s+)?(?:investors?|institutions?)|diis?|"
           r"domestic\s+institutions?|mutual\s+funds?|mfs?|institutions?|institutional(?:\s+investors?)?|insurance\s+companies|insurers)")
_MOVE = (r"(?:increas\w*|decreas\w*|ris(?:e|en|es|ing)|fall(?:en|ing|s)?|fell|declin\w*|drop\w*|up|down|chang\w*|trend\w*|"
         r"over\s+time|history|accumulat\w*|buying|selling|adding|trimming|cut\w*|rais\w*)")
_OWNERSHIP = re.compile(
    rf"\b{_HOLDER}\s+(?:holding|holdings|stake|shareholding|ownership|share|exposure)\b|"
    rf"\b(?:holding|stake|shareholding|ownership)\s+(?:of|by)\s+(?:the\s+)?{_HOLDER}\b|"
    r"\bshareholding(?:\s+pattern)?\b|\bownership\s+(?:pattern|structure|trend|history|changes?\s+over|over)\b|\bwho\s+(?:owns|holds)\b|"
    rf"\bpledg\w*\b.{{0,30}}\b(?:{_MOVE}|level|how\s+much|percent|%)|\b(?:increas\w*|decreas\w*|ris(?:e|en|ing)|declin\w*)\b.{{0,30}}\bpledg\w*|"
    rf"\b(?:smart\s+money|{_HOLDER})\b.{{0,25}}\b(?:accumulat\w*|buying|selling|adding|trimming|exiting|entered|exited|exit|enter)\b|"
    r"\bwhich\s+(?:funds?|fund\s+houses?|amcs?|mutual\s+funds?|institutions?|schemes?)\b.{0,30}\b(?:entered|exited|bought|sold|added|"
    r"hold|holds|own|owns|increas\w*|reduc\w*|cut)\b|"
    r"\binstitutional\s+(?:buying|selling|ownership|holding|support|interest)\b|\bpromoters?\s+(?:buying|selling|buy|sell|sold|bought)\b",
    re.I)
# A disclosure, not a trend: the event feed's Ownership chip answers these.
_OWN_EVENT = re.compile(
    r"\bfilings?\b|\bdisclosures?\b|\bsast\b|\binsider\b|\bencumbrance\b|\bpledg\w*\s+changes?\b|\bchanges?\s+in\s+(the\s+)?pledg\w*|"
    r"\bannouncements?\b|\bnotices?\b|\bstake\s+sales?\b|\b(bulk|block)\s+deals?\b", re.I)
_VALUATION = re.compile(
    r"\bvaluations?\b|\bvalued\b|\b(expensive|cheap|costly|pricey)\b|\b(over|under)[- ]?valued\b|\bfair(ly)?\s+valued\b|"
    r"\bp\s*/\s*e\b|\bpe\s+(ratio|multiple|range|band|history)\b|\bpe\b\s*\??\s*$|\bprice[- ]to[- ](earnings|book|sales)\b|\bp\s*/\s*b\b|"
    r"\bpb\s+ratio\b|\bev\s*/\s*ebitda\b|\bev\s+to\s+ebitda\b|\benterprise\s+value\b|\b(earnings|valuation)\s+multiples?\b|"
    r"\btrad(e|es|ing)\s+at\s+a\s+(premium|discount)\b|\b(premium|discount)\s+to\s+(its\s+)?(peers|sector|history|historical)\b|"
    r"\bpric(ing|ed)\s+in\b|\bjustif(y|ies)\b.{0,30}\bvaluation\b|\bif\s+(earnings|profits?|eps)\s+grow\w*\b|"
    r"\b(earnings|profits?|eps)\s+grow\w*\s+(by\s+)?\d", re.I)
_RISKS = re.compile(
    r"\brisks\b|\b(biggest|key|main|major|top|financial|governance|business|balance[- ]sheet|liquidity|solvency|credit|debt|leverage)\s+risks?\b|"
    r"\brisk\s+(factors?|analysis|assessment|checks?)\b|\bwhat\s+could\s+go\s+wrong\b|\bred[- ]?flags?\b|\bforensic\b|\bwarning\s+signs?\b|"
    r"\bdebt\b|\bborrowings?\b|\bleverage(d)?\b|\bd\s*/\s*e\b|\bdebt[- ]to[- ]equity\b|\binterest\s+cover(age)?\b|"
    r"\bcurrent\s+ratio\b|\bliquidity\b|\bhow\s+much\s+cash\b|\bcash\s+(position|balance|reserves?|pile|on\s+(the\s+)?(books|balance\s+sheet))\b|"
    r"\bcash[- ]?flows?\b|\bfree\s+cash\b|\bfcf\b|\boperating\s+cash\b|\bcfo\b|\bcash\s+conversion\b|\bconvert\w*\b.{0,20}\bcash\b|"
    r"\bprofits?\b.{0,30}\bcash\b|\breceivables?\b|\bdebtors?\b|\bworking\s+capital\b|\binventor(y|ies)\b|"
    r"\bbalance\s+sheet\b|\bfinancial\s+(health|strength|position|stability)\b|\bsolvency\b|\bgovernance\b|\brelated[- ]party\b|"
    r"\bauditor\b|\bcontingent\s+liabilit\w+", re.I)
_TREND = re.compile(
    r"\brevenues?\b|\bsales\b|\btop[- ]?line\b|\bturnover\b|\bebitda\b|\boperating\s+(profit|margins?|income)\b|\bmargins?\b|"
    r"\bpat\b|\bnet\s+(profit|income)\b|\bprofit(s|ability)?\b|\bbottom[- ]?line\b|\bearnings\s+(growth|trend|history|per\s+share)\b|\beps\b|"
    r"\broe\b|\broce\b|\breturn\s+on\s+(equity|capital(\s+employed)?)\b|\bgrowth\s+(trend|rate|history)\b|\b(qoq|yoy)\b|"
    r"\bquarter[- ]on[- ]quarter\b|\byear[- ]on[- ]year\b|\bfinancial\s+(performance|trend|history|analysis|track\s+record)\b|"
    r"\bgrow(n|th|ing)\b", re.I)

_GROWTH_PCT = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
_YEARS = re.compile(r"\b(\d{1,2}|three|four|five|six|seven|eight|nine|ten)\s+(fiscal\s+|financial\s+)?years?\b", re.I)
_QUARTERS = re.compile(r"\b(\d{1,2}|two|three|four|five|six|seven|eight|ten|twelve)\s+quarters?\b", re.I)
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
# The pieces a "compare A, B and C" sentence is split into, each then read for a company.
_LIST_SPLIT = re.compile(r"\s*(?:,|;|\bvs\.?(?=\s)|\bversus\b|\band\b|\bor\b|\bwith\b|\bagainst\b|\s&\s)\s*", re.I)


def is_research_thesis(message: str) -> bool:
    """A research thesis, investment case or research report: not built in W1, so no visual answer at all."""
    return bool(_THESIS.search(message or ""))


def research_words(message: str) -> bool:
    """The question reads like one of the five answers (used to decide whether the thread's stock is worth reading)."""
    msg = message or ""
    if _NOT_COMPANY.search(msg) or is_research_thesis(msg):
        return False
    return any(rx.search(msg) for rx in (_PEER_NOUN, _OWNERSHIP, _VALUATION, _RISKS, _TREND))


def _n(raw: str) -> int:
    return _WORDS.get(raw.lower()) or int(raw)


def window_params(message: str) -> Dict[str, Any]:
    """The window the question asks for: "last 5 years" → years, "last 4 quarters" → quarters (capped). Absent → {}."""
    out: Dict[str, Any] = {}
    m = _YEARS.search(message or "")
    if m:
        out["years"] = max(1, min(MAX_YEARS, _n(m.group(1))))
    m = _QUARTERS.search(message or "")
    if m:
        out["quarters"] = max(1, min(MAX_QUARTERS, _n(m.group(1))))
    return out


def growth_scenarios(message: str) -> List[float]:
    """The growth rates a scenario question names ("if earnings grow 15%, 20% or 25%"); [] when none (no scenario is shown)."""
    msg = message or ""
    if not re.search(r"\bgrow\w*\b|\bgrowth\b", msg, re.I):
        return []
    vals: List[float] = []
    for raw in _GROWTH_PCT.findall(msg):
        v = float(raw)
        if 0 < v <= 60 and v not in vals:
            vals.append(v)
    return vals[:4]


def symbols_in(message: str, first: Optional[str], stock_in: Callable[[str], Optional[str]]) -> List[str]:
    """Every company a comparison names, in the order the sentence names them, by the resolver's own reading of each piece ("HDFC
    Bank, ICICI Bank and Axis Bank" → three; "Compare Reliance vs Asian Paints" → RELIANCE first, although the resolver's reading
    of the whole sentence picks Asian Paints). `first` is that whole-sentence reading: kept, in front, when splitting broke its
    name ("Larsen & Toubro")."""
    out: List[str] = []
    for piece in _LIST_SPLIT.split(message or ""):
        if not piece or len(piece) > 80:
            continue
        sym = stock_in(piece)
        if sym and sym not in out and sym.upper() not in METRIC_WORDS:
            out.append(sym)
        if len(out) >= MAX_COMPARE:
            break
    if first and first not in out:
        out.insert(0, first)
    return out[:MAX_COMPARE]


def research_intent(message: str, symbols: List[str], from_thread: bool = False) -> Optional[Dict[str, Any]]:
    """{"name", "symbol", "params"} for one of the five answers, or None. `symbols` are the companies named (the first is the
    subject); for the thread's stock it is that one stock. The caller builds the Intent (this module does not import intents)."""
    msg = (message or "").strip()
    if not msg or not symbols or is_research_thesis(msg) or _NOT_COMPANY.search(msg):
        return None
    if from_thread and (_MARKET_WIDE.search(msg) or (_FEED.search(msg) and not (_DEICTIC.search(msg) or _WINDOW.search(msg)))):
        return None
    if _CAUSAL.search(msg) and not _CAUSAL_KEEP.search(msg):
        return None
    subject = symbols[0]
    params: Dict[str, Any] = {}
    if len(symbols) >= 2 or _PEER_NOUN.search(msg) or _WHICH.search(msg):
        params["symbols"] = list(symbols[:MAX_COMPARE])
        return {"name": "peer_compare", "symbol": subject, "params": params}
    if _OWNERSHIP.search(msg):
        if _OWN_EVENT.search(msg):
            return None                               # a disclosure question: the event feed's Ownership chip answers it
        return {"name": "ownership_trend", "symbol": subject, "params": params}
    if _VALUATION.search(msg):
        growth = growth_scenarios(msg)
        if growth:
            params["growth"] = growth
        return {"name": "valuation_view", "symbol": subject, "params": params}
    if _RISKS.search(msg):
        return {"name": "company_risks", "symbol": subject, "params": params}
    if _TREND.search(msg):
        params.update(window_params(msg))
        return {"name": "financial_trend", "symbol": subject, "params": params}
    if _COMPARE.search(msg):
        # "Compare RADICO and United Spirits" where only one name was recognised: that company against its peers, and the
        # answer says a named company may be missing.
        return {"name": "peer_compare", "symbol": subject, "params": {"symbols": [subject], "one_recognised": True}}
    return None
