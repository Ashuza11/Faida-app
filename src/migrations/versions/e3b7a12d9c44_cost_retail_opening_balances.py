"""cost retailer opening balances

Revision ID: e3b7a12d9c44
Revises: c61f47e3a2b8
"""

from alembic import op
import sqlalchemy as sa


revision = "e3b7a12d9c44"
down_revision = "c61f47e3a2b8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.add_column(sa.Column(
            "unit_cost", sa.Numeric(24, 12), nullable=False, server_default="0"
        ))
        batch_op.add_column(sa.Column(
            "actual_total_cost", sa.Numeric(24, 12), nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "is_cost_estimated", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ))

    # Current stock cost is the best recoverable estimate for legacy anchors.
    op.execute(sa.text("""
        UPDATE stock_opening_balances
        SET unit_cost = COALESCE((
                SELECT CASE
                    WHEN st.average_cost_per_unit > 0
                        THEN st.average_cost_per_unit
                    ELSE st.buying_price_per_unit
                END
                FROM stock st
                WHERE st.business_id = stock_opening_balances.business_id
                  AND st.network = stock_opening_balances.network
            ), 0)
    """))
    op.execute(sa.text("""
        UPDATE stock_opening_balances
        SET actual_total_cost = quantity * unit_cost
    """))
    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.alter_column(
            "is_cost_estimated",
            existing_type=sa.Boolean(),
            server_default=sa.false(),
        )


def downgrade():
    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.drop_column("is_cost_estimated")
        batch_op.drop_column("actual_total_cost")
        batch_op.drop_column("unit_cost")
