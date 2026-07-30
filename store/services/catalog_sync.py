"""Sync product catalogs from Digiseller and GGsel."""

from __future__ import annotations

import json
import logging

import aiohttp

import store.database.requests as rq
from store.integrations.providers import digiseller, ggsel

logger = logging.getLogger(__name__)


def _item_fields(row: dict) -> tuple[int | None, str | None, float | None, str | None]:
    item_id = row.get("id_goods") or row.get("id") or row.get("item_id") or row.get("id_good")
    name = row.get("name") or row.get("name_goods") or row.get("title")
    price = row.get("price") or row.get("price_rub") or row.get("cost")
    currency = row.get("currency") or row.get("curr") or "RUR"
    try:
        item_id_int = int(item_id) if item_id is not None else None
    except (TypeError, ValueError):
        item_id_int = None
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    return item_id_int, name, price_f, currency


async def sync_ggsel_catalog() -> int:
    count = 0
    async with aiohttp.ClientSession() as session:
        rows = await ggsel.seller_goods(session)
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id, name, price, currency = _item_fields(row)
            if item_id is None:
                continue
            await rq.upsert_product(
                marketplace="ggsel",
                external_item_id=item_id,
                name=name,
                price=price,
                currency=currency,
                raw_json=json.dumps(row, ensure_ascii=False),
                is_hidden=bool(row.get("is_hidden") or row.get("hidden")),
            )
            count += 1
    logger.info("Synced %s GGsel products", count)
    return count


async def sync_digiseller_catalog() -> int:
    count = 0
    async with aiohttp.ClientSession() as session:
        rows = await digiseller.seller_goods(session)
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id, name, price, currency = _item_fields(row)
            if item_id is None:
                continue
            await rq.upsert_product(
                marketplace="digiseller",
                external_item_id=item_id,
                name=name,
                price=price,
                currency=currency,
                raw_json=json.dumps(row, ensure_ascii=False),
                is_hidden=bool(row.get("is_hidden") or row.get("hidden")),
            )
            count += 1
    logger.info("Synced %s Digiseller products", count)
    return count


async def sync_all_catalogs() -> dict:
    g = await sync_ggsel_catalog()
    d = await sync_digiseller_catalog()
    return {"ggsel": g, "digiseller": d}
