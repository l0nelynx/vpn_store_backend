"""Compatibility facade for callers from the pre-pipeline Store API."""

from __future__ import annotations

from typing import Any

import store.database.requests as rq
from store.database.models import Order, PipelineRun, async_session
from store.domain.pipeline import PipelineError


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
    days, hwid = result.get("days"), result.get("hwid")
    return {
        "days": int(days) if days is not None else None,
        "template": result.get("internal_sq") or result.get("location"),
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
    """Run the published legacy pipeline and return the old response shape.

    ``session``, ``allow_extend`` and ``rw_cache`` remain accepted so old tools
    do not break, but execution and idempotency now belong to PipelineRuntime.
    """
    del session, allow_extend, rw_cache
    if marketplace not in {"ggsel", "digiseller"} or item_id is None:
        raise PipelineError("invalid_compat_order", "Marketplace and item_id are required", permanent=True)

    from sqlalchemy import select
    from store.services.runtime import build_context, execute_run, ingest_order

    provider_order_id = str(invoice_id or external_order_id) if marketplace == "ggsel" else str(external_order_id)
    content_id = str(chat_id or external_order_id) if marketplace == "ggsel" else None
    payload = {
        "invoice_id": provider_order_id,
        "content_id": content_id,
        "item_id": item_id,
        "invoice_state": 3,
        "buyer_info": {"email": email},
        "options": options or [],
        "compatibility": True,
    }
    order, run, created = await ingest_order(
        provider=marketplace,
        provider_order_id=provider_order_id,
        item_id=int(item_id),
        payload=payload,
        normalized_status="paid",
        invoice_id=provider_order_id,
        content_id=content_id,
        email=email,
        buyer_id=ggsel_buyer_id if marketplace == "ggsel" else digiseller_buyer_id,
        options=options or [],
        chat_id=str(chat_id or external_order_id),
        gross_amount=amount,
        net_amount=amount,
        currency=currency,
    )
    if run:
        async with async_session() as db:
            persistent_run = await db.get(PipelineRun, run.id)
            persistent_order = await db.get(Order, order.id)
            context = persistent_run.context or await build_context(persistent_order, persistent_run, db)
            parameters = context.setdefault("product", {}).setdefault("parameters", {})
            parameters.update({
                key: value for key, value in {
                    "days": days or 30,
                    "internal_sq": template,
                    "hwid": hwid,
                    "external_sq": outer_squad,
                }.items() if value is not None
            })
            context["trigger"]["compatibility_username"] = remnawave_username
            persistent_run.context = context
            await db.commit()
        await execute_run(run.id, before_response_only=marketplace == "digiseller")

    async with async_session() as db:
        current = await db.scalar(select(Order).where(
            Order.marketplace == marketplace,
            Order.provider_order_id == provider_order_id,
        ))
    return {
        "sub": current.subscription_url if current else None,
        "order_id": current.id if current else order.id,
        "remnawave_uuid": current.remnawave_uuid if current else None,
        "event": "create" if created else "existing",
        "created": created,
        # Marketplace delivery is already a pipeline step; old callers must not
        # send a second chat message.
        "should_notify_buyer": False,
    }


async def mark_delivered(order_id: int, session=None) -> None:
    """Compatibility status update for old maintenance tools."""
    await rq.update_order(order_id, delivery_status=1, status="delivered", session=session)
