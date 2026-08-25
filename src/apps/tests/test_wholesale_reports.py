from datetime import date, timedelta
from decimal import Decimal

from apps.businesses import create_business
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    Client,
    NetworkType,
    RoleType,
    Stock,
    StockOpeningBalance,
    User,
)
from apps.payments import collect_client_debt
from apps.opening_balances import save_opening_balances
from apps.purchases import record_wholesale_purchase
from apps.sales import record_wholesale_sale
from apps.wholesale_reports import build_wholesale_daily_report


def setup_report_business(session, suffix):
    owner = User(
        username=f"report-owner-{suffix}",
        phone=f"+243810003{suffix:03d}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner,
        name=f"Report Wholesale {suffix}",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    client = Client(
        name="Report Retailer",
        vendeur_id=owner.id,
        business_id=business.id,
    )
    session.add(client)
    session.flush()
    return owner, business, client


def test_daily_report_separates_sale_and_cash_dates(session):
    owner, business, client = setup_report_business(session, 1)
    sale_day = date.today() - timedelta(days=2)
    collection_day = sale_day + timedelta(days=1)
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.00900"),
        purchase_date=sale_day - timedelta(days=1),
    )
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.01000"),
        purchase_date=sale_day,
    )
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=500,
        cash_received=Decimal("2.00"),
        sale_date=sale_day,
        custom_unit_price=Decimal("0.01100"),
    )
    collect_client_debt(
        business=business,
        client=client,
        amount=Decimal("1.00"),
        recorded_by=owner,
        payment_date=collection_day,
    )
    session.flush()

    sale_report = build_wholesale_daily_report(
        business=business, target_date=sale_day
    )
    airtel = sale_report["networks"][NetworkType.AIRTEL.name]
    assert airtel["opening"] == 1000
    assert airtel["purchased"] == 1000
    assert airtel["purchase_cost"] == Decimal("10.000000000000")
    assert airtel["sold"] == 500
    assert airtel["closing"] == 1500
    assert sale_report["totals"]["revenue"] == Decimal("5.50")
    assert sale_report["totals"]["cost"] == Decimal("4.750000000000")
    assert sale_report["totals"]["sales_margin"] == Decimal("0.750000000000")
    assert sale_report["totals"]["cash_collected"] == Decimal("2.00")
    assert sale_report["totals"]["new_debt"] == Decimal("3.50")
    assert sale_report["totals"]["old_debt_collected"] == 0
    assert sale_report["totals"]["remaining_debt"] == Decimal("3.50")

    collection_report = build_wholesale_daily_report(
        business=business, target_date=collection_day
    )
    assert collection_report["totals"]["revenue"] == 0
    assert collection_report["totals"]["cash_collected"] == Decimal("1.00")
    assert collection_report["totals"]["old_debt_collected"] == Decimal("1.00")
    assert collection_report["totals"]["remaining_debt"] == Decimal("2.50")
    assert collection_report["totals"]["collected_margin"].quantize(
        Decimal("0.000001")
    ) == Decimal("0.136364")


def test_daily_report_is_business_isolated_and_route_renders(app, session):
    owner, business, client = setup_report_business(session, 2)
    other_owner, other_business, other_client = setup_report_business(session, 3)
    target = date.today()
    for target_business, target_owner, target_client in (
        (business, owner, client),
        (other_business, other_owner, other_client),
    ):
        record_wholesale_purchase(
            business=target_business,
            purchased_by=target_owner,
            network=NetworkType.ORANGE,
            quantity=1000,
            custom_unit_cost=Decimal("0.00900"),
            purchase_date=target,
        )
        record_wholesale_sale(
            business=target_business,
            sold_by=target_owner,
            client=target_client,
            network=NetworkType.ORANGE,
            quantity=100,
            cash_received=Decimal("1.00"),
            sale_date=target,
            custom_unit_price=Decimal("0.01000"),
        )
    session.commit()

    report = build_wholesale_daily_report(
        business=business, target_date=target
    )
    assert report["totals"]["purchased"] == 1000
    assert report["totals"]["sold"] == 100
    assert report["totals"]["revenue"] == Decimal("1.00")

    client_app = app.test_client()
    with client_app.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id
    response = client_app.get(
        f"/businesses/wholesale/report?date={target.isoformat()}"
    )
    assert response.status_code == 200
    assert b"Rapport journalier" in response.data
    assert b'id="report-home-btn"' in response.data
    assert b'id="report-pdf-btn"' in response.data
    assert b"Afficher" not in response.data
    assert b"Filtrer" not in response.data
    assert b"$1.00" in response.data

    pdf = client_app.get(
        f"/businesses/wholesale/report.pdf?date={target.isoformat()}"
    )
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF")


def test_dated_opening_anchor_separates_incomplete_previous_day(session):
    owner, business, client = setup_report_business(session, 4)
    first_day = date.today() - timedelta(days=1)
    second_day = first_day + timedelta(days=1)
    third_day = second_day + timedelta(days=1)
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=1000,
        custom_unit_cost=Decimal("0.00900"),
        purchase_date=first_day,
    )
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=100,
        cash_received=Decimal("0"),
        sale_date=first_day,
        custom_unit_price=Decimal("0.01000"),
    )
    updates = {network: (None, None) for network in NetworkType}
    updates[NetworkType.AIRTEL] = (700, Decimal("0.00900"))
    save_opening_balances(
        business=business,
        recorded_by=owner,
        balance_date=second_day,
        updates=updates,
    )
    record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=NetworkType.AIRTEL,
        quantity=100,
        custom_unit_cost=Decimal("0.00900"),
        purchase_date=second_day,
    )
    record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=NetworkType.AIRTEL,
        quantity=50,
        cash_received=Decimal("0"),
        sale_date=second_day,
        custom_unit_price=Decimal("0.01000"),
    )
    session.flush()

    first = build_wholesale_daily_report(
        business=business, target_date=first_day
    )["networks"][NetworkType.AIRTEL.name]
    second = build_wholesale_daily_report(
        business=business, target_date=second_day
    )["networks"][NetworkType.AIRTEL.name]
    third = build_wholesale_daily_report(
        business=business, target_date=third_day
    )["networks"][NetworkType.AIRTEL.name]

    assert first["opening"] == 0
    assert first["closing"] == 900
    assert second["opening"] == 700
    assert second["closing"] == 750
    assert third["opening"] == 750


def test_wholesale_opening_stock_route_uses_usd_ui(app, session):
    owner, business, _ = setup_report_business(session, 5)
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get("/businesses/wholesale/opening-stock")

    assert response.status_code == 200
    assert b"Stock d'ouverture" in response.data
    assert b"Grossiste" in response.data
    assert b"Valeur totale (USD)" in response.data
    assert b"Co\xc3\xbbt par unit\xc3\xa9 (FC)" not in response.data

    saved = browser.post(
        "/businesses/wholesale/opening-stock",
        data={
            "balance_date": date.today().isoformat(),
            "airtel": "10650",
            "airtel_total": "100",
        },
    )
    assert saved.status_code == 302
    opening = StockOpeningBalance.query.filter_by(
        business_id=business.id,
        network=NetworkType.AIRTEL,
        balance_date=date.today(),
    ).one()
    assert opening.business_id == business.id
    assert opening.quantity == 10650
    assert opening.unit_cost == Decimal("0.009389671362")
    assert opening.actual_total_cost == Decimal("100.000000000000")
    stock = Stock.query.filter_by(
        business_id=business.id,
        network=NetworkType.AIRTEL,
    ).one()
    assert stock.balance == 10650
    assert stock.inventory_value == Decimal("100.000000000000")
