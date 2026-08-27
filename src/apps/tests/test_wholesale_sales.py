from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.businesses import create_business
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    CashInflow,
    Client,
    NetworkType,
    PaymentEvent,
    PriceOperation,
    RoleType,
    Sale,
    Stock,
    TransactionStatus,
    User,
)
from apps.purchases import record_wholesale_purchase
from apps.payments import collect_client_debt, reverse_payment_event
from apps.sales import (
    build_wholesale_sale_groups,
    record_wholesale_sale,
    replace_unpaid_wholesale_sale,
    reverse_unpaid_wholesale_sale,
)
from apps.wholesale_reports import build_wholesale_daily_report


def setup_wholesale(session, suffix=1):
    owner = User(
        username=f"sale-owner-{suffix}",
        phone=f"+243810004{suffix:03d}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner,
        name=f"Wholesale {suffix}",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    client = Client(
        name="Retailer", vendeur_id=owner.id, business_id=business.id
    )
    session.add(client)
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=2000,
        custom_unit_cost=Decimal("0.00900"),
    )
    session.flush()
    preset = next(
        candidate
        for candidate in business.price_presets
        if candidate.network == NetworkType.AIRTEL
        and candidate.operation == PriceOperation.SALE
        and candidate.unit_price == Decimal("0.00940")
    )
    return owner, business, client, preset


def test_wholesale_sale_preserves_price_cost_and_margin(session):
    owner, business, client, preset = setup_wholesale(session)

    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=1000,
        cash_received=Decimal("9.40"),
        sale_date=date.today(),
        preset=preset,
    )
    session.flush()

    item = sale.sale_items[0]
    assert sale.total_amount_due == Decimal("9.40")
    assert sale.cash_paid == Decimal("9.40")
    assert sale.debt_amount == 0
    assert item.price_per_unit_applied == Decimal("0.00940")
    assert item.price_preset_id == preset.id
    assert item.cost_total == Decimal("9.000000000000")
    assert item.margin_amount == Decimal("0.400000000000")
    assert item.is_cost_estimated is False
    assert Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one().balance == 1000
    assert CashInflow.query.filter_by(sale_id=sale.id).one().amount == Decimal("9.40")


def test_wholesale_sale_groups_use_client_identity_and_business_date(session):
    owner, business, first_client, _ = setup_wholesale(session, suffix=501)
    second_client = Client(
        name=first_client.name,
        vendeur_id=owner.id,
        business_id=business.id,
    )
    session.add(second_client)
    session.flush()
    today = date.today()
    first = record_wholesale_sale(
        business=business, sold_by=owner, client=first_client,
        network=NetworkType.AIRTEL, quantity=300, cash_received=0,
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )
    second = record_wholesale_sale(
        business=business, sold_by=owner, client=first_client,
        network=NetworkType.AIRTEL, quantity=200, cash_received=Decimal("1.00"),
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )
    next_day = record_wholesale_sale(
        business=business, sold_by=owner, client=first_client,
        network=NetworkType.AIRTEL, quantity=100, cash_received=0,
        sale_date=today + timedelta(days=1), custom_unit_price=Decimal("0.01000"),
    )
    namesake = record_wholesale_sale(
        business=business, sold_by=owner, client=second_client,
        network=NetworkType.AIRTEL, quantity=100, cash_received=0,
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )

    groups = build_wholesale_sale_groups([namesake, next_day, second, first])

    assert len(groups) == 3
    assert {
        group["client_id"] for group in groups if group["sale_date"] == today
    } == {first_client.id, second_client.id}
    same_client_day = next(
        group for group in groups
        if group["client_id"] == first_client.id and group["sale_date"] == today
    )
    assert same_client_day["sales"] == [second, first]
    assert same_client_day["active_sale_count"] == 2
    assert same_client_day["total_amount_due"] == Decimal("5.00")
    assert same_client_day["cash_paid"] == Decimal("1.00")
    assert same_client_day["debt_amount"] == Decimal("4.00")
    assert same_client_day["item_groups"] == [{
        "network": NetworkType.AIRTEL,
        "price_per_unit": Decimal("0.010000000000"),
        "quantity": 500,
        "subtotal": Decimal("5.00"),
    }]


