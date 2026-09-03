from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from apps.businesses import create_business
from apps.models import (
    BusinessApprovalStatus,
    BusinessMembership,
    BusinessType,
    CashInflow,
    CashOutflow,
    CurrencyCode,
    MembershipRole,
    RoleType,
    User,
    WholesaleCashDirection,
    WholesaleCashEntry,
)
from apps.wholesale_cashbook import (
    CashbookConversionError,
    build_cashbook_totals,
    convert_cashbook_totals,
)


def make_user(session, suffix, role=RoleType.VENDEUR, vendeur_id=None):
    user = User(
        username=f"cashbook-user-{suffix}",
        phone=f"+243810008{suffix:03d}",
        role=role,
        vendeur_id=vendeur_id,
    )
    user.set_password("safe-password")
    session.add(user)
    session.flush()
    return user


def make_wholesale(session, owner, name):
    business = create_business(
        owner=owner,
        name=name,
        business_type=BusinessType.WHOLESALE,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    session.flush()
    return business


def login_to_business(client, user, business):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user.id)
        browser_session["_fresh"] = True
        browser_session["active_business_id"] = business.id


def movement(direction, amount, currency):
    return SimpleNamespace(
        direction=direction,
        amount=Decimal(amount),
        currency_code=currency,
    )


def test_cashbook_totals_preserve_currencies_and_convert_without_mutating():
    entries = [
        movement(WholesaleCashDirection.INFLOW, "40000", CurrencyCode.CDF),
        movement(WholesaleCashDirection.INFLOW, "50000", CurrencyCode.CDF),
        movement(WholesaleCashDirection.OUTFLOW, "10000", CurrencyCode.CDF),
        movement(WholesaleCashDirection.OUTFLOW, "58", CurrencyCode.USD),
    ]

    totals = build_cashbook_totals(entries)
    converted = convert_cashbook_totals(
        totals, target_currency=CurrencyCode.CDF, cdf_per_usd="2850"
    )

    assert totals[CurrencyCode.CDF] == {
        "inflow": Decimal("90000"),
        "outflow": Decimal("10000"),
        "balance": Decimal("80000"),
    }
    assert totals[CurrencyCode.USD]["balance"] == Decimal("-58")
    assert converted["inflow"] == Decimal("90000.00")
    assert converted["outflow"] == Decimal("175300.00")
    assert converted["balance"] == Decimal("-85300.00")
    assert totals[CurrencyCode.USD]["outflow"] == Decimal("58")


def test_cashbook_rejects_invalid_exchange_rate():
    totals = build_cashbook_totals([])

    for rate in ("0", "-1", "not-a-rate", "NaN"):
        try:
            convert_cashbook_totals(
                totals, target_currency=CurrencyCode.USD, cdf_per_usd=rate
            )
        except CashbookConversionError:
            pass
        else:
            raise AssertionError(f"rate {rate!r} should be rejected")


def test_owner_records_cashbook_entry_separately_from_sales_cash(app, session):
    owner = make_user(session, 1)
    business = make_wholesale(session, owner, "Caisse propriétaire")
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, business)
    movement_date = date(2026, 9, 3)

    response = browser.post(
        f"/businesses/wholesale/cashbook?date={movement_date.isoformat()}",
        data={
            "description": "Nanga",
            "direction": "INFLOW",
            "amount": "40000",
            "currency_code": "CDF",
            "entry_date": movement_date.isoformat(),
        },
    )

    assert response.status_code == 302
    entry = WholesaleCashEntry.query.one()
    assert entry.business_id == business.id
    assert entry.recorded_by_id == owner.id
    assert entry.description == "Nanga"
    assert entry.amount == Decimal("40000.00")
    assert entry.currency_code == CurrencyCode.CDF
    assert entry.direction == WholesaleCashDirection.INFLOW
    assert CashInflow.query.count() == 0
    assert CashOutflow.query.count() == 0

    page = browser.get(response.headers["Location"]).get_data(as_text=True)
    assert "Nanga" in page
    assert "40,000.00 FC" in page
    assert "Cette caisse est séparée des ventes" in page


def test_cashbook_filters_by_date_and_current_business(app, session):
    owner = make_user(session, 2)
    first = make_wholesale(session, owner, "Première caisse")
    second = make_wholesale(session, owner, "Deuxième caisse")
    selected = date(2026, 9, 3)
    session.add_all([
        WholesaleCashEntry(
            business_id=first.id, recorded_by_id=owner.id,
            entry_date=selected, direction=WholesaleCashDirection.INFLOW,
            amount=Decimal("100"), currency_code=CurrencyCode.USD,
            description="Visible aujourd'hui",
        ),
        WholesaleCashEntry(
            business_id=first.id, recorded_by_id=owner.id,
            entry_date=selected - timedelta(days=1),
            direction=WholesaleCashDirection.INFLOW, amount=Decimal("200"),
            currency_code=CurrencyCode.USD, description="Autre date",
        ),
        WholesaleCashEntry(
            business_id=second.id, recorded_by_id=owner.id,
            entry_date=selected, direction=WholesaleCashDirection.OUTFLOW,
            amount=Decimal("300"), currency_code=CurrencyCode.USD,
            description="Autre mode",
        ),
    ])
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, first)

    response = browser.get(
        f"/businesses/wholesale/cashbook?date={selected.isoformat()}"
    )
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Visible aujourd" in page
    assert "Autre date" not in page
    assert "Autre mode" not in page
    assert 'onchange="this.form.submit()"' in page


def test_explicit_stockeur_member_can_record_wholesale_cash(app, session):
    owner = make_user(session, 3)
    business = make_wholesale(session, owner, "Caisse partagée")
    stockeur = make_user(
        session, 4, role=RoleType.STOCKEUR, vendeur_id=owner.id
    )
    session.add(BusinessMembership(
        business_id=business.id,
        user_id=stockeur.id,
        role=MembershipRole.STOCKEUR,
    ))
    session.commit()
    browser = app.test_client()
    login_to_business(browser, stockeur, business)

    response = browser.post(
        "/businesses/wholesale/cashbook",
        data={
            "description": "Dépôt Bahati",
            "direction": "INFLOW",
            "amount": "50",
            "currency_code": "USD",
            "entry_date": "2026-09-03",
        },
    )

    assert response.status_code == 302
    entry = WholesaleCashEntry.query.one()
    assert entry.recorded_by_id == stockeur.id
    assert entry.business_id == business.id


def test_cashbook_conversion_is_rendered_from_native_totals(app, session):
    owner = make_user(session, 5)
    business = make_wholesale(session, owner, "Caisse conversion")
    selected = date(2026, 9, 3)
    session.add_all([
        WholesaleCashEntry(
            business_id=business.id, recorded_by_id=owner.id,
            entry_date=selected, direction=WholesaleCashDirection.INFLOW,
            amount=Decimal("10000"), currency_code=CurrencyCode.CDF,
            description="Alimasi",
        ),
        WholesaleCashEntry(
            business_id=business.id, recorded_by_id=owner.id,
            entry_date=selected, direction=WholesaleCashDirection.OUTFLOW,
            amount=Decimal("10"), currency_code=CurrencyCode.USD,
            description="Albin",
        ),
    ])
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, business)

    response = browser.get(
        "/businesses/wholesale/cashbook"
        f"?date={selected.isoformat()}&target_currency=CDF&exchange_rate=2800"
    )
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "10,000.00 FC" in page
    assert "28,000.00 FC" in page
    assert "-18,000.00 FC" in page
    assert WholesaleCashEntry.query.count() == 2
