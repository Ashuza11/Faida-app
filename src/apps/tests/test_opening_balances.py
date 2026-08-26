from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.businesses import create_business
from apps.main.utils import get_daily_report_data, get_utc_range_for_date
from apps.models import (
    BusinessApprovalStatus,
    BusinessType,
    DailyStockReport,
    NetworkType,
    RoleType,
    Sale,
    SaleItem,
    Stock,
    StockOpeningBalance,
    StockPurchase,
    User,
)
from apps.opening_balances import OpeningBalanceError, save_opening_balances
from apps.inventory import consume_stock
from apps.purchases import record_retail_purchase


def setup_retail(session, suffix=1):
    owner = User(
        username=f"opening-owner-{suffix}",
        phone=f"+243810008{suffix:03d}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner,
        name=f"Opening Retail {suffix}",
        business_type=BusinessType.RETAIL,
    )
    session.flush()
    return owner, business


def empty_updates():
    return {network: (None, None) for network in NetworkType}


def test_opening_balance_sets_exact_quantity_and_inventory_cost(session):
    owner, business = setup_retail(session)
    updates = empty_updates()
    updates[NetworkType.AIRTEL] = (1000, Decimal("20.25"))

    entries = save_opening_balances(
        business=business,
        recorded_by=owner,
        balance_date=date.today(),
        updates=updates,
    )
    session.flush()

    opening = entries[0]
    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    assert opening.unit_cost == Decimal("20.250000000000")
    assert opening.actual_total_cost == Decimal("20250.000000000000")
    assert opening.is_cost_estimated is False
    assert stock.balance == 1000
    assert stock.inventory_value == Decimal("20250.000000000000")
    assert stock.average_cost_per_unit == Decimal("20.250000000000")
    unit_cost, total_cost = consume_stock(stock=stock, quantity=10)
    assert unit_cost == Decimal("20.250000000000")
    assert total_cost == Decimal("202.500000000000")


def test_blank_network_is_unchanged_and_explicit_zero_clears_one_network(session):
    owner, business = setup_retail(session, suffix=2)
    initial = empty_updates()
    initial[NetworkType.AIRTEL] = (100, Decimal("20"))
    initial[NetworkType.ORANGE] = (200, Decimal("21"))
    save_opening_balances(
        business=business, recorded_by=owner,
        balance_date=date.today(), updates=initial,
    )
    session.flush()

    correction = empty_updates()
    correction[NetworkType.AIRTEL] = (0, None)
    save_opening_balances(
        business=business, recorded_by=owner,
        balance_date=date.today(), updates=correction,
    )
    session.flush()

    airtel = StockOpeningBalance.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    orange = StockOpeningBalance.query.filter_by(
        business_id=business.id, network=NetworkType.ORANGE
    ).one()
    assert airtel.quantity == 0
    assert airtel.actual_total_cost == 0
    assert orange.quantity == 200
    assert orange.actual_total_cost == Decimal("4200.000000000000")


def test_legacy_estimated_cost_is_not_silently_confirmed(session):
    owner, business = setup_retail(session, suffix=10)
    estimated = StockOpeningBalance(
        vendeur_id=owner.id, business_id=business.id,
        network=NetworkType.ORANGE, balance_date=date.today(),
        quantity=500, unit_cost=Decimal("20"),
        actual_total_cost=Decimal("10000"), is_cost_estimated=True,
        set_by_id=owner.id,
    )
    session.add(estimated)
    session.flush()
    updates = empty_updates()
    updates[NetworkType.ORANGE] = (500, None)
    updates[NetworkType.AIRTEL] = (100, Decimal("21"))

    save_opening_balances(
        business=business, recorded_by=owner,
        balance_date=date.today(), updates=updates,
    )
    session.flush()

    assert estimated.is_cost_estimated is True
    assert estimated.unit_cost == Decimal("20")


def test_today_reconciliation_includes_purchases_by_business_date(session):
    owner, business = setup_retail(session, suffix=3)
    record_retail_purchase(
        business=business, purchased_by=owner,
        network=NetworkType.AIRTEL, quantity=100,
        unit_cost=Decimal("22"), intended_selling_price=Decimal("25"),
        purchase_date=date.today(),
    )
    session.flush()
    updates = empty_updates()
    updates[NetworkType.AIRTEL] = (1000, Decimal("20"))

    save_opening_balances(
        business=business, recorded_by=owner,
        balance_date=date.today(), updates=updates,
    )
    session.flush()

    stock = Stock.query.filter_by(
        business_id=business.id, network=NetworkType.AIRTEL
    ).one()
    assert stock.balance == 1100
    assert stock.inventory_value == Decimal("22200.000000000000")
    assert stock.average_cost_per_unit == Decimal("20.181818181818")
    assert stock.buying_price_per_unit == Decimal("22.000000000000")