def test_wholesale_sales_page_renders_one_summary_per_client_and_day(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=502)
    first = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    second = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get("/businesses/wholesale/sales")
    page = response.data.decode()
    group_key = f'c:{retailer.id}:{date.today().isoformat()}'

    assert response.status_code == 200
    assert page.count(f'data-client-group="{group_key}"') == 1
    assert "2 ventes" in page
    assert "Airtel</strong>: 1000 @ $0.00940" in page
    assert "<small>Total</small><strong>$9.40</strong>" in page
    assert f'data-sale-id="{first.id}"' in page
    assert f'data-sale-id="{second.id}"' in page
    assert f"/businesses/wholesale/sales/{first.id}/edit" in page
    assert f"/businesses/wholesale/sales/{second.id}/edit" in page


def test_wholesale_cash_pays_old_debt_before_current_sale(session):
    owner, business, client, _ = setup_wholesale(session, suffix=2)
    first = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    second = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=Decimal("7.00"),
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()

    assert first.debt_amount == 0
    assert second.cash_paid == Decimal("2.00")
    assert second.debt_amount == Decimal("3.00")
    assert CashInflow.query.filter_by(sale_id=first.id).one().amount == Decimal("5.00")
    assert CashInflow.query.filter_by(sale_id=second.id).one().amount == Decimal("2.00")
    event = PaymentEvent.query.one()
    assert event.amount == Decimal("7.00")
    assert event.source_sale_id == second.id
    assert {allocation.sale_id for allocation in event.allocations} == {
        first.id,
        second.id,
    }


def test_payment_reversal_restores_every_allocated_debt_and_reports(session):
    owner, business, client, _ = setup_wholesale(session, suffix=23)
    first = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    second = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=Decimal("7.00"),
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()
    event = PaymentEvent.query.one()

    reverse_payment_event(
        payment_event=event,
        business=business,
        reversed_by=owner,
        reason="Montant incorrect",
    )
    session.flush()

    assert event.status == TransactionStatus.REVERSED
    assert event.reversal_reason == "Montant incorrect"
    assert {allocation.status for allocation in event.allocations} == {
        TransactionStatus.REVERSED
    }
    assert first.cash_paid == 0
    assert first.debt_amount == Decimal("5.00")
    assert second.cash_paid == 0
    assert second.initial_cash_paid == 0
    assert second.debt_amount == Decimal("5.00")
    report = build_wholesale_daily_report(
        business=business, target_date=date.today()
    )
    assert report["totals"]["cash_collected"] == 0
    assert report["totals"]["old_debt_collected"] == 0
    assert report["totals"]["remaining_debt"] == Decimal("10.00")

    reverse_unpaid_wholesale_sale(
        sale=second,
        business=business,
        reversed_by=owner,
        reason="Quantité incorrecte",
    )
    assert second.status == TransactionStatus.REVERSED


def test_payment_reversal_rejects_another_business(session):
    owner, business, client, _ = setup_wholesale(session, suffix=24)
    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=Decimal("1.00"),
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()
    event = PaymentEvent.query.filter_by(source_sale_id=sale.id).one()
    other_owner, other_business, _, _ = setup_wholesale(session, suffix=25)

    with pytest.raises(PermissionError, match="autre mode"):
        reverse_payment_event(
            payment_event=event,
            business=other_business,
            reversed_by=other_owner,
            reason="Montant incorrect",
        )

    assert event.status == TransactionStatus.ACTIVE


