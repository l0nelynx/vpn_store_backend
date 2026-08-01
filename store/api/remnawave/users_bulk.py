"""Bulk Remnawave user lookup via /api/users/stream (cursor) with fallback pagination."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from store.api.remnawave.api import get_sdk, _log_rw_error
from store.database.models import Order, async_session

logger = logging.getLogger(__name__)


def _normalize_user(raw: Any) -> dict[str, Any]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(by_alias=True)
    if not isinstance(raw, dict):
        raw = {}
    username = raw.get("username")
    user_id = raw.get("id")
    sub = raw.get("subscriptionUrl") or raw.get("subscription_url")
    expire = raw.get("expireAt") or raw.get("expire_at")
    status = raw.get("status")
    status_value = getattr(status, "value", status)
    return {
        "id": int(user_id) if user_id is not None else None,
        "username": username,
        "subscription_url": sub,
        "expire": expire,
        "status": str(status_value or "active").lower(),
    }


async def stream_all_users(page_size: int = 250) -> list[dict[str, Any]]:
    """Fetch all panel users via GET /api/users/stream (cursor pagination).

    Falls back to GET /api/users?start=&size= if stream is unavailable.
    """
    sdk = get_sdk()
    page_size = max(1, min(int(page_size), 1000))
    users: list[dict] = []

    # Prefer cursor stream
    try:
        cursor: int | None = None
        while True:
            response = await sdk.users.get_users_stream(size=page_size, cursor=cursor)
            batch = response.users or []
            for u in batch:
                users.append(_normalize_user(u))
            next_cursor = response.next_cursor
            has_more = response.has_more
            if not has_more or not next_cursor:
                break
            cursor = int(next_cursor)
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
            users.append(_normalize_user(u))
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
    page_size = max(1, min(int(page_size), 1000))
    remaining = set(needed) if needed is not None else None

    try:
        cursor: int | None = None
        while True:
            response = await sdk.users.get_users_stream(size=page_size, cursor=cursor)
            batch = response.users or []
            for u in batch:
                norm = _normalize_user(u)
                uname = norm.get("username")
                if not uname:
                    continue
                if remaining is None:
                    index[uname] = norm
                elif uname in remaining:
                    index[uname] = norm
                    remaining.discard(uname)
            next_cursor = response.next_cursor
            has_more = response.has_more
            if remaining is not None and not remaining:
                break
            if not has_more or not next_cursor:
                break
            cursor = int(next_cursor)
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
            norm = _normalize_user(u)
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


async def backfill_order_user_ids() -> dict[str, int]:
    """Resolve legacy Store orders to Remnawave 3 numeric ids by username."""
    async with async_session() as session:
        usernames = set(await session.scalars(
            select(Order.remnawave_username).where(
                Order.remnawave_user_id.is_(None),
                Order.remnawave_username.is_not(None),
            ).distinct()
        ))
    usernames.discard(None)
    if not usernames:
        return {"candidates": 0, "updated": 0, "unresolved": 0}

    index = await build_username_index(set(usernames))
    updated = 0
    async with async_session() as session:
        orders = list((await session.scalars(select(Order).where(
            Order.remnawave_user_id.is_(None),
            Order.remnawave_username.in_(usernames),
        ))).all())
        for order in orders:
            user = index.get(order.remnawave_username)
            if user and user.get("id") is not None:
                order.remnawave_user_id = int(user["id"])
                updated += 1
        await session.commit()
    unresolved = sum(1 for name in usernames if not index.get(name))
    logger.info(
        "Remnawave v3 id backfill: candidates=%s updated=%s unresolved=%s",
        len(usernames),
        updated,
        unresolved,
    )
    return {"candidates": len(usernames), "updated": updated, "unresolved": unresolved}
