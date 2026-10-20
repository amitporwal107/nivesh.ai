"""NSE symbol lookup: type-ahead search and "did you mean" over the symbol universe (read only; nothing is stored).

Used by GET /api/markets/symbol-lookup (routes/symbol_lookup.py) and by the Strategy Builder's plan route, so the two agree.

Source of the universe, read through the DaaS client and indexed in process for CACHE_TTL_S:
    DaaS /v1/symbols/universe   nidp.sector_master (NSE equity master: name, ISIN, sector) joined with the symbols that have
                                nidp.prices_eod_adjusted bars (last_price_date), the F&O flag (security_reference_daily) and
                                market cap (stock_features_daily). Fallback when that route is absent (an older DaaS):
                                /v1/symbols?limit=5000 (names and ISINs only; has_prices is then unknown, never guessed).
    scan snapshot               DaaS /v1/features/scan-snapshot symbols → `in_scanner` (null when it cannot be read).

All ranking rules live here, in one place (the constants below). A symbol is never invented: every result is a row of the
universe. A company with no price history is returned with has_prices False and ranks below those that have prices.
"""
from __future__ import annotations

import asyncio
import bisect
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

# ── rules (one place) ────────────────────────────────────────────────────────
CACHE_TTL_S = 300.0                   # the universe is rebuilt at most this often
MAX_QUERY_LEN = 40
QUERY_CHARS = re.compile(r"^[A-Za-z0-9 &.\-'()]+$")
ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
ISIN_PREFIX_MIN = 4                   # "INE0" and longer, starting IN, is read as a partial ISIN
DEFAULT_LIMIT, MAX_LIMIT = 8, 20
MAX_EDIT_SHORT, MAX_EDIT_LONG = 1, 2  # Damerau-Levenshtein on the symbol
SHORT_SYMBOL_LEN = 5                  # a text up to this long is allowed one edit only; under MIN_FUZZY_LEN none
MIN_FUZZY_LEN = 3
STRONG_SUGGESTION_MAX_EDIT = 1        # "exactly one strong suggestion" for the plan route: a variant or one edit
MAX_RECENT = 8
# Match classes, best first. The tier decides the order; inside a tier: has prices, bigger market cap, symbol.
TIERS = ("exact", "isin", "prefix", "variant", "name_prefix", "contains", "name", "edit_distance")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}
TIER_SCORE = {"exact": 100, "isin": 95, "prefix": 90, "variant": 85, "name_prefix": 80, "contains": 60, "name": 50, "edit_distance": 40}

_WORD = re.compile(r"[A-Z0-9]+")


class BadQuery(ValueError):
    """The text is not acceptable input (too long, or characters outside the allowed set)."""


def normalise(q: Any) -> str:
    """Trim, upper-case, collapse spaces. Raises BadQuery for a long text or one with characters a symbol or name never has."""
    if q is None:
        return ""
    s = " ".join(str(q).split())
    if len(s) > MAX_QUERY_LEN:
        raise BadQuery(f"The search text is longer than {MAX_QUERY_LEN} characters.")
    if s and not QUERY_CHARS.match(s):
        raise BadQuery("The search text may hold letters, digits, spaces and & . - ' ( ) only.")
    return s.upper()


