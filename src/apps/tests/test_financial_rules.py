from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.businesses import create_business
from apps.models import BusinessType, Client, RoleType, Sale, User
from apps.main.forms import get_clients_with_debt
from apps.payments import apply_payment_to_sale
from apps.main.utils import calculate_sale_total, custom_round_up


def make_vendeur(session, suffix="1"):
    user = User(
        username=f"vendeur-{suffix}",
        phone=f"+24381000000{suffix}",
        role=RoleType.VENDEUR,
    )
    user.set_password("safe-password")
    session.add(user)
    session.flush()
    return user


def make_sale(
    session, vendeur, *, client=None, adhoc=None, total="1000", debt=None,
    days_ago=0, business_id=None,
):
    total = Decimal(total)
    debt = total if debt is None else Decimal(debt)
    sale = Sale(
        seller_id=vendeur.id,
        vendeur_id=vendeur.id,
        business_id=business_id,
        client=client,
        client_name_adhoc=adhoc,
        sale_date=date.today() - timedelta(days=days_ago),
        total_amount_due=total,
        cash_paid=total - debt,
        debt_amount=debt,
    )
    session.add(sale)
    session.flush()
    return sale


def test_screenshot_sale_rounds_invoice_once():
    raw_lines = [Decimal("250") * Decimal("22.50"), Decimal("250") * Decimal("22.50")]

    assert raw_lines == [Decimal("5625.00"), Decimal("5625.00")]
    assert calculate_sale_total(raw_lines) == Decimal("11250")


@pytest.mark.parametrize(
    ("raw_lines", "expected"),
    [
        (["45000", "5625", "5625"], "56250"),
        (["22500", "11250"], "33750"),
        (["22500", "5625", "5625", "5625"], "39400"),
        (["5625"], "5650"),
    ],
)
def test_screenshot_rounding_examples(raw_lines, expected):
    assert calculate_sale_total(map(Decimal, raw_lines)) == Decimal(expected)


def test_fractional_franc_rounding_has_no_gap():
    assert custom_round_up(Decimal("6950.50")) == Decimal("6950")


def test_new_payment_pays_registered_clients_oldest_debt_first(session):
    vendeur = make_vendeur(session)
    client = Client(name="Mika", vendeur_id=vendeur.id)
    session.add(client)
    session.flush()
    oldest = make_sale(session, vendeur, client=client, total="3000", days_ago=2)
    newer_debt = make_sale(session, vendeur, client=client, total="2000", days_ago=1)
    current = make_sale(session, vendeur, client=client, total="5000", debt="5000")

    apply_payment_to_sale(
        sale=current,
        amount=Decimal("6000"),
        recorded_by=vendeur,
        payment_date=date.today(),
    )
    session.flush()

    assert oldest.debt_amount == Decimal("0")
    assert newer_debt.debt_amount == Decimal("0")
    assert current.cash_paid == Decimal("1000")
    assert current.debt_amount == Decimal("4000")
    assert [inflow.amount for inflow in oldest.cash_inflows] == [Decimal("3000")]
    assert [inflow.amount for inflow in newer_debt.cash_inflows] == [Decimal("2000")]


def test_ad_hoc_payment_never_uses_another_same_name_sale(session):
    vendeur = make_vendeur(session)
    first_cris = make_sale(session, vendeur, adhoc="Cris", total="3000", days_ago=1)
    second_cris = make_sale(session, vendeur, adhoc="Cris", total="5000")

    apply_payment_to_sale(
        sale=second_cris,
        amount=Decimal("2000"),
        recorded_by=vendeur,
        payment_date=date.today(),
    )

    assert first_cris.debt_amount == Decimal("3000")
    assert second_cris.debt_amount == Decimal("3000")


def test_payment_never_settles_debt_from_another_business(session):
    vendeur = make_vendeur(session, "9")
    retail = create_business(
        owner=vendeur, name="Retail One", business_type=BusinessType.RETAIL
    )
    second_retail = create_business(
        owner=vendeur, name="Retail Two", business_type=BusinessType.RETAIL
    )
    session.flush()
    client = Client(
        name="Shared Client", vendeur_id=vendeur.id, business_id=retail.id
    )
    session.add(client)
    session.flush()
    other_debt = make_sale(
        session,
        vendeur,
        client=client,
        total="3000",
        days_ago=1,
        business_id=second_retail.id,
    )
    current = make_sale(
        session,
        vendeur,
        client=client,
        total="5000",
        business_id=retail.id,
    )

    apply_payment_to_sale(
        sale=current,
        amount=Decimal("2000"),
        recorded_by=vendeur,
        payment_date=date.today(),
    )

    assert other_debt.debt_amount == Decimal("3000")
    assert current.debt_amount == Decimal("3000")


def test_same_name_ad_hoc_debts_have_distinct_selection_keys(session):
    vendeur = make_vendeur(session)
    first = make_sale(session, vendeur, adhoc="Cris", total="3000")
    second = make_sale(session, vendeur, adhoc="Cris", total="5000")

    choices = get_clients_with_debt(vendeur_id=vendeur.id)

    assert {key for key, _ in choices} == {f"a:{first.id}", f"a:{second.id}"}
    assert len(choices) == 2


def test_registered_clients_with_same_name_remain_distinct(session):
    vendeur = make_vendeur(session)
    first = Client(name="Cris", vendeur_id=vendeur.id)
    second = Client(name="Cris", vendeur_id=vendeur.id)
    session.add_all([first, second])
    session.flush()
    make_sale(session, vendeur, client=first, total="3000")
    make_sale(session, vendeur, client=second, total="5000")

    choices = get_clients_with_debt(vendeur_id=vendeur.id)

    assert {key for key, _ in choices} == {f"c:{first.id}", f"c:{second.id}"}
