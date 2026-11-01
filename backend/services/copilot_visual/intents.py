"""Which visual answer a Copilot question asks for (Release 1 of docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md).

Deterministic patterns only, no LLM. `resolve_intent` returns an Intent or None; None means the question is not one of
the seven Release-1 intents and the chat takes its usual path unchanged.

    market_view        "What is the market view today?", "Is the market trending?", "Nifty and Bank Nifty view"
    smart_money        "Where is smart money moving?", FII / DII flows, sector rotation, long build-up / short covering
    top_opportunities  "Today's top 5 opportunities" (N parsed, default 5, at most 10)
    breakouts          "Which breakouts are confirmed?"
    unusual_volume     "Which stocks have unusual volume?"
    stock_decision     "Is X a buy now?", "entry, target and stop-loss for X", "trade plan for X"; "this stock" and a
                       bare "what is the entry, target and stop-loss?" use the thread's last stock (`last_symbol`)
    expected_move      "What is the expected move in Nifty?" (NIFTY or BANKNIFTY), PCR / max pain / ATM IV of an index

Release 2:
    open_trades        "What are my open trades doing?", "my open positions", "my broker positions" — the user's broker book
                       (live when signed in, else the last stored read; the connect prompt when none) and the paper book
    fno_setups         "Which F&O setups are attractive?" — index and stock F&O, ranked by fit to today's regime
    trade_validity     "Is my trade in X still valid?", "has my thesis on X weakened?" — a named or thread stock
    exit_options       "Should I book profits or hold X?", "should I trail my stop?" — a named or thread stock
    position_size      "How much should I risk?", "what position size…" — the account's budget; a named stock adds its own

Release 3:
    daily_review       "What did I learn from today's trades?", "How did I do this week?", "my mistakes today" — the
                       paper book's closed trades and risk checks for the day (or the ISO week), `params.period`

Sector view (31 Oct 2026):
    sector_rotation    "Which sectors are leading and lagging?", "Show sector rotation today", "sector heatmap" — the sector
                       heatmap first, each sector with its five strongest stocks by the day's move

Results and market-research events (31 Oct 2026):
    results_calendar   "Which companies report results this week?" (today / tomorrow / yesterday / this week / next week / last
                       week; F&O only; a sector) — the desk's results calendar with each declared result's stored AI summary
    event_intelligence "Any order wins this week?", "M&A announcements today", "promoter pledge changes", "bulk and block deals",
                       "what did management say on the earnings call?", "How were TCS results?" — the Market Intelligence feed
                       the desk's chips read (Announcements, Results, Calls & guidance, Orders, M&A & actions, Ownership,
                       Bulk & block, Regulatory, Exchange notices), `params.category` = the chip, an optional stock

Not ours (None): the user's long-term portfolio / holdings / P&L (that is the CAS-portfolio_analyst's book, not the
paper-trading desk's), averaging a position, "what should I avoid today" (Q14, not built).

A stock is found with the Copilot's own resolver (services/copilot_tools/symbol_resolver.py), but F&O, PCR, P&L, GIFT,
IV, OI, ATM, VIX and the index names are never a stock here: they are removed before resolving and refused after.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

INTENTS = ("market_view", "smart_money", "top_opportunities", "breakouts", "unusual_volume", "stock_decision",
           "expected_move", "open_trades", "fno_setups", "trade_validity", "exit_options", "position_size", "daily_review",
           "sector_rotation", "results_calendar", "event_intelligence", "portfolio_hedge")
# Intents that read a stock (named or from the thread): the deictic/thread fallback applies to these, not just stock_decision.
SYMBOL_INTENTS = ("stock_decision", "trade_validity", "exit_options")


@dataclass(frozen=True)
class Intent:
    name: str
    symbol: Optional[str] = None              # a stock (named or thread-sourced); expected_move: NIFTY | BANKNIFTY
    params: Dict[str, Any] = field(default_factory=dict)
    symbol_from_thread: bool = False          # the stock came from the thread, not the message


# Upper-case tokens that are never a stock in a trader's question (market words, option words, order words).
NOT_A_STOCK = frozenset({
    "F&O", "FNO", "PCR", "P&L", "PNL", "GIFT", "IV", "IVP", "IVR", "OI", "ATM", "OTM", "ITM", "VIX", "INDIAVIX",
    "NIFTY", "NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "CE", "PE", "FUT", "SL",
    "TP", "RR", "EMA", "SMA", "RSI", "MACD", "ATR", "VWAP", "LTP", "NSE", "BSE", "EOD", "MTF", "MIS", "CNC", "NRML",
    "IST", "DII", "FII", "FPI", "MF", "SIP", "OK", "ENTRY", "EXIT", "TRADE", "PLAN", "SETUP", "BREAKOUT", "VOLUME", "STOP",
    "LOSS", "TARGET", "CALL", "PUT", "OPTION", "OPTIONS", "FUTURES", "INDEX", "MARKET", "TODAY", "NOW", "IS", "MY", "ME",
    "M&A", "MNA", "SAST", "ESOP", "SEBI", "QIP", "NCLT",            # corporate-event words (results / market-research events)
})
# The same words in any case (index and F&O words are never company names).
_ANY_CASE = frozenset({"f&o", "fno", "pcr", "p&l", "pnl", "gift", "iv", "oi", "atm", "vix", "nifty", "nifty50", "banknifty",
                       "finnifty", "midcpnifty", "sensex", "bankex", "m&a"})
_TOKEN = re.compile(r"[A-Za-z0-9&]+")
_BANK_NIFTY = re.compile(r"\b(bank\s*nifty|nifty\s*bank)\b", re.I)

# The user's long-term portfolio and the questions not built yet: never answered here (Release 2 moved its own
# phrases — open trades, book/hold/trail, F&O setups, position sizing, "still valid" — out of this gate, and Release 3
# the day's review; see the patterns below).
_NOT_OURS = re.compile(
    r"\bmy\s+(portfolio|holdings?|p&l|pnl)\b|\baverag(e|ing)\s+(down|up)\b|\bwhat\s+should\s+i\s+avoid\b", re.I)

_EXPECTED_MOVE = re.compile(
    r"\bexpected\s+move\b|\bimplied\s+move\b|\bhow\s+(much|far)\s+(can|will|could|may|might)\b.{0,40}\bmove\b|"
    r"\batm\s+iv\b|\bimplied\s+vol\w*|\bpcr\b|\bput[- ]call\s+ratio\b|\bmax\s+pain\b|\boi\s+walls?\b|\boption\s+chain\b|"
    r"\brange\s+(for|to|till|until)\s+(the\s+)?(this\s+)?(weekly\s+|monthly\s+)?expiry\b", re.I)
_INDEX_WORD = re.compile(r"\b(nifty|bank\s*nifty|banknifty|nifty\s*bank|index)\b", re.I)

_SMART_MONEY = re.compile(
    r"\bsmart\s+money\b|\bfiis?\b|\bdiis?\b|\bfpis?\b|\binstitution(al|s)?\b.{0,30}\b(flows?|buying|selling|money|activity)\b|"
    r"\bwhere\s+is\s+(the\s+)?money\b|\bmoney\s+(flow|flows|flowing|moving)\b|"
    r"\b(long|short)\s+build[- ]?ups?\b|\bshort\s+covering\b|\blong\s+unwinding\b|\bbuild[- ]?ups?\b", re.I)
# Sector questions have their own answer since 31 Oct 2026 (owner: "its a sector rotation intent so load the sector rotation
# heatmap"); `sector rotation` used to be a smart-money phrase and showed the FII/DII bars first.
_SECTOR_ROTATION = re.compile(
    r"\bsector\s+rotation\b|\bsectors?\s+(heat\s*map|rotation|performance|strength|leaders?|laggards?|trend|momentum|view|overview)\b|"
    r"\bheat\s*map\b.{0,20}\bsectors?\b|"
    r"\b(leading|lagging|strongest|weakest|best|worst|top|hot|cold)\s+(performing\s+)?sectors?\b|\bwhich\s+sectors?\b|"
    r"\bsectors?\b.{0,40}\b(leading|lagging|outperform\w*|underperform\w*|strong(er|est)?|weak(er|est)?|performing|"
    r"doing|moving|rotating|in\s+favou?r|out\s+of\s+favou?r)\b|"
    r"\b(lagging|leading|outperforming|underperforming)\b.{0,30}\bsectors?\b", re.I)
_UNUSUAL_VOLUME = re.compile(
    r"\bunusual(ly)?\s+(high\s+)?volumes?\b|\bvolume\s+(spikes?|surges?|shockers?|buzzers?)\b|"
    r"\b(high|heavy|abnormal|huge|big)\s+volumes?\b|\brelative\s+volume\b|\brvol\b", re.I)
_BREAKOUTS = re.compile(
    r"\bbreakouts\b|\bbreaking\s+out\b|\bbroke\s+out\b|\bconfirmed\s+breakouts?\b|\bbreakout\s+(stocks|candidates|list)\b|"
    r"\bwhich\b.{0,30}\bbreakout\b", re.I)
_TOP = re.compile(
    r"\btop\s+(\d{1,2}|three|five|ten)?\s*(trading\s+|trade\s+)?(opportunit\w+|ideas?|stocks?|setups?|trades?|picks?)\b|"
    r"\bbest\s+(trading\s+|trade\s+)?(opportunit\w+|ideas?|setups?|trades?)\b|\b(opportunit\w+|trade\s+ideas?)\s+(for\s+)?today\b|"
    r"\bwhat\s+(should|can|to)\s+i\s+(trade|buy)\s+today\b|\bwhat\s+to\s+(trade|buy)\s+today\b", re.I)
_TOP_NOT = re.compile(r"\b(gainers?|losers?|market\s+cap|dividend\w*|mutual\s+funds?|funds?|sip)\b", re.I)
_TOP_N = re.compile(r"\btop\s+(\d{1,2}|three|five|ten)\b", re.I)
_WORD_N = {"three": 3, "five": 5, "ten": 10}
_MARKET_VIEW = re.compile(
    r"\bmarket\s+(view|outlook|today|trend|mood|sentiment|pulse|summary|wrap|direction|breadth)\b|"
    r"\bhow\s+(is|was|did)\s+(the\s+)?market\b|\bmarket\s+(doing|looking)\b|"
    r"\b(is|was)\s+the\s+market\s+(trending|range[- ]?bound|volatile|bullish|bearish|up|down)\b|"
    r"\b(nifty|bank\s*nifty|banknifty)\b.{0,30}\b(view|outlook|today|trend|direction|key\s+levels)\b|"
    r"\b(view|outlook)\b.{0,30}\b(nifty|bank\s*nifty|banknifty)\b", re.I)

# ── Release 2 ────────────────────────────────────────────────────────────────

_OPEN_TRADES = re.compile(
    r"\bmy\s+open\s+(trades?|positions?)\b|\bopen\s+trades?\b|\bwhat\s+are\s+my\s+(trades?|positions?)\s+doing\b|"
    r"\bhow\s+are\s+my\s+(trades?|positions?)\s+(doing|going)\b|\bmy\s+(trades?|positions?)\s+today\b|"
    r"\bstatus\s+of\s+my\s+(trades?|positions?)\b|\bpaper\s+trades?\s+(status|summary)\b|"
    r"\b(my\s+)?broker\s+(positions?|trades?|book|portfolio)\b", re.I)
_FNO_SETUPS = re.compile(
    r"\b(f&o|fno|options?|futures)\s+(setups?|strateg(y|ies)|trades?|ideas?|opportunit\w+)\b|"
    r"\bwhich\s+(f&o|fno|options?)\b.{0,30}\battractive\b|\boptions?\s+trading\s+ideas?\b|"
    r"\bdefined[- ]risk\s+(setups?|strateg(y|ies))\b", re.I)
_TRADE_VALIDITY = re.compile(
    r"\bstill\s+valid\b|\bthesis\b|\bweaken(ed|ing)?\b|\bhas\s+(my|the)\s+setup\s+changed\b|"
    r"\bis\s+(my|the)\s+trade\s+(still\s+)?(ok|okay|good|intact)\b", re.I)
_EXIT_OPTIONS = re.compile(
    r"\bbook(ing)?\s+(the\s+)?(profits?|gains)\b|\bshould\s+i\s+(hold|exit|sell|book)\b|\b(or|and)\s+hold\b|"
    r"\btrail(ing)?\s+(my\s+)?stop\b|\bmove\s+(my\s+)?stop\s+to\s+breakeven\b|\bbreak[- ]?even\b|"
    r"\bbook\s+partial\b|\bpartial\s+(profit|exit)\b", re.I)
_POSITION_SIZE = re.compile(
    r"\bposition\s+siz\w*|\bhow\s+much\s+(should|can|do)\s+i\s+risk\b|\bhow\s+many\s+(shares?|lots?|units?)\s+(should|can)\s+i\s+"
    r"(buy|trade|take)\b|\bwhat\s+(size|quantity)\s+(should|can)\s+i\s+(take|buy|trade)\b|\brisk\s+budget\b|"
    r"\bdaily\s+loss\s+limit\b.{0,20}\bused\b", re.I)

# ── Quick Hedge: protecting the user's portfolio against a Nifty fall (services/quick_hedge) ──────────────────
# Checked BEFORE the _NOT_OURS gate: "protect my portfolio" names the portfolio but asks for a hedge, which this engine
# answers; every other question about "my portfolio" is still not ours. A named stock is never a portfolio hedge.
_PORTFOLIO_HEDGE = re.compile(
    r"\b(hedg\w*|protect\w*|insur\w*|safeguard|shield)\b.{0,40}\b(portfolio|holdings?|investments?|stocks|shares|equit\w+|money|savings|me|us)\b|"
    r"\b(portfolio|holdings?)\b.{0,30}\b(hedg\w*|protection|protect)\b|\bdownside\s+protection\b|\bquick\s+hedge\b|"
    r"\b(put\s+protection|protective\s+put)\b|\b(my|this|the)\s+hedge\b|\bhedge\s+(ideas?|options?|strateg\w+)\b|"
    r"\b(type|kind)s?\s+of\s+hedge\b|\b(cheapest|best)\s+(protection|hedge)\b|\bhow\s+much\s+protection\b|\bprotection\s+(options?|ideas?)\b|"
    r"\b(don'?t|do\s+not)\s+want\s+to\s+lose\s+more\s+than\b|"
    r"\bwhat\s+(happens|would\s+happen|if)\b.{0,30}\b(nifty|market|sensex)\b.{0,20}\b(fall|falls|drop|drops|crash\w*|declin\w+|correct\w+)\b", re.I)
_HEDGE_NOT = re.compile(r"\bhedge\s+funds?\b|\bstop[- ]?loss\b|\bexit\b", re.I)
_HEDGE_FALL = re.compile(
    r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:fall|drop|crash|correction|decline|dip|down)|"
    r"(?:fall|falls|drop|drops|crash|correction|decline|dip)\w*\s*(?:of|by|to|about|around)?\s*(\d{1,2}(?:\.\d+)?)\s*%|"
    r"against\s+an?\s+(\d{1,2}(?:\.\d+)?)\s*%", re.I)
_HEDGE_LOSE_PCT = re.compile(
    r"(?:lose|loss|losing|tolerate|accept|afford)\w*\s*(?:more\s+than|over|above|beyond|up\s+to|at\s+most|of|about|around)?\s*(\d{1,2}(?:\.\d+)?)\s*%", re.I)
_HEDGE_LOSE_RS = re.compile(
    r"(?:lose|loss|losing|tolerate|accept|afford|risk)\w*\s*(?:more\s+than|over|above|beyond|up\s+to|at\s+most|of|about|around)?\s*"
    r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|k|thousand|l)?\b(?!\s*%)", re.I)
_HEDGE_UNIT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3, "thousand": 1e3}
_HEDGE_TENOR = (("1w", re.compile(r"\b(1|one|a)\s+week\b|\bweekly\b", re.I)), ("2w", re.compile(r"\b(2|two)\s+weeks?\b|\bfortnight\b", re.I)),
                ("3m", re.compile(r"\b(3|three)\s+months?\b|\bquarter\b", re.I)), ("1m", re.compile(r"\b(1|one|a)\s+month\b|\b30\s+days\b|\bmonthly\b", re.I)))
_HEDGE_MODE = (("maximum", re.compile(r"\b(max(imum)?|most)\s+protection\b", re.I)), ("lowest_cost", re.compile(r"\blowest\s+cost\b|\bcheap(er|est)?\b|\blow[- ]cost\b|\bput\s+spread\b", re.I)),
                ("balanced", re.compile(r"\bbalanced\b", re.I)))


def hedge_params(message: str) -> Dict[str, Any]:
    """What a hedge question states: the fall feared, the loss tolerated (rupees or percent), the period and the choice asked about.
    Only what is written; the builder says which defaults it used for the rest."""
    out: Dict[str, Any] = {}
    m = _HEDGE_FALL.search(message)
    if m:
        v = float(next(g for g in m.groups() if g))
        if 0 < v <= 50:
            out["expected_fall_pct"] = v
    m = _HEDGE_LOSE_PCT.search(message)
    if m and 0 < float(m.group(1)) <= 100:
        out["tolerance_pct"] = float(m.group(1))
    else:
        m = _HEDGE_LOSE_RS.search(message)
        if m:
            v = float(m.group(1).replace(",", "")) * _HEDGE_UNIT.get((m.group(2) or "").lower(), 1.0)
            if v > 0:
                out["tolerance_rs"] = v
    for tenor, rx in _HEDGE_TENOR:
        if rx.search(message):
            out["tenor"] = tenor
            break
    for mode, rx in _HEDGE_MODE:
        if rx.search(message):
            out["mode"] = mode
            break
    return out


# ── Release 3 ────────────────────────────────────────────────────────────────
_DAILY_REVIEW = re.compile(
    r"\blearn(ed|t)?\s+from\b|\bwhat\s+did\s+i\s+learn\b|\bhow\s+did\s+i\s+do\b|"
    r"\bmistakes?\b.{0,25}\b(today|this\s+week|trades?|trading)\b|\bmy\s+mistakes\b|"
    r"\breview\s+(of\s+)?(my\s+)?(trades?|trading|day|week)\b|\b(daily|weekly|day's|week's|post[- ]trade)\s+review\b|"
    r"\bhow\s+(was|were)\s+my\s+(trades?|trading|day|week)\b", re.I)
_WEEK = re.compile(r"\b(this|the|past|last)\s+week\b|\bweekly\b|\bweek's\b", re.I)

# A decision about one stock. Trade words count in any persona; "buy now" style words only for a trader.
_TRADE_WORDS = re.compile(
    r"\bentry\b|\btargets?\b|\bstop[- ]?loss\b|\bstoploss\b|\bSL\b|\btrad(e|ing)\s+plan\b|\bhow\s+(should|do|can)\s+i\s+trade\b|"
    r"\bset[- ]?up\b|\bbreakout\b|\blevels?\s+(for|in|on)\b|\brisk[- ]?reward\b", re.I)
_BUY_WORDS = re.compile(
    r"\b(a\s+)?(good\s+)?buy\b|\bbuy\s+(now|today|here)\b|\bshould\s+i\s+(buy|enter|go\s+long)\b|\bgood\s+time\s+to\s+(buy|enter)\b|"
    r"\bworth\s+buying\b|\benter\s+(now|today|here)\b", re.I)
_DEICTIC = re.compile(r"\b(this|that|the\s+same)\s+(stock|share|one|name|company|counter|scrip)\b|\bis\s+it\b|\bfor\s+it\b|"
                      r"\bon\s+it\b", re.I)


# ── Results and market-research events (owner, 31 Oct 2026) ──────────────────────────────────────────────────────
# "Which companies report results this week?" went to the Filings analyst, which said it had no results calendar. The
# calendar and the event feed exist (desk: Market Desk › Market Intelligence); these patterns send the question to them.
_RES = re.compile(r"\b(results?|earnings|quarterly\s+numbers|q[1-4]\s*(fy\s*\d{2,4}\s*)?(results?|numbers|earnings))\b", re.I)
_REPORT_VERB = re.compile(r"\b(report(s|ing|ed)?|announc(e|es|ing|ed)|declar(e|es|ing|ed)|releas(e|es|ing)|publish(es|ing)?|due|"
                          r"scheduled|coming\s+up|upcoming|lined\s+up)\b", re.I)
_CAL_NOUN = re.compile(r"\b(results?|earnings)\s+(calendar|schedule|dates?|season)\b|\b(calendar|schedule)\s+(of|for)\s+(the\s+)?(results?|earnings)\b", re.I)
_RES_PERIOD = re.compile(r"\b(results?|earnings)\b.{0,12}\b(today|tomorrow|yesterday|tonight|this\s+week|next\s+week|last\s+week|"
                         r"coming\s+week|previous\s+week|past\s+week)\b", re.I)
# A question about a price move or a definition is not a calendar question.
_NOT_CALENDAR = re.compile(r"\b(react\w*|rall(y|ied|ies)|fell|fall(s|en)?|jump\w*|surg\w*|plung\w*|crash\w*|gap(ped)?\s+(up|down)|why)\b|"
                           r"^\s*(how\s+(to|do|does)|explain|define|what\s+(is|are|does)\s+(a|an|the)?\s*(quarterly\s+)?(results?|earnings)\b)", re.I)
_CONCEPT = re.compile(r"^\s*(what\s+(is|are|does|do)|explain|define|meaning\s+of|how\s+(does|do|to))\b", re.I)
_LISTING_CUE = re.compile(r"\b(today|tonight|yesterday|tomorrow|this\s+week|next\s+week|last\s+week|this\s+month|latest|recent|recently|new|"
                          r"any|which|show|list|biggest|largest|top|current|fresh)\b", re.I)
_BEAT_MISS = re.compile(r"\b(did|has|have|will|would)\b.{0,40}\b(beat|miss(ed)?)\b|\b(beat|miss(ed)?)\b.{0,25}\b(estimates?|expectations?|"
                        r"consensus|street|forecasts?|results?|earnings|numbers)\b", re.I)
_FNO_WORD = re.compile(r"\b(f&o|fno)\b", re.I)
# The desk's sector names (DaaS events calendar), by the words a trader uses.
_SECTOR_WORDS = (
    (r"\b(it|information\s+technology|software|tech)\b(?!\s*(trade|setup))", "Information Technology"),
    (r"\b(banks?|banking|nbfcs?|financials?|financial\s+services|insurers?|insurance)\b", "Financial Services"),
    (r"\b(pharma\w*|healthcare|hospitals?|health\s+care)\b", "Healthcare"),
    (r"\b(auto|autos|automobiles?|automotive)\b", "Automobile and Auto Components"),
    (r"\b(fmcg|consumer\s+goods)\b", "Fast Moving Consumer Goods"),
    (r"\b(metals?|mining|steel)\b", "Metals & Mining"),
    (r"\b(realty|real\s+estate)\b", "Realty"),
    (r"\b(oil|gas|energy)\b", "Oil Gas & Consumable Fuels"),
    (r"\bcapital\s+goods\b", "Capital Goods"),
    (r"\bchemicals?\b", "Chemicals"),
    (r"\bconsumer\s+durables?\b", "Consumer Durables"),
    (r"\b(telecom\w*)\b", "Telecommunication"),
    (r"\bpower\b", "Power"),
    (r"\b(cement|construction\s+materials?)\b", "Construction Materials"),
    (r"\btextiles?\b", "Textiles"),
)


def _calendar_period(msg: str) -> str:
    low = msg.lower()
    if re.search(r"\byesterday\b", low):
        return "yesterday"
    if re.search(r"\btomorrow\b", low):
        return "tomorrow"
    if re.search(r"\b(next|coming|following)\s+week\b", low):
        return "next_week"
    if re.search(r"\b(last|previous|past)\s+week\b", low):
        return "last_week"
    if re.search(r"\b(today|tonight)\b", low):
        return "today"
    return "this_week"


def _results_calendar(msg: str) -> Optional[Intent]:
    """"Which companies report results this week/today/tomorrow/next week?" — a list of companies (no one stock named)."""
    if not _RES.search(msg) or _NOT_CALENDAR.search(msg) or _EV_CALLS.search(msg):      # "earnings calls this week" is the calls chip
        return None
    if not (_CAL_NOUN.search(msg) or _REPORT_VERB.search(msg) or _RES_PERIOD.search(msg)):
        return None
    sector = next((name for pat, name in _SECTOR_WORDS if re.search(pat, msg, re.I)), None)
    return Intent("results_calendar", params={"period": _calendar_period(msg), "fno_only": bool(_FNO_WORD.search(msg)), "sector": sector})


# Event categories = the chips of the desk's Market Intelligence (frontend intel-data.ts INTEL_CHIPS), by the words a trader uses.
_EV_DEALS = re.compile(r"\b(bulk|block)\s+(and\s+(bulk|block)\s+)?deals?\b|\bbulk\s*/\s*block\b|\bbulk\s+and\s+block\b", re.I)
_EV_MNA = re.compile(
    r"\bm\s?&\s?a\b|\bmergers?\b|\bmerg(e|es|ed|ing)\b|\bacqui(re|res|red|ring|sitions?)\b|\bamalgamat\w+|\bde-?merg\w+|\bspin[- ]?offs?\b|"
    r"\bbuy[- ]?backs?\b|\bopen\s+offers?\b|\btake[- ]?overs?\b|\bstake\s+(sales?|purchases?|buys?|acquisitions?|hikes?|increases?|cuts?|sold|bought)\b|"
    r"\bdivest\w*|\bdelist\w*|\bjoint\s+ventures?\b|\bbonus\s+(issues?|shares?)\b|\bstock\s+splits?\b|\bsplit\s+announcements?\b|"
    r"\b(announc\w+|declar\w+|upcoming|recent|latest|any|new)\b.{0,20}\bdividends?\b|\bdividends?\b.{0,20}\b(announc\w+|declar\w+|"
    r"record\s+dates?|ex[- ]?dates?|this\s+week|today|tomorrow|upcoming)\b", re.I)
_EV_MNA_NOT = re.compile(r"\bdividend\s+(yield|stocks?|history|payout|calculator|tax)\b|\bdividend\b.{0,12}\b(yield|payout)\b", re.I)
_EV_ORDERS = re.compile(
    r"\border\s+(wins?|won|inflows?|intake|bagging|announcements?|news)\b|\b(won|win|wins|bagged|bags|bagging|secured?|receiv(ed|es|ing)|"
    r"awarded|clinch(ed|es)|landed)\b.{0,30}\b(orders?|contracts?)\b|\b(big|large|major|new|fresh|mega)\s+(orders?|contracts?)\b|"
    r"\bbagging\s*/\s*receiving\b|\b(orders?|contracts?)\s+(won|received|awarded|announced|wins)\b|\bwhich\s+companies\s+won\b|"
    r"\border\s+book\b.{0,25}\b(update\w*|position|size|growth|strong|backlog|announc\w+|latest|recent)\b|"
    r"\b(update\w*|latest|recent|strong)\s+order\s+book\b", re.I)
_EV_OWNERSHIP = re.compile(
    r"\bpledg(e|ed|es|ing)\b|\bencumbrance\b|\bsast\b|\bsubstantial\s+acquisition\b|\binsider\s+(trad\w+|buying|selling|transactions?|deals?)\b|"
    r"\b(promoters?|promoter\s+group|fii|fpi|dii)\s+(holding|shareholding|stake)\b.{0,40}\b(chang\w+|rais\w+|cut|hike|sold|sell\w*|bought|buy\w*|"
    r"increas\w+|decreas\w+|reduc\w+|disclos\w+|recent|latest|any|new|moves?)\b|"
    r"\b(chang\w+|rais\w+|cut|hike|sold|sell\w*|bought|buy\w*|increas\w+|decreas\w+|reduc\w+|disclos\w+|recent|latest|any|new)\b.{0,30}\b"
    r"(promoters?|promoter\s+group)\b.{0,12}\b(holding|shareholding|stake)\b|\b(promoters?)\s+(buying|selling|buy|sell|sold|bought|transactions?|dealings?)\b|"
    r"\bshareholding\s+(pattern\s+)?(changes?|updates?|disclosures?)\b|\bownership\s+(changes?|disclosures?|filings?|updates?)\b|"
    r"\bstake\s+(change|changes|disclosures?)\b", re.I)
_EV_CALLS = re.compile(
    r"\b(earnings|conference|con)\s*calls?\b|\bconcalls?\b|\bmanagement\s+(commentary|said|says|say|guidance|outlook|remarks|comments?|discussion|views?)\b|"
    r"\bwhat\s+did\s+(the\s+)?(\w+\s+)?management\b|\bguidance\b|\binvestor\s+(meets?|presentations?|days?)\b|\banalyst\s+meets?\b|"
    r"\btranscripts?\b|\bcall\s+(highlights|summary|takeaways)\b", re.I)
_EV_REGULATORY = re.compile(
    r"\bsebi\s+(circulars?|orders?|notices?|rules?|regulations?|norms?|directives?|updates?|actions?)\b|"
    r"\bregulatory\s+(announcements?|updates?|news|filings?|events?|actions?)\b|\blitigation\s+(news|updates?|filings?|cases?)\b|"
    r"\bmaster\s+circulars?\b", re.I)
_EV_EXCHANGE = re.compile(
    r"\bexchange\s+(notices?|queries|query|clarifications?|surveillance|alerts?)\b|\bprice\s+movement\s+(queries|query|clarifications?|notices?)\b|"
    r"\bclarification\s+(sought|on)\b|\bspurt\s+in\s+volume\b|\brumou?r\s+verification\b|\bnews\s+verification\b", re.I)
_EV_ANNOUNCEMENTS = re.compile(
    r"\bcapex\b|\bcapital\s+expenditure\b|\bqips?\b|\bfund[- ]?raising\b|\bfund\s+raise\b|\brights\s+issues?\b|\bcredit\s+rating\b|"
    r"\brating\s+(upgrades?|downgrades?|actions?)\b|\bmanagement\s+changes?\b|\b(ceo|cfo|md)\s+(appointments?|resignations?|changes?)\b|"
    r"\bresignations?\b", re.I)
_EV_GENERIC = re.compile(r"\b(corporate\s+)?(announcements?|filings?|disclosures?|corporate\s+actions?)\b", re.I)


def _event_period(msg: str, with_symbol: bool) -> str:
    low = msg.lower()
    if re.search(r"\b(today|tonight)\b", low):
        return "today"
    if re.search(r"\b(this\s+month|last\s+30\s+days|past\s+month|month)\b", low):
        return "month"
    if re.search(r"\b(this\s+week|last\s+7\s+days|past\s+week|recent|latest)\b", low):
        return "week"
    return "month" if with_symbol else "week"


def _event_category(msg: str, with_symbol: bool) -> Optional[str]:
    """The Market Intelligence chip a question is about, or None. Definitions ("what is a bulk deal?") and fundamentals
    ("promoter holding of TCS", "dividend yield of ITC") are not event questions."""
    if not with_symbol and _CONCEPT.search(msg) and not _LISTING_CUE.search(msg):
        return None
    if _EV_DEALS.search(msg):
        return "deals"
    if _EV_MNA.search(msg) and not _EV_MNA_NOT.search(msg):
        return "mna"
    if _EV_ORDERS.search(msg):
        return "orders"
    if _EV_OWNERSHIP.search(msg):
        return "ownership"
    if _EV_REGULATORY.search(msg):
        return "regulatory"
    if _EV_EXCHANGE.search(msg):
        return "exchange"
    if _EV_CALLS.search(msg):
        return "calls"
    if _EV_ANNOUNCEMENTS.search(msg):
        return "announcements"
    if _EV_GENERIC.search(msg) and (with_symbol or _LISTING_CUE.search(msg)):
        return "all"
    return None


def _event_intent(msg: str, sym: Optional[str]) -> Optional[Intent]:
    """results_calendar (a list of companies) or event_intelligence (a chip, optionally one stock). Results come first:
    "results" with a stock is that stock's results file; without one it is the calendar."""
    if sym is None:
        cal = _results_calendar(msg)
        if cal is not None:
            return cal
        cat = _event_category(msg, False)
        if cat is not None:
            return Intent("event_intelligence", params={"category": cat, "period": _event_period(msg, False)})
        return None
    if (_RES.search(msg) and not _NOT_CALENDAR.search(msg)) or _BEAT_MISS.search(msg):
        return Intent("event_intelligence", symbol=sym, params={"category": "results", "period": "month"})
    cat = _event_category(msg, True)
    if cat is not None:
        return Intent("event_intelligence", symbol=sym, params={"category": cat, "period": _event_period(msg, True)})
    return None


