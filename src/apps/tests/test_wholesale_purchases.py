from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.businesses import create_business
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    Client,
    NetworkType,
    PriceOperation,
    RoleType,
    Stock,
    StockPurchase,
    TransactionStatus,
    User,
)
from apps.purchases import (
    build_wholesale_purchase_groups,
    delete_retail_purchase,
    record_retail_purchase,
    record_wholesale_purchase,
    replace_retail_purchase,
    replace_wholesale_purchase,
    reverse_wholesale_purchase,
)
from apps.dates import business_local_date
from apps.sales import record_wholesale_sale
from apps.wholesale_reports import build_wholesale_daily_report


def make_owner(session, suffix):
    owner = User(
        username=f"wholesale-owner-{suffix}",
        phone=f"+243810006{suffix:03d}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    return owner


def approved_wholesale(session, owner, name):
    business = create_business(
        owner=owner,
        name=name,
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    return business


def orange_preset(business):
    return next(
        preset
        for preset in business.price_presets
        if preset.network == NetworkType.ORANGE
        and preset.operation == PriceOperation.PURCHASE
    )


def test_orange_ratio_preserves_exact_reference_cost(session):
    owner = make_owner(session, 1)
    business = approved_wholesale(session, owner, "Exact Orange")

    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.ORANGE,
        quantity=15975,
        preset=orange_preset(business),
    )
    session.flush()

    assert purchase.actual_total_cost == Decimal("150.000000000000")
    assert purchase.total_cost == Decimal("150.000000000000")
    assert purchase.amount_purchased == 15975
    assert purchase.price_preset_id == orange_preset(business).id
    assert purchase.stock_item.balance == Decimal("15975")
    assert purchase.stock_item.inventory_value == Decimal("150.000000000000")


def test_standard_airtel_purchase_uses_displayed_unit_price(session):
    owner = make_owner(session, 31)
    business = approved_wholesale(session, owner, "Exact Airtel")
    preset = next(
        candidate for candidate in business.price_presets
        if candidate.network == NetworkType.AIRTEL
        and candidate.operation == PriceOperation.PURCHASE
    )

    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100000,
        preset=preset,
    )
    session.flush()

    assert preset.unit_price == Decimal("0.009350000000")
    assert preset.ratio_amount is None
    assert preset.ratio_units is None
    assert purchase.actual_total_cost == Decimal("935.000000000000")
    assert purchase.stock_item.inventory_value == Decimal("935.000000000000")


def test_custom_cost_updates_wholesale_weighted_inventory(session):
    owner = make_owner(session, 2)
    business = approved_wholesale(session, owner, "Custom Cost")

    first = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=10000,
        custom_unit_cost=Decimal("0.00935"),
    )
    second = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=10000,
        custom_unit_cost=Decimal("0.01000"),
    )
    session.flush()

    stock = second.stock_item
    assert first.actual_total_cost == Decimal("93.500000000000")
    assert stock.balance == Decimal("20000")
    assert stock.inventory_value == Decimal("193.500000000000")
    assert stock.average_cost_per_unit == Decimal("0.009675000000")


def test_custom_total_derives_exact_wholesale_unit_cost(session):
    owner = make_owner(session, 201)
    business = approved_wholesale(session, owner, "Custom Total")

    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=10650,
        custom_total_cost=Decimal("100.00"),
    )
    session.flush()

    assert purchase.actual_total_cost == Decimal("100.000000000000")
    assert purchase.buying_price_at_purchase == Decimal("0.009389671362")
    assert purchase.stock_item.inventory_value == Decimal("100.000000000000")


def test_wholesale_purchase_rejects_total_entered_as_unit_cost(session):
    owner = make_owner(session, 202)
    business = approved_wholesale(session, owner, "Invalid Cost")

    with pytest.raises(ValueError, match="semble incorrect"):
        record_wholesale_purchase(
            business=business,
            purchased_by=owner,
            network=NetworkType.AIRTEL,
            quantity=10650,
            custom_unit_cost=Decimal("100.00"),
        )

    assert Stock.query.filter_by(business_id=business.id).count() == 0


