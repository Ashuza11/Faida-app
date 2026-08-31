from decimal import Decimal

from apps.businesses import create_business
from apps.models import (
    BusinessType,
    NetworkType,
    PriceOperation,
    RoleType,
    User,
)
from apps.pricing import WHOLESALE_SALE_PRICES, calculate_preset_cost


def make_owner(session):
    owner = User(
        username="pricing-owner", phone="+243810008888", role=RoleType.VENDEUR
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    return owner


def test_wholesale_gets_general_sale_choices_for_every_network(session):
    business = create_business(
        owner=make_owner(session),
        name="Wholesale",
        business_type=BusinessType.WHOLESALE,
    )
    session.flush()

    for network in NetworkType:
        values = {
            p.unit_price for p in business.price_presets
            if p.network == network and p.operation == PriceOperation.SALE
        }
        assert values == set(WHOLESALE_SALE_PRICES)


def test_orange_preset_hides_ratio_but_calculates_exactly(session):
    business = create_business(
        owner=make_owner(session),
        name="Wholesale",
        business_type=BusinessType.WHOLESALE,
    )
    orange = next(
        p for p in business.price_presets
        if p.network == NetworkType.ORANGE
        and p.operation == PriceOperation.PURCHASE
    )

    assert orange.label == "Standard Orange"
    assert orange.unit_price == Decimal("0.009389671362")
    assert calculate_preset_cost(orange, 15975) == Decimal("150.000000000000")


def test_airtel_and_africel_standard_costs_use_their_displayed_unit_prices(session):
    business = create_business(
        owner=make_owner(session),
        name="Wholesale references",
        business_type=BusinessType.WHOLESALE,
    )

    expected = {
        NetworkType.AIRTEL: (Decimal("0.00935"), Decimal("935.00000")),
        NetworkType.AFRICEL: (Decimal("0.00940"), Decimal("940.00000")),
    }
    for network, (displayed_price, expected_total) in expected.items():
        preset = next(
            candidate for candidate in business.price_presets
            if candidate.network == network
            and candidate.operation == PriceOperation.PURCHASE
        )
        assert preset.unit_price == displayed_price
        assert preset.ratio_amount is None
        assert preset.ratio_units is None
        assert calculate_preset_cost(preset, 100000) == expected_total


def test_retail_does_not_receive_wholesale_presets(session):
    business = create_business(
        owner=make_owner(session), name="Retail", business_type=BusinessType.RETAIL
    )
    assert business.price_presets == []
