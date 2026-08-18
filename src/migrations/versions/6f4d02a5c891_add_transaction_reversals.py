"""add transaction reversals and payment events

Revision ID: 6f4d02a5c891
Revises: b3a8cf947120
"""

from alembic import op
import sqlalchemy as sa


revision = "6f4d02a5c891"
down_revision = "b3a8cf947120"
branch_labels = None
depends_on = None


transaction_status = sa.Enum("ACTIVE", "REVERSED", name="transactionstatus")


def upgrade():
    transaction_status.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("stock_purchases") as batch_op:
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
            "fk_stock_purchases_reversed_by_id_users",
            "users",
            ["reversed_by_id"],
            ["id"],
        )

    with op.batch_alter_table("sales") as batch_op:
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
            "fk_sales_reversed_by_id_users",
            "users",
            ["reversed_by_id"],
            ["id"],
        )

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer()),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("source_sale_id", sa.Integer()),
        sa.Column("recorded_by_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["source_sale_id"], ["sales.id"]),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_events_business_id", "payment_events", ["business_id"])
    op.create_index("ix_payment_events_client_id", "payment_events", ["client_id"])
    op.create_index(
        "ix_payment_events_source_sale_id", "payment_events", ["source_sale_id"]
    )
    op.create_index("ix_payment_events_payment_date", "payment_events", ["payment_date"])

    with op.batch_alter_table("cash_inflows") as batch_op:
        batch_op.add_column(sa.Column("payment_event_id", sa.Integer()))
        batch_op.create_index(
            "ix_cash_inflows_payment_event_id", ["payment_event_id"]
        )
        batch_op.create_foreign_key(
            "fk_cash_inflows_payment_event_id_payment_events",
            "payment_events",
            ["payment_event_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("cash_inflows") as batch_op:
        batch_op.drop_constraint(
            "fk_cash_inflows_payment_event_id_payment_events", type_="foreignkey"
        )
        batch_op.drop_index("ix_cash_inflows_payment_event_id")
        batch_op.drop_column("payment_event_id")

    op.drop_index("ix_payment_events_payment_date", table_name="payment_events")
    op.drop_index("ix_payment_events_source_sale_id", table_name="payment_events")
    op.drop_index("ix_payment_events_client_id", table_name="payment_events")
    op.drop_index("ix_payment_events_business_id", table_name="payment_events")
    op.drop_table("payment_events")

    with op.batch_alter_table("sales") as batch_op:
        batch_op.drop_constraint("fk_sales_reversed_by_id_users", type_="foreignkey")
        batch_op.drop_column("reversal_reason")
        batch_op.drop_column("reversed_by_id")
        batch_op.drop_column("reversed_at")
        batch_op.drop_column("status")

    with op.batch_alter_table("stock_purchases") as batch_op:
        batch_op.drop_constraint(
            "fk_stock_purchases_reversed_by_id_users", type_="foreignkey"
        )
        batch_op.drop_column("reversal_reason")
        batch_op.drop_column("reversed_by_id")
        batch_op.drop_column("reversed_at")
        batch_op.drop_column("status")

    if op.get_bind().dialect.name == "postgresql":
        transaction_status.drop(op.get_bind(), checkfirst=True)
