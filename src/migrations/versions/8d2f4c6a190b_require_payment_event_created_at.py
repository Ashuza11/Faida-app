"""require payment event creation timestamps

Revision ID: 8d2f4c6a190b
Revises: 7c91a1e4f2b0
"""

from alembic import op
import sqlalchemy as sa


revision = "8d2f4c6a190b"
down_revision = "7c91a1e4f2b0"
branch_labels = None
depends_on = None


def upgrade():
    # Historical rows may predate the model's required timestamp. Backfill them
    # before applying NOT NULL so production upgrades cannot fail on old data.
    op.execute(sa.text(
        "UPDATE payment_events "
        "SET created_at = CURRENT_TIMESTAMP "
        "WHERE created_at IS NULL"
    ))
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
