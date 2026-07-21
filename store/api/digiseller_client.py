"""Digiseller HTTP client (catalog, debates)."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import aiohttp

from store.settings import secrets

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return (secrets.get("dig_url") or "https://api.digiseller.com").rstrip("/")


async def get_token(session: aiohttp.ClientSession) -> str | None:
    """Digiseller token via seller_id + api_key SHA256."""
    seller_id = secrets.get("dig_seller_id")
    api_key = secrets.get("dig_api_key")
    if not seller_id or not api_key:
        logger.warning("dig_seller_id / dig_api_key not configured")
        return None
    ts = int(time.time())
    sign = hashlib.sha256(f"{api_key}{ts}".encode()).hexdigest()
    url = f"{_base_url()}/api/apilogin"
    payload = {"seller_id": int(seller_id), "timestamp": ts, "sign": sign}
    async with session.post(url, json=payload, headers={"Accept": "application/json"}) as resp:
        data = await resp.json(content_type=None)
        token = data.get("token") or (data.get("retval") and data.get("token"))
        if not token and isinstance(data, dict):
            token = data.get("token")
        return token


async def list_seller_goods(session: aiohttp.ClientSession, token: str) -> list[dict]:
    url = f"{_base_url()}/api/seller-goods"
    payload = {
        "id_seller": int(secrets.get("dig_seller_id") or 0),
        "page": 1,
        "rows": 1000,
        "currency": "RUR",
        "lang": "ru-RU",
        "show_hidden": 1,
    }
    async with session.post(
        f"{url}?token={token}",
        json=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    ) as resp:
        data = await resp.json(content_type=None)
        rows = data.get("rows") or data.get("retval") or data.get("goods") or []
        if isinstance(rows, dict):
            rows = rows.get("row") or rows.get("goods") or []
        return rows if isinstance(rows, list) else []


async def list_chats(session: aiohttp.ClientSession, token: str) -> list[dict]:
    url = f"{_base_url()}/api/debates/v2/chats?token={token}"
    async with session.get(url, headers={"Accept": "application/json"}) as resp:
        data = await resp.json(content_type=None)
        if isinstance(data, list):
            return data
        return data.get("chats") or data.get("items") or []


async def list_messages(
    session: aiohttp.ClientSession,
    token: str,
    id_i: int | str,
    count: int = 50,
) -> list[dict]:
    url = f"{_base_url()}/api/debates/v2?token={token}&id_i={id_i}&count={count}"
    async with session.get(url, headers={"Accept": "application/json"}) as resp:
        if resp.status != 200:
            return []
        data = await resp.json(content_type=None)
        if isinstance(data, list):
            return data
        return data.get("items") or data.get("messages") or []


async def send_message(
    session: aiohttp.ClientSession,
    token: str,
    id_i: int | str,
    message: str,
) -> int:
    url = f"{_base_url()}/api/debates/v2?token={token}&id_i={id_i}"
    async with session.post(
        url,
        json={"message": message},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    ) as resp:
        return resp.status
