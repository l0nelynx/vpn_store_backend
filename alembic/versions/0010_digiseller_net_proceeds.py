"""Backfill Digiseller net proceeds and canonicalize WMR/RUR.

Revision ID: 0010_digiseller_net_proceeds
Revises: 0009_remnawave_v3_user_ids
"""

from __future__ import annotations

from alembic import op


revision = "0010_digiseller_net_proceeds"
down_revision = "0009_remnawave_v3_user_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WebMoney ruble (WMR) and RUR are 1:1 with RUB; without this mapping
    # ingest left gross_rub/net_rub null, so dashboard totals skipped Digiseller.
    op.execute(
        """
        UPDATE orders
        SET
            currency = CASE
                WHEN upper(coalesce(currency, '')) IN ('WMR', 'RUR') THEN 'RUB'
                ELSE currency
            END,
            gross_currency = CASE
                WHEN upper(coalesce(gross_currency, '')) IN ('WMR', 'RUR') THEN 'RUB'
                WHEN gross_currency IS NULL AND upper(coalesce(currency, '')) IN ('WMR', 'RUR', 'RUB') THEN 'RUB'
                ELSE gross_currency
            END,
            net_currency = CASE
                WHEN upper(coalesce(net_currency, '')) IN ('WMR', 'RUR') THEN 'RUB'
                WHEN net_currency IS NULL AND upper(coalesce(currency, '')) IN ('WMR', 'RUR', 'RUB') THEN 'RUB'
                ELSE net_currency
            END
        WHERE marketplace = 'digiseller'
        """
    )
    op.execute(
        """
        UPDATE orders
        SET
            gross_amount = coalesce(gross_amount, amount),
            net_amount = coalesce(net_amount, profit_amount, gross_amount, amount),
            gross_currency = coalesce(gross_currency, 'RUB'),
            net_currency = coalesce(net_currency, gross_currency, currency, 'RUB'),
            currency = coalesce(currency, 'RUB')
        WHERE marketplace = 'digiseller'
          AND (
              upper(coalesce(currency, gross_currency, net_currency, 'RUB')) IN ('RUB', 'WMR', 'RUR')
              OR currency IS NULL
          )
        """
    )
    op.execute(
        """
        UPDATE orders
        SET
            gross_rub = coalesce(
                gross_rub,
                CASE
                    WHEN upper(coalesce(gross_currency, currency, 'RUB')) = 'RUB'
                    THEN coalesce(gross_amount, amount)
                    ELSE gross_rub
                END
            ),
            net_rub = coalesce(
                net_rub,
                CASE
                    WHEN upper(coalesce(net_currency, currency, 'RUB')) = 'RUB'
                    THEN coalesce(net_amount, profit_amount, gross_amount, amount)
                    ELSE net_rub
                END
            )
        WHERE marketplace = 'digiseller'
        """
    )


def downgrade() -> None:
    pass