def test_wholesale_purchase_reversal_preserves_audit_and_inventory(session):
    owner = make_owner(session, 21)
    business = approved_wholesale(session, owner, "Purchase reversal")
    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=10000,
        custom_unit_cost=Decimal("0.00935"),
        purchase_date=date.today(),
    )
    session.flush()

    reverse_wholesale_purchase(
        purchase=purchase,
        business=business,
        reversed_by=owner,
        reason="Coût incorrect",
    )
    session.flush()

    assert purchase.status == TransactionStatus.REVERSED
    assert purchase.reversal_reason == "Coût incorrect"
    assert purchase.reversed_by_id == owner.id
    assert purchase.stock_item.balance == 0
    assert purchase.stock_item.inventory_value == 0
    report = build_wholesale_daily_report(
        business=business, target_date=date.today()
    )
    assert report["totals"]["purchased"] == 0
    assert report["totals"]["purchase_cost"] == 0


def test_wholesale_purchase_reversal_rejects_possibly_consumed_stock(session):
    owner = make_owner(session, 22)
    business = approved_wholesale(session, owner, "Consumed purchase")
    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=10000,
        custom_unit_cost=Decimal("0.00935"),
        purchase_date=date.today(),
    )
    client = Client(name="Retailer", vendeur_id=owner.id, business_id=business.id)
    session.add(client)
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=100,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()

    with pytest.raises(ValueError, match="ventes plus récentes"):
        reverse_wholesale_purchase(
            purchase=purchase,
            business=business,
            reversed_by=owner,
            reason="Coût incorrect",
        )

    assert purchase.status == TransactionStatus.ACTIVE


def test_purchase_rejects_preset_from_another_business(session):
    first_owner = make_owner(session, 3)
    second_owner = make_owner(session, 4)
    first_business = approved_wholesale(session, first_owner, "First")
    second_business = approved_wholesale(session, second_owner, "Second")

    with pytest.raises(ValueError, match="n'est plus disponible"):
        record_wholesale_purchase(
            business=first_business,
            purchased_by=first_owner,
            network=NetworkType.ORANGE,
            quantity=10650,
            preset=orange_preset(second_business),
        )

    assert Stock.query.filter_by(business_id=first_business.id).count() == 0


def test_pending_wholesale_cannot_record_purchase(session):
    owner = make_owner(session, 5)
    business = create_business(
        owner=owner, name="Pending", business_type=BusinessType.WHOLESALE
    )
    session.flush()

    with pytest.raises(PermissionError, match="pas encore approuvé"):
        record_wholesale_purchase(
            business=business,
            purchased_by=owner,
            network=NetworkType.AIRTEL,
            quantity=10000,
            custom_unit_cost=Decimal("0.00935"),
        )


def test_wholesale_purchase_route_records_selected_preset(app, session):
    owner = make_owner(session, 6)
    business = approved_wholesale(session, owner, "Route Purchase")
    preset = orange_preset(business)
    session.commit()
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = client.post(
        "/businesses/wholesale/purchases",
        data={
            "network": NetworkType.ORANGE.name,
            "quantity": "10650",
            "purchase_date": "2026-08-18",
            "price_choice": f"preset:{preset.id}",
        },
    )

    assert response.status_code == 302
    assert response.location.endswith(
        "/businesses/wholesale/purchases?date=2026-08-18"
    )
    purchase = StockPurchase.query.one()
    assert purchase.price_preset_id == preset.id
    assert purchase.actual_total_cost == Decimal("100.000000000000")
    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.ORANGE
    ).one()
    assert stock.balance == Decimal("10650")
    assert stock.inventory_value == Decimal("100.000000000000")

    page = client.get(response.location)
    assert b"Annuler achat" in page.data
    assert "retirera ses unités et son coût".encode() in page.data


