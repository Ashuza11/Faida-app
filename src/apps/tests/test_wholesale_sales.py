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
    PriceOperation,
    RoleType,
    Sale,
    Stock,
    User,
)
from apps.purchases import record_wholesale_purchase
from apps.payments import collect_client_debt
from apps.sales import record_wholesale_sale


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


def test_wholesale_sale_rejects_another_business_client(session):
    owner, business, _, preset = setup_wholesale(session, suffix=3)
    other_owner, other_business, other_client, _ = setup_wholesale(session, suffix=4)

    with pytest.raises(ValueError, match="autre entreprise"):
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
            "network": NetworkType.AIRTEL.name,
            "quantity": "1000",
            "price_choice": f"preset:{preset.id}",
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
    with pytest.raises(PermissionError, match="autre entreprise"):
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