def damerau(a: str, b: str, cap: int) -> int:
    """Optimal-string-alignment distance (insert, delete, replace, swap of neighbours); returns cap + 1 once it must exceed cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2: List[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            c = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                c = min(c, prev2[j - 2] + 1)
            cur[j] = c
            best = min(best, c)
        if best > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


def _words(text: str) -> List[Tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in _WORD.finditer(text.upper())]


class Universe:
    """The symbol rows with the in-memory maps the search uses (symbol and name-word prefix lists, ISIN map)."""

    def __init__(self, rows: List[Dict[str, Any]], source: str, as_of: Optional[str], scanner: Optional[set]):
        self.source, self.as_of = source, as_of
        self.entries: Dict[str, Dict[str, Any]] = {}
        have_prices = any(r.get("last_price_date") for r in rows)
        for r in rows:
            sym = str(r.get("symbol") or "").strip().upper()
            if not sym or sym in self.entries:
                continue
            last = str(r["last_price_date"])[:10] if r.get("last_price_date") else None
            mc = r.get("market_cap_cr")
            try:
                mc = float(mc) if mc is not None else None
            except (TypeError, ValueError):
                mc = None
            self.entries[sym] = {
                "symbol": sym, "name": (r.get("company_name") or None), "isin": (str(r["isin"]).upper() if r.get("isin") else None),
                "series": r.get("series"), "sector": r.get("sector"), "industry": r.get("industry"),
                "fno_eligible": r["fno_eligible"] if isinstance(r.get("fno_eligible"), bool) else None,
                "in_scanner": (sym in scanner) if scanner is not None else None,
                "last_price_date": last, "has_prices": (last is not None) if have_prices else None, "_mc": mc or 0.0,
                "_words": _words(r.get("company_name") or ""),
            }
            self.entries[sym]["_joined"] = "".join(w for w, _, _ in self.entries[sym]["_words"])
        self.symbols = sorted(self.entries)
        self.isins = {e["isin"]: s for s, e in self.entries.items() if e["isin"]}
        self.isin_list = sorted(self.isins)
        pairs = sorted((w, s) for s, e in self.entries.items() for w, _, _ in e["_words"])
        self.word_keys = [p[0] for p in pairs]
        self.word_syms = [p[1] for p in pairs]
        self.distinct_words = sorted(set(self.word_keys))

    def __len__(self) -> int:
        return len(self.entries)

    def with_prefix(self, keys: List[str], syms: Optional[List[str]], prefix: str) -> List[str]:
        lo = bisect.bisect_left(keys, prefix)
        hi = bisect.bisect_left(keys, prefix + "￿")
        return keys[lo:hi] if syms is None else syms[lo:hi]


def _range(text: str, needle: str) -> List[List[int]]:
    i = text.upper().find(needle)
    return [[i, i + len(needle)]] if i >= 0 and needle else []


def _name_ranges(e: Dict[str, Any], tokens: List[str]) -> List[List[int]]:
    out: List[List[int]] = []
    for t in tokens:
        for w, s, _end in e["_words"]:
            if w.startswith(t):
                out.append([s, s + len(t)])
                break
    return out


def _hit(e: Dict[str, Any], tier: str, matched_on: str, hl_sym: List[List[int]], hl_name: List[List[int]], distance: Optional[int] = None) -> Dict[str, Any]:
    return {"e": e, "tier": tier, "on": matched_on, "hl": {"symbol": hl_sym, "name": hl_name}, "dist": distance}


def search(u: Universe, q: str, limit: int = DEFAULT_LIMIT, fno_only: bool = False) -> List[Dict[str, Any]]:
    """Ranked results for the normalised text `q` (non-empty). Each is `public(hit)`-ready; the best tier per symbol wins."""
    best: Dict[str, Dict[str, Any]] = {}

    def add(h: Dict[str, Any]) -> None:
        s = h["e"]["symbol"]
        if fno_only and h["e"]["fno_eligible"] is not True:
            return
        cur = best.get(s)
        if cur is None or (TIER_RANK[h["tier"]], h["dist"] or 0) < (TIER_RANK[cur["tier"]], cur["dist"] or 0):
            best[s] = h

    compact = q.replace(" ", "")
    tokens = [t for t in _WORD.findall(q)]
    # exact symbol
    if q in u.entries or compact in u.entries:
        e = u.entries[q if q in u.entries else compact]
        add(_hit(e, "exact", "symbol", [[0, len(e["symbol"])]], []))
    # ISIN: exact, or a partial one
    if ISIN_RE.match(compact):
        s = u.isins.get(compact)
        if s:
            add(_hit(u.entries[s], "isin", "isin", [], []))
    elif compact.startswith("IN") and len(compact) >= ISIN_PREFIX_MIN:
        for k in u.with_prefix(u.isin_list, None, compact):
            add(_hit(u.entries[u.isins[k]], "isin", "isin", [], []))
    # symbol prefix (the text as typed, or without its spaces: "pc jew" → PCJEW)
    if len(compact) >= 1:
        for s in u.with_prefix(u.symbols, None, compact):
            add(_hit(u.entries[s], "prefix", "symbol", [[0, len(compact)]], []))
    # plural / singular variant: PCJEWELLERS ↔ PCJEWELLER
    if len(compact) >= MIN_FUZZY_LEN + 1:
        for alt in (compact[:-1] if compact.endswith("S") else None, compact + "S"):
            if alt and alt in u.entries:
                add(_hit(u.entries[alt], "variant", "symbol", [[0, len(alt)]], [], 1))
    # company name: every text word starts a distinct word of the name
    if tokens:
        first = u.with_prefix(u.word_keys, u.word_syms, tokens[0])
        for s in set(first):
            e = u.entries[s]
            used: set = set()
            ok = True
            for t in tokens:
                hit = next((i for i, (w, _, _) in enumerate(e["_words"]) if i not in used and w.startswith(t)), None)
                if hit is None:
                    ok = False
                    break
                used.add(hit)
            if ok:
                add(_hit(e, "name_prefix", "name", [], _name_ranges(e, tokens)))
    # contains: in the symbol, then in the name
    if len(compact) >= 2:
        for s in u.symbols:
            if compact in s and not s.startswith(compact):
                add(_hit(u.entries[s], "contains", "symbol", _range(s, compact), []))
        if len(best) < limit * 4:
            for s, e in u.entries.items():
                if e["name"] and s not in best and compact in e["_joined"]:
                    add(_hit(e, "name", "name", [], _range(e["name"], q) or _range(e["name"], compact)))
    # typo tolerance: only when the text is not already well served
    if len(best) < limit and len(compact) >= MIN_FUZZY_LEN:
        cap = MAX_EDIT_SHORT if len(compact) <= SHORT_SYMBOL_LEN else MAX_EDIT_LONG
        for s in u.symbols:
            if s in best or abs(len(s) - len(compact)) > cap:
                continue
            d = damerau(compact, s, cap)
            if d <= cap:
                add(_hit(u.entries[s], "edit_distance", "symbol", [], [], d))
        if len(tokens) == 1 and len(tokens[0]) >= MIN_FUZZY_LEN + 1:
            t = tokens[0]
            wcap = MAX_EDIT_SHORT if len(t) <= SHORT_SYMBOL_LEN else MAX_EDIT_LONG
            near = [w for w in u.distinct_words if abs(len(w) - len(t)) <= wcap and damerau(t, w, wcap) <= wcap]
            if near:
                near_set = set(near)
                for s, e in u.entries.items():
                    if s in best:
                        continue
                    for w, st, en in e["_words"]:
                        if w in near_set:
                            add(_hit(e, "edit_distance", "name", [], [[st, en]], damerau(t, w, wcap)))
                            break
    hits = list(best.values())
    hits.sort(key=lambda h: (TIER_RANK[h["tier"]], h["dist"] or 0, h["e"]["has_prices"] is False, -h["e"]["_mc"], h["e"]["symbol"]))
    return hits[:limit]


def public(h: Dict[str, Any]) -> Dict[str, Any]:
    e = h["e"]
    return {"symbol": e["symbol"], "name": e["name"], "isin": e["isin"], "series": e["series"], "sector": e["sector"], "industry": e["industry"],
            "fno_eligible": e["fno_eligible"], "in_scanner": e["in_scanner"], "last_price_date": e["last_price_date"], "has_prices": e["has_prices"],
            "match": h["tier"], "matched_on": h["on"], "highlight": h["hl"], "score": TIER_SCORE.get(h["tier"], 0) - ((h["dist"] or 0) * 5 if h["tier"] == "edit_distance" else 0)}


def entry_view(e: Dict[str, Any], match: str, matched_on: str = "symbol") -> Dict[str, Any]:
    return public({"e": e, "tier": match, "on": matched_on, "hl": {"symbol": [], "name": []}, "dist": None})


def strong_suggestion(results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The one result worth offering first: a single plural/singular variant or one-edit symbol, with nothing else as close."""
    close = [r for r in results if r["match"] in ("variant", "prefix", "exact") or (r["match"] == "edit_distance" and r["score"] >= TIER_SCORE["edit_distance"] - 5 * STRONG_SUGGESTION_MAX_EDIT)]
    return close[0] if len(close) == 1 else None


