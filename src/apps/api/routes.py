"""
Faida API v1 — JSON endpoints for offline sync
All routes require an active Flask session (login_required).
"""
from flask import jsonify, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
from uuid import uuid4
from hashlib import sha256

from apps.api import api_bp
from apps import db
from apps.models import (
    BusinessType,
    BusinessApprovalStatus,
    NetworkType,
    CashOutflowCategory,
    Stock,
    Sale,
    SaleItem,
    CashOutflow,
    Client,
    TransactionStatus,
    PriceOperation,
    PricePreset,
    User,
    SmsIngestion,
    CurrencyCode,
    WholesaleCashDirection,
    WholesaleCashEntry,
)
from apps.businesses import (
    businesses_for_user,
    get_current_business,
    resolve_business_for_user,
)
from apps.main.utils import custom_round_up, calculate_sale_total
from apps.payments import apply_payment_to_sale
from apps.inventory import consume_stock
from apps.money import (
    require_comparable_unit_prices,
    require_ledger_amount,
    require_quantity,
)
from apps.purchases import record_retail_purchase, record_wholesale_purchase
from apps.dates import business_local_date
from apps.sales import record_wholesale_sale
from apps.client_identities import ClientIdentityError, resolve_sms_sale_client
from apps.wholesale_cashbook import (
    CashbookEntryError,
    correct_cashbook_entry,
    record_cashbook_entry,
    reverse_cashbook_entry,
)


@api_bp.before_request
def protect_wholesale_from_legacy_sync_api():
    """Do not let legacy FC sync endpoints mutate an active USD ledger."""
    if request.endpoint in {
        "api_bp.health",
        "api_bp.android_businesses",
        "api_bp.sms_ingest",
        "api_bp.create_wholesale_cash_entry",
        "api_bp.correct_wholesale_cash_entry",
        "api_bp.reverse_wholesale_cash_entry",
    } or not current_user.is_authenticated:
        return None
    business = get_current_business()
    if business is not None and business.business_type == BusinessType.WHOLESALE:
        return jsonify({"error": "La synchronisation grossiste arrive bientôt."}), 409
    return None


# ── Health check ──────────────────────────────────────────────────────────────
@api_bp.route("/health", methods=["GET"])
def health():
    """Tiny response used by faida-offline.js to verify connectivity."""
    return jsonify({"status": "ok"}), 200


def _cashbook_business(payload):
    try:
        business = resolve_business_for_user(
            user=current_user, business_id=payload.get("business_id")
        )
    except (PermissionError, TypeError, ValueError) as error:
        raise PermissionError("Vous n'avez pas accès à cette caisse.") from error
    if business is None or business.business_type != BusinessType.WHOLESALE:
        raise CashbookEntryError("Choisissez le mode grossiste concerné.")
    return business


