from datetime import date
from decimal import Decimal

from apps.businesses import create_business
from apps.models import (
    BusinessType,
    Client,
    NetworkType,
    RoleType,
    Sale,
    SaleItem,
    Stock,
    User,
)
from apps.retail_reports import build_retail_margin_report


def _retail_context(session):
    owner = User(
        username="margin-owner", phone="+243810008811", role=RoleType.VENDEUR
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner, name="Marge détail", business_type=BusinessType.RETAIL
    )
    session.flush()
    client = Client(
        name="Client marge", vendeur_id=owner.id, business_id=business.id
    )
    session.add(client)
    session.flush()
    return owner, business, client


def _login(browser, owner, business):
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id


def test_margin_report_separates_commercial_margin_from_invoice_rounding(
    app, session
):
    owner, business, client = _retail_context(session)
    sale = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=business.id,
        client=client,
        sale_date=date.today(),
        total_amount_due=Decimal("5550.00"),
        cash_paid=Decimal("0"),
        debt_amount=Decimal("5550.00"),
    )
    sale.sale_items.append(SaleItem(
        network=NetworkType.ORANGE,
        quantity=250,
        price_per_unit_applied=Decimal("22.2075"),
        subtotal=Decimal("5551.88"),
        cost_per_unit_snapshot=Decimal("22.2075"),
        cost_total=Decimal("5551.875"),
        margin_amount=Decimal("0.005"),
        is_cost_estimated=False,
    ))
    session.add(sale)
    session.commit()

    report = build_retail_margin_report(
        business_id=business.id, target_date=date.today()
    )

    assert report["totals"]["revenue"] == Decimal("5550.00")
    assert report["totals"]["commercial_margin"] == Decimal("0.0000")
    assert report["totals"]["rounding_adjustment"] == Decimal("-1.8750")
    assert report["totals"]["profit"] == Decimal("-1.875")
    assert report["losses"] == []


def test_estimated_cost_is_not_presented_as_definitive(app, session):
    owner, business, client = _retail_context(session)
    sale = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=business.id,
        client=client,
        sale_date=date.today(),
        total_amount_due=Decimal("2500"),
        cash_paid=Decimal("0"),
        debt_amount=Decimal("2500"),
    )
    sale.sale_items.append(SaleItem(
        network=NetworkType.AIRTEL,
        quantity=100,
        price_per_unit_applied=Decimal("25"),
        subtotal=Decimal("2500"),
        cost_per_unit_snapshot=Decimal("30"),
        cost_total=Decimal("3000"),
        margin_amount=Decimal("-500"),
        is_cost_estimated=True,
    ))
    session.add(sale)
    session.commit()

    report = build_retail_margin_report(
        business_id=business.id, target_date=date.today()
    )
    assert report["totals"]["has_estimated_cost"] is True
    assert report["losses"] == []
    assert report["estimated_sales"][0]["sale_id"] == sale.id

    browser = app.test_client()
    _login(browser, owner, business)
    page = browser.get("/rapports")
    assert page.status_code == 200
    assert "À vérifier" in page.get_data(as_text=True)


def test_manual_loss_requires_explicit_confirmation(app, session):
    owner, business, client = _retail_context(session)
    session.add(Stock(
        vendeur_id=owner.id,
        business_id=business.id,
        network=NetworkType.AIRTEL,
        balance=Decimal("100"),
        inventory_value=Decimal("2500"),
        average_cost_per_unit=Decimal("25"),
        buying_price_per_unit=Decimal("25"),
        selling_price_per_unit=Decimal("20"),
    ))
    session.commit()
    browser = app.test_client()
    _login(browser, owner, business)
    payload = {
        "client_choice": "existing",
        "existing_client_id": str(client.id),
        "sale_items-0-network": NetworkType.AIRTEL.name,
        "sale_items-0-quantity": "10",
        "sale_items-0-price_per_unit_applied": "20",
        "cash_paid": "0",
        "sale_date": date.today().isoformat(),
        "submit": "Vendre",
    }

    rejected = browser.post("/vente_stock", data=payload, follow_redirects=True)
    assert "Confirmer la vente à perte" in rejected.get_data(as_text=True)
    assert Sale.query.filter_by(business_id=business.id).count() == 0

    payload["confirm_loss"] = "y"
    accepted = browser.post("/vente_stock", data=payload)
    assert accepted.status_code == 302
    assert Sale.query.filter_by(business_id=business.id).count() == 1
