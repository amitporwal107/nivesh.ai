"""Regression tests for DaaS API-key resolution across every caller.

Pure-Python; no DB, no network.

Why this exists — measured on staging 2026-08-18:
  • ``nivesh-staging-app-backend`` has ``NIDP_DAAS_INTERNAL_TOKEN`` set and
    ``NIDP_DAAS_API_KEY`` EMPTY.
  • Callers that read ``NIDP_DAAS_API_KEY`` only therefore resolved to ``""``
    and silently returned ``None`` for every DaaS call — while the staging DaaS
    itself was healthy and answering 200s for the callers that accept either.

The contract these tests pin: **every** DaaS caller resolves its key as
``NIDP_DAAS_API_KEY or NIDP_DAAS_INTERNAL_TOKEN``, so a deployment that sets
either variable authenticates.
"""
from __future__ import annotations

import importlib
import os

import pytest


# (module path, attribute or None) — None means the key is resolved inside the
# request function rather than at import time, so we assert on the source.
_SOURCE_CALLERS = [
    "backend/services/copilot_tools/stock_intelligence.py",
    "backend/services/copilot_tools/mf_intelligence.py",
    "backend/routes/copilot_widgets.py",
]

_ENV_VARS = ("NIDP_DAAS_API_KEY", "NIDP_DAAS_INTERNAL_TOKEN")


@pytest.fixture
def clean_env(monkeypatch):
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def _repo_root() -> str:
    # backend/tests/ -> repo root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.mark.parametrize("relpath", _SOURCE_CALLERS)
def test_every_daas_caller_accepts_either_env_var(relpath):
    """Drift guard: no caller may read NIDP_DAAS_API_KEY in isolation.

    A caller that reads only NIDP_DAAS_API_KEY is dead on any deployment that
    registers the credential as NIDP_DAAS_INTERNAL_TOKEN (which staging does).
    """
    path = os.path.join(_repo_root(), relpath)
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()

    assert "NIDP_DAAS_API_KEY" in src, f"{relpath} no longer reads the DaaS key at all"
    assert "NIDP_DAAS_INTERNAL_TOKEN" in src, (
        f"{relpath} reads NIDP_DAAS_API_KEY but not NIDP_DAAS_INTERNAL_TOKEN — "
        "it will resolve to an empty key on staging and silently return no data"
    )


def test_copilot_widgets_key_resolves_from_internal_token(clean_env):
    """copilot_widgets resolves its module-level key at import time."""
    pytest.importorskip("fastapi", reason="app deps not installed in this environment")
    clean_env.setenv("NIDP_DAAS_INTERNAL_TOKEN", "tok-internal")
    import routes.copilot_widgets as cw

    importlib.reload(cw)
    assert cw._DAAS_KEY == "tok-internal"


def test_copilot_widgets_api_key_wins_when_both_set(clean_env):
    pytest.importorskip("fastapi", reason="app deps not installed in this environment")
    clean_env.setenv("NIDP_DAAS_API_KEY", "tok-api")
    clean_env.setenv("NIDP_DAAS_INTERNAL_TOKEN", "tok-internal")
    import routes.copilot_widgets as cw

    importlib.reload(cw)
    assert cw._DAAS_KEY == "tok-api"


def test_copilot_widgets_key_empty_when_neither_set(clean_env):
    pytest.importorskip("fastapi", reason="app deps not installed in this environment")
    import routes.copilot_widgets as cw

    importlib.reload(cw)
    assert cw._DAAS_KEY == ""
