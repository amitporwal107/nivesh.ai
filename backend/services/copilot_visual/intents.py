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
    open_trades        "What are my open trades doing?", "my open positions" — the paper book, not a broker's
    fno_setups         "Which F&O setups are attractive?" — index and stock F&O, ranked by fit to today's regime
    trade_validity     "Is my trade in X still valid?", "has my thesis on X weakened?" — a named or thread stock
    exit_options       "Should I book profits or hold X?", "should I trail my stop?" — a named or thread stock
    position_size      "How much should I risk?", "what position size…" — the account's budget; a named stock adds its own

Release 3:
    daily_review       "What did I learn from today's trades?", "How did I do this week?", "my mistakes today" — the
                       paper book's closed trades and risk checks for the day (or the ISO week), `params.period`

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
           "expected_move", "open_trades", "fno_setups", "trade_validity", "exit_options", "position_size", "daily_review", "portfolio_hedge")
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
})
# The same words in any case (index and F&O words are never company names).
_ANY_CASE = frozenset({"f&o", "fno", "pcr", "p&l", "pnl", "gift", "iv", "oi", "atm", "vix", "nifty", "nifty50", "banknifty",
                       "finnifty", "midcpnifty", "sensex", "bankex"})
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
    r"\bwhere\s+is\s+(the\s+)?money\b|\bmoney\s+(flow|flows|flowing|moving)\b|\bsector\s+rotation\b|"
    r"\b(long|short)\s+build[- ]?ups?\b|\bshort\s+covering\b|\blong\s+unwinding\b|\bbuild[- ]?ups?\b", re.I)
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
    r"\bstatus\s+of\s+my\s+(trades?|positions?)\b|\bpaper\s+trades?\s+(status|summary)\b", re.I)
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
        return Intent("stock_decision", symbol=sym) if _decision_words(msg, trader) else None
    if _OPEN_TRADES.search(msg):
        return Intent("open_trades")
    if _POSITION_SIZE.search(msg):
        return Intent("position_size")
    if _FNO_SETUPS.search(msg):
        return Intent("fno_setups")
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
