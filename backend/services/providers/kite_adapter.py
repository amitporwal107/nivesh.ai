"""KiteMarketDataAdapter — instrument master and historical candles (docs/charting.md §32.5).

Built on the existing client in nidp/services/kite_bars (one Kite client and one credential path
for the repo). This adapter adds what §32 asks of a provider: a normalized result, deterministic
reason codes, bounded retry with backoff on retryable failures only, and integrity findings on the
candles it returns. It is synchronous (the kiteconnect SDK is); routes call it off the event loop.

What it does NOT certify (Phase B, stated on every candle result rather than assumed):
  * price_adjustment      — whether Kite's series is corporate-action adjusted is UNVERIFIED here;
  * session_completeness  — missing trading sessions are UNCHECKED (needs the exchange calendar).

The access token is read at call time and never logged, returned or put in an error message.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from nidp.services.kite_bars.client import MAX_DAYS, windows

from .contract import (
    AUTH_EXPIRED, DQ_BLOCKED, DQ_EMPTY, DQ_OK, DQ_PARTIAL, EMPTY_RESPONSE, IDENTIFIER_NOT_RESOLVED,
    INVALID_PAYLOAD, INVALID_REQUEST, PARTIAL_RESPONSE, PROVIDER_ERROR, PROVIDER_KITE, PROVIDER_UNAVAILABLE,
    RATE_LIMITED, RETRYABLE, ProviderError, ProviderResult, new_request_id, utcnow,
)

PROVIDER_VERSION = "kite-connect-v3"
NORMALIZATION_VERSION = "kite-candles-v1"
EXCHANGES = ("NSE", "BSE")
IST = timezone(timedelta(hours=5, minutes=30))
MAX_RETRIES = 3
BACKOFF_SECONDS = 1.5
REQ_INTERVAL = 0.35           # Kite allows ~3 historical req/s; same pacing as kite_bars/collect.py

# symbol -> instrument_token, per (exchange, IST date): the master is republished daily.
_instrument_cache: Dict[Tuple[str, date], Dict[str, int]] = {}


def default_token() -> str:
    """Today's access token: the secrets store, else the kite_bars daily token file."""
    from helpers import secrets
    token = (secrets.get("KITE_ACCESS_TOKEN") or "").strip()
    if token:
        return token
    from nidp.services.kite_bars.auth import read_token
    return read_token()


def _default_factory(access_token: str):
    from nidp.services.kite_bars.client import kite
    return kite(access_token)


def classify(exc: Exception) -> str:
    """Map a kiteconnect / transport exception to one reason code."""
    name = type(exc).__name__
    if getattr(exc, "code", None) == 429 or "too many requests" in str(exc).lower():
        return RATE_LIMITED
    if name in ("TokenException", "PermissionException"):
        return AUTH_EXPIRED
    if name == "InputException":
        return INVALID_REQUEST
    if name in ("NetworkException", "DataException", "GeneralException") or \
            any(tag in name for tag in ("Timeout", "ConnectionError", "SSLError")):
        return PROVIDER_UNAVAILABLE
    return PROVIDER_ERROR


