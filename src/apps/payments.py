"""Client payment allocation rules shared by sale and debt workflows."""

from datetime import date, datetime, timezone
from decimal import Decimal

from apps import db
from apps.models import CashInflow, CashInflowCategory, Sale


def allocate_registered_client_payment(
    *, client_id: int, vendeur_id: int, business_id: int | None,
    amount: Decimal, recorded_by, payment_date: date, exclude_sale_id=None,
    description=None,
) -> Decimal:
    """Pay a registered client's oldest debts and return unused cash."""
    remaining = Decimal(amount)
    query = Sale.query.filter(
        Sale.vendeur_id == vendeur_id,
        Sale.business_id == business_id,
        Sale.client_id == client_id,
        Sale.debt_amount > Decimal("0.00"),
    )
    if exclude_sale_id is not None:
        query = query.filter(Sale.id != exclude_sale_id)

    unpaid_sales = query.order_by(Sale.sale_date, Sale.created_at).all()
    for sale in unpaid_sales:
        if remaining <= 0:
            break
        paid = min(remaining, sale.debt_amount)
        sale.cash_paid += paid
        sale.debt_amount -= paid
        sale.updated_at = datetime.now(timezone.utc)
        db.session.add(CashInflow(
            amount=paid,
            category=CashInflowCategory.SALE_COLLECTION,
            description=description or "Paiement appliqué automatiquement à l'ancienne dette",
            recorded_by=recorded_by,
            vendeur_id=vendeur_id,
            business_id=business_id,
            sale=sale,
            payment_date=payment_date,
        ))
        remaining -= paid
    return remaining


def apply_payment_to_sale(
    *, sale: Sale, amount: Decimal, recorded_by, payment_date: date
) -> Decimal:
    """Apply cash to old registered-client debts first, then to this sale."""
    amount = Decimal(amount)
    maximum = sale.total_amount_due
    if sale.client_id is not None:
        old_debt = db.session.query(db.func.sum(Sale.debt_amount)).filter(
            Sale.vendeur_id == sale.vendeur_id,
            Sale.business_id == sale.business_id,
            Sale.client_id == sale.client_id,
            Sale.id != sale.id,
            Sale.debt_amount > 0,
        ).scalar() or Decimal("0.00")
        maximum += old_debt
    if amount > maximum:
        raise ValueError(
            "Le montant payé dépasse la dette totale du client et la vente actuelle."
        )

    remaining = amount
    if sale.client_id is not None:
        remaining = allocate_registered_client_payment(
            client_id=sale.client_id,
            vendeur_id=sale.vendeur_id,
            business_id=sale.business_id,
            amount=remaining,
            recorded_by=recorded_by,
            payment_date=payment_date,
            exclude_sale_id=sale.id,
        )
    current_paid = min(remaining, sale.total_amount_due)
    sale.cash_paid = current_paid
    sale.debt_amount = sale.total_amount_due - current_paid
    if current_paid > 0:
        db.session.add(CashInflow(
            amount=current_paid,
            category=CashInflowCategory.SALE_COLLECTION,
            description="Paiement de la vente",
            recorded_by=recorded_by,
            vendeur_id=sale.vendeur_id,
            business_id=sale.business_id,
            sale=sale,
            payment_date=payment_date,
        ))
    return amount - remaining