def test_sale_blocks_rewriting_dependent_opening_cost(session):
    owner, business = setup_retail(session, suffix=4)
    updates = empty_updates()
    updates[NetworkType.AIRTEL] = (1000, Decimal("20"))
    save_opening_balances(
        business=business, recorded_by=owner,
        balance_date=date.today(), updates=updates,
    )
    sale = Sale(
        seller_id=owner.id, vendeur_id=owner.id, business_id=business.id,
        sale_date=date.today(), total_amount_due=Decimal("25"),
        cash_paid=0, debt_amount=Decimal("25"),
    )
    sale.sale_items.append(SaleItem(
        network=NetworkType.AIRTEL, quantity=1,
        price_per_unit_applied=Decimal("25"), subtotal=Decimal("25"),
        cost_per_unit_snapshot=Decimal("20"), cost_total=Decimal("20"),
        margin_amount=Decimal("5"), is_cost_estimated=False,
    ))
    session.add(sale)
    session.flush()
    correction = empty_updates()
    correction[NetworkType.AIRTEL] = (900, Decimal("20"))

    with pytest.raises(OpeningBalanceError, match="ventes utilisent déjà"):
        save_opening_balances(
            business=business, recorded_by=owner,
            balance_date=date.today(), updates=correction,
        )


def test_past_purchase_blocks_rewriting_historical_opening(session):
    owner, business = setup_retail(session, suffix=7)
    target = date.today() - timedelta(days=3)
    opening = StockOpeningBalance(
        vendeur_id=owner.id, business_id=business.id,
        network=NetworkType.AIRTEL, balance_date=target,
        quantity=1000, unit_cost=Decimal("20"),
        actual_total_cost=Decimal("20000"), is_cost_estimated=False,
        set_by_id=owner.id,
    )
    stock = Stock(
        vendeur_id=owner.id, business_id=business.id,
        network=NetworkType.AIRTEL, balance=1100,
        buying_price_per_unit=Decimal("20"), selling_price_per_unit=Decimal("25"),
        inventory_value=Decimal("22000"), average_cost_per_unit=Decimal("20"),
    )
    session.add_all([opening, stock])
    session.flush()
    session.add(StockPurchase(
        purchased_by_id=owner.id, stock_item=stock,
        network=NetworkType.AIRTEL, amount_purchased=100,
        buying_price_at_purchase=Decimal("20"),
        selling_price_at_purchase=Decimal("25"),
        actual_total_cost=Decimal("2000"),
        purchase_date=target + timedelta(days=1),
    ))
    session.flush()
    correction = empty_updates()
    correction[NetworkType.AIRTEL] = (900, Decimal("20"))

    with pytest.raises(OpeningBalanceError, match="enregistré après cette ouverture"):
        save_opening_balances(
            business=business, recorded_by=owner,
            balance_date=target, updates=correction,
        )


def test_report_groups_purchase_by_purchase_date_not_creation_time(app, session):
    owner, business = setup_retail(session, suffix=5)
    target = date.today() - timedelta(days=2)
    stock = Stock(
        vendeur_id=owner.id, business_id=business.id,
        network=NetworkType.AIRTEL, balance=100,
        buying_price_per_unit=Decimal("20"), selling_price_per_unit=Decimal("25"),
        inventory_value=Decimal("2000"), average_cost_per_unit=Decimal("20"),
    )
    session.add(stock)
    session.flush()
    session.add(StockPurchase(
        purchased_by_id=owner.id, stock_item=stock,
        network=NetworkType.AIRTEL, amount_purchased=100,
        buying_price_at_purchase=Decimal("20"),
        selling_price_at_purchase=Decimal("25"),
        actual_total_cost=Decimal("2000"), purchase_date=target,
        created_at=datetime.now(timezone.utc),
    ))
    session.flush()
    start, end = get_utc_range_for_date(target)

    report, _, _ = get_daily_report_data(
        app, target, start, end,
        vendeur_id=owner.id, business_id=business.id,
    )

    assert report[NetworkType.AIRTEL.name]["purchased_stock"] == 100


