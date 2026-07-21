"""Shared Bearer auth for admin + order-params APIs."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from store.settings import secrets

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    token = secrets.get("api_token")
    if not token:
        raise HTTPException(status_code=503, detail="api_token not configured")
    if credentials is None or credentials.credentials != token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return credentials


async def verify_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    """Accept api_token or admin_password as Bearer."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    presented = credentials.credentials
    if presented == secrets.get("api_token"):
        return credentials
    admin_pw = secrets.get("admin_password") or secrets.get("dashboard_password")
    if admin_pw and presented == admin_pw:
        return credentials
    raise HTTPException(status_code=401, detail="Invalid token")
