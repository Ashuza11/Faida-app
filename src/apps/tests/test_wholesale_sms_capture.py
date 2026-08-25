from datetime import date, datetime, timezone
from decimal import Decimal

from apps.businesses import create_business
from apps.dates import business_local_date
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    NetworkType,
    PriceOperation,
    RoleType,
    Sale,
    Stock,
    StockPurchase,
    User,
)


def owner_with_modes(session):
    owner = User(
        username="sms-owner",
        phone="+243810003333",
        role=RoleType.VENDEUR,
        api_token="android-wholesale-token",
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    retail = create_business(
        owner=owner, name="Retail SMS", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner, name="Wholesale SMS", business_type=BusinessType.WHOLESALE
    )
    wholesale.approval_status = BusinessApprovalStatus.APPROVED
    session.commit()
    return owner, retail, wholesale


def auth_headers():
    return {"X-Api-Token": "android-wholesale-token"}


def test_business_date_uses_local_day_at_utc_day_boundary():
    assert business_local_date(
        datetime(2026, 8, 18, 22, 30, tzinfo=timezone.utc)
    ) == date(2026, 8, 19)


def test_android_lists_approved_modes_for_explicit_capture_selection(app, session):
    _, retail, wholesale = owner_with_modes(session)

    response = app.test_client().get(
        "/api/v1/android/businesses", headers=auth_headers()
    )

    assert response.status_code == 200
    modes = {item["id"]: item for item in response.get_json()["businesses"]}
    assert set(modes) == {retail.id, wholesale.id}
    assert modes[wholesale.id]["type"] == "wholesale"
    assert modes[wholesale.id]["label"] == "Mode grossiste — Wholesale SMS"


def test_token_sms_requires_explicit_business_id(app, session):
    owner_with_modes(session)

    response = app.test_client().post(
        "/api/v1/sms-ingest",
        headers=auth_headers(),
        json={"sender": "1000", "body": "8087:Vous avez recu un stock de :eTopUP:10650 U provenant"},
    )

    assert response.status_code == 400
    assert "mode Android" in response.get_json()["error"]


def test_wholesale_purchase_sms_uses_exact_default_usd_cost(app, session):
    _, retail, wholesale = owner_with_modes(session)

    response = app.test_client().post(
        "/api/v1/sms-ingest",
        headers=auth_headers(),
        json={
            "business_id": wholesale.id,
            "received_at": 1787061600000,
            "sender": "1000",
            "body": "8087:Vous avez recu un stock de :eTopUP:10650 U provenant",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["mode"] == "wholesale"
    assert payload["total_usd"] == 100.0
    purchase = session.get(StockPurchase, payload["purchase_id"])
    assert purchase.stock_item.business_id == wholesale.id
    assert purchase.actual_total_cost == Decimal("100.000000000000")
    assert purchase.purchase_date == business_local_date(
        datetime.fromtimestamp(1787061600000 / 1000, tz=timezone.utc)
    )
    assert Stock.query.filter_by(business_id=retail.id).count() == 0
    from apps.models import Client
    assert Client.query.filter_by(business_id=wholesale.id).count() == 0


def test_wholesale_sale_sms_creates_retailer_debt_at_default_price(app, session):
    _, retail, wholesale = owner_with_modes(session)
    purchase_preset = next(
        preset for preset in wholesale.price_presets
        if preset.network == NetworkType.AIRTEL
        and preset.operation == PriceOperation.PURCHASE
    )
    from apps.purchases import record_wholesale_purchase

    record_wholesale_purchase(
        business=wholesale,
        purchased_by=wholesale.owner,
        network=NetworkType.AIRTEL,
        quantity=10650,
        preset=purchase_preset,
    )
    session.commit()

    response = app.test_client().post(
        "/api/v1/sms-ingest",
        headers=auth_headers(),
        json={
            "business_id": wholesale.id,
            "received_at": 1787061601000,
            "sender": "1000",
            "body": "5037:Votre transfert de 250 U au 972067057 a reussi",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["mode"] == "wholesale"
    assert payload["payment_status"] == "debt"
    sale = session.get(Sale, payload["sale_id"])
    assert sale.sale_date == business_local_date(
        datetime.fromtimestamp(1787061601000 / 1000, tz=timezone.utc)
    )
    assert sale.business_id == wholesale.id
    assert sale.client.business_id == wholesale.id
    assert sale.client.phone_airtel == "+243972067057"
    assert sale.cash_paid == Decimal("0E-12")
    assert sale.debt_amount == Decimal("2.350000000000")
    assert Sale.query.filter_by(business_id=retail.id).count() == 0


def test_sms_rejects_business_owned_by_another_user(app, session):
    owner_with_modes(session)
    other = User(
        username="other-owner",
        phone="+243810004444",
        role=RoleType.VENDEUR,
    )
    other.set_password("safe-password")
    session.add(other)
    session.flush()
    other_business = create_business(
        owner=other, name="Other retail", business_type=BusinessType.RETAIL
    )
    session.commit()

    response = app.test_client().post(
        "/api/v1/sms-ingest",
        headers=auth_headers(),
        json={
            "business_id": other_business.id,
            "received_at": 1787061602000,
            "sender": "1000",
            "body": "8087:Vous avez recu un stock de :eTopUP:10650 U provenant",
        },
    )

    assert response.status_code == 403
    assert StockPurchase.query.count() == 0


def test_repeated_android_broadcast_does_not_duplicate_wholesale_purchase(app, session):
    _, _, wholesale = owner_with_modes(session)
    payload = {
        "business_id": wholesale.id,
        "received_at": 1787061603000,
        "sender": "1000",
        "body": "8087:Vous avez recu un stock de :eTopUP:10650 U provenant",
    }
    client = app.test_client()

    first = client.post("/api/v1/sms-ingest", headers=auth_headers(), json=payload)
    second = client.post("/api/v1/sms-ingest", headers=auth_headers(), json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"
    assert StockPurchase.query.filter(
        StockPurchase.stock_item.has(business_id=wholesale.id)
    ).count() == 1
