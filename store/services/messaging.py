"""Sync and send marketplace chat messages."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

import store.database.requests as rq
from store.integrations.providers import digiseller, ggsel
from store.notify import send_inbox_tg_notify

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


def normalize_unread_chat(marketplace: str, row: dict) -> dict | None:
    chat_id = row.get("id_i") or row.get("content_id") or row.get("inv")
    if chat_id is None:
        return None
    try:
        cnt_new = int(row.get("cnt_new") or 0)
    except (TypeError, ValueError):
        cnt_new = 0
    if cnt_new <= 0:
        return None
    return {
        "marketplace": marketplace,
        "chat_id": str(chat_id),
        "email": row.get("email"),
        "cnt_new": cnt_new,
        "last_at": _parse_dt(row.get("last_date") or row.get("last_message")),
    }


async def _fetch_unread_pages(adapter, marketplace: str, *, max_pages: int = 5) -> list[dict]:
    items: list[dict] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
        for page in range(1, max_pages + 1):
            rows = await adapter.chats(http, filter_new=True, page=page, page_size=50)
            if not rows:
                break
            for row in rows:
                normalized = normalize_unread_chat(marketplace, row)
                if normalized:
                    items.append(normalized)
            if len(rows) < 50:
                break
    return items


async def poll_unread_chats() -> dict:
    """Lightweight unread poll for Digiseller + GGSel; updates alerts and notifies TG."""
    summary = {"ggsel": 0, "digiseller": 0, "notified": 0, "errors": []}
    for marketplace, adapter in (("ggsel", ggsel), ("digiseller", digiseller)):
        try:
            unread = await _fetch_unread_pages(adapter, marketplace)
        except Exception as exc:
            logger.exception("Unread poll failed for %s", marketplace)
            summary["errors"].append(f"{marketplace}: {exc}")
            continue
        active_ids = {item["chat_id"] for item in unread}
        summary[marketplace] = len(unread)
        for item in unread:
            order = await rq.resolve_order_for_chat(marketplace, item["chat_id"])
            alert = await rq.upsert_chat_alert(
                marketplace=marketplace,
                chat_id=item["chat_id"],
                cnt_new=item["cnt_new"],
                email=item.get("email"),
                last_message_at=item.get("last_at"),
                order_id=order.id if order else None,
                customer_id=order.customer_id if order else None,
            )
            if item["cnt_new"] > (alert.last_notified_cnt_new or 0):
                who = item.get("email") or f"chat {item['chat_id']}"
                hint = f"customer #{alert.customer_id}" if alert.customer_id else f"chat {item['chat_id']}"
                try:
                    await send_inbox_tg_notify(
                        f"<b>{marketplace}</b>: {item['cnt_new']} unread from {who}\n"
                        f"Open Inbox → {hint}"
                    )
                    await rq.mark_chat_alert_notified(alert.id, item["cnt_new"])
                    summary["notified"] += 1
                except Exception:
                    logger.exception("TG inbox notify failed for %s/%s", marketplace, item["chat_id"])
        await rq.zero_missing_chat_alerts(marketplace, active_ids)
    return summary


async def acknowledge_customer_alerts(customer_id: int) -> None:
    """Mark marketplace chats as seen and clear local alerts after admin opens a thread."""
    alerts = await rq.clear_chat_alerts_for_customer(customer_id)
    if not alerts:
        return
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
        for alert in alerts:
            adapter = ggsel if alert["marketplace"] == "ggsel" else digiseller
            try:
                await adapter.mark_seen(http, alert["chat_id"])
            except Exception:
                logger.exception("mark_seen failed for %s/%s", alert["marketplace"], alert["chat_id"])


async def sync_order_messages(order_id: int) -> int:
    order = None
    async with rq.get_session() as session:
        from store.database.models import Order

        order = await session.get(Order, order_id)
        if order is None:
            return 0
        marketplace = order.marketplace
        chat_id = order.content_id or order.chat_id or order.external_order_id
        customer_id = order.customer_id
        provider_order_id = order.provider_order_id

    count = 0
    if marketplace == "ggsel":
        async with aiohttp.ClientSession() as http:
            messages = await ggsel.messages(http, int(chat_id))
            for m in messages:
                count += await _store_msg("ggsel", m, order_id, customer_id, chat_id)
    elif marketplace == "digiseller":
        async with aiohttp.ClientSession() as http:
            messages = await digiseller.messages(http, provider_order_id or chat_id)
            for m in messages:
                count += await _store_msg("digiseller", m, order_id, customer_id, chat_id)
    return count


async def sync_customer_messages(customer_id: int) -> int:
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
        chat_id = order.content_id or order.chat_id or order.external_order_id
        customer_id = order.customer_id
        provider_order_id = order.provider_order_id

    status = 400
    if marketplace == "ggsel":
        async with aiohttp.ClientSession() as http:
            await ggsel.send_message(http, int(chat_id), text)
            status = 200
    elif marketplace == "digiseller":
        async with aiohttp.ClientSession() as http:
            await digiseller.send_message(http, provider_order_id or chat_id, text)
            status = 200

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
