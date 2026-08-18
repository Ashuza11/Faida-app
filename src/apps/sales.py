"""Business-scoped sales transactions."""

from datetime import date
from decimal import Decimal

from apps import db
from apps.inventory import consume_stock
from apps.payments import apply_payment_to_sale
from apps.models import (
    Business,
    BusinessApprovalStatus,
    BusinessType,
    Client,
    NetworkType,
    PriceOperation,
    PricePreset,
    Sale,
    SaleItem,
    Stock,
    User,
)
from apps.money import as_decimal, calculate_invoice_total, quantize_unit_price


def record_wholesale_sale(
    *,
    business: Business,
    sold_by: User,
    client: Client,
    network: NetworkType,
    quantity,
    cash_received,
    sale_date: date,
    preset: PricePreset | None = None,
    custom_unit_price=None,
) -> Sale:
    """Record an exact wholesale sale and allocate cash to old debt first."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette opération est réservée au registre grossiste.")
    if business.approval_status != BusinessApprovalStatus.APPROVED:
        raise PermissionError("L'entreprise grossiste n'est pas encore approuvée.")
    if business.owner_user_id != sold_by.id:
        raise PermissionError("Seul le propriétaire peut enregistrer cette vente.")
    if client.business_id != business.id:
        raise ValueError("Le client sélectionné appartient à une autre entreprise.")

    quantity = as_decimal(quantity)
    if quantity <= 0 or quantity != quantity.to_integral_value():
        raise ValueError("La quantité doit être un nombre entier positif.")
    cash_received = as_decimal(cash_received or 0)
    if cash_received < 0:
        raise ValueError("Le montant reçu ne peut pas être négatif.")

    if preset is not None:
        if (
            preset.business_id != business.id
            or preset.network != network
            or preset.operation != PriceOperation.SALE
            or not preset.is_active
        ):
            raise ValueError("Le prix sélectionné ne correspond pas à cette vente.")
        unit_price = preset.unit_price
    else:
        if custom_unit_price is None:
            raise ValueError("Sélectionnez un prix ou saisissez un prix personnalisé.")
        unit_price = quantize_unit_price(custom_unit_price)
        if unit_price <= 0:
            raise ValueError("Le prix de vente doit être positif.")

    stock = (
        Stock.query.filter_by(business_id=business.id, network=network)
        .with_for_update()
        .one_or_none()
    )
    if stock is None:
        raise ValueError(f"Stock {network.value} introuvable.")
    cost_per_unit, cost_total = consume_stock(stock=stock, quantity=quantity)
    subtotal = calculate_invoice_total(
        [quantity * unit_price], business.currency_code
    )
    margin = subtotal - cost_total

    sale = Sale(
        seller_id=sold_by.id,
        vendeur_id=business.owner_user_id,
        business_id=business.id,
        client=client,
        sale_date=sale_date,
        total_amount_due=subtotal,
        cash_paid=Decimal("0"),
        debt_amount=subtotal,
    )
    sale.sale_items.append(SaleItem(
        network=network,
        price_preset=preset,
        quantity=int(quantity),
        price_per_unit_applied=unit_price,
        subtotal=subtotal,
        cost_per_unit_snapshot=cost_per_unit,
        cost_total=cost_total,
        margin_amount=margin,
        is_cost_estimated=False,
    ))
    db.session.add(sale)
    db.session.flush()
    apply_payment_to_sale(
        sale=sale,
        amount=cash_received,
        recorded_by=sold_by,
        payment_date=sale_date,
    )
    return sale