def test_wholesale_purchase_can_be_corrected_before_stock_is_sold(session):
    owner = make_owner(session, 61)
    business = approved_wholesale(session, owner, "Correct purchase")
    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.00935"),
    )
    session.flush()
    purchase_id = purchase.id

    replace_wholesale_purchase(
        purchase=purchase,
        business=business,
        updated_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1200,
        custom_unit_cost=Decimal("0.00940"),
        purchase_date=date.today(),
    )
    session.flush()

    assert purchase.id == purchase_id
    assert StockPurchase.query.count() == 1
    assert purchase.amount_purchased == 1200
    assert purchase.actual_total_cost == Decimal("11.280000000000")
    assert purchase.stock_item.balance == 1200
    assert purchase.stock_item.inventory_value == Decimal("11.280000000000")


def test_wholesale_purchase_edit_is_blocked_after_later_sale(session):
    owner = make_owner(session, 62)
    business = approved_wholesale(session, owner, "Consumed correction")
    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.00935"),
    )
    retailer = Client(name="Retailer", vendeur_id=owner.id, business_id=business.id)
    session.add(retailer)
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=retailer,
        network=NetworkType.AIRTEL,
        quantity=100,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()

    with pytest.raises(ValueError, match="ventes plus récentes"):
        replace_wholesale_purchase(
            purchase=purchase,
            business=business,
            updated_by=owner,
            network=NetworkType.AIRTEL,
            quantity=1200,
            custom_unit_cost=Decimal("0.00940"),
        )


def test_same_day_sale_recorded_before_purchase_does_not_block_edit(session):
    owner = make_owner(session, 64)
    business = approved_wholesale(session, owner, "Same-day ordering")
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=2000,
        custom_unit_cost=Decimal("0.00900"),
    )
    retailer = Client(name="Retailer", vendeur_id=owner.id, business_id=business.id)
    session.add(retailer)
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=retailer,
        network=NetworkType.AIRTEL,
        quantity=100,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()
    latest_purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.00935"),
        purchase_date=date.today(),
    )
    session.flush()

    replace_wholesale_purchase(
        purchase=latest_purchase,
        business=business,
        updated_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1200,
        custom_unit_cost=Decimal("0.00940"),
    )
    session.flush()

    assert latest_purchase.amount_purchased == 1200
    assert latest_purchase.actual_total_cost == Decimal("11.280000000000")


def test_wholesale_purchase_edit_route_updates_existing_record(app, session):
    owner = make_owner(session, 63)
    business = approved_wholesale(session, owner, "Route correction")
    purchase = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=1000, custom_unit_cost=Decimal("0.00935"),
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.post(
        f"/businesses/wholesale/purchases/{purchase.id}/edit",
        data={
            "network": NetworkType.AIRTEL.name,
            "quantity": "1200",
            "purchase_date": date.today().isoformat(),
            "price_choice": "custom",
            "custom_unit_cost": "0.00940",
        },
    )

    assert response.status_code == 302
    session.refresh(purchase)
    assert StockPurchase.query.count() == 1
    assert purchase.amount_purchased == 1200
    assert purchase.stock_item.balance == 1200


def test_wholesale_purchase_route_accepts_custom_total_paid(app, session):
    owner = make_owner(session, 631)
    business = approved_wholesale(session, owner, "Route custom total")
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    page = browser.get("/businesses/wholesale/purchases")
    assert b"Montant total pay\xc3\xa9 ($)" in page.data
    assert b"Prix personnalis\xc3\xa9 par unit\xc3\xa9 ($)" not in page.data

    response = browser.post(
        "/businesses/wholesale/purchases",
        data={
            "network": NetworkType.AIRTEL.name,
            "quantity": "10650",
            "purchase_date": date.today().isoformat(),
            "price_choice": "custom",
            "custom_total_cost": "100.00",
        },
    )

    assert response.status_code == 302
    purchase = StockPurchase.query.one()
    assert purchase.actual_total_cost == Decimal("100.000000000000")
    assert purchase.buying_price_at_purchase == Decimal("0.009389671362")


