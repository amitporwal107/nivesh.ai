"""Pure helpers for the email-OTP sign-in flow.

Kept dependency-free (no FastAPI / DB imports) so the code generation and
at-rest hashing are unit-testable in isolation. The endpoints live in
routes/auth.py; the storage/verify policy (TTL, attempt caps, rate limits)
lives there too.
"""
import hashlib
import secrets


def generate_otp() -> str:
    """Cryptographically-random 6-digit code, zero-padded (000000–999999)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, code: str) -> str:
    """SHA-256 of email+code. Codes are short-lived and rate-limited, so we
    persist only the hash and never the plaintext OTP. Binding the email in
    means a hash for one address can't validate another's code."""
    return hashlib.sha256(f"{email}:{code}".encode("utf-8")).hexdigest()
