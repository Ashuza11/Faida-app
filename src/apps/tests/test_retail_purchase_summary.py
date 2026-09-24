from datetime import date, timedelta
from decimal import Decimal

from apps.businesses import create_business
from apps.models import BusinessType, NetworkType, RoleType, TransactionStatus, User
from apps.purchases import build_retail_purchase_summary, record_retail_purchase


def make_owner(session, suffix):
    owner = User(
        username=f"purchase-summary-{suffix}",
        phone=f"+243810008{suffix:03d}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    return owner


def login(client, user):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user.id)
        browser_session["_fresh"] = True


def add_purchase(session, *, business, owner, network, quantity, cost, day):
    purchase = record_retail_purchase(
        business=business,
        purchased_by=owner,
        network=network,
        quantity=quantity,
        unit_cost=Decimal(cost),
        intended_selling_price=Decimal(cost) + Decimal("1"),
        purchase_date=day,
    )
    session.flush()
    return purchase


def test_retail_purchase_summary_uses_exact_active_costs_and_business_date(session):
    selected_date = date(2026, 9, 24)
    owner = make_owner(session, 1)
    business = create_business(
        owner=owner, name="Retail summary", business_type=BusinessType.RETAIL
    )
    other_owner = make_owner(session, 2)
    other_business = create_business(
        owner=other_owner, name="Other retail", business_type=BusinessType.RETAIL
    )
    session.flush()

    add_purchase(
        session, business=business, owner=owner, network=NetworkType.AIRTEL,
        quantity=100, cost="20", day=selected_date,
    )
    add_purchase(
        session, business=business, owner=owner, network=NetworkType.AIRTEL,
        quantity=50, cost="22", day=selected_date,
    )
    add_purchase(
        session, business=business, owner=owner, network=NetworkType.ORANGE,
        quantity=20, cost="25", day=selected_date,
    )
    reversed_purchase = add_purchase(
        session, business=business, owner=owner, network=NetworkType.AFRICEL,
        quantity=10, cost="24", day=selected_date,
    )
    reversed_purchase.status = TransactionStatus.REVERSED
    add_purchase(
        session, business=business, owner=owner, network=NetworkType.VODACOM,
        quantity=10, cost="24", day=selected_date - timedelta(days=1),
    )
    add_purchase(
        session, business=other_business, owner=other_owner,
        network=NetworkType.AIRTEL, quantity=1000, cost="30", day=selected_date,
    )
    session.commit()

    summary = build_retail_purchase_summary(
        business=business, target_date=selected_date
    )

    assert summary["total_units"] == 170
    assert summary["total_cost"] == Decimal("3600.000000000000")
    assert [row["network"] for row in summary["networks"]] == [
        NetworkType.AIRTEL, NetworkType.ORANGE
    ]
    assert summary["networks"][0]["total_units"] == 150
    assert summary["networks"][0]["total_cost"] == Decimal("3100.000000000000")


def test_retail_purchase_summary_appears_on_history_and_dashboard(app, session):
    selected_date = date(2026, 9, 20)
    owner = make_owner(session, 3)
    business = create_business(
        owner=owner, name="Visible summary", business_type=BusinessType.RETAIL
    )
    session.flush()
    purchase = add_purchase(
        session, business=business, owner=owner, network=NetworkType.AIRTEL,
        quantity=100, cost="20", day=selected_date,
    )
    session.commit()
    client = app.test_client()
    login(client, owner)
    with client.session_transaction() as browser_session:
        browser_session["active_business_id"] = business.id

    history = client.get(f"/achat_stock?date={selected_date.isoformat()}")
    dashboard = client.get(f"/index?date={selected_date.isoformat()}")

    assert history.status_code == 200
    assert dashboard.status_code == 200
    assert b"2,000.00 FC" in history.data
    assert b"2,000.00 FC" in dashboard.data
    assert f"{purchase.amount_purchased} unit".encode() in history.data

