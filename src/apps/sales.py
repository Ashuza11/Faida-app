"""Business-scoped sales transactions."""

from datetime import date, datetime, timezone
from decimal import Decimal

from apps import db
from apps.dates import business_local_datetime
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
    SaleItemHistory,
    Stock,
    StockPurchase,
    TransactionStatus,
    User,
)
from apps.money import (
    as_decimal,
    calculate_invoice_total,
    format_unit_price,
    quantize_unit_price,
    require_comparable_unit_prices,
    require_ledger_amount,
    require_quantity,
)
from apps.user_messages import user_message
from apps.wholesale_costs import (
    require_plausible_wholesale_selling_price,
    require_plausible_wholesale_unit_cost,
)


def build_retail_sale_display_numbers(sales) -> dict[int, int]:
    """Return stable, business-local sale numbers without exposing database IDs.

    All sales are counted, including reversed rows, so cancelling a sale never
    renumbers the remaining audit history. Database IDs remain the identifiers
    used by routes and relationships.
    """
    sales = list(sales)
    if not sales:
        return {}

    requested_by_business = {}
    requested_legacy = {}
    for sale in sales:
        if sale.business_id is not None:
            requested_by_business.setdefault(sale.business_id, set()).add(sale.id)
        else:
            requested_legacy.setdefault(sale.vendeur_id, set()).add(sale.id)

    display_numbers = {}
    for business_id, requested_ids in requested_by_business.items():
        numbered = (
            db.session.query(
                Sale.id.label("sale_id"),
                db.func.row_number().over(order_by=Sale.id.asc()).label(
                    "display_number"
                ),
            )
            .filter(Sale.business_id == business_id)
            .subquery()
        )
        rows = db.session.query(
            numbered.c.sale_id, numbered.c.display_number
        ).filter(numbered.c.sale_id.in_(requested_ids)).all()
        display_numbers.update({sale_id: int(number) for sale_id, number in rows})

    # Compatibility for historical rows that predate business scoping.
    for vendeur_id, requested_ids in requested_legacy.items():
        numbered = (
            db.session.query(
                Sale.id.label("sale_id"),
                db.func.row_number().over(order_by=Sale.id.asc()).label(
                    "display_number"
                ),
            )
            .filter(
                Sale.business_id.is_(None),
                Sale.vendeur_id == vendeur_id,
            )
            .subquery()
        )
        rows = db.session.query(
            numbered.c.sale_id, numbered.c.display_number
        ).filter(numbered.c.sale_id.in_(requested_ids)).all()
        display_numbers.update({sale_id: int(number) for sale_id, number in rows})

    return display_numbers


