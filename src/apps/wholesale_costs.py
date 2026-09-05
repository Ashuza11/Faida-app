"""Wholesale stock-cost validation, anomaly diagnosis, and audited repair."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import and_, or_

from apps import db
from apps.models import (
    BusinessType,
    PriceOperation,
    PricePreset,
    SaleItem,
    Stock,
    StockOpeningBalance,
    StockPurchase,
    TransactionStatus,
    WholesaleSaleCostCorrection,
)
from apps.money import INTERNAL_MONEY_QUANTUM, as_decimal, quantize_unit_price
from apps.user_messages import user_message


REFERENCE_FACTOR_LIMIT = Decimal("10")


def _display_unit_value(value) -> str:
    try:
        number = as_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return f"{number:.8f}" if number.is_finite() else str(number)


def reference_unit_cost(*, business_id, network, exclude_preset_id=None):
    for operation in (PriceOperation.PURCHASE, PriceOperation.SALE):
        query = PricePreset.query.filter_by(
            business_id=business_id,
            network=network,
            operation=operation,
            is_active=True,
        )
        if exclude_preset_id is not None:
            query = query.filter(PricePreset.id != exclude_preset_id)
        preset = query.order_by(
            PricePreset.is_default.desc(), PricePreset.id
        ).first()
        if preset is not None:
            return as_decimal(preset.unit_price)
    return None


def wholesale_unit_cost_is_plausible(
    *, business_id, network, unit_cost, exclude_preset_id=None
) -> bool:
    try:
        unit_cost = as_decimal(unit_cost)
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not unit_cost.is_finite() or unit_cost <= 0:
        return False
    reference = reference_unit_cost(
        business_id=business_id,
        network=network,
        exclude_preset_id=exclude_preset_id,
    )
    if reference is None or reference <= 0:
        return True
    return (
        reference / REFERENCE_FACTOR_LIMIT
        <= unit_cost
        <= reference * REFERENCE_FACTOR_LIMIT
    )


def require_plausible_wholesale_unit_cost(
    *, business_id, network, unit_cost, exclude_preset_id=None
):
    if wholesale_unit_cost_is_plausible(
        business_id=business_id,
        network=network,
        unit_cost=unit_cost,
        exclude_preset_id=exclude_preset_id,
    ):
        return
    reference = reference_unit_cost(
        business_id=business_id,
        network=network,
        exclude_preset_id=exclude_preset_id,
    )
    expected = (
        f" Le prix attendu est proche de ${reference:.8f}/u."
        if reference is not None else ""
    )
    raise ValueError(user_message(
        f"Le coût calculé (${_display_unit_value(unit_cost)}/u) semble incorrect.",
        f"{expected} Corrigez la quantité ou le montant total payé.".strip(),
    ))


def require_plausible_wholesale_selling_price(
    *, business_id, network, unit_price, exclude_preset_id=None
):
    if wholesale_unit_cost_is_plausible(
        business_id=business_id,
        network=network,
        unit_cost=unit_price,
        exclude_preset_id=exclude_preset_id,
    ):
        return
    reference = reference_unit_cost(
        business_id=business_id,
        network=network,
        exclude_preset_id=exclude_preset_id,
    )
    expected = (
        f" Le prix attendu est proche de ${reference:.8f}/u."
        if reference is not None else ""
    )
    raise ValueError(user_message(
        f"Le prix de vente (${_display_unit_value(unit_price)}/u) semble incorrect.",
        f"{expected} Corrigez le prix avant de continuer.".strip(),
    ))


def sale_item_has_cost_anomaly(item) -> bool:
    cost = as_decimal(item.cost_per_unit_snapshot)
    selling_price = as_decimal(item.price_per_unit_applied)
    return (
        cost <= 0
        or selling_price <= 0
        or cost > selling_price * REFERENCE_FACTOR_LIMIT
    )


def sale_item_cost_anomaly_reason(item) -> dict | None:
    """Return a user-facing diagnosis for one unsafe margin snapshot."""
    cost = as_decimal(item.cost_per_unit_snapshot)
    selling_price = as_decimal(item.price_per_unit_applied)
    if cost <= 0:
        return {
            "code": "missing_cost",
            "label": "Coût d'achat manquant ou nul",
        }
    if selling_price <= 0:
        return {
            "code": "invalid_selling_price",
            "label": "Prix de vente manquant ou nul",
        }
    if cost > selling_price * REFERENCE_FACTOR_LIMIT:
        return {
            "code": "cost_too_high",
            "label": (
                f"Coût d'achat anormalement élevé (${cost:.8f}/u pour "
                f"un prix de vente de ${selling_price:.8f}/u)"
            ),
        }
    return None


def suggested_historical_unit_cost(item: SaleItem) -> dict | None:
    """Find the best business-scoped historical source without claiming certainty."""
    sale = item.sale
    candidates = []
    purchases = (
        StockPurchase.query.join(Stock)
        .filter(
            Stock.business_id == sale.business_id,
            StockPurchase.network == item.network,
            StockPurchase.status == TransactionStatus.ACTIVE,
            StockPurchase.amount_purchased > 0,
            StockPurchase.actual_total_cost > 0,
            or_(
                StockPurchase.purchase_date < sale.sale_date,
                and_(
                    StockPurchase.purchase_date == sale.sale_date,
                    StockPurchase.created_at <= sale.created_at,
                ),
            ),
        )
        .order_by(
            StockPurchase.purchase_date.desc(),
            StockPurchase.created_at.desc(),
            StockPurchase.id.desc(),
        )
        .all()
    )
    for purchase in purchases:
        unit_cost = as_decimal(purchase.actual_total_cost) / as_decimal(
            purchase.amount_purchased
        )
        if _candidate_is_plausible(item, unit_cost):
            candidates.append({
                "unit_cost": quantize_unit_price(unit_cost),
                "date": purchase.purchase_date,
                "order": purchase.created_at,
                "source": f"Achat #{purchase.id} du {purchase.purchase_date:%d/%m/%Y}",
                "source_kind": "purchase",
            })
            break

    opening = (
        StockOpeningBalance.query.filter(
            StockOpeningBalance.business_id == sale.business_id,
            StockOpeningBalance.network == item.network,
            StockOpeningBalance.balance_date <= sale.sale_date,
            StockOpeningBalance.quantity > 0,
            StockOpeningBalance.actual_total_cost > 0,
        )
        .order_by(
            StockOpeningBalance.balance_date.desc(),
            StockOpeningBalance.id.desc(),
        )
        .first()
    )
    if opening is not None:
        unit_cost = as_decimal(opening.actual_total_cost) / as_decimal(
            opening.quantity
        )
        if _candidate_is_plausible(item, unit_cost):
            candidates.append({
                "unit_cost": quantize_unit_price(unit_cost),
                "date": opening.balance_date,
                "order": opening.created_at,
                "source": (
                    f"Stock d'ouverture du {opening.balance_date:%d/%m/%Y}"
                ),
                "source_kind": "opening",
            })

    if candidates:
        return max(candidates, key=lambda candidate: (
            candidate["date"], candidate["order"]
        ))

    fallback = reference_unit_cost(
        business_id=sale.business_id,
        network=item.network,
    )
    if fallback is not None and _candidate_is_plausible(item, fallback):
        return {
            "unit_cost": quantize_unit_price(fallback),
            "date": None,
            "order": None,
            "source": "Prix de référence du mode grossiste",
            "source_kind": "preset_fallback",
        }
    return None


def _candidate_is_plausible(item, unit_cost) -> bool:
    unit_cost = as_decimal(unit_cost)
    selling_price = as_decimal(item.price_per_unit_applied)
    return (
        unit_cost > 0
        and selling_price > 0
        and unit_cost <= selling_price * REFERENCE_FACTOR_LIMIT
    )


def repair_historical_sale_cost(
    *, item: SaleItem, corrected_by, unit_cost, confidence: str,
    source: str, note: str,
) -> WholesaleSaleCostCorrection:
    """Repair only margin facts and retain a complete before/after audit row."""
    if not corrected_by.is_platform_admin:
        raise PermissionError("Seul un administrateur peut corriger ce coût.")
    if item.sale.business is None or item.sale.business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette vente n'appartient pas à un mode grossiste.")
    if sale_item_cost_anomaly_reason(item) is None:
        raise ValueError("Le coût de cette vente ne nécessite plus de correction.")
    try:
        new_unit_cost = quantize_unit_price(unit_cost)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Saisissez un coût par unité valide.") from error
    if not _candidate_is_plausible(item, new_unit_cost):
        raise ValueError(
            "Le coût saisi reste incohérent avec le prix de vente. Vérifiez la source."
        )
    if confidence not in {"verified", "estimated"}:
        raise ValueError("Indiquez si le coût est vérifié ou estimé.")
    normalized_note = " ".join((note or "").split())
    if len(normalized_note) < 3:
        raise ValueError("Expliquez brièvement la source de la correction.")

    old_unit_cost = as_decimal(item.cost_per_unit_snapshot)
    old_total_cost = as_decimal(item.cost_total)
    old_margin = as_decimal(item.margin_amount)
    new_total_cost = (new_unit_cost * item.quantity).quantize(
        INTERNAL_MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    new_margin = (as_decimal(item.subtotal) - new_total_cost).quantize(
        INTERNAL_MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    correction = WholesaleSaleCostCorrection(
        sale_item=item,
        corrected_by=corrected_by,
        old_unit_cost=old_unit_cost,
        new_unit_cost=new_unit_cost,
        old_total_cost=old_total_cost,
        new_total_cost=new_total_cost,
        old_margin=old_margin,
        new_margin=new_margin,
        confidence=confidence,
        source=(source or "Saisie administrateur")[:160],
        note=normalized_note[:255],
    )
    item.cost_per_unit_snapshot = new_unit_cost
    item.cost_total = new_total_cost
    item.margin_amount = new_margin
    item.is_cost_estimated = confidence == "estimated"
    db.session.add(correction)
    return correction
