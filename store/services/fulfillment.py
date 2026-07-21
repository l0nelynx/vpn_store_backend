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
    # Prefer explicit internal_sq; location remains a legacy alias.
    template = result.get("internal_sq") or result.get("location")
    return {
        "days": int(days) if days is not None else None,
        "template": template,
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
    rw_cache: dict | None = None,
) -> dict[str, Any]:
    """Idempotent provision with Remnawave as source of truth for the live sub URL.

    If Store says delivered but the Remnawave user was deleted → recreate panel user
    and refresh Store row (Digiseller test inv=0 after manual delete).

    ``rw_cache``: optional username → user-dict|None from bulk stream to avoid N+1 GETs.
    """
    days = days if days is not None else 30
    existing = await rq.get_order_by_external(
        marketplace, external_order_id, session=session
    )

    if rw_cache is not None and remnawave_username in rw_cache:
        cached = rw_cache[remnawave_username]
        rw_live = cached if cached else None
    else:
        rw_live = await rem.get_user_from_username(remnawave_username)
        if rw_cache is not None:
            rw_cache[remnawave_username] = rw_live

    if existing and existing.delivery_status == 1 and rw_live and rw_live.get("subscription_url"):
        sub = rw_live["subscription_url"]
        if sub != existing.subscription_url or str(rw_live.get("uuid")) != str(existing.remnawave_uuid):
            await rq.update_order(
                existing.id,
                session=session,
                subscription_url=sub,
                remnawave_uuid=str(rw_live["uuid"]),
            )
        return {
            "sub": sub,
            "order_id": existing.id,
            "remnawave_uuid": str(rw_live["uuid"]),
            "event": "existing",
            "created": False,
            "should_notify_buyer": False,
        }

    if (
        existing
        and existing.subscription_url
        and existing.remnawave_uuid
        and existing.delivery_status != 1
        and rw_live
        and rw_live.get("subscription_url")
    ):
        return {
            "sub": rw_live["subscription_url"],
            "order_id": existing.id,
            "remnawave_uuid": str(rw_live["uuid"]),
            "event": "resend",
            "created": False,
            "should_notify_buyer": True,
        }

    if existing and existing.delivery_status == 1 and not rw_live:
        logger.warning(
            "Order %s/%s marked delivered but Remnawave user %s missing — recreating",
            marketplace,
            external_order_id,
            remnawave_username,
        )

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

    event_type = "create"
    should_notify = True

    if rw_live and rw_live.get("uuid"):
        rw_uuid = str(rw_live["uuid"])
        sub_url = rw_live.get("subscription_url")
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
        event_type = "recreate" if existing else "create"
        # Digiseller returns URL in webhook body; GGsel may still want a chat message
        # only for true first-time create. Recreate after panel delete: notify buyer
        # for GGsel, Digiseller gets URL via HTTP response.
        should_notify = marketplace == "ggsel"

    delivery_status = 0 if should_notify else 1
    if event_type in ("adopted", "existing"):
        delivery_status = 1
    if event_type == "recreate" and marketplace == "digiseller":
        delivery_status = 1
    status = "delivered" if delivery_status == 1 else "provisioned"

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
        days=days if event_type not in ("adopted", "existing") else 0,
        remnawave_uuid=str(rw_uuid),
        detail=(
            "recreated after missing remnawave user"
            if event_type == "recreate"
            else ("adopted existing remnawave user" if event_type == "adopted" else None)
        ),
        session=session,
    )

    if event_type in ("create", "recreate", "extend") and (
        event_type != "extend" or should_notify
    ):
        await send_tg_alert(
            message=(
                f"<b>⚠️ {'Recreated' if event_type == 'recreate' else 'New'} {marketplace} Order</b>\n"
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
        "created": event_type in ("create", "recreate"),
        "should_notify_buyer": should_notify,
    }


async def mark_delivered(order_id: int, session=None) -> None:
    await rq.update_order(
        order_id,
        delivery_status=1,
        status="delivered",
        session=session,
    )
