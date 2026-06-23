"""Regression guard for the advisor-vs-client copilot mode switch.

Bug (fixed 2026-06-24): the copilot decided "am I impersonating a client?"
by comparing the effective and session user-ids. That works for CLIENT
profiles (distinct shadow_user_id) but BREAKS for the advisor's own SELF
profile, whose shadow_user_id == the advisor's own user_id. Result: when an
advisor who is *their own client* opened their own portfolio, the copilot kept
showing the cross-client advisor questionnaire instead of the personal one.

The fix keys both detectors off the session's ``active_profile_id`` (set the
moment any profile — SELF or CLIENT — is opened) rather than the id compare.
These tests pin that behaviour for both detectors.

Pure-logic tests: the workspace lookup is stubbed, so no DB/LLM is needed.
Skipped automatically if the app's runtime deps aren't importable (e.g. on a
data-platform box without fastapi/motor installed).
"""
from __future__ import annotations

import asyncio

import pytest

try:  # the route modules need the app runtime (fastapi/motor) to import
    from routes.copilot_prompts import _is_advisor_mode
    from routes.copilot import _is_advisor_caller
    import routes.copilot_prompts as _cp
    import routes.copilot as _co
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"app runtime not importable here: {exc}", allow_module_level=True)


class _FakeColl:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, *_a, **_k):
        return self._doc


class _FakeDB:
    def __init__(self, ws_doc):
        self.workspaces = _FakeColl(ws_doc)


_ADVISORY = {"type": "ADVISORY"}
_INDIVIDUAL = {"type": "INDIVIDUAL"}


# (active_profile_id, workspace_doc, expected_advisor_mode)
_CASES = [
    ("root_no_profile_advisory",        None,         _ADVISORY,   True),   # workspace root → advisor tiles
    ("impersonating_self_profile",      "self_pid",   _ADVISORY,   False),  # the bug: SELF → must be client tiles
    ("impersonating_client_profile",    "client_pid", _ADVISORY,   False),  # CLIENT → client tiles
    ("empty_active_id_is_root",         "",           _ADVISORY,   True),   # falsy id == root
    ("individual_workspace_root",       None,         _INDIVIDUAL, False),  # non-advisory → never advisor mode
    ("no_workspace_root",               None,         None,        False),  # no workspace → never advisor mode
]


@pytest.mark.parametrize("label,active_profile_id,ws_doc,expected", _CASES)
def test_is_advisor_mode_keys_off_active_profile(monkeypatch, label, active_profile_id, ws_doc, expected):
    monkeypatch.setattr(_cp, "db", _FakeDB(ws_doc))
    got = asyncio.run(_is_advisor_mode("advisor_uid", active_profile_id))
    assert got is expected, f"{label}: _is_advisor_mode → {got}, expected {expected}"


@pytest.mark.parametrize("label,active_profile_id,ws_doc,expected", _CASES)
def test_is_advisor_caller_keys_off_active_profile(monkeypatch, label, active_profile_id, ws_doc, expected):
    monkeypatch.setattr(_co, "db", _FakeDB(ws_doc))
    got = asyncio.run(_is_advisor_caller("advisor_uid", active_profile_id))
    assert got is expected, f"{label}: _is_advisor_caller → {got}, expected {expected}"
