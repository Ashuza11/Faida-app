"""
Faida API v1 — JSON endpoints for offline sync
All routes require an active Flask session (login_required).
"""
from flask import jsonify, request, current_app
from flask_login import login_required, current_user
from decimal import Decimal, InvalidOperation

from apps.api import api_bp
from apps import db
from apps.models import (
    NetworkType,
    CashOutflowCategory,
    Stock,
    StockPurchase,
    Sale,
    SaleItem,
    CashOutflow,
    Client,
)
from apps.main.utils import custom_round_up


# ── Health check ──────────────────────────────────────────────────────────────
@api_bp.route("/health", methods=["GET"])
def health():
    """Tiny response used by faida-offline.js to verify connectivity."""
    return jsonify({"status": "ok"}), 200


# ── Stock levels ──────────────────────────────────────────────────────────────
@api_bp.route("/stock", methods=["GET"])
@login_required
def get_stock():
    """
    Returns current stock levels for the authenticated user's business.
    Cached by faida-offline.js for use when offline.
    """
    vendeur_id = current_user.business_vendeur_id
    if vendeur_id is None:
        return jsonify({"error": "Platform admins have no single stock view"}), 400

    stocks = Stock.query.filter_by(vendeur_id=vendeur_id).all()
    data = [
        {
            "network":                  s.network.value,
            "balance":                  float(s.balance),
            "buying_price_per_unit":    float(s.buying_price_per_unit) if s.buying_price_per_unit else None,
            "selling_price_per_unit":   float(s.selling_price_per_unit) if s.selling_price_per_unit else None,
        }
        for s in stocks
    ]
    return jsonify({"stock": data}), 200


