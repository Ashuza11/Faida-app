"""Business-scoped sales transactions."""

from datetime import date, datetime, timezone
from decimal import Decimal

from apps import db
from apps.inventory import consume_stock, restore_sale_cost
from apps.payments import apply_payment_to_sale
from apps.models import (
    Business,
    BusinessApprovalStatus,
    BusinessType,
    Client,
    NetworkType,
    PaymentEvent,
    PriceOperation,
    PricePreset,
    Sale,
    SaleItem,
    Stock,
    StockPurchase,
    TransactionStatus,
    User,
)
from apps.money import as_decimal, calculate_invoice_total, quantize_unit_price
from apps.user_messages import user_message


def record_wholesale_sale(
    *,
    business: Business,
    sold_by: User,
    client: Client,
    cash_received,
    sale_date: date,
    network: NetworkType | None = None,
    quantity=None,
    preset: PricePreset | None = None,
    custom_unit_price=None,
    items=None,
) -> Sale:
    """Record an exact, possibly multi-network wholesale sale."""
    _validate_wholesale_sale_access(
        business=business, sold_by=sold_by, client=client
    )
    cash_received = as_decimal(cash_received or 0)
    if cash_received < 0:
        raise ValueError("Le montant reçu ne peut pas être négatif.")

    if items is None:
        items = [{
            "network": network,
            "quantity": quantity,
            "preset": preset,
            "custom_unit_price": custom_unit_price,
        }]
    prepared_items, total = _consume_wholesale_sale_items(
        business=business, items=items
    )

    sale = Sale(
        seller_id=sold_by.id,
        vendeur_id=business.owner_user_id,
        business_id=business.id,
        client=client,
        sale_date=sale_date,
        total_amount_due=total,
        cash_paid=Decimal("0"),
        debt_amount=total,
    )
    sale.sale_items.extend(prepared_items)
    db.session.add(sale)
    db.session.flush()
    apply_payment_to_sale(
        sale=sale,
        amount=cash_received,
        recorded_by=sold_by,
        payment_date=sale_date,
    )
    return sale


def _validate_wholesale_sale_access(*, business, sold_by, client):
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette opération est disponible uniquement en mode grossiste.")
    if business.approval_status != BusinessApprovalStatus.APPROVED:
        raise PermissionError("Le mode grossiste n'est pas encore approuvé.")
    if business.owner_user_id != sold_by.id:
        raise PermissionError("Seul le propriétaire peut enregistrer cette vente.")
    if client.business_id != business.id:
        raise ValueError("Le client sélectionné appartient à un autre mode.")


def _wholesale_unit_price(*, business, network, preset, custom_unit_price):
    if preset is not None:
        if (
            preset.business_id != business.id
            or preset.network != network
            or preset.operation != PriceOperation.SALE
            or not preset.is_active
        ):
            raise ValueError(user_message(
                f"Le prix sélectionné n'est plus disponible pour {network.value}.",
                "Choisissez un autre prix.",
            ))
        unit_price = preset.unit_price
    else:
        if custom_unit_price is None:
            raise ValueError("Sélectionnez un prix ou saisissez un prix personnalisé.")
        unit_price = quantize_unit_price(custom_unit_price)
        if unit_price <= 0:
            raise ValueError("Le prix de vente doit être positif.")
    return unit_price


def _consume_wholesale_sale_items(*, business, items):
    if not items:
        raise ValueError("Ajoutez au moins un réseau.")
    seen_networks = set()
    prepared = []
    subtotals = []
    for item in items:
        network = item["network"]
        if network in seen_networks:
            raise ValueError(f"Le réseau {network.value} est saisi deux fois.")
        seen_networks.add(network)
        quantity = as_decimal(item["quantity"])
        if quantity <= 0 or quantity != quantity.to_integral_value():
            raise ValueError("La quantité doit être un nombre entier positif.")
        preset = item.get("preset")
        unit_price = _wholesale_unit_price(
            business=business,
            network=network,
            preset=preset,
            custom_unit_price=item.get("custom_unit_price"),
        )
        stock = (
            Stock.query.filter_by(business_id=business.id, network=network)
            .with_for_update()
            .one_or_none()
        )
        if stock is None:
            raise ValueError(user_message(
                f"Le stock {network.value} n'est pas encore configuré.",
                "Enregistrez d'abord un stock d'ouverture ou un achat.",
            ))
        if quantity > stock.balance:
            raise ValueError(user_message(
                f"Stock {network.value} insuffisant.",
                f"Disponible : {stock.balance} unités. Demandé : {quantity} unités.",
            ))
        cost_per_unit, cost_total = consume_stock(
            stock=stock, quantity=quantity
        )
        subtotal = calculate_invoice_total(
            [quantity * unit_price], business.currency_code
        )
        prepared.append(SaleItem(
            network=network,
            price_preset=preset,
            quantity=int(quantity),
            price_per_unit_applied=unit_price,
            subtotal=subtotal,
            cost_per_unit_snapshot=cost_per_unit,
            cost_total=cost_total,
            margin_amount=subtotal - cost_total,
            is_cost_estimated=False,
        ))
        subtotals.append(subtotal)
    return prepared, sum(subtotals, Decimal("0"))


