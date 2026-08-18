import pytest

from apps.businesses import add_stockeur, create_business
from apps.models import (
    BusinessType,
    CurrencyCode,
    MembershipRole,
    RoleType,
    User,
)


def make_user(session, *, suffix, role):
    user = User(
        username=f"user-{suffix}",
        phone=f"+2438100001{suffix:02d}",
        role=role,
    )
    user.set_password("safe-password")
    session.add(user)
    session.flush()
    return user


def test_owner_can_create_separate_retail_and_wholesale_businesses(session):
    owner = make_user(session, suffix=1, role=RoleType.VENDEUR)

    retail = create_business(
        owner=owner, name="Faida Retail", business_type=BusinessType.RETAIL
    )
    wholesale = create_business(
        owner=owner, name="Faida Wholesale", business_type=BusinessType.WHOLESALE
    )
    session.flush()

    assert retail.currency_code == CurrencyCode.CDF
    assert wholesale.currency_code == CurrencyCode.USD
    assert {business.id for business in owner.owned_businesses} == {
        retail.id, wholesale.id
    }
    assert retail.memberships[0].role == MembershipRole.OWNER
    assert wholesale.memberships[0].role == MembershipRole.OWNER


def test_retail_owner_controls_stockeur_membership(session):
    owner = make_user(session, suffix=2, role=RoleType.VENDEUR)
    stockeur = make_user(session, suffix=3, role=RoleType.STOCKEUR)
    retail = create_business(
        owner=owner, name="Retail", business_type=BusinessType.RETAIL
    )

    membership = add_stockeur(business=retail, stockeur=stockeur)
    session.flush()

    assert membership.role == MembershipRole.STOCKEUR
    assert membership.business_id == retail.id
    assert membership.user_id == stockeur.id


def test_wholesale_business_rejects_stockeurs(session):
    owner = make_user(session, suffix=4, role=RoleType.VENDEUR)
    stockeur = make_user(session, suffix=5, role=RoleType.STOCKEUR)
    wholesale = create_business(
        owner=owner, name="Wholesale", business_type=BusinessType.WHOLESALE
    )

    with pytest.raises(ValueError, match="grossiste"):
        add_stockeur(business=wholesale, stockeur=stockeur)


def test_stockeur_cannot_own_business(session):
    stockeur = make_user(session, suffix=6, role=RoleType.STOCKEUR)

    with pytest.raises(ValueError, match="posséder"):
        create_business(
            owner=stockeur, name="Invalid", business_type=BusinessType.RETAIL
        )