class KiteMarketDataAdapter:
    provider_id = PROVIDER_KITE
    provider_version = PROVIDER_VERSION

    def __init__(self, *, token_getter: Callable[[], str] = default_token,
                 kite_factory: Callable[[str], Any] = _default_factory,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = MAX_RETRIES):
        self._token_getter = token_getter
        self._kite_factory = kite_factory
        self._sleep = sleep
        self._max_retries = max_retries

    # ── plumbing ─────────────────────────────────────────────────────────
    def _client(self):
        token = (self._token_getter() or "").strip()
        if not token:
            raise ProviderError(AUTH_EXPIRED, "no Kite access token; the daily login handshake has not been run")
        try:
            return self._kite_factory(token)
        except RuntimeError as e:          # kite_bars raises this for a missing key or SDK
            raise ProviderError(AUTH_EXPIRED if "API_KEY" in str(e) else PROVIDER_ERROR, str(e)) from e

    def _call(self, fn: Callable[..., Any], *args, **kwargs):
        """Run one SDK call. Retries only failures classified as retryable, with backoff."""
        attempt = 0
        while True:
            attempt += 1
            try:
                return fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — classified below, never swallowed
                code = classify(e)
                if code not in RETRYABLE or attempt >= self._max_retries:
                    raise ProviderError(code, f"{type(e).__name__}: {e}"[:300]) from e
                self._sleep(BACKOFF_SECONDS * attempt)

    # ── instrument master ────────────────────────────────────────────────
    def sync_instruments(self, exchange: str = "NSE") -> ProviderResult:
        if exchange not in EXCHANGES:
            raise ProviderError(INVALID_REQUEST, f"unsupported exchange: {exchange}")
        request_id, requested_at = new_request_id(), utcnow()
        rows = self._call(self._client().instruments, exchange)
        received_at = utcnow()
        if not isinstance(rows, list):
            raise ProviderError(INVALID_PAYLOAD, "instrument master is not a list", raw_payload=rows)
        records = []
        for r in rows:
            try:
                records.append({
                    "instrument_token": int(r["instrument_token"]),
                    "exchange_token": str(r.get("exchange_token") or "") or None,
                    "tradingsymbol": str(r["tradingsymbol"]),
                    "name": (r.get("name") or None),
                    "exchange": str(r.get("exchange") or exchange),
                    "segment": r.get("segment"),
                    "instrument_type": r.get("instrument_type"),
                    "lot_size": r.get("lot_size"),
                    "tick_size": r.get("tick_size"),
                })
            except (KeyError, TypeError, ValueError) as e:
                raise ProviderError(INVALID_PAYLOAD, f"instrument row unreadable: {type(e).__name__}: {e}",
                                    raw_payload=rows) from e
        _instrument_cache[(exchange, received_at.astimezone(IST).date())] = _symbol_map(records, exchange)
        segments: Dict[str, int] = {}
        for rec in records:
            segments[str(rec["segment"])] = segments.get(str(rec["segment"]), 0) + 1
        return ProviderResult(
            provider_id=self.provider_id, provider_version=self.provider_version, request_id=request_id,
            requested_at=requested_at, response_received_at=received_at, instrument_identifier=exchange,
            availability_timestamp=received_at.isoformat(), normalized_records=records,
            data_quality_status=DQ_OK if records else DQ_EMPTY, error_code=None if records else EMPTY_RESPONSE,
            meta={"exchange": exchange, "by_segment": segments, "mapping_version": received_at.astimezone(IST).date().isoformat(),
                  "note": "Kite's instrument master carries no ISIN; ISIN mapping is not established by this call."},
            raw_payload=rows,
        )

    def _resolve(self, symbol: str, exchange: str) -> int:
        key = (exchange, utcnow().astimezone(IST).date())
        if key not in _instrument_cache:
            self.sync_instruments(exchange)
        token = _instrument_cache.get(key, {}).get(symbol)
        if token is None:
            raise ProviderError(IDENTIFIER_NOT_RESOLVED, f"{exchange}:{symbol} is not in Kite's instrument master")
        return token

    # ── historical candles ───────────────────────────────────────────────
    def fetch_candles(self, symbol: str, start: date, end: date, interval: str = "day",
                      exchange: str = "NSE") -> ProviderResult:
        if interval not in MAX_DAYS:
            raise ProviderError(INVALID_REQUEST, f"unsupported interval: {interval}")
        if exchange not in EXCHANGES:
            raise ProviderError(INVALID_REQUEST, f"unsupported exchange: {exchange}")
        if start > end:
            raise ProviderError(INVALID_REQUEST, "start is after end")
        request_id, requested_at = new_request_id(), utcnow()
        kc = self._client()
        token = self._resolve(symbol, exchange)

        raw: List[dict] = []
        failed: List[dict] = []
        chunks = windows(start, end, interval)
        for i, (w_start, w_end) in enumerate(chunks):
            try:
                rows = self._call(kc.historical_data, instrument_token=token, from_date=w_start, to_date=w_end,
                                  interval=interval, continuous=False, oi=False)
            except ProviderError as e:
                if e.code == AUTH_EXPIRED:      # every later window would fail the same way
                    raise
                failed.append({"start": w_start.isoformat(), "end": w_end.isoformat(), "error_code": e.code})
                continue
            raw.extend(rows or [])
            if i < len(chunks) - 1:
                self._sleep(REQ_INTERVAL)
        received_at = utcnow()
        if failed and len(failed) == len(chunks):
            raise ProviderError(failed[0]["error_code"], f"all {len(chunks)} window(s) failed for {exchange}:{symbol}")

        records, findings = _normalize_candles(raw)
        if findings.get("conflicting_duplicates") or findings.get("invalid_ohlc") or findings.get("unreadable_rows"):
            status, error_code = DQ_BLOCKED, INVALID_PAYLOAD
        elif failed:
            status, error_code = DQ_PARTIAL, PARTIAL_RESPONSE
        elif not records:
            status, error_code = DQ_EMPTY, EMPTY_RESPONSE
        else:
            status, error_code = DQ_OK, None
        last_ts = records[-1]["ts"] if records else None
        today_ist = received_at.astimezone(IST).date().isoformat()
        return ProviderResult(
            provider_id=self.provider_id, provider_version=self.provider_version, request_id=request_id,
            requested_at=requested_at, response_received_at=received_at,
            instrument_identifier=f"{exchange}:{symbol}", source_timestamp=last_ts,
            availability_timestamp=received_at.isoformat(), normalized_records=records,
            data_quality_status=status, error_code=error_code,
            retryable=bool(failed) and all(f["error_code"] in RETRYABLE for f in failed),
            meta={
                "instrument_token": token, "interval": interval,
                "requested_range": [start.isoformat(), end.isoformat()],
                "series_type": "EOD" if interval == "day" else "INTRADAY",
                "price_adjustment": "UNVERIFIED",
                "corporate_action_reconciled": False,
                "session_completeness": "UNCHECKED",
                "includes_current_session": bool(last_ts and last_ts[:10] == today_ist),
                "windows_requested": len(chunks), "failed_windows": failed, "findings": findings,
                "normalization_version": NORMALIZATION_VERSION,
            },
            raw_payload=raw,
        )


