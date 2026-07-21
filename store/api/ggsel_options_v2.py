"""GGsel Seller API v2 — offer options (for Parameters sync).

Legacy Digiseller-style ``/api/products/options`` on seller.ggsel.com uses a
different auth gate (``Authentication required``) and does not accept the
seller ``ggsel_api_key`` / apilogin token. Options must be fetched via v2.
"""

from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": api_key,
    }


def option_title(opt: dict) -> str | None:
    return (
        (opt.get("title_ru") or opt.get("title_en") or opt.get("title") or "")
        or None
    )


def variant_title(var: dict) -> str | None:
    return (
        (var.get("title_ru") or var.get("title_en") or var.get("title") or "")
        or None
    )


async def list_offers(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    api_key: str,
) -> list[dict]:
    """GET /api_sellers/v2/offers"""
    url = f"{base_url.rstrip('/')}/api_sellers/v2/offers"
    async with session.get(url, headers=_auth_headers(api_key)) as resp:
        if resp.status != 200:
            body = await resp.text()
            logger.warning("GGsel v2 list offers HTTP %s: %s", resp.status, body[:300])
            return []
        data = await resp.json(content_type=None)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "items", "offers", "result"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []


async def list_offer_options(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    api_key: str,
    offer_id: int,
) -> list[dict]:
    """GET /api_sellers/v2/offers/{offer_id}/options — options with variants."""
    url = f"{base_url.rstrip('/')}/api_sellers/v2/offers/{int(offer_id)}/options"
    async with session.get(url, headers=_auth_headers(api_key)) as resp:
        if resp.status != 200:
            body = await resp.text()
            logger.warning(
                "GGsel v2 options HTTP %s for offer %s: %s",
                resp.status,
                offer_id,
                body[:300],
            )
            return []
        data = await resp.json(content_type=None)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "items", "options", "result"):
                if isinstance(data.get(key), list):
                    return data[key]
            # single option object
            if data.get("id") is not None and data.get("variants") is not None:
                return [data]
        return []


def iter_option_variants(options: list[dict]) -> list[tuple[int, str | None, int, str | None]]:
    """Yield (param_id, param_name, user_data_id, variant_name)."""
    out: list[tuple[int, str | None, int, str | None]] = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        oid = opt.get("id")
        if oid is None:
            continue
        try:
            param_id = int(oid)
        except (TypeError, ValueError):
            continue
        pname = option_title(opt)
        for var in opt.get("variants") or []:
            if not isinstance(var, dict):
                continue
            vid = var.get("id")
            if vid is None:
                continue
            try:
                user_data_id = int(vid)
            except (TypeError, ValueError):
                continue
            out.append((param_id, pname, user_data_id, variant_title(var)))
    return out