def build_wholesale_sale_groups(sales, payment_events=()) -> list[dict]:
    """Group displayed wholesale sales by customer identity and business date.

    Names are deliberately not used as keys: two registered clients may share a
    name, while every sale belonging to one client must stay together. Reversed
    transactions remain visible for audit purposes but do not affect summaries.
    """
    payment_details = {
        sale.id: {
            "received_from_sale": Decimal("0"),
            "applied_from_own_receipts": Decimal("0"),
            "redirected_to_other_sales": Decimal("0"),
            "applied_from_other_receipts": Decimal("0"),
            "blocking_payment_ids": set(),
            "registration_time": business_local_datetime(
                sale.created_at
            ).strftime("%H:%M"),
            "items": [{
                "network": item.network,
                "quantity": item.quantity,
                "display_price": format_unit_price(item.price_per_unit_applied),
                "subtotal": as_decimal(item.subtotal),
            } for item in sale.sale_items],
        }
        for sale in sales
    }
    for event in payment_events:
        if event.status != TransactionStatus.ACTIVE:
            continue
        active_allocations = [
            allocation for allocation in event.allocations
            if allocation.status == TransactionStatus.ACTIVE
        ]
        source_detail = payment_details.get(event.source_sale_id)
        if source_detail is not None:
            source_detail["received_from_sale"] += as_decimal(event.amount)
            source_detail["blocking_payment_ids"].add(event.id)
            for allocation in active_allocations:
                if allocation.sale_id == event.source_sale_id:
                    source_detail["applied_from_own_receipts"] += as_decimal(
                        allocation.amount
                    )
                else:
                    source_detail["redirected_to_other_sales"] += as_decimal(
                        allocation.amount
                    )
        for allocation in active_allocations:
            target_detail = payment_details.get(allocation.sale_id)
            if target_detail is None:
                continue
            target_detail["blocking_payment_ids"].add(event.id)
            if event.source_sale_id != allocation.sale_id:
                target_detail["applied_from_other_receipts"] += as_decimal(
                    allocation.amount
                )

    for sale in sales:
        detail = payment_details[sale.id]
        tracked_paid = (
            detail["applied_from_own_receipts"]
            + detail["applied_from_other_receipts"]
        )
        detail["untracked_paid_amount"] = max(
            as_decimal(sale.cash_paid) - tracked_paid,
            Decimal("0"),
        )

    groups = {}
    for sale in sales:
        key = (sale.customer_group_key, sale.sale_date)
        group = groups.setdefault(key, {
            "key": f"{sale.customer_group_key}:{sale.sale_date.isoformat()}",
            "client_id": sale.client_id,
            "client_name": sale.client_display_name,
            "sale_date": sale.sale_date,
            "sales": [],
            "active_sale_count": 0,
            "total_amount_due": Decimal("0"),
            "cash_received_from_sales": Decimal("0"),
            "cash_paid": Decimal("0"),
            "cash_redirected_to_other_sales": Decimal("0"),
            "debt_amount": Decimal("0"),
            "item_groups": {},
            "payment_details": {},
        })
        group["sales"].append(sale)
        detail = payment_details[sale.id]
        detail["blocking_payment_ids"] = sorted(detail["blocking_payment_ids"])
        detail["blocking_payment_count"] = len(detail["blocking_payment_ids"])
        detail["has_blocking_payment"] = (
            detail["blocking_payment_count"] > 0
            or detail["untracked_paid_amount"] > 0
        )
        group["payment_details"][sale.id] = detail

        if sale.status != TransactionStatus.ACTIVE:
            continue

        group["active_sale_count"] += 1
        group["total_amount_due"] += as_decimal(sale.total_amount_due)
        group["cash_received_from_sales"] += detail["received_from_sale"]
        group["cash_paid"] += as_decimal(sale.cash_paid)
        group["cash_redirected_to_other_sales"] += detail[
            "redirected_to_other_sales"
        ]
        group["debt_amount"] += as_decimal(sale.debt_amount)
        for item in sale.sale_items:
            item_key = (item.network, as_decimal(item.price_per_unit_applied))
            item_group = group["item_groups"].setdefault(item_key, {
                "network": item.network,
                "price_per_unit": as_decimal(item.price_per_unit_applied),
                "display_price": format_unit_price(item.price_per_unit_applied),
                "quantity": 0,
                "subtotal": Decimal("0"),
            })
            item_group["quantity"] += item.quantity
            item_group["subtotal"] += as_decimal(item.subtotal)

    result = []
    for group in groups.values():
        group["item_groups"] = list(group["item_groups"].values())
        result.append(group)
    return result


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
    cash_received = require_ledger_amount(
        cash_received or 0, label="Le montant reçu", allow_zero=True
    )

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
        unit_price = quantize_unit_price(require_ledger_amount(
            custom_unit_price, label="Le prix de vente"
        ))
    require_plausible_wholesale_selling_price(
        business_id=business.id,
        network=network,
        unit_price=unit_price,
        exclude_preset_id=preset.id if preset is not None else None,
    )
    return unit_price


def _prepare_wholesale_sale_items(*, business, items):
    """Validate wholesale lines and calculate prices without changing stock."""
    if not items:
        raise ValueError("Ajoutez au moins un réseau.")
    seen_networks = set()
    prepared = []
    for item in items:
        network = item["network"]
        if network in seen_networks:
            raise ValueError(f"Le réseau {network.value} est saisi deux fois.")
        seen_networks.add(network)
        quantity = require_quantity(item["quantity"])
        preset = item.get("preset")
        unit_price = _wholesale_unit_price(
            business=business,
            network=network,
            preset=preset,
            custom_unit_price=item.get("custom_unit_price"),
        )
        subtotal = calculate_invoice_total(
            [quantity * unit_price], business.currency_code
        )
        require_ledger_amount(subtotal, label="Le total de la vente")
        prepared.append({
            "network": network,
            "quantity": int(quantity),
            "preset": preset,
            "unit_price": unit_price,
            "subtotal": subtotal,
        })
    require_ledger_amount(
        sum((item["subtotal"] for item in prepared), Decimal("0")),
        label="Le total de la vente",
    )
    return prepared


