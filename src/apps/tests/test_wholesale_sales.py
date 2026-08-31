from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.businesses import create_business
from apps.dates import business_local_date
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
from apps.payments import (
    collect_client_debt,
    correct_wholesale_payment_event,
    reverse_payment_event,
)
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


def test_wholesale_sale_rejects_abnormal_stock_cost_before_consumption(session):
    owner, business, client, preset = setup_wholesale(session, suffix=502)
    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    stock.average_cost_per_unit = Decimal("100")
    stock.inventory_value = stock.balance * Decimal("100")
    original_state = (stock.balance, stock.inventory_value)

    with pytest.raises(ValueError, match="semble incorrect"):
        record_wholesale_sale(
            business=business,
            sold_by=owner,
            client=client,
            network=NetworkType.AIRTEL,
            quantity=100,
            cash_received=0,
            sale_date=date.today(),
            preset=preset,
        )

    assert (stock.balance, stock.inventory_value) == original_state
    assert Sale.query.count() == 0


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
        "display_price": "0.01000",
        "quantity": 500,
        "subtotal": Decimal("5.00"),
    }]


def test_wholesale_sales_page_renders_one_summary_per_client_and_day(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=502)
    today = business_local_date()
    first = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=today, preset=preset,
    )
    second = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=today, preset=preset,
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get("/businesses/wholesale/sales")
    page = response.data.decode()
    group_key = f'c:{retailer.id}:{today.isoformat()}'

    assert response.status_code == 200
    assert page.count(f'data-client-group="{group_key}"') == 1
    assert "2 ventes" in page
    assert "Airtel</strong>: 1000 @ $0.00940 = $9.40" in page
    assert "<small>Total ventes</small><strong>$9.40</strong>" in page
    assert f'data-sale-id="{first.id}"' in page
    assert f'data-sale-id="{second.id}"' in page
    assert f"/businesses/wholesale/sales/{first.id}/edit" in page
    assert f"/businesses/wholesale/sales/{second.id}/edit" in page


def test_wholesale_sales_page_shows_exact_price_and_reconciled_subtotal(
    app, session
):
    owner, business, retailer, _ = setup_wholesale(session, suffix=507)
    today = business_local_date()
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=2000, cash_received=0,
        sale_date=today, custom_unit_price=Decimal("0.009455"),
    )
    session.commit()
    assert sale.total_amount_due == Decimal("18.91")

    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    page = browser.get("/businesses/wholesale/sales")
    html = page.data.decode()
    assert page.status_code == 200
    assert "Airtel</strong>: 2000 @ $0.009455 = $18.91" in html
    assert "Airtel: 2000 @ $0.009455 = $18.91" in html


