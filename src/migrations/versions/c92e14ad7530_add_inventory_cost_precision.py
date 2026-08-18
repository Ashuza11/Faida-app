"""add inventory cost precision

Revision ID: c92e14ad7530
Revises: a81c73f90b12
"""

from alembic import op
import sqlalchemy as sa


revision = "c92e14ad7530"
down_revision = "a81c73f90b12"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stock") as batch_op:
        batch_op.alter_column("buying_price_per_unit", type_=sa.Numeric(24, 12))
        batch_op.alter_column("selling_price_per_unit", type_=sa.Numeric(24, 12))
        batch_op.add_column(sa.Column(
            "inventory_value", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "average_cost_per_unit", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))

    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.alter_column("buying_price_at_purchase", type_=sa.Numeric(24, 12))
        batch_op.alter_column("selling_price_at_purchase", type_=sa.Numeric(24, 12))
        batch_op.add_column(sa.Column(
            "actual_total_cost", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))

    with op.batch_alter_table("sale_items") as batch_op:
        batch_op.alter_column("price_per_unit_applied", type_=sa.Numeric(24, 12))
        batch_op.add_column(sa.Column(
            "cost_per_unit_snapshot", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "cost_total", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "margin_amount", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "is_cost_estimated", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ))

    with op.batch_alter_table("sale_item_history") as batch_op:
        batch_op.alter_column("price_per_unit_applied", type_=sa.Numeric(24, 12))

    # Existing values are the best available baseline. Historical sale costs
    # remain explicitly marked estimated; future services write exact snapshots.
    op.execute(sa.text("""
        UPDATE stock
        SET average_cost_per_unit = buying_price_per_unit,
            inventory_value = balance * buying_price_per_unit
    """))
    op.execute(sa.text("""
        UPDATE stock_purchases
        SET actual_total_cost = amount_purchased * buying_price_at_purchase
    """))
    op.execute(sa.text("""
        UPDATE sale_items
        SET cost_per_unit_snapshot = COALESCE((
                SELECT st.buying_price_per_unit
                FROM sales s
                JOIN stock st
                  ON st.vendeur_id = s.vendeur_id
                 AND st.network = sale_items.network
                WHERE s.id = sale_items.sale_id
            ), 0),
            cost_total = quantity * COALESCE((
                SELECT st.buying_price_per_unit
                FROM sales s
                JOIN stock st
                  ON st.vendeur_id = s.vendeur_id
                 AND st.network = sale_items.network
                WHERE s.id = sale_items.sale_id
            ), 0),
            margin_amount = subtotal - quantity * COALESCE((
                SELECT st.buying_price_per_unit
                FROM sales s
                JOIN stock st
                  ON st.vendeur_id = s.vendeur_id
                 AND st.network = sale_items.network
                WHERE s.id = sale_items.sale_id
            ), 0),
            is_cost_estimated = 1
    """))


def downgrade():
    with op.batch_alter_table("sale_item_history") as batch_op:
        batch_op.alter_column("price_per_unit_applied", type_=sa.Numeric(10, 2))
    with op.batch_alter_table("sale_items") as batch_op:
        batch_op.drop_column("is_cost_estimated")
        batch_op.drop_column("margin_amount")
        batch_op.drop_column("cost_total")
        batch_op.drop_column("cost_per_unit_snapshot")
        batch_op.alter_column("price_per_unit_applied", type_=sa.Numeric(10, 2))
    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.drop_column("actual_total_cost")
        batch_op.alter_column("selling_price_at_purchase", type_=sa.Numeric(10, 2))
        batch_op.alter_column("buying_price_at_purchase", type_=sa.Numeric(10, 2))
    with op.batch_alter_table("stock") as batch_op:
        batch_op.drop_column("average_cost_per_unit")
        batch_op.drop_column("inventory_value")
        batch_op.alter_column("selling_price_per_unit", type_=sa.Numeric(10, 2))
        batch_op.alter_column("buying_price_per_unit", type_=sa.Numeric(10, 2))
