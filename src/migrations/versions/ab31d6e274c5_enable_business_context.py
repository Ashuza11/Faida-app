"""enable business context

Revision ID: ab31d6e274c5
Revises: f18bc4290d77
"""

from alembic import op
import sqlalchemy as sa


revision = "ab31d6e274c5"
down_revision = "f18bc4290d77"
branch_labels = None
depends_on = None


def upgrade():
    # Existing stockeurs receive access only to their employer's retail ledger.
    op.execute(sa.text("""
        INSERT INTO business_memberships
            (business_id, user_id, role, is_active, created_at)
        SELECT b.id, u.id, 'STOCKEUR', u.is_active, CURRENT_TIMESTAMP
        FROM users u
        JOIN businesses b
          ON b.owner_user_id = u.vendeur_id
         AND b.business_type = 'RETAIL'
        WHERE u.role = 'STOCKEUR'
          AND NOT EXISTS (
              SELECT 1 FROM business_memberships bm
              WHERE bm.business_id = b.id AND bm.user_id = u.id
          )
    """))

    with op.batch_alter_table("stock") as batch_op:
        batch_op.drop_constraint("_vendeur_network_uc", type_="unique")
        batch_op.create_unique_constraint(
            "_business_network_uc", ["business_id", "network"]
        )


def downgrade():
    with op.batch_alter_table("stock") as batch_op:
        batch_op.drop_constraint("_business_network_uc", type_="unique")
        batch_op.create_unique_constraint(
            "_vendeur_network_uc", ["vendeur_id", "network"]
        )
    op.execute(sa.text("""
        DELETE FROM business_memberships
        WHERE role = 'STOCKEUR'
    """))
