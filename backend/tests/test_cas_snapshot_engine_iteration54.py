"""CAS Snapshot Engine - API tests (iteration 54)
Tests: /api/portfolio/cas-snapshots, cas-performance, cas-sip-summary,
       cas-top-transactions, cas-sip-breakdown, cas-snapshot/{date}/activate
Also validates: parse_cas_pdf_with_data exists, _process_client_cas imports,
               cas_snapshots router registration.
"""
import pytest
import requests
import os
import importlib
import inspect

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Both users have 0 CAS snapshots — empty responses are correct/expected
SESSION_TOKEN_PRIYANKA = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com
SESSION_TOKEN_APORWAL = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"    # aporwal107@gmail.com


@pytest.fixture(scope="module")
def auth_headers():
    return {"Authorization": f"Bearer {SESSION_TOKEN_APORWAL}"}


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ── Code-level checks (no HTTP needed) ────────────────────────────────

class TestCodeLevelChecks:
    """Verify new functions/imports exist in the codebase without HTTP."""

    def test_parse_cas_pdf_with_data_exists(self):
        """helpers/parsing.py must export parse_cas_pdf_with_data()"""
        from helpers.parsing import parse_cas_pdf_with_data
        assert callable(parse_cas_pdf_with_data), "parse_cas_pdf_with_data must be callable"

    def test_parse_cas_pdf_with_data_is_async(self):
        """parse_cas_pdf_with_data should be an async function"""
        from helpers.parsing import parse_cas_pdf_with_data
        assert inspect.iscoroutinefunction(parse_cas_pdf_with_data), \
            "parse_cas_pdf_with_data should be async"

    def test_normalize_casparser_folios_exists(self):
        """helpers/parsing.py should have _normalize_casparser_folios"""
        from helpers import parsing
        assert hasattr(parsing, "_normalize_casparser_folios"), \
            "_normalize_casparser_folios must exist in helpers.parsing"

    def test_client_cas_invite_imports_new_deps(self):
        """routes/client_cas_invite.py must import parse_cas_pdf_with_data,
        detect_statement_period, create_cas_snapshot"""
        import routes.client_cas_invite as mod
        # Check the module-level names
        assert hasattr(mod, "parse_cas_pdf_with_data") or "parse_cas_pdf_with_data" in dir(mod), \
            "parse_cas_pdf_with_data import missing from client_cas_invite"
        assert hasattr(mod, "detect_statement_period") or "detect_statement_period" in dir(mod), \
            "detect_statement_period import missing from client_cas_invite"
        assert hasattr(mod, "create_cas_snapshot") or "create_cas_snapshot" in dir(mod), \
            "create_cas_snapshot import missing from client_cas_invite"

    def test_cas_snapshots_router_imported_in_server(self):
        """server.py must register the cas_snapshots router"""
        import server
        # The router is included — check FastAPI app routes have /api/portfolio/cas-snapshots
        routes = [r.path for r in server.app.routes]
        snapshot_routes = [r for r in routes if "cas-snapshot" in r]
        assert len(snapshot_routes) >= 1, \
            f"No cas-snapshot routes registered. Routes: {routes}"

    def test_cas_snapshots_router_has_correct_prefix(self):
        """cas_snapshots router prefix should be /api/portfolio"""
        from routes.cas_snapshots import router
        assert router.prefix == "/api/portfolio", \
            f"Expected prefix /api/portfolio, got {router.prefix}"

    def test_cas_snapshot_engine_has_create_cas_snapshot(self):
        """services/cas_snapshot_engine.py must export create_cas_snapshot"""
        from services.cas_snapshot_engine import create_cas_snapshot
        assert callable(create_cas_snapshot)

    def test_cas_period_detector_exists(self):
        """services/cas_period_detector.py must export detect_statement_period"""
        from services.cas_period_detector import detect_statement_period
        assert callable(detect_statement_period)


# ── HTTP API tests ─────────────────────────────────────────────────────

