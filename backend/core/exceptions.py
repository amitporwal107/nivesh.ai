"""Domain-specific exception hierarchy for nivesh.ai.

Hierarchy
---------
NiveshException (base)
├── ValidationException       VAL-001  HTTP 400
├── BusinessException         BIZ-001  HTTP 422
├── ResourceNotFoundException RES-001  HTTP 404
├── IntegrationException      INT-001  HTTP 502
├── AuthenticationException   AUTH-001 HTTP 401
├── AuthorizationException    AUTHZ-001 HTTP 403
├── RateLimitException        RATE-001 HTTP 429
└── SystemException           SYS-001  HTTP 500

Error code catalogue
--------------------
VAL-001   Generic validation failure
VAL-002   Missing required field
VAL-003   Invalid field format
VAL-004   Value out of allowed range

BIZ-001   Generic business rule violation
BIZ-002   Duplicate resource
BIZ-003   Insufficient funds / quota

RES-001   Generic resource not found
RES-002   Portfolio not found
RES-003   Holding not found
RES-004   User not found

INT-001   Generic integration failure
INT-002   External API timeout
INT-003   External API returned unexpected response
INT-004   Circuit breaker open

AUTH-001  Generic authentication failure
AUTH-002  Session expired
AUTH-003  Invalid credentials

AUTHZ-001 Generic authorization failure
AUTHZ-002 Resource ownership violation
AUTHZ-003 Role requirement not met

RATE-001  Generic rate limit exceeded
RATE-002  Per-user limit exceeded
RATE-003  Per-IP limit exceeded

SYS-001   Generic system error
SYS-002   Database unavailable
SYS-003   Configuration error
"""
from __future__ import annotations

from typing import Any, Optional


class NiveshException(Exception):
    """Base class for all domain exceptions.

    Always pass ``cause`` when wrapping a lower-level exception so the root
    cause is preserved in ``__cause__``.
    """
    error_code: str = "SYS-000"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[list[dict[str, Any]]] = None,
        cause: Optional[Exception] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.error_code
        self.details = details or []
        self.context = context or {}
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationException(NiveshException):
    """Input failed validation. Retrying with the same input will not help."""
    error_code = "VAL-001"
    http_status = 400


# ── Business logic ────────────────────────────────────────────────────────────

class BusinessException(NiveshException):
    """A business rule was violated. Not a programming error."""
    error_code = "BIZ-001"
    http_status = 422


# ── Resource ──────────────────────────────────────────────────────────────────

class ResourceNotFoundException(NiveshException):
    """The requested resource does not exist."""
    error_code = "RES-001"
    http_status = 404


# ── External integrations ─────────────────────────────────────────────────────

class IntegrationException(NiveshException):
    """An external service call failed.

    Always set ``cause`` to the underlying exception so on-call engineers
    can see the real error without digging through log lines.
    """
    error_code = "INT-001"
    http_status = 502


# ── Authentication / Authorization ────────────────────────────────────────────

class AuthenticationException(NiveshException):
    """The caller's identity could not be verified."""
    error_code = "AUTH-001"
    http_status = 401


class AuthorizationException(NiveshException):
    """The caller lacks permission to perform this action."""
    error_code = "AUTHZ-001"
    http_status = 403


# ── Rate limiting ─────────────────────────────────────────────────────────────

class RateLimitException(NiveshException):
    """The caller has exceeded their request quota."""
    error_code = "RATE-001"
    http_status = 429


# ── System ────────────────────────────────────────────────────────────────────

class SystemException(NiveshException):
    """An unexpected system-level failure occurred.

    Wrap unexpected low-level exceptions (DB errors, config issues, etc.)
    in this type so they reach the global handler with appropriate context.
    """
    error_code = "SYS-001"
    http_status = 500


# ── Convenience helpers ───────────────────────────────────────────────────────

def not_found(resource: str, identifier: str | None = None) -> ResourceNotFoundException:
    """Factory for concise ResourceNotFoundException construction."""
    msg = f"{resource} not found"
    if identifier:
        msg = f"{resource} '{identifier}' not found"
    return ResourceNotFoundException(msg, code="RES-001")


def integration_error(
    service: str,
    operation: str,
    cause: Optional[Exception] = None,
    *,
    code: str = "INT-001",
) -> IntegrationException:
    """Factory for IntegrationException with consistent messaging."""
    return IntegrationException(
        f"{service} call failed during {operation}",
        code=code,
        cause=cause,
    )
