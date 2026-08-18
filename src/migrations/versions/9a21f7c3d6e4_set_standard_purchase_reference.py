"""set exact reference totals for standard Airtel and Africel purchases

Revision ID: 9a21f7c3d6e4
Revises: 5e8c1d4a9f20
"""

from alembic import op
import sqlalchemy as sa


revision = "9a21f7c3d6e4"
down_revision = "5e8c1d4a9f20"
branch_labels = None
depends_on = None


STANDARD_LABELS = ("Standard Airtel", "Standard Africel")


def _standard_presets():
    return sa.table(
        "price_presets",
        sa.column("label", sa.String(80)),
        sa.column("ratio_amount", sa.Numeric(24, 12)),
        sa.column("ratio_units", sa.Numeric(24, 12)),
    )


def upgrade():
    presets = _standard_presets()
    op.execute(
        presets.update()
        .where(presets.c.label.in_(STANDARD_LABELS))
        .values(ratio_amount=sa.literal(100), ratio_units=sa.literal(10650))
    )


def downgrade():
    presets = _standard_presets()
    op.execute(
        presets.update()
        .where(presets.c.label.in_(STANDARD_LABELS))
        .where(presets.c.ratio_amount == 100)
        .where(presets.c.ratio_units == 10650)
        .values(ratio_amount=None, ratio_units=None)
    )
