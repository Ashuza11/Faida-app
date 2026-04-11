"""add sale_item_history table

Revision ID: 0df39880850f
Revises: ddc9430cbbe5
Create Date: 2026-04-11 16:32:38.185197

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '0df39880850f'
down_revision = 'ddc9430cbbe5'
branch_labels = None
depends_on = None

# networktype enum already exists in the DB — reference it without re-creating it
networktype = postgresql.ENUM(
    'AIRTEL', 'AFRICEL', 'ORANGE', 'VODACOM',
    name='networktype',
    create_type=False,
)


def upgrade():
    op.create_table('sale_item_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sale_id', sa.Integer(), nullable=True),
    sa.Column('vendeur_id', sa.Integer(), nullable=False),
    sa.Column('changed_by_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('network', networktype, nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('price_per_unit_applied', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vendeur_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('sale_item_history')
