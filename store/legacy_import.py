"""One-way, idempotent import of the pre-PostgreSQL Store configuration.

The runtime remains PostgreSQL-only.  This module exists solely to recover the
legacy SQLite configuration during rollout; the source database is always
opened read-only and is never modified.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select

from store.database.models import (
    MarketplaceProduct,
    OrderParam,
    ParamValueMapping,
    Product,
    ProductBinding,
    ProductOptionLabel,
    async_session,
)
from store.services.pipelines import bootstrap_legacy_pipelines


TABLES = ("order_params", "param_value_mappings", "product_option_labels")
PROVIDERS = {"ggsel", "digiseller"}


def read_legacy_snapshot(path: Path) -> dict[str, list[dict[str, Any]]]:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        existing = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            if table in existing
            else []
            for table in TABLES
        }
    finally:
        connection.close()


def _provider(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in PROVIDERS else None


async def _provider_candidates(snapshot: dict[str, list[dict[str, Any]]], session) -> dict[int, set[str]]:
    candidates: dict[int, set[str]] = defaultdict(set)
    for row in snapshot["product_option_labels"]:
        provider = _provider(row.get("marketplace"))
        if provider and row.get("item_id") is not None:
            candidates[int(row["item_id"])].add(provider)
    labels = await session.execute(select(ProductOptionLabel.item_id, ProductOptionLabel.marketplace))
    for item_id, value in labels:
        if provider := _provider(value):
            candidates[int(item_id)].add(provider)
    products = await session.execute(select(MarketplaceProduct.external_item_id, MarketplaceProduct.provider))
    for item_id, value in products:
        if provider := _provider(value):
            candidates[int(item_id)].add(provider)
    return candidates


async def _binding(provider: str, item_id: int, session) -> ProductBinding:
    binding = await session.scalar(
        select(ProductBinding).where(
            ProductBinding.provider == provider,
            ProductBinding.external_item_id == item_id,
        )
    )
    if binding is None:
        keys = (f"legacy-{provider}-{item_id}", f"import-{provider}-{item_id}")
        product = await session.scalar(select(Product).where(Product.key.in_(keys)).limit(1))
        if product is None:
            cached = await session.scalar(
                select(MarketplaceProduct).where(
                    MarketplaceProduct.provider == provider,
                    MarketplaceProduct.external_item_id == item_id,
                )
            )
            product = Product(
                key=keys[0],
                name=(cached.name if cached else None) or f"{provider} #{item_id}",
                status="active",
            )
            session.add(product)
            await session.flush()
        binding = ProductBinding(
            product_id=product.id,
            provider=provider,
            external_item_id=item_id,
            trigger_policy="automatic",
            status="active",
            option_mappings={},
        )
        session.add(binding)
        await session.flush()
    elif binding.status == "needs_configuration" and binding.published_pipeline_version_id is None:
        binding.status = "active"
        binding.trigger_policy = "automatic"
        product = await session.get(Product, binding.product_id)
        if product:
            product.status = "active"
    return binding


async def import_snapshot(snapshot: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    result = {
        "mappings_inserted": 0,
        "mappings_existing": 0,
        "labels_inserted": 0,
        "labels_existing": 0,
        "params_inserted": 0,
        "params_existing": 0,
        "params_needs_configuration": 0,
    }
    async with async_session() as session:
        for source in snapshot["param_value_mappings"]:
            type_ = str(source.get("type") or "").strip()
            value = str(source.get("value") or "").strip()
            label = str(source.get("label") or value).strip()
            if not type_ or not value:
                continue
            existing = await session.scalar(
                select(ParamValueMapping).where(
                    ParamValueMapping.type == type_, ParamValueMapping.value == value
                )
            )
            if existing:
                result["mappings_existing"] += 1
            else:
                session.add(ParamValueMapping(type=type_, label=label, value=value))
                result["mappings_inserted"] += 1

        for source in snapshot["product_option_labels"]:
            provider = _provider(source.get("marketplace"))
            required = (source.get("item_id"), source.get("param_id"), source.get("user_data_id"))
            if not provider or any(value is None for value in required):
                continue
            item_id, param_id, user_data_id = map(int, required)
            existing = await session.scalar(
                select(ProductOptionLabel).where(
                    ProductOptionLabel.marketplace == provider,
                    ProductOptionLabel.item_id == item_id,
                    ProductOptionLabel.param_id == param_id,
                    ProductOptionLabel.user_data_id == user_data_id,
                )
            )
            if existing:
                result["labels_existing"] += 1
            else:
                session.add(ProductOptionLabel(
                    marketplace=provider,
                    item_id=item_id,
                    param_id=param_id,
                    user_data_id=user_data_id,
                    item_name=source.get("item_name"),
                    param_name=source.get("param_name"),
                    variant_name=source.get("variant_name"),
                ))
                result["labels_inserted"] += 1

        await session.flush()
        candidates = await _provider_candidates(snapshot, session)
        for source in snapshot["order_params"]:
            required = (source.get("item_id"), source.get("param_id"), source.get("user_data_id"))
            type_ = str(source.get("type") or "").strip()
            data = str(source.get("data") or "").strip()
            if any(value is None for value in required) or not type_:
                continue
            item_id, param_id, user_data_id = map(int, required)
            provider = _provider(source.get("marketplace"))
            if provider is None and len(candidates[item_id]) == 1:
                provider = next(iter(candidates[item_id]))
            binding = await _binding(provider, item_id, session) if provider else None
            marketplace_condition = (
                OrderParam.marketplace == provider if provider else OrderParam.marketplace.is_(None)
            )
            existing = await session.scalar(
                select(OrderParam).where(
                    and_(
                        OrderParam.item_id == item_id,
                        OrderParam.param_id == param_id,
                        OrderParam.user_data_id == user_data_id,
                        OrderParam.type == type_,
                        OrderParam.data == data,
                        marketplace_condition,
                    )
                )
            )
            if existing:
                existing.binding_id = binding.id if binding else None
                existing.configuration_status = "configured" if binding else "needs_configuration"
                result["params_existing"] += 1
            else:
                session.add(OrderParam(
                    item_id=item_id,
                    param_id=param_id,
                    user_data_id=user_data_id,
                    type=type_,
                    data=data,
                    marketplace=provider,
                    binding_id=binding.id if binding else None,
                    configuration_status="configured" if binding else "needs_configuration",
                ))
                result["params_inserted"] += 1
            if binding is None:
                result["params_needs_configuration"] += 1
        await session.commit()
    await bootstrap_legacy_pipelines()
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy Store SQLite configuration")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--if-exists", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.source.is_file():
        if args.if_exists:
            print(json.dumps({"status": "skipped", "reason": "source_not_found"}))
            return 0
        raise FileNotFoundError(args.source)
    snapshot = read_legacy_snapshot(args.source)
    counts = {table: len(rows) for table, rows in snapshot.items()}
    if not args.apply:
        print(json.dumps({"status": "dry_run", "source": str(args.source), "counts": counts}))
        return 0
    result = await import_snapshot(snapshot)
    print(json.dumps({"status": "imported", "source": str(args.source), "counts": counts, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
