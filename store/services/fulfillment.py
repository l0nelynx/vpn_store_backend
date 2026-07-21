"""Shared order fulfillment: Remnawave provision + Order ledger."""

from __future__ import annotations

import logging
from typing import Any

import store.api.remnawave.api as rem
import store.database.requests as rq
from store.notify import send_tg_alert
from store.settings import secrets

logger = logging.getLogger(__name__)


async def parse_order_params(
    item_id,
    options: list[dict],
    id_key: str = "id",
    data_key: str = "user_data_id",
    session=None,
) -> dict:
    result: dict[str, str] = {}
    for option in options:
        params = await rq.get_order_params_dict(
            item_id=item_id,
            param_id=option[id_key],
            user_data_id=option[data_key],
            session=session,
        )
        result.update(params)
    days = result.get("days")
    hwid = result.get("hwid")
    return {
        "days": int(days) if days is not None else None,
        "template": result.get("location") or result.get("internal_sq"),
        "hwid": int(hwid) if hwid is not None else None,
        "outer_squad": result.get("external_sq"),
    }


async def fulfill_order(
    *,
    marketplace: str,
    external_order_id: str,
    remnawave_username: str,
    days: int,
    email: str | None = None,
    invoice_id: str | None = None,
    item_id: int | None = None,
    options: list | None = None,
    amount: float | None = None,
    currency: str | None = None,
    chat_id: str | None = None,
    template: str | None = None,
    hwid: int | None = None,
    outer_squad: str | None = None,
    ggsel_buyer_id: str | None = None,
    digiseller_buyer_id: str | None = None,
    session=None,
) -> dict[str, Any]:
    """Idempotent provision.

    - Same (marketplace, external_order_id): return existing subscription, resend-safe.
    - Remnawave user already exists: extend expire by ``days`` from max(now, expire).
    - New user: create in Remnawave.

    Returns dict with keys: sub, order_id, remnawave_uuid, event (create|extend|existing), created.
    """
    days = days if days is not None else 30
    existing = await rq.get_order_by_external(
        marketplace, external_order_id, session=session
    )
    if existing and existing.subscription_url and existing.delivery_status == 1:
        return {
            "sub": existing.subscription_url,
            "order_id": existing.id,
            "remnawave_uuid": existing.remnawave_uuid,
            "event": "existing",
            "created": False,
        }
    # Undelivered but already provisioned — do not extend again
    if existing and existing.subscription_url and existing.remnawave_uuid:
        return {
            "sub": existing.subscription_url,
            "order_id": existing.id,
            "remnawave_uuid": existing.remnawave_uuid,
            "event": "resend",
            "created": False,
        }

    customer = await rq.get_or_create_customer(
        email=email,
        ggsel_buyer_id=ggsel_buyer_id,
        digiseller_buyer_id=digiseller_buyer_id,
        session=session,
    )

    order = existing
    if order is None:
        order = await rq.create_order(
            marketplace=marketplace,
            external_order_id=external_order_id,
            invoice_id=invoice_id,
            item_id=item_id,
            options=options,
            amount=amount,
            currency=currency,
            chat_id=chat_id or str(external_order_id),
            days_ordered=days,
            remnawave_username=remnawave_username,
            customer_id=customer.id,
            session=session,
        )

    rw_user = await rem.get_user_from_username(remnawave_username)
    event_type = "create"
    if rw_user and rw_user != 404 and rw_user.get("uuid"):
        extended = await rem.extend_user(rw_user["uuid"], days=days)
        if extended:
            event_type = "extend"
            sub_url = extended.get("subscription_url") or rw_user.get("subscription_url")
            rw_uuid = rw_user["uuid"]
        else:
            sub_url = rw_user.get("subscription_url")
            rw_uuid = rw_user["uuid"]
            event_type = "existing"
    else:
        created = await rem.create_user(
            username=remnawave_username,
            days=days,
            limit_gb=0,
            descr=f"created by store ({marketplace})",
            email=email or f"{remnawave_username}@store.local",
            squad_id=template or secrets.get("rw_free_id"),
            telegram_id=None,
            hwid_device_limit=hwid,
            external_squad_uuid=outer_squad,
        )
        if not created or not created.get("uuid"):
            logger.error("Failed to create Remnawave user for %s", remnawave_username)
            return {"sub": None, "order_id": order.id, "created": False, "event": "error"}
        sub_url = created["subscription_url"]
        rw_uuid = created["uuid"]
        event_type = "create"

    await rq.update_order(
        order.id,
        session=session,
        remnawave_uuid=str(rw_uuid),
        remnawave_username=remnawave_username,
        subscription_url=sub_url,
        days_ordered=days,
        customer_id=customer.id,
        chat_id=chat_id or order.chat_id or str(external_order_id),
        status="provisioned",
    )

    await rq.add_subscription_event(
        order.id,
        event_type,
        days=days,
        remnawave_uuid=str(rw_uuid),
        session=session,
    )

    await send_tg_alert(
        message=(
            f"<b>⚠️ New {marketplace} Order</b>\n"
            f"<b>🎫 OrderId: </b><code>{external_order_id}</code>\n"
            f"<b>👤 Email: </b><code>{email or 'None'}</code>\n"
            f"<b>📱 HWID Limit: </b><code>{hwid if hwid is not None else 'default'}</code>\n"
            f"<b>📆 Days: </b>{days} ({event_type})\n"
            f"<b>💻 UUID: </b><code>{rw_uuid}</code>\n"
            f"<b>🔗 Link: </b><code>{sub_url}</code>"
        ),
        store_name=marketplace.upper()[:8],
    )

    return {
        "sub": sub_url,
        "order_id": order.id,
        "remnawave_uuid": str(rw_uuid),
        "event": event_type,
        "created": event_type == "create",
    }


async def mark_delivered(order_id: int, session=None) -> None:
    await rq.update_order(
        order_id,
        delivery_status=1,
        status="delivered",
        session=session,
    )
