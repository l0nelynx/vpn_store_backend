"""Add param_value_mappings catalog table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_param_value_mappings"
down_revision = "0002_order_params_marketplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_value_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("type", "value", name="uq_param_value_mappings_type_value"),
    )
    op.create_index(
        "ix_param_value_mappings_type",
        "param_value_mappings",
        ["type"],
    )


def downgrade() -> None:
    op.drop_index("ix_param_value_mappings_type", table_name="param_value_mappings")
    op.drop_table("param_value_mappings")
