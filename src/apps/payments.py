"""Client payment allocation rules shared by sale and debt workflows."""

from datetime import date, datetime, timezone
from decimal import Decimal

from apps import db
from apps.models import (
    Business,
    CashInflow,
    CashInflowCategory,
    Client,
    PaymentAllocationKind,
    PaymentEvent,
    Sale,
    TransactionStatus,
)


def allocate_registered_client_payment(
    *, client_id: int, vendeur_id: int, business_id: int | None,
    amount: Decimal, recorded_by, payment_date: date, exclude_sale_id=None,
    description=None, payment_event=None,
) -> Decimal:
    """Pay a registered client's oldest debts and return unused cash."""
    remaining = Decimal(amount)
    query = Sale.query.filter(
        Sale.vendeur_id == vendeur_id,
        Sale.business_id == business_id,
        Sale.client_id == client_id,
        Sale.status == TransactionStatus.ACTIVE,
        Sale.debt_amount > Decimal("0.00"),
    )
    if exclude_sale_id is not None:
        query = query.filter(Sale.id != exclude_sale_id)

    unpaid_sales = (
        query.order_by(Sale.sale_date, Sale.created_at)
        .with_for_update()
        .all()
    )
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
            allocation_kind=PaymentAllocationKind.PRIOR_DEBT,
            description=description or "Paiement appliqué automatiquement à l'ancienne dette",
            recorded_by=recorded_by,
            vendeur_id=vendeur_id,
            business_id=business_id,
            payment_event=payment_event,
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
            Sale.status == TransactionStatus.ACTIVE,
        ).scalar() or Decimal("0.00")
        maximum += old_debt
    if amount > maximum:
        raise ValueError(
            "Le montant payé dépasse la dette totale du client et la vente actuelle."
        )

    payment_event = None
    if amount > 0:
        payment_event = PaymentEvent(
            business_id=sale.business_id,
            client_id=sale.client_id,
            source_sale_id=sale.id,
            recorded_by_id=recorded_by.id,
            amount=amount,
            payment_date=payment_date,
            description="Paiement lors de la vente",
        )
        db.session.add(payment_event)

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
            payment_event=payment_event,
        )
    current_paid = min(remaining, sale.total_amount_due)
    sale.cash_paid = current_paid
    sale.initial_cash_paid = current_paid
    sale.debt_amount = sale.total_amount_due - current_paid
    if current_paid > 0:
        db.session.add(CashInflow(
            amount=current_paid,
            category=CashInflowCategory.SALE_COLLECTION,
            allocation_kind=PaymentAllocationKind.CURRENT_SALE,
            description="Paiement de la vente",
            recorded_by=recorded_by,
            vendeur_id=sale.vendeur_id,
            business_id=sale.business_id,
            payment_event=payment_event,
            sale=sale,
            payment_date=payment_date,
        ))
    return amount - remaining


def collect_client_debt(
    *,
    business: Business,
    client: Client,
    amount: Decimal,
    recorded_by,
    payment_date: date,
    description=None,
) -> Decimal:
    """Collect a registered client's debt within exactly one business."""
    if client.business_id != business.id:
        raise PermissionError("Ce client appartient à une autre entreprise.")
    if not any(
        membership.user_id == recorded_by.id and membership.is_active
        for membership in business.memberships
    ):
        raise PermissionError("Vous n'avez pas accès à cette entreprise.")

    amount = Decimal(amount)
    if amount <= 0:
        raise ValueError("Le montant payé doit être positif.")
    total_debt = db.session.query(db.func.sum(Sale.debt_amount)).filter(
        Sale.business_id == business.id,
        Sale.client_id == client.id,
        Sale.debt_amount > 0,
        Sale.status == TransactionStatus.ACTIVE,
    ).scalar() or Decimal("0.00")
    if total_debt <= 0:
        raise ValueError("Ce client n'a aucune dette impayée.")
    if amount > total_debt:
        raise ValueError("Le montant payé dépasse la dette totale du client.")

    payment_event = PaymentEvent(
        business_id=business.id,
        client_id=client.id,
        recorded_by_id=recorded_by.id,
        amount=amount,
        payment_date=payment_date,
        description=description,
    )
    db.session.add(payment_event)
    remaining = allocate_registered_client_payment(
        client_id=client.id,
        vendeur_id=business.owner_user_id,
        business_id=business.id,
        amount=amount,
        recorded_by=recorded_by,
        payment_date=payment_date,
        description=description,
        payment_event=payment_event,
    )
    if remaining != 0:
        raise RuntimeError("Le paiement n'a pas été entièrement alloué.")
    return amount


