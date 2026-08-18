"""backfill business tenant keys

Revision ID: f18bc4290d77
Revises: e07ad6fb4319
"""

from alembic import op
import sqlalchemy as sa


revision = "f18bc4290d77"
down_revision = "e07ad6fb4319"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "clients",
    "stock",
    "stock_opening_balances",
    "sales",
    "sale_item_history",
    "cash_outflows",
    "cash_inflows",
    "daily_stock_reports",
    "daily_overall_reports",
)


def upgrade():
    for table in TENANT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column(
                "business_id", sa.Integer(), nullable=True
            ))
            batch_op.create_foreign_key(
                f"fk_{table}_business_id", "businesses",
                ["business_id"], ["id"],
            )
            batch_op.create_index(
                f"ix_{table}_business_id", ["business_id"], unique=False
            )

        # Every existing row belongs to the retail business created from its
        # legacy vendeur. The column stays nullable for one release so old and
        # new application versions can roll safely during deployment.
        op.execute(sa.text(f"""
            UPDATE {table}
            SET business_id = (
                SELECT b.id
                FROM businesses b
                WHERE b.owner_user_id = {table}.vendeur_id
                  AND b.business_type = 'RETAIL'
                ORDER BY b.id
                LIMIT 1
            )
            WHERE business_id IS NULL
        """))


def downgrade():
    for table in reversed(TENANT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_business_id")
            batch_op.drop_constraint(
                f"fk_{table}_business_id", type_="foreignkey"
            )
            batch_op.drop_column("business_id")
