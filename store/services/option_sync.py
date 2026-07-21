"""Sync marketplace product option/variant names into product_option_labels (API v1)."""

from __future__ import annotations

import logging

import aiohttp

import store.api.aio_ggsel as ggsel
import store.api.digiseller_client as dig
import store.database.requests as rq
from store.api.options_v1 import get_product_option, list_product_options, localized_name, variant_id
from store.settings import secrets

logger = logging.getLogger(__name__)


async def _fetch_and_store_product(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    token: str,
    marketplace: str,
    item_id: int,
    item_name: str | None,
) -> dict:
    options = 0
    variants = 0
    errors = 0
    try:
        opt_list = await list_product_options(
            session, base_url=base_url, token=token, product_id=item_id
        )
    except Exception as e:
        logger.error("list options %s/%s: %s", marketplace, item_id, e)
        return {"item_id": item_id, "options": 0, "variants": 0, "errors": 1}

    for opt in opt_list:
        try:
            oid = opt.get("id")
            if oid is None:
                continue
            param_id = int(oid)
            param_name = localized_name(opt.get("name"))
            detail = await get_product_option(
                session, base_url=base_url, token=token, option_id=param_id
            )
            variants_raw = (detail or {}).get("variants") or []
            if not variants_raw and detail is None:
                # list-only fallback: no variants known
                continue
            options += 1
            if not param_name and detail:
                param_name = localized_name(detail.get("name"))
            for var in variants_raw:
                vid = variant_id(var)
                if vid is None:
                    continue
                await rq.upsert_product_option_label(
                    marketplace=marketplace,
                    item_id=item_id,
                    param_id=param_id,
                    user_data_id=vid,
                    item_name=item_name,
                    param_name=param_name,
                    variant_name=localized_name(var.get("name")),
                )
                variants += 1
        except Exception as e:
            errors += 1
            logger.error("option sync %s/%s: %s", marketplace, item_id, e)

    return {
        "item_id": item_id,
        "options": options,
        "variants": variants,
        "errors": errors,
    }


async def sync_digiseller_options(
    *,
    item_id: int | None = None,
) -> dict:
    products = await rq.list_products(marketplace="digiseller")
    if item_id is not None:
        products = [p for p in products if p["external_item_id"] == item_id]
    if not products:
        return {
            "marketplace": "digiseller",
            "products": 0,
            "options": 0,
            "variants": 0,
            "errors": 0,
            "detail": "no digiseller products in DB — sync catalog first",
        }

    async with aiohttp.ClientSession() as http:
        token = await dig.get_token(http)
        if not token:
            return {
                "marketplace": "digiseller",
                "products": 0,
                "options": 0,
                "variants": 0,
                "errors": 1,
                "detail": "dig_seller_id / dig_api_key not configured",
            }
        base = (secrets.get("dig_url") or "https://api.digiseller.com").rstrip("/")
        total_opt = total_var = total_err = 0
        for p in products:
            r = await _fetch_and_store_product(
                http,
                base_url=base,
                token=token,
                marketplace="digiseller",
                item_id=p["external_item_id"],
                item_name=p.get("name"),
            )
            total_opt += r["options"]
            total_var += r["variants"]
            total_err += r["errors"]
        return {
            "marketplace": "digiseller",
            "products": len(products),
            "options": total_opt,
            "variants": total_var,
            "errors": total_err,
        }


async def sync_ggsel_options(
    *,
    item_id: int | None = None,
) -> dict:
    products = await rq.list_products(marketplace="ggsel")
    if item_id is not None:
        products = [p for p in products if p["external_item_id"] == item_id]
    if not products:
        return {
            "marketplace": "ggsel",
            "products": 0,
            "options": 0,
            "variants": 0,
            "errors": 0,
            "detail": "no ggsel products in DB — sync catalog first",
        }

    # Digiseller-compatible v1 options host; auth: dig token preferred, else GGsel token
    base = (
        secrets.get("ggsel_options_url")
        or secrets.get("dig_url")
        or "https://api.digiseller.com"
    ).rstrip("/")

    async with aiohttp.ClientSession() as http:
        token = await dig.get_token(http)
        token_src = "dig"
        if not token:
            ggsel_base = secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
            async with aiohttp.ClientSession(base_url=ggsel_base) as ghttp:
                try:
                    token = await ggsel.get_token(ghttp)
                    token_src = "ggsel"
                except Exception as e:
                    return {
                        "marketplace": "ggsel",
                        "products": 0,
                        "options": 0,
                        "variants": 0,
                        "errors": 1,
                        "detail": f"no dig/ggsel token: {e}",
                    }

        total_opt = total_var = total_err = 0
        for p in products:
            r = await _fetch_and_store_product(
                http,
                base_url=base,
                token=token,
                marketplace="ggsel",
                item_id=p["external_item_id"],
                item_name=p.get("name"),
            )
            total_opt += r["options"]
            total_var += r["variants"]
            total_err += r["errors"]
        return {
            "marketplace": "ggsel",
            "products": len(products),
            "options": total_opt,
            "variants": total_var,
            "errors": total_err,
            "token_source": token_src,
            "options_base": base,
        }


async def sync_product_options(
    *,
    marketplace: str | None = None,
    item_id: int | None = None,
) -> dict:
    if marketplace == "ggsel":
        return {"ggsel": await sync_ggsel_options(item_id=item_id)}
    if marketplace == "digiseller":
        return {"digiseller": await sync_digiseller_options(item_id=item_id)}
    g = await sync_ggsel_options(item_id=item_id)
    d = await sync_digiseller_options(item_id=item_id)
    return {"ggsel": g, "digiseller": d}
