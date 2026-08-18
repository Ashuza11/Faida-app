import pytest

from apps.businesses import (
    add_stockeur,
    create_business,
    resolve_business_for_user,
)
from apps.models import BusinessType, RoleType, User


def user(session, suffix, role):
    account = User(
        username=f"context-{suffix}",
        phone=f"+243810005{suffix:03d}",
        role=role,
    )
    account.set_password("safe-password")
    session.add(account)
    session.flush()
    return account


def test_owner_defaults_to_retail_and_can_select_wholesale(session):
    owner = user(session, 1, RoleType.VENDEUR)
    wholesale = create_business(
        owner=owner, name="A Wholesale", business_type=BusinessType.WHOLESALE
    )
    retail = create_business(
        owner=owner, name="Z Retail", business_type=BusinessType.RETAIL
    )
    session.flush()

    assert resolve_business_for_user(user=owner) is retail
    assert resolve_business_for_user(user=owner, business_id=wholesale.id) is wholesale


def test_stockeur_can_resolve_only_assigned_retail_business(session):
    owner = user(session, 2, RoleType.VENDEUR)
    stockeur = user(session, 3, RoleType.STOCKEUR)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner, name="Wholesale", business_type=BusinessType.WHOLESALE
    )
    add_stockeur(business=retail, stockeur=stockeur)
    session.flush()

    assert resolve_business_for_user(user=stockeur) is retail
    with pytest.raises(PermissionError):
        resolve_business_for_user(user=stockeur, business_id=wholesale.id)
