"""add independent wholesale cashbook

Revision ID: d92e51a7bc40
Revises: 6fb2c04d8a31
"""

from alembic import op
import sqlalchemy as sa


revision = "d92e51a7bc40"
down_revision = "6fb2c04d8a31"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wholesale_cash_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("recorded_by_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0", name="_wholesale_cash_positive_amount_ck"
        ),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wholesale_cash_entries_business_id",
        "wholesale_cash_entries",
        ["business_id"],
    )
    op.create_index(
        "ix_wholesale_cash_entries_recorded_by_id",
        "wholesale_cash_entries",
        ["recorded_by_id"],
    )
    op.create_index(
        "ix_wholesale_cash_entries_entry_date",
        "wholesale_cash_entries",
        ["entry_date"],
    )
    op.create_index(
        "ix_wholesale_cash_business_date",
        "wholesale_cash_entries",
        ["business_id", "entry_date"],
    )


def downgrade():
    op.drop_index(
        "ix_wholesale_cash_business_date", table_name="wholesale_cash_entries"
    )
    op.drop_index(
        "ix_wholesale_cash_entries_entry_date",
        table_name="wholesale_cash_entries",
    )
    op.drop_index(
        "ix_wholesale_cash_entries_recorded_by_id",
        table_name="wholesale_cash_entries",
    )
    op.drop_index(
        "ix_wholesale_cash_entries_business_id",
        table_name="wholesale_cash_entries",
    )
    op.drop_table("wholesale_cash_entries")