def test_wholesale_sales_page_defaults_to_today_and_filters_by_date(app, session):
    owner, business, retailer, _ = setup_wholesale(session, suffix=503)
    today = business_local_date()
    yesterday = today - timedelta(days=1)
    today_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=100, cash_received=0,
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )
    yesterday_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=200, cash_received=0,
        sale_date=yesterday, custom_unit_price=Decimal("0.01100"),
    )
    other_owner, other_business, other_client, _ = setup_wholesale(
        session, suffix=504
    )
    other_sale = record_wholesale_sale(
        business=other_business, sold_by=other_owner, client=other_client,
        network=NetworkType.AIRTEL, quantity=100, cash_received=0,
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    current_page = browser.get("/businesses/wholesale/sales")
    current_html = current_page.data.decode()
    assert current_page.status_code == 200
    assert f'data-sale-id="{today_sale.id}"' in current_html
    assert f'data-sale-id="{yesterday_sale.id}"' not in current_html
    assert f'data-sale-id="{other_sale.id}"' not in current_html
    assert f'value="{today.isoformat()}"' in current_html
    assert "Marge des ventes du jour" in current_html
    assert "$0.10" in current_html

    old_page = browser.get(
        "/businesses/wholesale/sales", query_string={"date": yesterday.isoformat()}
    )
    old_html = old_page.data.decode()
    assert old_page.status_code == 200
    assert f'data-sale-id="{yesterday_sale.id}"' in old_html
    assert f'data-sale-id="{today_sale.id}"' not in old_html
    assert f'value="{yesterday.isoformat()}"' in old_html
    assert f"Marge des ventes du {yesterday.strftime('%d/%m/%Y')}" in old_html
    assert "$0.40" in old_html

    invalid_page = browser.get(
        "/businesses/wholesale/sales", query_string={"date": "incorrecte"}
    )
    invalid_html = invalid_page.data.decode()
    assert invalid_page.status_code == 200
    assert f'data-sale-id="{today_sale.id}"' in invalid_html
    assert f'data-sale-id="{yesterday_sale.id}"' not in invalid_html
    assert f'value="{today.isoformat()}"' in invalid_html


def test_wholesale_sales_page_reconciles_receipts_redirected_to_old_debt(
    app, session
):
    owner, business, retailer, _ = setup_wholesale(session, suffix=505)
    today = business_local_date()
    first_old_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=Decimal("4.00"),
        sale_date=today - timedelta(days=2),
        custom_unit_price=Decimal("0.01000"),
    )
    second_old_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=today - timedelta(days=1),
        custom_unit_price=Decimal("0.01000"),
    )
    first_new_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=100, cash_received=Decimal("3.00"),
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )
    second_new_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=100, cash_received=Decimal("3.00"),
        sale_date=today, custom_unit_price=Decimal("0.01000"),
    )
    session.commit()
    assert first_old_sale.cash_paid == Decimal("5.00")
    assert second_old_sale.cash_paid == Decimal("5.00")
    assert first_new_sale.cash_paid == 0
    assert second_new_sale.cash_paid == 0

    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    page = browser.get("/businesses/wholesale/sales")
    html = page.data.decode()
    assert page.status_code == 200
    assert "<small>Reçu lors des ventes</small><strong class=\"text-info\">$6.00" in html
    assert "<small>Payé sur ces ventes</small><strong class=\"text-success\">$0.00" in html
    assert "$6.00 reçu ici et appliqué aux anciennes dettes" in html
    assert html.count("Reçu ici $3.00") == 2
    assert html.count("$3.00 appliqué aux anciennes dettes") == 2

    client_page = browser.get(
        f"/businesses/wholesale/clients/{retailer.id}"
    )
    client_html = client_page.data.decode()
    assert client_page.status_code == 200
    assert f"Vente #{first_old_sale.id} du" in client_html
    assert f"Vente #{second_old_sale.id} du" in client_html


def test_wholesale_sale_confirmation_explains_old_debt_allocation(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=506)
    today = business_local_date()
    record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=today - timedelta(days=1), preset=preset,
    )
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.post(
        "/businesses/wholesale/sales",
        data={
            "client_id": str(retailer.id),
            "sale_items-0-network": NetworkType.AIRTEL.name,
            "sale_items-0-quantity": "100",
            "sale_items-0-price_choice": f"preset:{preset.id}",
            "sale_date": today.isoformat(),
            "cash_received": "2.00",
        },
        follow_redirects=True,
    )
    html = response.data.decode()
    assert response.status_code == 200
    assert "Vente enregistrée · $2.00 reçu." in html
    assert "$2.00 aux anciennes dettes · $0.00 à cette vente." in html


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
    group = build_wholesale_sale_groups([second], [event])[0]
    detail = group["payment_details"][second.id]
    assert group["cash_received_from_sales"] == Decimal("7.00")
    assert detail["redirected_to_other_sales"] == Decimal("5.00")
    assert detail["applied_from_own_receipts"] == Decimal("2.00")
    assert detail["applied_from_other_receipts"] == 0
    assert detail["blocking_payment_ids"] == [event.id]


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
    reversed_group = build_wholesale_sale_groups([second], [event])[0]
    reversed_detail = reversed_group["payment_details"][second.id]
    assert reversed_group["cash_received_from_sales"] == 0
    assert reversed_detail["blocking_payment_count"] == 0
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


