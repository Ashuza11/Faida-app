"""audit and deduplicate wholesale cashbook

Revision ID: e51b90d4ac72
Revises: d92e51a7bc40
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "e51b90d4ac72"
down_revision = "d92e51a7bc40"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("wholesale_cash_entries") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column("corrected_from_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(16),
                server_default="ACTIVE",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("reversed_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reversal_reason", sa.String(255), nullable=True))
        batch_op.create_foreign_key(
            "fk_wholesale_cash_corrected_from",
            "wholesale_cash_entries",
            ["corrected_from_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_wholesale_cash_reversed_by",
            "users",
            ["reversed_by_id"],
            ["id"],
        )

    if op.get_context().dialect.name == "postgresql":
        # Keep this backfill executable in both online deployments and Alembic's
        # offline SQL mode. PostgreSQL's built-in md5 function avoids requiring
        # a UUID extension on production databases.
        digest = "md5('faida-wholesale-cash-entry:' || id::text)"
        op.execute(
            sa.text(
                "UPDATE wholesale_cash_entries SET request_id = "
                f"substr({digest}, 1, 8) || '-' || "
                f"substr({digest}, 9, 4) || '-' || "
                f"substr({digest}, 13, 4) || '-' || "
                f"substr({digest}, 17, 4) || '-' || "
                f"substr({digest}, 21, 12) "
                "WHERE request_id IS NULL"
            )
        )
    else:
        entries = sa.table(
            "wholesale_cash_entries",
            sa.column("id", sa.Integer()),
            sa.column("request_id", sa.String(36)),
        )
        connection = op.get_bind()
        for entry_id in connection.execute(sa.select(entries.c.id)).scalars():
            connection.execute(
                entries.update()
                .where(entries.c.id == entry_id)
                .values(request_id=str(uuid4()))
            )

    with op.batch_alter_table("wholesale_cash_entries") as batch_op:
        batch_op.alter_column(
            "request_id", existing_type=sa.String(36), nullable=False
        )
        batch_op.alter_column(
            "status", existing_type=sa.String(16), server_default=None
        )
        batch_op.create_unique_constraint(
            "_wholesale_cash_business_request_uc",
            ["business_id", "request_id"],
        )
        batch_op.create_index(
            "ix_wholesale_cash_entries_corrected_from_id",
            ["corrected_from_id"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("wholesale_cash_entries") as batch_op:
        batch_op.drop_index("ix_wholesale_cash_entries_corrected_from_id")
        batch_op.drop_constraint(
            "_wholesale_cash_business_request_uc", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_wholesale_cash_reversed_by", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_wholesale_cash_corrected_from", type_="foreignkey"
        )
        batch_op.drop_column("reversal_reason")
        batch_op.drop_column("reversed_by_id")
        batch_op.drop_column("reversed_at")
        batch_op.drop_column("status")
        batch_op.drop_column("corrected_from_id")
        batch_op.drop_column("request_id")
