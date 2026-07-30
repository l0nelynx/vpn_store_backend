"""Activate bindings backed by recovered legacy parameters.

Revision ID: 0007_activate_imported_bindings
Revises: 0006_legacy_binding_backfill
"""

from __future__ import annotations

from alembic import op


revision = "0007_activate_imported_bindings"
down_revision = "0006_legacy_binding_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A worker from the previous rollout could publish a legacy pipeline onto a
    # needs_configuration binding before the SQLite importer linked its params.
    # The presence of an explicitly configured, linked parameter is sufficient
    # to restore the old automatic-delivery behavior regardless of whether the
    # pipeline version was assigned before or after the import.
    op.execute(
        """
        UPDATE product_bindings AS binding
        SET status = 'active', trigger_policy = 'automatic'
        WHERE binding.status = 'needs_configuration'
          AND EXISTS (
              SELECT 1
              FROM order_params AS parameter
              WHERE parameter.binding_id = binding.id
                AND parameter.configuration_status = 'configured'
          )
        """
    )


def downgrade() -> None:
    # Do not disable bindings that may have fulfilled orders after activation.
    pass
