"""Store numeric Remnawave v3 user identifiers.

Revision ID: 0009_remnawave_v3_user_ids
Revises: 0008_marketplace_chat_alerts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_remnawave_v3_user_ids"
down_revision = "0008_marketplace_chat_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("remnawave_user_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_orders_remnawave_user_id", "orders", ["remnawave_user_id"])
    op.add_column(
        "subscription_events",
        sa.Column("remnawave_user_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscription_events", "remnawave_user_id")
    op.drop_index("ix_orders_remnawave_user_id", table_name="orders")
    op.drop_column("orders", "remnawave_user_id")