def test_owner_can_reverse_payment_from_client_page(app, session):
    owner, business, client_record, _ = setup_wholesale(session, suffix=26)
    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client_record,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=Decimal("1.00"),
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.commit()
    event = PaymentEvent.query.filter_by(source_sale_id=sale.id).one()
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = client.post(
        f"/businesses/wholesale/payments/{event.id}/reverse",
        data={"reason": "Montant incorrect"},
    )

    assert response.status_code == 302
    session.refresh(event)
    session.refresh(sale)
    assert event.status == TransactionStatus.REVERSED
    assert sale.cash_paid == 0
    assert sale.debt_amount == Decimal("5.00")


def test_unpaid_wholesale_sale_reversal_restores_exact_inventory(session):
    owner, business, client, _ = setup_wholesale(session, suffix=21)
    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    original_balance = stock.balance
    original_value = stock.inventory_value
    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()

    reverse_unpaid_wholesale_sale(
        sale=sale,
        business=business,
        reversed_by=owner,
        reason="Quantité incorrecte",
    )
    session.flush()

    assert sale.status == TransactionStatus.REVERSED
    assert sale.reversal_reason == "Quantité incorrecte"
    assert sale.reversed_by_id == owner.id
    assert stock.balance == original_balance
    assert stock.inventory_value == original_value
    report = build_wholesale_daily_report(
        business=business, target_date=date.today()
    )
    assert report["totals"]["sold"] == 0
    assert report["totals"]["remaining_debt"] == 0


def test_paid_wholesale_sale_must_not_be_reversed(session):
    owner, business, client, _ = setup_wholesale(session, suffix=22)
    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=Decimal("1.00"),
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()

    with pytest.raises(ValueError, match="paiement"):
        reverse_unpaid_wholesale_sale(
            sale=sale,
            business=business,
            reversed_by=owner,
            reason="Quantité incorrecte",
        )

    assert sale.status == TransactionStatus.ACTIVE


def test_wholesale_sale_rejects_another_business_client(session):
    owner, business, _, preset = setup_wholesale(session, suffix=3)
    other_owner, other_business, other_client, _ = setup_wholesale(session, suffix=4)

    with pytest.raises(ValueError, match="autre mode"):
        record_wholesale_sale(
            business=business,
            sold_by=owner,
            client=other_client,
            network=NetworkType.AIRTEL,
            quantity=100,
            cash_received=0,
            sale_date=date.today(),
            preset=preset,
        )

    assert other_owner.id != owner.id
    assert other_business.id != business.id
    assert Sale.query.count() == 0


def test_wholesale_sales_page_records_new_retailer(app, session):
    owner, business, _, preset = setup_wholesale(session, suffix=5)
    session.commit()
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = client.post(
        "/businesses/wholesale/sales",
        data={
            "client_id": "new",
            "new_client_name": "Boutique Nouvelle",
            "sale_items-0-network": NetworkType.AIRTEL.name,
            "sale_items-0-quantity": "1000",
            "sale_items-0-price_choice": f"preset:{preset.id}",
            "sale_date": date.today().isoformat(),
            "cash_received": "5.00",
        },
    )

    assert response.status_code == 302
    new_client = Client.query.filter_by(
        business_id=business.id, name="Boutique Nouvelle"
    ).one()
    sale = Sale.query.filter_by(business_id=business.id, client_id=new_client.id).one()
    assert sale.total_amount_due == Decimal("9.40")
    assert sale.cash_paid == Decimal("5.00")
    assert sale.debt_amount == Decimal("4.40")

    page = client.get("/businesses/wholesale/sales")
    assert page.status_code == 200
    assert b"Marge du jour par prix" in page.data
    assert b"$0.40" in page.data
    assert b"$0.21" in page.data

    report_page = client.get("/businesses/wholesale/report")
    assert report_page.status_code == 200
    assert b"$0.40" in report_page.data
    assert b"$0.21" in report_page.data


def test_wholesale_sale_form_starts_with_one_dynamic_network_row(app, session):
    owner, business, _, _ = setup_wholesale(session, suffix=57)
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get("/businesses/wholesale/sales")

    assert response.status_code == 200
    page = response.data.decode()
    assert page.count('class="border rounded p-3 mb-3 wholesale-sale-item"') == 1
    assert 'id="addWholesaleSaleItem"' in page
    assert "rows.length >= 4" in page


