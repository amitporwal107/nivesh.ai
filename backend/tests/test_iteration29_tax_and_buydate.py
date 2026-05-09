"""Iteration 29 — Tax engine (ClearTax FY 25-26) + buy_date pipeline tests.

Covers:
- GET /api/copilot/suggested-prompts context_summary validation
- POST /api/plans/generate total_tax_impact + per-action tax_impact
- PUT /api/portfolio/holdings/{id} buy_date set + null-clear
- POST /api/portfolio/holdings — buy_date null when omitted
- Unit tests for services/tax_calculator.py (equity/debt/gold regimes, pending state)
"""
import os
import pytest
import requests
from datetime import date, datetime, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-ai-68.preview.emergentagent.com").rstrip("/")
SESSION = "370eff71-fda1-46d8-b506-b81b894d634f"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION)
    s.headers.update({"Content-Type": "application/json"})
    return s


# ─────────────────────────────────────────────────────────────────
# Copilot context_summary
# ─────────────────────────────────────────────────────────────────
class TestCopilotContext:
    def test_suggested_prompts_allocation_pcts(self, client):
        r = client.get(f"{BASE_URL}/api/copilot/suggested-prompts")
        assert r.status_code == 200
        cs = r.json().get("context_summary", {})
        e, d, g, o = cs.get("equity_pct", 0), cs.get("debt_pct", 0), cs.get("gold_pct", 0), cs.get("other_pct", 0)
        # sum ~ 100 (+/- 1 for rounding)
        assert 99 <= (e + d + g + o) <= 101, f"pct sum not ~100: e={e} d={d} g={g} o={o}"
        assert e > 0, "equity_pct must be > 0"
        assert g > 0, "gold_pct must be > 0 (ETF classifier)"
        assert d > 0, "debt_pct must be > 0 (ETF classifier)"

    def test_plan_tax_liability_nonzero(self, client):
        r = client.get(f"{BASE_URL}/api/copilot/suggested-prompts")
        assert r.status_code == 200
        cs = r.json().get("context_summary", {})
        assert cs.get("plan_tax_liability", 0) > 0, "plan_tax_liability must be > 0 (not ₹0 bug)"


# ─────────────────────────────────────────────────────────────────
# Plan generation
# ─────────────────────────────────────────────────────────────────
class TestPlanGenerate:
    def test_plan_total_tax_and_per_action(self, client):
        r = client.post(f"{BASE_URL}/api/plans/generate", json={"goal": "Optimise my taxes"})
        assert r.status_code == 200
        body = r.json()
        plan = body.get("plan", body)
        tti = plan.get("total_tax_impact", {})
        assert tti.get("total_tax_liability", 0) > 0, f"total_tax_liability must be > 0: {tti}"
        actions = plan.get("actions", [])
        assert len(actions) > 0
        exit_actions = [a for a in actions if (a.get("action_type") or "").lower() == "exit" or a.get("tax_impact")]
        # At least some action carries tax_impact
        assert len(exit_actions) > 0
        for a in exit_actions:
            ti = a.get("tax_impact") or {}
            assert "asset_class" in ti, f"missing asset_class in {ti}"
            assert "tax_regime" in ti
            assert "tax_liability" in ti
            # tax_liability must be number (not None)
            assert ti["tax_liability"] is not None


