"""allow ad-hoc payment events

Revision ID: 31c9a742bd18
Revises: 8e41c7d2a560
"""

from alembic import op
import sqlalchemy as sa


revision = "31c9a742bd18"
down_revision = "8e41c7d2a560"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.alter_column(
            "client_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade():
    bind = op.get_bind()
    missing_clients = bind.execute(
        sa.text("SELECT COUNT(*) FROM payment_events WHERE client_id IS NULL")
    ).scalar()
    if missing_clients:
        raise RuntimeError(
            "Cannot require payment_events.client_id while ad-hoc receipts exist."
        )
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.alter_column(
            "client_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
