"""add opening stock selling prices

Revision ID: b61f08d3ca42
Revises: a4d72c9e810f
"""

from alembic import op
import sqlalchemy as sa


revision = "b61f08d3ca42"
down_revision = "a4d72c9e810f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.add_column(sa.Column(
            "selling_price_per_unit", sa.Numeric(24, 12), nullable=True
        ))

    # Existing opening rows inherit the retail stock's configured selling
    # price when available. Wholesale rows intentionally remain NULL because
    # wholesale prices are selected per sale from presets.
    op.execute(sa.text("""
        UPDATE stock_opening_balances
        SET selling_price_per_unit = (
            SELECT stock.selling_price_per_unit
            FROM stock
            JOIN businesses ON businesses.id = stock.business_id
            WHERE stock.business_id = stock_opening_balances.business_id
              AND stock.network = stock_opening_balances.network
              AND businesses.business_type = 'RETAIL'
        )
        WHERE EXISTS (
            SELECT 1
            FROM stock
            JOIN businesses ON businesses.id = stock.business_id
            WHERE stock.business_id = stock_opening_balances.business_id
              AND stock.network = stock_opening_balances.network
              AND businesses.business_type = 'RETAIL'
        )
    """))


def downgrade():
    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.drop_column("selling_price_per_unit")
