"""scope retail reports by business

Revision ID: 8e41c7d2a560
Revises: 2d6a7b91e430
"""

from alembic import op


revision = "8e41c7d2a560"
down_revision = "2d6a7b91e430"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.drop_constraint(
            "_opening_balance_vendeur_network_date_uc", type_="unique"
        )
        batch_op.create_unique_constraint(
            "_opening_balance_business_network_date_uc",
            ["business_id", "network", "balance_date"],
        )

    with op.batch_alter_table("daily_stock_reports") as batch_op:
        batch_op.drop_constraint(
            "_vendeur_report_date_network_uc", type_="unique"
        )
        batch_op.create_unique_constraint(
            "_business_report_date_network_uc",
            ["business_id", "report_date", "network"],
        )

    with op.batch_alter_table("daily_overall_reports") as batch_op:
        batch_op.drop_constraint("_vendeur_report_date_uc", type_="unique")
        batch_op.create_unique_constraint(
            "_business_report_date_uc", ["business_id", "report_date"]
        )


def downgrade():
    with op.batch_alter_table("daily_overall_reports") as batch_op:
        batch_op.drop_constraint("_business_report_date_uc", type_="unique")
        batch_op.create_unique_constraint(
            "_vendeur_report_date_uc", ["vendeur_id", "report_date"]
        )

    with op.batch_alter_table("daily_stock_reports") as batch_op:
        batch_op.drop_constraint(
            "_business_report_date_network_uc", type_="unique"
        )
        batch_op.create_unique_constraint(
            "_vendeur_report_date_network_uc",
            ["vendeur_id", "report_date", "network"],
        )

    with op.batch_alter_table("stock_opening_balances") as batch_op:
        batch_op.drop_constraint(
            "_opening_balance_business_network_date_uc", type_="unique"
        )
        batch_op.create_unique_constraint(
            "_opening_balance_vendeur_network_date_uc",
            ["vendeur_id", "network", "balance_date"],
        )
