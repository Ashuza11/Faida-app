from datetime import date
from decimal import Decimal

import pytest

from apps import db
from apps.businesses import create_business
from apps.inventory import consume_stock
from apps.models import (
    BusinessType,
    Client,
    NetworkType,
    RoleType,
    Sale,
    SaleItem,
    SaleItemHistory,
    Stock,
    User,
)
from apps.purchases import record_retail_purchase
from apps.sales import replace_retail_sale


def setup_retail_inventory(session, *, suffix=1, include_orange=False):
    owner = User(
        username=f"replay-owner-{suffix}",
        phone=f"+243810008{suffix:03d}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner,
        name=f"Replay retail {suffix}",
        business_type=BusinessType.RETAIL,
    )
    session.flush()
    client = Client(
        name="Replay client",
        vendeur_id=owner.id,
        business_id=business.id,
    )
    session.add(client)
    record_retail_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100,
        unit_cost=Decimal("10"),
        intended_selling_price=Decimal("25"),
        purchase_date=date.today(),
    )
    if include_orange:
        record_retail_purchase(
            business=business,
            purchased_by=owner,
            network=NetworkType.ORANGE,
            quantity=200,
            unit_cost=Decimal("5"),
            intended_selling_price=Decimal("8"),
            purchase_date=date.today(),
        )
    session.flush()
    return owner, business, client


def record_retail_sale_for_test(
    *, business, owner, client, network, quantity, unit_price
):
    stock = Stock.query.filter_by(
        business_id=business.id,
        network=network,
    ).one()
    cost_per_unit, cost_total = consume_stock(stock=stock, quantity=quantity)
    subtotal = (Decimal(quantity) * unit_price).quantize(Decimal("0.01"))
    sale = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=business.id,
        client=client,
        sale_date=date.today(),
        total_amount_due=subtotal,
        cash_paid=Decimal("0"),
        debt_amount=subtotal,
    )
    sale.sale_items.append(SaleItem(
        network=network,
        quantity=quantity,
        price_per_unit_applied=unit_price,
        subtotal=subtotal,
        cost_per_unit_snapshot=cost_per_unit,
        cost_total=cost_total,
        margin_amount=subtotal - cost_total,
        is_cost_estimated=False,
    ))
    db.session.add(sale)
    db.session.flush()
    return sale


def test_retail_quantity_correction_replays_later_purchase_and_sale(session):
    owner, business, client = setup_retail_inventory(session, suffix=1)
    target = record_retail_sale_for_test(
        business=business,
        owner=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=20,
        unit_price=Decimal("25"),
    )
    record_retail_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100,
        unit_cost=Decimal("20"),
        intended_selling_price=Decimal("25"),
        purchase_date=date.today(),
    )
    session.flush()
    later_sale = record_retail_sale_for_test(
        business=business,
        owner=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=50,
        unit_price=Decimal("25"),
    )
    old_later_cost = later_sale.sale_items[0].cost_total

    replace_retail_sale(
        sale=target,
        business=business,
        updated_by=owner,
        client=client,
        client_name_adhoc=None,
        adhoc_customer_key=None,
        sale_date=target.sale_date,
        items=[{
            "network": NetworkType.AIRTEL,
            "quantity": 10,
            "price_per_unit_applied": Decimal("25"),
        }],
    )
    session.flush()

    target_item = target.sale_items[0]
    later_item = later_sale.sale_items[0]
    stock = Stock.query.filter_by(
        business_id=business.id,
        network=NetworkType.AIRTEL,
    ).one()
    assert target_item.cost_per_unit_snapshot == Decimal("10.000000000000")
    assert target_item.cost_total == Decimal("100.000000000000")
    assert later_item.cost_total == Decimal("763.157894736850")
    assert later_item.cost_total != old_later_cost
    assert later_item.margin_amount == later_item.subtotal - later_item.cost_total
    assert stock.balance == 140
    assert stock.inventory_value == Decimal("2136.842105263150")
    assert stock.average_cost_per_unit == Decimal("15.263157894737")
    assert SaleItemHistory.query.filter_by(sale_id=target.id).one().quantity == 20


