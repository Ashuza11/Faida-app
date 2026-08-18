"""link sale items to price presets

Revision ID: 4c9fd39180ca
Revises: c479db58fd31
"""

from alembic import op
import sqlalchemy as sa


revision = "4c9fd39180ca"
down_revision = "c479db58fd31"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sale_items") as batch_op:
        batch_op.add_column(sa.Column("price_preset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_sale_items_price_preset_id_price_presets",
            "price_presets",
            ["price_preset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_sale_items_price_preset_id", ["price_preset_id"])


def downgrade():
    with op.batch_alter_table("sale_items") as batch_op:
        batch_op.drop_index("ix_sale_items_price_preset_id")
        batch_op.drop_constraint(
            "fk_sale_items_price_preset_id_price_presets", type_="foreignkey"
        )
        batch_op.drop_column("price_preset_id")
