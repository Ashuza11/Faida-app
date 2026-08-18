from decimal import Decimal

import pytest

from apps.inventory import consume_stock, record_purchase, restore_sale_cost, reverse_purchase
from apps.models import NetworkType, RoleType, Stock, User


@pytest.fixture()
def stock(session):
    owner = User(
        username="inventory-owner", phone="+243810009999", role=RoleType.VENDEUR
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    item = Stock(vendeur_id=owner.id, network=NetworkType.ORANGE)
    session.add(item)
    session.flush()
    return item


def test_purchase_uses_moving_weighted_average(stock):
    record_purchase(
        stock=stock, quantity=10000, actual_total_cost=Decimal("93.50"),
        quoted_unit_cost=Decimal("0.00935"),
    )
    record_purchase(
        stock=stock, quantity=10650, actual_total_cost=Decimal("100"),
        quoted_unit_cost=Decimal("100") / Decimal("10650"),
    )

    assert stock.balance == Decimal("20650")
    assert stock.inventory_value == Decimal("193.500000000000")
    assert stock.average_cost_per_unit == Decimal("0.009370460048")


def test_sale_cost_snapshot_is_stable_after_later_purchase(stock):
    record_purchase(stock=stock, quantity=10000, actual_total_cost=Decimal("93.50"))
    unit_cost, cost = consume_stock(stock=stock, quantity=5000)
    record_purchase(stock=stock, quantity=10000, actual_total_cost=Decimal("100"))

    assert unit_cost == Decimal("0.009350000000")
    assert cost == Decimal("46.750000000000")
    assert stock.average_cost_per_unit != unit_cost


def test_consuming_final_units_clears_inventory_value(stock):
    record_purchase(stock=stock, quantity=3, actual_total_cost=Decimal("1"))
    _, cost = consume_stock(stock=stock, quantity=3)

    assert cost == Decimal("1.000000000000")
    assert stock.balance == 0
    assert stock.inventory_value == 0


def test_restore_sale_rebuilds_quantity_and_value(stock):
    record_purchase(stock=stock, quantity=10000, actual_total_cost=Decimal("93.50"))
    _, cost = consume_stock(stock=stock, quantity=2500)
    restore_sale_cost(stock=stock, quantity=2500, cost_total=cost)

    assert stock.balance == Decimal("10000")
    assert stock.inventory_value == Decimal("93.500000000000")
    assert stock.average_cost_per_unit == Decimal("0.009350000000")


def test_insufficient_sale_does_not_mutate_inventory(stock):
    record_purchase(stock=stock, quantity=100, actual_total_cost=Decimal("1"))

    with pytest.raises(ValueError, match="insuffisant"):
        consume_stock(stock=stock, quantity=101)

    assert stock.balance == Decimal("100")
    assert stock.inventory_value == Decimal("1.000000000000")


def test_unconsumed_purchase_can_be_reversed(stock):
    record_purchase(stock=stock, quantity=100, actual_total_cost=Decimal("1"))
    reverse_purchase(stock=stock, quantity=100, actual_total_cost=Decimal("1"))

    assert stock.balance == 0
    assert stock.inventory_value == 0


def test_consumed_purchase_cannot_rewrite_history(stock):
    record_purchase(stock=stock, quantity=100, actual_total_cost=Decimal("1"))
    consume_stock(stock=stock, quantity=50)

    with pytest.raises(ValueError, match="ajustement"):
        reverse_purchase(stock=stock, quantity=100, actual_total_cost=Decimal("1"))
