"""Stock and index type-ahead for the Copilot (GET /api/chat/instrument-search; owner, 29 Oct: "allow autocompletetion of
the stock based on ticker full name partial nae ...or provide suggestion in the copilot chat").

Source: the data platform's symbol master search (DaaS /v1/symbols/search: every NSE symbol with its company name, sector
and industry). On top of it, three things that search does not do, measured on staging 29 Oct:
  * the Copilot resolver's own short forms ("hul" → HINDUNILVR, "l&t" → LT, "sbi" → SBIN; services/copilot_tools/
    symbol_resolver._ALIASES), so autocomplete and the answer agree on what a short form means;
  * the NSE F&O index underlyings (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50), as `kind: "index"`;
  * words in any order ("motor tvs") and a ranking: exact ticker, ticker prefix, name words matched as prefixes (in order
    before any order), then substrings. The platform's own order breaks ties.

`tail_search` is for completing a stock inside a sentence: given the text BEFORE the cursor it tries the last 3, 2 and 1
words (a fragment never starts with an ordinary word such as "for" or "trade"), keeps the fragment whose best match ranks
highest (the longer one on a tie) and says where it starts, so the client replaces exactly that fragment.

`search_stocks` returns None when the symbol master cannot be read; the route then falls back to what it did before.
Read-only; no user data.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

INDEXES: List[Dict[str, Any]] = [
    {"symbol": "NIFTY", "name": "Nifty 50", "aliases": ("nifty", "nifty 50", "nifty50")},
    {"symbol": "BANKNIFTY", "name": "Nifty Bank", "aliases": ("bank nifty", "banknifty", "nifty bank")},
    {"symbol": "FINNIFTY", "name": "Nifty Financial Services", "aliases": ("fin nifty", "finnifty", "nifty financial services")},
    {"symbol": "MIDCPNIFTY", "name": "Nifty Midcap Select", "aliases": ("midcap nifty", "midcpnifty", "nifty midcap select")},
    {"symbol": "NIFTYNXT50", "name": "Nifty Next 50", "aliases": ("nifty next 50", "niftynxt50", "next 50")},
]
INDEX_SECTOR = "Index (F&O underlying)"

_WORD = re.compile(r"[a-z0-9&]+")
_TAIL_WORD = re.compile(r"[A-Za-z0-9&][A-Za-z0-9&.\-]*")
CACHE_TTL_S = 600.0
CACHE_MAX = 512
_cache: Dict[str, Tuple[float, Optional[List[Dict[str, Any]]]]] = {}

# Ordinary words a stock fragment never starts with (and a one-word fragment never is): question words, trading words,
# fillers. Includes the resolver's own stopword lists.
_ORDINARY = {
    "a", "an", "the", "for", "on", "in", "of", "to", "is", "it", "me", "my", "i", "and", "or", "with", "about", "at", "by",
    "plan", "trade", "trades", "trading", "buy", "sell", "short", "long", "entry", "exit", "stop", "loss", "target",
    "targets", "breakout", "setup", "how", "what", "why", "which", "should", "can", "could", "would", "will", "price",
    "stock", "stocks", "share", "shares", "market", "markets", "compare", "vs", "versus", "between", "tell", "show",
    "analyse", "analyze", "analysis", "option", "options", "call", "calls", "put", "puts", "spread", "future", "futures",
    "week", "weeks", "today", "tomorrow", "next", "this", "that", "these", "those", "good", "bad", "now", "if", "when",
    "then", "be", "do", "does", "did", "are", "was", "were", "has", "have", "had", "than", "more", "less", "up", "down",
    "move", "view", "positional", "intraday", "swing", "capital", "risk", "rs", "inr", "lakh", "crore", "please", "give",
    "get", "make", "create", "build", "find", "look", "looks", "looking", "doing", "outlook", "news", "results", "all",
    "any", "some", "your", "our", "their", "its", "from", "into", "over", "under", "after", "before", "per", "via",
}
try:
    from services.copilot_tools.symbol_resolver import _ALIASES as _RESOLVER_ALIASES
    from services.copilot_tools.symbol_resolver import _NAME_STOPWORDS, _PASSTHROUGH_STOPWORDS
    _ORDINARY |= set(_NAME_STOPWORDS) | {w.lower() for w in _PASSTHROUGH_STOPWORDS}
except Exception:  # noqa: BLE001 — the type-ahead works without them (no short forms)
    _RESOLVER_ALIASES = {}


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9&]", "", (text or "").lower())


def _prefix_in_order(qt: List[str], nt: List[str]) -> bool:
    i = 0
    for w in nt:
        if i < len(qt) and w.startswith(qt[i]):
            i += 1
    return i == len(qt)


def score(query: str, symbol: str, name: str, aliases: Tuple[str, ...] = ()) -> int:
    """How well `query` names this instrument (0 = not at all). Exact ticker 100, a short form 95, ticker prefix 75–85,
    name words as prefixes in order 70–75 (any order 60), name substring 45, ticker substring 35."""
    q, qc, sym = _norm(query), _compact(query), (symbol or "").lower()
    if not qc:
        return 0
    if qc == _compact(sym):
        return 100
    if q in aliases:
        return 95
    if len(qc) >= 2 and _compact(sym).startswith(qc):
        return 85 - min(10, len(sym) - len(qc))
    qt, nt = q.split(), _norm(name).split()
    if qt and nt:
        if _prefix_in_order(qt, nt):
            return 70 + (5 if nt[0].startswith(qt[0]) else 0)
        if all(any(w.startswith(t) for w in nt) for t in qt):
            return 60
    if q and q in _norm(name):
        return 45
    if qc in _compact(sym):
        return 35
    return 0


def _alias_target(query: str) -> Optional[str]:
    return _RESOLVER_ALIASES.get(_norm(query)) or _RESOLVER_ALIASES.get((query or "").strip().lower())


async def _master(term: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """The symbol master's rows for `term` (cached briefly), or None when it cannot be read."""
    key = f"{term.lower()}|{limit}"
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    from services.copilot_tools import daas_client
    data = await daas_client.search_symbols(term, limit=limit)
    rows = None if data is None else [r for r in (data.get("data") or []) if isinstance(r, dict) and r.get("symbol")]
    if rows is not None:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (now, rows)
    return rows


