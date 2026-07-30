"""PostgreSQL Store v2: local catalog, delivery pipelines and durable runtime.

Revision ID: 0005_delivery_pipeline
Revises: 0004_product_option_labels
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_delivery_pipeline"
down_revision = "0004_product_option_labels"
branch_labels = None
depends_on = None


NEW_TABLES = [
    "products",
    "delivery_pipelines",
    "pipeline_versions",
    "pipeline_steps",
    "product_bindings",
    "fx_rates",
    "pipeline_runs",
    "pipeline_step_runs",
    "order_events",
    "outbox_jobs",
    "dead_letter_jobs",
    "message_templates",
    "integration_profiles",
    "integration_secrets",
    "sync_checkpoints",
    "audit_log",
    "admin_sessions",
]


def _jsonb(default: str = "{}") -> sa.Column:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Store v2 migrations require PostgreSQL")

    # The dev branch used products as a provider cache. Preserve every row.
    op.rename_table("products", "marketplace_products")
    op.alter_column("marketplace_products", "marketplace", new_column_name="provider")
    op.alter_column("marketplace_products", "raw_json", new_column_name="raw")
    op.execute(
        "ALTER TABLE marketplace_products RENAME CONSTRAINT "
        "uq_products_marketplace_item TO uq_marketplace_products_provider_item"
    )
    op.execute(
        "ALTER TABLE marketplace_products ALTER COLUMN external_item_id TYPE bigint "
        "USING external_item_id::bigint"
    )
    op.execute(
        "ALTER TABLE marketplace_products ALTER COLUMN raw TYPE jsonb "
        "USING CASE WHEN raw IS NULL OR raw = '' THEN '{}'::jsonb ELSE raw::jsonb END"
    )
    op.execute(
        "ALTER TABLE marketplace_products ALTER COLUMN price TYPE numeric(18,4) "
        "USING price::numeric"
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("published_pipeline_version_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "delivery_pipelines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("providers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("current_draft_version_id", sa.Integer()),
        sa.Column("published_version_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "pipeline_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pipeline_id", sa.Integer(), sa.ForeignKey("delivery_pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("definition_hash", sa.String(64)),
        sa.Column("created_by", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("pipeline_id", "version", name="uq_pipeline_versions_number"),
    )
    op.create_foreign_key(
        "fk_products_published_pipeline_version",
        "products", "pipeline_versions", ["published_pipeline_version_id"], ["id"],
    )
    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("pipeline_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("phase", sa.String(24), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("condition", postgresql.JSONB()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retry_policy", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key_template", sa.String(500)),
        sa.Column("run_before_response", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("version_id", "key", name="uq_pipeline_steps_version_key"),
        sa.UniqueConstraint("version_id", "position", name="uq_pipeline_steps_version_position"),
    )
    op.create_table(
        "product_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_item_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_policy", sa.String(32), nullable=False, server_default="automatic"),
        sa.Column("option_mappings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("published_pipeline_version_id", sa.Integer(), sa.ForeignKey("pipeline_versions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "external_item_id", name="uq_product_bindings_provider_item"),
    )
    op.create_index("ix_product_bindings_product", "product_bindings", ["product_id"])
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rate_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_currency", sa.String(16), nullable=False),
        sa.Column("quote_currency", sa.String(16), nullable=False, server_default="RUB"),
        sa.Column("rate", sa.Numeric(24, 10), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.UniqueConstraint("rate_date", "base_currency", "quote_currency", name="uq_fx_rates_key"),
    )

    # Extend orders without invalidating the old Admin/CRM contract.
    order_columns = [
        sa.Column("provider_order_id", sa.String(100)),
        sa.Column("content_id", sa.String(100)),
        sa.Column("cart_uid", sa.String(100)),
        sa.Column("provider_external_order_id", sa.String(100)),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("product_bindings.id")),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_state", sa.String(50)),
        sa.Column("normalized_status", sa.String(50), nullable=False, server_default="created"),
        sa.Column("final_delivery_response", postgresql.JSONB()),
        sa.Column("buyer_email", sa.String(320)),
        sa.Column("gross_amount", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(18, 4)),
        sa.Column("profit_amount", sa.Numeric(18, 4)),
        sa.Column("amount_usd", sa.Numeric(18, 4)),
        sa.Column("gross_currency", sa.String(16)),
        sa.Column("net_currency", sa.String(16)),
        sa.Column("gross_rub", sa.Numeric(18, 4)),
        sa.Column("net_rub", sa.Numeric(18, 4)),
        sa.Column("fx_rate_id", sa.Integer(), sa.ForeignKey("fx_rates.id")),
        sa.Column("pipeline_version_id", sa.Integer(), sa.ForeignKey("pipeline_versions.id")),
    ]
    for column in order_columns:
        op.add_column("orders", column)
    op.execute("ALTER TABLE orders ALTER COLUMN amount TYPE numeric(18,4) USING amount::numeric")
    op.execute("ALTER TABLE orders ALTER COLUMN item_id TYPE bigint USING item_id::bigint")
    op.execute("ALTER TABLE orders ALTER COLUMN subscription_url TYPE varchar(1000)")
    op.execute(
        "UPDATE orders SET provider_order_id = CASE "
        "WHEN marketplace='ggsel' AND NULLIF(invoice_id, '') IS NOT NULL THEN invoice_id "
        "ELSE external_order_id END, "
        "content_id = CASE WHEN marketplace='ggsel' THEN external_order_id ELSE NULL END, "
        "normalized_status = status"
    )
    op.execute(
        "UPDATE orders SET buyer_email = customers.email "
        "FROM customers WHERE customers.id = orders.customer_id"
    )
    op.execute(
        "UPDATE orders SET options = CASE WHEN options_json IS NULL OR options_json='' "
        "THEN '[]'::jsonb ELSE options_json::jsonb END"
    )
    op.execute(
        "WITH duplicates AS (SELECT id, row_number() OVER "
        "(PARTITION BY marketplace, provider_order_id ORDER BY id) AS rn FROM orders) "
        "UPDATE orders SET provider_order_id=NULL, normalized_status='needs_configuration' "
        "FROM duplicates WHERE orders.id=duplicates.id AND duplicates.rn>1"
    )
    op.create_unique_constraint("uq_orders_provider_order", "orders", ["marketplace", "provider_order_id"])
    op.create_index("ix_orders_binding_id", "orders", ["binding_id"])

    op.add_column("order_params", sa.Column("binding_id", sa.Integer(), sa.ForeignKey("product_bindings.id")))
    op.add_column(
        "order_params",
        sa.Column("configuration_status", sa.String(32), nullable=False, server_default="configured"),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_version_id", sa.Integer(), sa.ForeignKey("pipeline_versions.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("correlation_id", sa.String(100), nullable=False, unique=True),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("execution_locked_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", "pipeline_version_id", name="uq_pipeline_runs_order_version"),
    )
    op.create_index("ix_pipeline_runs_status_created", "pipeline_runs", ["status", "created_at"])
    op.create_table(
        "pipeline_step_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("pipeline_steps.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(500), unique=True),
        sa.Column("inputs", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("outputs", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "step_id", "attempt", name="uq_step_runs_attempt"),
    )
    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("dedupe_key", sa.String(500), nullable=False, unique=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(100)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_claim", "outbox_jobs", ["status", "available_at"])
    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("outbox_job_id", sa.Integer(), sa.ForeignKey("outbox_jobs.id")),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "message_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("format", sa.String(20), nullable=False, server_default="plain"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "integration_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="http"),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("auth_type", sa.String(32), nullable=False, server_default="none"),
        sa.Column("auth_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("allowed_hosts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "integration_secrets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("integration_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "name", name="uq_integration_secrets_profile_name"),
    )
    op.create_table(
        "sync_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("stream", sa.String(100), nullable=False),
        sa.Column("cursor", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("gap_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detail", sa.Text()),
        sa.UniqueConstraint("provider", "stream", name="uq_sync_checkpoints_provider_stream"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("after", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # One local product/binding per existing marketplace item. Admin can merge later.
    op.execute(
        "INSERT INTO products (key, name, status) "
        "SELECT 'legacy-' || provider || '-' || external_item_id, "
        "COALESCE(name, provider || ' #' || external_item_id), 'active' "
        "FROM marketplace_products"
    )
    op.execute(
        "INSERT INTO product_bindings (product_id, provider, external_item_id, trigger_policy, status) "
        "SELECT p.id, mp.provider, mp.external_item_id, 'automatic', 'active' "
        "FROM marketplace_products mp JOIN products p "
        "ON p.key = 'legacy-' || mp.provider || '-' || mp.external_item_id"
    )
    op.execute(
        "UPDATE order_params opm SET binding_id=b.id, configuration_status='configured' "
        "FROM product_bindings b WHERE opm.marketplace=b.provider AND opm.item_id=b.external_item_id"
    )
    op.execute(
        "UPDATE order_params SET configuration_status='needs_configuration' WHERE binding_id IS NULL"
    )
    op.execute(
        "UPDATE orders o SET binding_id=b.id FROM product_bindings b "
        "WHERE o.marketplace=b.provider AND o.item_id=b.external_item_id"
    )


def downgrade() -> None:
    raise RuntimeError("0005 is a data-preserving, intentionally irreversible migration")
