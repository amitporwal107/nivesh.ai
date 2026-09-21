"""The Charts research surface serves Kite-derived prices, so it must never be open to everyone (NI-1)."""
import feature_flags as ff


def test_charting_flag_is_allowlist_only_by_default():
    spec = ff.KNOWN_FEATURES["charting"]
    assert spec["default_mode"] == "allowlist"
    assert spec["allowed_modes"] == ["off", "allowlist"]
    assert "everyone" not in spec["allowed_modes"]


def test_charting_flag_matches_sim_lab_licensing_posture():
    # Same data-licensing constraint as the Simulation Lab: internal Kite-derived prices.
    assert ff.KNOWN_FEATURES["charting"]["allowed_modes"] == ff.KNOWN_FEATURES["sim_lab"]["allowed_modes"]



class _FakeCollection:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, *_args, **_kwargs):
        return self._doc


class _FakeDb:
    def __init__(self, doc):
        self.system_config = _FakeCollection(doc)


def test_persisted_everyone_is_read_as_off_for_charting():
    # A stale or hand-edited 'everyone' in the DB must not open Kite-derived charts to all users.
    import asyncio
    persisted = {"key": "feature_flags",
                 "flags": {"charting": {"mode": "everyone", "allowlist": []}}}
    saved = {k: dict(v) for k, v in ff._flags.items()}
    try:
        asyncio.run(ff.hydrate_from_db(_FakeDb(persisted)))
        assert ff._flags["charting"]["mode"] == "off"          # downgraded, fail closed
        assert ff.is_enabled("charting", "someone.else@example.com") is False
    finally:
        ff._flags.clear()
        ff._flags.update(saved)


def test_setting_everyone_on_charting_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        ff.set_flag("charting", mode="everyone")
