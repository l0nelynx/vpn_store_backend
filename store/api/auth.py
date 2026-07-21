"""Admin session tokens (HMAC-signed, time-limited).

Service integrations keep using ``api_token``.
Store Admin SPA uses short-lived session tokens issued after login —
never the raw admin password as Bearer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets as py_secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from store.settings import secrets

_bearer_scheme = HTTPBearer(auto_error=False)

# In-memory revoke set (restart clears — acceptable for single-node admin)
_revoked: set[str] = set()


def _session_secret() -> str:
    explicit = secrets.get("admin_session_secret")
    if explicit:
        return str(explicit)
    # Derive from configured secrets so tokens invalidate when password rotates
    material = "|".join(
        [
            str(secrets.get("admin_password") or ""),
            str(secrets.get("api_token") or ""),
            str(secrets.get("admin_login") or "admin"),
        ]
    )
    if not material.strip("|"):
        raise RuntimeError("admin_password / api_token not configured")
    return hashlib.sha256(material.encode()).hexdigest()


def _b64e(data: bytes) -> str:
    return urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return urlsafe_b64decode(data + pad)


def create_session_token(*, username: str, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds or int(secrets.get("admin_session_ttl") or 12 * 3600)
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
        "jti": py_secrets.token_hex(8),
        "typ": "store_admin",
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(_session_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Malformed session") from e
    expected = hmac.new(_session_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid session signature")
    try:
        payload = json.loads(_b64d(body))
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid session payload") from e
    if payload.get("typ") != "store_admin":
        raise HTTPException(status_code=401, detail="Invalid session type")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired")
    jti = payload.get("jti")
    if jti and jti in _revoked:
        raise HTTPException(status_code=401, detail="Session revoked")
    return payload


def revoke_session_token(token: str) -> None:
    try:
        payload = verify_session_token(token)
        if jti := payload.get("jti"):
            _revoked.add(jti)
    except HTTPException:
        pass


def check_admin_password(username: str, password: str) -> bool:
    expected_user = str(secrets.get("admin_login") or "admin")
    expected_pw = secrets.get("admin_password") or secrets.get("dashboard_password")
    if not expected_pw:
        return False

    def _eq(a: str, b: str) -> bool:
        return hmac.compare_digest(
            hashlib.sha256(a.encode()).digest(),
            hashlib.sha256(b.encode()).digest(),
        )

    return _eq(username, expected_user) and _eq(password, str(expected_pw))


async def verify_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    """Service-to-service: Bearer must equal api_token (bot dashboard proxy)."""
    token = secrets.get("api_token")
    if not token:
        raise HTTPException(status_code=503, detail="api_token not configured")
    if credentials is None or not hmac.compare_digest(credentials.credentials, str(token)):
        raise HTTPException(status_code=401, detail="Invalid token")
    return credentials


async def verify_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    """Store Admin SPA session OR service api_token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    presented = credentials.credentials
    api_token = secrets.get("api_token")
    if api_token and hmac.compare_digest(presented, str(api_token)):
        return {"sub": "service", "typ": "api_token"}
    # Do NOT accept raw admin_password anymore
    return verify_session_token(presented)