def apply_additional_payment_to_sale(
    *, sale: Sale, amount: Decimal, recorded_by, payment_date: date
) -> Decimal:
    """Record new cash from an existing sale screen without rewriting history."""
    amount = Decimal(amount)
    if amount <= 0:
        raise ValueError("Le nouveau paiement doit être positif.")
    if sale.status != TransactionStatus.ACTIVE:
        raise ValueError("Une vente annulée ne peut pas recevoir de paiement.")

    maximum = sale.debt_amount
    if sale.client_id is not None:
        old_debt = db.session.query(db.func.sum(Sale.debt_amount)).filter(
            Sale.vendeur_id == sale.vendeur_id,
            Sale.business_id == sale.business_id,
            Sale.client_id == sale.client_id,
            Sale.id != sale.id,
            Sale.status == TransactionStatus.ACTIVE,
            Sale.debt_amount > 0,
        ).scalar() or Decimal("0.00")
        maximum += old_debt
    if amount > maximum:
        raise ValueError("Le paiement dépasse la dette totale du client.")

    event = PaymentEvent(
        business_id=sale.business_id,
        client_id=sale.client_id,
        source_sale_id=sale.id,
        recorded_by_id=recorded_by.id,
        amount=amount,
        payment_date=payment_date,
        description="Paiement supplémentaire",
    )
    db.session.add(event)

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
            payment_event=event,
        )
    paid_here = min(remaining, sale.debt_amount)
    if paid_here > 0:
        sale.cash_paid += paid_here
        sale.debt_amount -= paid_here
        sale.updated_at = datetime.now(timezone.utc)
        db.session.add(CashInflow(
            amount=paid_here,
            category=CashInflowCategory.SALE_COLLECTION,
            allocation_kind=PaymentAllocationKind.PRIOR_DEBT,
            description="Paiement supplémentaire",
            recorded_by=recorded_by,
            vendeur_id=sale.vendeur_id,
            business_id=sale.business_id,
            payment_event=event,
            sale=sale,
            payment_date=payment_date,
        ))
    return amount


def reverse_payment_event(
    *, payment_event: PaymentEvent, business: Business, reversed_by, reason: str
) -> None:
    """Reverse one receipt and every debt allocation it produced."""
    if payment_event.business_id != business.id:
        raise PermissionError("Ce paiement appartient à une autre entreprise.")
    if business.owner_user_id != reversed_by.id:
        raise PermissionError("Seul le propriétaire peut annuler ce paiement.")
    if payment_event.status != TransactionStatus.ACTIVE:
        raise ValueError("Ce paiement est déjà annulé.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("Indiquez la raison de l'annulation.")

    allocations = [
        allocation
        for allocation in payment_event.allocations
        if allocation.status == TransactionStatus.ACTIVE
    ]
    if not allocations:
        raise ValueError("Ce paiement ne contient aucune allocation annulable.")

    if any(allocation.sale_id is None for allocation in allocations):
        raise RuntimeError("Une allocation de paiement n'est liée à aucune vente.")
    sale_ids = {allocation.sale_id for allocation in allocations}
    sales = {
        sale.id: sale
        for sale in Sale.query.filter(Sale.id.in_(sale_ids)).with_for_update().all()
    }
    for allocation in allocations:
        sale = sales.get(allocation.sale_id)
        if sale is None or sale.business_id != business.id:
            raise PermissionError("Une allocation appartient à une autre entreprise.")
        if sale.status != TransactionStatus.ACTIVE:
            raise ValueError(
                "Une vente liée est annulée; ce paiement ne peut pas être modifié."
            )
        if sale.cash_paid < allocation.amount:
            raise RuntimeError("Le solde payé de la vente est incohérent.")
        if allocation.allocation_kind == PaymentAllocationKind.CURRENT_SALE:
            if sale.initial_cash_paid < allocation.amount:
                raise RuntimeError("Le paiement initial de la vente est incohérent.")

    for allocation in allocations:
        sale = sales[allocation.sale_id]
        sale.cash_paid -= allocation.amount
        sale.debt_amount += allocation.amount
        if allocation.allocation_kind == PaymentAllocationKind.CURRENT_SALE:
            sale.initial_cash_paid -= allocation.amount
        sale.updated_at = datetime.now(timezone.utc)
        allocation.status = TransactionStatus.REVERSED

    payment_event.status = TransactionStatus.REVERSED
    payment_event.reversed_at = datetime.now(timezone.utc)
    payment_event.reversed_by_id = reversed_by.id
    payment_event.reversal_reason = reason
