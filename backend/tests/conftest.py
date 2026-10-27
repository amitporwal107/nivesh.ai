"""Shared pytest fixtures — centralises test credentials + backend URL.

Credentials are loaded from env vars so they aren't hardcoded in tests:
    NIVESH_TEST_ADMIN_TOKEN
    NIVESH_TEST_USER_TOKEN
    NIVESH_TEST_ADMIN_EMAIL
    NIVESH_TEST_USER_EMAIL
    NIVESH_TEST_BASE_URL   (default: http://localhost:8001)

Defaults come from /app/backend/.env + /app/memory/test_credentials.md so
developers don't need to export anything locally, but CI / prod pipelines
must provide the real values via environment.
"""
import os
import pytest

# Load backend .env first so MONGO_URL / DB_NAME are available.
_ENV_PATH = "/app/backend/.env"
if os.path.exists(_ENV_PATH):
    for _line in open(_ENV_PATH):
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k, _v.strip('"'))

# Dev-default tokens — injected if no env var is set. This keeps dev test
# runs working without exposing the literal token in individual test files.
# CI / prod override via NIVESH_TEST_*_TOKEN env vars.
os.environ.setdefault("NIVESH_TEST_ADMIN_TOKEN", "370eff71-fda1-46d8-b506-b81b894d634f")
os.environ.setdefault("NIVESH_TEST_USER_TOKEN", "5770bebb-8a9a-41f7-a7b9-e8152ac25daa")
os.environ.setdefault("NIVESH_TEST_ADMIN_EMAIL", "priyankamantri@gmail.com")
os.environ.setdefault("NIVESH_TEST_USER_EMAIL", "aporwal107@gmail.com")
os.environ.setdefault("NIVESH_TEST_BASE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ["NIVESH_TEST_BASE_URL"]


@pytest.fixture(scope="session")
def admin_token() -> str:
    return os.environ["NIVESH_TEST_ADMIN_TOKEN"]


@pytest.fixture(scope="session")
def user_token() -> str:
    return os.environ["NIVESH_TEST_USER_TOKEN"]


@pytest.fixture(scope="session")
def admin_email() -> str:
    return os.environ["NIVESH_TEST_ADMIN_EMAIL"]


@pytest.fixture(scope="session")
def user_email() -> str:
    return os.environ["NIVESH_TEST_USER_EMAIL"]


# ── the universal risk service's server-resolved inputs (services/risk_gate/inputs.py) ──────────────────────────
# MOCK — not real data. Every desk / journal / AI-trader route now asks the risk service, which reads the sector
# (index_constituents) and the market state (the desk regime) on the server and BLOCKS when either is unknown. Unit
# tests have no data platform, so by default they get a known sector and a fresh, calm market state, dated at the
# reference session of whatever clock the test fixed (services/desk_trading.utcnow). The instrument's bars are NOT
# faked here: they come from each harness's own fake data platform, and fail closed without one.
# Tests of the fail-closed paths override `risk_mock_inputs` (tests/test_risk_service.py).
RISK_MOCK_SECTOR = "MOCK Sector"


@pytest.fixture(autouse=True)
def risk_mock_inputs(monkeypatch):
    try:
        from services import data_freshness as fresh
        from services import desk_trading as desk
        from services.risk_gate import inputs
    except Exception:  # noqa: BLE001 — a suite that cannot import the backend has nothing to patch
        yield None
        return
    state = {"sector": RISK_MOCK_SECTOR, "sectors": {}, "vix": 14.0, "regime": "BULL", "market_error": None,
             "market_as_of": None}

    async def sector_of(symbol):
        sector = state["sectors"].get(str(symbol).upper(), state["sector"])
        return {"sector": sector, "as_of": None, "source": "MOCK sector (tests/conftest.py)",
                "error": None if sector else f"{symbol} is on none of the MOCK lists"}

    async def market_state():
        if state["market_error"]:
            return {"vix": None, "regime": None, "as_of": None, "key": None, "source": "MOCK", "error": state["market_error"]}
        as_of = state["market_as_of"] or fresh.reference_session(desk.utcnow()).isoformat()
        return {"vix": state["vix"], "regime": state["regime"], "as_of": as_of, "key": "mock", "source": "MOCK regime",
                "error": None}

    monkeypatch.setattr(inputs, "sector_of", sector_of)
    monkeypatch.setattr(inputs, "market_state", market_state)
    yield state
