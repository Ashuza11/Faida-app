"""fix Airtel and Africel standard purchase costs

Revision ID: 6fb2c04d8a31
Revises: 4ad91e7c2f10
"""

from alembic import op
import sqlalchemy as sa
from decimal import Decimal


revision = "6fb2c04d8a31"
down_revision = "4ad91e7c2f10"
branch_labels = None
depends_on = None


STANDARD_PRICES = {
    "Standard Airtel": sa.literal(Decimal("0.00935")),
    "Standard Africel": sa.literal(Decimal("0.00940")),
}


def _presets():
    return sa.table(
        "price_presets",
        sa.column("label", sa.String(80)),
        sa.column("unit_price", sa.Numeric(24, 12)),
        sa.column("ratio_amount", sa.Numeric(24, 12)),
        sa.column("ratio_units", sa.Numeric(24, 12)),
    )


def upgrade():
    presets = _presets()
    for label, unit_price in STANDARD_PRICES.items():
        op.execute(
            presets.update()
            .where(presets.c.label == label)
            .where(presets.c.unit_price == unit_price)
            .where(presets.c.ratio_amount == 100)
            .where(presets.c.ratio_units == 10650)
            .values(ratio_amount=None, ratio_units=None)
        )


def downgrade():
    presets = _presets()
    for label, unit_price in STANDARD_PRICES.items():
        op.execute(
            presets.update()
            .where(presets.c.label == label)
            .where(presets.c.unit_price == unit_price)
            .where(presets.c.ratio_amount.is_(None))
            .where(presets.c.ratio_units.is_(None))
            .values(ratio_amount=sa.literal(100), ratio_units=sa.literal(10650))
        )
