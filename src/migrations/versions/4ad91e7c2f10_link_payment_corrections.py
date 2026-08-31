"""link payment corrections

Revision ID: 4ad91e7c2f10
Revises: e3b7a12d9c44
"""

from alembic import op
import sqlalchemy as sa


revision = "4ad91e7c2f10"
down_revision = "e3b7a12d9c44"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.add_column(sa.Column(
            "corrected_from_id", sa.Integer(), nullable=True
        ))
        batch_op.create_foreign_key(
            "fk_payment_events_corrected_from_id",
            "payment_events",
            ["corrected_from_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_payment_events_corrected_from_id",
            ["corrected_from_id"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.drop_index("ix_payment_events_corrected_from_id")
        batch_op.drop_constraint(
            "fk_payment_events_corrected_from_id", type_="foreignkey"
        )
        batch_op.drop_column("corrected_from_id")