def test_retail_network_correction_replays_both_stock_ledgers(session):
    owner, business, client = setup_retail_inventory(
        session, suffix=2, include_orange=True
    )
    target = record_retail_sale_for_test(
        business=business,
        owner=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=20,
        unit_price=Decimal("25"),
    )
    record_retail_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100,
        unit_cost=Decimal("20"),
        intended_selling_price=Decimal("25"),
    )
    record_retail_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.ORANGE,
        quantity=100,
        unit_cost=Decimal("8"),
        intended_selling_price=Decimal("10"),
    )
    session.flush()

    replace_retail_sale(
        sale=target,
        business=business,
        updated_by=owner,
        client=client,
        client_name_adhoc=None,
        adhoc_customer_key=None,
        sale_date=target.sale_date,
        items=[{
            "network": NetworkType.ORANGE,
            "quantity": 30,
            "price_per_unit_applied": Decimal("8"),
        }],
    )
    session.flush()

    airtel = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    orange = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.ORANGE
    ).one()
    assert [(item.network, item.quantity) for item in target.sale_items] == [
        (NetworkType.ORANGE, 30)
    ]
    assert target.sale_items[0].cost_total == Decimal("150.000000000000")
    assert airtel.balance == 200
    assert airtel.inventory_value == Decimal("3000.000000000000")
    assert orange.balance == 270
    assert orange.inventory_value == Decimal("1650.000000000000")


def test_replay_rejects_stock_that_did_not_exist_at_original_sale_time(session):
    owner, business, client = setup_retail_inventory(session, suffix=3)
    target = record_retail_sale_for_test(
        business=business,
        owner=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=20,
        unit_price=Decimal("25"),
    )
    record_retail_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100,
        unit_cost=Decimal("20"),
        intended_selling_price=Decimal("25"),
    )
    session.flush()
    session.commit()

    with pytest.raises(ValueError) as error:
        replace_retail_sale(
            sale=target,
            business=business,
            updated_by=owner,
            client=client,
            client_name_adhoc=None,
            adhoc_customer_key=None,
            sale_date=target.sale_date,
            items=[{
                "network": NetworkType.AIRTEL,
                "quantity": 120,
                "price_per_unit_applied": Decimal("25"),
            }],
        )

    assert "insuffisant à la date de la vente" in str(error.value)
    assert "Disponible : 100 unités" in str(error.value)
    session.rollback()
    stock = Stock.query.filter_by(
        business_id=business.id,
        network=NetworkType.AIRTEL,
    ).one()
    assert stock.balance == 180
    assert stock.inventory_value == Decimal("2800.000000000000")


def test_replay_identifies_later_retail_sale_that_would_lack_stock(session):
    owner, business, client = setup_retail_inventory(session, suffix=4)
    target = record_retail_sale_for_test(
        business=business,
        owner=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=20,
        unit_price=Decimal("25"),
    )
    later_sale = record_retail_sale_for_test(
        business=business,
        owner=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=70,
        unit_price=Decimal("25"),
    )
    session.commit()

    with pytest.raises(ValueError) as error:
        replace_retail_sale(
            sale=target,
            business=business,
            updated_by=owner,
            client=client,
            client_name_adhoc=None,
            adhoc_customer_key=None,
            sale_date=target.sale_date,
            items=[{
                "network": NetworkType.AIRTEL,
                "quantity": 40,
                "price_per_unit_applied": Decimal("25"),
            }],
        )

    assert "vente airtel plus récente impossible" in str(error.value).lower()
    assert "Vente concernée : #2" in str(error.value)
    session.rollback()
    session.refresh(later_sale)
    assert later_sale.sale_items[0].quantity == 70
