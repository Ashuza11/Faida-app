from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

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
    TransactionStatus,
    User,
    WholesaleCashDirection,
    WholesaleCashEntry,
)
from apps.wholesale_cashbook import (
    CashbookConversionError,
    CashbookEntryError,
    build_cashbook_totals,
    correct_cashbook_entry,
    convert_cashbook_totals,
    record_cashbook_entry,
    reverse_cashbook_entry,
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


def test_cashbook_rejects_amount_beyond_ledger_capacity(session):
    owner = make_user(session, 401)
    business = make_wholesale(session, owner, "Cash Input Safety")

    try:
        record_cashbook_entry(
            business=business,
            recorded_by=owner,
            direction=WholesaleCashDirection.INFLOW,
            amount=Decimal("10000000000.00"),
            currency_code=CurrencyCode.USD,
            description="Valeur erronée",
            entry_date=date.today(),
        )
    except CashbookEntryError as error:
        assert "trop élevé" in str(error)
    else:
        raise AssertionError("A corrupting cash amount should be rejected")

    assert WholesaleCashEntry.query.count() == 0


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


def test_cashbook_request_id_makes_retries_idempotent(session):
    owner = make_user(session, 6)
    business = make_wholesale(session, owner, "Caisse sans doublon")
    request_id = str(uuid4())
    values = {
        "business": business,
        "recorded_by": owner,
        "direction": WholesaleCashDirection.INFLOW,
        "amount": Decimal("75"),
        "currency_code": CurrencyCode.USD,
        "description": "Nanga",
        "entry_date": date(2026, 9, 4),
        "request_id": request_id,
    }

    first, first_created = record_cashbook_entry(**values)
    second, second_created = record_cashbook_entry(**values)

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert WholesaleCashEntry.query.count() == 1

    try:
        record_cashbook_entry(**{**values, "amount": Decimal("76")})
    except CashbookEntryError as error:
        assert "autres informations" in str(error)
    else:
        raise AssertionError("A request UUID must not accept different values")


def test_cashbook_correction_preserves_audit_and_updates_totals(session):
    owner = make_user(session, 7)
    business = make_wholesale(session, owner, "Caisse corrigée")
    original, _ = record_cashbook_entry(
        business=business, recorded_by=owner,
        direction=WholesaleCashDirection.OUTFLOW, amount="660000",
        currency_code=CurrencyCode.CDF, description="Besin",
        entry_date=date(2026, 9, 4), request_id=str(uuid4()),
    )

    replacement, created = correct_cashbook_entry(
        entry=original, business=business, corrected_by=owner,
        direction=WholesaleCashDirection.OUTFLOW, amount="60000",
        currency_code=CurrencyCode.CDF, description="Besin corrigé",
        entry_date=date(2026, 9, 4), request_id=str(uuid4()),
    )
    session.flush()

    assert created is True
    assert original.status == TransactionStatus.REVERSED
    assert original.reversal_reason == "Corrigé"
    assert original.replacement == replacement
    assert replacement.corrected_from == original
    totals = build_cashbook_totals([original, replacement])
    assert totals[CurrencyCode.CDF]["outflow"] == Decimal("60000.00")


def test_cashbook_delete_is_a_repeat_safe_audited_reversal(session):
    owner = make_user(session, 8)
    business = make_wholesale(session, owner, "Caisse supprimée")
    entry, _ = record_cashbook_entry(
        business=business, recorded_by=owner,
        direction=WholesaleCashDirection.INFLOW, amount="50",
        currency_code=CurrencyCode.USD, description="Dépôt Bahati",
        entry_date=date(2026, 9, 4), request_id=str(uuid4()),
    )

    assert reverse_cashbook_entry(
        entry=entry, business=business, reversed_by=owner,
        reason="Montant incorrect",
    ) is True
    assert reverse_cashbook_entry(
        entry=entry, business=business, reversed_by=owner,
        reason="Montant incorrect",
    ) is False
    assert entry.status == TransactionStatus.REVERSED
    assert entry.reversed_by_id == owner.id
    assert build_cashbook_totals([entry])[CurrencyCode.USD]["inflow"] == 0


def test_cashbook_edit_route_replaces_entry_and_displays_audit(app, session):
    owner = make_user(session, 9)
    business = make_wholesale(session, owner, "Caisse UI")
    original, _ = record_cashbook_entry(
        business=business, recorded_by=owner,
        direction=WholesaleCashDirection.INFLOW, amount="25000",
        currency_code=CurrencyCode.CDF, description="Sans libellé",
        entry_date=date(2026, 9, 4), request_id=str(uuid4()),
    )
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, business)

    edit_page = browser.get(
        f"/businesses/wholesale/cashbook/{original.id}/edit"
    )
    assert edit_page.status_code == 200
    assert b"L'ancienne version restera" in edit_page.data

    response = browser.post(
        f"/businesses/wholesale/cashbook/{original.id}/edit",
        data={
            "request_id": str(uuid4()),
            "description": "Njut",
            "direction": "INFLOW",
            "amount": "27500",
            "currency_code": "CDF",
            "entry_date": "2026-09-04",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    session.refresh(original)
    replacement = original.replacement
    assert original.status == TransactionStatus.REVERSED
    assert replacement.description == "Njut"
    assert replacement.amount == Decimal("27500.00")
    assert b"Corrections et suppressions" in response.data
    assert b"Modifier" in response.data
    assert b"Supprimer" in response.data


def test_stockeur_cannot_change_another_stockeurs_cash_entry(session):
    owner = make_user(session, 10)
    business = make_wholesale(session, owner, "Caisse permissions")
    first = make_user(session, 11, RoleType.STOCKEUR, owner.id)
    second = make_user(session, 12, RoleType.STOCKEUR, owner.id)
    session.add_all([
        BusinessMembership(
            business_id=business.id, user_id=first.id,
            role=MembershipRole.STOCKEUR,
        ),
        BusinessMembership(
            business_id=business.id, user_id=second.id,
            role=MembershipRole.STOCKEUR,
        ),
    ])
    session.flush()
    entry, _ = record_cashbook_entry(
        business=business, recorded_by=first,
        direction=WholesaleCashDirection.INFLOW, amount="40",
        currency_code=CurrencyCode.USD, description="Nanga",
        entry_date=date(2026, 9, 4), request_id=str(uuid4()),
    )

    try:
        reverse_cashbook_entry(
            entry=entry, business=business, reversed_by=second,
            reason="Erreur de saisie",
        )
    except PermissionError as error:
        assert "uniquement" in str(error)
    else:
        raise AssertionError("A stockeur changed another stockeur's entry")

    assert reverse_cashbook_entry(
        entry=entry, business=business, reversed_by=owner,
        reason="Correction propriétaire",
    ) is True


def test_cashbook_sync_api_deduplicates_lost_response_retry(app, session):
    owner = make_user(session, 13)
    business = make_wholesale(session, owner, "Caisse sync")
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, business)
    request_id = str(uuid4())
    payload = {
        "request_id": request_id,
        "business_id": business.id,
        "description": "Mugoli",
        "direction": "OUTFLOW",
        "amount": 58,
        "currency_code": "USD",
        "entry_date": "2026-09-04",
    }

    first = browser.post("/api/v1/wholesale-cash-entries", json=payload)
    second = browser.post("/api/v1/wholesale-cash-entries", json=payload)

    assert first.status_code == 201
    assert first.get_json()["status"] == "created"
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"
    assert first.get_json()["entry_id"] == second.get_json()["entry_id"]
    assert WholesaleCashEntry.query.count() == 1


def test_cashbook_sync_uses_payload_business_after_mode_switch(app, session):
    owner = make_user(session, 14)
    first = make_wholesale(session, owner, "Caisse origine")
    second = make_wholesale(session, owner, "Caisse active")
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, second)

    response = browser.post("/api/v1/wholesale-cash-entries", json={
        "request_id": str(uuid4()),
        "business_id": first.id,
        "description": "Alimasi",
        "direction": "OUTFLOW",
        "amount": 10000,
        "currency_code": "CDF",
        "entry_date": "2026-09-04",
    })

    assert response.status_code == 201
    assert WholesaleCashEntry.query.one().business_id == first.id


def test_unauthenticated_cashbook_sync_returns_json_401(app):
    response = app.test_client().post(
        "/api/v1/wholesale-cash-entries", json={}
    )

    assert response.status_code == 401
    assert "Reconnectez-vous" in response.get_json()["error"]


def test_cashbook_delete_route_removes_entry_from_totals_but_keeps_audit(
    app, session
):
    owner = make_user(session, 15)
    business = make_wholesale(session, owner, "Caisse annulation UI")
    entry, _ = record_cashbook_entry(
        business=business, recorded_by=owner,
        direction=WholesaleCashDirection.OUTFLOW, amount="100",
        currency_code=CurrencyCode.USD, description="Erreur papier",
        entry_date=date(2026, 9, 4), request_id=str(uuid4()),
    )
    session.commit()
    browser = app.test_client()
    login_to_business(browser, owner, business)

    response = browser.post(
        f"/businesses/wholesale/cashbook/{entry.id}/reverse",
        data={"reason": "Saisie en double"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    session.refresh(entry)
    assert entry.status == TransactionStatus.REVERSED
    assert entry.reversal_reason == "Saisie en double"
    assert b"Mouvement supprim" in response.data
    assert b"Saisie en double" in response.data
    assert b"$0.00" in response.data
