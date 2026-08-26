from datetime import date
from decimal import Decimal

from apps.businesses import create_business
from apps.models import (
    BusinessApprovalStatus,
    BusinessMembership,
    BusinessType,
    CashInflow,
    CashInflowCategory,
    CashOutflow,
    CashOutflowCategory,
    Client,
    NetworkType,
    PaymentEvent,
    RoleType,
    Sale,
    Stock,
    TransactionStatus,
    User,
)


def setup_ledgers(session):
    owner = User(
        username="route-isolation-owner",
        phone="+243810009902",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    retail = create_business(
        owner=owner, name="Retail Route", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner,
        name="Wholesale Route",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    retail_client = Client(
        name="Retail-visible client",
        vendeur_id=owner.id,
        business_id=retail.id,
    )
    wholesale_client = Client(
        name="Wholesale-hidden client",
        vendeur_id=owner.id,
        business_id=wholesale.id,
    )
    session.add_all([retail_client, wholesale_client])
    session.flush()
    session.add_all(
        [
            Sale(
                seller_id=owner.id,
                vendeur_id=owner.id,
                business_id=retail.id,
                client=retail_client,
                sale_date=date.today(),
                total_amount_due=Decimal("100"),
                cash_paid=Decimal("0"),
                debt_amount=Decimal("100"),
            ),
            Sale(
                seller_id=owner.id,
                vendeur_id=owner.id,
                business_id=wholesale.id,
                client=wholesale_client,
                sale_date=date.today(),
                total_amount_due=Decimal("10"),
                cash_paid=Decimal("0"),
                debt_amount=Decimal("10"),
            ),
            CashOutflow(
                vendeur_id=owner.id,
                business_id=retail.id,
                recorded_by=owner,
                amount=Decimal("5"),
                category=CashOutflowCategory.OTHER,
                expense_date=date.today(),
                description="Retail-visible expense",
            ),
            CashOutflow(
                vendeur_id=owner.id,
                business_id=wholesale.id,
                recorded_by=owner,
                amount=Decimal("7"),
                category=CashOutflowCategory.OTHER,
                expense_date=date.today(),
                description="Wholesale-hidden expense",
            ),
        ]
    )
    session.commit()
    return owner, retail, wholesale, retail_client, wholesale_client


def login_to_business(client, owner, business):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id


def test_retail_client_sale_debt_and_cash_pages_are_business_scoped(app, session):
    owner, retail, _, _, wholesale_client = setup_ledgers(session)
    client = app.test_client()
    login_to_business(client, owner, retail)

    clients_page = client.get("/admin/clients")
    sales_page = client.get("/vente_stock")
    debt_page = client.get("/sorties_cash/encaisser_dette")
    cash_page = client.get("/sorties_cash")

    for response in (clients_page, sales_page, debt_page, cash_page):
        assert response.status_code == 200
    assert b"Retail-visible client" in clients_page.data
    assert b"Wholesale-hidden client" not in clients_page.data
    assert b"Wholesale-hidden client" not in sales_page.data
    assert b"Retail-visible client" in debt_page.data
    assert b"Wholesale-hidden client" not in debt_page.data
    assert b"Retail-visible expense" in cash_page.data
    assert b"Wholesale-hidden expense" not in cash_page.data

    edit_response = client.post(
        f"/admin/clients/edit/{wholesale_client.id}", data={"name": "Changed"}
    )
    assert edit_response.status_code == 403


def test_new_retail_records_receive_active_business_key(app, session):
    owner, retail, _, retail_client, _ = setup_ledgers(session)
    session.add(Stock(
        vendeur_id=owner.id,
        business_id=retail.id,
        network=NetworkType.AIRTEL,
        balance=Decimal("100"),
        buying_price_per_unit=Decimal("20"),
        selling_price_per_unit=Decimal("25"),
        inventory_value=Decimal("2000"),
        average_cost_per_unit=Decimal("20"),
    ))
    session.commit()
    client = app.test_client()
    login_to_business(client, owner, retail)

    client_response = client.post(
        "/admin/clients",
        data={"name": "New retail client", "submit": "Ajouter Client"},
    )
    expense_response = client.post(
        "/enregistrer_sortie",
        data={
            "amount": "12.50",
            "category": CashOutflowCategory.OTHER.name,
            "expense_date": date.today().isoformat(),
            "description": "New retail expense",
            "submit": "Enregistrer",
        },
    )
    sale_response = client.post(
        "/vente_stock",
        data={
            "client_choice": "existing",
            "existing_client_id": str(retail_client.id),
            "sale_items-0-network": NetworkType.AIRTEL.name,
            "sale_items-0-quantity": "10",
            "sale_items-0-price_per_unit_applied": "25",
            "cash_paid": "0",
            "sale_date": date.today().isoformat(),
            "submit": "Enregistre Vente",
        },
    )

    assert client_response.status_code == 302
    assert expense_response.status_code == 302
    assert sale_response.status_code == 302
    assert Client.query.filter_by(name="New retail client").one().business_id == retail.id
    assert CashOutflow.query.filter_by(
        description="New retail expense"
    ).one().business_id == retail.id
    created_sale = Sale.query.filter_by(
        client_id=retail_client.id, total_amount_due=Decimal("250")
    ).one()
    assert created_sale.business_id == retail.id

    edit_response = client.get(f"/edit_sale/{created_sale.id}")
    assert edit_response.status_code == 302
    assert edit_response.headers["Location"].endswith(
        f"/delete_sale/{created_sale.id}"
    )
    cancel_response = client.post(
        f"/delete_sale/{created_sale.id}",
        data={"reason": "Quantité incorrecte"},
    )
    assert cancel_response.status_code == 302
    session.refresh(created_sale)
    stock = Stock.query.filter_by(
        business_id=retail.id, network=NetworkType.AIRTEL
    ).one()
    assert created_sale.status == TransactionStatus.REVERSED
    assert created_sale.reversal_reason == "Quantité incorrecte"
    assert stock.balance == Decimal("100")
    assert Sale.query.filter_by(id=created_sale.id).count() == 1


def test_retail_debt_payment_cannot_reach_wholesale_debt(app, session):
    owner, retail, _, retail_client, wholesale_client = setup_ledgers(session)
    retail_sale = Sale.query.filter_by(client_id=retail_client.id).one()
    wholesale_sale = Sale.query.filter_by(client_id=wholesale_client.id).one()
    client = app.test_client()
    login_to_business(client, owner, retail)

    response = client.post(
        "/sorties_cash/encaisser_dette",
        data={
            "client_key": f"c:{retail_client.id}",
            "amount_paid": "30.00",
            "payment_date": date.today().isoformat(),
            "description": "Retail payment",
            "submit": "Payer",
        },
    )

    assert response.status_code == 302
    session.refresh(retail_sale)
    session.refresh(wholesale_sale)
    assert retail_sale.debt_amount == Decimal("70.00")
    assert wholesale_sale.debt_amount == Decimal("10.00")
    event = PaymentEvent.query.one()
    assert event.business_id == retail.id
    assert event.client_id == retail_client.id


def test_owner_created_stockeur_receives_retail_membership(app, session):
    owner, retail, _, _, _ = setup_ledgers(session)
    client = app.test_client()
    login_to_business(client, owner, retail)

    response = client.post(
        "/admin/stocker",
        data={
            "username": "new-retail-stockeur",
            "phone": "+243810009903",
            "email": "stockeur@example.com",
            "password": "safe-password",
            "submit": "Ajouter",
        },
    )

    assert response.status_code == 302
    stockeur = User.query.filter_by(username="new-retail-stockeur").one()
    membership = BusinessMembership.query.filter_by(user_id=stockeur.id).one()
    assert membership.business_id == retail.id
    assert membership.is_active is True


def test_sale_cash_update_pays_older_retail_debt_first(app, session):
    owner, retail, _, retail_client, wholesale_client = setup_ledgers(session)
    oldest = Sale.query.filter_by(client_id=retail_client.id).one()
    wholesale_sale = Sale.query.filter_by(client_id=wholesale_client.id).one()
    current = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=retail.id,
        client=retail_client,
        sale_date=date.today(),
        total_amount_due=Decimal("80"),
        cash_paid=Decimal("0"),
        debt_amount=Decimal("80"),
    )
    session.add(current)
    session.commit()
    client = app.test_client()
    login_to_business(client, owner, retail)

    response = client.post(
        f"/update-sale-cash/{current.id}", data={"new_cash": "60.00"}
    )

    assert response.status_code == 302
    session.refresh(oldest)
    session.refresh(current)
    session.refresh(wholesale_sale)
    assert oldest.debt_amount == Decimal("40.00")
    assert current.cash_paid == 0
    assert current.debt_amount == Decimal("80.00")
    assert wholesale_sale.debt_amount == Decimal("10.00")
    event = PaymentEvent.query.one()
    assert event.amount == Decimal("60.00")
    assert {allocation.sale_id for allocation in event.allocations} == {oldest.id}

    detail_response = client.get(f"/view_sale_details/{current.id}")
    assert detail_response.status_code == 200
    assert b"60.00 FC" in detail_response.data
    cancel_response = client.post(
        f"/payments/{event.id}/reverse",
        data={"reason": "Montant incorrect"},
    )
    assert cancel_response.status_code == 302
    session.refresh(oldest)
    session.refresh(event)
    assert oldest.debt_amount == Decimal("100.00")
    assert event.status == TransactionStatus.REVERSED


def test_equal_name_adhoc_payment_and_cancellation_stay_sale_scoped(app, session):
    owner, retail, _, _, _ = setup_ledgers(session)
    first = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=retail.id,
        client_name_adhoc="Kiosque",
        adhoc_customer_key="kiosque-one",
        sale_date=date.today(),
        total_amount_due=Decimal("50"),
        cash_paid=Decimal("0"),
        debt_amount=Decimal("50"),
    )
    second = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=retail.id,
        client_name_adhoc="Kiosque",
        adhoc_customer_key="kiosque-two",
        sale_date=date.today(),
        total_amount_due=Decimal("50"),
        cash_paid=Decimal("0"),
        debt_amount=Decimal("50"),
    )
    session.add_all([first, second])
    session.commit()
    client = app.test_client()
    login_to_business(client, owner, retail)

    payment_response = client.post(
        "/sorties_cash/encaisser_dette",
        data={
            "client_key": "a:kiosque-one",
            "amount_paid": "20.00",
            "payment_date": date.today().isoformat(),
            "description": "Ad-hoc payment",
            "submit": "Payer",
        },
    )

    assert payment_response.status_code == 302
    session.refresh(first)
    session.refresh(second)
    assert first.debt_amount == Decimal("30.00")
    assert second.debt_amount == Decimal("50.00")
    event = PaymentEvent.query.one()
    assert event.client_id is None
    assert event.source_sale_id == first.id
    assert {allocation.sale_id for allocation in event.allocations} == {first.id}

    cancellation_response = client.post(
        f"/payments/{event.id}/reverse",
        data={"reason": "Montant incorrect"},
    )

    assert cancellation_response.status_code == 302
    session.refresh(first)
    session.refresh(second)
    assert first.debt_amount == Decimal("50.00")
    assert second.debt_amount == Decimal("50.00")
    assert event.status == TransactionStatus.REVERSED


