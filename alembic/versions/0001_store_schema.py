"""Initial Store schema: customers, orders, products, messages, order_params."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_store_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("email_normalized", sa.String(320), nullable=True),
        sa.Column("ggsel_buyer_id", sa.String(100), nullable=True),
        sa.Column("digiseller_buyer_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_customers_email_normalized", "customers", ["email_normalized"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("external_order_id", sa.String(100), nullable=False),
        sa.Column("invoice_id", sa.String(100), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(16), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("delivery_status", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(100), nullable=True),
        sa.Column("days_ordered", sa.Integer(), nullable=True),
        sa.Column("remnawave_username", sa.String(100), nullable=True),
        sa.Column("remnawave_uuid", sa.String(100), nullable=True),
        sa.Column("subscription_url", sa.String(500), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("marketplace", "external_order_id", name="uq_orders_marketplace_external"),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_chat_id", "orders", ["chat_id"])
    op.create_index("ix_orders_remnawave_username", "orders", ["remnawave_username"])
    op.create_index("ix_orders_remnawave_uuid", "orders", ["remnawave_uuid"])

    op.create_table(
        "subscription_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("remnawave_uuid", sa.String(100), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "order_params",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("param_id", sa.Integer(), nullable=False),
        sa.Column("user_data_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("data", sa.String(500), nullable=False),
        sa.Column("marketplace", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_order_params_lookup",
        "order_params",
        ["item_id", "param_id", "user_data_id"],
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("external_item_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(500), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(16), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("marketplace", "external_item_id", name="uq_products_marketplace_item"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("external_msg_id", sa.String(100), nullable=True),
        sa.Column("chat_id", sa.String(100), nullable=True),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_file", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("file_url", sa.String(500), nullable=True),
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "marketplace", "external_msg_id", name="uq_messages_marketplace_external"
        ),
    )
    op.create_index("ix_messages_customer_id", "messages", ["customer_id"])
    op.create_index("ix_messages_order_id", "messages", ["order_id"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("products")
    op.drop_table("order_params")
    op.drop_table("subscription_events")
    op.drop_table("orders")
    op.drop_table("customers")