def test_wholesale_sale_records_multiple_networks_on_one_invoice(session):
    owner, business, retailer, airtel_preset = setup_wholesale(session, suffix=51)
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.ORANGE,
        quantity=2000,
        custom_unit_cost=Decimal("0.00900"),
    )
    orange_preset = next(
        preset for preset in business.price_presets
        if preset.network == NetworkType.ORANGE
        and preset.operation == PriceOperation.SALE
    )

    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=retailer,
        cash_received=0,
        sale_date=date.today(),
        items=[
            {"network": NetworkType.AIRTEL, "quantity": 500, "preset": airtel_preset},
            {"network": NetworkType.ORANGE, "quantity": 750, "preset": orange_preset},
        ],
    )
    session.flush()

    assert len(sale.sale_items) == 2
    assert {item.network for item in sale.sale_items} == {
        NetworkType.AIRTEL, NetworkType.ORANGE
    }
    assert Sale.query.count() == 1
    assert Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one().balance == 1500
    assert Stock.query.filter_by(
        business_id=business.id, network=NetworkType.ORANGE
    ).one().balance == 1250


def test_retyping_existing_wholesale_client_name_reuses_client(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=52)
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    for _ in range(2):
        response = browser.post(
            "/businesses/wholesale/sales",
            data={
                "client_id": "new",
                "new_client_name": "  retailer  ",
                "sale_items-0-network": NetworkType.AIRTEL.name,
                "sale_items-0-quantity": "500",
                "sale_items-0-price_choice": f"preset:{preset.id}",
                "sale_date": date.today().isoformat(),
                "cash_received": "0",
            },
        )
        assert response.status_code == 302

    assert Client.query.filter_by(business_id=business.id).count() == 1
    assert Sale.query.filter_by(client_id=retailer.id).count() == 2


def test_unpaid_wholesale_sale_can_be_corrected(session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=53)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    session.flush()

    replace_unpaid_wholesale_sale(
        sale=sale,
        business=business,
        updated_by=owner,
        client=retailer,
        sale_date=date.today(),
        items=[{
            "network": NetworkType.AIRTEL,
            "quantity": 300,
            "custom_unit_price": Decimal("0.01000"),
        }],
    )
    session.flush()

    assert sale.id is not None
    assert len(sale.sale_items) == 1
    assert sale.sale_items[0].quantity == 300
    assert sale.total_amount_due == Decimal("3.00")
    assert sale.debt_amount == Decimal("3.00")
    assert Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one().balance == 1700


def test_paid_wholesale_sale_cannot_be_edited(session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=54)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=Decimal("1"),
        sale_date=date.today(), preset=preset,
    )

    with pytest.raises(ValueError, match="paiement"):
        replace_unpaid_wholesale_sale(
            sale=sale, business=business, updated_by=owner, client=retailer,
            sale_date=date.today(), items=[{
                "network": NetworkType.AIRTEL,
                "quantity": 300,
                "custom_unit_price": Decimal("0.01000"),
            }],
        )


def test_wholesale_sales_page_explains_active_and_redirected_payments(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=540)
    first_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    second_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=Decimal("1"),
        sale_date=date.today(), preset=preset,
    )
    session.commit()
    assert first_sale.cash_paid == Decimal("1.000000000000")
    assert second_sale.cash_paid == 0

    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    page = browser.get("/businesses/wholesale/sales")

    assert page.status_code == 200
    assert b"Paiement actif" in page.data
    assert b"Re\xc3\xa7u li\xc3\xa9" in page.data
    assert b"Voir les paiements" in page.data
    assert b"Paiement \xc3\xa0 annuler d'abord" not in page.data


