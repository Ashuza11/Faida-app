"""add wholesale revocation audit

Revision ID: a4d72c9e810f
Revises: 8d2f4c6a190b
"""

from alembic import op
import sqlalchemy as sa


revision = "a4d72c9e810f"
down_revision = "8d2f4c6a190b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(
            sa.Column("revoked_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("revocation_reason", sa.String(length=64), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_businesses_revoked_by_user_id_users",
            "users",
            ["revoked_by_user_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_constraint(
            "fk_businesses_revoked_by_user_id_users", type_="foreignkey"
        )
        batch_op.drop_column("revocation_reason")
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("revoked_by_user_id")
