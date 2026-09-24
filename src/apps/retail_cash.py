"""Authoritative daily cash rules for retail businesses."""

from dataclasses import dataclass
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from apps import db
from apps.models import (
    Business,
    BusinessType,
    CashInflow,
    CashOutflow,
    TransactionStatus,
)
from apps.money import require_ledger_amount
from apps.user_messages import user_message


class RetailCashError(ValueError):
    """Raised when a retail cash movement violates ledger rules."""


@dataclass(frozen=True)
class DailyRetailCashBalance:
    inflow: Decimal
    outflow: Decimal
    available: Decimal


def daily_retail_cash_balance(
    *, business_id: int, balance_date: date
) -> DailyRetailCashBalance:
    """Return active receipts, withdrawals, and available cash for one day."""
    inflow = db.session.query(func.sum(CashInflow.amount)).filter(
        CashInflow.business_id == business_id,
        CashInflow.payment_date == balance_date,
        CashInflow.status == TransactionStatus.ACTIVE,
    ).scalar() or Decimal("0.00")
    outflow = db.session.query(func.sum(CashOutflow.amount)).filter(
        CashOutflow.business_id == business_id,
        CashOutflow.expense_date == balance_date,
        CashOutflow.status == TransactionStatus.ACTIVE,
    ).scalar() or Decimal("0.00")
    inflow = Decimal(inflow)
    outflow = Decimal(outflow)
    return DailyRetailCashBalance(
        inflow=inflow,
        outflow=outflow,
        available=inflow - outflow,
    )


def record_retail_cash_outflow(
    *, business: Business, recorded_by, amount, category, expense_date: date,
    description=None, request_id=None,
) -> tuple[CashOutflow, bool]:
    """Record a withdrawal only when that business day has enough cash."""
    if business.business_type != BusinessType.RETAIL:
        raise RetailCashError("Cette opération est réservée au mode détaillant.")
    if expense_date is None:
        raise RetailCashError("Indiquez la date de la dépense.")
    amount = require_ledger_amount(amount, label="Le montant")
    request_id = (request_id or "").strip() or None

    # Serialize withdrawals for the business so concurrent requests cannot both
    # consume the same available cash. PostgreSQL enforces this row lock.
    db.session.query(Business).filter(Business.id == business.id).with_for_update().one()

    if request_id:
        existing = CashOutflow.query.filter_by(
            business_id=business.id, request_id=request_id
        ).first()
        if existing is not None:
            return existing, False

    balance = daily_retail_cash_balance(
        business_id=business.id, balance_date=expense_date
    )
    if amount > balance.available:
        raise RetailCashError(user_message(
            "Solde insuffisant.",
            f"Disponible le {expense_date.strftime('%d/%m/%Y')} : "
            f"{balance.available:,.2f} FC. Enregistrez d'abord une vente payée "
            "ou un encaissement.",
        ))

    outflow = CashOutflow(
        amount=amount,
        category=category,
        description=(description or "").strip() or None,
        recorded_by=recorded_by,
        vendeur_id=business.owner_user_id,
        business_id=business.id,
        expense_date=expense_date,
        request_id=request_id,
    )
    db.session.add(outflow)
    return outflow, True


def reverse_retail_cash_outflow(
    *, outflow: CashOutflow, business: Business, reversed_by, reason: str
) -> bool:
    """Reverse a withdrawal without deleting its audit history."""
    if outflow.business_id != business.id or business.business_type != BusinessType.RETAIL:
        raise PermissionError("Cette sortie appartient à un autre mode.")
    if business.owner_user_id != reversed_by.id:
        raise PermissionError("Seul le propriétaire peut annuler cette sortie.")
    if outflow.status == TransactionStatus.REVERSED:
        return False
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise RetailCashError("Indiquez brièvement pourquoi vous annulez cette sortie.")

    locked = CashOutflow.query.filter_by(id=outflow.id).with_for_update().one()
    if locked.status == TransactionStatus.REVERSED:
        return False
    locked.status = TransactionStatus.REVERSED
    locked.reversed_at = datetime.now(timezone.utc)
    locked.reversed_by_id = reversed_by.id
    locked.reversal_reason = reason
    return True


def require_cash_after_receipt_reversal(
    *, business: Business, inflows
) -> None:
    """Prevent receipt reversal after that day's money has been spent."""
    if business.business_type != BusinessType.RETAIL:
        return
    db.session.query(Business).filter(
        Business.id == business.id
    ).with_for_update().one()
    removal_by_date = defaultdict(lambda: Decimal("0.00"))
    for inflow in inflows:
        if inflow.status == TransactionStatus.ACTIVE:
            removal_by_date[inflow.payment_date] += Decimal(inflow.amount)

    for payment_date, removal in removal_by_date.items():
        balance = daily_retail_cash_balance(
            business_id=business.id, balance_date=payment_date
        )
        if removal > balance.available:
            raise RetailCashError(user_message(
                "Ce paiement a déjà servi à une sortie de caisse.",
                f"Annulez d'abord les sorties du {payment_date.strftime('%d/%m/%Y')} "
                "concernées, puis annulez ce paiement.",
            ))