def test_payment_correction_replaces_receipt_and_reapplies_oldest_debt(session):
    owner, business, client, _ = setup_wholesale(session, suffix=231)
    oldest = record_wholesale_sale(
        business=business, sold_by=owner, client=client,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), custom_unit_price=Decimal("0.01000"),
    )
    current = record_wholesale_sale(
        business=business, sold_by=owner, client=client,
        network=NetworkType.AIRTEL, quantity=500,
        cash_received=Decimal("7.00"), sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()
    original = PaymentEvent.query.one()

    replacement = correct_wholesale_payment_event(
        payment_event=original,
        business=business,
        corrected_by=owner,
        amount=Decimal("3.00"),
        payment_date=date.today(),
        reason="Montant mal saisi",
    )
    session.flush()

    assert original.status == TransactionStatus.REVERSED
    assert original.replacement is replacement
    assert replacement.corrected_from is original
    assert replacement.status == TransactionStatus.ACTIVE
    assert replacement.amount == Decimal("3.00")
    assert {allocation.status for allocation in original.allocations} == {
        TransactionStatus.REVERSED
    }
    assert len(replacement.allocations) == 1
    assert replacement.allocations[0].sale_id == oldest.id
    assert replacement.allocations[0].amount == Decimal("3.00")
    assert oldest.cash_paid == Decimal("3.00")
    assert oldest.debt_amount == Decimal("2.00")
    assert current.cash_paid == 0
    assert current.initial_cash_paid == 0
    assert current.debt_amount == Decimal("5.00")


def test_payment_correction_requires_newest_receipt_first(session):
    owner, business, client, _ = setup_wholesale(session, suffix=232)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=client,
        network=NetworkType.AIRTEL, quantity=500,
        cash_received=Decimal("1.00"), sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()
    original = PaymentEvent.query.filter_by(source_sale_id=sale.id).one()
    collect_client_debt(
        business=business,
        client=client,
        amount=Decimal("1.00"),
        recorded_by=owner,
        payment_date=date.today(),
    )
    session.flush()
    later = PaymentEvent.query.filter(PaymentEvent.id != original.id).one()

    with pytest.raises(ValueError, match=f"reçu #{later.id}"):
        correct_wholesale_payment_event(
            payment_event=original,
            business=business,
            corrected_by=owner,
            amount=Decimal("2.00"),
            payment_date=date.today(),
            reason="Montant mal saisi",
        )

    assert original.status == TransactionStatus.ACTIVE
    assert original.replacement is None


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


def test_owner_can_correct_payment_from_sales_card(app, session):
    owner, business, client_record, _ = setup_wholesale(session, suffix=261)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=client_record,
        network=NetworkType.AIRTEL, quantity=500,
        cash_received=Decimal("1.00"), sale_date=date.today(),
        custom_unit_price=Decimal("0.01000"),
    )
    session.commit()
    event = PaymentEvent.query.filter_by(source_sale_id=sale.id).one()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    sales_page = browser.get("/businesses/wholesale/sales")
    assert f"/businesses/wholesale/payments/{event.id}/correct".encode() in sales_page.data

    response = browser.post(
        f"/businesses/wholesale/payments/{event.id}/correct",
        data={
            "amount": "2.00",
            "payment_date": date.today().isoformat(),
            "reason": "Montant mal saisi",
        },
    )

    assert response.status_code == 302
    replacement = PaymentEvent.query.filter_by(corrected_from_id=event.id).one()
    assert event.status == TransactionStatus.REVERSED
    assert replacement.amount == Decimal("2.00")
    assert sale.cash_paid == Decimal("2.00")
    assert sale.debt_amount == Decimal("3.00")


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
    today = business_local_date()
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
            "sale_date": today.isoformat(),
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
    assert b"Marge du jour par prix" not in page.data
    assert b"$0.40" in page.data
    assert b"$0.21" in page.data

    report_page = client.get("/businesses/wholesale/report")
    assert report_page.status_code == 200
    assert b"Marge par prix de vente" in report_page.data
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
    today = business_local_date()
    first_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=today, preset=preset,
    )
    second_sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=Decimal("1"),
        sale_date=today, preset=preset,
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
    assert b"1 paiement li\xc3\xa9" in page.data
    assert b"$1.00 re\xc3\xa7u depuis cette vente" in page.data
    assert b"$1.00 appliqu\xc3\xa9 aux anciennes dettes" in page.data
    assert b"$1.00 re\xc3\xa7u via d'autres paiements" in page.data
    assert b"Voir les paiements" in page.data
    assert b"Paiement \xc3\xa0 annuler d'abord" not in page.data


