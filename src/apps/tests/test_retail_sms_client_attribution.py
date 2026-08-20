from decimal import Decimal

from apps.businesses import create_business
from apps.client_identities import replace_client_phones
from apps.models import BusinessType, Client, NetworkType, RoleType, Sale, Stock, User


def setup_retail_sms(session):
    owner = User(
        username="retail-sms-owner",
        phone="+243810008881",
        role=RoleType.VENDEUR,
        api_token="retail-sms-token",
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner, name="Retail SMS", business_type=BusinessType.RETAIL
    )
    session.flush()
    for network in (NetworkType.AIRTEL, NetworkType.ORANGE):
        session.add(Stock(
            vendeur_id=owner.id,
            business_id=business.id,
            network=network,
            balance=Decimal("10000"),
            inventory_value=Decimal("200000"),
            average_cost_per_unit=Decimal("20"),
            buying_price_per_unit=Decimal("20"),
            selling_price_per_unit=Decimal("22.5"),
        ))
    session.commit()
    return owner, business


def headers():
    return {"X-Api-Token": "retail-sms-token"}


def test_different_registered_numbers_group_sms_sales_under_one_client(app, session):
    owner, business = setup_retail_sms(session)
    client_record = Client(
        name="Deric Centre", vendeur_id=owner.id, business_id=business.id
    )
    session.add(client_record)
    session.flush()
    replace_client_phones(client=client_record, phone_entries=[
        (NetworkType.AIRTEL, "0972067057"),
        (NetworkType.ORANGE, "0841234567"),
    ])
    session.commit()
    browser = app.test_client()

    airtel = browser.post("/api/v1/sms-ingest", headers=headers(), json={
        "business_id": business.id,
        "received_at": 1787061700000,
        "sender": "1000",
        "body": "5037:Votre transfert de 250 U au 972067057 a reussi",
    })
    orange = browser.post("/api/v1/sms-ingest", headers=headers(), json={
        "business_id": business.id,
        "received_at": 1787061701000,
        "sender": "e-recharge",
        "body": "Vous avez transfere 250 U au 841234567",
    })

    assert airtel.status_code == orange.status_code == 201
    sales = Sale.query.order_by(Sale.id).all()
    assert [sale.client_id for sale in sales] == [client_record.id, client_record.id]
    assert all(sale.client_name_adhoc is None for sale in sales)


def test_repeated_unknown_retail_number_uses_one_identifiable_client(app, session):
    _, business = setup_retail_sms(session)
    browser = app.test_client()
    base_payload = {
        "business_id": business.id,
        "sender": "1000",
        "body": "5037:Votre transfert de 250 U au 972067057 a reussi",
    }

    first = browser.post(
        "/api/v1/sms-ingest", headers=headers(),
        json={**base_payload, "received_at": 1787061800000},
    )
    second = browser.post(
        "/api/v1/sms-ingest", headers=headers(),
        json={**base_payload, "received_at": 1787061801000},
    )

    assert first.status_code == second.status_code == 201
    clients = Client.query.filter_by(business_id=business.id).all()
    assert len(clients) == 1
    assert clients[0].identification_status == "needs_name"
    assert {sale.client_id for sale in Sale.query.all()} == {clients[0].id}


def test_retail_purchase_sms_never_creates_a_client(app, session):
    _, business = setup_retail_sms(session)

    response = app.test_client().post(
        "/api/v1/sms-ingest",
        headers=headers(),
        json={
            "business_id": business.id,
            "received_at": 1787061900000,
            "sender": "1000",
            "body": "8087:Vous avez recu un stock de :eTopUP:10650 U provenant",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["type"] == "purchase"
    assert Client.query.filter_by(business_id=business.id).count() == 0
