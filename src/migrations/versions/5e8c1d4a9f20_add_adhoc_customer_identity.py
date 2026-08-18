"""add explicit ad-hoc customer identity

Revision ID: 5e8c1d4a9f20
Revises: 7b7e0f44a821
"""

from alembic import op
import sqlalchemy as sa


revision = "5e8c1d4a9f20"
down_revision = "7b7e0f44a821"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales", sa.Column("adhoc_customer_key", sa.String(64), nullable=True))

    # Preserve the existing safety rule during backfill: matching names do not
    # prove identity. Every historical ad-hoc sale therefore starts distinct.
    sales = sa.table(
        "sales",
        sa.column("id", sa.Integer()),
        sa.column("client_id", sa.Integer()),
        sa.column("adhoc_customer_key", sa.String(64)),
    )
    op.execute(
        sales.update()
        .where(sales.c.client_id.is_(None))
        .values(
            adhoc_customer_key=(
                sa.literal("legacy-sale-") + sa.cast(sales.c.id, sa.String())
            )
        )
    )

    op.create_index(
        "ix_sales_adhoc_customer_key", "sales", ["adhoc_customer_key"], unique=False
    )


def downgrade():
    op.drop_index("ix_sales_adhoc_customer_key", table_name="sales")
    op.drop_column("sales", "adhoc_customer_key")
