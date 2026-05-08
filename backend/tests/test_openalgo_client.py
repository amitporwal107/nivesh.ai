"""Unit tests for `services.openalgo_client`.

Pure offline tests — every HTTP call is intercepted by monkey-patching
`requests.post`. Verifies:

  - Auth model (apikey in JSON body)
  - Health-check pass / fail / network error / OpenAlgo "error" payload
  - Holdings + positions normalisation into the Nivesh schema
  - avg_price merge from positionbook into holdings
  - ETF detection by symbol
  - Skipping zero-quantity / no-symbol rows
  - mask_api_key behaviour
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "/app/backend")

from services import openalgo_client as oa  # noqa: E402
from services.openalgo_client import (  # noqa: E402
    OpenAlgoClient,
    OpenAlgoError,
    SUPPORTED_BROKERS,
    mask_api_key,
)


# ── Test double for requests.post ───────────────────────────────────────
class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self) -> Any:
        return self._payload


class _Recorder:
    def __init__(self, route_to_resp: Dict[str, _FakeResponse]):
        self.route_to_resp = route_to_resp
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url, json=None, timeout=None, headers=None):
        path = "/" + url.split("/api/")[1] if "/api/" in url else url
        path = path.replace("/", "/", 1)  # cosmetic — keep as-is
        # Trim path to "/api/v1/..." so test routes can match.
        if "/api/" in url:
            path = "/api" + url.split("/api", 1)[1]
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        # Default response if not configured: 200 with empty body.
        return self.route_to_resp.get(path, _FakeResponse(200, {"status": "success", "data": {}}))


@pytest.fixture
def patch_post(monkeypatch):
    def _install(routes: Dict[str, _FakeResponse]) -> _Recorder:
        rec = _Recorder(routes)
        monkeypatch.setattr(oa.requests, "post", rec)
        return rec
    return _install


# ── Health check ────────────────────────────────────────────────────────
def test_health_check_ok(patch_post):
    rec = patch_post({
        "/api/v1/funds": _FakeResponse(200, {"status": "success", "data": {"availablecash": 1000}}),
    })
    c = OpenAlgoClient("http://oa.local:5000", "secret")
    ok, msg = c.health_check()
    assert ok is True
    assert msg == "ok"
    # Ensure auth was sent in JSON body, never as a header.
    assert rec.calls[0]["json"] == {"apikey": "secret"}
    assert "Authorization" not in (rec.calls[0]["headers"] or {})


def test_health_check_auth_failure(patch_post):
    patch_post({"/api/v1/funds": _FakeResponse(401, {}, text="unauthorized")})
    ok, msg = OpenAlgoClient("http://oa.local", "bad").health_check()
    assert ok is False
    assert "auth" in msg.lower() or "rejected" in msg.lower()


def test_health_check_openalgo_error_payload(patch_post):
    patch_post({"/api/v1/funds": _FakeResponse(200, {"status": "error", "message": "bad key"})})
    ok, msg = OpenAlgoClient("http://oa.local", "k").health_check()
    assert ok is False
    assert "bad key" in msg


def test_health_check_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise oa.requests.ConnectionError("no route to host")
    monkeypatch.setattr(oa.requests, "post", boom)
    ok, msg = OpenAlgoClient("http://oa.local", "k").health_check()
    assert ok is False
    assert "network" in msg.lower()


# ── Holdings + positions → normalised rows ──────────────────────────────
def test_fetch_normalized_holdings_basic(patch_post):
    holdings_payload = {
        "status": "success",
        "data": {
            "holdings": [
                {
                    "exchange": "NSE", "symbol": "INFY", "tradingsymbol": "INFY",
                    "quantity": 35, "product": "CNC", "ltp": 1300.50, "pnl": 5000,
                },
                {
                    "exchange": "NSE", "symbol": "RELIANCE", "tradingsymbol": "RELIANCE",
                    "quantity": 30, "product": "CNC", "ltp": 1394.30, "pnl": 0,
                },
                # ETF row — name pattern wins over `product`.
                {
                    "exchange": "NSE", "symbol": "GOLDBEES", "tradingsymbol": "GOLDBEES",
                    "quantity": 100, "product": "CNC", "ltp": 131.64, "pnl": 0,
                },
            ],
            "statistics": {"totalholdingvalue": 100000},
        },
    }
    positions_payload = {
        "status": "success",
        "data": [
            {"exchange": "NSE", "symbol": "INFY", "average_price": 1200.00, "quantity": 35},
            # RELIANCE intentionally absent — exercises LTP-PnL fallback.
            {"exchange": "NSE", "symbol": "GOLDBEES", "average_price": 130.00, "quantity": 100},
        ],
    }
    patch_post({
        "/api/v1/holdings": _FakeResponse(200, holdings_payload),
        "/api/v1/positionbook": _FakeResponse(200, positions_payload),
    })
    rows = OpenAlgoClient("http://oa.local", "k").fetch_normalized_holdings()
    assert len(rows) == 3
    by_sym = {r["ticker"]: r for r in rows}

    infy = by_sym["INFY"]
    assert infy["asset_type"] == "equity"
    assert infy["quantity"] == 35
    # avg_price merged from positionbook
    assert infy["buy_price"] == 1200.00
    assert infy["current_price"] == 1300.50
    assert infy["source"] == "openalgo"
    assert infy["source_id"] == "NSE:INFY"

    rel = by_sym["RELIANCE"]
    # PnL == 0 → buy_price ≈ ltp
    assert rel["asset_type"] == "equity"
    assert abs(rel["buy_price"] - 1394.30) < 1e-6

    gold = by_sym["GOLDBEES"]
    assert gold["asset_type"] == "etf"  # name-based override
    assert gold["buy_price"] == 130.00


def test_fetch_normalized_holdings_skips_zero_qty(patch_post):
    patch_post({
        "/api/v1/holdings": _FakeResponse(200, {
            "status": "success",
            "data": {"holdings": [
                {"exchange": "NSE", "symbol": "INFY", "quantity": 0, "ltp": 1300},
                {"exchange": "NSE", "symbol": "", "quantity": 10, "ltp": 100},
                {"exchange": "NSE", "symbol": "TCS", "quantity": 5, "ltp": 3000},
            ]},
        }),
        "/api/v1/positionbook": _FakeResponse(200, {"status": "success", "data": []}),
    })
    rows = OpenAlgoClient("http://oa.local", "k").fetch_normalized_holdings()
    assert [r["ticker"] for r in rows] == ["TCS"]


def test_fetch_normalized_holdings_handles_list_data(patch_post):
    """OpenAlgo occasionally returns the holdings list directly under
    `data` rather than `data.holdings`. The client must accept both."""
    patch_post({
        "/api/v1/holdings": _FakeResponse(200, {
            "status": "success",
            "data": [
                {"exchange": "NSE", "symbol": "INFY", "quantity": 10, "ltp": 1000},
            ],
        }),
        "/api/v1/positionbook": _FakeResponse(200, {"status": "success", "data": []}),
    })
    rows = OpenAlgoClient("http://oa.local", "k").fetch_normalized_holdings()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "INFY"


# ── Constructor validation + helpers ────────────────────────────────────
def test_constructor_requires_url_and_key():
    with pytest.raises(ValueError):
        OpenAlgoClient("", "k")
    with pytest.raises(ValueError):
        OpenAlgoClient("http://x", "")


def test_supported_brokers_present():
    # Slugs MUST match OpenAlgo's broker-plugin directory names (under
    # /app/openalgo/broker/) — not arbitrary marketing names. Mismatches
    # surface as "Broker authentication function not found" 500s when
    # the user redirects through OpenAlgo's broker callback router.
    # ICICI Direct is intentionally absent: OpenAlgo has no plugin for it.
    for slug in ("zerodha", "angel", "upstox", "groww", "fyers", "dhan"):
        assert slug in SUPPORTED_BROKERS, f"missing required broker: {slug}"
    # Sanity: nothing OpenAlgo-incompatible leaked back in.
    for bad in ("icicidirect", "angelone", "kotakneo"):
        assert bad not in SUPPORTED_BROKERS, (
            f"{bad!r} is not an OpenAlgo plugin slug — would 500 at callback"
        )


def test_mask_api_key_short_and_long():
    assert mask_api_key("") == ""
    assert mask_api_key("abcdef") == "•" * 6
    assert mask_api_key("abcd1234efgh5678") == "abcd••••••5678"


def test_openalgo_500_raises(patch_post):
    patch_post({"/api/v1/holdings": _FakeResponse(503, {}, text="upstream broker down")})
    c = OpenAlgoClient("http://x", "k")
    with pytest.raises(OpenAlgoError) as ei:
        c.fetch_holdings_raw()
    assert "503" in str(ei.value) or "server" in str(ei.value).lower()
