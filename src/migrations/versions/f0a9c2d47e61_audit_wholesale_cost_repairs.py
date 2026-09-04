"""audit wholesale cost repairs

Revision ID: f0a9c2d47e61
Revises: e51b90d4ac72
"""

from alembic import op
import sqlalchemy as sa


revision = "f0a9c2d47e61"
down_revision = "e51b90d4ac72"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wholesale_sale_cost_corrections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sale_item_id", sa.Integer(), nullable=False),
        sa.Column("corrected_by_id", sa.Integer(), nullable=False),
        sa.Column("old_unit_cost", sa.Numeric(24, 12), nullable=False),
        sa.Column("new_unit_cost", sa.Numeric(24, 12), nullable=False),
        sa.Column("old_total_cost", sa.Numeric(24, 12), nullable=False),
        sa.Column("new_total_cost", sa.Numeric(24, 12), nullable=False),
        sa.Column("old_margin", sa.Numeric(24, 12), nullable=False),
        sa.Column("new_margin", sa.Numeric(24, 12), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("source", sa.String(160), nullable=False),
        sa.Column("note", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IN ('verified', 'estimated')",
            name="_wholesale_cost_correction_confidence_ck",
        ),
        sa.ForeignKeyConstraint(
            ["sale_item_id"], ["sale_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["corrected_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wholesale_sale_cost_corrections_sale_item_id",
        "wholesale_sale_cost_corrections",
        ["sale_item_id"],
    )
    op.create_index(
        "ix_wholesale_sale_cost_corrections_corrected_by_id",
        "wholesale_sale_cost_corrections",
        ["corrected_by_id"],
    )


def downgrade():
    op.drop_index(
        "ix_wholesale_sale_cost_corrections_corrected_by_id",
        table_name="wholesale_sale_cost_corrections",
    )
    op.drop_index(
        "ix_wholesale_sale_cost_corrections_sale_item_id",
        table_name="wholesale_sale_cost_corrections",
    )
    op.drop_table("wholesale_sale_cost_corrections")
