"""PostgreSQL persistence model for Store v2.

The old CRM tables remain mapped so existing installations can be migrated in
place.  New fulfillment state is stored in immutable pipeline versions/runs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from store.settings import secrets


DATABASE_URL = secrets.get("database_url") or (
    "postgresql+asyncpg://store:store@127.0.0.1:5433/store"
)
if not str(DATABASE_URL).startswith("postgresql+"):
    raise RuntimeError("Store v2 supports PostgreSQL only")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320))
    email_normalized: Mapped[str | None] = mapped_column(String(320))
    ggsel_buyer_id: Mapped[str | None] = mapped_column(String(100))
    digiseller_buyer_id: Mapped[str | None] = mapped_column(String(100))

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    __table_args__ = (Index("ix_customers_email_normalized", "email_normalized"),)


class Product(TimestampMixin, Base):
    """Store-owned product which can be bound to several marketplace items."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", server_default="draft")
    published_pipeline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_versions.id", use_alter=True), nullable=True
    )

    bindings: Mapped[list["ProductBinding"]] = relationship(back_populates="product")


class MarketplaceProduct(Base):
    """Read-through cache populated from seller goods APIs."""

    __tablename__ = "marketplace_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_item_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(16))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "external_item_id", name="uq_marketplace_products_provider_item"),
    )


class ProductBinding(TimestampMixin, Base):
    __tablename__ = "product_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    external_item_id: Mapped[int] = mapped_column(BigInteger)
    trigger_policy: Mapped[str] = mapped_column(String(32), default="automatic")
    option_mappings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(32), default="active")
    published_pipeline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_versions.id", use_alter=True), nullable=True
    )

    product: Mapped[Product] = relationship(back_populates="bindings")
    __table_args__ = (
        UniqueConstraint("provider", "external_item_id", name="uq_product_bindings_provider_item"),
        Index("ix_product_bindings_product", "product_id"),
    )


class DeliveryPipeline(TimestampMixin, Base):
    __tablename__ = "delivery_pipelines"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    providers: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    current_draft_version_id: Mapped[int | None] = mapped_column(nullable=True)
    published_version_id: Mapped[int | None] = mapped_column(nullable=True)

    versions: Mapped[list["PipelineVersion"]] = relationship(
        back_populates="pipeline", foreign_keys="PipelineVersion.pipeline_id"
    )


class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("delivery_pipelines.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="draft", server_default="draft")
    definition_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pipeline: Mapped[DeliveryPipeline] = relationship(
        back_populates="versions", foreign_keys=[pipeline_id]
    )
    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="version", order_by="PipelineStep.position", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("pipeline_id", "version", name="uq_pipeline_versions_number"),
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(100))
    phase: Mapped[str] = mapped_column(String(24))
    type: Mapped[str] = mapped_column(String(100))
    condition: Mapped[dict | None] = mapped_column(JSONB)
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    retry_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    idempotency_key_template: Mapped[str | None] = mapped_column(String(500))
    run_before_response: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    version: Mapped[PipelineVersion] = relationship(back_populates="steps")
    __table_args__ = (
        UniqueConstraint("version_id", "key", name="uq_pipeline_steps_version_key"),
        UniqueConstraint("version_id", "position", name="uq_pipeline_steps_version_position"),
    )


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    external_order_id: Mapped[str] = mapped_column(String(100))
    provider_order_id: Mapped[str | None] = mapped_column(String(100))
    invoice_id: Mapped[str | None] = mapped_column(String(100))
    content_id: Mapped[str | None] = mapped_column(String(100))
    cart_uid: Mapped[str | None] = mapped_column(String(100))
    provider_external_order_id: Mapped[str | None] = mapped_column(String(100))
    item_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[int | None] = mapped_column(ForeignKey("product_bindings.id"))
    options: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    options_json: Mapped[str | None] = mapped_column(Text)  # compatibility
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    raw_state: Mapped[str | None] = mapped_column(String(50))
    normalized_status: Mapped[str] = mapped_column(String(50), default="created")
    status: Mapped[str] = mapped_column(String(50), default="created")  # compatibility
    delivery_status: Mapped[int] = mapped_column(Integer, default=0)
    final_delivery_response: Mapped[dict | None] = mapped_column(JSONB)
    buyer_email: Mapped[str | None] = mapped_column(String(320))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    profit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(16))
    gross_currency: Mapped[str | None] = mapped_column(String(16))
    net_currency: Mapped[str | None] = mapped_column(String(16))
    gross_rub: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    net_rub: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    fx_rate_id: Mapped[int | None] = mapped_column(ForeignKey("fx_rates.id"))
    chat_id: Mapped[str | None] = mapped_column(String(100))
    days_ordered: Mapped[int | None] = mapped_column(Integer)
    remnawave_username: Mapped[str | None] = mapped_column(String(100), index=True)
    remnawave_uuid: Mapped[str | None] = mapped_column(String(100), index=True)
    subscription_url: Mapped[str | None] = mapped_column(String(1000))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    pipeline_version_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_versions.id"))

    customer: Mapped[Customer | None] = relationship(back_populates="orders")
    events: Mapped[list["SubscriptionEvent"]] = relationship(back_populates="order")
    messages: Mapped[list["Message"]] = relationship(back_populates="order")
    __table_args__ = (
        UniqueConstraint("marketplace", "external_order_id", name="uq_orders_marketplace_external"),
        UniqueConstraint("marketplace", "provider_order_id", name="uq_orders_provider_order"),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_chat_id", "chat_id"),
        Index("ix_orders_binding_id", "binding_id"),
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    pipeline_version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id"))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    correlation_id: Mapped[str] = mapped_column(String(100), unique=True)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("order_id", "pipeline_version_id", name="uq_pipeline_runs_order_version"),
        Index("ix_pipeline_runs_status_created", "status", "created_at"),
    )