def test_wholesale_purchase_groups_sum_active_rows_by_network(session):
    owner = make_owner(session, 632)
    business = approved_wholesale(session, owner, "Grouped purchases")
    first = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=1000, custom_unit_cost=Decimal("0.00935"),
    )
    second = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=500, custom_unit_cost=Decimal("0.00935"),
    )
    reversed_purchase = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.ORANGE,
        quantity=100, custom_unit_cost=Decimal("0.00950"),
    )
    session.flush()
    reverse_wholesale_purchase(
        purchase=reversed_purchase,
        business=business,
        reversed_by=owner,
        reason="Saisie incorrecte",
    )

    groups = build_wholesale_purchase_groups(
        [reversed_purchase, second, first]
    )

    assert len(groups) == 2
    airtel = next(group for group in groups if group["network"] == NetworkType.AIRTEL)
    assert airtel["purchases"] == [second, first]
    assert airtel["active_purchase_count"] == 2
    assert airtel["total_units"] == 1500
    assert airtel["total_cost"] == Decimal("14.025000000000")
    assert airtel["display_total_cost"] == Decimal("14.03")
    assert airtel["average_unit_cost"] == Decimal("0.009350000")
    orange = next(group for group in groups if group["network"] == NetworkType.ORANGE)
    assert orange["active_purchase_count"] == 0
    assert orange["total_units"] == 0
    assert orange["total_cost"] == 0


def test_wholesale_purchases_page_groups_and_filters_by_date(app, session):
    owner = make_owner(session, 633)
    business = approved_wholesale(session, owner, "Daily purchases")
    today = business_local_date()
    yesterday = today - timedelta(days=1)
    first = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=1000, custom_unit_cost=Decimal("0.00935"),
        purchase_date=today,
    )
    second = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=500, custom_unit_cost=Decimal("0.00935"),
        purchase_date=today,
    )
    old = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.ORANGE,
        quantity=100, custom_unit_cost=Decimal("0.00950"),
        purchase_date=yesterday,
    )
    other_owner = make_owner(session, 634)
    other_business = approved_wholesale(session, other_owner, "Other purchases")
    other = record_wholesale_purchase(
        business=other_business, purchased_by=other_owner,
        network=NetworkType.AIRTEL, quantity=200,
        custom_unit_cost=Decimal("0.00935"), purchase_date=today,
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    current_page = browser.get("/businesses/wholesale/purchases")
    current_html = current_page.data.decode()
    assert current_page.status_code == 200
    assert current_html.count('data-purchase-group="AIRTEL"') == 1
    assert "2 achats" in current_html
    assert ">1500</strong>" in current_html
    assert ">$14.03</strong>" in current_html
    assert f'data-purchase-id="{first.id}"' in current_html
    assert f'data-purchase-id="{second.id}"' in current_html
    assert f'data-purchase-id="{old.id}"' not in current_html
    assert f'data-purchase-id="{other.id}"' not in current_html

    old_page = browser.get(
        f"/businesses/wholesale/purchases?date={yesterday.isoformat()}"
    )
    old_html = old_page.data.decode()
    assert old_page.status_code == 200
    assert f'data-purchase-id="{old.id}"' in old_html
    assert f'data-purchase-id="{first.id}"' not in old_html


def test_retail_purchase_replace_and_delete_preserve_inventory(session):
    owner = make_owner(session, 7)
    retail = create_business(
        owner=owner, name="Retail Service", business_type=BusinessType.RETAIL
    )
    session.flush()
    purchase = record_retail_purchase(
        business=retail,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100,
        unit_cost=Decimal("20"),
        intended_selling_price=Decimal("22.5"),
    )
    session.flush()

    replace_retail_purchase(
        purchase=purchase,
        business=retail,
        updated_by=owner,
        network=NetworkType.ORANGE,
        quantity=200,
        unit_cost=Decimal("21"),
        intended_selling_price=Decimal("23"),
    )
    session.flush()

    airtel = Stock.query.filter_by(
        business_id=retail.id, network=NetworkType.AIRTEL
    ).one()
    orange = Stock.query.filter_by(
        business_id=retail.id, network=NetworkType.ORANGE
    ).one()
    assert airtel.balance == 0
    assert orange.balance == 200
    assert purchase.stock_item_id == orange.id
    assert purchase.actual_total_cost == Decimal("4200.000000000000")

    delete_retail_purchase(
        purchase=purchase, business=retail, deleted_by=owner
    )
    session.flush()
    assert orange.balance == 0
    assert StockPurchase.query.count() == 0
