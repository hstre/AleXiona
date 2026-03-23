"""Unit tests for auth.py — token creation, decode, and validation."""
import os
import time
import pytest

# SECRET_KEY must be set before importing auth
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

from auth import create_token, decode_token, UserSession


# ── create_token ──────────────────────────────────────────────────────────────

def test_create_token_returns_non_empty_string():
    token = create_token("clinician", "session-abc")
    assert isinstance(token, str)
    assert len(token) > 10


def test_create_token_invalid_role_raises():
    with pytest.raises(ValueError, match="Unknown role"):
        create_token("admin", "session-abc")


def test_create_token_demo_role_accepted():
    token = create_token("demo", "session-xyz")
    assert token


# ── decode_token ──────────────────────────────────────────────────────────────

def test_decode_token_roundtrip():
    sid = "11111111-2222-3333-4444-555555555555"
    token = create_token("clinician", sid)
    user = decode_token(token)
    assert user.role == "clinician"
    assert user.session_id == sid
    assert user.user_id  # non-empty uuid


def test_decode_token_demo_roundtrip():
    token = create_token("demo", "demo-session")
    user = decode_token(token)
    assert user.role == "demo"
    assert not user.is_clinician


def test_decode_token_invalid_raises():
    with pytest.raises(ValueError, match="Invalid session token"):
        decode_token("not.a.real.token")


def test_decode_token_tampered_raises():
    token = create_token("clinician", "s1")
    tampered = token[:-4] + "xxxx"
    with pytest.raises(ValueError):
        decode_token(tampered)


def test_decode_token_expired_raises(monkeypatch):
    """Simulate an expired token by patching _MAX_AGE to -1.
    itsdangerous checks age > max_age; -1 makes every token immediately expired.
    """
    import auth as auth_module
    token = create_token("clinician", "s1")
    monkeypatch.setattr(auth_module, "_MAX_AGE", -1)
    with pytest.raises(ValueError, match="Session expired"):
        decode_token(token)


# ── UserSession ───────────────────────────────────────────────────────────────

def test_user_session_is_clinician():
    user = UserSession(user_id="u1", role="clinician", session_id="s1")
    assert user.is_clinician


def test_user_session_demo_not_clinician():
    user = UserSession(user_id="u1", role="demo", session_id="s1")
    assert not user.is_clinician


# ── Token does not carry role-escalation ─────────────────────────────────────

def test_different_sessions_get_different_tokens():
    t1 = create_token("clinician", "session-A")
    t2 = create_token("clinician", "session-B")
    assert t1 != t2


def test_same_inputs_get_different_tokens_due_to_uid():
    """Each call generates a new uid, so tokens differ even for same role+sid."""
    t1 = create_token("clinician", "same-session")
    t2 = create_token("clinician", "same-session")
    assert t1 != t2