def _cashbook_values(payload):
    try:
        return {
            "direction": WholesaleCashDirection[str(payload["direction"]).upper()],
            "amount": payload["amount"],
            "currency_code": CurrencyCode[str(payload["currency_code"]).upper()],
            "description": payload["description"],
            "entry_date": date.fromisoformat(str(payload["entry_date"])),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise CashbookEntryError("Les informations du mouvement sont incomplètes.") from error


@api_bp.route("/wholesale-cash-entries", methods=["POST"])
@login_required
def create_wholesale_cash_entry():
    payload = request.get_json(silent=True) or {}
    try:
        business = _cashbook_business(payload)
        entry, created = record_cashbook_entry(
            business=business,
            recorded_by=current_user,
            request_id=payload.get("request_id") or payload.get("local_id"),
            **_cashbook_values(payload),
        )
        db.session.commit()
        return jsonify({
            "status": "created" if created else "duplicate",
            "entry_id": entry.id,
            "request_id": entry.request_id,
        }), 201 if created else 200
    except PermissionError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 403
    except CashbookEntryError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400


@api_bp.route(
    "/wholesale-cash-entries/<int:entry_id>/corrections", methods=["POST"]
)
@login_required
def correct_wholesale_cash_entry(entry_id):
    payload = request.get_json(silent=True) or {}
    try:
        business = _cashbook_business(payload)
        entry = WholesaleCashEntry.query.filter_by(
            id=entry_id, business_id=business.id
        ).first()
        if entry is None:
            return jsonify({"error": "Ce mouvement n'existe plus."}), 404
        replacement, created = correct_cashbook_entry(
            entry=entry,
            business=business,
            corrected_by=current_user,
            request_id=payload.get("request_id") or payload.get("local_id"),
            **_cashbook_values(payload),
        )
        db.session.commit()
        return jsonify({
            "status": "corrected" if created else "duplicate",
            "entry_id": replacement.id,
            "request_id": replacement.request_id,
        }), 201 if created else 200
    except PermissionError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 403
    except CashbookEntryError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 409


@api_bp.route("/wholesale-cash-entries/<int:entry_id>/reverse", methods=["POST"])
@login_required
def reverse_wholesale_cash_entry(entry_id):
    payload = request.get_json(silent=True) or {}
    try:
        business = _cashbook_business(payload)
        entry = WholesaleCashEntry.query.filter_by(
            id=entry_id, business_id=business.id
        ).first()
        if entry is None:
            return jsonify({"error": "Ce mouvement n'existe plus."}), 404
        reversed_now = reverse_cashbook_entry(
            entry=entry,
            business=business,
            reversed_by=current_user,
            reason=payload.get("reason") or "Supprimé par l'utilisateur",
        )
        db.session.commit()
        return jsonify({
            "status": "reversed" if reversed_now else "duplicate",
            "entry_id": entry.id,
        }), 200
    except PermissionError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 403
    except CashbookEntryError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 409


# ── Stock levels ──────────────────────────────────────────────────────────────
@api_bp.route("/stock", methods=["GET"])
@login_required
def get_stock():
    """
    Returns current stock levels for the authenticated user's business.
    Cached by faida-offline.js for use when offline.
    """
    business = get_current_business()
    if business is None or current_user.business_vendeur_id is None:
        return jsonify({"error": "Choisissez un compte vendeur pour consulter son stock."}), 400

    stocks = Stock.query.filter_by(business_id=business.id).all()
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
        return jsonify({"error": "Les données envoyées sont incomplètes. Réessayez."}), 400

    local_id = payload.get("local_id")
    vendeur_id = current_user.business_vendeur_id
    business = get_current_business()

    if vendeur_id is None or business is None:
        return jsonify({"error": "Un administrateur ne peut pas enregistrer une vente à la place d'un vendeur."}), 403

    try:
        # ── Resolve client ───────────────────────────────────────────────────
        client = None
        client_name_adhoc = None
        adhoc_customer_key = None
        client_choice = payload.get("client_choice", "new")

        if client_choice == "existing":
            cid = payload.get("existing_client_id")
            if cid:
                client = Client.query.filter_by(
                    id=int(cid), business_id=business.id
                ).first()
                if not client:
                    return jsonify({"error": "Le client sélectionné n'est plus disponible. Choisissez un autre client."}), 400
        else:
            selected_key = (payload.get("adhoc_customer_key") or "").strip()
            if selected_key:
                prior_identity = Sale.query.filter(
                    Sale.business_id == business.id,
                    Sale.client_id.is_(None),
                    Sale.adhoc_customer_key == selected_key,
                    Sale.status == TransactionStatus.ACTIVE,
                ).order_by(Sale.created_at.desc()).first()
                if not prior_identity:
                    return jsonify({"error": "Ce client occasionnel n'a pas pu être identifié. Sélectionnez-le de nouveau."}), 400
                client_name_adhoc = prior_identity.client_display_name
                adhoc_customer_key = selected_key
            else:
                client_name_adhoc = payload.get("new_client_name") or "Client inconnu"
                adhoc_customer_key = uuid4().hex

        # ── Process sale items ───────────────────────────────────────────────
        items_payload = payload.get("sale_items", [])
        if not items_payload:
            return jsonify({"error": "Ajoutez au moins un réseau à la vente."}), 400

        raw_subtotals = []
        sale_items_to_add = []

        for item in items_payload:
            network_str = item.get("network", "").lower()
            try:
                network_enum = NetworkType(network_str)
            except ValueError:
                return jsonify({"error": f"Le réseau '{network_str}' n'est pas reconnu. Sélectionnez-le de nouveau."}), 400

            quantity = int(require_quantity(item.get("quantity", 0)))

            stock_item = Stock.query.filter_by(
                business_id=business.id, network=network_enum
            ).first()
            if not stock_item:
                return jsonify({"error": f"Le stock {network_str} n'est pas configuré. Enregistrez d'abord un stock d'ouverture ou un achat."}), 400

            if quantity > stock_item.balance:
                return jsonify({
                    "error": f"Stock insuffisant pour {network_str}. "
                             f"Disponible: {stock_item.balance}, Demandé: {quantity}"
                }), 400

            # Determine price
            price_override = item.get("price_per_unit_applied")
            if price_override is not None:
                try:
                    final_unit_price = require_ledger_amount(
                        price_override, label="Le prix de vente"
                    )
                except InvalidOperation:
                    return jsonify({"error": "Le prix unitaire saisi n'est pas valide."}), 400
            elif stock_item.selling_price_per_unit and stock_item.selling_price_per_unit > 0:
                final_unit_price = require_ledger_amount(
                    stock_item.selling_price_per_unit,
                    label="Le prix de vente",
                )
            else:
                return jsonify({
                    "error": f"Prix introuvable pour '{network_str}'. "
                             "Définissez un prix dans le stock ou entrez-le manuellement."
                }), 400

            require_comparable_unit_prices(
                cost=stock_item.average_cost_per_unit
                or stock_item.buying_price_per_unit,
                selling_price=final_unit_price,
            )
            subtotal = (Decimal(quantity) * final_unit_price).quantize(Decimal("0.01"))
            require_ledger_amount(subtotal, label="Le total de la vente")
            cost_per_unit, cost_total = consume_stock(
                stock=stock_item, quantity=quantity
            )
            db.session.add(stock_item)

            sale_items_to_add.append(SaleItem(
                network=network_enum,
                quantity=quantity,
                price_per_unit_applied=final_unit_price,
                subtotal=subtotal,
                cost_per_unit_snapshot=cost_per_unit,
                cost_total=cost_total,
                margin_amount=subtotal - cost_total,
                is_cost_estimated=False,
            ))
            raw_subtotals.append(subtotal)

        total_amount_due = calculate_sale_total(raw_subtotals)
        require_ledger_amount(total_amount_due, label="Le total de la vente")

        # ── Financials ───────────────────────────────────────────────────────
        try:
            cash_paid = require_ledger_amount(
                payload.get("cash_paid", "0"),
                label="Le montant payé",
                allow_zero=True,
            )
        except InvalidOperation:
            cash_paid = Decimal("0.00")

        # ── Save ─────────────────────────────────────────────────────────────
        new_sale = Sale(
            seller_id=current_user.id,
            vendeur_id=vendeur_id,
            business_id=business.id,
            client=client,
            client_name_adhoc=client_name_adhoc,
            adhoc_customer_key=adhoc_customer_key,
            total_amount_due=total_amount_due,
            cash_paid=Decimal("0.00"),
            debt_amount=total_amount_due,
        )
        new_sale.sale_items.extend(sale_items_to_add)
        db.session.add(new_sale)
        db.session.flush()
        apply_payment_to_sale(
            sale=new_sale,
            amount=cash_paid,
            recorded_by=current_user,
            payment_date=new_sale.sale_date,
        )
        db.session.commit()

        return jsonify({
            "status":   "created",
            "sale_id":  new_sale.id,
            "local_id": local_id,
        }), 201

    except ClientIdentityError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 409
    except (ValueError, InvalidOperation, TypeError, OverflowError) as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
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
        return jsonify({"error": "Les données envoyées sont incomplètes. Réessayez."}), 400

    vendeur_id = current_user.business_vendeur_id
    business = get_current_business()
    if vendeur_id is None or business is None:
        return jsonify({"error": "Un administrateur ne peut pas enregistrer un achat à la place d'un vendeur."}), 403

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

        new_purchase = record_retail_purchase(
            business=business,
            purchased_by=current_user,
            network=network_enum,
            quantity=amount_purchased,
            unit_cost=buying_price,
            intended_selling_price=selling_price,
        )
        db.session.flush()
        db.session.commit()

        return jsonify({
            "status":      "created",
            "purchase_id": new_purchase.id,
            "local_id":    local_id,
        }), 201

    except (ValueError, InvalidOperation, TypeError, OverflowError) as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
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
        return jsonify({"error": "Les données envoyées sont incomplètes. Réessayez."}), 400

    vendeur_id = current_user.business_vendeur_id
    business = get_current_business()
    if vendeur_id is None or business is None:
        return jsonify({"error": "Un administrateur ne peut pas enregistrer une sortie de caisse à la place d'un vendeur."}), 403

    local_id = payload.get("local_id")

    try:
        amount_raw = payload.get("amount")
        if amount_raw is None:
            return jsonify({"error": "Montant manquant"}), 400
        amount = require_ledger_amount(amount_raw, label="Le montant")

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
            business_id=business.id,
        )
        db.session.add(new_outflow)
        db.session.commit()

        return jsonify({
            "status":     "created",
            "outflow_id": new_outflow.id,
            "local_id":   local_id,
        }), 201

    except (ValueError, InvalidOperation, TypeError, OverflowError) as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
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


