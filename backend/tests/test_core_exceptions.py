"""Unit tests for core.exceptions — hierarchy, context preservation, factories."""
import pytest

from core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    BusinessException,
    IntegrationException,
    NiveshException,
    RateLimitException,
    ResourceNotFoundException,
    SystemException,
    ValidationException,
    integration_error,
    not_found,
)


class TestExceptionHierarchy:
    def test_all_subclass_nivesh_exception(self):
        for cls in (
            ValidationException,
            BusinessException,
            ResourceNotFoundException,
            IntegrationException,
            AuthenticationException,
            AuthorizationException,
            RateLimitException,
            SystemException,
        ):
            exc = cls("test")
            assert isinstance(exc, NiveshException)
            assert isinstance(exc, Exception)

    def test_default_error_codes(self):
        assert ValidationException("x").code == "VAL-001"
        assert BusinessException("x").code == "BIZ-001"
        assert ResourceNotFoundException("x").code == "RES-001"
        assert IntegrationException("x").code == "INT-001"
        assert AuthenticationException("x").code == "AUTH-001"
        assert AuthorizationException("x").code == "AUTHZ-001"
        assert RateLimitException("x").code == "RATE-001"
        assert SystemException("x").code == "SYS-001"

    def test_default_http_statuses(self):
        assert ValidationException("x").http_status == 400
        assert BusinessException("x").http_status == 422
        assert ResourceNotFoundException("x").http_status == 404
        assert IntegrationException("x").http_status == 502
        assert AuthenticationException("x").http_status == 401
        assert AuthorizationException("x").http_status == 403
        assert RateLimitException("x").http_status == 429
        assert SystemException("x").http_status == 500


class TestCausePreservation:
    def test_cause_is_set_on_init(self):
        original = ValueError("db timeout")
        exc = IntegrationException("Broker call failed", cause=original)
        assert exc.__cause__ is original

    def test_cause_none_is_safe(self):
        exc = ValidationException("bad input")
        assert exc.__cause__ is None

    def test_cause_chain_accessible(self):
        root = ConnectionError("socket refused")
        wrapper = SystemException("DB unavailable", cause=root)
        assert isinstance(wrapper.__cause__, ConnectionError)


class TestExceptionAttributes:
    def test_custom_code_overrides_default(self):
        exc = ValidationException("bad email", code="VAL-003")
        assert exc.code == "VAL-003"

    def test_details_stored(self):
        details = [{"field": "email", "message": "Invalid format"}]
        exc = ValidationException("invalid", details=details)
        assert exc.details == details

    def test_context_stored(self):
        exc = BusinessException("rule violated", context={"portfolio_id": "pf_123"})
        assert exc.context["portfolio_id"] == "pf_123"

    def test_default_details_is_empty_list(self):
        exc = ValidationException("x")
        assert exc.details == []

    def test_default_context_is_empty_dict(self):
        exc = ValidationException("x")
        assert exc.context == {}

    def test_message_attribute(self):
        exc = ResourceNotFoundException("Portfolio not found")
        assert exc.message == "Portfolio not found"
        assert str(exc) == "Portfolio not found"

    def test_to_dict(self):
        exc = ValidationException("bad", code="VAL-002", details=[{"field": "name"}])
        d = exc.to_dict()
        assert d["code"] == "VAL-002"
        assert d["message"] == "bad"
        assert d["details"] == [{"field": "name"}]

    def test_repr(self):
        exc = ValidationException("bad input")
        r = repr(exc)
        assert "ValidationException" in r
        assert "VAL-001" in r


class TestFactories:
    def test_not_found_without_identifier(self):
        exc = not_found("Portfolio")
        assert isinstance(exc, ResourceNotFoundException)
        assert "Portfolio" in exc.message
        assert exc.code == "RES-001"

    def test_not_found_with_identifier(self):
        exc = not_found("Portfolio", "pf_abc123")
        assert "pf_abc123" in exc.message

    def test_integration_error_factory(self):
        cause = TimeoutError("timeout")
        exc = integration_error("BrokerAPI", "fetch_holdings", cause=cause)
        assert isinstance(exc, IntegrationException)
        assert "BrokerAPI" in exc.message
        assert "fetch_holdings" in exc.message
        assert exc.__cause__ is cause
        assert exc.code == "INT-001"

    def test_integration_error_custom_code(self):
        exc = integration_error("AMFI", "nav_fetch", code="INT-002")
        assert exc.code == "INT-002"
