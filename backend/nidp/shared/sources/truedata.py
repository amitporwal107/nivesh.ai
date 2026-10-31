"""TrueData REST client: history bars and ticks, bhavcopy, symbol master, corporate actions, symbol changes, option chain
with Greeks. Standard library only, so the NIDP jobs and the app backend can both use it.

TrueData was chosen by the owner (29 Oct 2026). Every behaviour below was checked against TrueData's documentation AND
real calls on the trial account the same day (see the PR's report):
  * auth: POST https://auth.truedata.in/token (form, grant_type=password) → bearer token with `expires_in`.
  * TrueData answers many failures with HTTP 200 and a one-line body: "No data exists for X", "Symbol does not exist",
    "API calls quota exceeded!…", "Segment not subscribed", "Authorization has been denied…". These are classified
    into the provider contract's codes (services/providers/contract.py), never passed through as data.
  * history bars are ADJUSTED for corporate actions (bonus, split…), even past bhavcopies. Raw prices stay with NSE's
    own files (backend/nidp/shared/market_data_source.py).
  * the symbol master is served from api.truedata.in with the user and password IN THE QUERY STRING (TrueData's
    design); that URL is never logged and never put in an error.
  * the documents give different rate limits (10, 3 and 1 request/s); a per-host gate keeps at least `min_interval`
    seconds between calls (default 1.1 s, env TRUEDATA_MIN_INTERVAL_S).

Credentials: TRUEDATA_USERNAME / TRUEDATA_PASSWORD from the environment, or a KEY=VALUE file named by TRUEDATA_CRED_FILE
(local and research runs). Nothing here prints, logs or returns a password or a token.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AUTH_URL = "https://auth.truedata.in/token"
HISTORY = "https://history.truedata.in"
API = "https://api.truedata.in"
GREEKS = "https://greeks.truedata.in/api"
PROVIDER_ID = "truedata"
CLIENT_VERSION = "truedata-rest-v1"

# Reason codes, the same strings as services/providers/contract.py (not imported: NIDP jobs do not load the app).
NOT_CONFIGURED = "NOT_CONFIGURED"
AUTH_EXPIRED = "AUTH_EXPIRED"
RATE_LIMITED = "RATE_LIMITED"
EMPTY_RESPONSE = "EMPTY_RESPONSE"
IDENTIFIER_NOT_RESOLVED = "IDENTIFIER_NOT_RESOLVED"
INVALID_PAYLOAD = "INVALID_PAYLOAD"
TOOL_SCHEMA_CHANGED = "TOOL_SCHEMA_CHANGED"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
PROVIDER_ERROR = "PROVIDER_ERROR"
INVALID_REQUEST = "INVALID_REQUEST"
RETRYABLE = frozenset({RATE_LIMITED, PROVIDER_UNAVAILABLE})

BAR_INTERVALS = ("1min", "2min", "3min", "5min", "10min", "15min", "30min", "60min", "eod")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_NULL_DATES = {"", "1970-01-01", "0001-01-01"}


class TrueDataError(Exception):
    """A call that produced no usable records. The message never contains a credential, a token or a URL."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = code in RETRYABLE

    def __repr__(self) -> str:
        return f"TrueDataError({self.code!r}, {self.message!r})"


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:                      # never shows the password
        return f"Credentials(username={self.username!r}, password=<redacted>)"


def credentials_from_env(env: Optional[Dict[str, str]] = None) -> Optional[Credentials]:
    env = os.environ if env is None else env
    user, pwd = (env.get("TRUEDATA_USERNAME") or "").strip(), (env.get("TRUEDATA_PASSWORD") or "").strip()
    if not (user and pwd) and env.get("TRUEDATA_CRED_FILE"):
        try:
            pairs = dict(line.split("=", 1) for line in open(env["TRUEDATA_CRED_FILE"]).read().split() if "=" in line)
            user, pwd = pairs.get("TRUEDATA_USERNAME", "").strip(), pairs.get("TRUEDATA_PASSWORD", "").strip()
        except OSError:
            return None
    return Credentials(user, pwd) if user and pwd else None