def replace_unpaid_wholesale_sale(
    *, sale, business, updated_by, client, sale_date, items
):
    """Replace an unpaid wholesale invoice while preserving its audit identity."""
    _validate_wholesale_sale_access(
        business=business, sold_by=updated_by, client=client
    )
    if sale.business_id != business.id:
        raise PermissionError("Cette vente appartient à un autre mode.")
    if sale.status != TransactionStatus.ACTIVE:
        raise ValueError("Une vente annulée ne peut pas être modifiée.")
    has_source_payment = PaymentEvent.query.filter_by(
        source_sale_id=sale.id, status=TransactionStatus.ACTIVE
    ).first() is not None
    if sale.cash_paid > 0 or has_source_payment or any(
        inflow.status == TransactionStatus.ACTIVE for inflow in sale.cash_inflows
    ):
        raise ValueError(
            user_message(
                "Cette vente est liée à un paiement actif.",
                "Ouvrez Dettes, annulez le reçu concerné, puis réessayez.",
            )
        )

    affected_networks = {item.network for item in sale.sale_items}
    affected_networks.update(item["network"] for item in items)
    later_purchase = (
        db.session.query(StockPurchase.id)
        .join(Stock)
        .filter(
            Stock.business_id == business.id,
            StockPurchase.status == TransactionStatus.ACTIVE,
            StockPurchase.network.in_(affected_networks),
            StockPurchase.created_at > sale.created_at,
        )
        .first()
    )
    if later_purchase is not None:
        raise ValueError(
            user_message(
                "Un achat plus récent a changé le coût du stock.",
                "Corrigez d'abord cet achat avant de modifier la vente.",
            )
        )

    for old_item in sale.sale_items:
        stock = (
            Stock.query.filter_by(
                business_id=business.id, network=old_item.network
            )
            .with_for_update()
            .one()
        )
        restore_sale_cost(
            stock=stock,
            quantity=old_item.quantity,
            cost_total=old_item.cost_total,
        )
    sale.sale_items.clear()
    db.session.flush()

    prepared_items, total = _consume_wholesale_sale_items(
        business=business, items=items
    )
    sale.client = client
    sale.sale_date = sale_date
    sale.total_amount_due = total
    sale.cash_paid = Decimal("0")
    sale.initial_cash_paid = Decimal("0")
    sale.debt_amount = total
    sale.sale_items.extend(prepared_items)


def reverse_unpaid_sale(
    *, sale: Sale, business: Business, reversed_by: User, reason: str
) -> None:
    """Reverse an unpaid sale while retaining its immutable audit row."""
    has_membership = any(
        membership.user_id == reversed_by.id and membership.is_active
        for membership in business.memberships
    )
    if not has_membership:
        raise PermissionError("Vous n'avez pas accès à ce mode.")
    if sale.business_id != business.id:
        raise PermissionError("Cette vente appartient à un autre mode.")
    if sale.status != TransactionStatus.ACTIVE:
        raise ValueError("Cette vente est déjà annulée.")
    has_legacy_payment = any(
        inflow.status == TransactionStatus.ACTIVE
        and inflow.payment_event_id is None
        for inflow in sale.cash_inflows
    )
    if has_legacy_payment:
        raise ValueError(
            user_message(
                "Cette ancienne vente contient un paiement non annulable.",
                "Contactez l'administrateur pour effectuer la correction.",
            )
        )
    has_grouped_payment = any(
        inflow.status == TransactionStatus.ACTIVE
        for inflow in sale.cash_inflows
    )
    if has_grouped_payment or sale.cash_paid > 0:
        raise ValueError(
            user_message(
                "Cette vente est liée à un paiement actif.",
                "Ouvrez Dettes, annulez le reçu concerné, puis réessayez.",
            )
        )
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("Indiquez la raison de l'annulation.")

    for item in sale.sale_items:
        stock = (
            Stock.query.filter_by(
                business_id=business.id, network=item.network
            )
            .with_for_update()
            .one()
        )
        restore_sale_cost(
            stock=stock, quantity=item.quantity, cost_total=item.cost_total
        )
    sale.status = TransactionStatus.REVERSED
    sale.reversed_at = datetime.now(timezone.utc)
    sale.reversed_by_id = reversed_by.id
    sale.reversal_reason = reason


def reverse_unpaid_wholesale_sale(
    *, sale: Sale, business: Business, reversed_by: User, reason: str
) -> None:
    """Compatibility wrapper enforcing the wholesale ledger type."""
    if business.business_type != BusinessType.WHOLESALE:
        raise ValueError("Cette opération est disponible uniquement en mode grossiste.")
    reverse_unpaid_sale(
        sale=sale,
        business=business,
        reversed_by=reversed_by,
        reason=reason,
    )
