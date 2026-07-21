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
    allow_extend: bool = False,
) -> dict[str, Any]:
    """Idempotent provision.

    Policy:
    - Store order already delivered → no-op.
    - Store order provisioned but not delivered → ``resend`` (caller may chat once).
    - Remnawave username already exists (e.g. after empty DB migration) → **adopt**
      into Store as delivered: no extend, no buyer chat (``send_message`` skipped by caller).
    - Brand-new Remnawave user → create; caller sends delivery message.
    - ``allow_extend=True`` only for intentional renew paths (not GGsel last-sales poll).
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
            "should_notify_buyer": False,
        }
    if existing and existing.subscription_url and existing.remnawave_uuid:
        return {
            "sub": existing.subscription_url,
            "order_id": existing.id,
            "remnawave_uuid": existing.remnawave_uuid,
            "event": "resend",
            "created": False,
            "should_notify_buyer": existing.delivery_status != 1,
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
    should_notify = True

    if rw_user and rw_user.get("uuid"):
        rw_uuid = str(rw_user["uuid"])
        sub_url = rw_user.get("subscription_url")
        if allow_extend:
            extended = await rem.extend_user(rw_uuid, days=days)
            if extended:
                event_type = "extend"
                sub_url = extended.get("subscription_url") or sub_url
                should_notify = True
            else:
                event_type = "adopted"
                should_notify = False
        else:
            # Historical Remnawave user (or rediscovery after DB reset): do not
            # extend and do not spam marketplace chat again.
            event_type = "adopted"
            should_notify = False
            logger.info(
                "Adopting existing Remnawave user %s for %s/%s (no extend, no buyer notify)",
                remnawave_username,
                marketplace,
                external_order_id,
            )
    else:
        created = await rem.create_user(
            username=remnawave_username,
            days=days,
            limit_gb=0,
            descr=f"created by store ({marketplace})",
            email=email,
            squad_id=template or secrets.get("rw_free_id"),
            telegram_id=None,
            hwid_device_limit=hwid,
            external_squad_uuid=outer_squad,
        )
        if not created or not created.get("uuid"):
            logger.error("Failed to create Remnawave user for %s", remnawave_username)
            return {
                "sub": None,
                "order_id": order.id,
                "created": False,
                "event": "error",
                "should_notify_buyer": False,
            }
        sub_url = created["subscription_url"]
        rw_uuid = str(created["uuid"])
        event_type = "create"
        should_notify = True

    delivery_status = 1 if event_type == "adopted" else 0
    status = "delivered" if event_type == "adopted" else "provisioned"

    await rq.update_order(
        order.id,
        session=session,
        remnawave_uuid=str(rw_uuid),
        remnawave_username=remnawave_username,
        subscription_url=sub_url,
        days_ordered=days,
        customer_id=customer.id,
        chat_id=chat_id or order.chat_id or str(external_order_id),
        status=status,
        delivery_status=delivery_status,
    )

    await rq.add_subscription_event(
        order.id,
        event_type,
        days=days if event_type != "adopted" else 0,
        remnawave_uuid=str(rw_uuid),
        detail="adopted existing remnawave user" if event_type == "adopted" else None,
        session=session,
    )

    if event_type == "create" or (event_type == "extend" and should_notify):
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
    else:
        logger.info(
            "Order %s/%s event=%s — skipped admin alert / buyer notify",
            marketplace,
            external_order_id,
            event_type,
        )

    return {
        "sub": sub_url,
        "order_id": order.id,
        "remnawave_uuid": str(rw_uuid),
        "event": event_type,
        "created": event_type == "create",
        "should_notify_buyer": should_notify,
    }


async def mark_delivered(order_id: int, session=None) -> None:
    await rq.update_order(
        order_id,
        delivery_status=1,
        status="delivered",
        session=session,
    )
