"""Durable pipeline executor and marketplace order ingestion."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp
import nh3
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import store.api.remnawave.api as rem
from store.database.models import (
    Customer,
    DeadLetterJob,
    DeliveryPipeline,
    FxRate,
    MessageTemplate,
    Order,
    OrderEvent,
    OrderParam,
    OutboxJob,
    PipelineRun,
    PipelineStep,
    PipelineStepRun,
    PipelineVersion,
    Product,
    ProductBinding,
    async_session,
)
from store.domain.pipeline import PipelineError, evaluate_condition, get_path, render_template, render_value
from store.integrations.providers import digiseller, ggsel
from store.services.integrations import execute_http_action

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATES = {
    "ggsel_delivery": (
        "Спасибо за покупку!\nВаша ссылка для подписки: "
        "{{ steps.provision.outputs.subscription_url }}\n\n"
        "Добавьте её в поддерживаемый VPN-клиент. Если потребуется помощь, ответьте в этот чат."
    ),
    "digiseller_delivery": (
        "Заказ доставлен. Данные товара: {{ steps.provision.outputs.subscription_url }}"
    ),
}


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


async def bootstrap_templates() -> None:
    async with async_session() as session:
        for key, body in DEFAULT_TEMPLATES.items():
            existing = await session.scalar(select(MessageTemplate).where(MessageTemplate.key == key))
            if not existing:
                provider = "ggsel" if key.startswith("ggsel") else "digiseller"
                session.add(MessageTemplate(key=key, provider=provider, name=f"{provider.title()} delivery", body=body))
        await session.commit()


async def _binding(provider: str, item_id: int, session) -> ProductBinding | None:
    return await session.scalar(
        select(ProductBinding).where(
            ProductBinding.provider == provider,
            ProductBinding.external_item_id == int(item_id),
            ProductBinding.status == "active",
        )
    )


async def _parameters(binding: ProductBinding, options: list[dict], session) -> dict[str, Any]:
    rows = (
        await session.scalars(
            select(OrderParam).where(
                (OrderParam.binding_id == binding.id)
                | (
                    (OrderParam.binding_id.is_(None))
                    & (OrderParam.marketplace == binding.provider)
                    & (OrderParam.item_id == binding.external_item_id)
                )
            )
        )
    ).all()
    selected: dict[tuple[int, int], bool] = {}
    for option in options:
        try:
            selected[(int(option.get("id")), int(option.get("user_data_id", option.get("user_data"))))] = True
        except (TypeError, ValueError):
            continue
    result: dict[str, Any] = {}
    for row in rows:
        if (int(row.param_id), int(row.user_data_id)) in selected:
            result[row.type] = row.data
    for key in ("days", "hwid"):
        if key in result:
            try:
                result[key] = int(result[key])
            except (TypeError, ValueError):
                pass
    return result


async def _get_or_create_customer(email: str | None, provider: str, buyer_id: str | None, session) -> Customer:
    normalized = email.strip().lower() if email else None
    customer = None
    if normalized:
        customer = await session.scalar(select(Customer).where(Customer.email_normalized == normalized))
    field = Customer.ggsel_buyer_id if provider == "ggsel" else Customer.digiseller_buyer_id
    if not customer and buyer_id:
        customer = await session.scalar(select(Customer).where(field == str(buyer_id)))
    if not customer:
        customer = Customer(email=email, email_normalized=normalized)
        if provider == "ggsel":
            customer.ggsel_buyer_id = buyer_id
        else:
            customer.digiseller_buyer_id = buyer_id
        session.add(customer)
        await session.flush()
    elif email:
        # Marketplace purchase email is authoritative.
        customer.email, customer.email_normalized = email, normalized
    return customer


async def ingest_order(
    *,
    provider: str,
    provider_order_id: str,
    item_id: int,
    payload: dict[str, Any],
    normalized_status: str,
    invoice_id: str | None = None,
    content_id: str | None = None,
    email: str | None = None,
    buyer_id: str | None = None,
    options: list[dict] | None = None,
    chat_id: str | None = None,
    gross_amount: Any = None,
    net_amount: Any = None,
    profit_amount: Any = None,
    amount_usd: Any = None,
    currency: str | None = None,
    gross_currency: str | None = None,
    net_currency: str | None = None,
) -> tuple[Order, PipelineRun | None, bool]:
    options = options or []
    async with async_session() as session:
        identifiers = [Order.provider_order_id == str(provider_order_id)]
        if invoice_id:
            identifiers.append(Order.invoice_id == str(invoice_id))
        if provider == "ggsel" and content_id:
            # Legacy GGSel rows used content_id as external_order_id/chat_id.
            # Looking up both identifiers prevents an old paid invoice from
            # being provisioned again after migration.
            content = str(content_id)
            identifiers.extend((
                Order.external_order_id == content,
                Order.content_id == content,
                Order.chat_id == content,
            ))
        existing = await session.scalar(
            select(Order).where(
                Order.marketplace == provider,
                or_(*identifiers),
            ).order_by(Order.delivery_status.desc(), Order.id)
        )
        if existing:
            if email:
                existing.buyer_email = email
            existing.raw = payload
            existing.raw_state = str(payload.get("invoice_state") or payload.get("state") or "")
            if normalized_status in {"refund", "returned", "overdue", "cancelled"}:
                existing.status = existing.normalized_status = normalized_status
                session.add(OrderEvent(
                    order_id=existing.id,
                    type="order.state_changed",
                    payload={"normalized_status": normalized_status},
                ))
            elif normalized_status == "fulfilled":
                run = await session.scalar(select(PipelineRun).where(PipelineRun.order_id == existing.id))
                if not run:
                    existing.status = existing.normalized_status = "fulfilled"
                    existing.delivery_status = 1
            if existing.delivery_status == 1:
                # Never revive or create a run for a historical delivery.
                run = await session.scalar(select(PipelineRun).where(PipelineRun.order_id == existing.id))
                if run and run.status not in {"delivered", "delivered_with_warnings"}:
                    run.status = "delivered"
                    run.error_code = None
                    run.error_detail = None
                    run.execution_locked_at = None
                    run.completed_at = datetime.now(timezone.utc)
            await session.commit()
            run = await session.scalar(select(PipelineRun).where(PipelineRun.order_id == existing.id))
            return existing, run, False

        binding = await _binding(provider, item_id, session)
        if not binding and normalized_status == "paid":
            raise PipelineError(
                "product_not_configured",
                f"Товар {provider}:{item_id} не настроен для автоматической доставки",
                permanent=True,
            )
        customer = await _get_or_create_customer(email, provider, buyer_id, session)
        external = content_id if provider == "ggsel" and content_id else provider_order_id
        gross_value, net_value = _decimal(gross_amount), _decimal(net_amount)
        gross_curr = str(gross_currency or currency).upper() if gross_currency or currency else None
        net_curr = str(net_currency or currency).upper() if net_currency or currency else None
        fx_rate = None
        currencies = {value for value in (gross_curr, net_curr) if value and value.upper() not in {"RUB", "RUR"}}
        if currencies:
            # A single order normally has one source currency. Rates are append-only;
            # the selected row is pinned on the order for stable historical totals.
            fx_rate = await session.scalar(
                select(FxRate).where(FxRate.base_currency.in_(currencies), FxRate.quote_currency == "RUB")
                .order_by(FxRate.rate_date.desc()).limit(1)
            )
        def rub(value: Decimal | None, curr: str | None) -> Decimal | None:
            if value is None or not curr:
                return None
            if curr.upper() in {"RUB", "RUR"}:
                return value
            return value * fx_rate.rate if fx_rate and fx_rate.base_currency.upper() == curr.upper() else None
        order = Order(
            marketplace=provider,
            external_order_id=str(external),
            provider_order_id=str(provider_order_id),
            invoice_id=str(invoice_id) if invoice_id else (str(provider_order_id) if provider == "digiseller" else None),
            content_id=str(content_id) if content_id else None,
            cart_uid=str(payload.get("cart_uid")) if payload.get("cart_uid") else None,
            provider_external_order_id=str(payload.get("external_order_id")) if payload.get("external_order_id") else None,
            item_id=item_id,
            binding_id=binding.id if binding else None,
            options=options,
            options_json=json.dumps(options, ensure_ascii=False),
            raw=payload,
            raw_state=str(payload.get("invoice_state") or payload.get("state") or ""),
            normalized_status=normalized_status,
            status=normalized_status,
            buyer_email=email,
            customer_id=customer.id,
            chat_id=str(chat_id or external),
            gross_amount=gross_value,
            net_amount=net_value,
            profit_amount=_decimal(profit_amount),
            amount_usd=_decimal(amount_usd),
            amount=_decimal(net_amount or gross_amount),
            currency=currency,
            gross_currency=gross_curr,
            net_currency=net_curr,
            gross_rub=rub(gross_value, gross_curr),
            net_rub=rub(net_value, net_curr),
            fx_rate_id=fx_rate.id if fx_rate else None,
            pipeline_version_id=binding.published_pipeline_version_id if binding else None,
        )
        session.add(order)
        await session.flush()
        session.add(OrderEvent(order_id=order.id, type="order.ingested", payload={"provider": provider, "state": normalized_status}))
        run = None
        if normalized_status == "paid" and binding and binding.published_pipeline_version_id:
            run = PipelineRun(
                order_id=order.id,
                pipeline_version_id=binding.published_pipeline_version_id,
                status="pending",
                correlation_id=str(uuid.uuid4()),
                context={},
            )
            session.add(run)
            await session.flush()
        elif normalized_status == "fulfilled":
            order.delivery_status = 1
            order.status = order.normalized_status = "fulfilled"
        await session.commit()
        return order, run, True


async def build_context(order: Order, run: PipelineRun, session) -> dict[str, Any]:
    binding = await session.get(ProductBinding, order.binding_id) if order.binding_id else None
    product = await session.get(Product, binding.product_id) if binding else None
    parameters = await _parameters(binding, order.options or [], session) if binding else {}
    return {
        "order": {
            "id": order.id,
            "provider": order.marketplace,
            "provider_order_id": order.provider_order_id,
            "invoice_id": order.invoice_id,
            "content_id": order.content_id,
            "chat_id": order.chat_id,
            "item_id": order.item_id,
            "remnawave_user_id": order.remnawave_user_id,
            "normalized_status": order.normalized_status,
            "raw_state": order.raw_state,
        },
        "buyer": {"email": order.buyer_email},
        "product": {
            "id": product.id if product else None,
            "key": product.key if product else None,
            "name": product.name if product else None,
            "parameters": parameters,
            "options": order.options or [],
        },
        "trigger": order.raw or {},
        "steps": {},
        "system": {
            "run_id": run.id,
            "correlation_id": run.correlation_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    }


async def _template(key: str, session) -> MessageTemplate:
    row = await session.scalar(select(MessageTemplate).where(MessageTemplate.key == key, MessageTemplate.enabled.is_(True)))
    if not row:
        raise PipelineError("template_missing", f"Message template not found: {key}", permanent=True)
    return row


async def _provision(step: PipelineStep, context: dict[str, Any], order: Order) -> dict[str, Any]:
    config = step.config or {}
    username = str(context.get("trigger", {}).get("compatibility_username") or "")
    if not username:
        username = render_template(str(config.get("username_template") or ""), context)
    if not username:
        raise PipelineError("username_missing", "Remnawave username rendered empty", permanent=True)
    days = get_path(context, str(config.get("days_path") or ""), config.get("days_default", 30))
    try:
        days = int(days or config.get("days_default", 30))
    except (TypeError, ValueError) as exc:
        raise PipelineError("invalid_days", "Subscription days must be an integer", permanent=True) from exc
    existing = await rem.get_user_from_username(username)
    event = "existing"
    if existing:
        data = existing
    else:
        parameters = context.get("product", {}).get("parameters", {})
        data = await rem.create_user(
            username=username,
            days=days,
            limit_gb=int(config.get("limit_gb") or 0),
            descr=f"created by delivery pipeline run {context['system']['run_id']}",
            email=context.get("buyer", {}).get("email"),
            squad_id=parameters.get("internal_sq") or parameters.get("location") or config.get("squad_id"),
            hwid_device_limit=parameters.get("hwid"),
            external_squad_uuid=parameters.get("external_sq"),
        )
        event = "created"
    if not data or not data.get("id") or not data.get("subscription_url"):
        raise PipelineError("remnawave_failed", "Remnawave did not return a subscription")
    order.remnawave_username = username
    order.remnawave_user_id = int(data["id"])
    order.subscription_url = data["subscription_url"]
    order.days_ordered = days
    return {
        "id": int(data["id"]),
        "user_id": int(data["id"]),
        "username": username,
        "subscription_url": data["subscription_url"],
        "days": days,
        "event": event,
    }


async def _execute_step(
    step: PipelineStep,
    context: dict[str, Any],
    order: Order,
    session,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if step.type == "trigger.conditions":
        return {"matched": True}
    if step.type == "remnawave.provision_subscription":
        return await _provision(step, context, order)
    if step.type == "remnawave.update_user":
        configured_template = step.config.get("user_id_template") or step.config.get("uuid_template")
        rendered_user_id = render_template(str(configured_template), context) if configured_template else None
        user_id = rendered_user_id or order.remnawave_user_id
        try:
            user_id = int(user_id) if user_id else None
        except (TypeError, ValueError):
            # A published v2 pipeline may still render the removed UUID. Use
            # its stable username to resolve the numeric v3 id lazily.
            user_id = None
        if user_id is None and order.remnawave_username:
            existing = await rem.get_user_from_username(order.remnawave_username)
            user_id = existing.get("id") if existing else None
            if user_id:
                order.remnawave_user_id = int(user_id)
        if not user_id:
            raise PipelineError("remnawave_user_id_missing", "Remnawave numeric user id is missing")
        order.remnawave_user_id = int(user_id)
        rendered = render_value(step.config.get("fields") or {}, context)
        result = await rem.update_user(user_id, **rendered)
        if not result:
            raise PipelineError("remnawave_update_failed", "Remnawave update failed")
        return result
    if step.type == "http.request":
        config = dict(step.config)
        if idempotency_key:
            config["_idempotency_key"] = idempotency_key
        return await execute_http_action(profile_id=int(config["profile_id"]), config=config, context=context)
    if step.type == "marketplace.message":
        template = await _template(str(step.config.get("template_key")), session)
        body = render_template(template.body, context, escape=template.format == "html")
        async with aiohttp.ClientSession() as http:
            if order.marketplace == "ggsel":
                await ggsel.send_message(http, order.content_id or order.chat_id or "", body)
            else:
                await digiseller.send_message(http, order.provider_order_id or order.external_order_id, body)
        return {"sent": True, "chat_id": order.content_id if order.marketplace == "ggsel" else order.provider_order_id}
    if step.type == "webhook.response":
        is_html = step.config.get("format") == "html"
        goods = render_template(str(step.config.get("goods_template") or ""), context, escape=is_html)
        error = render_template(str(step.config.get("error_template") or ""), context, escape=is_html)
        if is_html:
            goods = nh3.clean(goods, tags={"b", "strong", "i", "em", "br", "p", "a", "code"}, attributes={"a": {"href"}})
        if not goods and not error:
            raise PipelineError("empty_digiseller_response", "Digiseller goods/error cannot both be empty", permanent=True)
        response = {"id": str(order.item_id), "inv": str(order.provider_order_id)}
        if goods:
            response["goods"] = goods
        if error:
            response["error"] = error
        order.final_delivery_response = response
        return {"response": response, "goods": goods, "error": error}
    raise PipelineError("unsupported_step", f"Unsupported pipeline step: {step.type}", permanent=True)


async def execute_run(run_id: int, *, before_response_only: bool = False) -> dict[str, Any]:
    async with async_session() as session:
        run = await session.get(PipelineRun, run_id, with_for_update=True)
        if not run:
            raise PipelineError("run_not_found", "Pipeline run not found", permanent=True)
        order = await session.get(Order, run.order_id, with_for_update=True)
        now = datetime.now(timezone.utc)
        if run.status in {"delivered", "delivered_with_warnings"}:
            return {"status": run.status, "response": order.final_delivery_response}
        if order.delivery_status == 1 or order.normalized_status in {"delivered", "fulfilled"}:
            # Final safety gate: a queued continuation from before legacy
            # reconciliation must not execute provisioning or messaging.
            run.status = "delivered"
            run.error_code = None
            run.error_detail = None
            run.execution_locked_at = None
            run.completed_at = run.completed_at or now
            await session.commit()
            return {"status": run.status, "response": order.final_delivery_response}
        if run.status == "running" and run.execution_locked_at and run.execution_locked_at > now - timedelta(minutes=5):
            return {"status": "running", "response": order.final_delivery_response}
        version = await session.scalar(
            select(PipelineVersion).where(PipelineVersion.id == run.pipeline_version_id).options(selectinload(PipelineVersion.steps))
        )
        if not version or version.status != "published":
            raise PipelineError("version_unavailable", "Published pipeline version not found", permanent=True)
        context = run.context or await build_context(order, run, session)
        run.status = "running"
        run.started_at = run.started_at or now
        run.execution_locked_at = now
        await session.commit()

    optional_failed = False
    pending_after_wall = False
    for step in version.steps:
        if before_response_only and not step.run_before_response:
            pending_after_wall = True
            continue
        async with async_session() as session:
            run = await session.get(PipelineRun, run_id, with_for_update=True)
            order = await session.get(Order, run.order_id, with_for_update=True)
            run.execution_locked_at = datetime.now(timezone.utc)
            existing = await session.scalar(
                select(PipelineStepRun)
                .where(PipelineStepRun.run_id == run.id, PipelineStepRun.step_id == step.id)
                .order_by(PipelineStepRun.attempt.desc())
            )
            if existing and existing.status in {"succeeded", "skipped"}:
                context["steps"][step.key] = {"status": existing.status, "outputs": existing.outputs or {}}
                continue
            if existing and existing.status == "running" and step.type == "http.request" and not step.idempotency_key_template:
                run.status = order.status = order.normalized_status = "needs_review"
                run.error_code = "ambiguous_previous_attempt"
                run.execution_locked_at = None
                await session.commit()
                return {"status": "needs_review", "response": order.final_delivery_response}
            if not evaluate_condition(step.condition, context):
                attempt = (existing.attempt + 1) if existing else 1
                row = PipelineStepRun(run_id=run.id, step_id=step.id, attempt=attempt, status="skipped", outputs={})
                session.add(row)
                context["steps"][step.key] = {"status": "skipped", "outputs": {}}
                run.context = context
                await session.commit()
                continue
            attempt = (existing.attempt + 1) if existing else 1
            idem = render_template(step.idempotency_key_template, context) if step.idempotency_key_template else None
            prior = None
            if idem:
                prior = await session.scalar(select(PipelineStepRun).where(PipelineStepRun.idempotency_key == idem))
            if prior and prior.status == "succeeded":
                context["steps"][step.key] = {"status": "succeeded", "outputs": prior.outputs or {}}
                run.context = context
                await session.commit()
                continue
            if prior and prior.run_id == run.id and prior.step_id == step.id:
                # The database key is the reservation. Reuse it for a safe upstream
                # retry and keep the same key on the outbound request.
                row = prior
                row.attempt = attempt
                row.status = "running"
                row.inputs = render_value(step.config, context)
                row.outputs = {}
                row.error_code = row.error_detail = None
                row.started_at = datetime.now(timezone.utc)
                row.completed_at = None
            elif prior:
                run.status = order.status = order.normalized_status = "needs_review"
                run.error_code = "idempotency_key_collision"
                run.execution_locked_at = None
                await session.commit()
                return {"status": "needs_review", "response": order.final_delivery_response}
            else:
                row = PipelineStepRun(
                    run_id=run.id, step_id=step.id, attempt=attempt, status="running",
                    idempotency_key=idem, inputs=render_value(step.config, context), started_at=datetime.now(timezone.utc),
                )
                session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                prior = await session.scalar(select(PipelineStepRun).where(PipelineStepRun.idempotency_key == idem))
                if prior and prior.status == "succeeded":
                    context["steps"][step.key] = {"status": "succeeded", "outputs": prior.outputs or {}}
                    continue
                raise

        try:
            async with asyncio.timeout(step.timeout_seconds):
                async with async_session() as session:
                    order = await session.get(Order, run.order_id, with_for_update=True)
                    outputs = await _execute_step(step, context, order, session, idempotency_key=idem)
                    row = await session.get(PipelineStepRun, row.id, with_for_update=True)
                    run = await session.get(PipelineRun, run_id, with_for_update=True)
                    row.status, row.outputs, row.completed_at = "succeeded", outputs, datetime.now(timezone.utc)
                    context["steps"][step.key] = {"status": "succeeded", "outputs": outputs}
                    run.context = context
                    await session.commit()
        except (TimeoutError, asyncio.TimeoutError) as exc:
            error = PipelineError("ambiguous_timeout", f"Step {step.key} timed out")
            async with async_session() as session:
                row = await session.get(PipelineStepRun, row.id, with_for_update=True)
                run = await session.get(PipelineRun, run_id, with_for_update=True)
                row.status, row.error_code, row.error_detail = "failed", error.code, str(error)
                if step.type == "http.request" and not step.idempotency_key_template:
                    run.status, run.error_code = "needs_review", error.code
                else:
                    run.status, run.error_code = "pending", error.code
                run.execution_locked_at = None
                await session.commit()
            if step.required:
                return {"status": run.status, "response": None}
            optional_failed = True
        except PipelineError as error:
            async with async_session() as session:
                row = await session.get(PipelineStepRun, row.id, with_for_update=True)
                run = await session.get(PipelineRun, run_id, with_for_update=True)
                order = await session.get(Order, run.order_id, with_for_update=True)
                row.status, row.error_code, row.error_detail = "failed", error.code, str(error)
                row.completed_at = datetime.now(timezone.utc)
                if step.required:
                    run.status = "failed" if error.permanent else "pending"
                    run.error_code, run.error_detail = error.code, str(error)
                    run.execution_locked_at = None
                    if error.permanent:
                        order.status = order.normalized_status = "failed"
                await session.commit()
            if step.required:
                return {"status": run.status, "response": order.final_delivery_response}
            optional_failed = True

    async with async_session() as session:
        run = await session.get(PipelineRun, run_id, with_for_update=True)
        order = await session.get(Order, run.order_id, with_for_update=True)
        if before_response_only and pending_after_wall:
            run.status = "pending_async"
            run.execution_locked_at = None
            await enqueue("pipeline.continue", f"pipeline.continue:{run.id}", {"run_id": run.id}, session=session)
        else:
            run.status = "delivered_with_warnings" if optional_failed else "delivered"
            run.execution_locked_at = None
            run.completed_at = datetime.now(timezone.utc)
            order.status = order.normalized_status = run.status
            order.delivery_status = 1
            await enqueue("email.sync", f"email.sync:{order.id}", {"order_id": order.id}, session=session)
        response = order.final_delivery_response
        await session.commit()
        return {"status": run.status, "response": response}


async def enqueue(kind: str, dedupe_key: str, payload: dict[str, Any], *, session=None) -> None:
    owns = session is None
    if owns:
        session = async_session()
    try:
        existing = await session.scalar(select(OutboxJob).where(OutboxJob.dedupe_key == dedupe_key))
        if not existing:
            session.add(OutboxJob(kind=kind, dedupe_key=dedupe_key, payload=payload))
        if owns:
            await session.commit()
    finally:
        if owns:
            await session.close()


async def handle_digiseller_supplier(payload: dict[str, Any]) -> dict[str, Any]:
    item_id, inv = payload.get("id"), payload.get("inv")
    pending = {"id": str(item_id or ""), "inv": str(inv or "")}
    if item_id is None or inv is None or not isinstance(payload.get("options"), list):
        return {**pending, "error": "Некорректные параметры заказа"}
    if not digiseller.valid_supplier_signature(payload):
        raise PipelineError("invalid_signature", "Invalid Digiseller supplier signature", permanent=True)
    async with async_session() as session:
        existing = await session.scalar(
            select(Order).where(Order.marketplace == "digiseller", Order.provider_order_id == str(inv))
        )
        if existing and existing.final_delivery_response:
            return existing.final_delivery_response
    try:
        order, run, _ = await ingest_order(
            provider="digiseller", provider_order_id=str(inv), item_id=int(item_id), payload=payload,
            normalized_status="paid", invoice_id=str(inv), options=payload.get("options") or [],
            email=payload.get("email") or payload.get("buyer_email"), buyer_id=payload.get("buyer_id"),
            chat_id=str(inv), gross_amount=payload.get("amount"), currency=payload.get("type_curr"),
            amount_usd=payload.get("amount_usd"),
        )
    except IntegrityError:
        # A concurrent webhook won the unique (provider, inv) insert. Read its
        # durable state and return/continue that single run.
        async with async_session() as session:
            order = await session.scalar(select(Order).where(
                Order.marketplace == "digiseller", Order.provider_order_id == str(inv)
            ))
            run = await session.scalar(select(PipelineRun).where(PipelineRun.order_id == order.id)) if order else None
        if not order:
            return pending
    except PipelineError as error:
        return {**pending, "error": str(error)} if error.permanent else pending
    if order.final_delivery_response:
        return order.final_delivery_response
    if not run:
        return pending
    try:
        result = await asyncio.wait_for(execute_run(run.id, before_response_only=True), timeout=12.0)
    except asyncio.TimeoutError:
        await enqueue("pipeline.continue", f"pipeline.continue:{run.id}", {"run_id": run.id})
        return pending
    if result.get("status") in {"pending", "pending_async"} and not result.get("response"):
        await enqueue("pipeline.continue", f"pipeline.continue:{run.id}", {"run_id": run.id})
    return result.get("response") or pending


async def ingest_ggsel_purchase(content: dict[str, Any], sale: dict[str, Any] | None = None) -> tuple[Order, PipelineRun | None, bool]:
    invoice_id = content.get("invoice_id") or (sale or {}).get("invoice_id")
    content_id = content.get("content_id")
    state = ggsel.normalize_state(content.get("invoice_state"))
    if not invoice_id or not content_id:
        raise PipelineError("invalid_order", "GGSel order is missing invoice_id/content_id", permanent=True)
    buyer = content.get("buyer_info") or {}
    return await ingest_order(
        provider="ggsel", provider_order_id=str(invoice_id), item_id=int(content["item_id"]),
        payload=content, normalized_status=state, invoice_id=str(invoice_id), content_id=str(content_id),
        email=buyer.get("email"), buyer_id=str(buyer.get("buyer_id") or "") or None,
        options=content.get("options") or [], chat_id=str(content_id),
        gross_amount=(sale or {}).get("price_rub"), net_amount=content.get("amount"),
        profit_amount=content.get("profit"), currency=content.get("currency_type") or "RUB",
        gross_currency="RUB", net_currency=content.get("currency_type") or "RUB",
    )


async def sync_email(order_id: int) -> None:
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if not order:
            return
        user_id = order.remnawave_user_id
        if not user_id and order.remnawave_username:
            existing = await rem.get_user_from_username(order.remnawave_username)
            user_id = existing.get("id") if existing else None
            if user_id:
                order.remnawave_user_id = int(user_id)
        if not user_id:
            raise PipelineError(
                "remnawave_user_id_missing",
                "Could not resolve the Remnawave 3 numeric user id",
            )
        email = order.buyer_email
        if not email:
            async with aiohttp.ClientSession() as http:
                adapter = ggsel if order.marketplace == "ggsel" else digiseller
                details = await adapter.purchase(http, order.provider_order_id or order.invoice_id or "")
                content = details.get("content") or details
                email = (content.get("buyer_info") or {}).get("email")
                if not email:
                    chats = await adapter.chats(http)
                    target = order.content_id if order.marketplace == "ggsel" else order.provider_order_id
                    chat = next((row for row in chats if str(row.get("id_i") or row.get("content_id") or row.get("inv")) == str(target)), None)
                    email = (chat or {}).get("email") or (chat or {}).get("buyer_email")
        if not email:
            # Keep the lazy v2 UUID -> v3 id reconciliation even when the
            # marketplace has no email to sync yet.
            if order.remnawave_user_id:
                await session.commit()
            return
        result = await rem.update_user_email(int(user_id), email)
        if not result:
            raise PipelineError("email_sync_failed", "Could not update Remnawave email")
        order.buyer_email = email
        if order.customer_id:
            customer = await session.get(Customer, order.customer_id)
            if customer:
                customer.email, customer.email_normalized = email, email.strip().lower()
        session.add(OrderEvent(order_id=order.id, type="remnawave.email_synced", payload={"email": email}))
        await session.commit()


async def claim_outbox(worker_id: str, limit: int = 10) -> list[int]:
    async with async_session() as session:
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=5)
        jobs = (
            await session.scalars(
                select(OutboxJob)
                .where(
                    or_(
                        and_(OutboxJob.status == "pending", OutboxJob.available_at <= func.now()),
                        and_(OutboxJob.status == "running", OutboxJob.locked_at < stale_before),
                    )
                )
                .order_by(OutboxJob.available_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()
        now = datetime.now(timezone.utc)
        for job in jobs:
            job.status, job.locked_by, job.locked_at = "running", worker_id, now
        await session.commit()
        return [job.id for job in jobs]


async def process_outbox_job(job_id: int) -> None:
    async with async_session() as session:
        job = await session.get(OutboxJob, job_id)
        if not job:
            return
        kind, payload = job.kind, job.payload
    try:
        if kind == "pipeline.continue":
            await execute_run(int(payload["run_id"]))
        elif kind == "email.sync":
            await sync_email(int(payload["order_id"]))
        else:
            raise PipelineError("unknown_job", f"Unknown outbox job: {kind}", permanent=True)
        async with async_session() as session:
            job = await session.get(OutboxJob, job_id, with_for_update=True)
            job.status, job.completed_at = "completed", datetime.now(timezone.utc)
            await session.commit()
    except Exception as exc:
        async with async_session() as session:
            job = await session.get(OutboxJob, job_id, with_for_update=True)
            job.attempts += 1
            job.last_error = str(exc)[:4000]
            job.locked_at = job.locked_by = None
            if job.attempts >= job.max_attempts:
                job.status = "dead_letter"
                session.add(DeadLetterJob(outbox_job_id=job.id, kind=job.kind, payload=job.payload, error=job.last_error))
            else:
                job.status = "pending"
                job.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 2 ** job.attempts))
            await session.commit()