def _symbol_map(records: List[dict], exchange: str) -> Dict[str, int]:
    """tradingsymbol -> token for cash equities and indices on `exchange`."""
    return {r["tradingsymbol"]: r["instrument_token"] for r in records
            if (r["segment"] == exchange and r["instrument_type"] == "EQ") or r["segment"] == "INDICES"}


def _normalize_candles(raw: List[dict]) -> Tuple[List[dict], Dict[str, int]]:
    """Canonical bars sorted by time, plus integrity findings. Identical repeats are collapsed and
    counted; a repeated timestamp with different prices, or an impossible bar, is reported — both
    versions are dropped from the output and the caller blocks the series."""
    findings = {"duplicate_bars": 0, "conflicting_duplicates": 0, "invalid_ohlc": 0, "unreadable_rows": 0}
    by_ts: Dict[str, dict] = {}
    conflicted = set()
    for row in raw:
        try:
            ts = row["date"]
            ts = ts.isoformat() if isinstance(ts, (datetime, date)) else str(ts)
            bar = {"ts": ts, "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]),
                   "close": float(row["close"]), "volume": int(row.get("volume") or 0)}
        except (KeyError, TypeError, ValueError):
            findings["unreadable_rows"] += 1
            continue
        if not (bar["low"] > 0 and bar["high"] >= max(bar["open"], bar["close"])
                and bar["low"] <= min(bar["open"], bar["close"])):
            findings["invalid_ohlc"] += 1
            continue
        seen = by_ts.get(ts)
        if seen is None:
            by_ts[ts] = bar
        elif seen == bar:
            findings["duplicate_bars"] += 1
        else:
            findings["conflicting_duplicates"] += 1
            conflicted.add(ts)
    records = [by_ts[ts] for ts in sorted(by_ts) if ts not in conflicted]
    return records, findings