# ─────────────────────────────────────────────────────────────────
# Holdings CRUD with buy_date
# ─────────────────────────────────────────────────────────────────
class TestHoldingsBuyDate:
    def test_post_without_buy_date_is_null(self, client):
        payload = {
            "name": "TEST_BUYDATE_NULL",
            "ticker": "TESTNULL",
            "asset_type": "equity",
            "quantity": 1,
            "buy_price": 100,
            "current_price": 120,
        }
        r = client.post(f"{BASE_URL}/api/portfolio/holdings", json=payload)
        assert r.status_code in (200, 201), r.text
        data = r.json()
        hid = data["holding_id"]
        assert data["buy_date"] is None, f"buy_date should be null, got {data.get('buy_date')}"
        # cleanup
        client.delete(f"{BASE_URL}/api/portfolio/holdings/{hid}")

    def test_put_buy_date_persists(self, client):
        # Pick any existing holding
        r = client.get(f"{BASE_URL}/api/portfolio/holdings")
        assert r.status_code == 200
        holdings = r.json()
        assert len(holdings) > 0
        # Use one not Ambuja (to avoid mutating sanity-set)
        target = next(h for h in holdings if "AMBUJA" not in (h.get("name") or "").upper())
        hid = target["holding_id"]
        original = target.get("buy_date")
        # set to 2023-06-15
        r = client.put(f"{BASE_URL}/api/portfolio/holdings/{hid}", json={"buy_date": "2023-06-15"})
        assert r.status_code == 200
        assert r.json().get("buy_date") == "2023-06-15"
        # GET to verify
        r2 = client.get(f"{BASE_URL}/api/portfolio/holdings")
        t = next(h for h in r2.json() if h["holding_id"] == hid)
        assert t["buy_date"] == "2023-06-15"
        # restore
        if original:
            client.put(f"{BASE_URL}/api/portfolio/holdings/{hid}", json={"buy_date": original})

    def test_put_buy_date_null_clears(self, client):
        """BUG CHECK: sending {buy_date: null} should clear — not 400."""
        r = client.get(f"{BASE_URL}/api/portfolio/holdings")
        holdings = r.json()
        target = next(h for h in holdings if "AMBUJA" not in (h.get("name") or "").upper())
        hid = target["holding_id"]
        original = target.get("buy_date")
        resp = client.put(f"{BASE_URL}/api/portfolio/holdings/{hid}", json={"buy_date": None})
        # Expected per review request: should accept and clear. Currently returns 400.
        assert resp.status_code == 200, f"PUT buy_date=null should clear, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("buy_date") is None, f"buy_date should be null after clearing, got {data.get('buy_date')}"
        # restore
        if original:
            client.put(f"{BASE_URL}/api/portfolio/holdings/{hid}", json={"buy_date": original})


# ─────────────────────────────────────────────────────────────────
# Tax calculator unit tests (ClearTax FY 25-26 rules)
# ─────────────────────────────────────────────────────────────────
class TestTaxCalculator:
    """Unit-level tests — imports backend service directly."""

    @pytest.fixture(autouse=True)
    def _setup_path(self):
        import sys
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")

    def _hold(self, **kw):
        base = {"asset_type": "equity", "name": "Test",
                "buy_price": 100, "current_price": 200, "quantity": 100,
                "buy_date": "2023-01-01"}
        base.update(kw)
        return base

    def test_equity_stcg_20pct(self):
        from services.tax_calculator import calculate_tax_impact
        # 6 months ago
        bd = (date.today() - timedelta(days=180)).isoformat()
        h = self._hold(buy_date=bd)  # gain = 100*100 = 10000
        r = calculate_tax_impact(h)
        assert r["asset_class"] == "equity"
        assert r["is_long_term"] is False
        assert r["tax_rate"] == 0.20
        assert r["tax_liability"] == pytest.approx(10000 * 0.20, rel=0.01)
        assert r["tax_regime"] == "equity_stcg"

    def test_equity_ltcg_12_5pct_with_exemption(self):
        from services.tax_calculator import calculate_tax_impact
        bd = (date.today() - timedelta(days=500)).isoformat()
        h = self._hold(buy_date=bd, quantity=100, buy_price=100, current_price=2000)
        # gain = 190000 (> 1.25L exemption)
        r = calculate_tax_impact(h)
        assert r["is_long_term"] is True
        assert r["tax_rate"] == 0.125
        # taxable = 190000 - 125000 = 65000 → tax = 8125
        assert r["taxable_gain"] == pytest.approx(65000, rel=0.01)
        assert r["tax_liability"] == pytest.approx(65000 * 0.125, rel=0.01)

    def test_debt_post_apr23_always_slab(self):
        from services.tax_calculator import calculate_tax_impact
        # Debt MF bought in 2024 → always slab
        h = self._hold(asset_type="mutual_fund", name="HDFC Liquid Fund",
                       buy_date="2024-01-01", buy_price=100, current_price=120, quantity=1000)
        r = calculate_tax_impact(h, user_slab_rate=0.30)
        assert r["asset_class"] == "debt"
        assert r["tax_regime"] == "debt_slab_always"
        assert r["tax_rate"] == 0.30

    def test_gold_ltcg_above_24m(self):
        from services.tax_calculator import calculate_tax_impact
        h = self._hold(asset_type="etf", name="Nippon Gold ETF",
                       buy_date="2022-01-01", buy_price=100, current_price=200, quantity=100)
        r = calculate_tax_impact(h)
        assert r["asset_class"] == "gold"
        assert r["is_long_term"] is True
        assert r["tax_rate"] == 0.125

    def test_pending_when_buy_date_none(self):
        from services.tax_calculator import calculate_tax_impact
        h = self._hold(buy_date=None)
        r = calculate_tax_impact(h)
        assert r["tax_impact_pending"] is True
        assert r["tax_regime"] == "pending"
        assert r["tax_liability"] == 0.0
        assert r["pending_reason"] == "purchase_date_missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
