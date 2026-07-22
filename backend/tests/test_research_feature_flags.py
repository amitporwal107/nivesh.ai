"""Unit tests for the `research` + `research_only` feature flags.

These are the entitlements that gate the Research (Filings Intelligence) surface
and confine research-only pilots to it. Pure in-memory checks against
feature_flags (no DB / network) — the same source /auth/me and /api/user/profile
expose to the frontend via user_feature_map().
"""
import feature_flags as ff


def test_known_features_registers_research_keys():
    assert "research" in ff.KNOWN_FEATURES
    assert "research_only" in ff.KNOWN_FEATURES
    # research is broadly available by default; research_only is opt-in per user.
    assert ff.KNOWN_FEATURES["research"]["default_mode"] == "everyone"
    assert ff.KNOWN_FEATURES["research_only"]["default_mode"] == "allowlist"
    assert ff.KNOWN_FEATURES["research_only"]["default_allowlist"] == []


def test_research_enabled_for_everyone_by_default():
    # 'everyone' mode → enabled regardless of email (even None).
    assert ff.is_enabled("research", "anyone@example.com") is True
    assert ff.is_enabled("research", None) is True


def test_research_only_off_until_explicitly_allowlisted():
    # Empty allowlist → nobody is confined by default.
    assert ff.is_enabled("research_only", "someone@example.com") is False
    m = ff.user_feature_map("someone@example.com")
    assert m["research"] is True
    assert m["research_only"] is False


def test_adding_a_user_confines_only_that_user():
    email = "pilot_test_only@example.com"
    other = "not_a_pilot@example.com"
    try:
        ff.add_user("research_only", email)
        assert ff.is_enabled("research_only", email) is True
        # case-insensitive match
        assert ff.is_enabled("research_only", email.upper()) is True
        # everyone else stays unconfined
        assert ff.is_enabled("research_only", other) is False
        m = ff.user_feature_map(email)
        assert m["research_only"] is True
        assert m["research"] is True
    finally:
        ff.remove_user("research_only", email)
        assert ff.is_enabled("research_only", email) is False
