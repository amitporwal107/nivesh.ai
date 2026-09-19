"""Redis cache in front of the Trendlyne MCP server, so data that does not change intraday is fetched at most once.

Freshness classes (IST):
  eod     prices, volumes, delivery, technicals, scores, price-based ratios (PE, PEG, P/S, market cap)
          -> expire at the next 07:00 IST (Trendlyne serves end-of-day data; it changes once per trading day)
  filing  shareholding, quarterly results, annual statements and ratios
          -> daily while filings are due (day 1-60 after a quarter end), else 7 days
  static  entity resolution, parameter search, label map -> 30 days
  docs    document search -> 7 days;  news -> 1 hour
  neg     stock codes Trendlyne cannot resolve -> 1 day (one bad code rejects a whole batch)

Bulk values are cached per (stock code, parameter), so any mix of stocks and parameters is served from the cache and
only the missing pairs are fetched, packed into calls of at most 10 stocks x 50 parameters.

Archive: the cache expires, the history must not. Every response actually fetched from Trendlyne is also appended to
TL_ARCHIVE_DIR/<fetch date IST>/{param_values,tool_responses}.jsonl.gz (append-only, never rewritten), so prices,
technicals, overview, events, deals and insider data accumulate a daily history. `read_archive` loads it back.
"""
import datetime as dt
import difflib
import glob
import gzip
import hashlib
import json
import os
import re

from tl_client import MAX_PARAMS, MAX_STOCKS, TLError, parse_entities, parse_param_values, unresolved_codes

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PREFIX = "tl:v1:"
DAY = 86400
FILING_RE = re.compile(r"holding|pledge|promoter|\bfii\b|\bdii\b|institution|\bmf\b|public", re.I)
EOD_RE = re.compile(r"\b(ltp|price|pe|peg|p/e|market cap|mcap|chg|change|vol\.?|volume|delivery|rsi|mfi|adx|atr|cci|"
                    r"williams?|macd|sma|ema|high|low|score|fair|discount|distance|spread|returns?|graham|yield|beta|"
                    r"close|open|52w|days below)\b", re.I)


class BudgetExceeded(RuntimeError):
    pass


def _norm(s: str) -> str:
    s = s.lower()
    for a, b in (("annual", "ann."), ("quarter", "qtr"), ("current price", "ltp"), ("year", "yr"), ("volume", "vol."),
                 ("average", "avg"), ("change", "chg"), ("trendlyne ", ""), ("capitalization", "cap")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9%]", "", s)


def classify(label: str) -> str:
    """Freshness class of a parameter from its human label (helping_text or response label).
    Ownership first (a 'holding change' is still quarterly data), then anything price- or market-driven is eod."""
    if FILING_RE.search(label):
        return "filing"
    return "eod" if EOD_RE.search(label) else "filing"


def next_0700_ist(now: dt.datetime) -> dt.datetime:
    n = now.astimezone(IST)
    t = n.replace(hour=7, minute=0, second=0, microsecond=0)
    return t if t > n else t + dt.timedelta(days=1)


def in_filing_season(d: dt.date) -> bool:
    """Day 1..60 after a quarter end (Mar/Jun/Sep/Dec): results and shareholding filings are still arriving."""
    for y in (d.year - 1, d.year):
        for m, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = dt.date(y, m, day)
            if 1 <= (d - q).days <= 60:
                return True
    return False


def expiry(cls: str, now: dt.datetime) -> int:
    """Seconds to live for a freshly fetched value of this class."""
    if cls == "eod":
        return max(60, int((next_0700_ist(now) - now).total_seconds()))
    if cls == "filing":
        return expiry("eod", now) if in_filing_season(now.astimezone(IST).date()) else 7 * DAY
    return {"static": 30 * DAY, "docs": 7 * DAY, "news": 3600, "neg": DAY}[cls]