class PipelineStepRun(Base):
    __tablename__ = "pipeline_step_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    step_id: Mapped[int] = mapped_column(ForeignKey("pipeline_steps.id"))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    idempotency_key: Mapped[str | None] = mapped_column(String(500))
    inputs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    outputs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("run_id", "step_id", "attempt", name="uq_step_runs_attempt"),
        UniqueConstraint("idempotency_key", name="uq_step_runs_idempotency_key"),
    )


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    days: Mapped[int | None] = mapped_column(Integer)
    remnawave_uuid: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    order: Mapped[Order] = relationship(back_populates="events")


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(100))
    dedupe_key: Mapped[str] = mapped_column(String(500), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_outbox_claim", "status", "available_at"),)


class DeadLetterJob(Base):
    __tablename__ = "dead_letter_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    outbox_job_id: Mapped[int | None] = mapped_column(ForeignKey("outbox_jobs.id"))
    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageTemplate(TimestampMixin, Base):
    __tablename__ = "message_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(20), default="plain")
    body: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class IntegrationProfile(TimestampMixin, Base):
    __tablename__ = "integration_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(50), default="http")
    base_url: Mapped[str] = mapped_column(String(1000))
    auth_type: Mapped[str] = mapped_column(String(32), default="none")
    auth_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    allowed_hosts: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class IntegrationSecret(TimestampMixin, Base):
    __tablename__ = "integration_secrets"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("integration_profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    __table_args__ = (
        UniqueConstraint("profile_id", "name", name="uq_integration_secrets_profile_name"),
    )


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    stream: Mapped[str] = mapped_column(String(100))
    cursor: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gap_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("provider", "stream", name="uq_sync_checkpoints_provider_stream"),
    )


class FxRate(Base):
    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    base_currency: Mapped[str] = mapped_column(String(16))
    quote_currency: Mapped[str] = mapped_column(String(16), default="RUB")
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    source: Mapped[str] = mapped_column(String(100))
    __table_args__ = (
        UniqueConstraint("rate_date", "base_currency", "quote_currency", name="uq_fx_rates_key"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    username: Mapped[str] = mapped_column(String(100))
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    marketplace: Mapped[str] = mapped_column(String(32))
    external_msg_id: Mapped[str | None] = mapped_column(String(100))
    chat_id: Mapped[str | None] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(16))
    body: Mapped[str | None] = mapped_column(Text)
    is_file: Mapped[bool] = mapped_column(Boolean, default=False)
    file_url: Mapped[str | None] = mapped_column(String(500))
    written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    order: Mapped[Order | None] = relationship(back_populates="messages")
    __table_args__ = (
        Index("ix_messages_customer_id", "customer_id"),
        Index("ix_messages_order_id", "order_id"),
        UniqueConstraint("marketplace", "external_msg_id", name="uq_messages_marketplace_external"),
    )


class MarketplaceChatAlert(Base):
    """Snapshot of marketplace unread debates for admin bell + TG alerts."""

    __tablename__ = "marketplace_chat_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    chat_id: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320))
    cnt_new: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    last_notified_cnt_new: Mapped[int] = mapped_column(Integer, default=0)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("marketplace", "chat_id", name="uq_marketplace_chat_alerts"),
        Index("ix_marketplace_chat_alerts_active", "cnt_new", "cleared_at"),
    )


class OrderParam(Base):
    __tablename__ = "order_params"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger)
    param_id: Mapped[int] = mapped_column(BigInteger)
    user_data_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(50))
    data: Mapped[str] = mapped_column(String(500))
    marketplace: Mapped[str | None] = mapped_column(String(32))
    binding_id: Mapped[int | None] = mapped_column(ForeignKey("product_bindings.id"))
    configuration_status: Mapped[str] = mapped_column(String(32), default="configured")
    __table_args__ = (Index("ix_order_params_lookup", "item_id", "param_id", "user_data_id"),)


class ParamValueMapping(Base):
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
    __tablename__ = "product_option_labels"
    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[int] = mapped_column(BigInteger)
    param_id: Mapped[int] = mapped_column(BigInteger)
    user_data_id: Mapped[int] = mapped_column(BigInteger)
    item_name: Mapped[str | None] = mapped_column(String(500))
    param_name: Mapped[str | None] = mapped_column(String(500))
    variant_name: Mapped[str | None] = mapped_column(String(500))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("marketplace", "item_id", "param_id", "user_data_id", name="uq_product_option_labels_key"),
        Index("ix_product_option_labels_item", "marketplace", "item_id"),
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(100))
    vless_uuid: Mapped[str | None] = mapped_column(String(100))
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
    user: Mapped[User] = relationship(back_populates="transactions")
    __table_args__ = (Index("ix_transaction_user_id", "user_id"),)


async def async_main() -> None:
    """Connectivity check. Schema changes are Alembic-only."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