# ── Symbol mapping: NSE contract → TrueData symbol (formats checked on the trial, 29 Oct 2026) ────────────────

def _strike_text(strike: float) -> str:
    s = float(strike)
    return str(int(s)) if s == int(s) else f"{s:.2f}".rstrip("0").rstrip(".")


def option_symbol(underlying: str, expiry: date, strike: float, right: str) -> str:
    """NIFTY, 2026-11-03, 23000, CE → NIFTY26110323000CE."""
    right = right.upper()
    if right not in ("CE", "PE"):
        raise ValueError(f"option right must be CE or PE, not {right!r}")
    return f"{underlying.upper()}{expiry:%y%m%d}{_strike_text(strike)}{right}"


def future_symbol(underlying: str, expiry: date) -> str:
    """RELIANCE, 2026-11-23 → RELIANCE26NOVFUT."""
    return f"{underlying.upper()}{expiry:%y}{_MONTHS[expiry.month - 1]}FUT"


def continuous_future_symbol(underlying: str, month: int = 1) -> str:
    """NIFTY, 1 → NIFTY-I (near month); 2 → NIFTY-II."""
    if month not in (1, 2, 3):
        raise ValueError("continuous month must be 1, 2 or 3")
    return f"{underlying.upper()}-{'I' * month}"


def index_symbol(name: str) -> str:
    """Warehouse index names ("Nifty 50", "Nifty Bank") → TrueData's ("NIFTY 50", "NIFTY BANK")."""
    return " ".join(name.split()).upper()


# ── Parsing helpers ───────────────────────────────────────────────────────────────────────────────────────────

def _num(v: Any) -> Any:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return s
    return int(f) if f.is_integer() and "." not in s else f


def _date_or_none(v: Optional[str], fmts=("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y %I:%M:%S %p")) -> Optional[date]:
    s = (v or "").strip()
    if s in _NULL_DATES:
        return None
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def classify_message(text: str) -> Optional[Tuple[str, str]]:
    """TrueData's one-line failure answers (sent with HTTP 200) → (code, message). None for a data body."""
    head = text.strip().strip('"').strip()
    low = head.lower()
    if low.startswith("<!doctype") or low.startswith("<html"):
        return PROVIDER_ERROR, "TrueData returned an HTML page (unknown path or service error)"
    if "\n" in head or len(head) > 300:                # a data body (CSV), not a one-line failure
        return None
    if low.startswith("no data exists"):
        return EMPTY_RESPONSE, head[:200]
    if "symbol does not exist" in low:
        return IDENTIFIER_NOT_RESOLVED, head[:200]
    if "quota exceeded" in low:
        return RATE_LIMITED, head[:200]
    if "segment not subscribed" in low or "authorization has been denied" in low:
        return NOT_CONFIGURED, head[:200]
    if low.startswith("invalid"):
        return INVALID_REQUEST, head[:200]
    return None


# Columns that are names or dates, never numbers (a symbol such as "NAN" or a code such as "500325" stays text).
_TEXT_COLS = frozenset({
    "symbol", "isin", "series", "company", "purpose", "oldsymbol", "new_symbol", "underlying", "metastocksymbol",
    "symbolalias", "industry", "exchange", "timestamp", "expiry", "circuit", "ex_date", "record_date", "bc_start",
    "bc_end", "applicationdate", "calltimestamp", "puttimestamp"})


def _cell(col: str, v: str) -> Any:
    if col.lower() in _TEXT_COLS:
        s = v.strip()
        return s or None
    return _num(v)


def parse_csv(text: str) -> List[Dict[str, Any]]:
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    return [{k: _cell(k, v) for k, v in zip(header, r)} for r in rows[1:]]


# ── Client ────────────────────────────────────────────────────────────────────────────────────────────────────

Transport = Callable[[str, str, Optional[bytes], Dict[str, str], float], Tuple[int, bytes]]


USER_AGENT = "nivesh-nidp/1.0"


