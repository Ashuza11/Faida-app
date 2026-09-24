"""add reversible retail cash outflows

Revision ID: 7c91a1e4f2b0
Revises: f0a9c2d47e61
"""

from alembic import op
import sqlalchemy as sa


revision = "7c91a1e4f2b0"
down_revision = "f0a9c2d47e61"
branch_labels = None
depends_on = None


transaction_status = sa.Enum("ACTIVE", "REVERSED", name="transactionstatus")


def upgrade():
    with op.batch_alter_table("cash_outflows") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(64)))
        batch_op.add_column(sa.Column(
            "status",
            transaction_status,
            server_default="ACTIVE",
            nullable=False,
        ))
        batch_op.add_column(sa.Column("reversed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("reversed_by_id", sa.Integer()))
        batch_op.add_column(sa.Column("reversal_reason", sa.String(255)))
        batch_op.create_foreign_key(
            "fk_cash_outflows_reversed_by_id_users",
            "users",
            ["reversed_by_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "_cash_outflow_positive_amount_ck", "amount > 0"
        )
        batch_op.create_index(
            "ix_cash_outflows_business_date_status",
            ["business_id", "expense_date", "status"],
        )
        batch_op.create_unique_constraint(
            "_cash_outflows_business_request_uc", ["business_id", "request_id"]
        )


def downgrade():
    with op.batch_alter_table("cash_outflows") as batch_op:
        batch_op.drop_constraint(
            "_cash_outflows_business_request_uc", type_="unique"
        )
        batch_op.drop_index("ix_cash_outflows_business_date_status")
        batch_op.drop_constraint(
            "_cash_outflow_positive_amount_ck", type_="check"
        )
        batch_op.drop_constraint(
            "fk_cash_outflows_reversed_by_id_users", type_="foreignkey"
        )
        batch_op.drop_column("reversal_reason")
        batch_op.drop_column("reversed_by_id")
        batch_op.drop_column("reversed_at")
        batch_op.drop_column("status")
        batch_op.drop_column("request_id")
