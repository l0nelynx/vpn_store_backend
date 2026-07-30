"""Add order_params.marketplace (nullable) for existing DBs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "0002_order_params_marketplace"
down_revision = "0001_store_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='order_params' AND column_name='marketplace') THEN "
            "ALTER TABLE order_params ADD COLUMN marketplace VARCHAR(32); END IF; END $$"
        )
        return
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("order_params")}
    if "marketplace" not in columns:
        op.add_column(
            "order_params",
            sa.Column("marketplace", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    if context.is_offline_mode():
        op.execute("ALTER TABLE order_params DROP COLUMN IF EXISTS marketplace")
        return
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("order_params")}
    if "marketplace" in columns:
        op.drop_column("order_params", "marketplace")