def _urllib_transport(method: str, url: str, data: Optional[bytes], headers: Dict[str, str],
                      timeout: float) -> Tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class TrueDataClient:
    """One client per process is enough; the token and the rate gate are shared by all its calls."""

    def __init__(self, credentials: Optional[Credentials] = None, *, transport: Optional[Transport] = None,
                 min_interval: Optional[float] = None, timeout: float = 60.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self._creds = credentials if credentials is not None else credentials_from_env()
        self._transport = transport or _urllib_transport
        self._min_interval = float(min_interval if min_interval is not None
                                   else os.environ.get("TRUEDATA_MIN_INTERVAL_S", "1.1"))
        self._timeout = timeout
        self._clock, self._sleep = clock, sleep
        self._token: Optional[str] = None
        self._token_until = 0.0
        self._last_call: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._creds is not None

    # ── plumbing ──
    def _require_creds(self) -> Credentials:
        if self._creds is None:
            raise TrueDataError(NOT_CONFIGURED, "TrueData credentials are not configured "
                                                "(TRUEDATA_USERNAME / TRUEDATA_PASSWORD)")
        return self._creds

    def _gate(self, host: str) -> None:
        with self._lock:
            now = self._clock()
            wait = self._last_call.get(host, -1e9) + self._min_interval - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
            self._last_call[host] = now

    def _fetch_token(self) -> str:
        creds = self._require_creds()
        body = urllib.parse.urlencode({"username": creds.username, "password": creds.password,
                                       "grant_type": "password"}).encode()
        self._gate("auth")
        try:
            status, raw = self._transport("POST", AUTH_URL, body,
                                          {"Content-Type": "application/x-www-form-urlencoded"}, self._timeout)
        except Exception as exc:                                     # network failure
            raise TrueDataError(PROVIDER_UNAVAILABLE, f"TrueData auth unreachable: {type(exc).__name__}") from None
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            payload = {}
        token = payload.get("access_token")
        if status != 200 or not token:
            desc = str(payload.get("error_description") or payload.get("error") or f"HTTP {status}")[:160]
            raise TrueDataError(AUTH_EXPIRED, f"TrueData login refused: {desc}")
        ttl = float(payload.get("expires_in") or 3600)
        self._token, self._token_until = token, self._clock() + max(60.0, ttl - 300.0)
        return token

    def _bearer(self, force: bool = False) -> str:
        if force or not self._token or self._clock() >= self._token_until:
            return self._fetch_token()
        return self._token

    def _get(self, base: str, path: str, params: Dict[str, Any], *, creds_in_query: bool = False) -> str:
        """GET → body text. Retries once after refreshing the token on a 401. Never exposes the URL."""
        query = {k: v for k, v in params.items() if v is not None}
        headers: Dict[str, str] = {}
        if creds_in_query:
            creds = self._require_creds()
            query.update({"user": creds.username, "password": creds.password})
        host = urllib.parse.urlsplit(base).netloc
        for attempt in (1, 2):
            if not creds_in_query:
                headers["Authorization"] = f"Bearer {self._bearer(force=attempt == 2)}"
            self._gate(host)
            url = f"{base}/{path}?{urllib.parse.urlencode(query)}"
            try:
                status, raw = self._transport("GET", url, None, headers, self._timeout)
            except Exception as exc:
                raise TrueDataError(PROVIDER_UNAVAILABLE, f"TrueData {path} unreachable: {type(exc).__name__}") from None
            text = raw.decode("utf-8", "replace")
            if status == 401 and attempt == 1 and not creds_in_query:
                continue
            if status == 401:
                raise TrueDataError(AUTH_EXPIRED, f"TrueData {path}: authorization refused")
            if status == 429:
                raise TrueDataError(RATE_LIMITED, f"TrueData {path}: rate limited")
            if status >= 500:
                raise TrueDataError(PROVIDER_UNAVAILABLE, f"TrueData {path}: HTTP {status}")
            failure = classify_message(text)
            if failure:
                code, msg = failure
                raise TrueDataError(code, f"TrueData {path}: {msg}")
            if status != 200:
                raise TrueDataError(PROVIDER_ERROR, f"TrueData {path}: HTTP {status}")
            return text
        raise TrueDataError(AUTH_EXPIRED, f"TrueData {path}: authorization refused")   # pragma: no cover

    # ── history ──
    def bars(self, symbol: str, start: datetime, end: datetime, interval: str = "1min",
             delivery: bool = False) -> List[Dict[str, Any]]:
        """OHLCV(+OI) bars, ADJUSTED for corporate actions. interval: 1min…60min or eod."""
        if interval not in BAR_INTERVALS:
            raise TrueDataError(INVALID_REQUEST, f"unknown bar interval {interval!r}")
        text = self._get(HISTORY, "getbars", {
            "symbol": symbol, "from": f"{start:%y%m%dT%H:%M:%S}", "to": f"{end:%y%m%dT%H:%M:%S}",
            "response": "csv", "interval": interval, "delivery": "true" if delivery else None})
        return parse_csv(text)

    def ticks(self, symbol: str, start: datetime, end: datetime, bidask: bool = True) -> List[Dict[str, Any]]:
        """Tick history (about one week back on the trial), with best bid/ask when `bidask`."""
        text = self._get(HISTORY, "getticks", {
            "symbol": symbol, "bidask": "1" if bidask else "0", "from": f"{start:%y%m%dT%H:%M:%S}",
            "to": f"{end:%y%m%dT%H:%M:%S}", "response": "csv"})
        return parse_csv(text)

    def bhavcopy(self, segment: str, day: date) -> List[Dict[str, Any]]:
        """End-of-day snapshot for a segment ('EQ' or 'FO'). Traded contracts only; adjusted for later corporate
        actions when the date is in the past."""
        segment = segment.upper()
        if segment not in ("EQ", "FO"):
            raise TrueDataError(INVALID_REQUEST, f"bhavcopy segment must be EQ or FO, not {segment!r}")
        return parse_csv(self._get(HISTORY, "getbhavcopy", {"segment": segment, "date": f"{day:%Y-%m-%d}",
                                                             "response": "csv"}))

    def expiries(self, symbol: str) -> List[date]:
        rows = parse_csv(self._get(HISTORY, "getSymbolExpiryList", {"symbol": symbol, "response": "csv"}))
        out = [_date_or_none(str(r.get("expiry"))) for r in rows]
        return [d for d in out if d and d.year < 2099]          # 2099-12-31 marks the continuous contract

    def index_components(self, index_name: str) -> List[Dict[str, Any]]:
        """CURRENT members only (no point-in-time history)."""
        return parse_csv(self._get(HISTORY, "getindexcomponents", {"response": "csv", "indexname": index_name}))

    def symbol_changes(self, symbol: str) -> List[Dict[str, Any]]:
        rows = parse_csv(self._get(HISTORY, "getsymbolchangehistory", {"response": "csv", "SYMBOL": symbol}))
        for r in rows:
            r["effective_date"] = _date_or_none(str(r.get("applicationdate") or ""))
        return rows

    def corporate_actions(self, ex_from: date, ex_to: date) -> List[Dict[str, Any]]:
        """All corporate actions (NSE and BSE) with ex-date in the range. `ratio` is TrueData's adjustment ratio
        (bonus 1:1 → 2, split 10→2 → 5); BSE rows carry a `_BSE` suffix on the symbol.

        Two quirks seen on the trial (29 Oct 2026), handled here rather than passed on:
          * identical rows can repeat (the same BSE buy-back three times): exact duplicates are dropped;
          * BSE split rows carry ratio 1 where the NSE row of the same split carries 5 or 10: a split, bonus or
            consolidation with ratio 1 is flagged `ratio_suspect`, so it is never read as "no adjustment"."""
        raw = parse_csv(self._get(HISTORY, "getcorpactionrange", {"exdatefrom": f"{ex_from:%Y-%m-%d}",
                                                                   "exdateto": f"{ex_to:%Y-%m-%d}",
                                                                   "response": "csv"}))
        seen, rows = set(), []
        for r in raw:
            key = tuple(sorted((k, str(v)) for k, v in r.items()))
            if key not in seen:
                seen.add(key)
                rows.append(r)
        for r in rows:
            sym = str(r.get("symbol") or "")
            r["exchange"] = "BSE" if sym.endswith("_BSE") else "NSE"
            r["base_symbol"] = sym[:-4] if sym.endswith("_BSE") else sym
            r["kind"] = corporate_action_kind(str(r.get("purpose") or ""))
            r["ratio"] = float(r["ratio"]) if isinstance(r.get("ratio"), (int, float)) else None
            r["ratio_suspect"] = r["kind"] in ("split", "bonus", "consolidation") and r["ratio"] in (None, 1.0)
            for k in ("ex_date", "record_date", "bc_start", "bc_end"):
                r[k] = _date_or_none(str(r.get(k) or ""))
        return rows

    def option_chain_greeks(self, symbol: str, expiry: date) -> List[Dict[str, Any]]:
        """Live option chain with Greeks (an add-on on paid plans)."""
        return parse_csv(self._get(GREEKS, "getOptionChainwithGreeks", {"symbol": symbol,
                                                                         "expiry": f"{expiry:%d-%m-%Y}",
                                                                         "response": "csv"}))

    def symbol_master(self, segment: str, search: Optional[str] = None,
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Instrument master: lot size, tick size (rupees), ISIN, expiry, strike, circuit band. TrueData takes the
        credentials in the query string here; the URL is never logged."""
        text = self._get(API, "getAllSymbols", {
            "segment": segment, "csv": "true", "csvHeader": "true", "ticksize": "true", "companyname": "true",
            "isin": "true", "underlying": "true", "circuit": "true", "search": search, "limit": limit},
            creds_in_query=True)
        return parse_symbol_master(text)


def corporate_action_kind(purpose: str) -> str:
    p = purpose.lower()
    if "bonus" in p:
        return "bonus"
    if "split" in p or "sub-division" in p or "subdivision" in p:
        return "split"
    if "consolid" in p:
        return "consolidation"
    if "right" in p:
        return "rights"
    if "demerger" in p:
        return "demerger"
    if "dividend" in p:
        return "dividend"
    return "other"


def parse_symbol_master(text: str) -> List[Dict[str, Any]]:
    """The master's header can carry one more column than its rows (seen on the trial: a duplicate `symbolalias` in
    the equity master, an empty `company` in the F&O master). Align by dropping the duplicate, then `company`;
    anything else is a schema change and is refused rather than misread."""
    raw = [r for r in csv.reader(io.StringIO(text)) if r and any(c.strip() for c in r)]
    if not raw:
        return []
    header = [h.strip() for h in raw[0]]
    out: List[Dict[str, Any]] = []
    for row in raw[1:]:
        cols = header
        if len(row) != len(cols):
            dedup = list(dict.fromkeys(cols))
            if len(row) == len(dedup):
                cols = dedup
            elif len(row) == len(dedup) - 1 and "company" in dedup:
                cols = [c for c in dedup if c != "company"]
            else:
                raise TrueDataError(TOOL_SCHEMA_CHANGED,
                                    f"symbol master row has {len(row)} fields for a {len(header)}-column header")
        rec = {k: _cell(k, v) for k, v in zip(cols, row)}
        tick = rec.get("ticksize")
        rec["tick_size"] = round(tick / 100.0, 4) if isinstance(tick, (int, float)) else None    # paise → rupees
        band = str(rec.get("circuit") or "")
        parts = [_num(p) for p in band.split("-") if p.strip()]
        nums = [p for p in parts if isinstance(p, (int, float))]
        rec["circuit_low"], rec["circuit_high"] = (min(nums), max(nums)) if len(nums) == 2 else (None, None)
        rec["expiry_date"] = _date_or_none(str(rec.get("expiry") or ""))
        out.append(rec)
    return out
