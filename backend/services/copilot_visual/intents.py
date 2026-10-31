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

Not ours (None): the user's own trades and positions, booking profits / holding / exiting, F&O setups and strategies,
position sizing, "what should I avoid", the day's review (Releases 2 and 3).

A stock is found with the Copilot's own resolver (services/copilot_tools/symbol_resolver.py), but F&O, PCR, P&L, GIFT,
IV, OI, ATM, VIX and the index names are never a stock here: they are removed before resolving and refused after.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

INTENTS = ("market_view", "smart_money", "top_opportunities", "breakouts", "unusual_volume", "stock_decision",
           "expected_move")


@dataclass(frozen=True)
class Intent:
    name: str
    symbol: Optional[str] = None              # stock_decision: the stock; expected_move: NIFTY | BANKNIFTY
    params: Dict[str, Any] = field(default_factory=dict)
    symbol_from_thread: bool = False          # stock_decision: the stock came from the thread, not the message


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

# The user's own book and the Release 2/3 questions: never answered here.
_NOT_OURS = re.compile(
    r"\bmy\s+(open\s+|existing\s+|current\s+)?(trades?|positions?|portfolio|holdings?|p&l|pnl)\b|\bopen\s+trades?\b|"
    r"\bbook(ing)?\s+(the\s+)?(profits?|gains)\b|\bstill\s+valid\b|\bshould\s+i\s+(hold|exit|sell|book)\b|\b(or|and)\s+hold\b|"
    r"\btrail(ing)?\b|\baverag(e|ing)\s+(down|up)\b|"
    r"\b(f&o|fno|options?|futures)\s+(setups?|strateg(y|ies)|trades?|ideas?|opportunit\w+)\b|\bwhat\s+should\s+i\s+avoid\b|"
    r"\blearn\s+from\b|\bposition\s+siz\w*|\bhow\s+much\s+(should|can|do)\s+i\s+risk\b|\bmy\b", re.I)

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
    """True when the question is a stock decision that names no stock ("Is this stock a buy now?", "What is the entry,
    target and stop-loss?"): the chat then reads the thread's last stock (cheap, only then)."""
    msg = message or ""
    if _NOT_OURS.search(msg) or not _decision_words(msg, _is_trader(persona, surface)):
        return False
    return stock_in(msg) is None


def _index_of(message: str) -> str:
    return "BANKNIFTY" if re.search(r"\bbank\s*nifty\b|\bbanknifty\b|\bnifty\s*bank\b", message, re.I) else "NIFTY"


def resolve_intent(message: str, persona: Optional[str] = None, surface: Optional[str] = None,
                   last_symbol: Optional[str] = None) -> Optional[Intent]:
    """The Release-1 intent of a Copilot question, or None (the chat's usual path)."""
    msg = (message or "").strip()
    if not msg or len(msg) > 400 or _NOT_OURS.search(msg):
        return None
    trader = _is_trader(persona, surface)
    sym = stock_in(msg)
    if _EXPECTED_MOVE.search(msg) and sym is None:
        return Intent("expected_move", symbol=_index_of(msg))
    if sym is not None:
        return Intent("stock_decision", symbol=sym) if _decision_words(msg, trader) else None
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
    if last_symbol and _decision_words(msg, trader) and (_DEICTIC.search(msg) or _TRADE_WORDS.search(msg)):
        ls = last_symbol.upper()
        if ls not in NOT_A_STOCK and ls.lower() not in _ANY_CASE:
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
        if w.get("widget_type") == "visual_answer" and data.get("intent") == "stock_decision":
            sym = next((b.get("symbol") for b in data.get("blocks") or [] if isinstance(b, dict) and b.get("type") == "candles"),
                       None)
        elif w.get("widget_type") in ("trade_plan", "instrument_detail"):
            sym = data.get("symbol")
        if not sym and m.get("role") == "user" and isinstance(m.get("content"), str):
            sym = stock_in(m["content"])
        if isinstance(sym, str) and sym and sym.upper() not in NOT_A_STOCK:
            return sym.upper()
    return None
