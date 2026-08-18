"""add wholesale approval lifecycle

Revision ID: 91f87f77ea20
Revises: ab31d6e274c5
"""

from alembic import op
import sqlalchemy as sa


revision = "91f87f77ea20"
down_revision = "ab31d6e274c5"
branch_labels = None
depends_on = None


approval_status = sa.Enum(
    "PENDING", "APPROVED", "REJECTED", name="businessapprovalstatus"
)


def upgrade():
    approval_status.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "approval_status",
                approval_status,
                server_default="APPROVED",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("approved_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_businesses_approved_by_user_id_users",
            "users",
            ["approved_by_user_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_constraint(
            "fk_businesses_approved_by_user_id_users", type_="foreignkey"
        )
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by_user_id")
        batch_op.drop_column("approval_status")
    if op.get_bind().dialect.name == "postgresql":
        approval_status.drop(op.get_bind(), checkfirst=True)
