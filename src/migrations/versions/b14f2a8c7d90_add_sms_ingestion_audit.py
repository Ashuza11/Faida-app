"""add idempotent Android SMS ingestion audit

Revision ID: b14f2a8c7d90
Revises: 9a21f7c3d6e4
"""

from alembic import op
import sqlalchemy as sa


revision = "b14f2a8c7d90"
down_revision = "9a21f7c3d6e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sms_ingestions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("sender", sa.String(40), nullable=False),
        sa.Column("received_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("message_type", sa.String(16), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=True),
        sa.Column("purchase_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"]),
        sa.ForeignKeyConstraint(["purchase_id"], ["stock_purchases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "fingerprint", name="_sms_business_fingerprint_uc"
        ),
    )
    op.create_index(
        "ix_sms_ingestions_business_id", "sms_ingestions", ["business_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_sms_ingestions_business_id", table_name="sms_ingestions")
    op.drop_table("sms_ingestions")
