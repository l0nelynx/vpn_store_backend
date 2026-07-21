"""Digiseller / GGsel Seller API v1 product options helpers."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def localized_name(name_field: Any, prefer: str = "ru-RU") -> str | None:
    """Extract display string from Digiseller-style name locale array."""
    if name_field is None:
        return None
    if isinstance(name_field, str):
        return name_field.strip() or None
    if not isinstance(name_field, list):
        return None
    preferred = None
    first = None
    for entry in name_field:
        if not isinstance(entry, dict):
            continue
        val = entry.get("value")
        if not val:
            continue
        if first is None:
            first = str(val)
        if entry.get("locale") == prefer:
            preferred = str(val)
            break
    return preferred or first


async def list_product_options(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    token: str,
    product_id: int,
) -> list[dict]:
    """GET /api/products/options/list/{product_id} — v1."""
    url = f"{base_url.rstrip('/')}/api/products/options/list/{int(product_id)}?token={token}"
    async with session.get(url, headers={"Accept": "application/json"}) as resp:
        if resp.status != 200:
            body = await resp.text()
            logger.warning(
                "options list HTTP %s for product %s: %s",
                resp.status,
                product_id,
                body[:200],
            )
            return []
        data = await resp.json(content_type=None)
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, list):
            return content
        return []


async def get_product_option(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    token: str,
    option_id: int,
) -> dict | None:
    """GET /api/products/options/{option_id} — v1 (includes variants)."""
    url = f"{base_url.rstrip('/')}/api/products/options/{int(option_id)}?token={token}"
    async with session.get(url, headers={"Accept": "application/json"}) as resp:
        if resp.status != 200:
            body = await resp.text()
            logger.warning(
                "option detail HTTP %s for option %s: %s",
                resp.status,
                option_id,
                body[:200],
            )
            return None
        data = await resp.json(content_type=None)
        if not isinstance(data, dict):
            return None
        content = data.get("content")
        return content if isinstance(content, dict) else None


def variant_id(variant: dict) -> int | None:
    raw = variant.get("id")
    if raw is None:
        raw = variant.get("variant_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
