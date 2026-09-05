"""Client payment allocation rules shared by sale and debt workflows."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, or_

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
from apps.money import require_ledger_amount
from apps.user_messages import user_message


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


def allocate_adhoc_customer_payment(
    *, customer_key: str, vendeur_id: int, business_id: int | None,
    amount: Decimal, recorded_by, payment_date: date, exclude_sale_id=None,
    description=None, payment_event=None,
) -> Decimal:
    """Pay only debts belonging to one explicitly selected ad-hoc identity."""
    remaining = Decimal(amount)
    query = Sale.query.filter(
        Sale.vendeur_id == vendeur_id,
        Sale.business_id == business_id,
        Sale.client_id.is_(None),
        Sale.adhoc_customer_key == customer_key,
        Sale.status == TransactionStatus.ACTIVE,
        Sale.debt_amount > Decimal("0.00"),
    )
    if exclude_sale_id is not None:
        query = query.filter(Sale.id != exclude_sale_id)
    for old_sale in query.order_by(Sale.sale_date, Sale.created_at).with_for_update().all():
        if remaining <= 0:
            break
        paid = min(remaining, old_sale.debt_amount)
        old_sale.cash_paid += paid
        old_sale.debt_amount -= paid
        old_sale.updated_at = datetime.now(timezone.utc)
        db.session.add(CashInflow(
            amount=paid,
            category=CashInflowCategory.SALE_COLLECTION,
            allocation_kind=PaymentAllocationKind.PRIOR_DEBT,
            description=description or "Paiement appliqué automatiquement à l'ancienne dette",
            recorded_by=recorded_by,
            vendeur_id=vendeur_id,
            business_id=business_id,
            payment_event=payment_event,
            sale=old_sale,
            payment_date=payment_date,
        ))
        remaining -= paid
    return remaining


def apply_payment_to_sale(
    *, sale: Sale, amount: Decimal, recorded_by, payment_date: date,
    payment_event: PaymentEvent | None = None,
) -> Decimal:
    """Apply cash to old registered-client debts first, then to this sale."""
    amount = require_ledger_amount(
        amount, label="Le montant payé", allow_zero=True
    )
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
    elif sale.adhoc_customer_key:
        old_debt = db.session.query(db.func.sum(Sale.debt_amount)).filter(
            Sale.vendeur_id == sale.vendeur_id,
            Sale.business_id == sale.business_id,
            Sale.client_id.is_(None),
            Sale.adhoc_customer_key == sale.adhoc_customer_key,
            Sale.id != sale.id,
            Sale.status == TransactionStatus.ACTIVE,
            Sale.debt_amount > 0,
        ).scalar() or Decimal("0.00")
        maximum += old_debt
    if amount > maximum:
        raise ValueError(
            "Le montant payé dépasse la dette totale du client et la vente actuelle."
        )

    if amount > 0:
        if payment_event is None:
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
        elif any((
            payment_event.business_id != sale.business_id,
            payment_event.client_id != sale.client_id,
            payment_event.source_sale_id != sale.id,
            Decimal(payment_event.amount) != amount,
            payment_event.payment_date != payment_date,
        )):
            raise ValueError("Le reçu de remplacement ne correspond pas à cette vente.")

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
    elif sale.adhoc_customer_key:
        remaining = allocate_adhoc_customer_payment(
            customer_key=sale.adhoc_customer_key,
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
    payment_event: PaymentEvent | None = None,
) -> Decimal:
    """Collect a registered client's debt within exactly one business."""
    if client.business_id != business.id:
        raise PermissionError("Ce client appartient à un autre mode.")
    if not any(
        membership.user_id == recorded_by.id and membership.is_active
        for membership in business.memberships
    ):
        raise PermissionError("Vous n'avez pas accès à ce mode.")

    amount = require_ledger_amount(amount, label="Le montant payé")
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

    if payment_event is None:
        payment_event = PaymentEvent(
            business_id=business.id,
            client_id=client.id,
            recorded_by_id=recorded_by.id,
            amount=amount,
            payment_date=payment_date,
            description=description,
        )
        db.session.add(payment_event)
    elif any((
        payment_event.business_id != business.id,
        payment_event.client_id != client.id,
        payment_event.source_sale_id is not None,
        Decimal(payment_event.amount) != amount,
        payment_event.payment_date != payment_date,
    )):
        raise ValueError("Le reçu de remplacement ne correspond pas à ce client.")
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