def test_legacy_payment_is_visible_but_cannot_be_guessed_or_cancelled(app, session):
    owner, retail, _, retail_client, _ = setup_ledgers(session)
    sale = Sale.query.filter_by(client_id=retail_client.id).one()
    sale.cash_paid = Decimal("25")
    sale.debt_amount = Decimal("75")
    legacy_allocation = CashInflow(
        amount=Decimal("25"),
        category=CashInflowCategory.SALE_COLLECTION,
        description="Ancien paiement",
        recorded_by=owner,
        vendeur_id=owner.id,
        business_id=retail.id,
        payment_event_id=None,
        sale=sale,
        payment_date=date.today(),
    )
    session.add(legacy_allocation)
    session.commit()
    client = app.test_client()
    login_to_business(client, owner, retail)

    details = client.get(f"/view_sale_details/{sale.id}")

    assert details.status_code == 200
    assert b"Anciens paiements non annulables" in details.data
    assert b"Ancien paiement" in details.data
    assert f"/payments/".encode() not in details.data

    cancellation = client.post(
        f"/delete_sale/{sale.id}",
        data={"reason": "Correction historique"},
        follow_redirects=True,
    )

    assert cancellation.status_code == 200
    assert "ancienne vente contient un paiement non annulable".encode() in cancellation.data
    assert b"Contactez l&#39;administrateur" in cancellation.data
    session.refresh(sale)
    assert sale.status == TransactionStatus.ACTIVE
    assert sale.cash_paid == Decimal("25.00")
    assert sale.debt_amount == Decimal("75.00")
