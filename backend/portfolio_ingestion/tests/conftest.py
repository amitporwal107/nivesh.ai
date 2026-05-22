"""Pytest fixtures for portfolio_ingestion.

Kept minimal in this first slice — only the FastAPI TestClient. Integration
fixtures (asyncpg pool, throwaway schema, mock GCS) land alongside T1.2+.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from portfolio_ingestion.config import reset_settings_for_test
from portfolio_ingestion.main import create_app


@pytest.fixture
def tmp_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    reset_settings_for_test()
    app = create_app()
    return TestClient(app)
