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


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("NIVESH_TEST_BASE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def admin_token() -> str:
    return os.environ.get(
        "NIVESH_TEST_ADMIN_TOKEN",
        # Dev-default — overridden in CI via NIVESH_TEST_ADMIN_TOKEN.
        "370eff71-fda1-46d8-b506-b81b894d634f",
    )


@pytest.fixture(scope="session")
def user_token() -> str:
    return os.environ.get(
        "NIVESH_TEST_USER_TOKEN",
        "5770bebb-8a9a-41f7-a7b9-e8152ac25daa",
    )


@pytest.fixture(scope="session")
def admin_email() -> str:
    return os.environ.get("NIVESH_TEST_ADMIN_EMAIL", "priyankamantri@gmail.com")


@pytest.fixture(scope="session")
def user_email() -> str:
    return os.environ.get("NIVESH_TEST_USER_EMAIL", "aporwal107@gmail.com")
