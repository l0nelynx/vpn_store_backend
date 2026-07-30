"""Sync marketplace product option/variant names into product_option_labels (API v1)."""

from __future__ import annotations

import logging

import aiohttp

import store.database.requests as rq
from store.api.options_v1 import get_product_option, list_product_options, localized_name, variant_id
from store.integrations.providers import digiseller
from store.settings import secrets

logger = logging.getLogger(__name__)


async def _fetch_and_store_product(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    marketplace: str,
    item_id: int,
    item_name: str | None,
    token: str | None = None,
    authorization: str | None = None,
) -> dict:
    options = 0
    variants = 0
    errors = 0
    try:
        opt_list = await list_product_options(
            session,
            base_url=base_url,
            product_id=item_id,
            token=token,
            authorization=authorization,
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
                session,
                base_url=base_url,
                option_id=param_id,
                token=token,
                authorization=authorization,
            )
            variants_raw = (detail or {}).get("variants") or []
            if not variants_raw and detail is None:
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
        token = await digiseller.token(http)
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
    """Sync option/variant names via GGsel Seller API v2.

    ``/api/products/options`` on seller.ggsel.com is a different auth gate
    (``Authentication required``) and does not accept ``ggsel_api_key``.
    """
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

    from store.api import ggsel_options_v2 as ggsel_v2

    ggsel_base = (secrets.get("ggsel_base_url") or "https://seller.ggsel.com").rstrip("/")
    base = (secrets.get("ggsel_options_url") or ggsel_base).rstrip("/")
    ggsel_key = secrets.get("ggsel_api_key")
    if not ggsel_key:
        return {
            "marketplace": "ggsel",
            "products": 0,
            "options": 0,
            "variants": 0,
            "errors": 1,
            "detail": "ggsel_api_key not configured",
        }

    api_key = str(ggsel_key)
    total_opt = total_var = total_err = 0
    synced_offers = 0

    async with aiohttp.ClientSession() as http:
        # Auth smoke-test against v2 (different gate than /api/products/options)
        offers = await ggsel_v2.list_offers(http, base_url=base, api_key=api_key)
        if not offers:
            url = f"{base}/api_sellers/v2/offers"
            async with http.get(
                url, headers={"Accept": "application/json", "Authorization": api_key}
            ) as resp:
                if resp.status in (401, 403):
                    body = await resp.text()
                    return {
                        "marketplace": "ggsel",
                        "products": len(products),
                        "options": 0,
                        "variants": 0,
                        "errors": 1,
                        "detail": (
                            f"GGsel v2 auth failed HTTP {resp.status}: {body[:200]}. "
                            "Use Seller API key from seller.ggsel.com admin as ggsel_api_key "
                            "(Authorization header)."
                        ),
                        "token_source": "ggsel_api_key_authorization_v2",
                        "options_base": f"{base}/api_sellers/v2/offers/{{id}}/options",
                    }
            # Empty offer list with 2xx — still try product external_item_id as offer_id

        for p in products:
            oid = p["external_item_id"]
            try:
                options = await ggsel_v2.list_offer_options(
                    http, base_url=base, api_key=api_key, offer_id=oid
                )
                if not options:
                    continue
                synced_offers += 1
                pairs = ggsel_v2.iter_option_variants(options)
                seen_params: set[int] = set()
                for param_id, pname, user_data_id, vname in pairs:
                    seen_params.add(param_id)
                    await rq.upsert_product_option_label(
                        marketplace="ggsel",
                        item_id=oid,
                        param_id=param_id,
                        user_data_id=user_data_id,
                        item_name=p.get("name"),
                        param_name=pname,
                        variant_name=vname,
                    )
                    total_var += 1
                total_opt += len(seen_params)
            except Exception as e:
                total_err += 1
                logger.error("GGsel v2 option sync offer %s: %s", oid, e)

    return {
        "marketplace": "ggsel",
        "products": len(products),
        "offers_synced": synced_offers,
        "options": total_opt,
        "variants": total_var,
        "errors": total_err,
        "token_source": "ggsel_api_key_authorization_v2",
        "options_base": f"{base}/api_sellers/v2/offers/{{id}}/options",
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
