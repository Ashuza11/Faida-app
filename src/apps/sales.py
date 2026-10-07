"""Business-scoped sales transactions."""

from datetime import date, datetime, timezone
from decimal import Decimal

from apps import db
from apps.client_identities import normalized_client_name
from apps.dates import business_local_datetime
from apps.inventory import consume_stock, restore_sale_cost
from apps.payments import apply_payment_to_sale, reverse_payment_event
from apps.models import (
    Business,
    BusinessApprovalStatus,
    BusinessType,
    Client,
    CashInflow,
    NetworkType,
    PaymentEvent,
    PriceOperation,
    PricePreset,
    Sale,
    SaleItem,
    SaleItemHistory,
    Stock,
    StockOpeningBalance,
    StockPurchase,
    TransactionStatus,
    User,
)
from apps.money import (
    INTERNAL_MONEY_QUANTUM,
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


class LaterSaleStockConflict(ValueError):
    """Historical replay cannot preserve a later sale after a correction."""


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


def build_retail_sale_groups(sales, display_numbers) -> list[dict]:
    """Group one day's retail sales by their customer-facing identity.

    Retail names are treated as the customer-facing identity. New sales always
    register a client, while matching legacy ad-hoc rows remain grouped with it.
    """
    groups = {}
    for sale in sales:
        client_name = normalized_client_name(sale.client_display_name)
        customer_key = f"name:{client_name.casefold()}"
        key = (customer_key, sale.sale_date)
        group = groups.setdefault(key, {
            "key": f"{customer_key}:{sale.sale_date.isoformat()}",
            "client_name": client_name,
            "client_id": sale.client_id,
            "sale_date": sale.sale_date,
            "sales": [],
            "sale_rows": [],
            "seller_names": [],
            "active_sale_count": 0,
            "total_amount_due": Decimal("0"),
            "cash_paid": Decimal("0"),
            "debt_amount": Decimal("0"),
            "item_groups": {},
        })
        group["sales"].append(sale)
        if group["client_id"] is None and sale.client_id is not None:
            group["client_id"] = sale.client_id
            group["client_name"] = sale.client_display_name
        group["sale_rows"].append({
            "sale": sale,
            "display_number": display_numbers[sale.id],
            "registration_time": business_local_datetime(
                sale.created_at
            ).strftime("%H:%M"),
        })
        if sale.seller.username not in group["seller_names"]:
            group["seller_names"].append(sale.seller.username)
        if sale.status != TransactionStatus.ACTIVE:
            continue

        group["active_sale_count"] += 1
        group["total_amount_due"] += as_decimal(sale.total_amount_due)
        group["cash_paid"] += as_decimal(sale.cash_paid)
        group["debt_amount"] += as_decimal(sale.debt_amount)
        for item in sale.sale_items:
            item_key = (item.network, as_decimal(item.price_per_unit_applied))
            item_group = group["item_groups"].setdefault(item_key, {
                "network": item.network,
                "price_per_unit": as_decimal(item.price_per_unit_applied),
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


def _inventory_event_key(*, created_at, event_order, event_id):
    """Build a timezone-neutral ordering key for recorded inventory events."""
    if created_at.tzinfo is not None:
        created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
    return created_at, event_order, event_id


def _consume_replayed_stock(*, quantity, balance, inventory_value):
    """Apply the same weighted-average consumption rules as live inventory."""
    quantity = as_decimal(quantity)
    balance = as_decimal(balance)
    inventory_value = as_decimal(inventory_value)
    if quantity > balance:
        return None
    unit_cost = quantize_unit_price(inventory_value / balance)
    cost_total = (
        inventory_value
        if quantity == balance
        else (quantity * unit_cost).quantize(INTERNAL_MONEY_QUANTUM)
    )
    remaining_balance = balance - quantity
    remaining_value = max(Decimal("0"), inventory_value - cost_total)
    if remaining_balance == 0:
        remaining_value = Decimal("0")
    return unit_cost, cost_total, remaining_balance, remaining_value


def _snapshot_sale_items(*, sale, changed_by):
    for item in sale.sale_items:
        db.session.add(SaleItemHistory(
            sale_id=sale.id,
            vendeur_id=sale.vendeur_id,
            business_id=sale.business_id,
            changed_by_id=changed_by.id,
            action="edit",
            network=item.network,
            quantity=item.quantity,
            price_per_unit_applied=item.price_per_unit_applied,
            subtotal=item.subtotal,
        ))


def _apply_corrected_sale_items(
    *, sale, old_items_by_network, prepared_items, target_costs
):
    """Replace sale lines after their inventory costs have been calculated."""
    prepared_by_network = {item["network"]: item for item in prepared_items}
    for old_network, old_item in list(old_items_by_network.items()):
        if old_network not in prepared_by_network:
            sale.sale_items.remove(old_item)
    for item in prepared_items:
        sale_item = old_items_by_network.get(item["network"])
        if sale_item is None:
            sale_item = SaleItem(network=item["network"])
            sale.sale_items.append(sale_item)
        unit_cost, cost_total = target_costs[item["network"]]
        sale_item.price_preset = item.get("preset")
        sale_item.quantity = item["quantity"]
        sale_item.price_per_unit_applied = item["unit_price"]
        sale_item.subtotal = item["subtotal"]
        sale_item.cost_per_unit_snapshot = unit_cost
        sale_item.cost_total = cost_total
        sale_item.margin_amount = item["subtotal"] - cost_total
        sale_item.is_cost_estimated = False


def _apply_current_stock_sale_correction(
    *, sale, business, prepared_items, is_wholesale
):
    """Exchange a sale's networks against current stock in one transaction.

    This is the safe fallback when the exact historical replay would invalidate
    an intervening sale. It mirrors reversing the wrong sale now and recording
    the corrected stock movement now, while preserving the invoice and audit ID.
    """
    old_items_by_network = {item.network: item for item in sale.sale_items}
    prepared_by_network = {item["network"]: item for item in prepared_items}
    affected_networks = set(old_items_by_network) | set(prepared_by_network)
    stocks = (
        Stock.query.filter(
            Stock.business_id == business.id,
            Stock.network.in_(affected_networks),
        )
        .order_by(Stock.id)
        .with_for_update()
        .all()
    )
    stocks_by_network = {stock.network: stock for stock in stocks}
    missing_network = next(
        (network for network in affected_networks if network not in stocks_by_network),
        None,
    )
    if missing_network is not None:
        raise ValueError(user_message(
            f"Le stock {missing_network.value} n'est pas encore configuré.",
            "Enregistrez d'abord un stock initial ou un achat.",
        ))

    balances = {
        network: as_decimal(stock.balance)
        for network, stock in stocks_by_network.items()
    }
    values = {
        network: as_decimal(stock.inventory_value)
        for network, stock in stocks_by_network.items()
    }
    for old_item in old_items_by_network.values():
        balances[old_item.network] += as_decimal(old_item.quantity)
        values[old_item.network] += as_decimal(old_item.cost_total)

    target_costs = {}
    for network in sorted(affected_networks, key=lambda value: value.name):
        corrected = prepared_by_network.get(network)
        if corrected is None:
            continue
        result = _consume_replayed_stock(
            quantity=corrected["quantity"],
            balance=balances[network],
            inventory_value=values[network],
        )
        if result is None:
            raise ValueError(user_message(
                f"Stock {network.value} insuffisant pour cette correction.",
                f"Disponible maintenant : {int(balances[network])} unités. "
                f"Demandé : {corrected['quantity']} unités.",
            ))
        unit_cost, cost_total, balances[network], values[network] = result
        if is_wholesale:
            require_plausible_wholesale_unit_cost(
                business_id=business.id,
                network=network,
                unit_cost=unit_cost,
            )
        else:
            require_comparable_unit_prices(
                cost=unit_cost,
                selling_price=corrected["unit_price"],
            )
        target_costs[network] = (unit_cost, cost_total)

    for network, stock in stocks_by_network.items():
        stock.balance = balances[network]
        stock.inventory_value = values[network]
        stock.average_cost_per_unit = (
            quantize_unit_price(values[network] / balances[network])
            if balances[network] else Decimal("0")
        )
    _apply_corrected_sale_items(
        sale=sale,
        old_items_by_network=old_items_by_network,
        prepared_items=prepared_items,
        target_costs=target_costs,
    )


def _replay_inventory_after_sale_correction(
    *, sale, business, prepared_items, is_wholesale
):
    """Rebuild affected inventory from the corrected sale through current state.

    Current stock is first rolled back to the instant before the target sale.
    The corrected sale and every later purchase/sale are then replayed in their
    original recording order. This preserves weighted-average historical costs.
    """
    old_items_by_network = {item.network: item for item in sale.sale_items}
    prepared_by_network = {item["network"]: item for item in prepared_items}
    affected_networks = set(old_items_by_network) | set(prepared_by_network)

    later_opening = (
        StockOpeningBalance.query.filter(
            StockOpeningBalance.business_id == business.id,
            StockOpeningBalance.network.in_(affected_networks),
            StockOpeningBalance.balance_date > sale.sale_date,
        )
        .order_by(StockOpeningBalance.balance_date, StockOpeningBalance.id)
        .first()
    )
    if later_opening is not None:
        raise ValueError(user_message(
            "Un stock initial plus récent sépare cette vente du stock actuel.",
            "Corrigez cette vente avec l'administrateur pour préserver l'inventaire.",
        ))

    stocks = (
        Stock.query.filter(
            Stock.business_id == business.id,
            Stock.network.in_(affected_networks),
        )
        .order_by(Stock.id)
        .with_for_update()
        .all()
    )
    stocks_by_network = {stock.network: stock for stock in stocks}
    missing_network = next(
        (network for network in affected_networks if network not in stocks_by_network),
        None,
    )
    if missing_network is not None:
        raise ValueError(user_message(
            f"Le stock {missing_network.value} n'est pas encore configuré.",
            "Enregistrez d'abord un stock initial ou un achat.",
        ))

    target_key = _inventory_event_key(
        created_at=sale.created_at,
        event_order=1,
        event_id=sale.id,
    )
    target_costs = {}
    later_item_costs = []
    stock_updates = {}
    for network in sorted(affected_networks, key=lambda value: value.name):
        stock = stocks_by_network[network]
        purchases = (
            StockPurchase.query.join(Stock)
            .filter(
                Stock.business_id == business.id,
                StockPurchase.network == network,
                StockPurchase.status == TransactionStatus.ACTIVE,
                StockPurchase.created_at >= sale.created_at,
            )
            .all()
        )
        sale_items = (
            SaleItem.query.join(Sale)
            .filter(
                Sale.business_id == business.id,
                Sale.status == TransactionStatus.ACTIVE,
                SaleItem.network == network,
                Sale.created_at >= sale.created_at,
            )
            .all()
        )
        events = []
        for purchase in purchases:
            key = _inventory_event_key(
                created_at=purchase.created_at,
                event_order=0,
                event_id=purchase.id,
            )
            if key >= target_key:
                events.append((key, "purchase", purchase))
        for item in sale_items:
            key = _inventory_event_key(
                created_at=item.sale.created_at,
                event_order=1,
                event_id=item.sale_id,
            )
            if key >= target_key:
                events.append((key, "sale", item))
        events.sort(key=lambda event: event[0])

        balance = as_decimal(stock.balance)
        inventory_value = as_decimal(stock.inventory_value)
        for _, event_type, event in reversed(events):
            if event_type == "sale":
                balance += as_decimal(event.quantity)
                inventory_value += as_decimal(event.cost_total)
            else:
                balance -= as_decimal(event.amount_purchased)
                inventory_value -= as_decimal(event.actual_total_cost)
        if balance < 0 or inventory_value < -INTERNAL_MONEY_QUANTUM:
            raise ValueError(user_message(
                f"L'historique du stock {network.value} est incohérent.",
                "Contactez l'administrateur avant de modifier cette vente.",
            ))
        inventory_value = max(Decimal("0"), inventory_value)

        corrected = prepared_by_network.get(network)
        if corrected is not None:
            result = _consume_replayed_stock(
                quantity=corrected["quantity"],
                balance=balance,
                inventory_value=inventory_value,
            )
            if result is None:
                raise ValueError(user_message(
                    f"Stock {network.value} insuffisant à la date de la vente.",
                    f"Disponible : {int(balance)} unités. Demandé : {corrected['quantity']} unités.",
                ))
            unit_cost, cost_total, balance, inventory_value = result
            if is_wholesale:
                require_plausible_wholesale_unit_cost(
                    business_id=business.id,
                    network=network,
                    unit_cost=unit_cost,
                )
            else:
                require_comparable_unit_prices(
                    cost=unit_cost,
                    selling_price=corrected["unit_price"],
                )
            target_costs[network] = (unit_cost, cost_total)

        for key, event_type, event in events:
            if key <= target_key:
                continue
            if event_type == "purchase":
                balance += as_decimal(event.amount_purchased)
                inventory_value = (
                    inventory_value + as_decimal(event.actual_total_cost)
                ).quantize(INTERNAL_MONEY_QUANTUM)
                continue
            result = _consume_replayed_stock(
                quantity=event.quantity,
                balance=balance,
                inventory_value=inventory_value,
            )
            if result is None:
                sale_number = (
                    event.sale_id
                    if is_wholesale
                    else build_retail_sale_display_numbers([event.sale])[
                        event.sale_id
                    ]
                )
                raise LaterSaleStockConflict(user_message(
                    f"La correction rend une vente {network.value} plus récente impossible.",
                    f"Vente concernée : #{sale_number}.",
                ))
            unit_cost, cost_total, balance, inventory_value = result
            later_item_costs.append((event, unit_cost, cost_total))

        stock_updates[network] = (balance, inventory_value)

    for event, unit_cost, cost_total in later_item_costs:
        event.cost_per_unit_snapshot = unit_cost
        event.cost_total = cost_total
        event.margin_amount = as_decimal(event.subtotal) - cost_total
        event.is_cost_estimated = False
    for network, (balance, inventory_value) in stock_updates.items():
        stock = stocks_by_network[network]
        stock.balance = balance
        stock.inventory_value = inventory_value
        stock.average_cost_per_unit = (
            quantize_unit_price(inventory_value / balance)
            if balance else Decimal("0")
        )
    _apply_corrected_sale_items(
        sale=sale,
        old_items_by_network=old_items_by_network,
        prepared_items=prepared_items,
        target_costs=target_costs,
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
    confirm_loss: bool = False,
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
    sale = (
        Sale.query.filter_by(id=sale.id, business_id=business.id)
        .with_for_update()
        .one()
    )
    db.session.expire(sale, ["sale_items"])
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
        stock = Stock.query.filter_by(
            business_id=business.id, network=network
        ).one_or_none()
        if stock is None:
            raise ValueError(user_message(
                f"Le stock {network.value} n'est pas encore configuré.",
                "Enregistrez d'abord un stock d'ouverture ou un achat.",
            ))
        raw_price = raw_item.get("price_per_unit_applied")
        if raw_price in (None, ""):
            raw_price = stock.selling_price_per_unit
        if raw_price in (None, ""):
            raise ValueError(
                f"Saisissez le prix de vente pour {network.value.capitalize()}."
            )
        unit_price = require_ledger_amount(raw_price, label="Le prix de vente")
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
    _snapshot_sale_items(sale=sale, changed_by=updated_by)

    if inventory_unchanged:
        for item in prepared:
            sale_item = old_items_by_network[item["network"]]
            require_comparable_unit_prices(
                cost=sale_item.cost_per_unit_snapshot,
                selling_price=item["unit_price"],
            )
            if (
                item["unit_price"] < as_decimal(sale_item.cost_per_unit_snapshot)
                and not confirm_loss
            ):
                raise ValueError(user_message(
                    f"Vente à perte sur {item['network'].value.capitalize()}.",
                    "Cochez « Confirmer la vente à perte » pour continuer.",
                ))
            sale_item.price_per_unit_applied = item["unit_price"]
            sale_item.subtotal = item["subtotal"]
            sale_item.margin_amount = item["subtotal"] - sale_item.cost_total
    else:
        try:
            _replay_inventory_after_sale_correction(
                sale=sale,
                business=business,
                prepared_items=prepared,
                is_wholesale=False,
            )
        except LaterSaleStockConflict:
            _apply_current_stock_sale_correction(
                sale=sale,
                business=business,
                prepared_items=prepared,
                is_wholesale=False,
            )
        if not confirm_loss:
            loss_item = next((
                item for item in sale.sale_items
                if as_decimal(item.price_per_unit_applied)
                < as_decimal(item.cost_per_unit_snapshot)
            ), None)
            if loss_item is not None:
                raise ValueError(user_message(
                    f"Vente à perte sur {loss_item.network.value.capitalize()}.",
                    "Cochez « Confirmer la vente à perte » pour continuer.",
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
    sale = (
        Sale.query.filter_by(id=sale.id, business_id=business.id)
        .with_for_update()
        .one()
    )
    db.session.expire(sale, ["sale_items"])
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
    _snapshot_sale_items(sale=sale, changed_by=updated_by)
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

    try:
        _replay_inventory_after_sale_correction(
            sale=sale,
            business=business,
            prepared_items=prepared_inputs,
            is_wholesale=True,
        )
    except LaterSaleStockConflict:
        _apply_current_stock_sale_correction(
            sale=sale,
            business=business,
            prepared_items=prepared_inputs,
            is_wholesale=True,
        )
    sale.client = client
    sale.sale_date = sale_date
    sale.total_amount_due = corrected_total
    sale.debt_amount = corrected_total - as_decimal(sale.cash_paid)


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


def reverse_sale_with_linked_payments(
    *, sale: Sale, business: Business, reversed_by: User
) -> None:
    """Cancel an auditable sale and its linked receipts atomically."""
    if sale.business_id != business.id:
        raise PermissionError("Cette vente appartient à un autre mode.")
    if sale.status != TransactionStatus.ACTIVE:
        raise ValueError("Cette vente est déjà annulée.")

    linked_payments = (
        PaymentEvent.query
        .outerjoin(CashInflow, CashInflow.payment_event_id == PaymentEvent.id)
        .filter(
            PaymentEvent.business_id == business.id,
            PaymentEvent.status == TransactionStatus.ACTIVE,
            db.or_(
                PaymentEvent.source_sale_id == sale.id,
                db.and_(
                    CashInflow.sale_id == sale.id,
                    CashInflow.status == TransactionStatus.ACTIVE,
                ),
            ),
        )
        .order_by(PaymentEvent.id)
        .distinct()
        .all()
    )
    for payment_event in linked_payments:
        reverse_payment_event(
            payment_event=payment_event,
            business=business,
            reversed_by=reversed_by,
            reason=f"Annulé avec la vente #{sale.id}",
        )

    reverse_unpaid_sale(
        sale=sale,
        business=business,
        reversed_by=reversed_by,
        reason="Annulation confirmée",
    )