# ── the cached universe ──────────────────────────────────────────────────────

_cache: Dict[str, Any] = {"u": None, "at": 0.0}
_lock: Optional[asyncio.Lock] = None


async def _load() -> Universe:
    rows: List[Dict[str, Any]] = []
    source = "DaaS /v1/symbols/universe (nidp.sector_master + prices_eod_adjusted + security_reference_daily + stock_features_daily)"
    status, body = await daas_client.get_raw("/symbols/universe", None, timeout=30.0)
    if status == 200 and isinstance(body, dict) and isinstance(body.get("data"), list) and body["data"]:
        rows = body["data"]
    else:
        status2, body2 = await daas_client.get_raw("/symbols", {"limit": 5000}, timeout=30.0)
        if status2 != 200 or not isinstance(body2, dict) or not isinstance(body2.get("data"), list) or not body2["data"]:
            raise RuntimeError(f"the symbol universe could not be read (DaaS /v1/symbols/universe HTTP {status}, /v1/symbols HTTP {status2})")
        rows = body2["data"]
        source = "DaaS /v1/symbols (nidp.sector_master; the universe route is not deployed, so price days and F&O flags are unknown)"
    scanner: Optional[set] = None
    try:
        from routes import positional
        snap = await positional._scan_snapshot()
        scanner = {str(r.get("symbol") or "").upper() for r in snap["rows"]}
    except Exception as e:  # noqa: BLE001 — the scanner flag is optional: unknown, never "not in scan"
        logger.warning("symbol lookup: scan snapshot unavailable: %s", e)
    dates = [str(r["last_price_date"])[:10] for r in rows if r.get("last_price_date")]
    return Universe(rows, source, max(dates) if dates else None, scanner)