def test_wholesale_sale_edit_route_updates_invoice(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=55)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.post(
        f"/businesses/wholesale/sales/{sale.id}/edit",
        data={
            "client_id": str(retailer.id),
            "sale_items-0-network": NetworkType.AIRTEL.name,
            "sale_items-0-quantity": "300",
            "sale_items-0-price_choice": "custom",
            "sale_items-0-custom_unit_price": "0.01000",
            "sale_date": date.today().isoformat(),
            "cash_received": "0",
        },
    )

    assert response.status_code == 302
    session.refresh(sale)
    assert Sale.query.count() == 1
    assert sale.sale_items[0].quantity == 300
    assert sale.total_amount_due == Decimal("3.00")


def test_sale_edit_is_blocked_after_later_purchase_changes_cost(session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=56)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    session.flush()
    record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=1000, custom_unit_cost=Decimal("0.01200"),
    )
    session.flush()

    with pytest.raises(ValueError, match="achat plus récent"):
        replace_unpaid_wholesale_sale(
            sale=sale, business=business, updated_by=owner, client=retailer,
            sale_date=date.today(), items=[{
                "network": NetworkType.AIRTEL,
                "quantity": 300,
                "custom_unit_price": Decimal("0.01000"),
            }],
        )


def test_debt_collection_is_oldest_first_and_keeps_payment_date(session):
    owner, business, client, _ = setup_wholesale(session, suffix=6)
    oldest = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today() - timedelta(days=2),
        custom_unit_price=Decimal("0.01000"),
    )
    newer = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today() - timedelta(days=1),
        custom_unit_price=Decimal("0.01000"),
    )
    selected_payment_date = date.today() - timedelta(days=3)

    collect_client_debt(
        business=business,
        client=client,
        amount=Decimal("7.00"),
        recorded_by=owner,
        payment_date=selected_payment_date,
        description="Paiement test",
    )
    session.flush()

    assert oldest.debt_amount == 0
    assert newer.debt_amount == Decimal("3.00")
    payments = CashInflow.query.order_by(CashInflow.id).all()
    assert [payment.amount for payment in payments] == [Decimal("5.00"), Decimal("2.00")]
    assert {payment.payment_date for payment in payments} == {selected_payment_date}
    assert {payment.description for payment in payments} == {"Paiement test"}


def test_debt_collection_rejects_excess_and_cross_business_client(session):
    owner, business, client, _ = setup_wholesale(session, suffix=7)
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    _, other_business, other_client, _ = setup_wholesale(session, suffix=8)

    with pytest.raises(ValueError, match="dépasse"):
        collect_client_debt(
            business=business,
            client=client,
            amount=Decimal("5.01"),
            recorded_by=owner,
            payment_date=date.today(),
        )
    with pytest.raises(PermissionError, match="autre mode"):
        collect_client_debt(
            business=business,
            client=other_client,
            amount=Decimal("1.00"),
            recorded_by=owner,
            payment_date=date.today(),
        )
    assert other_business.id != business.id


def test_duplicate_retailer_names_have_distinct_debt_pages(app, session):
    owner, business, first_client, _ = setup_wholesale(session, suffix=9)
    second_client = Client(
        name=first_client.name,
        vendeur_id=owner.id,
        business_id=business.id,
    )
    session.add(second_client)
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=first_client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=0,
        sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.commit()
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    listing = client.get("/businesses/wholesale/clients")
    assert listing.status_code == 200
    assert f"Grossiste · {business.name}".encode() in listing.data
    assert "Détaillants ·".encode() not in listing.data
    assert listing.data.count(first_client.name.encode()) == 2
    assert f"Client #{first_client.id}".encode() in listing.data
    assert f"Client #{second_client.id}".encode() in listing.data

    payment = client.post(
        f"/businesses/wholesale/clients/{first_client.id}",
        data={
            "amount": "2.00",
            "payment_date": date.today().isoformat(),
            "description": "Partial",
        },
    )
    assert payment.status_code == 302
    assert Sale.query.filter_by(client_id=first_client.id).one().debt_amount == Decimal("3.00")
    assert Sale.query.filter_by(client_id=second_client.id).count() == 0
