"""Import of a public Chartink dashboard: URL check, page fetch, widget parsing and classification.

A public dashboard page carries its widgets as HTML-escaped JSON in a `:widgets="[...]"` attribute. Each widget has `id, name, description, query`;
`query` is Chartink's SQL-like text `select ... WHERE <clause> GROUP BY symbol ORDER BY 1 desc`, and the part after the top-level WHERE up to
GROUP BY is exactly the `scan_clause` the screener endpoint takes (services/positional_engine/chartink_api.py runs it).

Stock scan versus market statistics (STOCK_SCAN_RULE): a stock scan lists stocks, so it groups by `symbol`, selects a `Price` column, and has a real
condition; a widget that groups by anything else (`marketcapname` ...), or selects no price, or whose clause is a bare `1 = 1` (a universe listing, not a
filter) is a market statistic and is never run as a scan.

Nothing here logs a clause. The fetch targets chartink.com over https only.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DASHBOARD_URL_RE = re.compile(r"^https://chartink\.com/dashboard/(\d{1,12})/?$")
HOST = "chartink.com"
MAX_PAGE_BYTES = 4_000_000          # the real page is about 0.45 MB; a page beyond this is refused, not truncated
FETCH_TIMEOUT_S = 20
MAX_REDIRECTS = 3
MAX_WIDGETS = 100                   # widgets read from a page; a dashboard has a few dozen at most
MAX_NAME_LEN, MAX_DESC_LEN, MAX_CLAUSE_LEN = 120, 400, 20_000
INTRADAY_RE = re.compile(r"\b\d+\s*(?:minute|min|hour)s?\b", re.I)
STOCK_SCAN_RULE = ("A stock scan groups by symbol, selects a Price column and has a real condition (not a bare 1 = 1 universe listing); anything else "
                   "(grouped by market-cap class or another field, no price, or only a universe listing) is a market statistic and is not run as a scan.")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9",
}


class DashboardError(Exception):
    """A typed import failure: `code` is the stable short code, `status` the HTTP status the route answers with."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def validate_url(url: Any) -> Tuple[str, str]:
    """(canonical url, dashboard id). Only https://chartink.com/dashboard/<digits> is accepted: no other host, scheme, port, userinfo, query or fragment."""
    if not isinstance(url, str) or not url.strip() or len(url) > 200:
        raise DashboardError("invalid_dashboard_url", "dashboard_url must be a text like https://chartink.com/dashboard/123456.")
    m = DASHBOARD_URL_RE.match(url.strip())
    if not m:
        raise DashboardError("invalid_dashboard_url", "dashboard_url must be https://chartink.com/dashboard/<number> (https, host chartink.com, no query or extra path).")
    return f"https://{HOST}/dashboard/{m.group(1)}", m.group(1)


class _SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https://chartink.com/... (at most MAX_REDIRECTS); anything else is refused."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urllib.parse.urlparse(newurl)
        if p.scheme != "https" or (p.hostname or "").lower() != HOST or p.port not in (None, 443) or p.username or p.password:
            raise DashboardError("redirect_off_site", "Chartink redirected to another site; the dashboard was not fetched.", 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str) -> str:
    """The dashboard page text. Raises DashboardError (dashboard_fetch_failed / dashboard_too_large / redirect_off_site). Blocking: run in a thread."""
    opener = urllib.request.build_opener(_SameSiteRedirects())      # no cookie processor: nothing is stored or sent
    try:
        with opener.open(urllib.request.Request(url, headers=HEADERS), timeout=FETCH_TIMEOUT_S) as resp:
            raw = resp.read(MAX_PAGE_BYTES + 1)
    except DashboardError:
        raise
    except urllib.error.HTTPError as e:
        why = {404: "the dashboard was not found or is not public", 403: "Chartink refused the request (403)", 429: "Chartink is rate limiting this server (429)"}
        raise DashboardError("dashboard_fetch_failed", f"Chartink answered HTTP {e.code}: {why.get(e.code, 'the page could not be read')}.", 502)
    except Exception as e:  # noqa: BLE001 — timeout, DNS, TLS, a redirect loop: all become one typed error
        raise DashboardError("dashboard_fetch_failed", f"Chartink could not be reached ({type(e).__name__}).", 502)
    if len(raw) > MAX_PAGE_BYTES:
        raise DashboardError("dashboard_too_large", f"The dashboard page is larger than {MAX_PAGE_BYTES // 1_000_000} MB; it was not read.", 502)
    return raw.decode("utf-8", errors="replace")


