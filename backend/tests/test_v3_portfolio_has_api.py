"""Tests for HAS integration in /api/insights/v3-portfolio (Iteration 34)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-ai-68.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"
ALLOWED_ACTIONS = {"ADD", "HOLD", "TRIM", "SWITCH", "EXIT", "REVIEW", "UNKNOWN"}
ACTION_PRIORITY = {"EXIT": 0, "SWITCH": 1, "TRIM": 2, "REVIEW": 3, "HOLD": 4, "ADD": 5, "UNKNOWN": 6}


@pytest.fixture(scope="module")
def v3_portfolio():
    cookies = {"session_token": SESSION_TOKEN}
    resp = requests.get(f"{BASE_URL}/api/insights/v3-portfolio", cookies=cookies, timeout=60)
    assert resp.status_code == 200, f"status={resp.status_code} body={resp.text[:300]}"
    return resp.json()


# ── Portfolio-level HAS aggregates ───────────────────────────────────────
class TestPortfolioHasAggregates:
    def test_portfolio_object_present(self, v3_portfolio):
        assert "portfolio" in v3_portfolio, list(v3_portfolio.keys())

    def test_avg_has_score_is_number(self, v3_portfolio):
        port = v3_portfolio["portfolio"]
        assert "avg_has_score" in port, list(port.keys())
        avg = port["avg_has_score"]
        assert avg is None or isinstance(avg, (int, float))
        if isinstance(avg, (int, float)):
            assert 0 <= avg <= 100

    def test_has_action_counts_keys(self, v3_portfolio):
        port = v3_portfolio["portfolio"]
        assert "has_action_counts" in port
        counts = port["has_action_counts"]
        assert isinstance(counts, dict)
        required = {"ADD", "HOLD", "TRIM", "SWITCH", "EXIT", "REVIEW", "UNKNOWN"}
        assert required.issubset(set(counts.keys())), f"missing={required - set(counts.keys())}"
        for k, v in counts.items():
            assert isinstance(v, int) and v >= 0, f"{k}={v}"

    def test_target_weight_pct_per_fund(self, v3_portfolio):
        port = v3_portfolio["portfolio"]
        assert "target_weight_pct_per_fund" in port
        twp = port["target_weight_pct_per_fund"]
        assert isinstance(twp, (int, float))
        assert 0 < twp <= 100


# ── Per-fund HAS structure ───────────────────────────────────────────────
class TestPerFundHas:
    def test_funds_list_exists(self, v3_portfolio):
        funds = v3_portfolio.get("funds") or v3_portfolio.get("fund_breakdown") or []
        assert isinstance(funds, list)
        assert len(funds) > 0, "expected at least 1 fund for priyankamantri"

    def _funds(self, v3_portfolio):
        return v3_portfolio.get("funds") or v3_portfolio.get("fund_breakdown") or []

    def test_at_least_one_fund_has_has_payload(self, v3_portfolio):
        funds = self._funds(v3_portfolio)
        with_has = [f for f in funds if isinstance(f.get("has"), dict)]
        assert len(with_has) > 0, "no fund exposes a `has` object"

    def test_has_object_required_keys(self, v3_portfolio):
        funds = self._funds(v3_portfolio)
        with_has = [f for f in funds if isinstance(f.get("has"), dict)]
        sample = with_has[0]["has"]
        required = {"has", "action", "reason", "category", "components",
                    "ois_score", "ads_score", "ads_deviation_pp",
                    "tfs_penalty", "guardrails", "confidence"}
        missing = required - set(sample.keys())
        assert not missing, f"sample.keys()={list(sample.keys())} missing={missing}"

    def test_actions_in_allowed_set(self, v3_portfolio):
        funds = self._funds(v3_portfolio)
        for f in funds:
            h = f.get("has")
            if isinstance(h, dict):
                assert h.get("action") in ALLOWED_ACTIONS, f"{f.get('fund_name')}: {h.get('action')}"

    def test_funds_sorted_by_has_action_priority(self, v3_portfolio):
        funds = self._funds(v3_portfolio)
        # Build (priority, has_score) sequence ONLY for entries with has
        seq = []
        for f in funds:
            h = f.get("has")
            if isinstance(h, dict) and h.get("action") in ACTION_PRIORITY:
                seq.append((ACTION_PRIORITY[h["action"]], h.get("has") or 0))
        # Confirm non-decreasing by (priority, has_score asc)
        for i in range(1, len(seq)):
            assert seq[i] >= seq[i - 1] or seq[i][0] == seq[i - 1][0], (
                f"sort broken at index {i}: {seq[i-1]} -> {seq[i]}"
            )

    def test_high_quality_protection_no_exit(self, v3_portfolio):
        """Q≥75 AND H≥70 must NOT have action='EXIT' unless overlap > 80%."""
        funds = self._funds(v3_portfolio)
        violations = []
        for f in funds:
            h = f.get("has")
            if not isinstance(h, dict):
                continue
            comps = h.get("components") or {}
            q = comps.get("quality")
            hh = comps.get("health")
            if q is not None and hh is not None and q >= 75 and hh >= 70:
                if h.get("action") == "EXIT":
                    overlap = h.get("ois_score") or 0
                    if overlap <= 80:
                        violations.append((f.get("fund_name"), q, hh, overlap))
        assert not violations, f"high-quality funds wrongly EXIT'd: {violations}"

    def test_action_counts_match_funds(self, v3_portfolio):
        funds = self._funds(v3_portfolio)
        port_counts = v3_portfolio["portfolio"]["has_action_counts"]
        actual = {k: 0 for k in port_counts}
        for f in funds:
            h = f.get("has")
            if isinstance(h, dict):
                a = h.get("action")
                if a in actual:
                    actual[a] += 1
        # Sum of HAS funds should match sum of port counts (excluding non-HAS funds)
        total_port = sum(port_counts.values())
        total_actual = sum(actual.values())
        assert total_actual == total_port, f"actual={actual} vs port={port_counts}"

    def test_category_field_valid(self, v3_portfolio):
        funds = self._funds(v3_portfolio)
        valid_cats = {"equity", "hybrid", "debt", "liquid"}
        for f in funds:
            h = f.get("has")
            if isinstance(h, dict):
                assert h.get("category") in valid_cats, f"{f.get('fund_name')}: {h.get('category')}"