async def get_universe(force: bool = False) -> Universe:
    """The cached universe; a failed refresh keeps serving the last good one. Raises RuntimeError when there never was one."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    now = time.monotonic()
    if not force and _cache["u"] is not None and now - _cache["at"] < CACHE_TTL_S:
        return _cache["u"]
    async with _lock:
        if not force and _cache["u"] is not None and time.monotonic() - _cache["at"] < CACHE_TTL_S:
            return _cache["u"]
        try:
            _cache.update(u=await _load(), at=time.monotonic())
        except Exception as e:  # noqa: BLE001
            if _cache["u"] is None:
                raise RuntimeError(str(e))
            logger.warning("symbol lookup: refresh failed, serving the cached universe: %s", e)
            _cache["at"] = time.monotonic() - CACHE_TTL_S + 30.0     # retry in 30 s
        return _cache["u"]


def reset_cache() -> None:
    _cache.update(u=None, at=0.0)


async def lookup(q: Any, limit: int = DEFAULT_LIMIT, fno_only: bool = False) -> Dict[str, Any]:
    """Search body for non-empty text. Raises BadQuery, RuntimeError (universe unreadable)."""
    text = normalise(q)
    limit = max(1, min(int(limit), MAX_LIMIT))
    u = await get_universe()
    res = [public(h) for h in search(u, text, limit, fno_only)] if text else []
    exact = next((r for r in res if r["match"] == "exact"), None)
    reason = None
    if text and not res:
        reason = f"No NSE stock matches {text}" + (" among F&O stocks." if fno_only else ".")
    return {"query": text, "exact": exact, "results": res, "count": len(res), "reason": reason, "source": u.source, "as_of": u.as_of, "universe_size": len(u)}
