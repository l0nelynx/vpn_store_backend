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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select

from store.database.models import (
    Customer,
    MarketplaceProduct,
    Order,
    OrderEvent,
    OrderParam,
    ParamValueMapping,
    PipelineRun,
    Product,
    ProductBinding,
    ProductOptionLabel,
    async_session,
)
from store.services.pipelines import bootstrap_legacy_pipelines


TABLES = (
    "customers",
    "orders",
    "order_params",
    "param_value_mappings",
    "product_option_labels",
)
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


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _options(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _is_delivered(source: dict[str, Any]) -> bool:
    """Trust only the legacy delivery flag, never a marketplace state alone."""
    try:
        return int(source.get("delivery_status") or 0) == 1
    except (TypeError, ValueError):
        return False


async def _legacy_customer(
    source_id: Any,
    sources: dict[int, dict[str, Any]],
    imported: dict[int, Customer],
    session,
) -> Customer | None:
    try:
        legacy_id = int(source_id)
    except (TypeError, ValueError):
        return None
    if legacy_id in imported:
        return imported[legacy_id]
    source = sources.get(legacy_id)
    if not source:
        return None
    email = _text(source.get("email"))
    normalized = _text(source.get("email_normalized")) or (email.lower() if email else None)
    ggsel_id = _text(source.get("ggsel_buyer_id"))
    digiseller_id = _text(source.get("digiseller_buyer_id"))
    clauses = []
    if normalized:
        clauses.append(Customer.email_normalized == normalized)
    if ggsel_id:
        clauses.append(Customer.ggsel_buyer_id == ggsel_id)
    if digiseller_id:
        clauses.append(Customer.digiseller_buyer_id == digiseller_id)
    customer = await session.scalar(select(Customer).where(or_(*clauses)).limit(1)) if clauses else None
    if customer is None:
        customer = Customer(
            email=email,
            email_normalized=normalized,
            ggsel_buyer_id=ggsel_id,
            digiseller_buyer_id=digiseller_id,
        )
        session.add(customer)
        await session.flush()
    else:
        customer.email = customer.email or email
        customer.email_normalized = customer.email_normalized or normalized
        customer.ggsel_buyer_id = customer.ggsel_buyer_id or ggsel_id
        customer.digiseller_buyer_id = customer.digiseller_buyer_id or digiseller_id
    imported[legacy_id] = customer
    return customer


async def _matching_orders(source: dict[str, Any], provider: str, session) -> list[Order]:
    external_id = _text(source.get("external_order_id"))
    invoice_id = _text(source.get("invoice_id"))
    clauses = []
    if external_id:
        clauses.append(Order.external_order_id == external_id)
    if invoice_id:
        clauses.extend((Order.provider_order_id == invoice_id, Order.invoice_id == invoice_id))
    if provider == "ggsel" and external_id:
        # In the legacy GGSel schema external_order_id held the chat/content id.
        clauses.extend((Order.content_id == external_id, Order.chat_id == external_id))
    if not clauses:
        return []
    return list((await session.scalars(
        select(Order).where(Order.marketplace == provider, or_(*clauses))
    )).all())


async def _import_delivered_orders(
    snapshot: dict[str, list[dict[str, Any]]], session
) -> dict[str, int]:
    result = {
        "legacy_orders_seen": len(snapshot["orders"]),
        "legacy_orders_delivered": 0,
        "orders_inserted": 0,
        "orders_reconciled": 0,
        "runs_suppressed": 0,
    }
    customer_sources = {
        int(row["id"]): row for row in snapshot["customers"] if row.get("id") is not None
    }
    customers: dict[int, Customer] = {}
    now = datetime.now(timezone.utc)
    for source in snapshot["orders"]:
        provider = _provider(source.get("marketplace"))
        if not provider or not _is_delivered(source):
            continue
        result["legacy_orders_delivered"] += 1
        matches = await _matching_orders(source, provider, session)
        if matches:
            for order in matches:
                was_terminal = order.delivery_status == 1
                order.delivery_status = 1
                order.status = order.normalized_status = "delivered"
                runs = list((await session.scalars(
                    select(PipelineRun).where(PipelineRun.order_id == order.id)
                )).all())
                for run in runs:
                    if run.status not in {"delivered", "delivered_with_warnings"}:
                        run.status = "delivered"
                        run.error_code = None
                        run.error_detail = None
                        run.execution_locked_at = None
                        run.completed_at = now
                        result["runs_suppressed"] += 1
                if not was_terminal:
                    session.add(OrderEvent(
                        order_id=order.id,
                        type="order.legacy_delivery_reconciled",
                        payload={"legacy_order_id": source.get("id")},
                    ))
                    result["orders_reconciled"] += 1
            continue

        external_id = _text(source.get("external_order_id"))
        invoice_id = _text(source.get("invoice_id"))
        if not external_id and not invoice_id:
            continue
        customer = await _legacy_customer(source.get("customer_id"), customer_sources, customers, session)
        item_id = source.get("item_id")
        binding = None
        if item_id is not None:
            binding = await session.scalar(select(ProductBinding).where(
                ProductBinding.provider == provider,
                ProductBinding.external_item_id == int(item_id),
            ))
        content_id = external_id if provider == "ggsel" else None
        provider_order_id = invoice_id or (external_id if provider == "digiseller" else None)
        options = _options(source.get("options_json"))
        order = Order(
            marketplace=provider,
            external_order_id=external_id or invoice_id,
            provider_order_id=provider_order_id,
            invoice_id=invoice_id or (provider_order_id if provider == "digiseller" else None),
            content_id=content_id,
            item_id=int(item_id) if item_id is not None else None,
            binding_id=binding.id if binding else None,
            options=options,
            options_json=source.get("options_json"),
            raw={"legacy_sqlite_order_id": source.get("id")},
            raw_state=_text(source.get("status")),
            normalized_status="delivered",
            status="delivered",
            delivery_status=1,
            buyer_email=customer.email if customer else None,
            amount=_decimal(source.get("amount")),
            currency=_text(source.get("currency")),
            chat_id=_text(source.get("chat_id")) or content_id or provider_order_id,
            days_ordered=source.get("days_ordered"),
            remnawave_username=_text(source.get("remnawave_username")),
            remnawave_uuid=_text(source.get("remnawave_uuid")),
            subscription_url=_text(source.get("subscription_url")),
            customer_id=customer.id if customer else None,
            created_at=_timestamp(source.get("created_at")) or now,
            updated_at=_timestamp(source.get("updated_at")) or now,
        )
        session.add(order)
        await session.flush()
        session.add(OrderEvent(
            order_id=order.id,
            type="order.legacy_delivery_imported",
            payload={"legacy_order_id": source.get("id")},
        ))
        result["orders_inserted"] += 1
    return result


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
    elif binding.status == "needs_configuration":
        # Legacy parameters make this binding unambiguous. It may already have
        # received a compatibility pipeline from an earlier worker bootstrap;
        # that must not prevent activation.
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
        result.update(await _import_delivered_orders(snapshot, session))
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
