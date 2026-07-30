"""Pipeline catalog, immutable versioning, publishing and product bindings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from store.database.models import (
    AuditLog,
    DeliveryPipeline,
    PipelineStep,
    PipelineVersion,
    Product,
    ProductBinding,
    async_session,
)
from store.domain.pipeline import PipelineDefinition, PipelineStepSpec, definition_hash, dry_run, validate_pipeline


def _step_dict(step: PipelineStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "key": step.key,
        "phase": step.phase,
        "type": step.type,
        "condition": step.condition,
        "required": step.required,
        "retry_policy": step.retry_policy,
        "timeout_seconds": step.timeout_seconds,
        "config": step.config,
        "idempotency_key_template": step.idempotency_key_template,
        "run_before_response": step.run_before_response,
    }


def _definition(pipeline: DeliveryPipeline, version: PipelineVersion) -> PipelineDefinition:
    return PipelineDefinition(
        providers=pipeline.providers or [],
        steps=[PipelineStepSpec.model_validate(_step_dict(step)) for step in version.steps],
    )


def _pipeline_dict(pipeline: DeliveryPipeline, include_versions: bool = False) -> dict[str, Any]:
    result = {
        "id": pipeline.id,
        "key": pipeline.key,
        "name": pipeline.name,
        "description": pipeline.description,
        "providers": pipeline.providers or [],
        "current_draft_version_id": pipeline.current_draft_version_id,
        "published_version_id": pipeline.published_version_id,
        "created_at": pipeline.created_at.isoformat() if pipeline.created_at else None,
        "updated_at": pipeline.updated_at.isoformat() if pipeline.updated_at else None,
    }
    if include_versions:
        result["versions"] = [
            {
                "id": version.id,
                "version": version.version,
                "status": version.status,
                "definition_hash": version.definition_hash,
                "created_by": version.created_by,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "published_at": version.published_at.isoformat() if version.published_at else None,
                "steps": [_step_dict(step) for step in version.steps],
            }
            for version in sorted(pipeline.versions, key=lambda item: item.version, reverse=True)
        ]
    return result


async def list_pipelines() -> list[dict[str, Any]]:
    async with async_session() as session:
        rows = (
            await session.scalars(
                select(DeliveryPipeline)
                .options(selectinload(DeliveryPipeline.versions).selectinload(PipelineVersion.steps))
                .order_by(DeliveryPipeline.updated_at.desc())
            )
        ).all()
        return [_pipeline_dict(row, include_versions=True) for row in rows]


async def get_pipeline(pipeline_id: int) -> dict[str, Any] | None:
    async with async_session() as session:
        row = await session.scalar(
            select(DeliveryPipeline)
            .where(DeliveryPipeline.id == pipeline_id)
            .options(selectinload(DeliveryPipeline.versions).selectinload(PipelineVersion.steps))
        )
        return _pipeline_dict(row, include_versions=True) if row else None


async def create_pipeline(
    *, key: str, name: str, description: str | None, providers: list[str], steps: list[dict], actor: str
) -> dict[str, Any]:
    definition = PipelineDefinition(providers=providers, steps=steps)
    async with async_session() as session:
        pipeline = DeliveryPipeline(key=key, name=name, description=description, providers=providers)
        session.add(pipeline)
        await session.flush()
        version = PipelineVersion(pipeline_id=pipeline.id, version=1, status="draft", created_by=actor)
        session.add(version)
        await session.flush()
        for position, spec in enumerate(definition.steps):
            session.add(PipelineStep(version_id=version.id, position=position, **spec.model_dump()))
        pipeline.current_draft_version_id = version.id
        session.add(AuditLog(actor=actor, action="create", entity_type="pipeline", entity_id=str(pipeline.id), after={"key": key}))
        await session.commit()
        return (await get_pipeline(pipeline.id)) or {}


async def replace_draft(version_id: int, steps: list[dict], *, actor: str) -> dict[str, Any]:
    async with async_session() as session:
        version = await session.get(PipelineVersion, version_id)
        if not version or version.status != "draft":
            raise ValueError("Only a draft version can be edited")
        pipeline = await session.get(DeliveryPipeline, version.pipeline_id)
        definition = PipelineDefinition(providers=pipeline.providers or [], steps=steps)
        await session.execute(delete(PipelineStep).where(PipelineStep.version_id == version.id))
        for position, spec in enumerate(definition.steps):
            session.add(PipelineStep(version_id=version.id, position=position, **spec.model_dump()))
        session.add(AuditLog(actor=actor, action="edit", entity_type="pipeline_version", entity_id=str(version.id), after=definition.model_dump(mode="json")))
        await session.commit()
    return await get_version(version_id)


async def get_version(version_id: int) -> dict[str, Any]:
    async with async_session() as session:
        version = await session.scalar(
            select(PipelineVersion)
            .where(PipelineVersion.id == version_id)
            .options(selectinload(PipelineVersion.steps))
        )
        if not version:
            raise ValueError("Pipeline version not found")
        pipeline = await session.get(DeliveryPipeline, version.pipeline_id)
        return {
            "id": version.id,
            "pipeline_id": version.pipeline_id,
            "version": version.version,
            "status": version.status,
            "definition_hash": version.definition_hash,
            "providers": pipeline.providers or [],
            "steps": [_step_dict(step) for step in version.steps],
        }


async def validate_version(version_id: int) -> dict[str, Any]:
    data = await get_version(version_id)
    definition = PipelineDefinition(providers=data["providers"], steps=data["steps"])
    issues = validate_pipeline(definition)
    return {"valid": not any(item.level == "error" for item in issues), "issues": [item.as_dict() for item in issues]}


async def dry_run_version(version_id: int, context: dict[str, Any]) -> dict[str, Any]:
    data = await get_version(version_id)
    return dry_run(PipelineDefinition(providers=data["providers"], steps=data["steps"]), context)


async def publish_version(version_id: int, *, actor: str, binding_ids: list[int] | None = None) -> dict[str, Any]:
    async with async_session() as session:
        version = await session.scalar(
            select(PipelineVersion)
            .where(PipelineVersion.id == version_id)
            .options(selectinload(PipelineVersion.steps))
        )
        if not version or version.status != "draft":
            raise ValueError("Only a draft version can be published")
        pipeline = await session.get(DeliveryPipeline, version.pipeline_id)
        definition = _definition(pipeline, version)
        issues = validate_pipeline(definition)
        errors = [issue for issue in issues if issue.level == "error"]
        if errors:
            raise ValueError("; ".join(issue.message for issue in errors))
        now = datetime.now(timezone.utc)
        version.status = "published"
        version.published_at = now
        version.definition_hash = definition_hash(definition)
        pipeline.published_version_id = version.id
        pipeline.current_draft_version_id = None
        if binding_ids:
            bindings = (
                await session.scalars(select(ProductBinding).where(ProductBinding.id.in_(binding_ids)))
            ).all()
            providers = {binding.provider for binding in bindings}
            if not providers.issubset(set(pipeline.providers or [])):
                raise ValueError("Binding provider is not enabled by this pipeline")
            for binding in bindings:
                binding.published_pipeline_version_id = version.id
                product = await session.get(Product, binding.product_id)
                if product:
                    product.published_pipeline_version_id = version.id
                    product.status = "active"
        session.add(AuditLog(actor=actor, action="publish", entity_type="pipeline_version", entity_id=str(version.id), after={"hash": version.definition_hash, "bindings": binding_ids or []}))
        await session.commit()
    return await get_version(version_id)


async def clone_version(version_id: int, *, actor: str) -> dict[str, Any]:
    async with async_session() as session:
        source = await session.scalar(
            select(PipelineVersion).where(PipelineVersion.id == version_id).options(selectinload(PipelineVersion.steps))
        )
        if not source:
            raise ValueError("Pipeline version not found")
        pipeline = await session.get(DeliveryPipeline, source.pipeline_id)
        current = await session.scalar(select(func.max(PipelineVersion.version)).where(PipelineVersion.pipeline_id == source.pipeline_id))
        target = PipelineVersion(pipeline_id=source.pipeline_id, version=int(current or 0) + 1, status="draft", created_by=actor)
        session.add(target)
        await session.flush()
        for position, step in enumerate(source.steps):
            payload = _step_dict(step)
            payload.pop("id", None)
            session.add(PipelineStep(version_id=target.id, position=position, **payload))
        pipeline.current_draft_version_id = target.id
        session.add(AuditLog(actor=actor, action="clone", entity_type="pipeline_version", entity_id=str(target.id), after={"source_version_id": source.id}))
        await session.commit()
    return await get_version(target.id)


async def rollback_version(version_id: int, *, actor: str, binding_ids: list[int] | None = None) -> dict[str, Any]:
    """Point a pipeline and its existing bindings at an older immutable version."""
    async with async_session() as session:
        target = await session.get(PipelineVersion, version_id)
        if not target or target.status != "published":
            raise ValueError("Rollback target must be a published version")
        pipeline = await session.get(DeliveryPipeline, target.pipeline_id)
        version_ids = select(PipelineVersion.id).where(PipelineVersion.pipeline_id == pipeline.id)
        stmt = select(ProductBinding).where(ProductBinding.published_pipeline_version_id.in_(version_ids))
        if binding_ids:
            stmt = stmt.where(ProductBinding.id.in_(binding_ids))
        bindings = (await session.scalars(stmt)).all()
        providers = {binding.provider for binding in bindings}
        if not providers.issubset(set(pipeline.providers or [])):
            raise ValueError("Binding provider is not enabled by this pipeline")
        pipeline.published_version_id = target.id
        for binding in bindings:
            binding.published_pipeline_version_id = target.id
            product = await session.get(Product, binding.product_id)
            if product:
                product.published_pipeline_version_id = target.id
        session.add(AuditLog(
            actor=actor,
            action="rollback",
            entity_type="pipeline_version",
            entity_id=str(target.id),
            after={"bindings": [binding.id for binding in bindings]},
        ))
        await session.commit()
    return await get_version(version_id)


async def diff_versions(left_id: int, right_id: int) -> dict[str, Any]:
    left, right = await get_version(left_id), await get_version(right_id)
    left_steps = {step["key"]: step for step in left["steps"]}
    right_steps = {step["key"]: step for step in right["steps"]}
    return {
        "added": [right_steps[key] for key in right_steps.keys() - left_steps.keys()],
        "removed": [left_steps[key] for key in left_steps.keys() - right_steps.keys()],
        "changed": [
            {"key": key, "before": left_steps[key], "after": right_steps[key]}
            for key in left_steps.keys() & right_steps.keys()
            if left_steps[key] != right_steps[key]
        ],
    }


LEGACY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "ggsel": {
        "key": "legacy-ggsel-remnawave",
        "name": "GGSel · Remnawave",
        "steps": [
            {"key": "paid", "phase": "trigger", "type": "trigger.conditions", "condition": {"path": "order.normalized_status", "op": "equals", "value": "paid"}},
            {"key": "provision", "phase": "action", "type": "remnawave.provision_subscription", "config": {"username_template": "gg_id{{ order.content_id }}", "days_path": "product.parameters.days", "days_default": 30}, "idempotency_key_template": "remnawave:{{ system.run_id }}:provision"},
            {"key": "buyer_message", "phase": "delivery", "type": "marketplace.message", "required": True, "config": {"template_key": "ggsel_delivery"}},
        ],
    },
    "digiseller": {
        "key": "legacy-digiseller-remnawave",
        "name": "Digiseller · Remnawave",
        "steps": [
            {"key": "signed", "phase": "trigger", "type": "trigger.conditions", "timeout_seconds": 1, "run_before_response": True},
            {"key": "provision", "phase": "action", "type": "remnawave.provision_subscription", "timeout_seconds": 8, "config": {"username_template": "dig_id{{ order.provider_order_id }}", "days_path": "product.parameters.days", "days_default": 30}, "idempotency_key_template": "remnawave:{{ system.run_id }}:provision", "run_before_response": True},
            {"key": "webhook", "phase": "delivery", "type": "webhook.response", "required": True, "timeout_seconds": 2, "config": {"goods_template": "{{ steps.provision.outputs.subscription_url }}", "format": "plain"}, "run_before_response": True},
            {"key": "buyer_message", "phase": "delivery", "type": "marketplace.message", "required": False, "config": {"template_key": "digiseller_delivery"}},
        ],
    },
}


async def bootstrap_legacy_pipelines() -> None:
    """Create deterministic compatibility pipelines and attach unconfigured bindings."""
    for provider, payload in LEGACY_DEFINITIONS.items():
        async with async_session() as session:
            existing = await session.scalar(select(DeliveryPipeline).where(DeliveryPipeline.key == payload["key"]))
        if not existing:
            created = await create_pipeline(
                key=payload["key"], name=payload["name"], description="Generated from dev fulfillment flow",
                providers=[provider], steps=payload["steps"], actor="system:migration",
            )
            await publish_version(created["current_draft_version_id"], actor="system:migration")
        async with async_session() as session:
            pipeline = await session.scalar(select(DeliveryPipeline).where(DeliveryPipeline.key == payload["key"]))
            bindings = (
                await session.scalars(
                    select(ProductBinding).where(
                        ProductBinding.provider == provider,
                        ProductBinding.status == "active",
                        ProductBinding.published_pipeline_version_id.is_(None),
                    )
                )
            ).all()
            for binding in bindings:
                binding.published_pipeline_version_id = pipeline.published_version_id
                product = await session.get(Product, binding.product_id)
                if product and not product.published_pipeline_version_id:
                    product.published_pipeline_version_id = pipeline.published_version_id
                    product.status = "active"
            await session.commit()