def _consume_wholesale_sale_items(*, business, items):
    prepared_inputs = _prepare_wholesale_sale_items(
        business=business, items=items
    )
    prepared_items = []
    subtotals = []
    for item in prepared_inputs:
        network = item["network"]
        quantity = item["quantity"]
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
        require_plausible_wholesale_unit_cost(
            business_id=business.id,
            network=network,
            unit_cost=stock.average_cost_per_unit,
        )
        cost_per_unit, cost_total = consume_stock(
            stock=stock, quantity=quantity
        )
        prepared_items.append(SaleItem(
            network=network,
            price_preset=item["preset"],
            quantity=quantity,
            price_per_unit_applied=item["unit_price"],
            subtotal=item["subtotal"],
            cost_per_unit_snapshot=cost_per_unit,
            cost_total=cost_total,
            margin_amount=item["subtotal"] - cost_total,
            is_cost_estimated=False,
        ))
        subtotals.append(item["subtotal"])
    return prepared_items, sum(subtotals, Decimal("0"))


def sale_has_active_payment(sale: Sale) -> bool:
    """Return whether an active receipt or allocation is linked to the sale."""
    if as_decimal(sale.cash_paid) > 0:
        return True
    if PaymentEvent.query.filter_by(
        source_sale_id=sale.id, status=TransactionStatus.ACTIVE
    ).first() is not None:
        return True
    return any(
        inflow.status == TransactionStatus.ACTIVE for inflow in sale.cash_inflows
    )


def wholesale_sale_has_active_payment(sale: Sale) -> bool:
    """Backward-compatible name used by the wholesale screens."""
    return sale_has_active_payment(sale)