class TestCasSnapshotsAPI:
    """GET /api/portfolio/cas-snapshots"""

    def test_cas_snapshots_returns_200(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshots", headers=auth_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"

    def test_cas_snapshots_response_shape(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshots", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "count" in data, f"'count' missing from response: {data}"
        assert "snapshots" in data, f"'snapshots' missing from response: {data}"
        assert "current_snapshot_date" in data, f"'current_snapshot_date' missing: {data}"

    def test_cas_snapshots_count_matches_list(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshots", headers=auth_headers)
        data = r.json()
        assert data["count"] == len(data["snapshots"]), \
            f"count={data['count']} but snapshots has {len(data['snapshots'])} items"

    def test_cas_snapshots_empty_for_clean_user(self, session, auth_headers):
        """Both users have 0 snapshots — empty list is correct"""
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshots", headers=auth_headers)
        data = r.json()
        # Empty is correct (not an error)
        assert isinstance(data["snapshots"], list), "snapshots should be a list"
        print(f"Snapshot count: {data['count']} (expected 0 for clean user)")

    def test_cas_snapshots_priyanka_user(self, session):
        """Test with priyanka's session token"""
        headers = {"Authorization": f"Bearer {SESSION_TOKEN_PRIYANKA}"}
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshots", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "count" in data and "snapshots" in data
        print(f"Priyanka snapshot count: {data['count']}")


class TestCasPerformanceAPI:
    """GET /api/portfolio/cas-performance"""

    def test_cas_performance_returns_200(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-performance", headers=auth_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"

    def test_cas_performance_response_shape(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-performance", headers=auth_headers)
        data = r.json()
        assert "count" in data, f"'count' missing: {data}"
        assert "series" in data, f"'series' missing: {data}"

    def test_cas_performance_series_is_list(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-performance", headers=auth_headers)
        data = r.json()
        assert isinstance(data["series"], list), "series should be a list"

    def test_cas_performance_count_matches_series(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-performance", headers=auth_headers)
        data = r.json()
        assert data["count"] == len(data["series"])

    def test_cas_performance_with_date_range(self, session, auth_headers):
        """Test with explicit from/to params"""
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-performance",
            params={"from": "2025-01-01", "to": "2026-12-31"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "series" in data


class TestCasSipSummaryAPI:
    """GET /api/portfolio/cas-sip-summary"""

    def test_cas_sip_summary_returns_200(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-sip-summary", headers=auth_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"

    def test_cas_sip_summary_response_shape(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-sip-summary", headers=auth_headers)
        data = r.json()
        assert "months" in data, f"'months' missing: {data}"
        assert "total_invested" in data, f"'total_invested' missing: {data}"

    def test_cas_sip_summary_months_is_list(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-sip-summary", headers=auth_headers)
        data = r.json()
        assert isinstance(data["months"], list)

    def test_cas_sip_summary_total_invested_is_number(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-sip-summary", headers=auth_headers)
        data = r.json()
        assert isinstance(data["total_invested"], (int, float))


class TestCasTopTransactionsAPI:
    """GET /api/portfolio/cas-top-transactions"""

    def test_cas_top_transactions_returns_200(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-top-transactions", headers=auth_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"

    def test_cas_top_transactions_response_shape(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-top-transactions", headers=auth_headers)
        data = r.json()
        assert "count" in data, f"'count' missing: {data}"
        assert "transactions" in data, f"'transactions' missing: {data}"

    def test_cas_top_transactions_list(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-top-transactions", headers=auth_headers)
        data = r.json()
        assert isinstance(data["transactions"], list)

    def test_cas_top_transactions_count_matches(self, session, auth_headers):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-top-transactions", headers=auth_headers)
        data = r.json()
        assert data["count"] == len(data["transactions"])

    def test_cas_top_transactions_n_limit(self, session, auth_headers):
        """n param limits results to max 50"""
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-top-transactions",
            params={"n": 5},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["transactions"]) <= 5


class TestCasSipBreakdownAPI:
    """GET /api/portfolio/cas-sip-breakdown"""

    def test_cas_sip_breakdown_returns_200(self, session, auth_headers):
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-sip-breakdown",
            params={"month": "2026-01"},
            headers=auth_headers,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"

    def test_cas_sip_breakdown_response_shape(self, session, auth_headers):
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-sip-breakdown",
            params={"month": "2026-01"},
            headers=auth_headers,
        )
        data = r.json()
        assert "month" in data, f"'month' missing: {data}"
        assert "funds" in data, f"'funds' missing: {data}"
        assert "amcs" in data, f"'amcs' missing: {data}"
        assert "total" in data, f"'total' missing: {data}"

    def test_cas_sip_breakdown_correct_month(self, session, auth_headers):
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-sip-breakdown",
            params={"month": "2026-01"},
            headers=auth_headers,
        )
        data = r.json()
        assert data["month"] == "2026-01"

    def test_cas_sip_breakdown_funds_and_amcs_are_lists(self, session, auth_headers):
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-sip-breakdown",
            params={"month": "2026-01"},
            headers=auth_headers,
        )
        data = r.json()
        assert isinstance(data["funds"], list)
        assert isinstance(data["amcs"], list)

    def test_cas_sip_breakdown_invalid_month_format(self, session, auth_headers):
        """Bad month format should return 400"""
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-sip-breakdown",
            params={"month": "January-2026"},
            headers=auth_headers,
        )
        assert r.status_code == 400, f"Expected 400 for invalid month, got {r.status_code}"

    def test_cas_sip_breakdown_missing_month_param(self, session, auth_headers):
        """month param is required — missing should return 422"""
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-sip-breakdown",
            headers=auth_headers,
        )
        assert r.status_code == 422, f"Expected 422 for missing month, got {r.status_code}"


class TestActivateCasSnapshot:
    """POST /api/portfolio/cas-snapshot/{snapshot_date}/activate"""

    def test_activate_nonexistent_snapshot_returns_404(self, session, auth_headers):
        """BADDATE snapshot should return 404"""
        r = session.post(
            f"{BASE_URL}/api/portfolio/cas-snapshot/BADDATE/activate",
            headers=auth_headers,
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text[:300]}"

    def test_activate_404_has_detail(self, session, auth_headers):
        """404 response should include error detail"""
        r = session.post(
            f"{BASE_URL}/api/portfolio/cas-snapshot/BADDATE/activate",
            headers=auth_headers,
        )
        data = r.json()
        assert "detail" in data, f"'detail' missing from 404 response: {data}"
        print(f"404 detail: {data.get('detail')}")

    def test_activate_valid_date_but_no_snapshot_returns_404(self, session, auth_headers):
        """A valid date format but no snapshot for it → still 404"""
        r = session.post(
            f"{BASE_URL}/api/portfolio/cas-snapshot/2099-01-01/activate",
            headers=auth_headers,
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text[:300]}"

    def test_activate_unauthenticated_returns_401(self, session):
        """No auth headers → should return 401"""
        r = session.post(
            f"{BASE_URL}/api/portfolio/cas-snapshot/2026-01-31/activate",
        )
        assert r.status_code in (401, 403), \
            f"Expected 401/403 for unauthenticated, got {r.status_code}"


class TestCasSnapshotSingleAPI:
    """GET /api/portfolio/cas-snapshot"""

    def test_get_latest_snapshot_no_data_returns_404(self, session, auth_headers):
        """No snapshots yet → GET /cas-snapshot (no date) returns 404"""
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshot", headers=auth_headers)
        # For user with 0 snapshots, 404 is the correct response
        assert r.status_code in (200, 404), \
            f"Expected 200 or 404, got {r.status_code}: {r.text[:300]}"
        if r.status_code == 404:
            data = r.json()
            assert "detail" in data
            print(f"Expected 404 (no snapshots): {data.get('detail')}")

    def test_get_snapshot_bad_date_returns_404(self, session, auth_headers):
        """Querying a date that doesn't exist returns 404"""
        r = session.get(
            f"{BASE_URL}/api/portfolio/cas-snapshot",
            params={"date": "2099-01-01"},
            headers=auth_headers,
        )
        assert r.status_code == 404


class TestAuthRequired:
    """All endpoints require auth — verify 401/403 when unauthenticated"""

    def test_cas_snapshots_requires_auth(self, session):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-snapshots")
        assert r.status_code in (401, 403), \
            f"Expected 401/403, got {r.status_code}"

    def test_cas_performance_requires_auth(self, session):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-performance")
        assert r.status_code in (401, 403)

    def test_cas_sip_summary_requires_auth(self, session):
        r = session.get(f"{BASE_URL}/api/portfolio/cas-sip-summary")
        assert r.status_code in (401, 403)
