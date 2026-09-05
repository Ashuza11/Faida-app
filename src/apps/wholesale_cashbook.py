"""Accounting and audit services for the manual wholesale cashbook."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from apps import db
from apps.models import (
    Business,
    BusinessMembership,
    BusinessType,
    CurrencyCode,
    TransactionStatus,
    User,
    WholesaleCashDirection,
    WholesaleCashEntry,
)
from apps.money import require_ledger_amount


MONEY_QUANTUM = Decimal("0.01")


class CashbookConversionError(ValueError):
    """Raised when a cashbook conversion request is not usable."""


class CashbookEntryError(ValueError):
    """Raised when a cashbook mutation is invalid or unauthorized."""


def _request_id(value=None) -> str:
    if value in (None, ""):
        return str(uuid4())
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise CashbookEntryError("La demande n'est plus valide. Rechargez la page.") from error


def _validated_values(*, direction, amount, currency_code, description, entry_date):
    try:
        normalized_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise CashbookEntryError("Le montant est invalide.") from error
    if not normalized_amount.is_finite() or normalized_amount <= 0:
        raise CashbookEntryError("Le montant doit être supérieur à zéro.")
    try:
        require_ledger_amount(normalized_amount, label="Le montant")
    except ValueError as error:
        raise CashbookEntryError(str(error)) from error
    if not isinstance(direction, WholesaleCashDirection):
        raise CashbookEntryError("Choisissez entrée ou sortie.")
    if not isinstance(currency_code, CurrencyCode):
        raise CashbookEntryError("Choisissez USD ou FC.")
    normalized_description = " ".join((description or "").split())
    if not normalized_description:
        raise CashbookEntryError("Indiquez le libellé du mouvement.")
    if len(normalized_description) > 160:
        raise CashbookEntryError("Le libellé est trop long.")
    if not isinstance(entry_date, date):
        raise CashbookEntryError("Choisissez une date valide.")
    return {
        "direction": direction,
        "amount": normalized_amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        "currency_code": currency_code,
        "description": normalized_description,
        "entry_date": entry_date,
    }


def _require_member(*, business: Business, actor: User):
    if business.business_type != BusinessType.WHOLESALE:
        raise CashbookEntryError("Cette caisse appartient au mode grossiste.")
    membership = BusinessMembership.query.filter_by(
        business_id=business.id, user_id=actor.id, is_active=True
    ).first()
    if membership is None:
        raise PermissionError("Vous n'avez pas accès à cette caisse.")
    return membership


def ensure_cashbook_entry_change_allowed(
    entry: WholesaleCashEntry, *, business: Business, actor: User
):
    _require_member(business=business, actor=actor)
    if entry.business_id != business.id:
        raise PermissionError("Ce mouvement appartient à un autre mode.")
    if actor.id not in {business.owner_user_id, entry.recorded_by_id}:
        raise PermissionError(
            "Vous pouvez modifier uniquement les mouvements que vous avez enregistrés."
        )


def _same_values(entry: WholesaleCashEntry, values: dict) -> bool:
    return all(getattr(entry, field) == value for field, value in values.items())


def record_cashbook_entry(
    *, business: Business, recorded_by: User, direction, amount,
    currency_code, description, entry_date, request_id=None,
) -> tuple[WholesaleCashEntry, bool]:
    """Create once per request UUID, returning (entry, was_created)."""
    _require_member(business=business, actor=recorded_by)
    normalized_request_id = _request_id(request_id)
    values = _validated_values(
        direction=direction,
        amount=amount,
        currency_code=currency_code,
        description=description,
        entry_date=entry_date,
    )
    existing = WholesaleCashEntry.query.filter_by(
        business_id=business.id, request_id=normalized_request_id
    ).first()
    if existing is not None:
        if not _same_values(existing, values):
            raise CashbookEntryError(
                "Cette demande a déjà été utilisée avec d'autres informations."
            )
        return existing, False

    entry = WholesaleCashEntry(
        business_id=business.id,
        recorded_by_id=recorded_by.id,
        request_id=normalized_request_id,
        **values,
    )
    try:
        with db.session.begin_nested():
            db.session.add(entry)
            db.session.flush()
    except IntegrityError:
        existing = WholesaleCashEntry.query.filter_by(
            business_id=business.id, request_id=normalized_request_id
        ).first()
        if existing is None or not _same_values(existing, values):
            raise CashbookEntryError("Le mouvement n'a pas pu être enregistré.")
        return existing, False
    return entry, True


def correct_cashbook_entry(
    *, entry: WholesaleCashEntry, business: Business, corrected_by: User,
    direction, amount, currency_code, description, entry_date, request_id,
) -> tuple[WholesaleCashEntry, bool]:
    """Reverse an active row and create an auditable corrected replacement."""
    entry = (
        WholesaleCashEntry.query.filter_by(id=entry.id, business_id=business.id)
        .with_for_update()
        .one()
    )
    ensure_cashbook_entry_change_allowed(
        entry, business=business, actor=corrected_by
    )
    normalized_request_id = _request_id(request_id)
    values = _validated_values(
        direction=direction,
        amount=amount,
        currency_code=currency_code,
        description=description,
        entry_date=entry_date,
    )
    existing = WholesaleCashEntry.query.filter_by(
        business_id=business.id, request_id=normalized_request_id
    ).first()
    if existing is not None:
        if (
            existing.corrected_from_id != entry.id
            or not _same_values(existing, values)
        ):
            raise CashbookEntryError("Cette correction a déjà été utilisée.")
        return existing, False
    if entry.status != TransactionStatus.ACTIVE:
        raise CashbookEntryError("Ce mouvement a déjà été corrigé ou supprimé.")
    entry.status = TransactionStatus.REVERSED
    entry.reversed_at = datetime.now(timezone.utc)
    entry.reversed_by_id = corrected_by.id
    entry.reversal_reason = "Corrigé"
    replacement = WholesaleCashEntry(
        business_id=business.id,
        recorded_by_id=corrected_by.id,
        request_id=normalized_request_id,
        corrected_from_id=entry.id,
        **values,
    )
    db.session.add(replacement)
    db.session.flush()
    return replacement, True


def reverse_cashbook_entry(
    *, entry: WholesaleCashEntry, business: Business, reversed_by: User, reason: str
) -> bool:
    """Soft-delete an entry; repeated reversal is harmless."""
    entry = (
        WholesaleCashEntry.query.filter_by(id=entry.id, business_id=business.id)
        .with_for_update()
        .one()
    )
    ensure_cashbook_entry_change_allowed(entry, business=business, actor=reversed_by)
    if entry.status == TransactionStatus.REVERSED:
        return False
    normalized_reason = " ".join((reason or "").split())
    if len(normalized_reason) < 3:
        raise CashbookEntryError("Indiquez pourquoi vous supprimez ce mouvement.")
    entry.status = TransactionStatus.REVERSED
    entry.reversed_at = datetime.now(timezone.utc)
    entry.reversed_by_id = reversed_by.id
    entry.reversal_reason = normalized_reason
    return True


def build_cashbook_totals(entries) -> dict:
    """Total movements in their original currencies without mixing ledgers."""
    totals = {
        code: {
            "inflow": Decimal("0"),
            "outflow": Decimal("0"),
            "balance": Decimal("0"),
        }
        for code in CurrencyCode
    }
    for entry in entries:
        if getattr(entry, "status", TransactionStatus.ACTIVE) != TransactionStatus.ACTIVE:
            continue
        key = (
            "inflow"
            if entry.direction == WholesaleCashDirection.INFLOW
            else "outflow"
        )
        totals[entry.currency_code][key] += entry.amount
    for values in totals.values():
        values["balance"] = values["inflow"] - values["outflow"]
    return totals


def convert_cashbook_totals(
    totals: dict, *, target_currency: CurrencyCode, cdf_per_usd
) -> dict:
    """Combine native totals for display using a non-destructive FX rate."""
    try:
        rate = Decimal(str(cdf_per_usd))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise CashbookConversionError("Le taux de change est invalide.") from error
    if not rate.is_finite() or rate <= 0:
        raise CashbookConversionError("Le taux de change doit être supérieur à zéro.")
    try:
        require_ledger_amount(rate, label="Le taux de change")
    except ValueError as error:
        raise CashbookConversionError(str(error)) from error

    converted = {}
    for key in ("inflow", "outflow", "balance"):
        if target_currency == CurrencyCode.CDF:
            value = totals[CurrencyCode.CDF][key] + (
                totals[CurrencyCode.USD][key] * rate
            )
        else:
            value = totals[CurrencyCode.USD][key] + (
                totals[CurrencyCode.CDF][key] / rate
            )
        converted[key] = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    converted["currency"] = target_currency
    converted["rate"] = rate
    return converted