def replace_retail_sale(
    *,
    sale: Sale,
    business: Business,
    updated_by: User,
    client: Client | None,
    client_name_adhoc: str | None,
    adhoc_customer_key: str | None,
    sale_date: date,
    items,
) -> None:
    """Correct a retail sale without replacing its receipts or audit identity."""
    if business.business_type != BusinessType.RETAIL:
        raise ValueError("Cette opération est disponible uniquement en mode détaillant.")
    has_membership = any(
        membership.user_id == updated_by.id and membership.is_active
        for membership in business.memberships
    )
    if not has_membership:
        raise PermissionError("Vous n'avez pas accès à ce mode.")
    if sale.business_id != business.id:
        raise PermissionError("Cette vente appartient à un autre mode.")
    if sale.status != TransactionStatus.ACTIVE:
        raise ValueError("Une vente annulée ne peut pas être modifiée.")
    if client is not None and client.business_id != business.id:
        raise PermissionError("Ce client appartient à un autre mode.")

    client_name_adhoc = (client_name_adhoc or "").strip() or None
    if client is None and not client_name_adhoc:
        raise ValueError("Sélectionnez un client ou saisissez son nom.")
    if client is None and not adhoc_customer_key:
        raise ValueError("Ce client occasionnel n'a pas pu être identifié.")

    has_active_payment = sale_has_active_payment(sale)
    old_identity = (
        sale.client_id,
        sale.adhoc_customer_key if sale.client_id is None else None,
    )
    new_identity = (
        client.id if client is not None else None,
        adhoc_customer_key if client is None else None,
    )
    if has_active_payment and new_identity != old_identity:
        raise ValueError(user_message(
            "Le client ne peut pas être changé après un paiement.",
            "Le reçu reste lié à ce client. Corrigez seulement les articles.",
        ))
    if has_active_payment and sale_date != sale.sale_date:
        raise ValueError(user_message(
            "La date ne peut pas être changée après un paiement.",
            "Le reçu conserve la date de cette vente.",
        ))

    old_items_by_network = {item.network: item for item in sale.sale_items}
    prepared = []
    seen_networks = set()
    for raw_item in items:
        network = raw_item.get("network")
        if not isinstance(network, NetworkType):
            try:
                network = NetworkType[str(network)]
            except (KeyError, TypeError):
                raise ValueError("Sélectionnez un réseau valide.") from None
        if network in seen_networks:
            raise ValueError(
                f"Le réseau {network.value.capitalize()} apparaît plusieurs fois."
            )
        seen_networks.add(network)
        quantity = int(require_quantity(raw_item.get("quantity")))
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
        available = as_decimal(stock.balance)
        if network in old_items_by_network:
            available += old_items_by_network[network].quantity
        if quantity > available:
            raise ValueError(user_message(
                f"Stock {network.value} insuffisant.",
                f"Disponible pour cette correction : {int(available)} unités.",
            ))
        raw_price = raw_item.get("price_per_unit_applied")
        if raw_price in (None, ""):
            raw_price = stock.selling_price_per_unit
        if raw_price in (None, ""):
            raise ValueError(
                f"Saisissez le prix de vente pour {network.value.capitalize()}."
            )
        unit_price = require_ledger_amount(raw_price, label="Le prix de vente")
        require_comparable_unit_prices(
            cost=stock.average_cost_per_unit or stock.buying_price_per_unit,
            selling_price=unit_price,
        )
        subtotal = (Decimal(quantity) * unit_price).quantize(Decimal("0.01"))
        require_ledger_amount(subtotal, label="Le total de la vente")
        prepared.append({
            "network": network,
            "quantity": quantity,
            "unit_price": unit_price,
            "subtotal": subtotal,
        })
    if not prepared:
        raise ValueError("Ajoutez au moins un article.")

    # Retail invoices apply the configured FC rounding once to the whole sale.
    from apps.main.utils import calculate_sale_total
    corrected_total = calculate_sale_total(
        item["subtotal"] for item in prepared
    )
    if corrected_total < as_decimal(sale.cash_paid):
        raise ValueError(user_message(
            "Le nouveau total est inférieur au montant déjà payé.",
            "Corrigez d'abord le paiement, puis modifiez la vente.",
        ))

    inventory_unchanged = (
        len(old_items_by_network) == len(prepared)
        and all(
            item["network"] in old_items_by_network
            and old_items_by_network[item["network"]].quantity == item["quantity"]
            for item in prepared
        )
    )
    if not inventory_unchanged:
        affected_networks = set(old_items_by_network)
        affected_networks.update(item["network"] for item in prepared)
        later_purchase = (
            StockPurchase.query.join(Stock).filter(
                Stock.business_id == business.id,
                StockPurchase.status == TransactionStatus.ACTIVE,
                StockPurchase.network.in_(affected_networks),
                StockPurchase.created_at > sale.created_at,
            ).order_by(StockPurchase.created_at.asc(), StockPurchase.id.asc()).first()
        )
        if later_purchase is not None:
            raise ValueError(user_message(
                "La quantité ou le réseau ne peut pas être modifié.",
                f"Un achat {later_purchase.network.value.capitalize()} a été enregistré ensuite. Le prix reste modifiable.",
            ))

    for old_item in sale.sale_items:
        db.session.add(SaleItemHistory(
            sale_id=sale.id,
            vendeur_id=sale.vendeur_id,
            business_id=sale.business_id,
            changed_by_id=updated_by.id,
            action="edit",
            network=old_item.network,
            quantity=old_item.quantity,
            price_per_unit_applied=old_item.price_per_unit_applied,
            subtotal=old_item.subtotal,
        ))

    if inventory_unchanged:
        for item in prepared:
            sale_item = old_items_by_network[item["network"]]
            sale_item.price_per_unit_applied = item["unit_price"]
            sale_item.subtotal = item["subtotal"]
            sale_item.margin_amount = item["subtotal"] - sale_item.cost_total
    else:
        for old_item in sale.sale_items:
            stock = Stock.query.filter_by(
                business_id=business.id, network=old_item.network
            ).with_for_update().one()
            restore_sale_cost(
                stock=stock,
                quantity=old_item.quantity,
                cost_total=old_item.cost_total,
            )
        sale.sale_items.clear()
        db.session.flush()
        for item in prepared:
            stock = Stock.query.filter_by(
                business_id=business.id, network=item["network"]
            ).with_for_update().one()
            cost_per_unit, cost_total = consume_stock(
                stock=stock, quantity=item["quantity"]
            )
            sale.sale_items.append(SaleItem(
                network=item["network"],
                quantity=item["quantity"],
                price_per_unit_applied=item["unit_price"],
                subtotal=item["subtotal"],
                cost_per_unit_snapshot=cost_per_unit,
                cost_total=cost_total,
                margin_amount=item["subtotal"] - cost_total,
                is_cost_estimated=False,
            ))

    sale.client = client
    sale.client_name_adhoc = client_name_adhoc if client is None else None
    sale.adhoc_customer_key = adhoc_customer_key if client is None else None
    sale.sale_date = sale_date
    sale.total_amount_due = corrected_total
    sale.debt_amount = corrected_total - as_decimal(sale.cash_paid)
    sale.updated_at = datetime.now(timezone.utc)


