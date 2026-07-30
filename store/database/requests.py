"""Database access layer for Store."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update

from store.database.models import (
    Customer,
    Message,
    Order,
    OrderParam,
    ParamValueMapping,
    MarketplaceProduct,
    Product,
    ProductBinding,
    ProductOptionLabel,
    SubscriptionEvent,
    Transaction,
    User,
    async_session,
)

logger = logging.getLogger(__name__)


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    e = email.strip().lower()
    if not e or e.endswith("@cheeze.com") or e.endswith("@marzban.ru") or e.endswith("@bot.local"):
        return None
    return e


@asynccontextmanager
async def get_session(existing_session=None):
    if existing_session is not None:
        yield existing_session
    else:
        async with async_session() as session:
            yield session


# ── Customers / Orders ──────────────────────────────────────────────────────


async def get_or_create_customer(
    *,
    email: str | None = None,
    ggsel_buyer_id: str | None = None,
    digiseller_buyer_id: str | None = None,
    session=None,
) -> Customer:
    async with get_session(session) as s:
        norm = normalize_email(email)
        customer = None
        if norm:
            customer = await s.scalar(
                select(Customer).where(Customer.email_normalized == norm)
            )
        if customer is None and ggsel_buyer_id:
            customer = await s.scalar(
                select(Customer).where(Customer.ggsel_buyer_id == str(ggsel_buyer_id))
            )
        if customer is None and digiseller_buyer_id:
            customer = await s.scalar(
                select(Customer).where(
                    Customer.digiseller_buyer_id == str(digiseller_buyer_id)
                )
            )
        if customer is None:
            customer = Customer(
                email=email,
                email_normalized=norm,
                ggsel_buyer_id=str(ggsel_buyer_id) if ggsel_buyer_id else None,
                digiseller_buyer_id=str(digiseller_buyer_id) if digiseller_buyer_id else None,
            )
            s.add(customer)
            await s.flush()
        else:
            if norm and not customer.email_normalized:
                customer.email = email
                customer.email_normalized = norm
            if ggsel_buyer_id and not customer.ggsel_buyer_id:
                customer.ggsel_buyer_id = str(ggsel_buyer_id)
            if digiseller_buyer_id and not customer.digiseller_buyer_id:
                customer.digiseller_buyer_id = str(digiseller_buyer_id)
            await s.flush()
        if session is None:
            await s.commit()
            await s.refresh(customer)
        return customer


async def get_order_by_external(
    marketplace: str, external_order_id: str, session=None
) -> Order | None:
    async with get_session(session) as s:
        return await s.scalar(
            select(Order).where(
                Order.marketplace == marketplace,
                Order.external_order_id == str(external_order_id),
            )
        )


async def get_order_by_provider_id(
    marketplace: str, provider_order_id: str, session=None
) -> Order | None:
    """Canonical idempotency lookup (GGSel invoice_id, Digiseller inv)."""
    async with get_session(session) as s:
        return await s.scalar(
            select(Order).where(
                Order.marketplace == marketplace,
                Order.provider_order_id == str(provider_order_id),
            )
        )


async def get_orders_by_externals(
    marketplace: str, external_order_ids: list[str], session=None
) -> dict[str, Order]:
    """Batch load orders keyed by external_order_id."""
    ids = [str(x) for x in external_order_ids if x is not None and str(x)]
    if not ids:
        return {}
    async with get_session(session) as s:
        rows = (
            await s.scalars(
                select(Order).where(
                    Order.marketplace == marketplace,
                    Order.external_order_id.in_(ids),
                )
            )
        ).all()
        return {o.external_order_id: o for o in rows}


async def get_orders_by_invoice_ids(
    marketplace: str, invoice_ids: list[str], session=None
) -> dict[str, Order]:
    """Batch load orders keyed by invoice_id."""
    ids = [str(x) for x in invoice_ids if x is not None and str(x)]
    if not ids:
        return {}
    async with get_session(session) as s:
        rows = (
            await s.scalars(
                select(Order).where(
                    Order.marketplace == marketplace,
                    Order.invoice_id.in_(ids),
                )
            )
        ).all()
        return {str(o.invoice_id): o for o in rows if o.invoice_id}


async def create_order(
    *,
    marketplace: str,
    external_order_id: str,
    invoice_id: str | None = None,
    item_id: int | None = None,
    options: list | dict | None = None,
    amount: float | None = None,
    currency: str | None = None,
    chat_id: str | None = None,
    days_ordered: int | None = None,
    remnawave_username: str | None = None,
    customer_id: int | None = None,
    status: str = "created",
    session=None,
) -> Order:
    async with get_session(session) as s:
        order = Order(
            marketplace=marketplace,
            external_order_id=str(external_order_id),
            provider_order_id=(
                str(invoice_id)
                if marketplace == "ggsel" and invoice_id is not None
                else str(external_order_id)
            ),
            invoice_id=str(invoice_id) if invoice_id is not None else None,
            content_id=str(external_order_id) if marketplace == "ggsel" else None,
            item_id=item_id,
            options=options or [],
            options_json=json.dumps(options, ensure_ascii=False) if options is not None else None,
            amount=amount,
            currency=currency,
            chat_id=str(chat_id) if chat_id is not None else None,
            days_ordered=days_ordered,
            remnawave_username=remnawave_username,
            customer_id=customer_id,
            status=status,
            normalized_status=status,
            delivery_status=0,
        )
        s.add(order)
        await s.flush()
        if session is None:
            await s.commit()
            await s.refresh(order)
        return order


async def update_order(order_id: int, session=None, **fields) -> Order | None:
    async with get_session(session) as s:
        order = await s.get(Order, order_id)
        if order is None:
            return None
        for key, value in fields.items():
            if hasattr(order, key):
                setattr(order, key, value)
        await s.flush()
        if session is None:
            await s.commit()
            await s.refresh(order)
        return order


async def add_subscription_event(
    order_id: int,
    event_type: str,
    *,
    days: int | None = None,
    remnawave_uuid: str | None = None,
    detail: str | None = None,
    session=None,
) -> SubscriptionEvent:
    async with get_session(session) as s:
        ev = SubscriptionEvent(
            order_id=order_id,
            event_type=event_type,
            days=days,
            remnawave_uuid=remnawave_uuid,
            detail=detail,
        )
        s.add(ev)
        await s.flush()
        if session is None:
            await s.commit()
        return ev


def _orders_filter_stmt(
    *,
    email: str | None = None,
    marketplace: str | None = None,
    remnawave_uuid: str | None = None,
    remnawave_username: str | None = None,
    external_order_id: str | None = None,
    q: str | None = None,
):
    stmt = select(Order, Customer).outerjoin(Customer, Customer.id == Order.customer_id)
    if email:
        norm = normalize_email(email) or email.strip().lower()
        stmt = stmt.where(Customer.email_normalized == norm)
    if marketplace:
        stmt = stmt.where(Order.marketplace == marketplace)
    if remnawave_uuid:
        stmt = stmt.where(Order.remnawave_uuid == remnawave_uuid)
    if remnawave_username:
        stmt = stmt.where(Order.remnawave_username == remnawave_username)
    if external_order_id:
        oid = str(external_order_id)
        stmt = stmt.where(
            or_(Order.external_order_id == oid, Order.invoice_id == oid)
        )
    if q:
        qq = q.strip()
        if qq:
            like = f"%{qq}%"
            stmt = stmt.where(
                or_(
                    Order.external_order_id == qq,
                    Order.invoice_id == qq,
                    Order.external_order_id.ilike(like),
                    Order.invoice_id.ilike(like),
                    Customer.email.ilike(like),
                    Customer.email_normalized.ilike(like),
                )
            )
    return stmt


_ORDER_SORT_COLS = {
    "created_at": Order.created_at,
    "external_order_id": Order.external_order_id,
    "marketplace": Order.marketplace,
    "delivery_status": Order.delivery_status,
}


async def list_orders(
    *,
    email: str | None = None,
    marketplace: str | None = None,
    remnawave_uuid: str | None = None,
    remnawave_username: str | None = None,
    external_order_id: str | None = None,
    q: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    session=None,
) -> list[dict]:
    async with get_session(session) as s:
        stmt = _orders_filter_stmt(
            email=email,
            marketplace=marketplace,
            remnawave_uuid=remnawave_uuid,
            remnawave_username=remnawave_username,
            external_order_id=external_order_id,
            q=q,
        )
        col = _ORDER_SORT_COLS.get(sort, Order.created_at)
        stmt = stmt.order_by(col.asc() if order == "asc" else col.desc())
        stmt = stmt.offset(offset).limit(limit)
        rows = (await s.execute(stmt)).all()
        return [_order_dict(o, c) for o, c in rows]


async def get_customer_by_id(customer_id: int, session=None) -> Customer | None:
    async with get_session(session) as s:
        return await s.get(Customer, customer_id)


async def get_customer_360(
    *,
    email: str | None = None,
    customer_id: int | None = None,
    remnawave_uuid: str | None = None,
    session=None,
) -> dict | None:
    async with get_session(session) as s:
        customer = None
        if customer_id:
            customer = await s.get(Customer, customer_id)
        elif email:
            norm = normalize_email(email) or email.strip().lower()
            customer = await s.scalar(
                select(Customer).where(Customer.email_normalized == norm)
            )
        elif remnawave_uuid:
            order = await s.scalar(
                select(Order).where(Order.remnawave_uuid == remnawave_uuid).limit(1)
            )
            if order and order.customer_id:
                customer = await s.get(Customer, order.customer_id)
        if customer is None:
            return None
        orders = (
            await s.scalars(
                select(Order)
                .where(Order.customer_id == customer.id)
                .order_by(Order.created_at.desc())
            )
        ).all()
        return {
            "id": customer.id,
            "email": customer.email,
            "email_normalized": customer.email_normalized,
            "ggsel_buyer_id": customer.ggsel_buyer_id,
            "digiseller_buyer_id": customer.digiseller_buyer_id,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
            "orders": [_order_dict(o, customer) for o in orders],
            "order_count": len(orders),
        }


async def resolve_recipients(
    *,
    remnawave_uuids: list[str] | None = None,
    usernames: list[str] | None = None,
    emails: list[str] | None = None,
    session=None,
) -> list[dict]:
    """Match store orders/customers for CRM broadcast."""
    async with get_session(session) as s:
        found: dict[int, dict] = {}
        clauses = []
        if remnawave_uuids:
            clauses.append(Order.remnawave_uuid.in_(remnawave_uuids))
        if usernames:
            clauses.append(Order.remnawave_username.in_(usernames))
        if emails:
            norms = [normalize_email(e) or e.strip().lower() for e in emails]
            cust_ids = (
                await s.scalars(
                    select(Customer.id).where(Customer.email_normalized.in_(norms))
                )
            ).all()
            if cust_ids:
                clauses.append(Order.customer_id.in_(list(cust_ids)))
        if not clauses:
            return []
        stmt = (
            select(Order, Customer)
            .outerjoin(Customer, Customer.id == Order.customer_id)
            .where(or_(*clauses))
            .order_by(Order.created_at.desc())
        )
        for order, customer in (await s.execute(stmt)).all():
            # Prefer newest order per customer for chat delivery
            key = order.customer_id or order.id
            if key in found:
                continue
            found[key] = {
                "order_id": order.id,
                "marketplace": order.marketplace,
                "external_order_id": order.external_order_id,
                "chat_id": order.chat_id or order.external_order_id,
                "remnawave_uuid": order.remnawave_uuid,
                "remnawave_username": order.remnawave_username,
                "email": customer.email if customer else None,
                "customer_id": order.customer_id,
            }
        return list(found.values())


def _order_dict(order: Order, customer: Customer | None = None) -> dict:
    return {
        "id": order.id,
        "marketplace": order.marketplace,
        "external_order_id": order.external_order_id,
        "provider_order_id": order.provider_order_id,
        "invoice_id": order.invoice_id,
        "content_id": order.content_id,
        "cart_uid": order.cart_uid,
        "item_id": order.item_id,
        "amount": order.amount,
        "gross_amount": order.gross_amount,
        "net_amount": order.net_amount,
        "profit_amount": order.profit_amount,
        "gross_rub": order.gross_rub,
        "net_rub": order.net_rub,
        "currency": order.currency,
        "status": order.status,
        "normalized_status": order.normalized_status,
        "delivery_status": order.delivery_status,
        "chat_id": order.chat_id,
        "days_ordered": order.days_ordered,
        "remnawave_username": order.remnawave_username,
        "remnawave_uuid": order.remnawave_uuid,
        "subscription_url": order.subscription_url,
        "customer_id": order.customer_id,
        "email": order.buyer_email or (customer.email if customer else None),
        "pipeline_version_id": order.pipeline_version_id,
        "final_delivery_response": order.final_delivery_response,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


# ── Products ────────────────────────────────────────────────────────────────


async def upsert_product(
    *,
    marketplace: str,
    external_item_id: int,
    name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    raw_json: str | None = None,
    is_hidden: bool = False,
    session=None,
) -> MarketplaceProduct:
    async with get_session(session) as s:
        product = await s.scalar(
            select(MarketplaceProduct).where(
                MarketplaceProduct.provider == marketplace,
                MarketplaceProduct.external_item_id == external_item_id,
            )
        )
        if product is None:
            product = MarketplaceProduct(
                provider=marketplace,
                external_item_id=external_item_id,
            )
            s.add(product)
        product.name = name
        product.price = price
        product.currency = currency
        try:
            product.raw = json.loads(raw_json) if raw_json else {}
        except (TypeError, ValueError):
            product.raw = {"unparsed": str(raw_json)}
        product.is_hidden = is_hidden
        product.synced_at = datetime.now(timezone.utc)
        await s.flush()
        binding = await s.scalar(
            select(ProductBinding).where(
                ProductBinding.provider == marketplace,
                ProductBinding.external_item_id == external_item_id,
            )
        )
        legacy_params = (
            await s.scalars(
                select(OrderParam).where(
                    OrderParam.marketplace == marketplace,
                    OrderParam.item_id == external_item_id,
                )
            )
        ).all()
        if binding is None:
            local = Product(
                key=f"import-{marketplace}-{external_item_id}",
                name=name or f"{marketplace} #{external_item_id}",
                status="active" if legacy_params else "draft",
            )
            s.add(local)
            await s.flush()
            binding = ProductBinding(
                product_id=local.id,
                provider=marketplace,
                external_item_id=external_item_id,
                trigger_policy="automatic" if legacy_params else "manual",
                status="active" if legacy_params else "needs_configuration",
                option_mappings={},
            )
            s.add(binding)
            await s.flush()
        elif (
            legacy_params
            and binding.status == "needs_configuration"
        ):
            binding.status = "active"
            binding.trigger_policy = "automatic"
        if legacy_params:
            for parameter in legacy_params:
                parameter.binding_id = binding.id
                parameter.configuration_status = "configured"
        if session is None:
            await s.commit()
            await s.refresh(product)
        return product


async def list_products(marketplace: str | None = None, session=None) -> list[dict]:
    async with get_session(session) as s:
        stmt = select(MarketplaceProduct)
        if marketplace:
            stmt = stmt.where(MarketplaceProduct.provider == marketplace)
        stmt = stmt.order_by(MarketplaceProduct.provider, MarketplaceProduct.external_item_id)
        rows = (await s.scalars(stmt)).all()
        return [
            {
                "id": p.id,
                "marketplace": p.provider,
                "external_item_id": p.external_item_id,
                "name": p.name,
                "price": p.price,
                "currency": p.currency,
                "is_hidden": p.is_hidden,
                "synced_at": p.synced_at.isoformat() if p.synced_at else None,
            }
            for p in rows
        ]


# ── Messages ────────────────────────────────────────────────────────────────


async def upsert_message(
    *,
    marketplace: str,
    external_msg_id: str | None,
    direction: str,
    body: str | None,
    chat_id: str | None = None,
    order_id: int | None = None,
    customer_id: int | None = None,
    is_file: bool = False,
    file_url: str | None = None,
    written_at: datetime | None = None,
    session=None,
) -> Message | None:
    async with get_session(session) as s:
        if external_msg_id:
            existing = await s.scalar(
                select(Message).where(
                    Message.marketplace == marketplace,
                    Message.external_msg_id == str(external_msg_id),
                )
            )
            if existing:
                return existing
        msg = Message(
            marketplace=marketplace,
            external_msg_id=str(external_msg_id) if external_msg_id else None,
            direction=direction,
            body=body,
            chat_id=str(chat_id) if chat_id else None,
            order_id=order_id,
            customer_id=customer_id,
            is_file=is_file,
            file_url=file_url,
            written_at=written_at,
        )
        s.add(msg)
        await s.flush()
        if session is None:
            await s.commit()
            await s.refresh(msg)
        return msg


async def list_messages(
    *,
    customer_id: int | None = None,
    order_id: int | None = None,
    email: str | None = None,
    limit: int = 200,
    session=None,
) -> list[dict]:
    async with get_session(session) as s:
        stmt = select(Message)
        if order_id:
            stmt = stmt.where(Message.order_id == order_id)
        elif customer_id:
            stmt = stmt.where(Message.customer_id == customer_id)
        elif email:
            norm = normalize_email(email) or email.strip().lower()
            cust = await s.scalar(
                select(Customer).where(Customer.email_normalized == norm)
            )
            if not cust:
                return []
            stmt = stmt.where(Message.customer_id == cust.id)
        stmt = stmt.order_by(Message.written_at.asc().nulls_last(), Message.id.asc()).limit(limit)
        rows = (await s.scalars(stmt)).all()
        return [
            {
                "id": m.id,
                "order_id": m.order_id,
                "customer_id": m.customer_id,
                "marketplace": m.marketplace,
                "external_msg_id": m.external_msg_id,
                "chat_id": m.chat_id,
                "direction": m.direction,
                "body": m.body,
                "is_file": m.is_file,
                "file_url": m.file_url,
                "written_at": m.written_at.isoformat() if m.written_at else None,
            }
            for m in rows
        ]


async def list_inbox_threads(
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
    marketplace: str | None = None,
    sort: str = "last_at",
    order: str = "desc",
    session=None,
) -> dict:
    """Paginated threads: one per customer, with search/filter/sort."""
    async with get_session(session) as s:
        last_msg_sq = (
            select(
                Message.customer_id.label("cid"),
                func.max(Message.written_at).label("last_at"),
            )
            .where(Message.customer_id.is_not(None))
            .group_by(Message.customer_id)
            .subquery()
        )
        order_count_sq = (
            select(
                Order.customer_id.label("cid"),
                func.count().label("order_count"),
            )
            .where(Order.customer_id.is_not(None))
            .group_by(Order.customer_id)
            .subquery()
        )

        stmt = (
            select(
                Customer,
                last_msg_sq.c.last_at,
                func.coalesce(order_count_sq.c.order_count, 0).label("order_count"),
            )
            .outerjoin(last_msg_sq, last_msg_sq.c.cid == Customer.id)
            .outerjoin(order_count_sq, order_count_sq.c.cid == Customer.id)
        )

        if marketplace:
            stmt = stmt.where(
                Customer.id.in_(
                    select(Order.customer_id).where(
                        Order.marketplace == marketplace,
                        Order.customer_id.is_not(None),
                    )
                )
            )

        if q:
            qq = q.strip()
            if qq:
                like = f"%{qq}%"
                order_match = select(Order.customer_id).where(
                    Order.customer_id.is_not(None),
                    or_(
                        Order.external_order_id == qq,
                        Order.invoice_id == qq,
                        Order.external_order_id.ilike(like),
                        Order.invoice_id.ilike(like),
                    ),
                )
                stmt = stmt.where(
                    or_(
                        Customer.email.ilike(like),
                        Customer.email_normalized.ilike(like),
                        Customer.id.in_(order_match),
                    )
                )

        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = await s.scalar(count_stmt) or 0

        asc = order == "asc"
        if sort == "email":
            col = Customer.email
            stmt = stmt.order_by(col.asc().nulls_last() if asc else col.desc().nulls_last())
        elif sort == "order_count":
            col = order_count_sq.c.order_count
            stmt = stmt.order_by(
                func.coalesce(col, 0).asc() if asc else func.coalesce(col, 0).desc()
            )
        else:
            # last_at: prefer last message time, fallback to customer.updated_at
            la = func.coalesce(last_msg_sq.c.last_at, Customer.updated_at)
            stmt = stmt.order_by(la.asc().nulls_last() if asc else la.desc().nulls_last())

        stmt = stmt.offset(offset).limit(limit)
        rows = (await s.execute(stmt)).all()

        threads = []
        for c, last_at, order_count in rows:
            last_msg = await s.scalar(
                select(Message)
                .where(Message.customer_id == c.id)
                .order_by(Message.written_at.desc().nulls_last(), Message.id.desc())
                .limit(1)
            )
            threads.append(
                {
                    "customer_id": c.id,
                    "email": c.email,
                    "order_count": int(order_count or 0),
                    "last_message": last_msg.body if last_msg else None,
                    "last_at": (
                        last_at.isoformat()
                        if last_at
                        else (
                            last_msg.written_at.isoformat()
                            if last_msg and last_msg.written_at
                            else None
                        )
                    ),
                }
            )
        return {
            "items": threads,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


async def count_orders(
    *,
    email: str | None = None,
    marketplace: str | None = None,
    remnawave_uuid: str | None = None,
    remnawave_username: str | None = None,
    external_order_id: str | None = None,
    q: str | None = None,
    session=None,
) -> int:
    async with get_session(session) as s:
        stmt = _orders_filter_stmt(
            email=email,
            marketplace=marketplace,
            remnawave_uuid=remnawave_uuid,
            remnawave_username=remnawave_username,
            external_order_id=external_order_id,
            q=q,
        )
        count_stmt = select(func.count()).select_from(
            stmt.order_by(None).with_only_columns(Order.id).subquery()
        )
        return await s.scalar(count_stmt) or 0


# ── Order params (dashboard-compatible) ─────────────────────────────────────


async def create_order_param(
    item_id: int,
    param_id: int,
    user_data_id: int,
    type_: str,
    data: str,
    marketplace: str | None = None,
):
    async with async_session() as session:
        if not marketplace:
            providers = set(
                await session.scalars(
                    select(ProductOptionLabel.marketplace)
                    .where(ProductOptionLabel.item_id == item_id)
                    .distinct()
                )
            )
            if len(providers) == 1:
                marketplace = providers.pop()
        session.add(
            OrderParam(
                item_id=item_id,
                param_id=param_id,
                user_data_id=user_data_id,
                type=type_,
                data=data,
                marketplace=marketplace,
            )
        )
        await session.commit()


async def get_order_params_dict(
    item_id: int, param_id: int, user_data_id: int, session=None
) -> dict[str, str]:
    async with get_session(session) as s:
        result = await s.scalars(
            select(OrderParam).where(
                OrderParam.item_id == item_id,
                OrderParam.param_id == param_id,
                OrderParam.user_data_id == user_data_id,
            )
        )
        return {row.type: row.data for row in result}


async def get_all_order_params(item_id: int | None = None) -> list[dict]:
    async with async_session() as session:
        stmt = select(OrderParam)
        if item_id is not None:
            stmt = stmt.where(OrderParam.item_id == item_id)
        result = await session.scalars(stmt)
        return [
            {
                "id": row.id,
                "item_id": row.item_id,
                "param_id": row.param_id,
                "user_data_id": row.user_data_id,
                "type": row.type,
                "data": row.data,
                "marketplace": row.marketplace,
                "binding_id": row.binding_id,
                "configuration_status": row.configuration_status,
            }
            for row in result
        ]


async def update_order_param(record_id: int, **kwargs) -> bool:
    async with async_session() as session:
        param = await session.get(OrderParam, record_id)
        if param is None:
            return False
        for key, value in kwargs.items():
            if hasattr(param, key):
                setattr(param, key, value)
        await session.commit()
        return True


async def item_id_exists(item_id: int, session=None) -> bool:
    async with get_session(session) as s:
        result = await s.scalar(
            select(OrderParam.id).where(OrderParam.item_id == item_id).limit(1)
        )
        return result is not None


async def delete_order_param(record_id: int) -> bool:
    async with async_session() as session:
        param = await session.get(OrderParam, record_id)
        if param is None:
            return False
        await session.delete(param)
        await session.commit()
        return True


async def delete_order_params_for_variant(
    *,
    item_id: int,
    param_id: int,
    user_data_id: int,
) -> int:
    """Delete all OrderParam rows for one marketplace option variant."""
    async with async_session() as session:
        rows = (
            await session.scalars(
                select(OrderParam).where(
                    OrderParam.item_id == item_id,
                    OrderParam.param_id == param_id,
                    OrderParam.user_data_id == user_data_id,
                )
            )
        ).all()
        count = len(rows)
        for row in rows:
            await session.delete(row)
        await session.commit()
        return count


async def delete_product_option_labels_for_variant(
    *,
    item_id: int,
    param_id: int,
    user_data_id: int,
    marketplace: str | None = None,
) -> int:
    """Remove cached label row(s) so the variant leaves the Parameters tree until re-sync."""
    async with async_session() as session:
        stmt = select(ProductOptionLabel).where(
            ProductOptionLabel.item_id == item_id,
            ProductOptionLabel.param_id == param_id,
            ProductOptionLabel.user_data_id == user_data_id,
        )
        if marketplace:
            stmt = stmt.where(ProductOptionLabel.marketplace == marketplace)
        rows = (await session.scalars(stmt)).all()
        count = len(rows)
        for row in rows:
            await session.delete(row)
        await session.commit()
        return count


# ── Param value mappings (human-readable catalog) ───────────────────────────


def _param_mapping_dict(row: ParamValueMapping) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "label": row.label,
        "value": row.value,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_param_value_mappings(type_: str | None = None) -> list[dict]:
    async with async_session() as session:
        stmt = select(ParamValueMapping).order_by(ParamValueMapping.type, ParamValueMapping.label)
        if type_:
            stmt = stmt.where(ParamValueMapping.type == type_)
        rows = (await session.scalars(stmt)).all()
        return [_param_mapping_dict(r) for r in rows]


async def create_param_value_mapping(type_: str, label: str, value: str) -> dict:
    async with async_session() as session:
        row = ParamValueMapping(type=type_, label=label, value=value)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _param_mapping_dict(row)


async def update_param_value_mapping(record_id: int, **kwargs) -> dict | None:
    async with async_session() as session:
        row = await session.get(ParamValueMapping, record_id)
        if row is None:
            return None
        for key, value in kwargs.items():
            if key == "type":
                row.type = value
            elif hasattr(row, key):
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return _param_mapping_dict(row)


async def delete_param_value_mapping(record_id: int) -> bool:
    async with async_session() as session:
        row = await session.get(ParamValueMapping, record_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


# ── Product option labels (catalog names for Parameters UI) ──────────────────


def _option_label_dict(row: ProductOptionLabel) -> dict:
    return {
        "id": row.id,
        "marketplace": row.marketplace,
        "item_id": row.item_id,
        "param_id": row.param_id,
        "user_data_id": row.user_data_id,
        "item_name": row.item_name,
        "param_name": row.param_name,
        "variant_name": row.variant_name,
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
    }


async def upsert_product_option_label(
    *,
    marketplace: str,
    item_id: int,
    param_id: int,
    user_data_id: int,
    item_name: str | None = None,
    param_name: str | None = None,
    variant_name: str | None = None,
    session=None,
) -> ProductOptionLabel:
    async with get_session(session) as s:
        row = await s.scalar(
            select(ProductOptionLabel).where(
                ProductOptionLabel.marketplace == marketplace,
                ProductOptionLabel.item_id == item_id,
                ProductOptionLabel.param_id == param_id,
                ProductOptionLabel.user_data_id == user_data_id,
            )
        )
        if row is None:
            row = ProductOptionLabel(
                marketplace=marketplace,
                item_id=item_id,
                param_id=param_id,
                user_data_id=user_data_id,
            )
            s.add(row)
        row.item_name = item_name
        row.param_name = param_name
        row.variant_name = variant_name
        row.synced_at = datetime.now(timezone.utc)
        await s.flush()
        if session is None:
            await s.commit()
            await s.refresh(row)
        return row


async def list_product_option_labels(
    *,
    marketplace: str | None = None,
    item_id: int | None = None,
    session=None,
) -> list[dict]:
    async with get_session(session) as s:
        stmt = select(ProductOptionLabel).order_by(
            ProductOptionLabel.marketplace,
            ProductOptionLabel.item_id,
            ProductOptionLabel.param_id,
            ProductOptionLabel.user_data_id,
        )
        if marketplace:
            stmt = stmt.where(ProductOptionLabel.marketplace == marketplace)
        if item_id is not None:
            stmt = stmt.where(ProductOptionLabel.item_id == item_id)
        rows = (await s.scalars(stmt)).all()
        return [_option_label_dict(r) for r in rows]


# ── Legacy helpers (kept for migrate script / transitional paths) ───────────


async def set_user(tg_id, session=None):
    async with get_session(session) as s:
        user = await s.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            s.add(User(tg_id=tg_id))
            await s.commit()


async def create_transaction(user_tg_id: int, user_transaction: str, username: str, days: int, uuid: str = "None", session=None):
    async with get_session(session) as s:
        user = await s.scalar(select(User).where(User.tg_id == user_tg_id))
        if user:
            s.add(
                Transaction(
                    transaction_id=user_transaction,
                    vless_uuid=uuid,
                    username=username,
                    order_status="created",
                    delivery_status=0,
                    days_ordered=days,
                    user_id=user.id,
                )
            )
            await s.commit()


async def update_user_api_info(
    tg_id: int = 0,
    username: str = None,
    vless_uuid: str = None,
    api_provider: str = None,
    session=None,
):
    async with get_session(session) as s:
        user = await s.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            return False
        if username is not None:
            user.username = username
        if vless_uuid is not None:
            user.vless_uuid = str(vless_uuid)
        if api_provider is not None:
            user.api_provider = api_provider
        await s.commit()
        return True


async def update_delivery_status(tg_id: int, new_delivery_status: int, session=None):
    async with get_session(session) as s:
        user = await s.scalar(select(User).where(User.tg_id == tg_id))
        if user:
            await s.execute(
                update(Transaction)
                .where(Transaction.user_id == user.id)
                .values(delivery_status=new_delivery_status)
            )
            await s.commit()