def plan_batches(missing: dict) -> list[tuple[list[str], list[str]]]:
    """Pack {code: missing params} into as few calls as possible: up to 10 codes per call, and the call asks for the
    union of their missing params (up to 50). Re-fetching a param that is already cached for one of the codes costs
    nothing extra and refreshes it. Codes needing more than 50 params are split across calls."""
    batches, cur_c, cur_p = [], [], set()
    for c in sorted(missing, key=lambda c: (sorted(missing[c]), c)):
        ps = sorted(missing[c])
        for j in range(0, len(ps), MAX_PARAMS):
            chunk = set(ps[j:j + MAX_PARAMS])
            if cur_c and (len(cur_c) >= MAX_STOCKS or len(cur_p | chunk) > MAX_PARAMS or c in cur_c):
                batches.append((cur_c, sorted(cur_p)))
                cur_c, cur_p = [], set()
            cur_c.append(c)
            cur_p |= chunk
    if cur_c:
        batches.append((cur_c, sorted(cur_p)))
    return batches


class RedisStore:
    """The small surface TLCache needs; a dict-backed fake with the same methods is used in tests."""

    def __init__(self, url: str | None = None):
        import redis
        self.r = redis.Redis.from_url(url or os.environ.get("TL_REDIS_URL", "redis://127.0.0.1:6380/2"),
                                      socket_timeout=5, decode_responses=True)

    def mget(self, keys):
        return self.r.mget(keys) if keys else []

    def set_many(self, items):  # {key: (value, ttl_seconds)}
        p = self.r.pipeline()
        for k, (v, ttl) in items.items():
            p.set(k, v, ex=int(ttl))
        p.execute()

    def get(self, k):
        return self.r.get(k)

    def incr(self, k, ttl):
        p = self.r.pipeline()
        p.incr(k)
        p.expire(k, ttl)
        return p.execute()[0]

    def hgetall(self, k):
        return self.r.hgetall(k)

    def hset_many(self, k, mapping, ttl):
        if mapping:
            p = self.r.pipeline()
            p.hset(k, mapping=mapping)
            p.expire(k, ttl)
            p.execute()


ARCHIVE_DIR = os.environ.get("TL_ARCHIVE_DIR", "/app/research/trendlyne/archive")


def archive_append(root: str, kind: str, record: dict, fetched_at: dt.datetime):
    """Append one JSON line to <root>/<YYYY-MM-DD>/<kind>.jsonl.gz (multi-member gzip: safe to append)."""
    d = os.path.join(root, fetched_at.astimezone(IST).strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f"{kind}.jsonl.gz"), "at", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")


def read_archive(kind: str, root: str = ARCHIVE_DIR, start: str = "0000", end: str = "9999"):
    """Yield archived records of one kind for fetch dates start..end (YYYY-MM-DD, inclusive)."""
    for d in sorted(glob.glob(os.path.join(root, "*", f"{kind}.jsonl.gz"))):
        day = os.path.basename(os.path.dirname(d))
        if start <= day <= end:
            with gzip.open(d, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)


