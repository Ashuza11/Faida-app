from apps.businesses import add_stockeur, create_business
from apps.models import (
    Business,
    BusinessApprovalStatus,
    BusinessType,
    CurrencyCode,
    NetworkType,
    PricePreset,
    PriceOperation,
    RoleType,
    Stock,
    User,
)


def make_user(session, *, suffix, role=RoleType.VENDEUR):
    user = User(
        username=f"route-user-{suffix}",
        phone=f"+243810007{suffix:03d}",
        role=role,
    )
    user.set_password("safe-password")
    session.add(user)
    session.flush()
    return user


def login(client, user):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user.id)
        browser_session["_fresh"] = True


def test_owner_creates_isolated_usd_wholesale_workspace(app, session):
    owner = make_user(session, suffix=1)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    session.commit()
    client = app.test_client()
    login(client, owner)

    response = client.post(
        "/businesses/wholesale/create",
        data={"name": "Faida Distribution"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/businesses")
    wholesale = Business.query.filter_by(
        owner_user_id=owner.id, business_type=BusinessType.WHOLESALE
    ).one()
    assert wholesale.currency_code == CurrencyCode.USD
    assert wholesale.approval_status == BusinessApprovalStatus.PENDING
    assert wholesale.id != retail.id
    assert {stock.network for stock in Stock.query.filter_by(
        business_id=wholesale.id
    )} == set(NetworkType)
    assert PricePreset.query.filter_by(
        business_id=wholesale.id, operation=PriceOperation.SALE
    ).count() == 16
    assert PricePreset.query.filter_by(
        business_id=wholesale.id, operation=PriceOperation.PURCHASE
    ).count() == 3


def test_owner_switches_between_retail_and_wholesale(app, session):
    owner = make_user(session, suffix=2)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner,
        name="Wholesale",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.commit()
    client = app.test_client()
    login(client, owner)

    wholesale_response = client.post(f"/businesses/{wholesale.id}/switch")
    with client.session_transaction() as browser_session:
        assert browser_session["active_business_id"] == wholesale.id
    assert wholesale_response.headers["Location"].endswith("/businesses/wholesale")

    retail_response = client.post(f"/businesses/{retail.id}/switch")
    with client.session_transaction() as browser_session:
        assert browser_session["active_business_id"] == retail.id
    assert retail_response.headers["Location"].endswith("/index")


def test_stockeur_cannot_switch_to_owners_wholesale_business(app, session):
    owner = make_user(session, suffix=3)
    stockeur = make_user(session, suffix=4, role=RoleType.STOCKEUR)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner,
        name="Wholesale",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    add_stockeur(business=retail, stockeur=stockeur)
    session.commit()
    client = app.test_client()
    login(client, stockeur)

    response = client.post(f"/businesses/{wholesale.id}/switch")

    assert response.status_code == 403


def test_wholesale_session_is_kept_out_of_legacy_retail_routes(app, session):
    owner = make_user(session, suffix=5)
    wholesale = create_business(
        owner=owner,
        name="Wholesale",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.commit()
    client = app.test_client()
    login(client, owner)
    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = wholesale.id

    response = client.get("/vente_stock")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/businesses/wholesale")


def test_pending_wholesale_cannot_be_selected(app, session):
    owner = make_user(session, suffix=6)
    wholesale = create_business(
        owner=owner, name="Pending Wholesale", business_type=BusinessType.WHOLESALE
    )
    session.commit()
    client = app.test_client()
    login(client, owner)

    response = client.post(f"/businesses/{wholesale.id}/switch")

    assert response.status_code == 403


def test_platform_admin_approves_wholesale_request(app, session):
    owner = make_user(session, suffix=7)
    admin = make_user(session, suffix=8, role=RoleType.PLATFORM_ADMIN)
    wholesale = create_business(
        owner=owner, name="Approval Needed", business_type=BusinessType.WHOLESALE
    )
    session.commit()
    client = app.test_client()
    login(client, admin)

    response = client.post(
        f"/admin/businesses/{wholesale.id}/approve-wholesale"
    )

    assert response.status_code == 302
    session.refresh(wholesale)
    assert wholesale.approval_status == BusinessApprovalStatus.APPROVED
    assert wholesale.approved_by_user_id == admin.id
    assert wholesale.approved_at is not None
