"""Pull recent marketplace sales into Store DB (adopt, no buyer spam)."""

from __future__ import annotations

import logging

import aiohttp

import store.api.aio_ggsel as ggsel
import store.api.digiseller_client as dig
import store.database.requests as rq
from store.services.fulfillment import fulfill_order, parse_order_params
from store.settings import secrets

logger = logging.getLogger(__name__)


async def sync_ggsel_orders(top: int = 50) -> dict:
    base = secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
    adopted = created = skipped = errors = 0
    async with aiohttp.ClientSession(base_url=base) as http:
        token = await ggsel.get_token(http)
        last = await ggsel.return_last_sales(http, top=top, token=token)
        for sale in last.get("sales") or []:
            try:
                order_info = await ggsel.get_order_info(http, sale["invoice_id"], token)
                content = order_info.get("content") or {}
                content_id = content.get("content_id")
                if content_id is None:
                    skipped += 1
                    continue
                state = content.get("invoice_state")
                if state is not None and not (3 <= int(state) <= 4):
                    skipped += 1
                    continue
                existing = await rq.get_order_by_external("ggsel", str(content_id))
                if existing and existing.delivery_status == 1:
                    skipped += 1
                    continue
                options = content.get("options") or []
                item_id = content.get("item_id")
                buyer = content.get("buyer_info") or {}
                params = await parse_order_params(
                    item_id=item_id,
                    options=options,
                    id_key="id",
                    data_key="user_data_id",
                )
                days = params["days"] if params["days"] is not None else 30
                result = await fulfill_order(
                    marketplace="ggsel",
                    external_order_id=str(content_id),
                    remnawave_username=f"gg_id{content_id}",
                    days=days,
                    email=buyer.get("email"),
                    invoice_id=str(content.get("invoice_id") or sale["invoice_id"]),
                    item_id=item_id,
                    options=options,
                    chat_id=str(content_id),
                    template=params["template"],
                    hwid=params["hwid"],
                    outer_squad=params["outer_squad"],
                    ggsel_buyer_id=str(buyer.get("buyer_id") or content_id),
                    allow_extend=False,
                )
                if result.get("event") == "create":
                    created += 1
                elif result.get("event") == "adopted":
                    adopted += 1
                else:
                    skipped += 1
            except Exception as e:
                errors += 1
                logger.error("sync_ggsel_orders sale error: %s", e)
    return {"marketplace": "ggsel", "top": top, "adopted": adopted, "created": created, "skipped": skipped, "errors": errors}


async def sync_digiseller_orders(top: int = 50) -> dict:
    """Best-effort: Digiseller seller-last-sales (same shape as GGsel when available)."""
    adopted = created = skipped = errors = 0
    async with aiohttp.ClientSession() as http:
        token = await dig.get_token(http)
        if not token:
            return {
                "marketplace": "digiseller",
                "top": top,
                "adopted": 0,
                "created": 0,
                "skipped": 0,
                "errors": 1,
                "detail": "dig_seller_id / dig_api_key not configured",
            }
        sales = await dig.list_last_sales(http, token, top=top)
        for sale in sales:
            try:
                inv = sale.get("invoice_id") or sale.get("inv") or sale.get("id_i")
                item_id = sale.get("id_goods") or sale.get("id") or sale.get("item_id")
                if inv is None:
                    skipped += 1
                    continue
                existing = await rq.get_order_by_external("digiseller", str(inv))
                if existing and existing.delivery_status == 1:
                    skipped += 1
                    continue
                # Minimal adopt by Remnawave username dig_id{inv}
                email = sale.get("email") or sale.get("buyer_email")
                options = sale.get("options") or []
                params = {"days": 30, "template": None, "hwid": None, "outer_squad": None}
                if item_id is not None and options:
                    params = await parse_order_params(
                        item_id=int(item_id),
                        options=options,
                        id_key="id",
                        data_key="user_data",
                    )
                days = params["days"] if params.get("days") is not None else 30
                result = await fulfill_order(
                    marketplace="digiseller",
                    external_order_id=str(inv),
                    remnawave_username=f"dig_id{inv}",
                    days=days,
                    email=email,
                    invoice_id=str(inv),
                    item_id=int(item_id) if item_id is not None else None,
                    options=options or None,
                    chat_id=str(inv),
                    template=params.get("template"),
                    hwid=params.get("hwid"),
                    outer_squad=params.get("outer_squad"),
                    digiseller_buyer_id=str(sale.get("buyer_id") or inv),
                    allow_extend=False,
                )
                if result.get("event") == "create":
                    created += 1
                elif result.get("event") == "adopted":
                    adopted += 1
                else:
                    skipped += 1
            except Exception as e:
                errors += 1
                logger.error("sync_digiseller_orders sale error: %s", e)
    return {
        "marketplace": "digiseller",
        "top": top,
        "adopted": adopted,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


async def sync_all_orders(top: int = 50) -> dict:
    g = await sync_ggsel_orders(top=top)
    d = await sync_digiseller_orders(top=top)
    return {"ggsel": g, "digiseller": d}
