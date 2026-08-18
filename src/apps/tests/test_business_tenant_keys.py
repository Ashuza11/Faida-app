from datetime import date
from decimal import Decimal

from apps.businesses import create_business
from apps.models import (
    BusinessType,
    Client,
    NetworkType,
    RoleType,
    Sale,
    Stock,
    User,
)


def test_same_owner_businesses_have_independent_tenant_keys(session):
    owner = User(
        username="multi-business-owner",
        phone="+243810007777",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner, name="Wholesale", business_type=BusinessType.WHOLESALE
    )
    session.flush()

    retail_stock = Stock(
        vendeur_id=owner.id, business_id=retail.id,
        network=NetworkType.AIRTEL, balance=100,
    )
    wholesale_stock = Stock(
        vendeur_id=owner.id, business_id=wholesale.id,
        network=NetworkType.ORANGE, balance=1000,
    )
    session.add_all([retail_stock, wholesale_stock])
    session.flush()

    assert Stock.query.filter_by(business_id=retail.id).one() is retail_stock
    assert Stock.query.filter_by(business_id=wholesale.id).one() is wholesale_stock


def test_clients_and_sales_are_scoped_by_business_not_owner(session):
    owner = User(
        username="shared-owner", phone="+243810006666", role=RoleType.VENDEUR
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner, name="Wholesale", business_type=BusinessType.WHOLESALE
    )
    session.flush()
    retail_client = Client(
        name="Client", vendeur_id=owner.id, business_id=retail.id
    )
    wholesale_client = Client(
        name="Client", vendeur_id=owner.id, business_id=wholesale.id
    )
    session.add_all([retail_client, wholesale_client])
    session.flush()
    session.add_all([
        Sale(
            seller_id=owner.id, vendeur_id=owner.id, business_id=retail.id,
            client=retail_client, sale_date=date.today(),
            total_amount_due=Decimal("100"), cash_paid=0, debt_amount=100,
        ),
        Sale(
            seller_id=owner.id, vendeur_id=owner.id, business_id=wholesale.id,
            client=wholesale_client, sale_date=date.today(),
            total_amount_due=Decimal("10"), cash_paid=0, debt_amount=10,
        ),
    ])
    session.flush()

    assert Sale.query.filter_by(business_id=retail.id).one().client is retail_client
    assert Sale.query.filter_by(business_id=wholesale.id).one().client is wholesale_client
