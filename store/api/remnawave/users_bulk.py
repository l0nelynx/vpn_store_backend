"""Bulk Remnawave user lookup via /api/users/stream (cursor) with fallback pagination."""

from __future__ import annotations

import logging
from typing import Any

from store.api.remnawave.api import get_sdk, _log_rw_error

logger = logging.getLogger(__name__)


def _normalize_user(raw: dict[str, Any]) -> dict[str, Any]:
    username = raw.get("username")
    uuid = raw.get("uuid")
    sub = raw.get("subscriptionUrl") or raw.get("subscription_url")
    expire = raw.get("expireAt") or raw.get("expire_at")
    return {
        "uuid": str(uuid) if uuid is not None else None,
        "username": username,
        "subscription_url": sub,
        "expire": expire,
        "status": "active",
    }


async def stream_all_users(page_size: int = 250) -> list[dict[str, Any]]:
    """Fetch all panel users via GET /api/users/stream (cursor pagination).

    Falls back to GET /api/users?start=&size= if stream is unavailable.
    """
    sdk = get_sdk()
    client = sdk._client
    page_size = max(1, min(int(page_size), 1000))
    users: list[dict] = []

    # Prefer cursor stream
    try:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"size": page_size}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get("/users/stream", params=params, timeout=60.0)
            if resp.status_code == 404:
                raise RuntimeError("stream endpoint not available")
            resp.raise_for_status()
            data = resp.json()
            payload = data.get("response") if isinstance(data, dict) else None
            if payload is None and isinstance(data, dict):
                payload = data
            batch = (payload or {}).get("users") or []
            for u in batch:
                if isinstance(u, dict):
                    users.append(_normalize_user(u))
            next_cursor = (payload or {}).get("nextCursor")
            has_more = bool((payload or {}).get("hasMore"))
            if not has_more or not next_cursor:
                break
            cursor = str(next_cursor)
        logger.info("Remnawave stream loaded %s users", len(users))
        return users
    except Exception as e:
        logger.warning("Remnawave /users/stream failed (%s); falling back to paginated /users", e)

    # Fallback: offset pagination
    start = 0
    while True:
        try:
            response = await sdk.users.get_all_users(start=start, size=page_size)
        except Exception as e:
            _log_rw_error("get_all_users", f"start={start}", e)
            break
        batch = getattr(response, "users", None) or []
        if not batch:
            break
        for u in batch:
            raw = u.model_dump(by_alias=True) if hasattr(u, "model_dump") else dict(u)
            users.append(_normalize_user(raw if isinstance(raw, dict) else {}))
            if not users[-1].get("username") and hasattr(u, "username"):
                users[-1] = {
                    "uuid": str(getattr(u, "uuid", "")),
                    "username": getattr(u, "username", None),
                    "subscription_url": getattr(u, "subscription_url", None),
                    "expire": getattr(u, "expire_at", None),
                    "status": "active",
                }
        if len(batch) < page_size:
            break
        start += page_size
    logger.info("Remnawave paginated /users loaded %s users", len(users))
    return users


async def build_username_index(
    needed: set[str] | None = None,
    *,
    page_size: int = 250,
) -> dict[str, dict[str, Any] | None]:
    """Map username → user dict.

    If ``needed`` is set, stream until all needed usernames are found (or stream ends).
    Missing usernames are stored as ``None`` so callers can skip per-user GETs.
    """
    index: dict[str, dict[str, Any] | None] = {}
    if needed is not None:
        for name in needed:
            index[name] = None

    sdk = get_sdk()
    client = sdk._client
    page_size = max(1, min(int(page_size), 1000))
    remaining = set(needed) if needed is not None else None

    try:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"size": page_size}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get("/users/stream", params=params, timeout=60.0)
            if resp.status_code == 404:
                raise RuntimeError("stream endpoint not available")
            resp.raise_for_status()
            data = resp.json()
            payload = data.get("response") if isinstance(data, dict) else data
            batch = (payload or {}).get("users") or []
            for u in batch:
                if not isinstance(u, dict):
                    continue
                norm = _normalize_user(u)
                uname = norm.get("username")
                if not uname:
                    continue
                if remaining is None:
                    index[uname] = norm
                elif uname in remaining:
                    index[uname] = norm
                    remaining.discard(uname)
            next_cursor = (payload or {}).get("nextCursor")
            has_more = bool((payload or {}).get("hasMore"))
            if remaining is not None and not remaining:
                break
            if not has_more or not next_cursor:
                break
            cursor = str(next_cursor)
        logger.info(
            "Remnawave username index via stream: matched=%s needed=%s",
            sum(1 for v in index.values() if v),
            len(needed) if needed is not None else "all",
        )
        return index
    except Exception as e:
        logger.warning("Stream index failed (%s); using paginated fallback", e)

    # Fallback full scan with get_all_users
    start = 0
    while True:
        try:
            response = await sdk.users.get_all_users(start=start, size=page_size)
        except Exception as exc:
            _log_rw_error("get_all_users", f"start={start}", exc)
            break
        batch = getattr(response, "users", None) or []
        if not batch:
            break
        for u in batch:
            uname = getattr(u, "username", None)
            if not uname:
                continue
            norm = {
                "uuid": str(getattr(u, "uuid", "")),
                "username": uname,
                "subscription_url": getattr(u, "subscription_url", None),
                "expire": getattr(u, "expire_at", None),
                "status": "active",
            }
            if remaining is None:
                index[uname] = norm
            elif uname in remaining:
                index[uname] = norm
                remaining.discard(uname)
        if remaining is not None and not remaining:
            break
        if len(batch) < page_size:
            break
        start += page_size
    return index
