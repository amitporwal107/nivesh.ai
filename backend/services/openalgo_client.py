"""OpenAlgo REST adapter for Nivesh Secure Portfolio Connect.

OpenAlgo (https://github.com/marketcalls/openalgo) is a self-hosted
broker-API middleware that exposes a unified REST surface for 30+ Indian
brokers. We use it read-only — holdings + positions + funds — and never
place orders. Per-user OpenAlgo API keys are stored AES-256-GCM encrypted
via `services.pii_security`.

This module is the thin adapter:

    client = OpenAlgoClient(base_url="http://...", api_key="...")
    healthy, msg = client.health_check()
    rows = client.fetch_normalized_holdings()  # list[dict] in Nivesh shape

The output of `fetch_normalized_holdings()` matches the canonical holding
schema used by `helpers.parsing.save_holdings()` so broker-imported rows
pass through the same persistence + enrichment as CAS or Excel imports.

Auth model — OpenAlgo accepts the API key as a JSON body field named
`apikey` on every endpoint (no Authorization header). All endpoints are
POST. Responses come back as `{status: "success" | "error", data: {...}}`.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15  # seconds; OpenAlgo holdings calls usually return in <2s

# Broker → display name mapping. Keys MUST match OpenAlgo's broker-plugin
# directory names (under /app/openalgo/broker/) — those are what OpenAlgo's
# REDIRECT_URL parser, plugin loader, and broker-callback router accept.
# Mismatches surface as "Broker authentication function not found." 500s.
#
# A single OpenAlgo deployment is configured for ONE broker at a time
# (REDIRECT_URL + BROKER_API_KEY env vars). The user-facing dropdown
# below lists everything OpenAlgo *can* serve; whichever the operator's
# OpenAlgo instance is currently configured for is the only one that
# completes the OAuth round-trip. Future multi-broker support requires
# either per-user OpenAlgo containers or an OpenAlgo fork.
SUPPORTED_BROKERS: Dict[str, str] = {
    "zerodha": "Zerodha",
    "angel": "Angel One",
    "upstox": "Upstox",
    "groww": "Groww",
    "fyers": "Fyers",
    "dhan": "Dhan",
    "kotak": "Kotak Neo",
    "shoonya": "Shoonya",
    "aliceblue": "AliceBlue",
    "iifl": "IIFL",
    "iiflcapital": "IIFL Capital",
    "motilal": "Motilal Oswal",
    "samco": "Samco",
    "paytm": "Paytm Money",
    "fivepaisa": "5paisa",
    "flattrade": "Flattrade",
    "definedge": "Definedge",
    "tradejini": "Tradejini",
    "indmoney": "INDmoney",
    "mstock": "m.Stock",
}

# OpenAlgo `product` codes → Nivesh asset_type. CNC (Cash & Carry) and
# DELIVERY are long-side equity holdings; MIS is intraday and skipped.
_PRODUCT_TO_ASSET_TYPE: Dict[str, str] = {
    "CNC": "equity",
    "DELIVERY": "equity",
    "NRML": "equity",
    "MIS": "equity",  # Intraday — caller decides whether to drop.
    "MTF": "equity",
}

# Symbol → asset_type override based on common ETF / gold-ETF naming.
_ETF_NAME_RE = re.compile(r"\b(ETF|BeES|GOLDBEES|LIQUIDBEES|NIFTY1D)\b", re.I)


class OpenAlgoError(Exception):
    """Raised for any non-success response from OpenAlgo."""


class OpenAlgoClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # ── Low-level HTTP ──────────────────────────────────────────────────
    def _post(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.post(
                url,
                json={"apikey": self.api_key},
                timeout=self.timeout,
                headers={"User-Agent": "Nivesh-SPC/1.0"},
            )
        except requests.RequestException as e:
            raise OpenAlgoError(f"network error contacting OpenAlgo: {e}") from e

        if resp.status_code >= 500:
            raise OpenAlgoError(f"OpenAlgo {resp.status_code} server error at {path}")
        if resp.status_code in (401, 403):
            raise OpenAlgoError("OpenAlgo rejected the API key (auth failure)")
        if resp.status_code >= 400:
            raise OpenAlgoError(f"OpenAlgo {resp.status_code}: {resp.text[:200]}")

        try:
            body = resp.json()
        except ValueError as e:
            raise OpenAlgoError(f"OpenAlgo returned non-JSON: {e}") from e

        if isinstance(body, dict) and body.get("status") == "error":
            msg = body.get("message") or body.get("error") or "unknown OpenAlgo error"
            raise OpenAlgoError(f"OpenAlgo error: {msg}")
        return body

    # ── Health check ────────────────────────────────────────────────────
    def health_check(self) -> Tuple[bool, str]:
        """Return (ok, message). Calls /api/v1/funds because it's the
        cheapest endpoint that exercises both reachability and key auth.
        Never raises — converts every error path to (False, msg) for the
        connect-route UX.
        """
        try:
            body = self._post("/api/v1/funds")
        except OpenAlgoError as e:
            return False, str(e)
        except Exception as e:  # noqa: BLE001
            return False, f"unexpected error: {e}"
        if not isinstance(body, dict):
            return False, "OpenAlgo returned unexpected payload shape"
        return True, "ok"

    # ── Holdings ────────────────────────────────────────────────────────
    def fetch_holdings_raw(self) -> List[Dict[str, Any]]:
        body = self._post("/api/v1/holdings")
        data = (body.get("data") or {}) if isinstance(body, dict) else {}
        # OpenAlgo response shape: {data: {holdings: [...], statistics: {...}}}
        rows = data.get("holdings") if isinstance(data, dict) else None
        if rows is None and isinstance(data, list):
            rows = data
        return list(rows or [])

    def fetch_positions_raw(self) -> List[Dict[str, Any]]:
        body = self._post("/api/v1/positionbook")
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("positions") or [])
        return []

    def fetch_funds_raw(self) -> Dict[str, Any]:
        body = self._post("/api/v1/funds")
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else {}

    # ── Normalisation to Nivesh holding schema ──────────────────────────
    def fetch_normalized_holdings(self) -> List[Dict[str, Any]]:
        """Return broker holdings shaped for `helpers.parsing.save_holdings`.

        We merge OpenAlgo's holdings (which lack avg_price) with the
        positionbook (which has it) by (exchange, symbol). Symbols stay
        in `ticker` — the existing enrichment pipeline maps NSE symbols
        to ISIN via `data/equity_list.csv`.
        """
        holdings = self.fetch_holdings_raw()
        positions = self.fetch_positions_raw()

        # Build (exchange, symbol) → avg_price lookup from positionbook.
        avg_by_key: Dict[Tuple[str, str], float] = {}
        for p in positions:
            ex = str(p.get("exchange") or "").upper()
            sym = str(p.get("symbol") or "").upper()
            ap = _to_float(p.get("average_price") or p.get("averageprice") or p.get("avg_price"))
            if ex and sym and ap > 0:
                avg_by_key[(ex, sym)] = ap

        out: List[Dict[str, Any]] = []
        for h in holdings:
            sym = str(h.get("symbol") or "").upper().strip()
            if not sym:
                continue
            ex = str(h.get("exchange") or "").upper()
            qty = _to_float(h.get("quantity") or h.get("qty"))
            if qty <= 0:
                continue
            product = str(h.get("product") or "").upper()
            ltp = _to_float(h.get("ltp") or h.get("last_price") or h.get("close"))
            pnl = _to_float(h.get("pnl") or h.get("profitandloss"))
            avg_price = avg_by_key.get((ex, sym), 0.0)
            # Fallback: derive avg from LTP and PnL when positionbook misses.
            if avg_price <= 0 and ltp > 0 and qty > 0:
                avg_price = ltp - (pnl / qty if qty > 0 else 0.0)
                if avg_price <= 0:
                    avg_price = ltp  # Pessimistic but stable.

            asset_type = _PRODUCT_TO_ASSET_TYPE.get(product, "equity")
            if _ETF_NAME_RE.search(sym) or _ETF_NAME_RE.search(str(h.get("tradingsymbol") or "")):
                asset_type = "etf"

            out.append({
                "name": str(h.get("tradingsymbol") or h.get("symbol") or sym).strip(),
                "ticker": sym,
                "asset_type": asset_type,
                "quantity": qty,
                "buy_price": round(avg_price, 4) if avg_price > 0 else 0.0,
                "current_price": round(ltp, 4) if ltp > 0 else 0.0,
                "sector": "Other",
                "source": "openalgo",
                "source_id": f"{ex}:{sym}" if ex else sym,
            })
        return out


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def mask_api_key(key: str) -> str:
    """First-4 + last-4 readback for UI/audit. Returns '' for empty."""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 6}{key[-4:]}"
