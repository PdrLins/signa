"""Tests for security — JWT, OTP, password hashing."""

import os

# Set required env vars before importing settings
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.security import (
    create_access_token,
    create_session_token,
    decode_token,
    generate_otp,
    hash_otp,
    hash_password,
    verify_otp,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "my-secure-password"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token("user-123", "pedro")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["username"] == "pedro"
        assert "jti" in payload
        assert "exp" in payload

    def test_invalid_token(self):
        assert decode_token("garbage.token.here") is None

    def test_empty_token(self):
        assert decode_token("") is None


class TestOTP:
    def test_generate_is_6_digits(self):
        otp = generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()
        assert 100000 <= int(otp) <= 999999

    def test_hash_and_verify(self):
        otp = "847291"
        salt = "session-token-123"
        hashed = hash_otp(otp, salt)
        assert hashed != otp
        assert verify_otp(otp, hashed, salt) is True

    def test_wrong_otp(self):
        hashed = hash_otp("123456", "salt")
        assert verify_otp("654321", hashed, "salt") is False

    def test_wrong_salt(self):
        hashed = hash_otp("123456", "salt-a")
        assert verify_otp("123456", hashed, "salt-b") is False

    def test_unique_otps(self):
        otps = {generate_otp() for _ in range(100)}
        assert len(otps) > 50  # Should be mostly unique


class TestSessionToken:
    def test_length(self):
        token = create_session_token()
        assert len(token) > 20

    def test_unique(self):
        tokens = {create_session_token() for _ in range(50)}
        assert len(tokens) == 50
