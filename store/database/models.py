"""Store ORM models.

Legacy `users` / `transactions` tables are kept for migration compatibility but
new fulfillment writes to Customer / Order / SubscriptionEvent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from store.settings import secrets


def _database_url() -> str:
    url = secrets.get("database_url") or "sqlite+aiosqlite:///db/backend_db.sqlite3"
    return url


_engine_kwargs: dict = {"pool_pre_ping": True}
if _database_url().startswith("sqlite"):
    _engine_kwargs.update(pool_size=1, max_overflow=0)

engine = create_async_engine(url=_database_url(), **_engine_kwargs)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    if not str(engine.url).startswith("sqlite"):
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA wal_autocheckpoint=100")
    cursor.close()


async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)
    ggsel_buyer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    digiseller_buyer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")

    __table_args__ = (
        Index("ix_customers_email_normalized", "email_normalized"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))  # ggsel | digiseller
    external_order_id: Mapped[str] = mapped_column(String(100))
    invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="created")
    delivery_status: Mapped[int] = mapped_column(Integer, default=0)  # 0 pending, 1 sent
    chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    days_ordered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remnawave_username: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    remnawave_uuid: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    subscription_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["Customer | None"] = relationship(back_populates="orders")
    events: Mapped[list["SubscriptionEvent"]] = relationship(back_populates="order")
    messages: Mapped[list["Message"]] = relationship(back_populates="order")

    __table_args__ = (
        UniqueConstraint("marketplace", "external_order_id", name="uq_orders_marketplace_external"),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_chat_id", "chat_id"),
    )


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    event_type: Mapped[str] = mapped_column(String(50))  # create | extend | resend
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remnawave_uuid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="events")


class OrderParam(Base):
    """Product option → Remnawave mapping (dashboard-compatible)."""

    __tablename__ = "order_params"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer)
    param_id: Mapped[int] = mapped_column(Integer)
    user_data_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    data: Mapped[str] = mapped_column(String(500))
    marketplace: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_order_params_lookup", "item_id", "param_id", "user_data_id"),
    )


class ParamValueMapping(Base):
    """Human-readable catalog of parameter values (label → technical value)."""

    __tablename__ = "param_value_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_param_value_mappings_type_value"),
        Index("ix_param_value_mappings_type", "type"),
    )


class ProductOptionLabel(Base):
    """Cached marketplace option/variant names for Parameters UI."""

    __tablename__ = "product_option_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[int] = mapped_column(Integer)
    param_id: Mapped[int] = mapped_column(Integer)
    user_data_id: Mapped[int] = mapped_column(Integer)
    item_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    param_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    variant_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "marketplace",
            "item_id",
            "param_id",
            "user_data_id",
            name="uq_product_option_labels_key",
        ),
        Index("ix_product_option_labels_item", "marketplace", "item_id"),
    )


class Product(Base):
    """Cached marketplace catalog row."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    external_item_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("marketplace", "external_item_id", name="uq_products_marketplace_item"),
    )


class Message(Base):
    """Mirrored marketplace chat message."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    external_msg_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direction: Mapped[str] = mapped_column(String(16))  # inbound | outbound
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_file: Mapped[bool] = mapped_column(Boolean, default=False)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped["Order | None"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_customer_id", "customer_id"),
        Index("ix_messages_order_id", "order_id"),
        UniqueConstraint(
            "marketplace", "external_msg_id", name="uq_messages_marketplace_external"
        ),
    )


# --- Legacy tables (read/migrate only; new code should use Customer/Order) ---

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    vless_uuid: Mapped[str] = mapped_column(String(100), nullable=True)
    api_provider: Mapped[str] = mapped_column(String(50), default="remnawave")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")

    __table_args__ = (Index("ix_user_username", "username"),)


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    vless_uuid: Mapped[str] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(50))
    order_status: Mapped[str] = mapped_column(String(50))
    delivery_status: Mapped[int] = mapped_column(Integer)
    days_ordered: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user: Mapped["User"] = relationship(back_populates="transactions")

    __table_args__ = (Index("ix_transaction_user_id", "user_id"),)


def _ensure_sqlite_columns(connection) -> None:
    """create_all does not ALTER existing tables — patch known new columns."""
    if not str(engine.url).startswith("sqlite"):
        return
    from sqlalchemy import text

    rows = connection.execute(text("PRAGMA table_info(order_params)")).fetchall()
    if not rows:
        return
    cols = {r[1] for r in rows}
    if "marketplace" not in cols:
        connection.execute(
            text("ALTER TABLE order_params ADD COLUMN marketplace VARCHAR(32)")
        )


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_sqlite_columns)
