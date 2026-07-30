"""Standards-based JWT access tokens and rotating refresh sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets as py_secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select

from store.database.models import AdminSession, async_session
from store.settings import secrets

_bearer_scheme = HTTPBearer(auto_error=False)
_password_hash = PasswordHash.recommended()
ISSUER = "vpn-store"


def _jwt_secret() -> str:
    value = secrets.get("jwt_secret") or secrets.get("admin_session_secret")
    if not value:
        raise RuntimeError("STORE_JWT_SECRET/jwt_secret is required")
    return str(value)


def check_admin_password(username: str, password: str) -> bool:
    expected_user = str(secrets.get("admin_login") or "admin")
    if not hmac.compare_digest(username, expected_user):
        return False
    password_hash = secrets.get("admin_password_hash")
    if password_hash:
        try:
            return _password_hash.verify(password, str(password_hash))
        except Exception:
            return False
    # Transitional support only; deployments should move to admin_password_hash.
    expected = str(secrets.get("admin_password") or "")
    return bool(expected) and hmac.compare_digest(
        hashlib.sha256(password.encode()).digest(), hashlib.sha256(expected.encode()).digest()
    )


def _encode_access(username: str, session_jti: str) -> tuple[str, int]:
    ttl = int(secrets.get("admin_access_ttl") or 900)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": py_secrets.token_hex(16),
        "sid": session_jti,
        "typ": "access",
        "iss": ISSUER,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256"), ttl


def _refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(username: str) -> dict[str, Any]:
    refresh_ttl = int(secrets.get("admin_refresh_ttl") or 30 * 24 * 3600)
    refresh = py_secrets.token_urlsafe(48)
    jti = py_secrets.token_hex(16)
    async with async_session() as session:
        session.add(
            AdminSession(
                jti=jti,
                username=username,
                refresh_token_hash=_refresh_hash(refresh),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=refresh_ttl),
            )
        )
        await session.commit()
    access, ttl = _encode_access(username, jti)
    return {"access_token": access, "refresh_token": refresh, "expires_in": ttl, "username": username}


async def rotate_refresh(token: str) -> dict[str, Any]:
    digest = _refresh_hash(token)
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        row = await session.scalar(
            select(AdminSession).where(AdminSession.refresh_token_hash == digest).with_for_update()
        )
        if not row or row.revoked_at or row.expires_at <= now:
            raise HTTPException(status_code=401, detail="Refresh session expired")
        row.revoked_at = now
        username = row.username
        await session.commit()
    return await create_session(username)


async def revoke_refresh(token: str | None) -> None:
    if not token:
        return
    async with async_session() as session:
        row = await session.scalar(
            select(AdminSession).where(AdminSession.refresh_token_hash == _refresh_hash(token)).with_for_update()
        )
        if row and not row.revoked_at:
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()


async def verify_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    token = secrets.get("api_token")
    if not token:
        raise HTTPException(status_code=503, detail="api_token not configured")
    if credentials is None or not hmac.compare_digest(credentials.credentials, str(token)):
        raise HTTPException(status_code=401, detail="Invalid service token")
    return {"sub": "service", "typ": "service"}


def _decode_access(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, _jwt_secret(), algorithms=["HS256"], issuer=ISSUER,
            options={"require": ["sub", "exp", "iat", "jti", "sid", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


async def verify_human_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = _decode_access(credentials.credentials)
    async with async_session() as session:
        row = await session.scalar(select(AdminSession).where(AdminSession.jti == payload["sid"]))
        if not row or row.revoked_at or row.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Session revoked")
    return payload


async def verify_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Compatibility admin APIs still accept the service token."""
    if credentials:
        service = secrets.get("api_token")
        if service and hmac.compare_digest(credentials.credentials, str(service)):
            return {"sub": "service", "typ": "service"}
    return await verify_human_admin(credentials)
