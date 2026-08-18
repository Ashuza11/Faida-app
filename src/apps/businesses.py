"""Business creation and membership rules.

This module is additive while legacy vendeur-scoped routes are migrated to
business_id. Keeping the rules here prevents UI, CLI, and API flows from
disagreeing about who can access a business.
"""

from apps import db
from apps.models import (
    Business,
    BusinessMembership,
    BusinessType,
    CurrencyCode,
    MembershipRole,
    RoleType,
    User,
)


def create_business(
    *, owner: User, name: str, business_type: BusinessType,
    currency_code: CurrencyCode | None = None,
) -> Business:
    if owner.is_stockeur:
        raise ValueError("Un stockeur ne peut pas posséder une entreprise.")
    if currency_code is None:
        currency_code = (
            CurrencyCode.USD if business_type == BusinessType.WHOLESALE
            else CurrencyCode.CDF
        )

    business = Business(
        name=name.strip(),
        business_type=business_type,
        currency_code=currency_code,
        owner=owner,
    )
    business.memberships.append(BusinessMembership(
        user=owner, role=MembershipRole.OWNER
    ))
    db.session.add(business)
    return business


def add_stockeur(*, business: Business, stockeur: User) -> BusinessMembership:
    if not business.allows_stockeurs:
        raise ValueError("Une entreprise grossiste ne peut pas avoir de stockeurs.")
    if stockeur.role != RoleType.STOCKEUR:
        raise ValueError("Le membre doit avoir le rôle stockeur.")
    if any(m.user_id == stockeur.id or m.user is stockeur for m in business.memberships):
        raise ValueError("Ce stockeur appartient déjà à cette entreprise.")

    membership = BusinessMembership(
        business=business, user=stockeur, role=MembershipRole.STOCKEUR
    )
    db.session.add(membership)
    return membership
