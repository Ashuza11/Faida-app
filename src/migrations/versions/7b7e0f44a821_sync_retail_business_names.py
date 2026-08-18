"""sync retail business names

Revision ID: 7b7e0f44a821
Revises: 31c9a742bd18
"""

from alembic import op
import sqlalchemy as sa


revision = "7b7e0f44a821"
down_revision = "31c9a742bd18"
branch_labels = None
depends_on = None


def upgrade():
    # Retail mode names originally copied the seller name once at registration.
    # Synchronize existing rows after seller renames; wholesale names are
    # intentionally independent and must not be overwritten.
    op.execute(sa.text("""
        UPDATE businesses
        SET name = (
            SELECT users.username
            FROM users
            WHERE users.id = businesses.owner_user_id
        )
        WHERE business_type = 'RETAIL'
    """))


def downgrade():
    # The previous copied name cannot be reconstructed reliably.
    pass