def correct_wholesale_payment_event(
    *, payment_event: PaymentEvent, business: Business, corrected_by,
    amount: Decimal, payment_date: date, reason: str,
) -> PaymentEvent:
    """Replace the newest client receipt without erasing its audit history."""
    if payment_event.business_id != business.id:
        raise PermissionError("Ce paiement appartient à un autre mode.")
    if business.owner_user_id != corrected_by.id:
        raise PermissionError("Seul le propriétaire peut corriger ce paiement.")
    if payment_event.status != TransactionStatus.ACTIVE:
        raise ValueError("Seul un paiement actif peut être corrigé.")
    if payment_event.client_id is None:
        raise ValueError("Ce paiement n'est pas lié à un client grossiste.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("Indiquez la raison de la correction.")
    amount = require_ledger_amount(amount, label="Le montant correct")

    locked_event = (
        PaymentEvent.query.filter_by(id=payment_event.id)
        .with_for_update()
        .one()
    )
    later_event = (
        PaymentEvent.query.filter(
            PaymentEvent.business_id == business.id,
            PaymentEvent.client_id == locked_event.client_id,
            PaymentEvent.status == TransactionStatus.ACTIVE,
            PaymentEvent.id != locked_event.id,
            or_(
                PaymentEvent.created_at > locked_event.created_at,
                and_(
                    PaymentEvent.created_at == locked_event.created_at,
                    PaymentEvent.id > locked_event.id,
                ),
            ),
        )
        .order_by(PaymentEvent.created_at.desc(), PaymentEvent.id.desc())
        .first()
    )
    if later_event is not None:
        raise ValueError(user_message(
            "Un paiement plus récent dépend de l'ordre des dettes.",
            f"Corrigez d'abord le reçu #{later_event.id}.",
        ))

    source_sale = (
        db.session.get(Sale, locked_event.source_sale_id)
        if locked_event.source_sale_id is not None
        else None
    )
    client = db.session.get(Client, locked_event.client_id)
    if client is None or client.business_id != business.id:
        raise PermissionError("Le client de ce paiement appartient à un autre mode.")
    if source_sale is not None and (
        source_sale.business_id != business.id
        or source_sale.client_id != client.id
        or source_sale.status != TransactionStatus.ACTIVE
    ):
        raise ValueError(user_message(
            "La vente liée à ce paiement ne peut pas être corrigée.",
            "Vérifiez son statut avant de continuer.",
        ))

    reverse_payment_event(
        payment_event=locked_event,
        business=business,
        reversed_by=corrected_by,
        reason=reason,
    )
    replacement = PaymentEvent(
        business_id=business.id,
        client_id=client.id,
        source_sale_id=source_sale.id if source_sale is not None else None,
        corrected_from=locked_event,
        recorded_by_id=corrected_by.id,
        amount=amount,
        payment_date=payment_date,
        description=f"Correction du reçu #{locked_event.id}",
    )
    db.session.add(replacement)
    if source_sale is not None:
        apply_payment_to_sale(
            sale=source_sale,
            amount=amount,
            recorded_by=corrected_by,
            payment_date=payment_date,
            payment_event=replacement,
        )
    else:
        collect_client_debt(
            business=business,
            client=client,
            amount=amount,
            recorded_by=corrected_by,
            payment_date=payment_date,
            description=replacement.description,
            payment_event=replacement,
        )
    return replacement


def apply_additional_payment_to_sale(
    *, sale: Sale, amount: Decimal, recorded_by, payment_date: date
) -> Decimal:
    """Record new cash from an existing sale screen without rewriting history."""
    amount = require_ledger_amount(amount, label="Le nouveau paiement")
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
    elif sale.adhoc_customer_key:
        old_debt = db.session.query(db.func.sum(Sale.debt_amount)).filter(
            Sale.vendeur_id == sale.vendeur_id,
            Sale.business_id == sale.business_id,
            Sale.client_id.is_(None),
            Sale.adhoc_customer_key == sale.adhoc_customer_key,
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
    elif sale.adhoc_customer_key:
        remaining = allocate_adhoc_customer_payment(
            customer_key=sale.adhoc_customer_key,
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
        raise PermissionError("Ce paiement appartient à un autre mode.")
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
        raise ValueError(user_message(
            "Ce paiement ne peut pas être annulé automatiquement.",
            "Contactez l'administrateur pour le corriger.",
        ))

    if any(allocation.sale_id is None for allocation in allocations):
        raise RuntimeError(user_message(
            "Ce paiement contient des informations incomplètes.",
            "Contactez l'administrateur avant de le modifier.",
        ))
    sale_ids = {allocation.sale_id for allocation in allocations}
    sales = {
        sale.id: sale
        for sale in Sale.query.filter(Sale.id.in_(sale_ids)).with_for_update().all()
    }
    for allocation in allocations:
        sale = sales.get(allocation.sale_id)
        if sale is None or sale.business_id != business.id:
            raise PermissionError("Une allocation appartient à un autre mode.")
        if sale.status != TransactionStatus.ACTIVE:
            raise ValueError(
                user_message(
                    "Ce paiement concerne une vente déjà annulée.",
                    "Contactez l'administrateur pour le corriger.",
                )
            )
        if sale.cash_paid < allocation.amount:
            raise RuntimeError(user_message(
                "Les montants de la vente ne correspondent pas au paiement.",
                "Contactez l'administrateur avant de continuer.",
            ))
        if allocation.allocation_kind == PaymentAllocationKind.CURRENT_SALE:
            if sale.initial_cash_paid < allocation.amount:
                raise RuntimeError(user_message(
                    "Le paiement enregistré avec cette vente est incomplet.",
                    "Contactez l'administrateur avant de continuer.",
                ))

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