def test_selected_date_loads_existing_values_in_retail_form(app, session):
    owner, business = setup_retail(session, suffix=6)
    target = date.today() - timedelta(days=5)
    session.add(StockOpeningBalance(
        vendeur_id=owner.id, business_id=business.id,
        network=NetworkType.ORANGE, balance_date=target,
        quantity=500, unit_cost=Decimal("21"),
        actual_total_cost=Decimal("10500"), is_cost_estimated=False,
        set_by_id=owner.id,
    ))
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get(f"/stock/ouverture?date={target.isoformat()}")

    assert response.status_code == 200
    assert f'value="{target.isoformat()}"'.encode() in response.data
    assert b'value="500"' in response.data
    assert b'value="21.000000000000"' in response.data
    assert b"30 derni\xc3\xa8res dates" in response.data


def test_current_stock_fallback_is_not_labeled_as_yesterday(app, session):
    owner, business = setup_retail(session, suffix=8)
    session.add(Stock(
        vendeur_id=owner.id, business_id=business.id,
        network=NetworkType.AIRTEL, balance=100,
        buying_price_per_unit=Decimal("20"), selling_price_per_unit=Decimal("25"),
        inventory_value=Decimal("2000"), average_cost_per_unit=Decimal("20"),
    ))
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get("/stock/ouverture")

    assert "Stock actuel estimé".encode() in response.data
    assert "Solde d'hier".encode() not in response.data


def test_opening_route_refreshes_existing_archived_report(app, session):
    owner, business = setup_retail(session, suffix=11)
    target = date.today() - timedelta(days=7)
    archived = DailyStockReport(
        vendeur_id=owner.id, business_id=business.id,
        report_date=target, network=NetworkType.AIRTEL,
        initial_stock_balance=0, purchased_stock_amount=0,
        sold_stock_amount=0, final_stock_balance=0,
        virtual_value=0, debt_amount=0,
    )
    session.add(archived)
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.post(
        "/stock/ouverture",
        data={
            "balance_date": target.isoformat(),
            "airtel": "300",
            "airtel_cost": "20",
            "submit": "Enregistrer",
        },
    )

    assert response.status_code == 302
    session.refresh(archived)
    assert archived.initial_stock_balance == 300
    assert archived.final_stock_balance == 300


def test_wholesale_opening_balance_is_stored_in_its_own_business(session):
    owner, retail = setup_retail(session, suffix=9)
    wholesale = create_business(
        owner=owner, name="Wholesale opening",
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    updates = empty_updates()
    updates[NetworkType.AIRTEL] = (100, Decimal("0.009"))

    entries = save_opening_balances(
        business=wholesale, recorded_by=owner,
        balance_date=date.today(), updates=updates,
    )
    session.flush()

    assert StockOpeningBalance.query.filter_by(business_id=retail.id).count() == 0
    assert entries[0].business_id == wholesale.id
    assert entries[0].unit_cost == Decimal("0.009000000000")
    wholesale_stock = Stock.query.filter_by(
        business_id=wholesale.id,
        network=NetworkType.AIRTEL,
    ).one()
    assert wholesale_stock.balance == 100
    assert wholesale_stock.inventory_value == Decimal("0.900000000000")


def test_pending_wholesale_cannot_set_opening_stock(session):
    owner, _ = setup_retail(session, suffix=13)
    wholesale = create_business(
        owner=owner,
        name="Pending wholesale opening",
        business_type=BusinessType.WHOLESALE,
    )
    session.flush()
    updates = empty_updates()
    updates[NetworkType.AIRTEL] = (100, Decimal("0.009"))

    with pytest.raises(OpeningBalanceError, match="approuvé"):
        save_opening_balances(
            business=wholesale,
            recorded_by=owner,
            balance_date=date.today(),
            updates=updates,
        )


def test_opening_history_limits_by_date_not_network_entry(app, session):
    owner, business = setup_retail(session, suffix=12)
    oldest = date.today() - timedelta(days=31)
    for offset in range(31):
        balance_date = oldest + timedelta(days=offset)
        for network in (NetworkType.AIRTEL, NetworkType.ORANGE):
            session.add(StockOpeningBalance(
                vendeur_id=owner.id, business_id=business.id,
                network=network, balance_date=balance_date,
                quantity=100, unit_cost=Decimal("20"),
                actual_total_cost=Decimal("2000"), is_cost_estimated=False,
                set_by_id=owner.id,
            ))
    session.commit()
    browser = app.test_client()
    with browser.session_transaction() as browser_session:
        browser_session["_user_id"] = str(owner.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id

    response = browser.get("/stock/ouverture")

    assert response.status_code == 200
    assert oldest.strftime("%d/%m/%Y").encode() not in response.data
    assert (oldest + timedelta(days=1)).strftime("%d/%m/%Y").encode() in response.data