class TLCache:
    def __init__(self, client, store, daily_cap: int | None = None, now=None, archive_dir: str | None = ARCHIVE_DIR):
        self.client, self.store = client, store
        self.archive_dir = archive_dir
        self.daily_cap = daily_cap if daily_cap is not None else int(os.environ.get("TL_DAILY_CALL_CAP", "300"))
        self._now = now or (lambda: dt.datetime.now(IST))
        self.stats = {"calls": 0, "rejected": 0, "hits": 0, "misses": 0}

    # ---- quota ----------------------------------------------------------------------------------------------------
    def calls_today(self) -> int:
        return int(self.store.get(f"{PREFIX}calls:{self._now().date()}") or 0)

    def _call(self, tool: str, args: dict) -> str:
        if self.calls_today() >= self.daily_cap:
            raise BudgetExceeded(f"daily Trendlyne call cap {self.daily_cap} reached")
        now = self._now()
        self.store.incr(f"{PREFIX}calls:{now.date()}", 3 * DAY)
        self.store.incr(f"{PREFIX}calls:{now:%Y-%m}", 40 * DAY)
        self.stats["calls"] += 1
        return self.client.call(tool, args)

    # ---- cached whole-response tools ------------------------------------------------------------------------------
    def _cached_tool(self, tool: str, args: dict, cls: str) -> str:
        key = PREFIX + "tool:" + tool + ":" + hashlib.sha1(json.dumps(args, sort_keys=True).encode()).hexdigest()[:20]
        hit = self.store.get(key)
        if hit is not None:
            self.stats["hits"] += 1
            return hit
        self.stats["misses"] += 1
        text = self._call(tool, args)
        now = self._now()
        self.store.set_many({key: (text, expiry(cls, now))})
        if self.archive_dir:
            archive_append(self.archive_dir, "tool_responses",
                           {"fetched_at": now.isoformat(timespec="seconds"), "tool": tool, "args": args, "cls": cls,
                            "text": text}, now)
        return text

    def search_entities(self, query: str, limit: int = 5) -> list[dict]:
        return parse_entities(self._cached_tool("search_entities", {"query": query, "entity_type": "stock", "limit": limit}, "static"))

    def search_parameters(self, query: str) -> list[dict]:
        data = json.loads(self._cached_tool("search_financial_parameters", {"query": query}, "static")).get("data", [])
        self.store.hset_many(PREFIX + "paramtext", {d["parameter"]: d["helping_text"] for d in data}, 90 * DAY)
        return data

    def ownership(self, code: str, kind: str = "shareholding") -> str:
        return self._cached_tool("get_ownership_deals_insider_sast", {"stock_code": code, "type": kind},
                                 "filing" if kind == "shareholding" else "eod")

    def overview(self, code: str, kind: str = "overview") -> str:
        return self._cached_tool("get_overview_news_corp_events", {"stock_code": code, "type": kind},
                                 "news" if kind == "news" else "eod")

    def documents(self, query: str) -> str:
        return self._cached_tool("get_document_search_results", {"query": query}, "docs")

    # ---- per-(stock, parameter) bulk values -----------------------------------------------------------------------
    def labels(self) -> dict:
        return self.store.hgetall(PREFIX + "labelmap") or {}

    def seed_labels(self, mapping: dict):
        self.store.hset_many(PREFIX + "labelmap", mapping, 90 * DAY)

    def seed_param_text(self, mapping: dict):
        self.store.hset_many(PREFIX + "paramtext", mapping, 90 * DAY)

    def _map_labels(self, params: list[str], response_labels: list[str]) -> dict:
        """param -> response label. Known pairs first, then a unique confident fuzzy match; else unmapped."""
        known, text = self.labels(), self.store.hgetall(PREFIX + "paramtext") or {}
        out, free = {}, [l for l in response_labels]
        for p in params:
            if known.get(p) in free:
                out[p] = known[p]
                free.remove(known[p])
        new = {}
        for p in [p for p in params if p not in out]:  # exact name match first (SMA20 vs SMA200 differ only slightly)
            exact = [l for l in free if _norm(l) == _norm(text.get(p, p))]
            if len(exact) == 1:
                out[p] = exact[0]
                free.remove(exact[0])
                new[p] = exact[0]
        for p in [p for p in params if p not in out]:
            scores = sorted(((difflib.SequenceMatcher(None, _norm(text.get(p, p)), _norm(l)).ratio(), l) for l in free), reverse=True)
            if len(free) == 1 or (scores and scores[0][0] >= 0.8 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.15)):
                out[p] = free[0] if len(free) == 1 else scores[0][1]
                free.remove(out[p])
                new[p] = out[p]
        if new:
            self.seed_labels(new)
        return out

    def _pv_key(self, code: str, param: str) -> str:
        return f"{PREFIX}pv:{code.upper()}:{param}"

    def get_params(self, codes: list[str], params: list[str]) -> dict:
        """{code: {param: value-or-None}} for every resolvable code; fetches only uncached pairs."""
        codes = list(dict.fromkeys(c.strip().upper() for c in codes if c and c.strip()))
        params = list(dict.fromkeys(params))
        neg = dict(zip(codes, self.store.mget([f"{PREFIX}neg:{c}" for c in codes])))
        codes = [c for c in codes if neg[c] is None]
        keys = [(c, p) for c in codes for p in params]
        cached = dict(zip(keys, self.store.mget([self._pv_key(c, p) for c, p in keys])))
        missing = {}
        for (c, p), v in cached.items():
            if v is None:
                missing.setdefault(c, set()).add(p)
        self.stats["hits"] += sum(v is not None for v in cached.values())
        self.stats["misses"] += sum(len(s) for s in missing.values())
        for cs, ps in plan_batches(missing):
            self._fetch(cs, ps, cached)
        out = {c: {} for c in codes if self.store.get(f"{PREFIX}neg:{c}") is None}
        for (c, p), v in cached.items():
            if c in out:
                out[c][p] = None if v is None else json.loads(v)["v"]
        return out

    def _fetch(self, cs: list[str], ps: list[str], cached: dict, retry: bool = True):
        try:
            stocks, vals = parse_param_values(self._call("get_stock_parameter_values", {"stock_codes": cs, "parameters": ps}))
        except TLError as e:
            bad = unresolved_codes(str(e), cs)
            self.stats["rejected"] += 1
            if not bad or not retry:
                raise
            self.store.set_many({f"{PREFIX}neg:{c.upper()}": (str(e)[:200], expiry("neg", self._now())) for c in bad})
            rest = [c for c in cs if c not in bad]
            if rest:
                self._fetch(rest, ps, cached, retry=False)
            return
        self._store(cs, ps, stocks, vals, self._now(), cached)

    def restore(self, record: dict) -> int:
        """Re-cache an archived param_values record from its raw labelled values (no call, not re-archived) — used
        after new label mappings are confirmed. Values keep their original expiry."""
        cs, raw = record["codes"], record.get("raw") or {}
        keys = list(dict.fromkeys(k for v in raw.values() for k in v))
        rk = record.get("row_key") or {}
        left = [k for k in keys if k not in cs and k not in rk.values()]
        for c in cs:
            rk.setdefault(c, c if c in keys else (left.pop(0) if left else None))
        stocks = [{"nse": rk[c], "bse": "", "name": record.get("names", {}).get(c, ""), "asof": record.get("asof", {}).get(c)}
                  for c in cs if rk.get(c)]
        cached = {}
        self._store(cs, record["params"], stocks, raw, dt.datetime.fromisoformat(record["fetched_at"]), cached, archive=False)
        return len(cached)

    def ingest(self, cs: list[str], ps: list[str], text: str, fetched_at: dt.datetime) -> int:
        """Cache a get_stock_parameter_values response obtained earlier (e.g. from a call log); values keep the expiry
        they would have had at fetch time. Returns the number of values stored."""
        stocks, vals = parse_param_values(text)
        cached = {}
        self._store([c.upper() for c in cs], ps, stocks, vals, fetched_at, cached)
        return len(cached)

    def _store(self, cs, ps, stocks, vals, fetched_at: dt.datetime, cached: dict, archive: bool = True):
        # response rows are keyed by the stock's NSE symbol (or its numeric id for BSE-only stocks); map back to codes
        row_key, left = {}, []
        for s in stocks:
            code = next((c for c in cs if c in (s["nse"].upper(), s["bse"].upper())), None)
            if code:
                row_key[code] = s["nse"]
            else:
                left.append(s)
        for c, s in zip([c for c in cs if c not in row_key], left):  # ISIN requests: response order = request order
            row_key[c] = s["nse"]
        asof = {s["nse"]: s["asof"] for s in stocks}
        lab = self._map_labels(ps, list(vals))
        if self.archive_dir and archive:
            archive_append(self.archive_dir, "param_values", {
                "fetched_at": fetched_at.isoformat(timespec="seconds"), "codes": cs, "params": ps,
                "labels": {p: lab.get(p) for p in ps},
                "asof": {c: asof.get(row_key[c]) for c in cs if c in row_key},
                "values": {c: {p: vals.get(lab[p], {}).get(row_key[c]) for p in ps if lab.get(p)} for c in cs if c in row_key},
                "names": {c: s["name"] for c in cs for s in stocks if row_key.get(c) == s["nse"]},
                "row_key": row_key, "raw": vals}, fetched_at)  # every labelled value as served, including labels not yet mapped to a code
        age = (self._now() - fetched_at).total_seconds()
        items = {}
        for p in ps:
            label = lab.get(p)
            if label is None:  # never cache a blank we could not attribute; it would hide real data
                self.stats.setdefault("unmapped", set()).add(p)
                continue
            cls = classify(label)
            ttl = expiry(cls, fetched_at) - age
            if ttl <= 0:
                continue
            for c in cs:
                if c not in row_key:
                    continue
                raw = vals.get(label, {}).get(row_key[c])
                v = None if raw in (None, "", "None", "null", "-") else raw
                rec = json.dumps({"v": v, "asof": asof.get(row_key[c]), "at": fetched_at.isoformat(timespec="seconds"), "cls": cls})
                items[self._pv_key(c, p)] = (rec, ttl)
                cached[(c, p)] = rec
        self.store.set_many(items)
