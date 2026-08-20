from apps.businesses import create_business
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    Client,
    NetworkType,
    RoleType,
    User,
)


def setup_wholesale(session):
    owner = User(
        username="wholesale-clients-owner",
        phone="+243810009991",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner,
        name="Grossiste Clients",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.commit()
    return owner, business


def login(client, owner, business):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["active_business_id"] = business.id


def test_wholesale_menu_exposes_separate_clients_and_debts(app, session):
    owner, business = setup_wholesale(session)
    client = app.test_client()
    login(client, owner, business)

    response = client.get("/businesses/wholesale/client-management")

    assert response.status_code == 200
    assert b">Clients<" in response.data
    assert b">Dettes<" in response.data


def test_wholesale_owner_registers_many_numbers_for_one_client(app, session):
    owner, business = setup_wholesale(session)
    browser = app.test_client()
    login(browser, owner, business)

    response = browser.post(
        "/businesses/wholesale/client-management",
        data={
            "name": "Deric Centre",
            "phone_airtel": "0972067057\n0991234567",
            "phone_orange": "0841234567",
            "phone_africel": "",
            "phone_vodacom": "",
            "address": "Centre-ville",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    client = Client.query.filter_by(
        business_id=business.id, name="Deric Centre"
    ).one()
    assert set(client.airtel_phones) == {"+243972067057", "+243991234567"}
    assert client.orange_phones == ["+243841234567"]


def test_wholesale_owner_can_identify_sms_created_client(app, session):
    owner, business = setup_wholesale(session)
    sms_client = Client(
        name="Client à identifier · +243972067057",
        vendeur_id=owner.id,
        business_id=business.id,
        registration_source="sms",
        identification_status="needs_name",
    )
    session.add(sms_client)
    session.flush()
    from apps.client_identities import replace_client_phones
    replace_client_phones(
        client=sms_client,
        phone_entries=[(NetworkType.AIRTEL, "+243972067057")],
    )
    session.commit()
    browser = app.test_client()
    login(browser, owner, business)

    response = browser.post(
        f"/businesses/wholesale/client-management/{sms_client.id}/edit",
        data={
            "name": "Deric Route",
            "phone_airtel": "+243972067057\n0991234567",
            "phone_africel": "",
            "phone_orange": "",
            "phone_vodacom": "",
            "address": "Route principale",
            "is_active": "y",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    session.refresh(sms_client)
    assert sms_client.name == "Deric Route"
    assert sms_client.identification_status == "identified"
    assert set(sms_client.airtel_phones) == {"+243972067057", "+243991234567"}
