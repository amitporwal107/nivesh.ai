"""Unit tests for OpenAI key resolution (NFR-09). No network, no GSM.

This exists because the contract was documented and then not followed: _llm.py
said "every specialist node must use this rather than reading os.environ
directly", six modules read os.environ anyway, and after the key was rotated in
GSM the vision tier kept sending the stale env key and 401'd on every page —
silently, because the tier is graceful by design.
"""
from __future__ import annotations

import sys
import types

import pytest

from nidp.shared import openai_key


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Never let a real helpers.* on the path decide these tests.
    monkeypatch.delitem(sys.modules, "helpers", raising=False)
    monkeypatch.delitem(sys.modules, "helpers.gsm", raising=False)
    monkeypatch.delitem(sys.modules, "helpers.secrets", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


def _install(gsm_value=None, secrets_value=None, gsm_raises=False):
    """Fake the helpers package so resolution order is observable."""
    pkg = types.ModuleType("helpers")
    pkg.__path__ = []
    gsm = types.ModuleType("helpers.gsm")
    secrets = types.ModuleType("helpers.secrets")

    def gsm_get(name):
        if gsm_raises:
            raise RuntimeError("no GCP credentials on this box")
        return gsm_value if name == "OPENAI_API_KEY" else None

    gsm.get = gsm_get
    secrets.get = lambda name: secrets_value if name == "OPENAI_API_KEY" else None
    pkg.gsm, pkg.secrets = gsm, secrets
    sys.modules["helpers"] = pkg
    sys.modules["helpers.gsm"] = gsm
    sys.modules["helpers.secrets"] = secrets


def test_gsm_wins_over_env__the_rotation_bug():
    # THE regression: key rotated in GSM, stale key still in nidp.env.
    # Reading env gave the stale key and every vision call 401'd.
    _install(gsm_value="sk-rotated-in-gsm")
    import os
    os.environ["OPENAI_API_KEY"] = "sk-stale-in-env-file"
    assert openai_key.get_openai_api_key() == "sk-rotated-in-gsm"


def test_gsm_wins_over_admin_override():
    _install(gsm_value="sk-from-gsm", secrets_value="sk-from-admin-db")
    assert openai_key.get_openai_api_key() == "sk-from-gsm"


def test_falls_back_to_admin_override_when_gsm_empty():
    _install(gsm_value=None, secrets_value="sk-from-admin-db")
    assert openai_key.get_openai_api_key() == "sk-from-admin-db"


def test_falls_back_to_env_when_gsm_and_admin_empty(monkeypatch):
    _install(gsm_value=None, secrets_value=None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert openai_key.get_openai_api_key() == "sk-from-env"


def test_gsm_unavailable_does_not_raise__local_dev_still_boots(monkeypatch):
    # No GCP credentials (local dev, no SA mounted) must fall through, not crash.
    _install(gsm_raises=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert openai_key.get_openai_api_key() == "sk-from-env"


def test_no_helpers_package_at_all_falls_back_to_env(monkeypatch):
    # nidp must remain importable/runnable without the app's helpers package.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert openai_key.get_openai_api_key() == "sk-from-env"


def test_returns_empty_string_when_nothing_configured():
    _install(gsm_value=None, secrets_value=None)
    assert openai_key.get_openai_api_key() == ""
    assert openai_key.openai_configured() is False


def test_openai_configured_is_true_when_gsm_has_it():
    _install(gsm_value="sk-x")
    assert openai_key.openai_configured() is True


def test_llm_module_delegates_to_the_shared_resolver():
    # One implementation, not two that can drift apart.
    _install(gsm_value="sk-shared")
    from nidp.services.copilot_agent._llm import get_openai_api_key as llm_resolve
    assert llm_resolve() == "sk-shared"
