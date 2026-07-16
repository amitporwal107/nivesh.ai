"""Resolve a free-text stock mention to a canonical NSE symbol.

The Copilot stock node used to extract the ticker with a case-sensitive regex
(`[A-Z]{2,10}`), so a query like "How is hdfc looking" produced no symbol, fell
back to the NIFTY50 index, and every stock tool 404'd — the user saw "I couldn't
retrieve the data". This module turns a user message (or a single token) into a
canonical symbol so lowercase mentions and common company names resolve.

Resolution order (first hit wins):
  1. An explicit uppercase ticker token that exactly matches a known symbol.
  2. A name phrase (1–3 leading tokens of a company name) that maps to a UNIQUE
     instrument. Ambiguous phrases ("tata", "bank", "hdfc") are dropped from the
     index during build, so they never resolve here.
  3. A curated alias for a dominant shorthand ("hdfc" → HDFCBANK, "sbi" → SBIN).
  4. Pass-through: any uppercase ticker-shaped token, even if it isn't in the
     curated universe — the curated list is ~115 names, so real tickers like
     PERSISTENT must still reach DaaS rather than be rejected.

Returns `Resolution(symbol=None, ...)` when nothing plausibly names an instrument
("how is my day going"); the caller turns that into a clarification prompt.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

try:  # the curated universe lives at backend/instruments_data.py
    from instruments_data import INDIAN_INSTRUMENTS
except Exception:  # noqa: BLE001 — never let a bad import break the chat
    INDIAN_INSTRUMENTS = []


@dataclass
class Resolution:
    symbol: Optional[str] = None
    display_name: Optional[str] = None
    # how we resolved: "ticker" | "name" | "alias" | "passthrough" | None
    source: Optional[str] = None
    # other unique tickers the same phrase could have meant (for clarification UX)
    candidates: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.symbol)


# Dominant shorthands users type that are ambiguous (and thus dropped from the
# name index) but have one overwhelmingly-common meaning in Indian markets.
_ALIASES: Dict[str, str] = {
    "hdfc": "HDFCBANK",
    "sbi": "SBIN",
    "icici": "ICICIBANK",
    "kotak": "KOTAKBANK",
    "axis": "AXISBANK",
    "airtel": "BHARTIARTL",
    "hul": "HINDUNILVR",
    "lnt": "LT",
    "l&t": "LT",
    "l and t": "LT",
    "m&m": "M&M",
    "dmart": "DMART",
    "d-mart": "DMART",
    "bajaj finance": "BAJFINANCE",
    "bajaj finserv": "BAJAJFINSV",
    # Renamed / rebranded entities — the old name still dominates user queries.
    "zomato": "ETERNAL",   # Zomato Ltd renamed to Eternal Ltd (ticker ETERNAL)
}

# Renamed/merged TICKERS — when the user types the OLD ticker ($ZOMATO), map it
# to the current symbol. Applied on the ticker + pass-through paths (the name
# alias above only covers the lowercase name form, e.g. "zomato").
_TICKER_RENAMES: Dict[str, str] = {
    "ZOMATO": "ETERNAL",   # Zomato Ltd → Eternal Ltd
}

# Uppercase tokens that look like tickers but are common English words — guard
# the pass-through step so an all-caps sentence ("HOW IS X") doesn't grab "HOW".
_PASSTHROUGH_STOPWORDS: Set[str] = {
    "HOW", "WHAT", "WHY", "WHEN", "WHO", "THE", "AND", "FOR", "ARE", "WAS",
    "BUY", "SELL", "HOLD", "STOCK", "SHARE", "PRICE", "TARGET", "LOOKING",
    "DOING", "TODAY", "ABOUT", "TELL", "GOOD", "GREAT", "OVER", "INTO",
    # Research-domain acronyms that appear in thematic/research questions and are
    # NOT NSE tickers — without this a question like "which companies talk about
    # AI" or "US FDA inspections" wrongly resolves "AI"/"US"/"FDA" to a ticker and
    # collapses a cross-company question to a single (wrong) company.
    "AI", "ML", "US", "USA", "UK", "EU", "FDA", "USFDA", "DGTR", "GST", "RBI",
    "SEBI", "GDP", "CEO", "CFO", "COO", "ESG", "YOY", "QOQ", "EBITDA", "USD",
    "INR", "AUM", "SIP", "NAV", "ETF", "FII", "DII", "IPO", "QIP", "NCD",
    "EPS", "ROE", "ROCE", "NPA", "CAPEX", "OPEX", "IBC", "NCLT", "LODR",
}

_WORD_RE = re.compile(r"[a-z0-9&]+")
_TICKER_RE = re.compile(r"\b[A-Z][A-Z0-9&]{1,9}\b")


def _norm_tokens(text: str) -> List[str]:
    """Lowercase, keep alphanumerics + '&', tokens of length ≥ 1."""
    return _WORD_RE.findall(text.lower())


def _build_index():
    tickers: Dict[str, str] = {}             # UPPER ticker -> ticker
    phrase_tmp: Dict[str, Set[str]] = defaultdict(set)  # phrase -> {tickers}
    for inst in INDIAN_INSTRUMENTS:
        if inst.get("type") != "equity":
            continue
        ticker = (inst.get("ticker") or "").strip()
        if not ticker:
            continue
        tickers[ticker.upper()] = ticker
        toks = _norm_tokens(inst.get("name") or "")
        # 1-, 2-, 3-token leading phrases; require single tokens to be ≥ 3 chars
        # so noise like "of"/"&" never becomes a key.
        for n in (1, 2, 3):
            if len(toks) < n:
                continue
            window = toks[:n] if n > 1 else [toks[0]]
            # also index every contiguous n-gram, not just the leading one,
            # so "tata motors" resolves even though name starts with "tata".
            grams = [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]
            for g in grams:
                if n == 1 and len(g) < 3:
                    continue
                phrase_tmp[g].add(ticker)
    # keep only phrases that map to exactly one instrument
    phrases: Dict[str, str] = {p: next(iter(s)) for p, s in phrase_tmp.items() if len(s) == 1}
    ambiguous: Dict[str, List[str]] = {p: sorted(s) for p, s in phrase_tmp.items() if len(s) > 1}
    return tickers, phrases, ambiguous


_TICKERS, _PHRASES, _AMBIGUOUS = _build_index()


def resolve_symbol(text: str) -> Resolution:
    """Resolve a user message (or single token) to a canonical NSE symbol."""
    if not text or not text.strip():
        return Resolution()

    # 1. explicit uppercase ticker exactly matching a known symbol
    upper_tokens = _TICKER_RE.findall(text)
    for tok in upper_tokens:
        if tok in _TICKERS:
            sym = _TICKER_RENAMES.get(_TICKERS[tok], _TICKERS[tok])
            return Resolution(symbol=sym, display_name=tok, source="ticker")

    toks = _norm_tokens(text)

    # 2. multi-word name phrase — "hdfc life"/"tata motors" must beat a 1-token
    #    alias or single-token name (e.g. "sbi life" → SBILIFE, not SBIN).
    for n in (3, 2):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i:i + n])
            if gram in _PHRASES:
                return Resolution(symbol=_PHRASES[gram], display_name=gram, source="name")

    # 3. curated alias for a dominant shorthand. Runs BEFORE single-token name
    #    matches because some shorthands collide with another instrument's name
    #    (e.g. "sbi" appears only in "SBI Life Insurance", but the user means SBIN).
    norm = " ".join(toks)
    for alias, sym in _ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", norm):
            return Resolution(
                symbol=sym, display_name=alias, source="alias",
                candidates=_AMBIGUOUS.get(alias, []),
            )

    # 4. single-token name match (unique distinctive word, e.g. "reliance")
    for tok in toks:
        if tok in _PHRASES:
            return Resolution(symbol=_PHRASES[tok], display_name=tok, source="name")

    # 5. pass-through: an uppercase ticker-shaped token not in the curated list
    for tok in upper_tokens:
        if tok not in _PASSTHROUGH_STOPWORDS:
            return Resolution(symbol=_TICKER_RENAMES.get(tok, tok), display_name=tok, source="passthrough")

    return Resolution()
