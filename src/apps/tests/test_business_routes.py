from datetime import date
from decimal import Decimal

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
    StockPurchase,
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

    modes_page = client.get("/businesses")
    assert modes_page.status_code == 200
    assert "Mode détail".encode() in modes_page.data
    assert b"Mode grossiste" in modes_page.data
    assert b"Changer mode" in modes_page.data
    assert b"Mes entreprises" not in modes_page.data

    wholesale_response = client.post(f"/businesses/{wholesale.id}/switch")
    with client.session_transaction() as browser_session:
        assert browser_session["active_business_id"] == wholesale.id
    assert wholesale_response.headers["Location"].endswith("/businesses/wholesale")

    retail_response = client.post(f"/businesses/{retail.id}/switch")
    with client.session_transaction() as browser_session:
        assert browser_session["active_business_id"] == retail.id
    assert retail_response.headers["Location"].endswith("/index")


def test_wholesale_dashboard_uses_sidebar_actions_and_compact_header(app, session):
    owner = make_user(session, suffix=21)
    wholesale = create_business(
        owner=owner,
        name="Ets Albin",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.commit()
    client = app.test_client()
    login(client, owner)
    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = wholesale.id

    response = client.get("/businesses/wholesale")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ets Albin" in page
    assert "Grossiste" in page
    assert "USD" in page
    assert 'id="navbar-wholesale"' in page
    for label in ("Vendre", "Acheter", "Dettes", "Rapport", "Changer mode"):
        assert label in page
    # Only the mode switch remains in the page header; operations live in the sidebar.
    content = page.rsplit('<div class="container-fluid mt-4">', 1)[1]
    header = content.split('<div class="row">', 1)[0]
    assert "Vendre" not in header
    assert "Acheter" not in header


def test_date_filters_auto_submit_without_action_buttons(app, session):
    owner = make_user(session, suffix=22)
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

    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = retail.id

    for url in ("/index", "/sorties_cash", "/sorties_cash/encaisser_dette", "/achat_stock", "/rapports"):
        response = client.get(url)
        assert response.status_code == 200
        assert b"Afficher" not in response.data
        assert b"Filtrer" not in response.data
        assert b'onchange="this.form.submit()"' in response.data

    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = wholesale.id

    wholesale_report = client.get(f"/businesses/wholesale/report?date={date.today().isoformat()}")
    assert wholesale_report.status_code == 200
    assert b"Afficher" not in wholesale_report.data
    assert b"Filtrer" not in wholesale_report.data
    assert b'id="report-home-btn"' in wholesale_report.data
    assert b'id="report-pdf-btn"' in wholesale_report.data


def test_compact_buttons_render_on_retail_and_business_pages(app, session):
    owner = make_user(session, suffix=23)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    session.commit()
    client = app.test_client()
    login(client, owner)

    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = retail.id

    businesses_page = client.get("/businesses")
    clients_page = client.get("/admin/clients")

    assert businesses_page.status_code == 200
    assert b"Ajouter grossiste" in businesses_page.data
    assert b"Ajouter le mode grossiste" not in businesses_page.data

    assert clients_page.status_code == 200
    assert b"Ajouter" in clients_page.data
    assert b"Ajouter Client" not in clients_page.data
    assert b"Position" in clients_page.data
    assert b"Obtenir ma position" not in clients_page.data


def test_profile_rename_syncs_retail_mode_but_preserves_wholesale_name(app, session):
    owner = make_user(session, suffix=20)
    owner.email = "owner20@example.com"
    retail = create_business(
        owner=owner, name="0970353088", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner,
        name="Ets Albin",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.commit()
    client = app.test_client()
    login(client, owner)

    response = client.post(
        "/profile",
        data={
            "username": "Ets Ashuza",
            "email": owner.email,
            "phone": owner.phone,
        },
    )

    assert response.status_code == 302
    session.refresh(owner)
    session.refresh(retail)
    session.refresh(wholesale)
    assert owner.username == "Ets Ashuza"
    assert retail.name == "Ets Ashuza"
    assert wholesale.name == "Ets Albin"


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

    dashboard = client.get("/businesses/wholesale")
    assert dashboard.status_code == 200
    assert b"Wholesale" in dashboard.data

    api_response = client.get("/api/v1/stock")
    assert api_response.status_code == 409


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


def test_retail_purchase_never_updates_same_network_wholesale_stock(app, session):
    owner = make_user(session, suffix=9)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner,
        name="Wholesale",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    retail_stock = Stock(
        vendeur_id=owner.id,
        business_id=retail.id,
        network=NetworkType.AIRTEL,
        balance=Decimal("100"),
    )
    wholesale_stock = Stock(
        vendeur_id=owner.id,
        business_id=wholesale.id,
        network=NetworkType.AIRTEL,
        balance=Decimal("1000"),
    )
    session.add_all([retail_stock, wholesale_stock])
    session.commit()
    client = app.test_client()
    login(client, owner)
    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = retail.id

    response = client.post(
        "/achat_stock",
        data={
            "network": NetworkType.AIRTEL.name,
            "amount_purchased": "10",
            "buying_price_choice": "26.79",
            "intended_selling_price_choice": "27.5",
        },
    )

    assert response.status_code == 302
    session.refresh(retail_stock)
    session.refresh(wholesale_stock)
    assert retail_stock.balance == Decimal("110")
    assert wholesale_stock.balance == Decimal("1000")

    purchase = StockPurchase.query.filter_by(stock_item_id=retail_stock.id).one()
    history = client.get("/achat_stock")
    assert history.status_code == 200
    assert b">ID</th>" not in history.data

    edit_page = client.get(f"/achat_stock/editer/{purchase.id}")
    assert edit_page.status_code == 200
    assert f"#{purchase.id}".encode() not in edit_page.data

    delete_page = client.get(f"/achat_stock/supprimer/{purchase.id}")
    assert delete_page.status_code == 200
    assert b"ID Achat" not in delete_page.data
    assert StockPurchase.query.one().stock_item_id == retail_stock.id
