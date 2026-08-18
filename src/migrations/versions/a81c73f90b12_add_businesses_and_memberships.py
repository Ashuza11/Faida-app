"""add businesses and memberships

Revision ID: a81c73f90b12
Revises: d4b0b8e1bb3a
"""

from alembic import op
import sqlalchemy as sa


revision = "a81c73f90b12"
down_revision = "d4b0b8e1bb3a"
branch_labels = None
depends_on = None


def upgrade():
    business_type = sa.Enum("RETAIL", "WHOLESALE", name="businesstype")
    currency_code = sa.Enum("CDF", "USD", name="currencycode")
    membership_role = sa.Enum("OWNER", "STOCKEUR", name="membershiprole")

    op.create_table(
        "businesses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("business_type", business_type, nullable=False),
        sa.Column("currency_code", currency_code, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_businesses_owner_user_id", "businesses", ["owner_user_id"])

    op.create_table(
        "business_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "user_id", name="_business_user_membership_uc"),
    )
    op.create_index("ix_business_memberships_business_id", "business_memberships", ["business_id"])
    op.create_index("ix_business_memberships_user_id", "business_memberships", ["user_id"])

    # Every existing vendeur becomes the owner of one backward-compatible
    # retail/CDF business. Existing tenant tables remain untouched in this
    # additive migration and move to business_id in the next verified slice.
    op.execute(sa.text("""
        INSERT INTO businesses
            (name, business_type, currency_code, owner_user_id, is_active, created_at, updated_at)
        SELECT username, 'RETAIL', 'CDF', id, is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM users
        WHERE role = 'VENDEUR'
    """))
    op.execute(sa.text("""
        INSERT INTO business_memberships
            (business_id, user_id, role, is_active, created_at)
        SELECT b.id, b.owner_user_id, 'OWNER', TRUE, CURRENT_TIMESTAMP
        FROM businesses b
    """))


def downgrade():
    op.drop_index("ix_business_memberships_user_id", table_name="business_memberships")
    op.drop_index("ix_business_memberships_business_id", table_name="business_memberships")
    op.drop_table("business_memberships")
    op.drop_index("ix_businesses_owner_user_id", table_name="businesses")
    op.drop_table("businesses")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="membershiprole").drop(bind, checkfirst=True)
        sa.Enum(name="currencycode").drop(bind, checkfirst=True)
        sa.Enum(name="businesstype").drop(bind, checkfirst=True)