# ── Sales ─────────────────────────────────────────────────────────────────────
@api_bp.route("/sales", methods=["POST"])
@login_required
def create_sale():
    """
    Accepts an offline-queued sale and saves it to the database.
    Expects JSON body matching the offline queue format.

    Required fields:
      - sale_items: list of {network, quantity, price_per_unit_applied}
      - cash_paid: number
      - client_choice: "existing" | "new"
      - existing_client_id: string|null (when client_choice == "existing")
      - new_client_name: string|null (when client_choice == "new")
      - local_id: string (UUID, used for idempotency)
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON body"}), 400

    local_id = payload.get("local_id")
    vendeur_id = current_user.business_vendeur_id

    if vendeur_id is None:
        return jsonify({"error": "Platform admins cannot submit sales via API"}), 403

    try:
        # ── Resolve client ───────────────────────────────────────────────────
        client = None
        client_name_adhoc = None
        client_choice = payload.get("client_choice", "new")

        if client_choice == "existing":
            cid = payload.get("existing_client_id")
            if cid:
                client = Client.query.filter_by(id=int(cid), vendeur_id=vendeur_id).first()
                if not client:
                    return jsonify({"error": "Client introuvable ou inaccessible"}), 400
        else:
            client_name_adhoc = payload.get("new_client_name") or "Client inconnu"

        # ── Process sale items ───────────────────────────────────────────────
        items_payload = payload.get("sale_items", [])
        if not items_payload:
            return jsonify({"error": "Aucun article de vente fourni"}), 400

        total_amount_due = Decimal("0.00")
        sale_items_to_add = []

        for item in items_payload:
            network_str = item.get("network", "").lower()
            try:
                network_enum = NetworkType(network_str)
            except ValueError:
                return jsonify({"error": f"Réseau invalide: {network_str}"}), 400

            quantity = int(item.get("quantity", 0))
            if quantity < 1:
                return jsonify({"error": "Quantité invalide"}), 400

            stock_item = Stock.query.filter_by(
                vendeur_id=vendeur_id, network=network_enum
            ).first()
            if not stock_item:
                return jsonify({"error": f"Stock '{network_str}' introuvable"}), 400

            if quantity > stock_item.balance:
                return jsonify({
                    "error": f"Stock insuffisant pour {network_str}. "
                             f"Disponible: {stock_item.balance}, Demandé: {quantity}"
                }), 400

            # Determine price
            price_override = item.get("price_per_unit_applied")
            if price_override is not None:
                try:
                    final_unit_price = Decimal(str(price_override))
                except InvalidOperation:
                    return jsonify({"error": "Prix unitaire invalide"}), 400
            elif stock_item.selling_price_per_unit and stock_item.selling_price_per_unit > 0:
                final_unit_price = stock_item.selling_price_per_unit
            else:
                return jsonify({
                    "error": f"Prix introuvable pour '{network_str}'. "
                             "Définissez un prix dans le stock ou entrez-le manuellement."
                }), 400

            subtotal = custom_round_up(quantity * final_unit_price)
            stock_item.balance -= quantity
            db.session.add(stock_item)

            sale_items_to_add.append(SaleItem(
                network=network_enum,
                quantity=quantity,
                price_per_unit_applied=final_unit_price,
                subtotal=subtotal,
            ))
            total_amount_due += subtotal

        # ── Financials ───────────────────────────────────────────────────────
        try:
            cash_paid = Decimal(str(payload.get("cash_paid", "0")))
        except InvalidOperation:
            cash_paid = Decimal("0.00")

        debt_amount = total_amount_due - cash_paid
        if debt_amount < 0:
            return jsonify({"error": "Le montant payé dépasse le total dû"}), 400

        # ── Save ─────────────────────────────────────────────────────────────
        new_sale = Sale(
            seller_id=current_user.id,
            vendeur_id=vendeur_id,
            client=client,
            client_name_adhoc=client_name_adhoc,
            total_amount_due=total_amount_due,
            cash_paid=cash_paid,
            debt_amount=debt_amount,
        )
        new_sale.sale_items.extend(sale_items_to_add)
        db.session.add(new_sale)
        db.session.commit()

        return jsonify({
            "status":   "created",
            "sale_id":  new_sale.id,
            "local_id": local_id,
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[API] Sale sync error: {e}")
        return jsonify({"error": "Erreur serveur lors de l'enregistrement de la vente"}), 500


# ── Stock Purchases ───────────────────────────────────────────────────────────
@api_bp.route("/stock-purchases", methods=["POST"])
@login_required
def create_stock_purchase():
    """
    Accepts an offline-queued stock purchase.

    Required fields:
      - network: string (airtel|africel|orange|vodacom)
      - amount_purchased: int
      - buying_price_choice: string (decimal or "custom")
      - custom_buying_price: number|null
      - intended_selling_price_choice: string (decimal or "custom")
      - custom_intended_selling_price: number|null
      - local_id: string (UUID)
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON body"}), 400

    vendeur_id = current_user.business_vendeur_id
    if vendeur_id is None:
        return jsonify({"error": "Platform admins cannot submit purchases via API"}), 403

    # Only vendeurs (not stockeurs) can purchase stock — match vendeur_required decorator
    from apps.models import RoleType
    if current_user.role not in (RoleType.VENDEUR, RoleType.PLATFORM_ADMIN):
        return jsonify({"error": "Accès refusé — seuls les vendeurs peuvent acheter du stock"}), 403

    local_id = payload.get("local_id")

    try:
        # Network
        network_str = payload.get("network", "").lower()
        try:
            network_enum = NetworkType(network_str)
        except ValueError:
            return jsonify({"error": f"Réseau invalide: {network_str}"}), 400

        # Quantity
        amount_purchased = int(payload.get("amount_purchased", 0))
        if amount_purchased < 1:
            return jsonify({"error": "Quantité invalide"}), 400

        # Buying price
        bp_choice = payload.get("buying_price_choice", "")
        if bp_choice == "custom":
            raw = payload.get("custom_buying_price")
            if raw is None:
                return jsonify({"error": "Prix d'achat personnalisé manquant"}), 400
            buying_price = Decimal(str(raw))
        else:
            try:
                buying_price = Decimal(str(bp_choice))
            except InvalidOperation:
                return jsonify({"error": "Prix d'achat invalide"}), 400

        # Selling price
        sp_choice = payload.get("intended_selling_price_choice", "")
        if sp_choice == "custom":
            raw = payload.get("custom_intended_selling_price")
            if raw is None:
                return jsonify({"error": "Prix de vente personnalisé manquant"}), 400
            selling_price = Decimal(str(raw))
        else:
            try:
                selling_price = Decimal(str(sp_choice))
            except InvalidOperation:
                return jsonify({"error": "Prix de vente invalide"}), 400

        # Update or create stock
        stock_item = Stock.query.filter_by(
            vendeur_id=vendeur_id, network=network_enum
        ).first()

        if stock_item:
            stock_item.balance += amount_purchased
            stock_item.buying_price_per_unit = buying_price
            stock_item.selling_price_per_unit = selling_price
        else:
            stock_item = Stock(
                vendeur_id=vendeur_id,
                network=network_enum,
                balance=amount_purchased,
                buying_price_per_unit=buying_price,
                selling_price_per_unit=selling_price,
                reduction_rate=Decimal("0.00"),
            )
            db.session.add(stock_item)

        db.session.flush()

        new_purchase = StockPurchase(
            stock_item_id=stock_item.id,
            network=network_enum,
            amount_purchased=amount_purchased,
            buying_price_at_purchase=buying_price,
            selling_price_at_purchase=selling_price,
            purchased_by=current_user,
        )
        db.session.add(new_purchase)
        db.session.commit()

        return jsonify({
            "status":      "created",
            "purchase_id": new_purchase.id,
            "local_id":    local_id,
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[API] Stock purchase sync error: {e}")
        return jsonify({"error": "Erreur serveur lors de l'enregistrement de l'achat"}), 500


# ── Cash Outflows ─────────────────────────────────────────────────────────────
@api_bp.route("/cash-outflows", methods=["POST"])
@login_required
def create_cash_outflow():
    """
    Accepts an offline-queued cash outflow.

    Required fields:
      - amount: number
      - category: string (enum name, e.g. "OPERATING_EXPENSE")
      - description: string|null
      - local_id: string (UUID)
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON body"}), 400

    vendeur_id = current_user.business_vendeur_id
    if vendeur_id is None:
        return jsonify({"error": "Platform admins cannot submit outflows via API"}), 403

    local_id = payload.get("local_id")

    try:
        amount_raw = payload.get("amount")
        if amount_raw is None:
            return jsonify({"error": "Montant manquant"}), 400
        amount = Decimal(str(amount_raw))
        if amount <= 0:
            return jsonify({"error": "Le montant doit être positif"}), 400

        # Category — accept enum name or enum value
        category_raw = payload.get("category", "")
        category = None
        # Try by name first (e.g. "OPERATING_EXPENSE")
        try:
            category = CashOutflowCategory[category_raw]
        except KeyError:
            # Try by value (e.g. "Frais de Fonctionnement")
            for cat in CashOutflowCategory:
                if cat.value == category_raw:
                    category = cat
                    break

        if category is None:
            category = CashOutflowCategory.OTHER

        description = payload.get("description", "") or ""

        new_outflow = CashOutflow(
            amount=amount,
            category=category,
            description=description,
            recorded_by=current_user,
            vendeur_id=vendeur_id,
        )
        db.session.add(new_outflow)
        db.session.commit()

        return jsonify({
            "status":     "created",
            "outflow_id": new_outflow.id,
            "local_id":   local_id,
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[API] Cash outflow sync error: {e}")
        return jsonify({"error": "Erreur serveur lors de l'enregistrement de la sortie cash"}), 500


# ── Sync status ───────────────────────────────────────────────────────────────
@api_bp.route("/sync/status", methods=["GET"])
@login_required
def sync_status():
    """Returns a lightweight status response — used to detect connectivity."""
    return jsonify({"status": "online", "user": current_user.username}), 200
