"""add report transaction facts

Revision ID: b3a8cf947120
Revises: 4c9fd39180ca
"""

from alembic import op
import sqlalchemy as sa


revision = "b3a8cf947120"
down_revision = "4c9fd39180ca"
branch_labels = None
depends_on = None


allocation_kind = sa.Enum(
    "CURRENT_SALE", "PRIOR_DEBT", name="paymentallocationkind"
)


def upgrade():
    allocation_kind.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.add_column(sa.Column("purchase_date", sa.Date(), nullable=True))
        batch_op.create_index("ix_stock_purchases_purchase_date", ["purchase_date"])
    op.execute(
        "UPDATE stock_purchases SET purchase_date = DATE(created_at) "
        "WHERE purchase_date IS NULL"
    )
    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.alter_column("purchase_date", nullable=False)

    with op.batch_alter_table("sales") as batch_op:
        batch_op.add_column(sa.Column(
            "initial_cash_paid",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ))
    with op.batch_alter_table("cash_inflows") as batch_op:
        batch_op.add_column(sa.Column(
            "allocation_kind", allocation_kind, nullable=True
        ))
    allocation_case = (
        "CASE WHEN description = 'Paiement de la vente' "
        "THEN 'CURRENT_SALE' ELSE 'PRIOR_DEBT' END"
    )
    if op.get_bind().dialect.name == "postgresql":
        allocation_case = f"({allocation_case})::paymentallocationkind"
    op.execute(
        "UPDATE cash_inflows "
        f"SET allocation_kind = {allocation_case} "
        "WHERE sale_id IS NOT NULL"
    )
    op.execute(
        "UPDATE sales SET initial_cash_paid = COALESCE(("
        "SELECT SUM(cash_inflows.amount) FROM cash_inflows "
        "WHERE cash_inflows.sale_id = sales.id "
        "AND cash_inflows.allocation_kind = 'CURRENT_SALE'"
        "), cash_paid)"
    )


def downgrade():
    with op.batch_alter_table("cash_inflows") as batch_op:
        batch_op.drop_column("allocation_kind")
    with op.batch_alter_table("sales") as batch_op:
        batch_op.drop_column("initial_cash_paid")
    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.drop_index("ix_stock_purchases_purchase_date")
        batch_op.drop_column("purchase_date")
    if op.get_bind().dialect.name == "postgresql":
        allocation_kind.drop(op.get_bind(), checkfirst=True)
