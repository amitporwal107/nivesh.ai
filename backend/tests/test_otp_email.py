"""Unit tests for the email-OTP sign-in code path.

Pure/isolated: exercises the OTP code generator, the at-rest hashing, and the
email body renderer without a database or an SMTP server.
"""
import hashlib
import hmac

import pytest

from services import email_service
from helpers.otp import generate_otp, hash_otp

OTP_TTL_MINUTES = 30  # mirrors routes.auth.OTP_TTL_MINUTES (kept fastapi-free here)


def test_generate_otp_is_six_digits_zero_padded():
    codes = [generate_otp() for _ in range(2000)]
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert all(0 <= int(c) <= 999999 for c in codes)
    # Zero-padding must actually be exercised (a value < 100000 renders leading 0s).
    assert any(c.startswith("0") for c in codes)


def test_hash_is_stable_and_binds_email_and_code():
    h = hash_otp("a@b.com", "123456")
    assert hmac.compare_digest(h, hash_otp("a@b.com", "123456"))     # same input → same hash
    assert not hmac.compare_digest(h, hash_otp("a@b.com", "123457"))  # wrong code
    assert not hmac.compare_digest(h, hash_otp("x@b.com", "123456"))  # wrong email
    assert h == hashlib.sha256(b"a@b.com:123456").hexdigest()


def test_hash_never_contains_plaintext_code():
    assert "123456" not in hash_otp("a@b.com", "123456")


def test_build_otp_email_contains_code_and_expiry():
    subject, text, html = email_service.build_otp_email("amit@rbs.com", "048213", OTP_TTL_MINUTES)
    for body in (subject, text, html):
        assert "048213" in body
    assert f"{OTP_TTL_MINUTES} minutes" in text
    assert f"{OTP_TTL_MINUTES} minutes" in html
    assert "amit@rbs.com" in text and "amit@rbs.com" in html


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
