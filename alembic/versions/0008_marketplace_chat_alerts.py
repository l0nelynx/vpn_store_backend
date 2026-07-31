"""Add marketplace_chat_alerts for unread inbox notifications.

Revision ID: 0008_marketplace_chat_alerts
Revises: 0007_activate_imported_bindings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_marketplace_chat_alerts"
down_revision = "0007_activate_imported_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_chat_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("cnt_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("last_notified_cnt_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("marketplace", "chat_id", name="uq_marketplace_chat_alerts"),
    )
    op.create_index(
        "ix_marketplace_chat_alerts_active",
        "marketplace_chat_alerts",
        ["cnt_new", "cleared_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_marketplace_chat_alerts_active", table_name="marketplace_chat_alerts")
    op.drop_table("marketplace_chat_alerts")