def replace_unpaid_wholesale_sale(
    *, sale, business, updated_by, client, sale_date, items
):
    """Correct a wholesale invoice while preserving receipts and audit identity."""
    _validate_wholesale_sale_access(
        business=business, sold_by=updated_by, client=client
    )
    if sale.business_id != business.id:
        raise PermissionError("Cette vente appartient à un autre mode.")
    if sale.status != TransactionStatus.ACTIVE:
        raise ValueError("Une vente annulée ne peut pas être modifiée.")
    has_active_payment = wholesale_sale_has_active_payment(sale)
    if has_active_payment and client.id != sale.client_id:
        raise ValueError(
            user_message(
                "Le client ne peut pas être changé après un paiement.",
                "Le reçu reste lié à ce client. Corrigez seulement la vente.",
            )
        )
    if has_active_payment and sale_date != sale.sale_date:
        raise ValueError(
            user_message(
                "La date ne peut pas être changée après un paiement.",
                "Le reçu conserve la date de cette vente.",
            )
        )

    prepared_inputs = _prepare_wholesale_sale_items(
        business=business, items=items
    )
    corrected_total = sum(
        (item["subtotal"] for item in prepared_inputs), Decimal("0")
    )
    if has_active_payment and corrected_total < as_decimal(sale.cash_paid):
        raise ValueError(user_message(
            "Le nouveau total est inférieur au montant déjà payé.",
            "Corrigez d'abord le paiement, puis modifiez la vente.",
        ))
    old_items_by_network = {item.network: item for item in sale.sale_items}
    inventory_unchanged = (
        len(old_items_by_network) == len(prepared_inputs)
        and all(
            prepared["network"] in old_items_by_network
            and old_items_by_network[prepared["network"]].quantity
            == prepared["quantity"]
            for prepared in prepared_inputs
        )
    )
    if inventory_unchanged:
        total = Decimal("0")
        for prepared in prepared_inputs:
            sale_item = old_items_by_network[prepared["network"]]
            sale_item.price_preset = prepared["preset"]
            sale_item.price_per_unit_applied = prepared["unit_price"]
            sale_item.subtotal = prepared["subtotal"]
            sale_item.margin_amount = prepared["subtotal"] - sale_item.cost_total
            total += prepared["subtotal"]
        sale.client = client
        sale.sale_date = sale_date
        sale.total_amount_due = total
        sale.debt_amount = total - as_decimal(sale.cash_paid)
        return

    affected_networks = {item.network for item in sale.sale_items}
    affected_networks.update(item["network"] for item in prepared_inputs)
    later_purchase = (
        StockPurchase.query
        .join(Stock)
        .filter(
            Stock.business_id == business.id,
            StockPurchase.status == TransactionStatus.ACTIVE,
            StockPurchase.network.in_(affected_networks),
            StockPurchase.created_at > sale.created_at,
        )
        .order_by(StockPurchase.created_at.asc(), StockPurchase.id.asc())
        .first()
    )
    if later_purchase is not None:
        raise ValueError(
            user_message(
                "La quantité ou le réseau ne peut pas être modifié.",
                (
                    f"Un achat {later_purchase.network.value.capitalize()} "
                    f"#{later_purchase.id} a été enregistré ensuite. "
                    + (
                        "Le prix reste modifiable."
                        if has_active_payment
                        else "Le prix et le client restent modifiables."
                    )
                ),
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
    sale.debt_amount = total - as_decimal(sale.cash_paid)
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