def _strip_non_stock(text: str) -> str:
    text = _BANK_NIFTY.sub(" ", text)

    def keep(m: "re.Match[str]") -> str:
        tok = m.group(0)
        if tok.lower() in _ANY_CASE or (tok.isupper() and tok in NOT_A_STOCK):
            return " "
        return tok
    return _TOKEN.sub(keep, text)


def stock_in(text: str) -> Optional[str]:
    """The NSE symbol a message names, by the Copilot's own resolver, never a market or F&O word. A lower-case word is
    tried as a ticker only when the curated list knows it (no lower-case pass-through)."""
    from services.copilot_tools.symbol_resolver import resolve_symbol
    cleaned = _strip_non_stock(text or "")
    try:
        res = resolve_symbol(cleaned)
    except Exception:  # noqa: BLE001 — no symbol is an answer, never a failure
        return None
    sym = (res.symbol or "").upper() or None
    if sym and sym not in NOT_A_STOCK and sym.lower() not in _ANY_CASE:
        return sym
    for tok in _TOKEN.findall(cleaned):
        if tok.isupper() or len(tok) < 2:
            continue
        try:
            r = resolve_symbol(tok.upper())
        except Exception:  # noqa: BLE001
            continue
        if r.source == "ticker" and r.symbol and r.symbol.upper() not in NOT_A_STOCK:
            return r.symbol.upper()
    return None


