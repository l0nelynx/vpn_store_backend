"""Versioned Store Admin API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import selectinload

from store.api.auth import verify_human_admin
from store.database.models import (
    AuditLog,
    DeadLetterJob,
    IntegrationProfile,
    MessageTemplate,
    Order,
    OrderEvent,
    OutboxJob,
    PipelineRun,
    PipelineStep,
    PipelineStepRun,
    Product,
    ProductBinding,
    SyncCheckpoint,
    async_session,
)
from store.integrations.providers import digiseller, ggsel
from store.domain.pipeline import PipelineDefinition, evaluate_condition, mask_secrets, render_template, render_value, validate_pipeline
from store.services import pipelines
from store.services.catalog_sync import sync_all_catalogs
from store.services.integrations import execute_http_action, save_profile_secret
from store.services.order_sync import sync_all_orders
from store.services.runtime import enqueue

router = APIRouter(
    prefix="/store/api/v1", tags=["store-v1"], dependencies=[Depends(verify_human_admin)]
)


class ProductBody(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,99}$")
    name: str
    description: str | None = None
    status: str = "draft"


class BindingBody(BaseModel):
    provider: str
    external_item_id: int
    trigger_policy: str = "automatic"
    option_mappings: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class PipelineBody(BaseModel):
    key: str
    name: str
    description: str | None = None
    providers: list[str]
    steps: list[dict[str, Any]]


class StepsBody(BaseModel):
    steps: list[dict[str, Any]]


class PublishBody(BaseModel):
    binding_ids: list[int] = Field(default_factory=list)


class DryRunBody(BaseModel):
    context: dict[str, Any]


class LiveTestBody(BaseModel):
    confirmation: str
    context: dict[str, Any]


class TemplateBody(BaseModel):
    key: str
    provider: str
    name: str
    format: str = "plain"
    body: str
    enabled: bool = True


class IntegrationBody(BaseModel):
    key: str
    name: str
    type: str = "http"
    base_url: str
    auth_type: str = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    allowed_hosts: list[str]
    enabled: bool = True
    secrets: dict[str, str] = Field(default_factory=dict)


async def _audit(actor: str, action: str, entity: str, entity_id: Any, after: dict | None = None) -> None:
    async with async_session() as session:
        session.add(AuditLog(actor=actor, action=action, entity_type=entity, entity_id=str(entity_id), after=after))
        await session.commit()


def _binding_dict(row: ProductBinding) -> dict[str, Any]:
    return {
        "id": row.id, "product_id": row.product_id, "provider": row.provider,
        "external_item_id": row.external_item_id, "trigger_policy": row.trigger_policy,
        "option_mappings": row.option_mappings, "status": row.status,
        "published_pipeline_version_id": row.published_pipeline_version_id,
    }


def _product_dict(row: Product) -> dict[str, Any]:
    return {
        "id": row.id, "key": row.key, "name": row.name, "description": row.description,
        "status": row.status, "published_pipeline_version_id": row.published_pipeline_version_id,
        "bindings": [_binding_dict(binding) for binding in row.bindings],
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


@router.get("/products")
async def list_products():
    async with async_session() as session:
        rows = (
            await session.scalars(select(Product).options(selectinload(Product.bindings)).order_by(Product.name))
        ).all()
        return [_product_dict(row) for row in rows]


@router.post("/products", status_code=201)
async def create_product(body: ProductBody, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = Product(**body.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row, ["bindings"])
    await _audit(auth["sub"], "create", "product", row.id, body.model_dump())
    return _product_dict(row)


@router.put("/products/{product_id}")
async def update_product(product_id: int, body: ProductBody, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(Product, product_id)
        if not row:
            raise HTTPException(404, "Product not found")
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        await session.commit()
        await session.refresh(row, ["bindings"])
    await _audit(auth["sub"], "update", "product", product_id, body.model_dump())
    return _product_dict(row)


@router.delete("/products/{product_id}")
async def archive_product(product_id: int, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(Product, product_id)
        if not row:
            raise HTTPException(404, "Product not found")
        row.status = "archived"
        await session.execute(
            ProductBinding.__table__.update().where(ProductBinding.product_id == product_id).values(status="archived")
        )
        await session.commit()
    await _audit(auth["sub"], "archive", "product", product_id)
    return {"id": product_id, "status": "archived"}


@router.post("/products/{product_id}/bindings", status_code=201)
async def create_binding(product_id: int, body: BindingBody, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        if not await session.get(Product, product_id):
            raise HTTPException(404, "Product not found")
        row = ProductBinding(product_id=product_id, **body.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
    await _audit(auth["sub"], "create", "product_binding", row.id, body.model_dump())
    return _binding_dict(row)


@router.put("/products/{product_id}/bindings/{binding_id}")
async def update_binding(product_id: int, binding_id: int, body: BindingBody, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(ProductBinding, binding_id)
        if not row or row.product_id != product_id:
            raise HTTPException(404, "Binding not found")
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
    await _audit(auth["sub"], "update", "product_binding", row.id, body.model_dump())
    return _binding_dict(row)


@router.delete("/products/{product_id}/bindings/{binding_id}")
async def delete_binding(product_id: int, binding_id: int, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(ProductBinding, binding_id)
        if not row or row.product_id != product_id:
            raise HTTPException(404, "Binding not found")
        await session.delete(row)
        await session.commit()
    await _audit(auth["sub"], "delete", "product_binding", binding_id)
    return {"ok": True}


@router.get("/pipelines")
async def list_pipelines():
    return await pipelines.list_pipelines()


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: int):
    result = await pipelines.get_pipeline(pipeline_id)
    if not result:
        raise HTTPException(404, "Pipeline not found")
    return result


@router.post("/pipelines", status_code=201)
async def create_pipeline(body: PipelineBody, auth=Depends(verify_human_admin)):
    try:
        return await pipelines.create_pipeline(**body.model_dump(), actor=auth["sub"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/pipeline-versions/{version_id}")
async def update_pipeline_version(version_id: int, body: StepsBody, auth=Depends(verify_human_admin)):
    try:
        return await pipelines.replace_draft(version_id, body.steps, actor=auth["sub"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/pipeline-versions/{version_id}/validate")
async def validate_pipeline_version(version_id: int):
    return await pipelines.validate_version(version_id)


@router.post("/pipeline-versions/{version_id}/dry-run")
async def dry_run_pipeline_version(version_id: int, body: DryRunBody):
    return await pipelines.dry_run_version(version_id, body.context)


@router.post("/pipeline-versions/{version_id}/live-test")
async def live_test_pipeline_version(version_id: int, body: LiveTestBody, auth=Depends(verify_human_admin)):
    """Execute connector HTTP actions only, with an explicit isolated test context."""
    if body.confirmation != "LIVE TEST" or body.context.get("trigger", {}).get("test_mode") is not True:
        raise HTTPException(400, "Live test requires confirmation='LIVE TEST' and trigger.test_mode=true")
    try:
        raw = await pipelines.get_version(version_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    definition = PipelineDefinition(providers=raw["providers"], steps=raw["steps"])
    errors = [issue.message for issue in validate_pipeline(definition) if issue.level == "error"]
    if errors:
        raise HTTPException(400, "; ".join(errors))
    context = body.context
    context.setdefault("steps", {})
    rendered_steps: list[dict[str, Any]] = []
    executed = 0
    for step in definition.steps:
        applicable = evaluate_condition(step.condition, context)
        outputs: dict[str, Any] = {}
        did_execute = False
        if applicable and step.type == "http.request":
            config = dict(step.config)
            if step.idempotency_key_template:
                config["_idempotency_key"] = render_template(step.idempotency_key_template, context)
            outputs = await execute_http_action(profile_id=int(config["profile_id"]), config=config, context=context)
            did_execute = True
            executed += 1
        elif applicable:
            output_names = list((step.config.get("outputs") or {}).keys())
            if step.type == "remnawave.provision_subscription":
                output_names = ["id", "user_id", "username", "subscription_url", "days"]
            outputs = {name: f"<preview:{step.key}.{name}>" for name in output_names}
        context["steps"][step.key] = {"status": "succeeded" if did_execute else "previewed", "outputs": outputs}
        rendered_steps.append({
            "key": step.key,
            "type": step.type,
            "applicable": applicable,
            "executed": did_execute,
            "rendered_config": mask_secrets(render_value(step.config, context)) if applicable else None,
            "outputs": outputs,
        })
    await _audit(auth["sub"], "live_test", "pipeline_version", version_id, {"executed_http_actions": executed})
    return {"ok": True, "executed_http_actions": executed, "steps": rendered_steps}


@router.post("/pipeline-versions/{version_id}/publish")
async def publish_pipeline_version(version_id: int, body: PublishBody, auth=Depends(verify_human_admin)):
    try:
        return await pipelines.publish_version(version_id, actor=auth["sub"], binding_ids=body.binding_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/pipeline-versions/{version_id}/clone", status_code=201)
async def clone_pipeline_version(version_id: int, auth=Depends(verify_human_admin)):
    try:
        return await pipelines.clone_version(version_id, actor=auth["sub"])
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/pipeline-versions/{version_id}/rollback")
async def rollback_pipeline_version(version_id: int, body: PublishBody, auth=Depends(verify_human_admin)):
    try:
        return await pipelines.rollback_version(version_id, actor=auth["sub"], binding_ids=body.binding_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/pipeline-versions/{left_id}/diff/{right_id}")
async def diff_pipeline_versions(left_id: int, right_id: int):
    return await pipelines.diff_versions(left_id, right_id)


@router.get("/pipeline-runs")
async def list_runs(status: str | None = None, limit: int = Query(100, le=500)):
    async with async_session() as session:
        stmt = select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(PipelineRun.status == status)
        rows = (await session.scalars(stmt)).all()
        return [
            {"id": row.id, "order_id": row.order_id, "pipeline_version_id": row.pipeline_version_id,
             "status": row.status, "correlation_id": row.correlation_id, "error_code": row.error_code,
             "created_at": row.created_at.isoformat()} for row in rows
        ]


@router.get("/pipeline-runs/{run_id}")
async def get_run(run_id: int):
    async with async_session() as session:
        run = await session.get(PipelineRun, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        rows = (
            await session.execute(
                select(PipelineStepRun, PipelineStep)
                .join(PipelineStep, PipelineStep.id == PipelineStepRun.step_id)
                .where(PipelineStepRun.run_id == run_id)
                .order_by(PipelineStep.position, PipelineStepRun.attempt)
            )
        ).all()
        return {
            "id": run.id, "order_id": run.order_id, "status": run.status,
            "correlation_id": run.correlation_id, "context": run.context,
            "error_code": run.error_code, "error_detail": run.error_detail,
            "steps": [
                {"id": attempt.id, "step_id": step.id, "step_key": step.key, "type": step.type, "attempt": attempt.attempt,
                 "status": attempt.status, "inputs": attempt.inputs, "outputs": attempt.outputs,
                 "error_code": attempt.error_code, "error_detail": attempt.error_detail}
                for attempt, step in rows
            ],
        }


@router.post("/pipeline-runs/{run_id}/steps/{step_id}/retry")
async def retry_step(run_id: int, step_id: int, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        run, step = await session.get(PipelineRun, run_id), await session.get(PipelineStep, step_id)
        if not run or not step:
            raise HTTPException(404, "Run or step not found")
        method = str((step.config or {}).get("method", "GET")).upper()
        if step.type == "http.request" and method != "GET" and not step.idempotency_key_template:
            raise HTTPException(409, "Unsafe retry: idempotency key is missing")
        run.status, run.error_code, run.error_detail = "pending", None, None
        await session.commit()
    await enqueue("pipeline.continue", f"pipeline.retry:{run_id}:{step_id}:{datetime.now(timezone.utc).timestamp()}", {"run_id": run_id})
    await _audit(auth["sub"], "retry", "pipeline_step", step_id, {"run_id": run_id})
    return {"queued": True}


@router.get("/orders")
async def v1_orders(provider: str | None = None, status: str | None = None, limit: int = Query(100, le=500), offset: int = 0):
    async with async_session() as session:
        stmt = select(Order).order_by(Order.created_at.desc()).offset(offset).limit(limit)
        if provider:
            stmt = stmt.where(Order.marketplace == provider)
        if status:
            stmt = stmt.where(Order.normalized_status == status)
        rows = (await session.scalars(stmt)).all()
        return [{"id": o.id, "provider": o.marketplace, "provider_order_id": o.provider_order_id,
                 "invoice_id": o.invoice_id, "content_id": o.content_id, "item_id": o.item_id,
                 "status": o.normalized_status, "buyer_email": o.buyer_email,
                 "gross_rub": o.gross_rub, "net_rub": o.net_rub, "currency": o.currency,
                 "remnawave_user_id": o.remnawave_user_id,
                 "remnawave_uuid": o.remnawave_uuid, "pipeline_version_id": o.pipeline_version_id,
                 "created_at": o.created_at.isoformat()} for o in rows]


@router.get("/orders/{order_id}/events")
async def order_events(order_id: int):
    async with async_session() as session:
        rows = (await session.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.created_at))).all()
        return [{"id": row.id, "type": row.type, "payload": row.payload, "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/analytics/overview")
async def analytics_overview():
    async with async_session() as session:
        order_count = await session.scalar(select(func.count(Order.id))) or 0
        delivered = await session.scalar(select(func.count(Order.id)).where(Order.delivery_status == 1)) or 0
        # Digiseller webhooks historically stored amount but left *_rub null (WMR / missing profit).
        gross_expr = func.coalesce(Order.gross_rub, Order.gross_amount, Order.amount)
        net_expr = func.coalesce(Order.net_rub, Order.profit_amount, Order.net_amount, Order.gross_rub, Order.amount)
        gross = await session.scalar(select(func.coalesce(func.sum(gross_expr), 0))) or 0
        net = await session.scalar(select(func.coalesce(func.sum(net_expr), 0))) or 0
        needs_review = await session.scalar(select(func.count(PipelineRun.id)).where(PipelineRun.status == "needs_review")) or 0
        dead_letters = await session.scalar(select(func.count(DeadLetterJob.id))) or 0
        providers = (
            await session.execute(select(Order.marketplace, func.count(Order.id)).group_by(Order.marketplace))
        ).all()
        # Digiseller 12s SLA is the sync wall (run_before_response), not full async run lifetime.
        p95_digiseller = await session.scalar(text(
            "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY sync_seconds) FROM ("
            "  SELECT SUM(EXTRACT(EPOCH FROM (psr.completed_at - psr.started_at))) AS sync_seconds"
            "  FROM pipeline_runs pr"
            "  JOIN orders o ON o.id = pr.order_id"
            "  JOIN pipeline_step_runs psr ON psr.run_id = pr.id"
            "  JOIN pipeline_steps ps ON ps.id = psr.step_id"
            "  WHERE o.marketplace = 'digiseller'"
            "    AND ps.run_before_response IS TRUE"
            "    AND psr.started_at IS NOT NULL"
            "    AND psr.completed_at IS NOT NULL"
            "  GROUP BY pr.id"
            ") sync_walls"
        ))
        step_errors = (
            await session.execute(
                select(PipelineStepRun.error_code, func.count(PipelineStepRun.id))
                .where(PipelineStepRun.status == "failed")
                .group_by(PipelineStepRun.error_code)
                .order_by(func.count(PipelineStepRun.id).desc())
                .limit(10)
            )
        ).all()
        return {"orders": order_count, "delivered": delivered, "gross_rub": gross, "net_rub": net,
                "needs_review": needs_review, "dead_letters": dead_letters,
                "digiseller_p95_seconds": p95_digiseller,
                "digiseller_sync_limit_seconds": 12,
                "step_errors": [{"code": code or "unknown", "count": count} for code, count in step_errors],
                "providers": [{"provider": provider, "orders": count} for provider, count in providers]}


_SERIES_RANGES: dict[str, tuple[timedelta, str, timedelta]] = {
    # lookback, date_trunc unit, step between buckets
    "day": (timedelta(hours=24), "hour", timedelta(hours=1)),
    "week": (timedelta(days=7), "day", timedelta(days=1)),
    "month": (timedelta(days=30), "day", timedelta(days=1)),
    "3m": (timedelta(days=90), "week", timedelta(days=7)),
    "6m": (timedelta(days=180), "week", timedelta(days=7)),
    "year": (timedelta(days=365), "month", timedelta(days=31)),
}


def _truncate_bucket(moment: datetime, unit: str) -> datetime:
    moment = moment.astimezone(timezone.utc)
    if unit == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    if unit == "day":
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "week":
        day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unsupported bucket unit: {unit}")


def _next_bucket(moment: datetime, unit: str) -> datetime:
    if unit == "hour":
        return moment + timedelta(hours=1)
    if unit == "day":
        return moment + timedelta(days=1)
    if unit == "week":
        return moment + timedelta(days=7)
    if unit == "month":
        year, month = moment.year, moment.month + 1
        if month > 12:
            year, month = year + 1, 1
        return moment.replace(year=year, month=month)
    raise ValueError(f"unsupported bucket unit: {unit}")


def _iter_buckets(since: datetime, until: datetime, unit: str) -> list[datetime]:
    cursor = _truncate_bucket(since, unit)
    end = _truncate_bucket(until, unit)
    buckets: list[datetime] = []
    while cursor <= end:
        buckets.append(cursor)
        cursor = _next_bucket(cursor, unit)
    return buckets


@router.get("/analytics/series")
async def analytics_series(
    range: Literal["day", "week", "month", "3m", "6m", "year"] = Query("week"),
    metric: Literal["orders", "revenue"] = Query("orders"),
):
    lookback, unit, _ = _SERIES_RANGES[range]
    now = datetime.now(timezone.utc)
    since = now - lookback
    bucket_expr = func.date_trunc(unit, Order.created_at)
    value_expr = (
        func.count(Order.id)
        if metric == "orders"
        else func.coalesce(func.sum(func.coalesce(
            Order.net_rub, Order.profit_amount, Order.net_amount, Order.gross_rub, Order.amount,
        )), 0)
    )
    async with async_session() as session:
        rows = (
            await session.execute(
                select(bucket_expr.label("bucket"), Order.marketplace, value_expr.label("value"))
                .where(Order.created_at >= since)
                .group_by(bucket_expr, Order.marketplace)
                .order_by(bucket_expr)
            )
        ).all()

    by_bucket: dict[datetime, dict[str, float]] = {}
    for bucket, marketplace, value in rows:
        if bucket is None or not marketplace:
            continue
        key = bucket if bucket.tzinfo else bucket.replace(tzinfo=timezone.utc)
        key = key.astimezone(timezone.utc)
        cell = by_bucket.setdefault(key, {"ggsel": 0.0, "digiseller": 0.0})
        market = str(marketplace).lower()
        if market not in cell:
            cell[market] = 0.0
        amount = float(value) if isinstance(value, (int, float, Decimal)) else float(value or 0)
        cell[market] = amount

    series = []
    for bucket in _iter_buckets(since, now, unit):
        cell = by_bucket.get(bucket, {"ggsel": 0.0, "digiseller": 0.0})
        point = {
            "bucket": bucket.isoformat(),
            "ggsel": cell.get("ggsel", 0.0),
            "digiseller": cell.get("digiseller", 0.0),
        }
        for market, amount in cell.items():
            if market not in point:
                point[market] = amount
        series.append(point)
    return {"range": range, "metric": metric, "series": series}


@router.get("/templates")
async def list_templates():
    async with async_session() as session:
        rows = (await session.scalars(select(MessageTemplate).order_by(MessageTemplate.provider, MessageTemplate.name))).all()
        return [{"id": row.id, "key": row.key, "provider": row.provider, "name": row.name,
                 "format": row.format, "body": row.body, "enabled": row.enabled} for row in rows]


@router.post("/templates", status_code=201)
async def create_template(body: TemplateBody, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = MessageTemplate(**body.model_dump())
        session.add(row)
        await session.commit(); await session.refresh(row)
    await _audit(auth["sub"], "create", "message_template", row.id, body.model_dump())
    return {"id": row.id, **body.model_dump()}


@router.put("/templates/{template_id}")
async def update_template(template_id: int, body: TemplateBody, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(MessageTemplate, template_id)
        if not row: raise HTTPException(404, "Template not found")
        for key, value in body.model_dump().items(): setattr(row, key, value)
        await session.commit()
    await _audit(auth["sub"], "update", "message_template", template_id, body.model_dump())
    return {"id": template_id, **body.model_dump()}


@router.delete("/templates/{template_id}")
async def disable_template(template_id: int, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(MessageTemplate, template_id)
        if not row:
            raise HTTPException(404, "Template not found")
        row.enabled = False
        await session.commit()
    await _audit(auth["sub"], "disable", "message_template", template_id)
    return {"id": template_id, "enabled": False}


@router.get("/integration-profiles")
async def list_integrations():
    async with async_session() as session:
        rows = (await session.scalars(select(IntegrationProfile).order_by(IntegrationProfile.name))).all()
        return [{"id": row.id, "key": row.key, "name": row.name, "type": row.type,
                 "base_url": row.base_url, "auth_type": row.auth_type, "auth_config": row.auth_config,
                 "allowed_hosts": row.allowed_hosts, "enabled": row.enabled, "secrets_configured": True}
                for row in rows]


@router.post("/integration-profiles", status_code=201)
async def create_integration(body: IntegrationBody, auth=Depends(verify_human_admin)):
    payload = body.model_dump(exclude={"secrets"})
    async with async_session() as session:
        row = IntegrationProfile(**payload); session.add(row); await session.commit(); await session.refresh(row)
    for name, value in body.secrets.items(): await save_profile_secret(row.id, name, value)
    await _audit(auth["sub"], "create", "integration_profile", row.id, payload)
    return {"id": row.id, **payload, "secrets_configured": sorted(body.secrets)}


@router.put("/integration-profiles/{profile_id}")
async def update_integration(profile_id: int, body: IntegrationBody, auth=Depends(verify_human_admin)):
    payload = body.model_dump(exclude={"secrets"})
    async with async_session() as session:
        row = await session.get(IntegrationProfile, profile_id)
        if not row: raise HTTPException(404, "Integration not found")
        for key, value in payload.items(): setattr(row, key, value)
        await session.commit()
    for name, value in body.secrets.items(): await save_profile_secret(profile_id, name, value)
    await _audit(auth["sub"], "update", "integration_profile", profile_id, payload)
    return {"id": profile_id, **payload, "secrets_configured": sorted(body.secrets)}


@router.delete("/integration-profiles/{profile_id}")
async def disable_integration(profile_id: int, auth=Depends(verify_human_admin)):
    async with async_session() as session:
        row = await session.get(IntegrationProfile, profile_id)
        if not row:
            raise HTTPException(404, "Integration not found")
        row.enabled = False
        await session.commit()
    await _audit(auth["sub"], "disable", "integration_profile", profile_id)
    return {"id": profile_id, "enabled": False}


@router.get("/integration-health")
async def integration_health():
    result: dict[str, Any] = {"database": {"ok": False}, "ggsel": {}, "digiseller": {}}
    async with async_session() as session:
        await session.execute(text("SELECT 1")); result["database"] = {"ok": True, "driver": "postgresql"}
        checkpoints = (await session.scalars(select(SyncCheckpoint))).all()
        result["checkpoints"] = [{"provider": row.provider, "stream": row.stream,
                                  "last_success_at": row.last_success_at, "gap_detected": row.gap_detected,
                                  "detail": row.detail} for row in checkpoints]
        result["outbox"] = {status: count for status, count in (
            await session.execute(select(OutboxJob.status, func.count()).group_by(OutboxJob.status))
        ).all()}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
        for name, adapter in (("ggsel", ggsel), ("digiseller", digiseller)):
            try:
                await adapter.token(http)
                result[name] = {"ok": True, "token_valid_until": adapter.cache.valid_until}
            except Exception as exc:
                result[name] = {"ok": False, "error": str(exc)}
                continue
            if name == "digiseller" and result[name].get("ok"):
                result[name]["required_permissions"] = ["view_invoice", "debates_write", "token_get_perms"]
                try:
                    result[name]["permissions"] = await digiseller.permissions(http)
                except Exception as exc:
                    # Auth already succeeded; permissions is diagnostic-only.
                    result[name]["permissions_error"] = str(exc)
    return result


@router.post("/sync/catalog")
async def sync_catalog(): return await sync_all_catalogs()


@router.post("/sync/orders")
async def sync_orders(top: int = Query(50, ge=1, le=200)): return await sync_all_orders(top=top)


@router.get("/audit")
async def audit_log(limit: int = Query(100, le=500)):
    async with async_session() as session:
        rows = (await session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))).all()
        return [{"id": row.id, "actor": row.actor, "action": row.action, "entity_type": row.entity_type,
                 "entity_id": row.entity_id, "before": row.before, "after": row.after,
                 "created_at": row.created_at.isoformat()} for row in rows]
