"""Add product_option_labels cache table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_product_option_labels"
down_revision = "0003_param_value_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_option_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("param_id", sa.Integer(), nullable=False),
        sa.Column("user_data_id", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.String(length=500), nullable=True),
        sa.Column("param_name", sa.String(length=500), nullable=True),
        sa.Column("variant_name", sa.String(length=500), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "marketplace",
            "item_id",
            "param_id",
            "user_data_id",
            name="uq_product_option_labels_key",
        ),
    )
    op.create_index(
        "ix_product_option_labels_item",
        "product_option_labels",
        ["marketplace", "item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_option_labels_item", table_name="product_option_labels")
    op.drop_table("product_option_labels")
