"""add business price presets

Revision ID: e07ad6fb4319
Revises: c92e14ad7530
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e07ad6fb4319"
down_revision = "c92e14ad7530"
branch_labels = None
depends_on = None


def existing_network_type():
    """Reference the base-schema enum without recreating it on PostgreSQL."""
    values = ("AIRTEL", "AFRICEL", "ORANGE", "VODACOM")
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(
            *values,
            name="networktype",
            create_type=False,
        )
    return sa.Enum(*values, name="networktype")


def upgrade():
    op.create_table(
        "price_presets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("network", existing_network_type(), nullable=False),
        sa.Column("operation", sa.Enum("PURCHASE", "SALE", name="priceoperation"), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("unit_price", sa.Numeric(24, 12), nullable=False),
        sa.Column("ratio_amount", sa.Numeric(24, 12), nullable=True),
        sa.Column("ratio_units", sa.Numeric(24, 12), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(ratio_amount IS NULL AND ratio_units IS NULL) OR "
            "(ratio_amount > 0 AND ratio_units > 0)",
            name="_price_preset_complete_ratio_ck",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_presets_business_id", "price_presets", ["business_id"])


def downgrade():
    op.drop_index("ix_price_presets_business_id", table_name="price_presets")
    op.drop_table("price_presets")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="priceoperation").drop(bind, checkfirst=True)