_WIDGETS_RE = re.compile(r''':widgets=(?:"([^"]*)"|'([^']*)')''', re.S)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def parse_page(page: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(title, raw widget dicts). Raises dashboard_page_changed when the page has no widgets attribute or it is not a JSON list."""
    m = _WIDGETS_RE.search(page)
    if not m:
        raise DashboardError("dashboard_page_changed", "The page has no widget list (the dashboard is private, deleted, or Chartink changed its page).", 502)
    try:
        widgets = json.loads(html.unescape(m.group(1) if m.group(1) is not None else m.group(2)))
    except ValueError:
        raise DashboardError("dashboard_page_changed", "The page's widget list is not readable JSON (Chartink changed its page).", 502)
    if not isinstance(widgets, list):
        raise DashboardError("dashboard_page_changed", "The page's widget list is not a list (Chartink changed its page).", 502)
    t = _TITLE_RE.search(page)
    title = " ".join(html.unescape(t.group(1)).split())[:MAX_NAME_LEN] if t else None
    return title or None, [w for w in widgets[:MAX_WIDGETS] if isinstance(w, dict)]


# ── the query text ───────────────────────────────────────────────────────────

def _top_level(query: str, word: str) -> List[int]:
    """Start offsets of `word` (a keyword, case-insensitive) outside quotes and brackets/parentheses."""
    out, depth, quote, i, n = [], 0, None, 0, len(query)
    pat = re.compile(r"\b" + word.replace(" ", r"\s+") + r"\b", re.I)
    while i < n:
        ch = query[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and ch.lower() == word[0].lower():
            m = pat.match(query, i)
            if m and (i == 0 or not (query[i - 1].isalnum() or query[i - 1] == "_")):
                out.append(i)
        i += 1
    return out


def split_query(query: str) -> Dict[str, Any]:
    """{select, clause, group_by, aliases}. clause is the text after the top-level WHERE up to GROUP BY, whitespace collapsed; None parts when absent."""
    q = query if isinstance(query, str) else ""
    wh, gb = _top_level(q, "where"), _top_level(q, "group by")
    w = wh[0] if wh else None
    g = next((x for x in gb if w is None or x > w), None)
    clause = " ".join(q[w + 5:g].split()) if w is not None and g is not None else None
    gm = re.match(r"group\s+by\s+(\w+)", q[g:], re.I) if g is not None else None
    select = q[:w] if w is not None else q
    aliases = [a[0] or a[1] for a in re.findall(r"""\bas\s+(?:'([^']*)'|"([^"]*)")""", select, re.I)]
    return {"clause": clause or None, "group_by": gm.group(1).lower() if gm else None, "aliases": [a.strip() for a in aliases]}


def is_stock_scan(parts: Dict[str, Any]) -> bool:
    clause = re.sub(r"\s+", "", (parts["clause"] or "").lower())
    bare = re.fullmatch(r"(\{[^}]*\})?1=1", clause) is not None
    return parts["group_by"] == "symbol" and any(a.lower() == "price" for a in parts["aliases"]) and bool(clause) and not bare


_CUSTOM_RE = re.compile(r"\{custom_indicator_(\d+)_(start|end)\}")


def unsupported_reason(clause: str) -> Optional[str]:
    """Why the public screener endpoint cannot run this clause, or None. A custom indicator written inline between its
    {custom_indicator_N_start} and {custom_indicator_N_end} markers carries its own expression and runs; a marker without its pair does not."""
    marks = [(m.group(1), m.group(2)) for m in _CUSTOM_RE.finditer(clause)]
    for ident in {i for i, _ in marks}:
        if sum(1 for i, k in marks if i == ident and k == "start") != sum(1 for i, k in marks if i == ident and k == "end"):
            return "custom_indicator_reference: the clause refers to a custom indicator of the dashboard owner that is not written inline, which the public screener cannot evaluate"
    return None


def uses_intraday(clause: str) -> bool:
    return INTRADAY_RE.search(clause) is not None


def _text(v: Any, cap: int) -> Optional[str]:
    return " ".join(v.split())[:cap] if isinstance(v, str) and v.strip() else None


def widget_to_scan(w: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The scan entry stored for one widget (defaults: stock scans enabled and bullish; market statistics and unsupported scans disabled), or None for a
    widget without an id or a usable query. `clause` is kept for running and is dropped from API answers unless asked for."""
    wid, query = w.get("id"), w.get("query")
    if isinstance(wid, bool) or not isinstance(wid, (int, str)) or not str(wid).strip() or not isinstance(query, str):
        return None
    parts = split_query(query)
    name = _text(w.get("name"), MAX_NAME_LEN) or f"Scan {wid}"
    clause = parts["clause"]
    if clause is None or len(clause) > MAX_CLAUSE_LEN:
        return {"id": str(wid), "name": name, "description": _text(w.get("description"), MAX_DESC_LEN), "clause": None, "kind": "market_stats",
                "supported": False, "unsupported_reason": "no_clause: the widget's query has no WHERE ... GROUP BY condition to run" if clause is None
                else f"clause_too_long: more than {MAX_CLAUSE_LEN} characters", "uses_intraday_candles": False, "enabled": False, "direction": "neutral"}
    stock = is_stock_scan(parts)
    reason = unsupported_reason(clause) if stock else "market_statistic: " + STOCK_SCAN_RULE
    return {"id": str(wid), "name": name, "description": _text(w.get("description"), MAX_DESC_LEN), "clause": clause,
            "kind": "stock_scan" if stock else "market_stats", "supported": stock and reason is None, "unsupported_reason": reason,
            "uses_intraday_candles": uses_intraday(clause), "enabled": stock and reason is None, "direction": "bullish" if stock else "neutral"}


def build_scans(widgets: List[Dict[str, Any]], previous: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The scan list of a (re-)import. A scan the user already had (same widget id) keeps their `enabled` and `direction` choices, but `enabled`
    cannot be true for a scan that is now unsupported."""
    keep = {s["id"]: s for s in previous or []}
    out, seen = [], set()
    for w in widgets:
        s = widget_to_scan(w)
        if s is None or s["id"] in seen:
            continue
        seen.add(s["id"])
        old = keep.get(s["id"])
        if old and s["supported"]:
            if isinstance(old.get("enabled"), bool):
                s["enabled"] = old["enabled"]
            if old.get("direction") in ("bullish", "bearish", "neutral"):
                s["direction"] = old["direction"]
        out.append(s)
    return out
