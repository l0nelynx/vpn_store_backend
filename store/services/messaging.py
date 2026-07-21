"""Sync and send marketplace chat messages."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

import store.api.aio_ggsel as ggsel
import store.api.digiseller_client as dig
import store.database.requests as rq
from store.settings import secrets

logger = logging.getLogger(__name__)


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def sync_order_messages(order_id: int) -> int:
    order = None
    async with rq.get_session() as session:
        from store.database.models import Order

        order = await session.get(Order, order_id)
        if order is None:
            return 0
        marketplace = order.marketplace
        chat_id = order.chat_id or order.external_order_id
        customer_id = order.customer_id
        external_order_id = order.external_order_id

    count = 0
    if marketplace == "ggsel":
        base = secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
        async with aiohttp.ClientSession(base_url=base) as http:
            token = await ggsel.get_token(http)
            messages = await ggsel.list_messages(http, token, int(chat_id))
            for m in messages:
                count += await _store_msg(
                    "ggsel", m, order_id, customer_id, chat_id
                )
    elif marketplace == "digiseller":
        async with aiohttp.ClientSession() as http:
            token = await dig.get_token(http)
            if not token:
                return 0
            messages = await dig.list_messages(http, token, chat_id)
            for m in messages:
                count += await _store_msg(
                    "digiseller", m, order_id, customer_id, chat_id
                )
    return count


async def sync_customer_messages(customer_id: int) -> int:
    orders = await rq.list_orders(limit=50)
    # filter in python — list_orders doesn't filter by customer_id yet
    async with rq.get_session() as session:
        from sqlalchemy import select
        from store.database.models import Order

        rows = (
            await session.scalars(select(Order).where(Order.customer_id == customer_id))
        ).all()
    total = 0
    for o in rows:
        total += await sync_order_messages(o.id)
    return total


async def _store_msg(
    marketplace: str,
    raw: dict,
    order_id: int,
    customer_id: int | None,
    chat_id: str,
) -> int:
    msg_id = raw.get("id") or raw.get("id_message")
    buyer = raw.get("buyer")
    seller = raw.get("seller")
    if buyer in (1, True, "1"):
        direction = "inbound"
    elif seller in (1, True, "1"):
        direction = "outbound"
    else:
        direction = "inbound" if raw.get("from") == "buyer" else "outbound"
    body = raw.get("message") or raw.get("text") or ""
    await rq.upsert_message(
        marketplace=marketplace,
        external_msg_id=str(msg_id) if msg_id is not None else None,
        direction=direction,
        body=body,
        chat_id=str(chat_id),
        order_id=order_id,
        customer_id=customer_id,
        is_file=bool(raw.get("is_file")),
        file_url=raw.get("url"),
        written_at=_parse_dt(raw.get("date_written") or raw.get("date")),
    )
    return 1


async def send_to_order(order_id: int, text: str) -> dict:
    async with rq.get_session() as session:
        from store.database.models import Order

        order = await session.get(Order, order_id)
        if order is None:
            return {"ok": False, "error": "order not found"}
        marketplace = order.marketplace
        chat_id = order.chat_id or order.external_order_id
        customer_id = order.customer_id

    status = 400
    if marketplace == "ggsel":
        base = secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
        async with aiohttp.ClientSession(base_url=base) as http:
            token = await ggsel.get_token(http)
            status = await ggsel.send_message(http, int(chat_id), text, token)
    elif marketplace == "digiseller":
        async with aiohttp.ClientSession() as http:
            token = await dig.get_token(http)
            if not token:
                return {"ok": False, "error": "digiseller token unavailable"}
            status = await dig.send_message(http, token, chat_id, text)

    if status == 200:
        await rq.upsert_message(
            marketplace=marketplace,
            external_msg_id=None,
            direction="outbound",
            body=text,
            chat_id=str(chat_id),
            order_id=order_id,
            customer_id=customer_id,
            written_at=datetime.now(timezone.utc),
        )
        return {"ok": True, "status": status}
    return {"ok": False, "status": status}


async def broadcast_to_recipients(recipients: list[dict], text: str, dry_run: bool = False) -> dict:
    delivered = failed = skipped = 0
    details = []
    for r in recipients:
        order_id = r.get("order_id")
        chat_id = r.get("chat_id")
        if not order_id or not chat_id:
            skipped += 1
            details.append({**r, "result": "skipped"})
            continue
        if dry_run:
            delivered += 1
            details.append({**r, "result": "dry_run"})
            continue
        res = await send_to_order(order_id, text)
        if res.get("ok"):
            delivered += 1
            details.append({**r, "result": "delivered"})
        else:
            failed += 1
            details.append({**r, "result": "failed", "error": res})
    return {
        "delivered": delivered,
        "failed": failed,
        "skipped": skipped,
        "details": details,
    }
