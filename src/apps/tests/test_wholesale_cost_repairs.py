from datetime import date, timedelta
from decimal import Decimal

from flask import g

from apps.businesses import create_business
from apps.dates import business_local_date
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    Client,
    NetworkType,
    RoleType,
    Sale,
    SaleItem,
    StockOpeningBalance,
    User,
    WholesaleSaleCostCorrection,
)
from apps.payments import collect_client_debt
from apps.purchases import record_wholesale_purchase
from apps.sales import record_wholesale_sale
from apps.wholesale_costs import suggested_historical_unit_cost
from apps.wholesale_reports import build_wholesale_daily_report


def make_user(session, suffix, role=RoleType.VENDEUR):
    user = User(
        username=f"cost-repair-{suffix}",
        phone=f"+243810008{suffix:03d}",
        role=role,
    )
    user.set_password("safe-password")
    session.add(user)
    session.flush()
    return user


def make_wholesale(session, owner):
    business = create_business(
        owner=owner,
        name="Ets Cost Repair",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    return business


def login(browser, user, business_id=None):
    g.pop("_login_user", None)
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user.id)
        browser_session["_fresh"] = True
        if business_id is not None:
            browser_session["active_business_id"] = business_id


def test_cash_margin_warning_identifies_old_sale_and_admin_repairs_only_cost(
    app, session
):
    owner = make_user(session, 1)
    admin = make_user(session, 2, RoleType.PLATFORM_ADMIN)
    business = make_wholesale(session, owner)
    client = Client(
        name="Guillaume", vendeur_id=owner.id, business_id=business.id
    )
    session.add(client)
    sale_day = business_local_date() - timedelta(days=2)
    collection_day = sale_day + timedelta(days=1)
    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.00900"),
        purchase_date=sale_day - timedelta(days=1),
    )
    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=100,
        cash_received=Decimal("0"),
        sale_date=sale_day,
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()
    item = sale.sale_items[0]
    item.cost_per_unit_snapshot = Decimal("100")
    item.cost_total = Decimal("10000")
    item.margin_amount = item.subtotal - item.cost_total
    collect_client_debt(
        business=business,
        client=client,
        amount=Decimal("1.00"),
        recorded_by=owner,
        payment_date=collection_day,
    )
    session.commit()
    paid_before = sale.cash_paid
    debt_before = sale.debt_amount

    report = build_wholesale_daily_report(
        business=business, target_date=collection_day
    )
    assert report["totals"]["sales_margin_has_anomaly"] is False
    assert report["totals"]["collected_margin_has_anomaly"] is True
    assert report["cost_anomalies"]["collection_sale_ids"] == [sale.id]
    detail = report["cost_anomalies"]["details"][0]
    assert detail["sale_id"] == sale.id
    assert detail["client_name"] == "Guillaume"
    assert detail["sale_date"] == sale_day
    assert detail["network"] == NetworkType.AIRTEL
    assert detail["reason_code"] == "cost_too_high"
    assert detail["affects_collected_margin"] is True

    vendor_browser = app.test_client()
    login(vendor_browser, owner, business.id)
    warning = vendor_browser.get(
        f"/businesses/wholesale/sales?date={collection_day.isoformat()}"
    )
    warning_html = warning.data.decode()
    assert warning.status_code == 200
    assert "Paiements et ventes enregistrés" in warning_html
    assert f"Ancienne vente #{sale.id}" in warning_html
    assert f"Vente #{sale.id} · Guillaume" in warning_html
    assert "Airtel" in warning_html
    assert sale_day.strftime("%d/%m/%Y") in warning_html
    assert "anormalement élevé" in warning_html
    assert "N'annulez le paiement que si son montant est incorrect" in warning_html
    assert f"#sale-{sale.id}" in warning_html
    assert f"#vente-{sale.id}" in warning_html

    admin_browser = app.test_client()
    login(admin_browser, admin)
    anomaly_page = admin_browser.get("/admin/wholesale-costs")
    anomaly_html = anomaly_page.data.decode()
    assert anomaly_page.status_code == 200, anomaly_page.location
    assert f"Vente #{sale.id} · Guillaume" in anomaly_html
    assert f"Achat #{purchase.id}" in anomaly_html
    assert "Suggestion estimée" in anomaly_html

    repaired = admin_browser.post(
        f"/admin/wholesale-costs/{item.id}/repair",
        data={
            "unit_cost": "0.009",
            "confidence": "estimated",
            "note": "Calculé depuis l'achat fournisseur correspondant",
        },
        follow_redirects=True,
    )
    assert repaired.status_code == 200
    assert "Coût corrigé" in repaired.data.decode()
    session.refresh(item)
    session.refresh(sale)
    correction = WholesaleSaleCostCorrection.query.one()
    assert correction.old_unit_cost == Decimal("100.000000000000")
    assert correction.new_unit_cost == Decimal("0.009000000000")
    assert correction.source == f"Achat #{purchase.id} du {purchase.purchase_date:%d/%m/%Y}"
    assert correction.confidence == "estimated"
    assert item.is_cost_estimated is True
    assert item.cost_total == Decimal("0.900000000000")
    assert item.margin_amount == Decimal("0.100000000000")
    assert sale.cash_paid == paid_before
    assert sale.debt_amount == debt_before

    repaired_report = build_wholesale_daily_report(
        business=business, target_date=collection_day
    )
    assert repaired_report["totals"]["collected_margin_has_anomaly"] is False
    assert repaired_report["totals"]["collected_margin"] == Decimal(
        "0.100000000000"
    )


def test_historical_cost_suggestion_can_use_opening_stock(session):
    owner = make_user(session, 3)
    business = make_wholesale(session, owner)
    client = Client(name="Opening Client", vendeur_id=owner.id, business_id=business.id)
    session.add(client)
    sale_day = date.today() - timedelta(days=3)
    opening = StockOpeningBalance(
        vendeur_id=owner.id,
        business_id=business.id,
        network=NetworkType.ORANGE,
        balance_date=sale_day,
        quantity=Decimal("10650"),
        unit_cost=Decimal("0.009389671362"),
        actual_total_cost=Decimal("100"),
        is_cost_estimated=False,
        set_by_id=owner.id,
    )
    sale = Sale(
        sale_date=sale_day,
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=business.id,
        client=client,
        total_amount_due=Decimal("0.95"),
        cash_paid=Decimal("0"),
        debt_amount=Decimal("0.95"),
        initial_cash_paid=Decimal("0"),
    )
    item = SaleItem(
        sale=sale,
        network=NetworkType.ORANGE,
        quantity=100,
        price_per_unit_applied=Decimal("0.00950"),
        subtotal=Decimal("0.95"),
        cost_per_unit_snapshot=Decimal("0"),
        cost_total=Decimal("0"),
        margin_amount=Decimal("0.95"),
        is_cost_estimated=True,
    )
    session.add_all([opening, sale, item])
    session.flush()

    suggestion = suggested_historical_unit_cost(item)

    assert suggestion["source_kind"] == "opening"
    assert suggestion["unit_cost"] == Decimal("0.009389671362")
    assert "Stock d'ouverture" in suggestion["source"]