# ── SMS auto-capture ──────────────────────────────────────────────────────────
def _authenticate_android_token():
    """Resolve an active vendor from the personal Android API token."""
    token = request.headers.get("X-Api-Token", "").strip()
    if not token:
        return None
    return User.query.filter_by(api_token=token, is_active=True).first()


@api_bp.route("/android/businesses", methods=["GET"])
def android_businesses():
    """List approved owner modes so Android can bind capture explicitly."""
    user = _authenticate_android_token()
    if user is None:
        return jsonify({"error": "Code API invalide ou compte désactivé"}), 401
    businesses = [
        business for business in businesses_for_user(user)
        if business.owner_user_id == user.id
        and business.approval_status == BusinessApprovalStatus.APPROVED
    ]
    return jsonify({"businesses": [
        {
            "id": business.id,
            "name": business.name,
            "type": business.business_type.value,
            "label": (
                f"Mode grossiste — {business.name}"
                if business.business_type == BusinessType.WHOLESALE
                else f"Mode détail — {business.name}"
            ),
        }
        for business in businesses
    ]}), 200


@api_bp.route("/sms-ingest", methods=["POST"])
def sms_ingest():
    """
    Receives a raw SMS from the Android TWA BroadcastReceiver and creates
    the appropriate Sale or StockPurchase record automatically.

    Auth: active Flask session (browser) OR X-Api-Token header (Android app).
    Body: { "sender": "1000", "body": "5037:Votre transfert de 2500 U au 972067057..." }

    Returns:
      type=sale     → Sale created, client linked if phone matched
      type=purchase → StockPurchase created, stock balance increased
      type=unknown  → Sender or pattern not recognized, ignored silently
    """
    # Authenticate: session (browser) or X-Api-Token header (Android)
    if current_user.is_authenticated:
        authed_user = current_user
    else:
        authed_user = _authenticate_android_token()
        if not authed_user:
            return jsonify({"error": "Code Android incorrect ou compte désactivé. Vérifiez le code dans l'application."}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Le message envoyé par l'application Android est incomplet. Réessayez."}), 400

    sender = payload.get("sender", "").strip()
    body = payload.get("body", "").strip()
    if not sender or not body:
        return jsonify({"error": "Le numéro de l'expéditeur ou le contenu du SMS est manquant."}), 400

    try:
        if current_user.is_authenticated:
            business = get_current_business()
        else:
            business_id = payload.get("business_id")
            if business_id is None:
                return jsonify({"error": "Choisissez le mode détail ou grossiste avant d'activer la capture."}), 400
            business = resolve_business_for_user(
                user=authed_user, business_id=business_id
            )
    except (PermissionError, TypeError, ValueError):
        return jsonify({"error": "Le mode sélectionné n'est plus disponible. Choisissez-le de nouveau dans l'application."}), 403
    vendeur_id = authed_user.business_vendeur_id
    if vendeur_id is None or business is None:
        return jsonify({"error": "La capture SMS est disponible uniquement pour les comptes vendeurs."}), 403
    if business.owner_user_id != authed_user.id:
        return jsonify({"error": "La capture SMS est réservée au propriétaire"}), 403

    from apps.main.sms_parser import parse_sms
    parsed = parse_sms(sender, body)

    if parsed.message_type == "unknown":
        current_app.logger.debug(f"[SMS] Ignored unknown sender={sender!r}")
        return jsonify({"type": "unknown", "status": "ignored"}), 200

    if parsed.quantity <= 0:
        return jsonify({"error": "La quantité n'a pas pu être lue dans ce SMS. Enregistrez l'opération manuellement."}), 400

    ingestion = None
    if not current_user.is_authenticated:
        try:
            received_at = int(payload.get("received_at"))
            if received_at <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "La date de réception du SMS est manquante. Réessayez la synchronisation."}), 400
        fingerprint = sha256(
            f"{business.id}\0{sender.strip().lower()}\0{body}\0{received_at}".encode("utf-8")
        ).hexdigest()
        existing = SmsIngestion.query.filter_by(
            business_id=business.id, fingerprint=fingerprint
        ).first()
        if existing is not None:
            return jsonify({
                "type": existing.message_type,
                "status": "duplicate",
                "sale_id": existing.sale_id,
                "purchase_id": existing.purchase_id,
            }), 200
        ingestion = SmsIngestion(
            business_id=business.id,
            user_id=authed_user.id,
            fingerprint=fingerprint,
            sender=sender,
            received_at_ms=received_at,
            message_type=parsed.message_type,
        )
        db.session.add(ingestion)
        try:
            db.session.flush()
        except IntegrityError:
            # A concurrent delivery won the unique fingerprint race. Its
            # transaction remains the only one allowed to mutate inventory.
            db.session.rollback()
            existing = SmsIngestion.query.filter_by(
                business_id=business.id, fingerprint=fingerprint
            ).first()
            return jsonify({
                "type": existing.message_type if existing else parsed.message_type,
                "status": "duplicate",
                "sale_id": existing.sale_id if existing else None,
                "purchase_id": existing.purchase_id if existing else None,
            }), 200

    try:
        if business.business_type == BusinessType.WHOLESALE:
            if parsed.message_type == "sale":
                return _sms_create_wholesale_sale(
                    parsed, business, authed_user, ingestion=ingestion
                )
            return _sms_create_wholesale_purchase(
                parsed, business, authed_user, ingestion=ingestion
            )
        if parsed.message_type == "sale":
            return _sms_create_sale(parsed, business, vendeur_id, authed_user)
        else:
            return _sms_create_purchase(parsed, business, vendeur_id, authed_user)
    except (ValueError, PermissionError) as error:
        db.session.rollback()
        return jsonify({"error": str(error).replace("\n", " ")}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[SMS ingest] Unhandled error: {e}", exc_info=True)
        return jsonify({"error": "Ce SMS n'a pas pu être enregistré. Vérifiez les informations puis réessayez."}), 500


def _default_wholesale_preset(*, business, network, operation):
    return PricePreset.query.filter_by(
        business_id=business.id,
        network=network,
        operation=operation,
        is_default=True,
        is_active=True,
    ).order_by(PricePreset.display_order, PricePreset.id).first()


def _sms_wholesale_client(parsed, business, owner):
    """Resolve a retailer by its business-scoped network number."""
    client, _created = resolve_sms_sale_client(
        business=business,
        owner=owner,
        network=parsed.network,
        raw_phone=parsed.recipient_phone,
        sms_name=parsed.client_name,
    )
    return client


def _sms_business_date(ingestion=None):
    if ingestion is None:
        return business_local_date()
    received_at = datetime.fromtimestamp(
        ingestion.received_at_ms / 1000,
        tz=timezone.utc,
    )
    return business_local_date(received_at)


def _sms_create_wholesale_sale(parsed, business, owner, *, ingestion=None):
    preset = _default_wholesale_preset(
        business=business,
        network=parsed.network,
        operation=PriceOperation.SALE,
    )
    if preset is None:
        return jsonify({
            "error": f"La vente {parsed.network.value} n'a pas été enregistrée. Choisissez d'abord un prix de vente par défaut."
        }), 400
    client = _sms_wholesale_client(parsed, business, owner)
    sale = record_wholesale_sale(
        business=business,
        sold_by=owner,
        client=client,
        network=parsed.network,
        quantity=parsed.quantity,
        cash_received=Decimal("0"),
        sale_date=_sms_business_date(ingestion),
        preset=preset,
    )
    if ingestion is not None:
        ingestion.sale_id = sale.id
    db.session.commit()
    return jsonify({
        "type": "sale",
        "mode": "wholesale",
        "status": "created",
        "sale_id": sale.id,
        "network": parsed.network.value,
        "quantity": parsed.quantity,
        "total_usd": float(sale.total_amount_due),
        "client": client.name,
        "payment_status": "debt",
    }), 201


def _sms_create_wholesale_purchase(parsed, business, owner, *, ingestion=None):
    preset = _default_wholesale_preset(
        business=business,
        network=parsed.network,
        operation=PriceOperation.PURCHASE,
    )
    if preset is None:
        return jsonify({
            "error": f"L'achat {parsed.network.value} n'a pas été enregistré. Choisissez d'abord un prix d'achat par défaut."
        }), 400
    purchase = record_wholesale_purchase(
        business=business,
        purchased_by=owner,
        network=parsed.network,
        quantity=parsed.quantity,
        preset=preset,
        purchase_date=_sms_business_date(ingestion),
    )
    db.session.flush()
    if ingestion is not None:
        ingestion.purchase_id = purchase.id
    db.session.commit()
    return jsonify({
        "type": "purchase",
        "mode": "wholesale",
        "status": "created",
        "purchase_id": purchase.id,
        "network": parsed.network.value,
        "quantity": parsed.quantity,
        "total_usd": float(purchase.actual_total_cost),
        "new_balance": float(purchase.stock_item.balance),
    }), 201


def _sms_create_sale(parsed, business, vendeur_id: int, authed_user):
    """Create a Sale from a parsed sell SMS."""
    client, client_created = resolve_sms_sale_client(
        business=business,
        owner=business.owner,
        network=parsed.network,
        raw_phone=parsed.recipient_phone,
        sms_name=parsed.client_name,
    )

    # Get stock for this network
    stock_item = Stock.query.filter_by(
        business_id=business.id, network=parsed.network
    ).first()
    if not stock_item:
        return jsonify({"error": f"Le stock {parsed.network.value} n'est pas configuré. Enregistrez d'abord un stock d'ouverture ou un achat."}), 400

    if parsed.quantity > stock_item.balance:
        return jsonify({
            "type": "sale",
            "status": "rejected",
            "error": (
                f"Stock {parsed.network.value} insuffisant: "
                f"{stock_item.balance} disponible, {parsed.quantity} demandé"
            ),
        }), 400

    quantity = require_quantity(parsed.quantity)
    unit_price = require_ledger_amount(
        stock_item.selling_price_per_unit or Decimal("1.00"),
        label="Le prix de vente",
    )
    require_comparable_unit_prices(
        cost=stock_item.average_cost_per_unit or stock_item.buying_price_per_unit,
        selling_price=unit_price,
    )
    subtotal = custom_round_up(quantity * unit_price)
    require_ledger_amount(subtotal, label="Le total de la vente")

    cost_per_unit, cost_total = consume_stock(
        stock=stock_item, quantity=parsed.quantity
    )
    db.session.add(stock_item)

    sale_item = SaleItem(
        network=parsed.network,
        quantity=int(quantity),
        price_per_unit_applied=unit_price,
        subtotal=subtotal,
        cost_per_unit_snapshot=cost_per_unit,
        cost_total=cost_total,
        margin_amount=subtotal - cost_total,
        is_cost_estimated=False,
    )
    new_sale = Sale(
        seller_id=authed_user.id,
        vendeur_id=vendeur_id,
        business_id=business.id,
        client=client,
        client_name_adhoc=None,
        adhoc_customer_key=None,
        sale_date=date.today(),
        total_amount_due=subtotal,
        cash_paid=subtotal,    # assume cash received; vendor edits if credit
        debt_amount=Decimal("0.00"),
    )
    new_sale.sale_items.append(sale_item)
    db.session.add(new_sale)
    db.session.flush()
    apply_payment_to_sale(
        sale=new_sale,
        amount=subtotal,
        recorded_by=authed_user,
        payment_date=new_sale.sale_date,
    )
    db.session.commit()

    current_app.logger.info(
        f"[SMS] Sale created: #{new_sale.id} {parsed.network.value} "
        f"{parsed.quantity}U → {parsed.recipient_phone} (client_created={client_created})"
    )
    return jsonify({
        "type": "sale",
        "status": "created",
        "sale_id": new_sale.id,
        "network": parsed.network.value,
        "quantity": parsed.quantity,
        "total_fc": float(subtotal),
        "client": client.name,
        "client_known": not client_created,
        "client_needs_name": client.identification_status == "needs_name",
    }), 201


def _sms_create_purchase(parsed, business, vendeur_id: int, authed_user):
    """Create a StockPurchase from a parsed purchase SMS."""
    stock_item = Stock.query.filter_by(
        business_id=business.id, network=parsed.network
    ).first()
    if not stock_item:
        return jsonify({"error": f"Le stock {parsed.network.value} n'est pas configuré. Enregistrez d'abord un stock d'ouverture ou un achat."}), 400

    buying_price = stock_item.buying_price_per_unit or Decimal("0.00")
    selling_price = stock_item.selling_price_per_unit or Decimal("1.00")

    new_purchase = record_retail_purchase(
        business=business,
        purchased_by=authed_user,
        network=parsed.network,
        quantity=parsed.quantity,
        unit_cost=buying_price,
        intended_selling_price=selling_price,
    )
    db.session.commit()

    current_app.logger.info(
        f"[SMS] Purchase created: #{new_purchase.id} {parsed.network.value} "
        f"+{parsed.quantity}U (new balance: {stock_item.balance})"
    )
    return jsonify({
        "type": "purchase",
        "status": "created",
        "purchase_id": new_purchase.id,
        "network": parsed.network.value,
        "quantity": parsed.quantity,
        "new_balance": float(stock_item.balance),
    }), 201
