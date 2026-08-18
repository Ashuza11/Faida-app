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


def businesses_for_user(user: User):
    """Return active businesses explicitly granted to a user."""
    if user.is_platform_admin:
        return Business.query.filter_by(is_active=True).order_by(Business.name).all()
    return (
        Business.query
        .join(BusinessMembership)
        .filter(
            BusinessMembership.user_id == user.id,
            BusinessMembership.is_active.is_(True),
            Business.is_active.is_(True),
        )
        .order_by(Business.name)
        .all()
    )


def resolve_business_for_user(*, user: User, business_id=None):
    businesses = businesses_for_user(user)
    if not businesses:
        return None
    if business_id is not None:
        for business in businesses:
            if business.id == int(business_id):
                return business
        raise PermissionError("Vous n'avez pas accès à cette entreprise.")
    retail = next(
        (b for b in businesses if b.business_type == BusinessType.RETAIL), None
    )
    return retail or businesses[0]


def get_current_business():
    """Resolve and persist the authenticated user's selected business."""
    from flask import session
    from flask_login import current_user

    if not current_user.is_authenticated:
        return None
    selected_id = session.get("active_business_id")
    try:
        business = resolve_business_for_user(
            user=current_user, business_id=selected_id
        )
    except (PermissionError, TypeError, ValueError):
        session.pop("active_business_id", None)
        business = resolve_business_for_user(user=current_user)
    if business is not None:
        session["active_business_id"] = business.id
    return business


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
    from apps.pricing import seed_default_price_presets
    business.price_presets.extend(seed_default_price_presets(business))
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
