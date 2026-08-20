"""add normalized multi-number client identities

Revision ID: c61f47e3a2b8
Revises: b14f2a8c7d90
"""

from collections import Counter
from datetime import datetime, timezone

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c61f47e3a2b8"
down_revision = "b14f2a8c7d90"
branch_labels = None
depends_on = None


NETWORK_COLUMNS = (
    ("AIRTEL", "phone_airtel"),
    ("AFRICEL", "phone_africel"),
    ("ORANGE", "phone_orange"),
    ("VODACOM", "phone_vodacom"),
)


def _normalize_phone(raw_phone):
    if not raw_phone:
        return None
    phone = "".join(char for char in raw_phone if char.isdigit() or char == "+")
    if phone.startswith("0"):
        phone = "+243" + phone[1:]
    elif phone.startswith("243"):
        phone = "+" + phone
    elif not phone.startswith("+"):
        phone = "+243" + phone
    if len(phone) != 13 or not phone[1:].isdigit() or not phone.startswith("+243"):
        return None
    return phone


def upgrade():
    bind = op.get_bind()
    op.add_column(
        "clients",
        sa.Column("registration_source", sa.String(16), nullable=False, server_default="manual"),
    )
    op.add_column(
        "clients",
        sa.Column("identification_status", sa.String(24), nullable=False, server_default="identified"),
    )
    # SQLAlchemy persists Python Enum member names in the existing PostgreSQL type.
    enum_values = ("AIRTEL", "AFRICEL", "ORANGE", "VODACOM")
    network_enum = (
        postgresql.ENUM(*enum_values, name="networktype", create_type=False)
        if bind.dialect.name == "postgresql"
        else sa.Enum(*enum_values, name="networktype")
    )
    op.create_table(
        "client_phones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("network", network_enum, nullable=False),
        sa.Column("normalized_phone", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalized_phone LIKE '+243%'", name="_client_phone_drc_format_ck"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "network", "normalized_phone",
            name="_client_phone_business_network_uc",
        ),
    )
    op.create_index("ix_client_phones_business_id", "client_phones", ["business_id"])
    op.create_index("ix_client_phones_client_id", "client_phones", ["client_id"])
    op.create_table(
        "client_phone_conflicts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("network", network_enum, nullable=False),
        sa.Column("normalized_phone", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id", "network", "normalized_phone",
            name="_client_phone_conflict_client_uc",
        ),
    )
    op.create_index(
        "ix_client_phone_conflicts_business_id",
        "client_phone_conflicts", ["business_id"],
    )
    op.create_index(
        "ix_client_phone_conflicts_client_id",
        "client_phone_conflicts", ["client_id"],
    )

    # Offline SQL generation has no database rows to inspect. Real deployments run
    # online and execute the guarded legacy-data backfill below.
    if context.is_offline_mode():
        return

    clients = sa.table(
        "clients",
        sa.column("id", sa.Integer),
        sa.column("business_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("registration_source", sa.String),
        sa.column("identification_status", sa.String),
        *(sa.column(column, sa.String) for _, column in NETWORK_COLUMNS),
    )
    client_phones = sa.table(
        "client_phones",
        sa.column("business_id", sa.Integer),
        sa.column("client_id", sa.Integer),
        sa.column("network", sa.String),
        sa.column("normalized_phone", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    client_phone_conflicts = sa.table(
        "client_phone_conflicts",
        sa.column("business_id", sa.Integer),
        sa.column("client_id", sa.Integer),
        sa.column("network", sa.String),
        sa.column("normalized_phone", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    candidates = []
    client_rows = {}
    for row in bind.execute(sa.select(clients)).mappings():
        client_rows[row["id"]] = row
        if row["business_id"] is None:
            continue
        for network, column in NETWORK_COLUMNS:
            normalized = _normalize_phone(row[column])
            if normalized:
                candidates.append((row["business_id"], row["id"], network, normalized))

    counts = Counter((business_id, network, phone) for business_id, _, network, phone in candidates)
    now = datetime.now(timezone.utc)
    # Conflicting legacy numbers are deliberately not guessed or imported. They remain
    # visible in the legacy fields for manual correction before SMS matching can use them.
    rows = [
        {
            "business_id": business_id,
            "client_id": client_id,
            "network": network,
            "normalized_phone": phone,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        for business_id, client_id, network, phone in candidates
        if counts[(business_id, network, phone)] == 1
    ]
    if rows:
        bind.execute(client_phones.insert(), rows)
    conflict_rows = [
        {
            "business_id": business_id,
            "client_id": client_id,
            "network": network,
            "normalized_phone": phone,
            "created_at": now,
        }
        for business_id, client_id, network, phone in candidates
        if counts[(business_id, network, phone)] > 1
    ]
    if conflict_rows:
        bind.execute(client_phone_conflicts.insert(), conflict_rows)

    # Earlier wholesale SMS capture named unknown recipients with their phone.
    # Mark only that unambiguous pattern as SMS-discovered; do not infer from names.
    sms_discovered_ids = {
        client_id
        for _, client_id, _, phone in candidates
        if _normalize_phone(client_rows[client_id].get("name")) == phone
    }
    if sms_discovered_ids:
        bind.execute(
            clients.update()
            .where(clients.c.id.in_(sms_discovered_ids))
            .values(registration_source="sms", identification_status="needs_name")
        )


def downgrade():
    op.drop_index(
        "ix_client_phone_conflicts_client_id", table_name="client_phone_conflicts"
    )
    op.drop_index(
        "ix_client_phone_conflicts_business_id", table_name="client_phone_conflicts"
    )
    op.drop_table("client_phone_conflicts")
    op.drop_index("ix_client_phones_client_id", table_name="client_phones")
    op.drop_index("ix_client_phones_business_id", table_name="client_phones")
    op.drop_table("client_phones")
    op.drop_column("clients", "identification_status")
    op.drop_column("clients", "registration_source")
