"""Add order_params.marketplace (nullable) for existing DBs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_order_params_marketplace"
down_revision = "0001_store_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("order_params") as batch:
        batch.add_column(sa.Column("marketplace", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("order_params") as batch:
        batch.drop_column("marketplace")
