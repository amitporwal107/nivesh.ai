"""Unit tests for helpers/openai_key.py — the shared OpenAI key resolver.

No network, no GSM, no DB. helpers.gsm / helpers.secrets are faked so the
resolution order is observable.

This module is the fix for a real incident: the key was rotated in Secret
Manager, fourteen call sites across the app and nidp read os.environ instead,
and the vision tier 401'd on every page — silently, because it degrades
gracefully. The first test below is that bug.
"""
from __future__ import annotations

import sys
import types

import pytest

from helpers import openai_key


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delitem(sys.modules, "helpers.gsm", raising=False)
    monkeypatch.delitem(sys.modules, "helpers.secrets", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


def _fake(gsm_value=None, admin_value=None, gsm_raises=False):
    gsm = types.ModuleType("helpers.gsm")
    secrets = types.ModuleType("helpers.secrets")

    def _gsm_get(name):
        if gsm_raises:
            raise RuntimeError("no GCP credentials on this box")
        return gsm_value if name == "OPENAI_API_KEY" else None

    gsm.get = _gsm_get
    secrets.get = lambda name: (admin_value or "") if name == "OPENAI_API_KEY" else ""
    sys.modules["helpers.gsm"] = gsm
    sys.modules["helpers.secrets"] = secrets


def test_gsm_beats_a_stale_env_key__the_incident():
    # Exactly what happened: rotated in GSM, stale value still in nidp.env.
    _fake(gsm_value="sk-rotated-in-gsm")
    import os
    os.environ["OPENAI_API_KEY"] = "sk-stale-in-env-file"
    assert openai_key.get_openai_api_key() == "sk-rotated-in-gsm"
    assert openai_key.source_of_key() == "gsm"


def test_gsm_beats_admin_override():
    _fake(gsm_value="sk-gsm", admin_value="sk-admin")
    assert openai_key.get_openai_api_key() == "sk-gsm"


def test_admin_override_used_when_gsm_empty():
    _fake(gsm_value=None, admin_value="sk-admin")
    assert openai_key.get_openai_api_key() == "sk-admin"
    assert openai_key.source_of_key() == "admin"


def test_env_used_when_gsm_and_admin_empty(monkeypatch):
    _fake(gsm_value=None, admin_value=None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert openai_key.get_openai_api_key() == "sk-env"
    assert openai_key.source_of_key() == "env"


def test_missing_gcp_credentials_does_not_raise(monkeypatch):
    # Local dev with no SA mounted must fall through, not crash the process.
    _fake(gsm_raises=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert openai_key.get_openai_api_key() == "sk-env"


def test_nothing_configured_returns_empty_not_none():
    # Callers do `if not key: skip`. None would break `.strip()` on the way in.
    _fake(gsm_value=None, admin_value=None)
    assert openai_key.get_openai_api_key() == ""
    assert openai_key.openai_configured() is False
    assert openai_key.source_of_key() is None


def test_whitespace_is_stripped():
    # A trailing newline from `echo key | gcloud secrets create` is a 401 that
    # looks exactly like a wrong key.
    _fake(gsm_value="  sk-padded\n")
    assert openai_key.get_openai_api_key() == "sk-padded"


def test_nidp_shim_resolves_through_the_same_helpers_implementation():
    _fake(gsm_value="sk-shared")
    from nidp.shared.openai_key import get_openai_api_key as nidp_resolve
    assert nidp_resolve() == "sk-shared"


def test_nidp_shim_falls_back_to_env_without_the_helpers_package(monkeypatch):
    # nidp must stay runnable in a bare checkout with no app helpers on the path.
    monkeypatch.setitem(sys.modules, "helpers.openai_key", None)  # force ImportError
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-only")
    from nidp.shared.openai_key import get_openai_api_key as nidp_resolve
    assert nidp_resolve() == "sk-env-only"
