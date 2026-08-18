from datetime import date, datetime, timezone
from decimal import Decimal

from apps.businesses import create_business
from apps.main.utils import (
    get_daily_report_data,
    get_utc_range_for_date,
    update_daily_reports,
)
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    Client,
    DailyOverallReport,
    NetworkType,
    RoleType,
    Sale,
    SaleItem,
    Stock,
    StockPurchase,
    User,
)


def add_transactions(session, *, business, owner, client_name, purchased, sold):
    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one_or_none()
    if stock is None:
        stock = Stock(
            vendeur_id=owner.id,
            business_id=business.id,
            network=NetworkType.AIRTEL,
            balance=Decimal("0"),
            buying_price_per_unit=Decimal("1.00"),
            selling_price_per_unit=Decimal("1.00"),
        )
        session.add(stock)
        session.flush()
    client = Client(
        name=client_name,
        vendeur_id=owner.id,
        business_id=business.id,
    )
    session.add(client)
    session.add(
        StockPurchase(
            purchased_by_id=owner.id,
            stock_item=stock,
            network=NetworkType.AIRTEL,
            buying_price_at_purchase=Decimal("1.00"),
            selling_price_at_purchase=Decimal("1.00"),
            actual_total_cost=Decimal(purchased),
            amount_purchased=purchased,
            purchase_date=date.today(),
            created_at=datetime.now(timezone.utc),
        )
    )
    sale = Sale(
        seller_id=owner.id,
        vendeur_id=owner.id,
        business_id=business.id,
        client=client,
        sale_date=date.today(),
        total_amount_due=Decimal(sold),
        cash_paid=Decimal("0"),
        debt_amount=Decimal(sold),
    )
    sale.sale_items.append(
        SaleItem(
            network=NetworkType.AIRTEL,
            quantity=sold,
            price_per_unit_applied=Decimal("1.00"),
            subtotal=Decimal(sold),
            cost_per_unit_snapshot=Decimal("1.00"),
            cost_total=Decimal(sold),
            margin_amount=Decimal("0"),
            is_cost_estimated=False,
        )
    )
    session.add(sale)
    session.flush()
    return client


def test_retail_report_excludes_same_owners_wholesale_ledger(app, session):
    owner = User(
        username="report-owner",
        phone="+243810009901",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    retail = create_business(
        owner=owner, name="Retail Ledger", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner,
        name="Wholesale Ledger",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    add_transactions(
        session,
        business=retail,
        owner=owner,
        client_name="Retail-only customer",
        purchased=100,
        sold=25,
    )
    add_transactions(
        session,
        business=wholesale,
        owner=owner,
        client_name="Wholesale-only customer",
        purchased=900,
        sold=400,
    )
    session.commit()

    start_utc, end_utc = get_utc_range_for_date(date.today())
    report, total_sales, total_debt = get_daily_report_data(
        app,
        date.today(),
        start_utc,
        end_utc,
        vendeur_id=owner.id,
        business_id=retail.id,
    )

    assert report["AIRTEL"]["purchased_stock"] == Decimal("100")
    assert report["AIRTEL"]["sold_stock_quantity"] == Decimal("25")
    assert total_sales == Decimal("25")
    assert total_debt == Decimal("25")

    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = retail.id
    response = client.get("/rapports")

    assert response.status_code == 200
    assert b"Retail-only customer" in response.data
    assert b"Wholesale-only customer" not in response.data

    update_daily_reports(
        app,
        report_date_to_update=date.today(),
        vendeur_id=owner.id,
        business_id=retail.id,
    )
    update_daily_reports(
        app,
        report_date_to_update=date.today(),
        vendeur_id=owner.id,
        business_id=wholesale.id,
    )
    archived = DailyOverallReport.query.filter_by(
        vendeur_id=owner.id, report_date=date.today()
    ).all()
    assert {report.business_id for report in archived} == {retail.id, wholesale.id}