def _is_trader(persona: Optional[str], surface: Optional[str]) -> bool:
    p = (persona or "").lower()
    return p == "trader" or (surface == "trading_desk" and p != "investor")


def _decision_words(message: str, trader: bool) -> bool:
    return bool(_TRADE_WORDS.search(message) or (trader and _BUY_WORDS.search(message)))


def wants_thread_symbol(message: str, persona: Optional[str] = None, surface: Optional[str] = None) -> bool:
    """True when the question is about one stock but names none ("Is this stock a buy now?", "Is my trade still
    valid?", "Should I book profits?"): the chat then reads the thread's last stock (cheap, only then)."""
    msg = message or ""
    if _NOT_OURS.search(msg) or _DAILY_REVIEW.search(msg):
        return False
    trader = _is_trader(persona, surface)
    about_a_stock = _decision_words(msg, trader) or _TRADE_VALIDITY.search(msg) or _EXIT_OPTIONS.search(msg)
    if not about_a_stock:
        return False
    return stock_in(msg) is None


def _index_of(message: str) -> str:
    return "BANKNIFTY" if re.search(r"\bbank\s*nifty\b|\bbanknifty\b|\bnifty\s*bank\b", message, re.I) else "NIFTY"


def resolve_intent(message: str, persona: Optional[str] = None, surface: Optional[str] = None,
                   last_symbol: Optional[str] = None) -> Optional[Intent]:
    """The Release-1 intent of a Copilot question, or None (the chat's usual path)."""
    msg = (message or "").strip()
    if msg and len(msg) <= 400 and _PORTFOLIO_HEDGE.search(msg) and not _HEDGE_NOT.search(msg) and stock_in(msg) is None:
        return Intent("portfolio_hedge", params=hedge_params(msg))
    if not msg or len(msg) > 400 or _NOT_OURS.search(msg):
        return None
    trader = _is_trader(persona, surface)
    if _DAILY_REVIEW.search(msg):
        # Before the stock read: "how did I do on the TCS trade today?" is the day's review (TCS is one of its rows).
        return Intent("daily_review", params={"period": "week" if _WEEK.search(msg) else "day"})
    sym = stock_in(msg)
    if _EXPECTED_MOVE.search(msg) and sym is None:
        return Intent("expected_move", symbol=_index_of(msg))
    if sym is not None:
        # A named stock: the most specific pattern wins (validity and exit questions can also carry trade words,
        # e.g. "should I hold or trail my stop in X", so these are checked before the plain entry/stop/target read).
        if _TRADE_VALIDITY.search(msg):
            return Intent("trade_validity", symbol=sym)
        if _EXIT_OPTIONS.search(msg):
            return Intent("exit_options", symbol=sym)
        if _POSITION_SIZE.search(msg):
            return Intent("position_size", symbol=sym)
        if _decision_words(msg, trader):
            return Intent("stock_decision", symbol=sym)
        return _event_intent(msg, sym)
    ev = _event_intent(msg, None)
    if ev is not None:
        return ev
    if _OPEN_TRADES.search(msg):
        return Intent("open_trades")
    if _POSITION_SIZE.search(msg):
        return Intent("position_size")
    if _FNO_SETUPS.search(msg):
        return Intent("fno_setups")
    if _SECTOR_ROTATION.search(msg):
        return Intent("sector_rotation")
    if _SMART_MONEY.search(msg):
        return Intent("smart_money")
    if _UNUSUAL_VOLUME.search(msg):
        return Intent("unusual_volume")
    if _BREAKOUTS.search(msg):
        return Intent("breakouts")
    if _TOP.search(msg) and not _TOP_NOT.search(msg):
        m = _TOP_N.search(msg)
        n = 5
        if m:
            raw = m.group(1).lower()
            n = _WORD_N.get(raw) or int(raw)
        return Intent("top_opportunities", params={"n": max(1, min(10, n))})
    if _MARKET_VIEW.search(msg):
        return Intent("market_view")
    if last_symbol:
        ls = last_symbol.upper()
        if ls not in NOT_A_STOCK and ls.lower() not in _ANY_CASE:
            if _TRADE_VALIDITY.search(msg):
                return Intent("trade_validity", symbol=ls, symbol_from_thread=True)
            if _EXIT_OPTIONS.search(msg):
                return Intent("exit_options", symbol=ls, symbol_from_thread=True)
            if _decision_words(msg, trader) and (_DEICTIC.search(msg) or _TRADE_WORDS.search(msg)):
                return Intent("stock_decision", symbol=ls, symbol_from_thread=True)
    return None


def last_symbol_from(messages: Iterable[Dict[str, Any]]) -> Optional[str]:
    """The newest stock in a thread (messages newest first): a saved card's stock (a visual stock decision, a trade
    plan or a stock card), else the newest user message that names one."""
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        w = m.get("widget") if isinstance(m.get("widget"), dict) else {}
        data = w.get("data") if isinstance(w.get("data"), dict) else {}
        sym = None
        if w.get("widget_type") == "visual_answer" and data.get("intent") in SYMBOL_INTENTS:
            sym = next((b.get("symbol") for b in data.get("blocks") or [] if isinstance(b, dict) and b.get("type") == "candles"),
                       None)
        elif w.get("widget_type") in ("trade_plan", "instrument_detail"):
            sym = data.get("symbol")
        if not sym and m.get("role") == "user" and isinstance(m.get("content"), str):
            sym = stock_in(m["content"])
        if isinstance(sym, str) and sym and sym.upper() not in NOT_A_STOCK:
            return sym.upper()
    return None