def _row(symbol: str, name: str, sector: Optional[str], kind: str = "stock") -> Dict[str, Any]:
    return {"symbol": symbol, "name": name or symbol, "sector": sector, "kind": kind}


async def search_stocks(term: str, limit: int = 6) -> Optional[List[Dict[str, Any]]]:
    """Ranked stocks and F&O indices for `term`; None when the symbol master cannot be read (the caller falls back)."""
    term = (term or "").strip()
    if len(_compact(term)) < 2:
        return []
    found: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}       # symbol -> (score, order, row)

    def add(sc: int, order: int, row: Dict[str, Any]) -> None:
        prev = found.get(row["symbol"])
        if prev is None or sc > prev[0]:
            found[row["symbol"]] = (sc, order, row)

    for i, ix in enumerate(INDEXES):
        sc = score(term, ix["symbol"], ix["name"], ix["aliases"])
        if sc >= 60:
            add(sc, i, _row(ix["symbol"], ix["name"], INDEX_SECTOR, "index"))

    rows = await _master(term, max(limit * 3, 15))
    if rows is None:
        return None
    for i, r in enumerate(rows):
        name = r.get("company_name") or r.get("name") or ""
        add(max(score(term, r["symbol"], name), 1), 100 + i, _row(r["symbol"], name, r.get("sector") or r.get("industry")))

    target = _alias_target(term)
    if target:
        exact = next((r for r in (await _master(target, 5) or []) if r.get("symbol") == target), None)
        add(95, 0, _row(target, (exact or {}).get("company_name") or target, (exact or {}).get("sector") or (exact or {}).get("industry")))

    qt = _norm(term).split()
    if len(qt) > 1 and not any(s >= 60 for s, _, _ in found.values()):
        # Words in another order than the company name ("motor tvs"): search by the longest word, keep names with all.
        longest = max(qt, key=len)
        for i, r in enumerate(await _master(longest, 30) or []):
            name = r.get("company_name") or r.get("name") or ""
            sc = score(term, r["symbol"], name)
            if sc >= 60:
                add(sc, 200 + i, _row(r["symbol"], name, r.get("sector") or r.get("industry")))

    ranked = sorted(found.values(), key=lambda t: (-t[0], t[1]))
    return [row for _, _, row in ranked[:limit]]


def tail_fragments(text: str) -> List[Tuple[str, int]]:
    """The candidate stock fragments at the END of `text` (the text before the cursor): the last 3, 2 and 1 words, each
    with where it starts. None when the text ends in a space or punctuation (the word is finished)."""
    if not text or not text[-1].isalnum() and text[-1] not in "&.-":
        return []
    words = list(_TAIL_WORD.finditer(text))
    if not words or words[-1].end() != len(text):
        return []
    out: List[Tuple[str, int]] = []
    for n in (3, 2, 1):
        if len(words) < n:
            continue
        span = words[-n:]
        first = span[0].group(0).lower()
        if first in _ORDINARY:
            continue
        if n == 1 and len(_compact(first)) < 2:
            continue
        out.append((text[span[0].start():], span[0].start()))
    return out


GOOD_MATCH = 60


def _top(frag: str, rows: List[Dict[str, Any]]) -> int:
    return max(score(frag, r["symbol"], r["name"], next((ix["aliases"] for ix in INDEXES if ix["symbol"] == r["symbol"]), ()))
               or (95 if _alias_target(frag) == r["symbol"] else 0) for r in rows)


async def tail_search(text: str, limit: int = 5) -> Dict[str, Any]:
    """Stock completions for the fragment being typed at the end of `text`: {stocks, fragment, fragment_start}.
    The LONGEST fragment with a good match (ticker, short form or name words, 60+) wins: "tvs mo" is TVS Motor, not
    the tickers that start with "mo". Only when no fragment matches well is the last word's best guess offered."""
    fallback: Optional[Tuple[str, int, List[Dict[str, Any]]]] = None
    for frag, start in tail_fragments(text or ""):                  # longest first
        rows = await search_stocks(frag, limit)
        if not rows:
            continue
        if _top(frag, rows) >= GOOD_MATCH:
            return {"stocks": rows, "fragment": frag, "fragment_start": start}
        if len(frag.split()) == 1 and fallback is None:
            fallback = (frag, start, rows)
    if fallback is None:
        return {"stocks": [], "fragment": None, "fragment_start": None}
    return {"stocks": fallback[2], "fragment": fallback[0], "fragment_start": fallback[1]}
