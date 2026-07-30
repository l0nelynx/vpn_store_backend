from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from store.api import auth
from store.settings import secrets


def test_access_jwt_requires_issuer_type_and_expiry(monkeypatch) -> None:
    monkeypatch.setitem(secrets, "jwt_secret", "test-jwt-key-that-is-long-enough")
    token, ttl = auth._encode_access("admin", "session-id")
    payload = auth._decode_access(token)
    assert ttl == 900
    assert payload["sub"] == "admin"
    assert payload["typ"] == "access"

    now = datetime.now(timezone.utc)
    expired = jwt.encode({
        "sub": "admin", "iat": now - timedelta(minutes=2), "exp": now - timedelta(minutes=1),
        "jti": "token", "sid": "session", "typ": "access", "iss": auth.ISSUER,
    }, secrets["jwt_secret"], algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        auth._decode_access(expired)
    assert error.value.status_code == 401


def test_admin_password_comparison(monkeypatch) -> None:
    monkeypatch.setitem(secrets, "admin_login", "operator")
    monkeypatch.setitem(secrets, "admin_password", "strong-password")
    secrets.pop("admin_password_hash", None)
    assert auth.check_admin_password("operator", "strong-password")
    assert not auth.check_admin_password("operator", "wrong")
