"""Backfill legacy bindings from explicitly scoped order parameters.

Revision ID: 0006_legacy_binding_backfill
Revises: 0005_delivery_pipeline
"""

from __future__ import annotations

from alembic import op


revision = "0006_legacy_binding_backfill"
down_revision = "0005_delivery_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0005 originally seeded bindings only from marketplace_products. Some
    # installations had valid order_params for products that had never been
    # cached, so those previously working products became undeliverable.
    # Recover a missing marketplace only when the existing catalog/option cache
    # identifies exactly one provider for that item id. Cross-provider matches
    # deliberately remain needs_configuration.
    op.execute(
        """
        WITH item_providers AS (
            SELECT item_id, min(provider) AS provider
            FROM (
                SELECT external_item_id AS item_id, lower(trim(provider)) AS provider
                FROM marketplace_products
                UNION
                SELECT item_id, lower(trim(marketplace)) AS provider
                FROM product_option_labels
            ) AS candidates
            WHERE provider IN ('ggsel', 'digiseller')
            GROUP BY item_id
            HAVING count(DISTINCT provider) = 1
        )
        UPDATE order_params AS parameter
        SET marketplace = item_providers.provider
        FROM item_providers
        WHERE parameter.item_id = item_providers.item_id
          AND (parameter.marketplace IS NULL OR trim(parameter.marketplace) = '')
        """
    )
    op.execute(
        """
        INSERT INTO products (key, name, status)
        SELECT
            'legacy-' || source.provider || '-' || source.item_id,
            COALESCE(mp.name, source.provider || ' #' || source.item_id),
            'active'
        FROM (
            SELECT DISTINCT lower(trim(marketplace)) AS provider, item_id
            FROM order_params
            WHERE lower(trim(marketplace)) IN ('ggsel', 'digiseller')
        ) AS source
        LEFT JOIN marketplace_products AS mp
          ON mp.provider = source.provider
         AND mp.external_item_id = source.item_id
        WHERE NOT EXISTS (
            SELECT 1 FROM product_bindings AS binding
            WHERE binding.provider = source.provider
              AND binding.external_item_id = source.item_id
        )
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO product_bindings (
            product_id, provider, external_item_id, trigger_policy, status,
            option_mappings
        )
        SELECT
            product.id, source.provider, source.item_id, 'automatic', 'active',
            '{}'::jsonb
        FROM (
            SELECT DISTINCT lower(trim(marketplace)) AS provider, item_id
            FROM order_params
            WHERE lower(trim(marketplace)) IN ('ggsel', 'digiseller')
        ) AS source
        JOIN products AS product
          ON product.key = 'legacy-' || source.provider || '-' || source.item_id
        ON CONFLICT (provider, external_item_id) DO NOTHING
        """
    )
    # Catalog sync may already have created a deliberately disabled binding.
    # It is safe to activate only when legacy parameters explicitly identify
    # the provider and no custom pipeline has been selected yet.
    op.execute(
        """
        UPDATE product_bindings AS binding
        SET status = 'active', trigger_policy = 'automatic'
        WHERE binding.status = 'needs_configuration'
          AND binding.published_pipeline_version_id IS NULL
          AND EXISTS (
              SELECT 1 FROM order_params AS parameter
              WHERE lower(trim(parameter.marketplace)) = binding.provider
                AND parameter.item_id = binding.external_item_id
          )
        """
    )
    op.execute(
        """
        UPDATE order_params AS parameter
        SET binding_id = binding.id, configuration_status = 'configured'
        FROM product_bindings AS binding
        WHERE lower(trim(parameter.marketplace)) = binding.provider
          AND parameter.item_id = binding.external_item_id
        """
    )


def downgrade() -> None:
    # The backfill only restores relationships for existing legacy data. Do not
    # delete products or bindings on downgrade because they may already be used
    # by delivered orders.
    pass
