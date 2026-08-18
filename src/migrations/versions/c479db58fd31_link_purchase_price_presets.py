"""link purchases to price presets

Revision ID: c479db58fd31
Revises: 91f87f77ea20
"""

from alembic import op
import sqlalchemy as sa


revision = "c479db58fd31"
down_revision = "91f87f77ea20"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.add_column(sa.Column("price_preset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_stock_purchases_price_preset_id_price_presets",
            "price_presets",
            ["price_preset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_stock_purchases_price_preset_id", ["price_preset_id"]
        )


def downgrade():
    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.drop_index("ix_stock_purchases_price_preset_id")
        batch_op.drop_constraint(
            "fk_stock_purchases_price_preset_id_price_presets",
            type_="foreignkey",
        )
        batch_op.drop_column("price_preset_id")