def test_wholesale_sales_page_keeps_legacy_paid_sale_protected(app, session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=541)
    today = business_local_date()
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=today, preset=preset,
    )
    sale.cash_paid = Decimal("1.00")
    sale.debt_amount -= Decimal("1.00")
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    page = browser.get("/businesses/wholesale/sales")

    assert page.status_code == 200
    assert b"Paiement ancien" in page.data
    assert b"$1.00 pay\xc3\xa9 via un ancien re\xc3\xa7u sans d\xc3\xa9tail" in page.data
    assert f"/businesses/wholesale/sales/{sale.id}/edit".encode() not in page.data


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


def test_price_client_and_date_edit_after_later_purchase_preserves_cost(session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=551)
    other_client = Client(
        name="Other retailer",
        vendeur_id=owner.id,
        business_id=business.id,
    )
    session.add(other_client)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    session.flush()
    original_item = sale.sale_items[0]
    original_item_id = original_item.id
    original_cost_per_unit = original_item.cost_per_unit_snapshot
    original_cost_total = original_item.cost_total

    record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=1000, custom_unit_cost=Decimal("0.01200"),
    )
    session.flush()
    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    stock_state = (
        stock.balance,
        stock.inventory_value,
        stock.average_cost_per_unit,
    )
    corrected_date = date.today() - timedelta(days=1)

    replace_unpaid_wholesale_sale(
        sale=sale,
        business=business,
        updated_by=owner,
        client=other_client,
        sale_date=corrected_date,
        items=[{
            "network": NetworkType.AIRTEL,
            "quantity": 500,
            "custom_unit_price": Decimal("0.009455"),
        }],
    )
    session.flush()

    assert len(sale.sale_items) == 1
    corrected_item = sale.sale_items[0]
    assert corrected_item.id == original_item_id
    assert corrected_item.price_preset_id is None
    assert corrected_item.price_per_unit_applied == Decimal("0.009455000000")
    assert corrected_item.subtotal == Decimal("4.73")
    assert corrected_item.cost_per_unit_snapshot == original_cost_per_unit
    assert corrected_item.cost_total == original_cost_total
    assert corrected_item.margin_amount == Decimal("0.230000000000")
    assert sale.client_id == other_client.id
    assert sale.sale_date == corrected_date
    assert sale.total_amount_due == Decimal("4.73")
    assert sale.debt_amount == Decimal("4.73")
    assert (
        stock.balance,
        stock.inventory_value,
        stock.average_cost_per_unit,
    ) == stock_state


def test_sale_edit_is_blocked_after_later_purchase_changes_cost(session):
    owner, business, retailer, preset = setup_wholesale(session, suffix=56)
    sale = record_wholesale_sale(
        business=business, sold_by=owner, client=retailer,
        network=NetworkType.AIRTEL, quantity=500, cash_received=0,
        sale_date=date.today(), preset=preset,
    )
    session.flush()
    later_purchase = record_wholesale_purchase(
        business=business, purchased_by=owner, network=NetworkType.AIRTEL,
        quantity=1000, custom_unit_cost=Decimal("0.01200"),
    )
    session.flush()

    with pytest.raises(ValueError) as error:
        replace_unpaid_wholesale_sale(
            sale=sale, business=business, updated_by=owner, client=retailer,
            sale_date=date.today(), items=[{
                "network": NetworkType.AIRTEL,
                "quantity": 300,
                "custom_unit_price": Decimal("0.01000"),
            }],
        )

    message = str(error.value)
    assert "quantité ou le réseau" in message
    assert f"achat Airtel #{later_purchase.id}" in message
    assert "Le prix et le client restent modifiables" in message
    assert sale.sale_items[0].quantity == 500
    assert Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one().balance == 2500


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
