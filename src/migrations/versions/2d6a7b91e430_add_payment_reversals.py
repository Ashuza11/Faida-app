"""add payment reversals

Revision ID: 2d6a7b91e430
Revises: 6f4d02a5c891
"""

from alembic import op
import sqlalchemy as sa


revision = "2d6a7b91e430"
down_revision = "6f4d02a5c891"
branch_labels = None
depends_on = None


transaction_status = sa.Enum("ACTIVE", "REVERSED", name="transactionstatus")


def upgrade():
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                transaction_status,
                server_default="ACTIVE",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("reversed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("reversed_by_id", sa.Integer()))
        batch_op.add_column(sa.Column("reversal_reason", sa.String(255)))
        batch_op.create_foreign_key(
            "fk_payment_events_reversed_by_id_users",
            "users",
            ["reversed_by_id"],
            ["id"],
        )

    with op.batch_alter_table("cash_inflows") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                transaction_status,
                server_default="ACTIVE",
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table("cash_inflows") as batch_op:
        batch_op.drop_column("status")

    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.drop_constraint(
            "fk_payment_events_reversed_by_id_users", type_="foreignkey"
        )
        batch_op.drop_column("reversal_reason")
        batch_op.drop_column("reversed_by_id")
        batch_op.drop_column("reversed_at")
        batch_op.drop_column("status")
