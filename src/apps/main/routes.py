# ============================================================
# Faida App Buisiness Logic
# ============================================================
from apps.main import pdf_routes
from apps.main import bp
from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required, current_user
from sqlalchemy import func
from jinja2 import TemplateNotFound
from apps.main.utils import (
    custom_round_up,
    calculate_sale_total,
    get_paginated_results,
    get_daily_report_data,
    get_local_timezone_datetime_info,
    APP_TIMEZONE,
    get_date_context,
    get_utc_range_for_date,
    get_stock_purchase_history_query,
    get_sales_history_query,
    update_daily_reports,
)
from apps.payments import (
    apply_additional_payment_to_sale,
    apply_payment_to_sale,
    collect_client_debt,
    reverse_payment_event,
)
from apps.inventory import consume_stock
from apps.client_identities import (
    ClientIdentityError,
    ensure_unique_client_name,
    replace_client_phones,
)

from apps.decorators import (
    platform_admin_required,
    vendeur_required,
    business_member_required,
    get_current_vendeur_id,
    filter_by_vendeur,
    ensure_access,
)

from apps import db
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
import pytz
from apps.models import (
    User,
    RoleType,
    Client,
    StockPurchase,
    NetworkType,
    Stock,
    Sale,
    SaleItem,
    CashOutflow,
    CashInflow,
    CashInflowCategory,
    DailyOverallReport,
    DailyStockReport,
    StockOpeningBalance,
    normalize_phone,
    validate_drc_phone,
    BusinessType,
    CurrencyCode,
    PriceOperation,
    PricePreset,
    PaymentEvent,
    PaymentAllocationKind,
    TransactionStatus,
)

from apps.main.forms import (
    StockeurForm,
    UserEditForm,
    ClientForm,
    ClientEditForm,
    StockPurchaseForm,
    StockOpeningBalanceForm,
    SaleForm,
    CashOutflowForm,
    DebtCollectionForm,
    EditProfileForm,
    DeleteConfirmForm,
    get_clients_with_debt,
    WholesaleBusinessForm,
    WholesalePurchaseForm,
    WholesaleSaleForm,
    WholesaleDebtPaymentForm,
    TransactionReversalForm,
)
from apps.businesses import (
    add_stockeur,
    businesses_for_user,
    create_business,
    get_current_business,
    rename_vendor,
    resolve_business_for_user,
)
from apps.purchases import (
    delete_retail_purchase,
    record_retail_purchase,
    record_wholesale_purchase,
    replace_retail_purchase,
    reverse_wholesale_purchase,
)
from apps.sales import (
    record_wholesale_sale,
    reverse_unpaid_sale,
    reverse_unpaid_wholesale_sale,
)
from apps.wholesale_reports import build_wholesale_daily_report


# Define the timezone for the application
APP_TIMEZONE = pytz.timezone("Africa/Lubumbashi")


_WHOLESALE_SAFE_ENDPOINTS = {
    "main_bp.businesses",
    "main_bp.create_wholesale_business",
    "main_bp.switch_business",
    "main_bp.wholesale_dashboard",
    "main_bp.wholesale_purchases",
    "main_bp.reverse_wholesale_purchase_route",
    "main_bp.wholesale_sales",
    "main_bp.reverse_wholesale_sale_route",
    "main_bp.wholesale_clients",
    "main_bp.wholesale_client_management",
    "main_bp.wholesale_client_edit",
    "main_bp.wholesale_client_archive",
    "main_bp.wholesale_client_detail",
    "main_bp.reverse_wholesale_payment_route",
    "main_bp.wholesale_report",
    "main_bp.profile",
    "main_bp.health",
}


@bp.before_request
def protect_unmigrated_wholesale_routes():
    """Keep wholesale sessions out of legacy retailer-scoped screens."""
    if not current_user.is_authenticated or current_user.is_platform_admin:
        return None
    business = get_current_business()
    if (
        business is not None
        and business.business_type == BusinessType.WHOLESALE
        and request.endpoint not in _WHOLESALE_SAFE_ENDPOINTS
    ):
        flash("Cette page n'est pas disponible ici.", "info")
        return redirect(url_for("main_bp.wholesale_dashboard"))
    return None


@bp.route("/businesses")
@login_required
def businesses():
    available_businesses = businesses_for_user(current_user)
    return render_template(
        "main/businesses.html",
        businesses=available_businesses,
        has_wholesale=any(
            business.business_type == BusinessType.WHOLESALE
            for business in available_businesses
        ),
        current_business=get_current_business(),
        form=WholesaleBusinessForm(),
        segment="businesses",
    )


@bp.route("/businesses/wholesale/create", methods=["POST"])
@login_required
@vendeur_required
def create_wholesale_business():
    if not current_user.is_vendeur:
        abort(403)
    form = WholesaleBusinessForm()
    if not form.validate_on_submit():
        flash("Entrez un nom valide.", "danger")
        return redirect(url_for("main_bp.businesses"))
    if any(
        business.business_type == BusinessType.WHOLESALE
        for business in businesses_for_user(current_user)
    ):
        flash("Ce mode est déjà sur votre compte.", "warning")
        return redirect(url_for("main_bp.businesses"))

    business = create_business(
        owner=current_user,
        name=form.name.data,
        business_type=BusinessType.WHOLESALE,
        currency_code=CurrencyCode.USD,
    )
    db.session.flush()
    for network in NetworkType:
        db.session.add(
            Stock(
                vendeur_id=current_user.id,
                business_id=business.id,
                network=network,
                balance=Decimal("0"),
                buying_price_per_unit=Decimal("0"),
                selling_price_per_unit=Decimal("0.00940"),
                inventory_value=Decimal("0"),
                average_cost_per_unit=Decimal("0"),
            )
        )
    db.session.commit()
    flash(
        "Demande envoyée. Un administrateur doit l'approuver.",
        "success",
    )
    return redirect(url_for("main_bp.businesses"))


@bp.route("/businesses/<int:business_id>/switch", methods=["POST"])
@login_required
def switch_business(business_id):
    try:
        business = resolve_business_for_user(
            user=current_user, business_id=business_id
        )
    except PermissionError:
        abort(403)
    session["active_business_id"] = business.id
    destination = (
        "main_bp.wholesale_dashboard"
        if business.business_type == BusinessType.WHOLESALE
        else "main_bp.index"
    )
    return redirect(url_for(destination))


@bp.route("/businesses/wholesale")
@login_required
def wholesale_dashboard():
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    stocks = (
        Stock.query.filter_by(business_id=business.id)
        .order_by(Stock.network)
        .all()
    )
    return render_template(
        "main/wholesale_dashboard.html",
        business=business,
        stocks=stocks,
        segment="wholesale",
        sub_segment="dashboard",
    )


@bp.route("/businesses/wholesale/purchases", methods=["GET", "POST"])
@login_required
@vendeur_required
def wholesale_purchases():
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)

    presets = (
        PricePreset.query.filter_by(
            business_id=business.id,
            operation=PriceOperation.PURCHASE,
            is_active=True,
        )
        .order_by(PricePreset.network, PricePreset.display_order, PricePreset.id)
        .all()
    )
    form = WholesalePurchaseForm()
    form.price_choice.choices = [
        (f"preset:{preset.id}", f"{preset.network.value.capitalize()} — {preset.label}")
        for preset in presets
    ] + [("custom", "Prix personnalisé")]
    if request.method == "GET":
        form.purchase_date.data = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()

    if form.validate_on_submit():
        try:
            network = NetworkType[form.network.data]
            selected_preset = None
            custom_unit_cost = None
            if form.price_choice.data == "custom":
                custom_unit_cost = form.custom_unit_cost.data
            else:
                preset_id = int(form.price_choice.data.removeprefix("preset:"))
                selected_preset = db.session.get(PricePreset, preset_id)
            record_wholesale_purchase(
                business=business,
                purchased_by=current_user,
                network=network,
                quantity=form.quantity.data,
                preset=selected_preset,
                custom_unit_cost=custom_unit_cost,
                purchase_date=form.purchase_date.data,
            )
            db.session.commit()
            flash("Achat enregistré.", "success")
            return redirect(url_for("main_bp.wholesale_purchases"))
        except (ValueError, PermissionError) as error:
            db.session.rollback()
            flash(str(error), "danger")

    purchases = (
        StockPurchase.query.join(Stock)
        .filter(Stock.business_id == business.id)
        .order_by(StockPurchase.created_at.desc())
        .all()
    )
    preset_data = {network.name: [] for network in NetworkType}
    for preset in presets:
        preset_data[preset.network.name].append(
            {
                "value": f"preset:{preset.id}",
                "label": preset.label,
                "unit_price": str(preset.unit_price),
                "ratio_amount": str(preset.ratio_amount or ""),
                "ratio_units": str(preset.ratio_units or ""),
            }
        )
    return render_template(
        "main/wholesale_purchases.html",
        business=business,
        form=form,
        purchases=purchases,
        preset_data=preset_data,
        reversal_form=TransactionReversalForm(),
        segment="wholesale",
        sub_segment="purchases",
    )


@bp.route("/businesses/wholesale/purchases/<int:purchase_id>/reverse", methods=["POST"])
@login_required
@vendeur_required
def reverse_wholesale_purchase_route(purchase_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    purchase = db.get_or_404(StockPurchase, purchase_id)
    form = TransactionReversalForm()
    if not form.validate_on_submit():
        flash("Ajoutez une raison.", "danger")
        return redirect(url_for("main_bp.wholesale_purchases"))
    try:
        reverse_wholesale_purchase(
            purchase=purchase,
            business=business,
            reversed_by=current_user,
            reason=form.reason.data,
        )
        db.session.commit()
        flash("Achat annulé.", "success")
    except (ValueError, PermissionError) as error:
        db.session.rollback()
        flash(str(error), "danger")
    return redirect(url_for("main_bp.wholesale_purchases"))


@bp.route("/businesses/wholesale/sales", methods=["GET", "POST"])
@login_required
@vendeur_required
def wholesale_sales():
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)

    clients = (
        Client.query.filter_by(business_id=business.id, is_active=True)
        .order_by(Client.name)
        .all()
    )
    presets = (
        PricePreset.query.filter_by(
            business_id=business.id,
            operation=PriceOperation.SALE,
            is_active=True,
        )
        .order_by(PricePreset.network, PricePreset.display_order, PricePreset.id)
        .all()
    )
    form = WholesaleSaleForm()
    form.client_id.choices = [("new", "Nouveau détaillant")] + [
        (str(client.id), client.name) for client in clients
    ]
    form.price_choice.choices = [
        (f"preset:{preset.id}", f"{preset.network.value.capitalize()} — {preset.label}")
        for preset in presets
    ] + [("custom", "Prix personnalisé")]

    if form.validate_on_submit():
        try:
            if form.client_id.data == "new":
                name = (form.new_client_name.data or "").strip()
                if len(name) < 2:
                    raise ValueError("Saisissez le nom du nouveau détaillant.")
                name = ensure_unique_client_name(
                    business_id=business.id, name=name
                )
                client = Client(
                    name=name,
                    vendeur_id=current_user.id,
                    business_id=business.id,
                )
                db.session.add(client)
                db.session.flush()
            else:
                client = db.session.get(Client, int(form.client_id.data))

            network = NetworkType[form.network.data]
            selected_preset = None
            custom_unit_price = None
            if form.price_choice.data == "custom":
                custom_unit_price = form.custom_unit_price.data
            else:
                preset_id = int(form.price_choice.data.removeprefix("preset:"))
                selected_preset = db.session.get(PricePreset, preset_id)
            record_wholesale_sale(
                business=business,
                sold_by=current_user,
                client=client,
                network=network,
                quantity=form.quantity.data,
                cash_received=form.cash_received.data or Decimal("0"),
                sale_date=datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date(),
                preset=selected_preset,
                custom_unit_price=custom_unit_price,
            )
            db.session.commit()
            flash("Vente enregistrée.", "success")
            return redirect(url_for("main_bp.wholesale_sales"))
        except (ValueError, PermissionError) as error:
            db.session.rollback()
            flash(str(error), "danger")

    today = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()
    sales = (
        Sale.query.filter_by(business_id=business.id)
        .order_by(Sale.created_at.desc())
        .limit(100)
        .all()
    )
    daily_report = build_wholesale_daily_report(
        business=business,
        target_date=today,
    )

    preset_data = {network.name: [] for network in NetworkType}
    for preset in presets:
        preset_data[preset.network.name].append({
            "value": f"preset:{preset.id}",
            "label": preset.label,
            "unit_price": str(preset.unit_price),
        })
    return render_template(
        "main/wholesale_sales.html",
        business=business,
        form=form,
        sales=sales,
        daily_report=daily_report,
        preset_data=preset_data,
        reversal_form=TransactionReversalForm(),
        segment="wholesale",
        sub_segment="sales",
    )


@bp.route("/businesses/wholesale/sales/<int:sale_id>/reverse", methods=["POST"])
@login_required
@vendeur_required
def reverse_wholesale_sale_route(sale_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    sale = db.get_or_404(Sale, sale_id)
    form = TransactionReversalForm()
    if not form.validate_on_submit():
        flash("Ajoutez une raison.", "danger")
        return redirect(url_for("main_bp.wholesale_sales"))
    try:
        reverse_unpaid_wholesale_sale(
            sale=sale,
            business=business,
            reversed_by=current_user,
            reason=form.reason.data,
        )
        db.session.commit()
        flash("Vente annulée.", "success")
    except (ValueError, PermissionError) as error:
        db.session.rollback()
        flash(str(error), "danger")
    return redirect(url_for("main_bp.wholesale_sales"))


@bp.route("/businesses/wholesale/client-management", methods=["GET", "POST"])
@login_required
@vendeur_required
def wholesale_client_management():
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)

    form = ClientForm()
    if form.validate_on_submit():
        try:
            client = Client(
                name=ensure_unique_client_name(
                    business_id=business.id, name=form.name.data
                ),
                vendeur_id=current_user.id,
                business_id=business.id,
                address=form.address.data,
            )
            db.session.add(client)
            db.session.flush()
            replace_client_phones(
                client=client, phone_entries=_client_phone_entries(form)
            )
            db.session.commit()
            flash("Client créé.", "success")
            return redirect(url_for("main_bp.wholesale_client_management"))
        except ClientIdentityError as error:
            db.session.rollback()
            flash(str(error), "danger")

    clients = (
        Client.query.filter_by(business_id=business.id)
        .order_by(Client.is_active.desc(), Client.name, Client.id)
        .all()
    )
    return render_template(
        "main/wholesale_client_management.html",
        business=business,
        clients=clients,
        form=form,
        segment="wholesale",
        sub_segment="client_management",
    )


@bp.route(
    "/businesses/wholesale/client-management/<int:client_id>/edit",
    methods=["GET", "POST"],
)
@login_required
@vendeur_required
def wholesale_client_edit(client_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)
    client = db.get_or_404(Client, client_id)
    if client.business_id != business.id:
        abort(403)

    form = ClientEditForm()
    if request.method == "GET":
        form.name.data = client.name
        form.phone_airtel.data = "\n".join(client.airtel_phones)
        form.phone_africel.data = "\n".join(client.africel_phones)
        form.phone_orange.data = "\n".join(client.orange_phones)
        form.phone_vodacom.data = "\n".join(client.vodacom_phones)
        form.address.data = client.address
        form.gps_lat.data = client.gps_lat
        form.gps_long.data = client.gps_long
        form.is_active.data = client.is_active
    elif form.validate_on_submit():
        try:
            client.name = ensure_unique_client_name(
                business_id=business.id,
                name=form.name.data,
                exclude_client_id=client.id,
            )
            client.address = form.address.data
            client.gps_lat = form.gps_lat.data
            client.gps_long = form.gps_long.data
            client.is_active = form.is_active.data
            client.identification_status = "identified"
            replace_client_phones(
                client=client, phone_entries=_client_phone_entries(form)
            )
            db.session.commit()
            flash("Client mis à jour.", "success")
            return redirect(url_for("main_bp.wholesale_client_management"))
        except ClientIdentityError as error:
            db.session.rollback()
            flash(str(error), "danger")

    return render_template(
        "main/wholesale_client_edit.html",
        business=business,
        client=client,
        form=form,
        segment="wholesale",
        sub_segment="client_management",
    )


@bp.route(
    "/businesses/wholesale/client-management/<int:client_id>/archive",
    methods=["POST"],
)
@login_required
@vendeur_required
def wholesale_client_archive(client_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)
    client = db.get_or_404(Client, client_id)
    if client.business_id != business.id:
        abort(403)
    if not client.is_active:
        try:
            ensure_unique_client_name(
                business_id=business.id,
                name=client.name,
                exclude_client_id=client.id,
            )
        except ClientIdentityError as error:
            flash(str(error), "danger")
            return redirect(url_for("main_bp.wholesale_client_management"))
    client.is_active = not client.is_active
    db.session.commit()
    flash(
        f"Client {'réactivé' if client.is_active else 'archivé'} avec succès.",
        "success",
    )
    return redirect(url_for("main_bp.wholesale_client_management"))


@bp.route("/businesses/wholesale/clients")
@login_required
@vendeur_required
def wholesale_clients():
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)

    clients = (
        Client.query.filter_by(business_id=business.id)
        .order_by(Client.name, Client.id)
        .all()
    )
    totals = {
        row.client_id: row
        for row in db.session.query(
            Sale.client_id,
            func.count(Sale.id).label("sale_count"),
            func.sum(Sale.total_amount_due).label("purchased"),
            func.sum(Sale.cash_paid).label("paid"),
            func.sum(Sale.debt_amount).label("debt"),
        )
        .filter(
            Sale.business_id == business.id,
            Sale.client_id.isnot(None),
            Sale.status == TransactionStatus.ACTIVE,
        )
        .group_by(Sale.client_id)
        .all()
    }
    return render_template(
        "main/wholesale_clients.html",
        business=business,
        clients=clients,
        totals=totals,
        segment="wholesale",
        sub_segment="clients",
    )


@bp.route("/businesses/wholesale/clients/<int:client_id>", methods=["GET", "POST"])
@login_required
@vendeur_required
def wholesale_client_detail(client_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)
    client = db.get_or_404(Client, client_id)
    if client.business_id != business.id:
        abort(403)

    form = WholesaleDebtPaymentForm()
    if request.method == "GET":
        form.payment_date.data = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()
    if form.validate_on_submit():
        try:
            collect_client_debt(
                business=business,
                client=client,
                amount=form.amount.data,
                recorded_by=current_user,
                payment_date=form.payment_date.data,
                description=form.description.data,
            )
            db.session.commit()
            flash("Paiement appliqué.", "success")
            return redirect(
                url_for("main_bp.wholesale_client_detail", client_id=client.id)
            )
        except (ValueError, PermissionError) as error:
            db.session.rollback()
            flash(str(error), "danger")

    sales = (
        Sale.query.filter_by(business_id=business.id, client_id=client.id)
        .order_by(Sale.sale_date.desc(), Sale.created_at.desc())
        .all()
    )
    payments = (
        PaymentEvent.query.filter_by(business_id=business.id, client_id=client.id)
        .order_by(PaymentEvent.payment_date.desc(), PaymentEvent.created_at.desc())
        .all()
    )
    active_sales = [sale for sale in sales if sale.status == TransactionStatus.ACTIVE]
    total_purchased = sum((sale.total_amount_due for sale in active_sales), Decimal("0"))
    total_paid = sum((sale.cash_paid for sale in active_sales), Decimal("0"))
    total_debt = sum((sale.debt_amount for sale in active_sales), Decimal("0"))
    return render_template(
        "main/wholesale_client_detail.html",
        business=business,
        client=client,
        form=form,
        reversal_form=TransactionReversalForm(),
        sales=sales,
        payments=payments,
        total_purchased=total_purchased,
        total_paid=total_paid,
        total_debt=total_debt,
        segment="wholesale",
        sub_segment="client_detail",
    )


@bp.route(
    "/businesses/wholesale/payments/<int:payment_event_id>/reverse",
    methods=["POST"],
)
@login_required
@vendeur_required
def reverse_wholesale_payment_route(payment_event_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    payment_event = db.get_or_404(PaymentEvent, payment_event_id)
    client_id = payment_event.client_id
    form = TransactionReversalForm()
    if not form.validate_on_submit():
        flash("Ajoutez une raison.", "danger")
        return redirect(
            url_for("main_bp.wholesale_client_detail", client_id=client_id)
        )
    try:
        reverse_payment_event(
            payment_event=payment_event,
            business=business,
            reversed_by=current_user,
            reason=form.reason.data,
        )
        db.session.commit()
        flash("Paiement annulé.", "success")
    except (ValueError, PermissionError, RuntimeError) as error:
        db.session.rollback()
        flash(str(error), "danger")
    return redirect(
        url_for("main_bp.wholesale_client_detail", client_id=client_id)
    )


@bp.route("/businesses/wholesale/report")
@login_required
@vendeur_required
def wholesale_report():
    business = get_current_business()
    if business is None or business.business_type != BusinessType.WHOLESALE:
        return redirect(url_for("main_bp.businesses"))
    if business.owner_user_id != current_user.id:
        abort(403)
    date_text = request.args.get("date", "").strip()
    try:
        target_date = (
            datetime.strptime(date_text, "%Y-%m-%d").date()
            if date_text
            else datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()
        )
    except ValueError:
        flash("Date invalide.", "danger")
        return redirect(url_for("main_bp.wholesale_report"))
    report = build_wholesale_daily_report(
        business=business, target_date=target_date
    )
    return render_template(
        "main/wholesale_report.html",
        business=business,
        report=report,
        segment="wholesale",
        sub_segment="report",
    )


@bp.route("/health")
def health():
    return {"status": "ok"}, 200


@bp.route("/")
@bp.route("/index")
@login_required
def index():
    if current_user.is_platform_admin:
        return redirect(url_for("admin_bp.dashboard"))

    _, today_local_date, _, _ = get_local_timezone_datetime_info()

    # Support ?date= filter; default to today
    ctx = get_date_context()
    selected_date = ctx['selected_date']
    selected_date_str = ctx['date_str']
    is_today = ctx['is_today']

    active_business = get_current_business()
    business_id = active_business.id if active_business else None

    # --- 1. Stock balances — always live (current physical inventory) ---
    if business_id:
        current_stocks = Stock.query.filter_by(business_id=business_id).all()
    else:
        current_stocks = Stock.query.all()
    total_stocks_data = {s.network.value: s.balance for s in current_stocks}

    # --- 2. Sales Over Time chart (always last 7 days from today) ---
    sales_data_week = {}
    for i in range(6, -1, -1):
        d = today_local_date - timedelta(days=i)
        q = db.session.query(func.sum(Sale.total_amount_due))
        if business_id:
            q = q.filter(Sale.business_id == business_id)
        val = q.filter(Sale.sale_date == d).scalar()
        sales_data_week[d.strftime("%a")] = float(val) if val else 0.0

    # --- 3. Sales by Network chart (for the selected date) ---
    sales_by_network = {}
    for network in NetworkType:
        q = db.session.query(func.sum(SaleItem.subtotal)).join(Sale)
        if business_id:
            q = q.filter(Sale.business_id == business_id)
        val = q.filter(SaleItem.network == network, Sale.sale_date == selected_date).scalar()
        sales_by_network[network.value] = float(val) if val else 0.0

    # --- 4. KPI cards — scoped to selected_date ---
    # Total sales
    q = db.session.query(func.sum(Sale.total_amount_due))
    if business_id:
        q = q.filter(Sale.business_id == business_id)
    total_sales_today = float(q.filter(Sale.sale_date == selected_date).scalar() or 0)

    # Debts from sales on selected date
    q = db.session.query(func.sum(Sale.debt_amount)).filter(Sale.debt_amount > 0)
    if business_id:
        q = q.filter(Sale.business_id == business_id)
    total_debt = float(q.filter(Sale.sale_date == selected_date).scalar() or 0)

    # Cash inflow — sales cash paid on selected date
    q = db.session.query(func.sum(Sale.cash_paid))
    if business_id:
        q = q.filter(Sale.business_id == business_id)
    total_cash_inflow_sales = q.filter(Sale.sale_date == selected_date).scalar() or Decimal("0.00")

    # Cash inflow — non-sale entries on selected date
    q = db.session.query(func.sum(CashInflow.amount)).filter(CashInflow.sale_id.is_(None))
    if business_id:
        q = q.filter(CashInflow.business_id == business_id)
    total_cash_inflow_other = q.filter(CashInflow.payment_date == selected_date).scalar() or Decimal("0.00")

    total_cash_inflow_today = float(total_cash_inflow_sales + total_cash_inflow_other)

    # Cash outflow on selected date
    q = db.session.query(func.sum(CashOutflow.amount))
    if business_id:
        q = q.filter(CashOutflow.business_id == business_id)
    total_cash_outflow_today = float(q.filter(CashOutflow.expense_date == selected_date).scalar() or 0)

    # --- 5. Recent sales for the selected date ---
    base_query = Sale.query.options(
        db.joinedload(Sale.client),
        db.joinedload(Sale.sale_items),
    ).filter(Sale.sale_date == selected_date).order_by(Sale.created_at.desc())
    if business_id:
        base_query = base_query.filter(Sale.business_id == business_id)
    recent_sales = base_query.limit(5).all()

    # --- 6. Archived daily reports (always yesterday, for the report summary widget) ---
    yesterday_local_date = today_local_date - timedelta(days=1)
    if business_id:
        daily_stock_reports = DailyStockReport.query.filter_by(
            report_date=yesterday_local_date, business_id=business_id).all()
        daily_overall_report = DailyOverallReport.query.filter_by(
            report_date=yesterday_local_date, business_id=business_id).first()
    else:
        daily_stock_reports = DailyStockReport.query.filter_by(report_date=yesterday_local_date).all()
        daily_overall_report = DailyOverallReport.query.filter_by(report_date=yesterday_local_date).first()

    return render_template(
        "main/index.html",
        segment="index",
        total_stocks_data=total_stocks_data,
        sales_data_week=sales_data_week,
        sales_by_network=sales_by_network,
        total_sales_today=total_sales_today,
        total_debt=total_debt,
        total_cash_inflow_today=total_cash_inflow_today,
        total_cash_outflow_today=total_cash_outflow_today,
        recent_sales=recent_sales,
        daily_stock_reports=daily_stock_reports,
        daily_overall_report=daily_overall_report,
        NetworkType=NetworkType,
        selected_date=selected_date_str,
        is_today=is_today,
    )


@bp.route("/<template>")
@login_required
def route_template(template):
    try:
        if not template.endswith(".html"):
            template += ".html"

        segment = get_segment(request)
        return render_template("main/" + template, segment=segment)

    except TemplateNotFound:
        abort(404)
    except Exception as e:
        current_app.logger.error(f"Unexpected error in route_template: {e}")
        abort(500)


# Helper - Extract current page name from request
def get_segment(request):

    try:

        segment = request.path.split("/")[-1]

        if segment == "":
            segment = "index"

        return segment

    except:
        return None


@bp.route("/admin/stocker", methods=["GET", "POST"])
@login_required
@vendeur_required
def stocker_management():
    """
    Renders the stockeur management page for a VENDEUR to manage their employees.

    Access: VENDEUR only (not stockeurs, not platform admin here)
    Shows: The vendeur + all their stockeurs
    Creates: New stockeurs linked to this vendeur
    """
    stocker_form = StockeurForm()
    user_edit_form = UserEditForm()
    business = get_current_business()

    # --- Handle POST: Create new stockeur ---
    if stocker_form.validate_on_submit():
        try:
            # Normalize phone number
            phone = normalize_phone(stocker_form.phone.data)

            # Check if phone already exists (phone is unique across all users)
            existing_by_phone = User.query.filter_by(phone=phone).first()
            if existing_by_phone:
                flash("Ce numéro de téléphone est déjà utilisé.", "danger")
                return redirect(url_for("main_bp.stocker_management"))

            # Check if username already exists
            existing_by_username = User.query.filter_by(
                username=stocker_form.username.data
            ).first()
            if existing_by_username:
                flash("Ce nom d'utilisateur est déjà utilisé.", "danger")
                return redirect(url_for("main_bp.stocker_management"))

            # Check email if provided
            if stocker_form.email.data:
                existing_by_email = User.query.filter_by(
                    email=stocker_form.email.data.lower()
                ).first()
                if existing_by_email:
                    flash("Cette adresse email est déjà utilisée.", "danger")
                    return redirect(url_for("main_bp.stocker_management"))

            # Create new STOCKEUR linked to current vendeur
            new_stockeur = User(
                username=stocker_form.username.data,
                phone=phone,
                email=stocker_form.email.data.lower() if stocker_form.email.data else None,
                role=RoleType.STOCKEUR,  # Always STOCKEUR - vendeurs can only create stockeurs
                # Link to current vendeur (the employer)
                vendeur_id=current_user.id,
                created_by=current_user.id,
                is_active=True,
            )
            new_stockeur.set_password(stocker_form.password.data)

            db.session.add(new_stockeur)
            add_stockeur(business=business, stockeur=new_stockeur)
            db.session.commit()

            flash(
                f"Stockeur '{new_stockeur.username}' créé avec succès!", "success")
            return redirect(url_for("main_bp.stocker_management"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating stockeur: {e}")
            flash("Une erreur est survenue lors de la création.", "danger")

    # --- Handle GET: Fetch users for display ---

    # Get the current vendeur's ID
    vendeur_id = current_user.id  # Since @vendeur_required, current_user IS the vendeur

    # Query: Get the vendeur (themselves) + all their stockeurs
    users = User.query.filter(
        db.or_(
            User.id == vendeur_id,  # The vendeur themselves
            User.vendeur_id == vendeur_id  # Their stockeurs
        )
    ).order_by(
        User.role.asc(),  # Vendeur first, then stockeurs
        User.created_at.desc()  # Newest first within each role
    ).all()

    return render_template(
        "main/user.html",
        users=users,
        stocker_form=stocker_form,
        user_edit_form=user_edit_form,
        segment="admin",
        sub_segment="stocker",
    )


@bp.route("/admin/user/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@vendeur_required
def user_edit(user_id):
    """
    Edit a stockeur's information.
    Vendeurs can only edit their own stockeurs.
    """
    user = db.session.get(User, user_id)

    if not user:
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for("main_bp.stocker_management"))

    # Security check: Can only edit own stockeurs (or self)
    if user.id != current_user.id and user.vendeur_id != current_user.id:
        flash("Vous n'êtes pas autorisé à modifier cet utilisateur.", "danger")
        return redirect(url_for("main_bp.stocker_management"))

    # Prevent vendeur from changing their own role
    if user.id == current_user.id:
        flash("Utilisez la page profil pour modifier vos informations.", "warning")
        return redirect(url_for("main_bp.profile"))

    user_edit_form = UserEditForm()
    stocker_form = StockeurForm()

    if user_edit_form.validate_on_submit():
        # Check username uniqueness (excluding current user)
        existing_by_username = User.query.filter(
            User.username == user_edit_form.username.data,
            User.id != user_id
        ).first()

        if existing_by_username:
            flash("Ce nom d'utilisateur est déjà utilisé.", "danger")
        else:
            # Check email uniqueness if provided
            if user_edit_form.email.data:
                existing_by_email = User.query.filter(
                    User.email == user_edit_form.email.data.lower(),
                    User.id != user_id
                ).first()
                if existing_by_email:
                    flash("Cette adresse email est déjà utilisée.", "danger")
                    return redirect(url_for("main_bp.stocker_management"))

            # Update user
            user.username = user_edit_form.username.data
            user.email = user_edit_form.email.data.lower() if user_edit_form.email.data else None
            user.is_active = user_edit_form.is_active.data
            # Note: Don't allow changing role - stockeurs stay stockeurs

            db.session.commit()
            flash("Utilisateur mis à jour avec succès!", "success")
            return redirect(url_for("main_bp.stocker_management"))

    elif request.method == "GET":
        # Pre-populate form
        user_edit_form.username.data = user.username
        user_edit_form.email.data = user.email
        user_edit_form.is_active.data = user.is_active

    # Re-fetch users for the page
    vendeur_id = current_user.id
    users = User.query.filter(
        db.or_(
            User.id == vendeur_id,
            User.vendeur_id == vendeur_id
        )
    ).order_by(User.role.asc(), User.created_at.desc()).all()

    return render_template(
        "main/user.html",
        users=users,
        stocker_form=stocker_form,
        user_edit_form=user_edit_form,
        editing_user=user,  # Pass the user being edited
        segment="admin",
        sub_segment="stocker",
    )


@bp.route("/admin/user/toggle_active/<int:user_id>", methods=["POST"])
@login_required
@vendeur_required
def user_toggle_active(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Utilisateur non trouvé.", "danger")
    else:
        # Ownership check: vendeur can only toggle their own stockeurs (or themselves)
        if user.id != current_user.id and user.vendeur_id != current_user.id:
            flash("Vous n'êtes pas autorisé à modifier cet utilisateur.", "danger")
            return redirect(url_for("main_bp.stocker_management"))
        # Prevent deactivating the superadmin who is currently logged in
        if user.id == current_user.id and user.role == RoleType.PLATFORM_ADMIN:
            flash("Impossible de désactiver votre compte", "warning")
        else:
            user.is_active = not user.is_active  # Toggle the status
            db.session.commit()
            if user.is_active:
                flash(
                    f"Utilisateur '{user.username}' activé avec succès!", "success")
            else:
                flash(
                    f"Utilisateur '{user.username}' désactivé avec succès!", "success"
                )
    return redirect(url_for("main_bp.stocker_management"))


# Client Management
def _client_phone_entries(form):
    entries = []
    for network, field_name in (
        (NetworkType.AIRTEL, "phone_airtel"),
        (NetworkType.AFRICEL, "phone_africel"),
        (NetworkType.ORANGE, "phone_orange"),
        (NetworkType.VODACOM, "phone_vodacom"),
    ):
        raw_value = getattr(form, field_name).data or ""
        for value in raw_value.replace(",", "\n").splitlines():
            if value.strip():
                entries.append((network, value.strip()))
    return entries


@bp.route("/admin/clients", methods=["GET", "POST"])
@login_required
@business_member_required
def client_management():
    client_form = ClientForm()
    client_edit_form = ClientEditForm()
    business = get_current_business()

    if client_form.validate_on_submit():
        gps_lat = request.form.get("gps_lat")
        gps_long = request.form.get("gps_long")

        try:
            gps_lat = float(gps_lat) if gps_lat else None
            gps_long = float(gps_long) if gps_long else None
        except ValueError:
            flash("Coordonnées GPS invalides.", "danger")
            gps_lat = None
            gps_long = None

        try:
            clean_name = ensure_unique_client_name(
                business_id=business.id, name=client_form.name.data
            )
            new_client = Client(
                name=clean_name,
                address=client_form.address.data,
                gps_lat=gps_lat,
                gps_long=gps_long,
                vendeur_id=current_user.business_vendeur_id,
                business_id=business.id,
            )
            db.session.add(new_client)
            db.session.flush()
            replace_client_phones(
                client=new_client, phone_entries=_client_phone_entries(client_form)
            )
            db.session.commit()
            flash("Client créé avec succès!", "success")
            return redirect(url_for("main_bp.client_management"))
        except ClientIdentityError as error:
            db.session.rollback()
            flash(str(error), "danger")

    # FIX: Use the helper instead of role check
    if business is not None:
        clients = Client.query.filter_by(business_id=business.id).all()
    else:
        clients = Client.query.all()  # Platform admin sees all

    return render_template(
        "main/clients.html",
        clients=clients,
        client_form=client_form,
        client_edit_form=client_edit_form,
        segment="admin",
        sub_segment="clients",
    )


@bp.route("/admin/clients/edit/<int:client_id>", methods=["POST"])
@login_required
@vendeur_required
def client_edit(client_id):
    """
    Handles editing of client information.
    """
    client = db.get_or_404(Client, client_id)

    ensure_access(client)

    client_edit_form = ClientEditForm()
    if client_edit_form.validate_on_submit():
        try:
            client.name = ensure_unique_client_name(
                business_id=client.business_id,
                name=client_edit_form.name.data,
                exclude_client_id=client.id,
            )
            client.address = client_edit_form.address.data
            client.gps_lat = client_edit_form.gps_lat.data
            client.gps_long = client_edit_form.gps_long.data
            client.is_active = client_edit_form.is_active.data
            client.identification_status = "identified"
            replace_client_phones(
                client=client, phone_entries=_client_phone_entries(client_edit_form)
            )
            db.session.commit()
            flash("Client mis à jour.", "success")
            return redirect(url_for("main_bp.client_management"))
        except ClientIdentityError as error:
            db.session.rollback()
            flash(str(error), "danger")
    else:
        flash(
            "Vérifiez les champs.",
            "danger",
        )
    return redirect(url_for("main_bp.client_management"))


@bp.route("/admin/clients/toggle-active/<int:client_id>", methods=["POST"])
@login_required
@vendeur_required
def client_toggle_active(client_id):
    """
    Toggles the active status of a client.
    """
    client = db.get_or_404(Client, client_id)

    ensure_access(client)

    if not client.is_active:
        try:
            ensure_unique_client_name(
                business_id=client.business_id,
                name=client.name,
                exclude_client_id=client.id,
            )
        except ClientIdentityError as error:
            flash(str(error), "danger")
            return redirect(url_for("main_bp.client_management"))
    client.is_active = not client.is_active
    db.session.commit()
    status_message = "activé" if client.is_active else "désactivé"
    flash(f"Client {client.name} {status_message} avec succès!", "success")
    return redirect(url_for("main_bp.client_management"))


@bp.route("/achat_stock", methods=["GET", "POST"])
@login_required
@vendeur_required
def achat_stock():
    form = StockPurchaseForm()
    active_business = get_current_business()

    # --- 1. HANDLE POST (Processing the Purchase) ---
    if form.validate_on_submit():
        try:
            # A. Extract Network
            network_type_string_from_form = form.network.data
            try:
                # Assuming NetworkType is your Enum
                network_enum = NetworkType(
                    network_type_string_from_form.lower())
            except ValueError:
                raise ValueError(
                    f"Le type de réseau '{network_type_string_from_form}' n'est pas valide.")

            # B. Extract Amounts
            amount_purchased = form.amount_purchased.data

            # C. Determine Buying Price
            buying_price_to_record = None
            if form.buying_price_choice.data == "custom":
                buying_price_to_record = form.custom_buying_price.data
            elif form.buying_price_choice.data:
                buying_price_to_record = Decimal(form.buying_price_choice.data)

            # D. Determine Selling Price
            selling_price_to_record = None
            if form.intended_selling_price_choice.data == "custom":
                selling_price_to_record = form.custom_intended_selling_price.data
            elif form.intended_selling_price_choice.data:
                selling_price_to_record = Decimal(
                    form.intended_selling_price_choice.data)

            # E. Validate Prices
            if buying_price_to_record is None or selling_price_to_record is None:
                raise ValueError(
                    "Veuillez sélectionner ou entrer un prix d'achat et un prix de vente.")

            record_retail_purchase(
                business=active_business,
                purchased_by=current_user,
                network=network_enum,
                quantity=amount_purchased,
                unit_cost=buying_price_to_record,
                intended_selling_price=selling_price_to_record,
            )
            db.session.commit()

            flash("Achat enregistré.", "success")
            # Redirect to Clear the POST request
            return redirect(url_for("main_bp.achat_stock"))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error recording stock purchase: {e}")
            flash("Une erreur est survenue.", "danger")

    elif form.errors:
        current_app.logger.debug("achat_stock form errors: %s", form.errors)
        flash("Vérifiez les champs.", "danger")

    # --- 2. HANDLE GET (Data Fetching & Pagination) ---

    # Use helper to get query and context
    base_purchases_query, ctx = get_stock_purchase_history_query(
        date_filter=True)
    selected_date_str = ctx.get('date_str')

    # Paginate results
    stock_purchases_pagination, _, _ = get_paginated_results(
        base_purchases_query,
        endpoint_name='main_bp.achat_stock',
        per_page_config_key='SALES_PER_PAGE',
        date=selected_date_str
    )

    return render_template(
        "main/achat_stock.html",
        form=form,
        segment="stock",
        sub_segment="achat_stock",
        stock_purchases=stock_purchases_pagination.items,
        stock_purchases_pagination=stock_purchases_pagination,
        selected_date=selected_date_str
    )


# Edit Stock Purchase
@bp.route("/achat_stock/editer/<int:purchase_id>", methods=["GET", "POST"])
@login_required
@vendeur_required
def edit_stock_purchase(purchase_id):
    purchase = db.get_or_404(StockPurchase, purchase_id)
    ensure_access(purchase.stock_item)
    active_business = get_current_business()
    form = StockPurchaseForm(obj=purchase)

    # --- Pre-fill form based on existing purchase data ---
    # Pre-fill Buying Price choice
    if purchase.buying_price_at_purchase == Decimal("26.79"):
        form.buying_price_choice.data = "26.79"
        form.custom_buying_price.data = None
    elif purchase.buying_price_at_purchase == Decimal(
        "27.075"
    ):  # Match your form choices
        form.buying_price_choice.data = "27.075"
        form.custom_buying_price.data = None
    else:
        form.buying_price_choice.data = "custom"
        form.custom_buying_price.data = purchase.buying_price_at_purchase

    # Pre-fill Selling Price choice
    if purchase.selling_price_at_purchase == Decimal("27.5"):
        form.intended_selling_price_choice.data = "27.5"
        form.custom_intended_selling_price.data = None
    elif purchase.selling_price_at_purchase == Decimal(
        "28.0"
    ):  # Match your form choices
        form.intended_selling_price_choice.data = "28.0"
        form.custom_intended_selling_price.data = None
    else:
        form.intended_selling_price_choice.data = "custom"
        form.custom_intended_selling_price.data = purchase.selling_price_at_purchase

    if form.validate_on_submit():
        try:
            network_type_string_from_form = form.network.data
            try:
                network_enum = NetworkType(
                    network_type_string_from_form.lower())
            except ValueError:
                flash(
                    f"Le type de réseau '{network_type_string_from_form}' n'est pas valide.",
                    "danger",
                )
                return render_template(
                    "main/edit_stock_purchase.html",
                    form=form,
                    purchase=purchase,
                    page_title="Editer Achat Stock",
                    segment="stock",
                    sub_segment="achat_stock",
                )
            amount_purchased = form.amount_purchased.data

            # Determine BUYING price from the form
            buying_price_to_record = None
            if form.buying_price_choice.data == "custom":
                buying_price_to_record = form.custom_buying_price.data
            elif form.buying_price_choice.data:
                buying_price_to_record = Decimal(form.buying_price_choice.data)

            # Determine SELLING price from the form
            selling_price_to_record = None
            if form.intended_selling_price_choice.data == "custom":
                selling_price_to_record = form.custom_intended_selling_price.data
            elif form.intended_selling_price_choice.data:
                selling_price_to_record = Decimal(
                    form.intended_selling_price_choice.data
                )

            # Re-validate prices (though form.validate_on_submit() should catch this)
            if buying_price_to_record is None or selling_price_to_record is None:
                flash(
                    "Veuillez sélectionner ou entrer un prix d'achat et un prix de vente valides.",
                    "danger",
                )
                return render_template(
                    "main/edit_stock_purchase.html",
                    form=form,
                    purchase=purchase,
                    page_title="Editer Achat Stock",
                    segment="stock",
                    sub_segment="achat_stock",
                )

            replace_retail_purchase(
                purchase=purchase,
                business=active_business,
                updated_by=current_user,
                network=network_enum,
                quantity=amount_purchased,
                unit_cost=buying_price_to_record,
                intended_selling_price=selling_price_to_record,
            )
            db.session.commit()
            flash("Achat mis à jour.", "success")
            return redirect(url_for("main_bp.achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error updating stock purchase {purchase_id}: {e}"
            )
            flash(
                f"Une erreur est survenue lors de la mise à jour: {e}", "danger")

    return render_template(
        "main/edit_stock_purchase.html",
        form=form,
        purchase=purchase,
        page_title="Editer Achat Stock",
        segment="stock",
        sub_segment="achat_stock",
    )


# Delete Stock Purchase
@bp.route("/achat_stock/supprimer/<int:purchase_id>", methods=["GET", "POST"])
@login_required
@vendeur_required
def delete_stock_purchase(purchase_id):
    purchase = db.get_or_404(StockPurchase, purchase_id)
    ensure_access(purchase.stock_item)

    if request.method == "POST":
        try:
            delete_retail_purchase(
                purchase=purchase,
                business=get_current_business(),
                deleted_by=current_user,
            )
            db.session.commit()
            flash("Achat supprimé.", "success")
            return redirect(url_for("main_bp.achat_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error deleting stock purchase {purchase_id}: {e}"
            )
            flash(
                f"Une erreur est survenue lors de la suppression: {e}", "danger")
            return redirect(url_for("main_bp.achat_stock"))

    flash("Confirmez la suppression.", "warning")
    return render_template(
        "main/confirm_delete_stock_purchase.html",
        purchase=purchase,
        page_title="Confirmer Suppression",
        segment="stock",
        sub_segment="achat_stock",
    )


@bp.route("/stock/ouverture", methods=["GET", "POST"])
@login_required
@business_member_required
def stock_ouverture():
    """
    Set the opening (initial) airtime balance per network for a given date.
    Saves to StockOpeningBalance so get_daily_report_data() uses it as anchor.
    Also provides a "copy from yesterday" helper endpoint.
    """
    vendeur_id = get_current_vendeur_id()
    business = get_current_business()
    business_id = business.id if business is not None else None
    form = StockOpeningBalanceForm()

    # Default to today
    if request.method == "GET":
        from datetime import date as _date
        form.balance_date.data = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()
        # Pre-fill with any existing entry for today
        if vendeur_id:
            existing = StockOpeningBalance.query.filter_by(
                business_id=business_id,
                balance_date=form.balance_date.data,
            ).all()
            existing_map = {ob.network.name.lower(): ob.quantity for ob in existing}
            for field_name in ('airtel', 'africel', 'orange', 'vodacom'):
                field = getattr(form, field_name)
                val = existing_map.get(field_name)
                if val is not None:
                    field.data = int(val)

    if form.validate_on_submit():
        if not vendeur_id:
            flash("Mode introuvable.", "danger")
            return redirect(url_for('main_bp.stock_ouverture'))

        balance_date = form.balance_date.data
        network_fields = {
            NetworkType.AIRTEL:   form.airtel.data,
            NetworkType.AFRICEL:  form.africel.data,
            NetworkType.ORANGE:   form.orange.data,
            NetworkType.VODACOM:  form.vodacom.data,
        }

        try:
            today_local = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()
            is_today = (balance_date == today_local)

            for network, qty in network_fields.items():
                if qty is None:
                    qty = 0
                opening_qty = Decimal(str(qty))

                # Upsert the StockOpeningBalance anchor
                entry = StockOpeningBalance.query.filter_by(
                    business_id=business_id,
                    network=network,
                    balance_date=balance_date,
                ).first()
                if entry:
                    entry.quantity = opening_qty
                    entry.set_by_id = current_user.id
                else:
                    entry = StockOpeningBalance(
                        vendeur_id=vendeur_id,
                        business_id=business_id,
                        network=network,
                        balance_date=balance_date,
                        quantity=opening_qty,
                        set_by_id=current_user.id,
                    )
                    db.session.add(entry)

                # For today: recalculate Stock.balance so sales/display stay correct.
                # new_balance = opening − already_sold_today + already_purchased_today
                if is_today:
                    sold_today = db.session.query(
                        func.coalesce(func.sum(SaleItem.quantity), 0)
                    ).join(Sale).filter(
                        Sale.sale_date == today_local,
                        Sale.business_id == business_id,
                        Sale.status == TransactionStatus.ACTIVE,
                        SaleItem.network == network,
                    ).scalar()

                    day_start_utc, day_end_utc = get_utc_range_for_date(today_local)
                    purchased_today = db.session.query(
                        func.coalesce(func.sum(StockPurchase.amount_purchased), 0)
                    ).join(Stock, StockPurchase.stock_item_id == Stock.id).filter(
                        Stock.business_id == business_id,
                        StockPurchase.network == network,
                        StockPurchase.status == TransactionStatus.ACTIVE,
                        StockPurchase.created_at >= day_start_utc,
                        StockPurchase.created_at <= day_end_utc,
                    ).scalar()

                    new_balance = opening_qty - Decimal(str(sold_today)) + Decimal(str(purchased_today))
                    stock_item = Stock.query.filter_by(
                        business_id=business_id, network=network
                    ).first()
                    if stock_item:
                        stock_item.balance = max(new_balance, Decimal("0.00"))
                    else:
                        stock_item = Stock(
                            vendeur_id=vendeur_id,
                            business_id=business_id,
                            network=network,
                            balance=max(new_balance, Decimal("0.00")),
                            buying_price_per_unit=Decimal("0.94"),
                            selling_price_per_unit=Decimal("1.00"),
                        )
                        db.session.add(stock_item)

            db.session.commit()
            flash(
                f"Stock initial du {balance_date.strftime('%d/%m/%Y')} enregistré avec succès.",
                "success",
            )
            return redirect(url_for('main_bp.stock_ouverture'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving opening balance: {e}")
            flash("Une erreur est survenue lors de l'enregistrement.", "danger")

    # Fetch yesterday's data to show as suggestion
    yesterday = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date() - timedelta(days=1)
    yesterday_map = {}
    if vendeur_id:
        prev_reports = DailyStockReport.query.filter_by(
            report_date=yesterday, business_id=business_id
        ).all()
        if prev_reports:
            yesterday_map = {r.network.name.lower(): int(r.final_stock_balance or 0)
                             for r in prev_reports}
        else:
            # Fall back to live Stock.balance if no archive
            live_stocks = Stock.query.filter_by(business_id=business_id).all()
            yesterday_map = {s.network.name.lower(): int(s.balance or 0)
                             for s in live_stocks}

    # Existing entries (all dates) for the history table
    history_q = (
        StockOpeningBalance.query.filter_by(business_id=business_id)
        if business_id is not None else StockOpeningBalance.query
    )
    history = history_q.order_by(
        StockOpeningBalance.balance_date.desc()
    ).limit(30).all()

    return render_template(
        "main/stock_ouverture.html",
        form=form,
        yesterday_map=yesterday_map,
        yesterday=yesterday,
        history=history,
        segment="stock",
        sub_segment="stock_ouverture",
        page_title="Stock Initial",
    )


@bp.route("/vente_stock", methods=["GET", "POST"])
@login_required
@business_member_required
def vente_stock():
    form = SaleForm()
    business = get_current_business()

    # --- 1. SETUP FORM DATA ---
    # Populate client choices dynamically
    # NEW
    if business is not None:
        clients = Client.query.filter_by(
            business_id=business.id, is_active=True).order_by(Client.name).all()
    else:
        clients = Client.query.filter_by(
            is_active=True).order_by(Client.name).all()

    client_choices = [("", "Sélectionnez un client existant")]
    client_choices.extend([(str(c.id), c.name) for c in clients])
    form.existing_client_id.choices = client_choices
    adhoc_sales = Sale.query.filter(
        Sale.business_id == business.id,
        Sale.client_id.is_(None),
        Sale.adhoc_customer_key.isnot(None),
        Sale.status == TransactionStatus.ACTIVE,
    ).order_by(Sale.created_at.desc()).all()
    adhoc_groups = {}
    for prior_sale in adhoc_sales:
        group = adhoc_groups.setdefault(prior_sale.adhoc_customer_key, {
            "name": prior_sale.client_display_name,
            "debt": Decimal("0.00"),
            "last_sale": prior_sale,
        })
        group["debt"] += prior_sale.debt_amount
    form.adhoc_customer_key.choices = [("", "Nouvelle personne")]
    form.adhoc_customer_key.choices.extend(
        (
            key,
            f"Même client : {data['name']} — dette {data['debt']:,.2f} FC",
        )
        for key, data in adhoc_groups.items()
        if data["debt"] > 0 or data["last_sale"].sale_date == date.today()
    )

    # Pre-fill empty rows for the FieldList on GET
    if request.method == "GET":
        if not form.sale_items:
            for _ in range(3):
                form.sale_items.append_entry()
        # Default sale_date to today in local timezone
        if not form.sale_date.data:
            form.sale_date.data = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()

    # --- 2. HANDLE POST (Processing the Sale) ---
    if form.validate_on_submit():
        try:
            # A. Resolve Client
            client = None
            client_name_adhoc = None
            adhoc_customer_key = None

            if form.client_choice.data == "existing":
                client_id = form.existing_client_id.data
                if not client_id:
                    raise ValueError(
                        "Sélectionnez un client.")
                client = Client.query.filter_by(
                    id=int(client_id),
                    business_id=business.id,
                ).first()
                if not client:
                    raise ValueError("Client invalide.")

            elif form.client_choice.data == "new":
                selected_key = (form.adhoc_customer_key.data or "").strip()
                if selected_key:
                    prior_identity = Sale.query.filter(
                        Sale.business_id == business.id,
                        Sale.client_id.is_(None),
                        Sale.adhoc_customer_key == selected_key,
                        Sale.status == TransactionStatus.ACTIVE,
                    ).order_by(Sale.created_at.desc()).first()
                    if not prior_identity:
                        raise ValueError("Client temporaire invalide.")
                    client_name_adhoc = prior_identity.client_display_name
                    adhoc_customer_key = selected_key
                else:
                    client_name_adhoc = (form.new_client_name.data or "").strip()
                    if not client_name_adhoc:
                        raise ValueError("Saisissez le nom du client.")
                    adhoc_customer_key = uuid4().hex

            # B. Process Sale Items
            raw_subtotals = []
            sale_items_to_add = []

            # Check if list is empty
            # (Note: Logic depends on how your form handles empty removals,
            # usually we filter out empty entries here)

            for index, item_data in enumerate(form.sale_items.entries):
                # Skip empty entries if your logic allows it, otherwise validate
                network_enum = item_data.form.network.data
                quantity = item_data.form.quantity.data

                # Basic validation skipping empty rows if needed
                if not network_enum or not quantity:
                    continue

                network_type = NetworkType[network_enum]
                price_override = item_data.form.price_per_unit_applied.data

                # Check Stock Availability
                vendeur_id = current_user.business_vendeur_id
                stock_item = Stock.query.filter_by(
                    business_id=business.id, network=network_type).first()

                if not stock_item:
                    raise ValueError(
                        f"Stock introuvable pour {network_type.value}.")

                if quantity > stock_item.balance:
                    raise ValueError(
                        f"Stock insuffisant pour {network_type.value}."
                    )

                # Determine Price
                final_unit_price = None
                if price_override is not None:
                    final_unit_price = price_override
                elif stock_item.selling_price_per_unit and stock_item.selling_price_per_unit > 0:
                    final_unit_price = stock_item.selling_price_per_unit
                else:
                    raise ValueError(
                        f"Prix introuvable pour {network_type.value}."
                    )

                # Calculate Line Totals
                subtotal_raw = quantity * final_unit_price
                subtotal = subtotal_raw.quantize(Decimal("0.01"))

                cost_per_unit, cost_total = consume_stock(
                    stock=stock_item, quantity=quantity
                )

                # Prepare Object
                new_item = SaleItem(
                    network=network_type,
                    quantity=quantity,
                    price_per_unit_applied=final_unit_price,
                    subtotal=subtotal,
                    cost_per_unit_snapshot=cost_per_unit,
                    cost_total=cost_total,
                    margin_amount=subtotal - cost_total,
                    is_cost_estimated=False,
                )
                db.session.add(stock_item)

                sale_items_to_add.append(new_item)
                raw_subtotals.append(subtotal)

            if not sale_items_to_add:
                raise ValueError(
                    "Ajoutez au moins un article.")

            # C. Finalize Financials
            total_amount_due = calculate_sale_total(raw_subtotals)
            cash_received = form.cash_paid.data or Decimal("0.00")

            # D. Save Sale
            new_sale = Sale(
                seller_id=current_user.id,
                vendeur_id=current_user.business_vendeur_id,
                business_id=business.id,
                client=client,
                client_name_adhoc=client_name_adhoc,
                adhoc_customer_key=adhoc_customer_key,
                total_amount_due=total_amount_due,
                cash_paid=Decimal("0.00"),
                debt_amount=total_amount_due,
                sale_date=form.sale_date.data,
            )
            new_sale.sale_items.extend(sale_items_to_add)

            db.session.add(new_sale)
            db.session.flush()
            apply_payment_to_sale(
                sale=new_sale,
                amount=cash_received,
                recorded_by=current_user,
                payment_date=form.sale_date.data,
            )
            db.session.commit()

            flash("Vente enregistrée.", "success")
            return redirect(url_for("main_bp.vente_stock"))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Sale Error: {e}")
            flash("Une erreur est survenue.", "danger")

    # Handle Form Validation Errors (if submit failed but no exception raised)
    elif form.errors:
        flash("Vérifiez les champs.", "danger")
        # Optional: Detailed error logging to flash can be done here if desired

    # --- 3. HANDLE GET (Data Fetching & Pagination) ---

    # A. Get Date Context using your Utility
    # This automatically checks request.args for 'date' and defaults to Today
    base_sales_query, ctx = get_sales_history_query(date_filter=True)
    selected_date_str = ctx.get('date_str')

    # B. Paginate using your Utility
    sales_pagination, _, _ = get_paginated_results(
        base_sales_query,
        endpoint_name='main_bp.vente_stock',
        per_page_config_key='SALES_PER_PAGE',
        date=selected_date_str
    )

    return render_template(
        "main/vente_stock.html",
        form=form,
        segment="stock",
        sub_segment="vente_stock",
        # Pass the pagination object for the macro
        sales_pagination=sales_pagination,
        # Pass the date string for the Date Filter macro
        selected_date=selected_date_str
    )


@bp.route("/update-sale-cash/<int:sale_id>", methods=["POST"])
@login_required
@business_member_required
def update_sale_cash(sale_id):
    sale = db.get_or_404(Sale, sale_id)
    ensure_access(sale)
    try:
        # new_cash is directly from the input named 'new_cash'
        new_cash = Decimal(request.form.get("new_cash", "0.00"))
    except InvalidOperation:
        flash("Paiement invalide.", "danger")
        return redirect(url_for("main_bp.vente_stock"))

    if new_cash < 0:
        flash("Le paiement doit être positif.", "danger")
        return redirect(url_for("main_bp.vente_stock"))

    if new_cash < sale.cash_paid:
        flash("Annulez ce paiement avant de le réduire.", "danger")
        return redirect(url_for("main_bp.vente_stock"))

    try:
        additional_cash = new_cash - sale.cash_paid
        if additional_cash > 0:
            apply_additional_payment_to_sale(
                sale=sale,
                amount=additional_cash,
                recorded_by=current_user,
                payment_date=datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date(),
            )
        db.session.commit()
        flash("Paiement mis à jour.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating sale cash {sale_id}: {e}")
        flash("Une erreur est survenue.", "danger")

    return redirect(url_for("main_bp.vente_stock"))


@bp.route("/edit_sale/<int:sale_id>", methods=["GET", "POST"])
@login_required
@business_member_required
def edit_sale(sale_id):
    sale = db.get_or_404(Sale, sale_id)
    ensure_access(sale)
    flash(
        "Annulez la vente, puis saisissez la correction.",
        "warning",
    )
    return redirect(url_for("main_bp.delete_sale", sale_id=sale.id))


@bp.route("/delete_sale/<int:sale_id>", methods=["GET", "POST"])
@login_required
@business_member_required
def delete_sale(sale_id):
    sale = db.get_or_404(Sale, sale_id)
    ensure_access(sale)
    business = get_current_business()
    confirm_form = TransactionReversalForm()

    if request.method == "POST":

        try:
            if not confirm_form.validate_on_submit():
                raise ValueError("Ajoutez une raison.")
            reverse_unpaid_sale(
                sale=sale,
                business=business,
                reversed_by=current_user,
                reason=confirm_form.reason.data,
            )
            db.session.commit()
            flash(
                "Vente annulée. Saisissez la correction si besoin.",
                "success",
            )
            return redirect(url_for("main_bp.vente_stock"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error deleting sale {sale_id}: {e}", exc_info=True
            )
            flash("Une erreur est survenue.", "danger")
            return redirect(url_for("main_bp.vente_stock"))

    flash("Confirmez l'annulation.", "warning")
    return render_template(
        "main/confirm_delete_sale.html",
        sale=sale,
        confirm_form=confirm_form,
        page_title="Confirmer Suppression Vente",
        segment="stock",
        sub_segment="vente_stock",
    )


@bp.route("/view_sale_details/<int:sale_id>", methods=["GET"])
@login_required
@business_member_required
def view_sale_details(sale_id):
    sale = db.get_or_404(Sale, sale_id)
    ensure_access(sale)
    payment_events = (
        PaymentEvent.query.outerjoin(CashInflow)
        .filter(
            db.or_(
                PaymentEvent.source_sale_id == sale.id,
                CashInflow.sale_id == sale.id,
            )
        )
        .distinct()
        .order_by(PaymentEvent.payment_date.desc(), PaymentEvent.created_at.desc())
        .all()
    )
    legacy_allocations = (
        CashInflow.query.filter(
            CashInflow.sale_id == sale.id,
            CashInflow.business_id == sale.business_id,
            CashInflow.payment_event_id.is_(None),
            CashInflow.status == TransactionStatus.ACTIVE,
        )
        .order_by(CashInflow.payment_date.desc(), CashInflow.created_at.desc())
        .all()
    )
    return render_template(
        "main/sale_details.html",
        sale=sale,
        payment_events=payment_events,
        legacy_allocations=legacy_allocations,
        reversal_form=TransactionReversalForm(),
        segment="stock",
        sub_segment="vente_stock",
    )


@bp.route("/payments/<int:payment_event_id>/reverse", methods=["POST"])
@login_required
@vendeur_required
def reverse_retail_payment_route(payment_event_id):
    business = get_current_business()
    if business is None or business.business_type != BusinessType.RETAIL:
        return redirect(url_for("main_bp.businesses"))
    payment_event = db.get_or_404(PaymentEvent, payment_event_id)
    form = TransactionReversalForm()
    redirect_sale_id = payment_event.source_sale_id
    if redirect_sale_id is None and payment_event.allocations:
        redirect_sale_id = payment_event.allocations[0].sale_id
    try:
        if not form.validate_on_submit():
            raise ValueError("Ajoutez une raison.")
        reverse_payment_event(
            payment_event=payment_event,
            business=business,
            reversed_by=current_user,
            reason=form.reason.data,
        )
        db.session.commit()
        flash("Paiement annulé et dettes restaurées.", "success")
    except (ValueError, PermissionError, RuntimeError) as error:
        db.session.rollback()
        flash(str(error), "danger")
    if redirect_sale_id is not None:
        return redirect(
            url_for("main_bp.view_sale_details", sale_id=redirect_sale_id)
        )
    return redirect(url_for("main_bp.vente_stock"))

# ============================================================
# UPDATED: sorties_cash route with DATE FILTERING
# ============================================================


@bp.route("/sorties_cash", methods=["GET"])
@login_required
@business_member_required
def sorties_cash():
    """
    Display cash movements (inflows and outflows) for the business.
    Supports date filtering via URL parameter: ?date=YYYY-MM-DD
    """

    # --- 1. Get Date Context (handles URL param and UTC conversion) ---
    ctx = get_date_context()
    selected_date_str = ctx['date_str']

    # --- 2. Get Vendeur Context ---
    vendeur_id = get_current_vendeur_id()
    business = get_current_business()
    business_id = business.id if business is not None else None

    # --- 3. Build Queries with Date + Vendeur Filtering ---

    # Base queries
    outflow_query = CashOutflow.query.filter(
        CashOutflow.expense_date == ctx['selected_date']
    )

    inflow_query = CashInflow.query.filter(
        CashInflow.payment_date == ctx['selected_date'],
        CashInflow.status == TransactionStatus.ACTIVE,
    )

    sales_cash_query = db.session.query(db.func.sum(Sale.cash_paid)).filter(
        Sale.sale_date == ctx['selected_date']
    )

    # Apply vendeur filter if not platform admin
    if business_id is not None:
        outflow_query = outflow_query.filter(CashOutflow.business_id == business_id)
        inflow_query = inflow_query.filter(CashInflow.business_id == business_id)
        sales_cash_query = sales_cash_query.filter(Sale.business_id == business_id)
    elif vendeur_id:
        outflow_query = outflow_query.filter(
            CashOutflow.vendeur_id == vendeur_id)
        inflow_query = inflow_query.filter(CashInflow.vendeur_id == vendeur_id)
        sales_cash_query = sales_cash_query.filter(
            Sale.vendeur_id == vendeur_id)

    # Execute queries
    all_outflows = outflow_query.order_by(CashOutflow.expense_date.desc(), CashOutflow.created_at.desc()).all()
    all_inflows = inflow_query.order_by(CashInflow.payment_date.desc(), CashInflow.created_at.desc()).all()
    all_sales_cash_paid_sum = sales_cash_query.scalar()

    # --- 4. Calculate Totals ---
    total_outflow = (
        sum(outflow.amount for outflow in all_outflows)
        if all_outflows
        else Decimal("0.00")
    )

    total_cash_inflows_records = (
        sum(inflow.amount for inflow in all_inflows)
        if all_inflows
        else Decimal("0.00")
    )

    total_sales_cash_paid = (
        all_sales_cash_paid_sum if all_sales_cash_paid_sum else Decimal("0.00")
    )

    # IMPORTANT: CashInflow records for SALE_COLLECTION are already reflected in
    # Sale.cash_paid (encaisser_dette updates both). Adding them here would double-count.
    # Only add CashInflow records NOT linked to a sale (e.g. "Autre Entrée").
    total_unsale_inflows = sum(
        inflow.amount for inflow in all_inflows if inflow.sale_id is None
    )
    total_inflow = total_sales_cash_paid + total_unsale_inflows

    # --- 5. Render Template with selected_date for the filter ---
    return render_template(
        "main/sorties_cash.html",
        outflows=all_outflows,
        inflows=all_inflows,
        total_outflow=total_outflow,
        total_inflow=total_inflow,
        total_sales_cash_paid=total_sales_cash_paid,  # Bonus: separate display if needed
        total_cash_inflows_records=total_cash_inflows_records,  # Bonus: separate display
        selected_date=selected_date_str,  # ← This is what the filter needs!
        segment="stock",
        sub_segment="Sorties_Cash",
    )

# Enregistre une Sortie (Cash Outflow)


@bp.route("/enregistrer_sortie", methods=["GET", "POST"])
@login_required
@business_member_required
def enregistrer_sortie():
    form = CashOutflowForm(request.form)
    page_title = "Gestion Cash"
    sub_page_title = "Enregistrer Sortie"
    business = get_current_business()

    # Default expense_date to today in local timezone on GET
    if request.method == "GET" and not form.expense_date.data:
        form.expense_date.data = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()

    if "submit" in request.form:
        if form.validate_on_submit():
            try:
                new_outflow = CashOutflow(
                    amount=form.amount.data,
                    category=form.category.data,
                    description=form.description.data,
                    recorded_by=current_user,
                    vendeur_id=current_user.business_vendeur_id,
                    business_id=business.id,
                    expense_date=form.expense_date.data,
                )
                db.session.add(new_outflow)
                db.session.commit()

                flash("Sortie de caisse enregistrée avec succès!", "success")
                return redirect(url_for("main_bp.sorties_cash"))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error saving cash outflow: {e}")
                flash(
                    "Une erreur est survenue.", "danger"
                )

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(
                        f"Erreur dans le champ '{form[field].label.text}': {error}",
                        "danger",
                    )

    return render_template(
        "main/enregistrer_sortie.html",
        form=form,
        page_title=page_title,
        sub_page_title=sub_page_title,
        segment="enregistrer_sortie",
    )


# Encaisser une Dette (Debt Collection)
@bp.route("/sorties_cash/encaisser_dette", methods=["GET", "POST"])
@login_required
@business_member_required
def encaisser_dette():
    ctx = get_date_context()
    filter_date = ctx['selected_date']
    filter_date_str = ctx['date_str']
    _vendeur_id = get_current_vendeur_id()
    business = get_current_business()

    form = DebtCollectionForm()
    # Always show the complete client balance: old debt must not disappear just
    # because it originated on another business date.
    form.client_key.choices = get_clients_with_debt(
        vendeur_id=_vendeur_id,
        business_id=business.id,
        sale_date=None,
    )

    if request.method == "GET" and not form.payment_date.data:
        form.payment_date.data = datetime.now(pytz.utc).astimezone(APP_TIMEZONE).date()

    if form.validate_on_submit():
        try:
            client_key = form.client_key.data
            amount_paid = form.amount_paid.data
            description = form.description.data
            payment_date = form.payment_date.data

            if amount_paid <= Decimal("0.00"):
                raise ValueError("Le montant payé doit être positif.")

            # A key represents an explicit identity, never merely a display name.
            unpaid_q = Sale.query.filter(
                Sale.debt_amount > 0,
                Sale.business_id == business.id,
                Sale.status == TransactionStatus.ACTIVE,
            )

            if client_key.startswith("c:"):
                unpaid_q = unpaid_q.filter(Sale.client_id == int(client_key[2:]))
            elif client_key.startswith("a:"):
                adhoc_key = client_key[2:]
                unpaid_q = unpaid_q.filter(
                    Sale.client_id.is_(None),
                    Sale.adhoc_customer_key == adhoc_key,
                )
            else:
                raise ValueError("Clé client invalide.")

            unpaid_sales = unpaid_q.order_by(Sale.sale_date.asc(), Sale.created_at.asc()).all()
            if not unpaid_sales:
                raise ValueError("Aucune dette trouvée pour ce client.")

            total_debt = sum(s.debt_amount for s in unpaid_sales)
            if amount_paid > total_debt:
                flash(
                    f"Le montant payé ({amount_paid:,.2f} FC) dépasse la dette totale "
                    f"({total_debt:,.2f} FC). Ajustement automatique.",
                    "warning",
                )
                amount_paid = total_debt

            if unpaid_sales[0].client is not None:
                remaining_for_count = amount_paid
                paid_count = 0
                for sale in unpaid_sales:
                    if remaining_for_count <= 0:
                        break
                    remaining_for_count -= min(remaining_for_count, sale.debt_amount)
                    paid_count += 1
                collect_client_debt(
                    business=business,
                    client=unpaid_sales[0].client,
                    amount=amount_paid,
                    recorded_by=current_user,
                    payment_date=payment_date,
                    description=description,
                )
            else:
                sale = unpaid_sales[0]
                payment_event = PaymentEvent(
                    business_id=business.id,
                    client_id=None,
                    source_sale_id=sale.id,
                    recorded_by_id=current_user.id,
                    amount=amount_paid,
                    payment_date=payment_date,
                    description=description,
                )
                db.session.add(payment_event)
                remaining = amount_paid
                paid_count = 0
                for debt_sale in unpaid_sales:
                    if remaining <= 0:
                        break
                    allocation = min(remaining, debt_sale.debt_amount)
                    debt_sale.cash_paid += allocation
                    debt_sale.debt_amount -= allocation
                    debt_sale.updated_at = datetime.now(timezone.utc)
                    db.session.add(CashInflow(
                        amount=allocation,
                        category=CashInflowCategory.SALE_COLLECTION,
                        allocation_kind=PaymentAllocationKind.PRIOR_DEBT,
                        description=description,
                        recorded_by=current_user,
                        vendeur_id=current_user.business_vendeur_id,
                        business_id=business.id,
                        payment_event=payment_event,
                        sale=debt_sale,
                        payment_date=payment_date,
                    ))
                    remaining -= allocation
                    paid_count += 1

            db.session.commit()
            client_name = unpaid_sales[0].client_display_name
            flash(
                f"Paiement de {amount_paid:,.2f} FC pour {client_name} enregistré. "
                f"{paid_count} vente(s) soldée(s).",
                "success",
            )
            return redirect(url_for("main_bp.sorties_cash"))

        except InvalidOperation:
            flash("Montant invalide.", "danger")
            db.session.rollback()
        except ValueError as e:
            flash(str(e), "danger")
            db.session.rollback()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error recording debt collection: {e}")
            flash("Une erreur est survenue.", "danger")

    # Count unique clients with any outstanding debt (for the "Voir toutes" link)
    all_debt_choices = get_clients_with_debt(vendeur_id=_vendeur_id, sale_date=None)
    total_debt_count = len(all_debt_choices)

    return render_template(
        "main/encaisser_dette.html",
        form=form,
        segment="stock",
        sub_segment="Sorties_Cash",
        sub_page_title="Encaisser Dette",
        selected_date=filter_date_str,
        is_today=ctx['is_today'],
        total_debt_count=total_debt_count,
        debt_count_today=len(form.client_key.choices),
    )


@bp.route("/rapports", methods=["GET"])
@login_required
@vendeur_required
def rapports():
    page_title = "Rapport Journalier"

    ctx = get_date_context()
    target_date = ctx['selected_date']
    vendeur_id = get_current_vendeur_id()
    business = get_current_business()
    business_id = business.id if business is not None else None

    current_app.logger.debug(f"Report requested for: {target_date}")

    networks = list(NetworkType.__members__.values())
    def zero_money(): return Decimal("0.00")

    # ── Stock balance table (initial / purchased / sold qty / final / virtual value) ──
    report_data = {
        network.name: {
            "initial_stock": zero_money(), "purchased_stock": zero_money(),
            "sold_stock": zero_money(), "final_stock": zero_money(),
            "virtual_value": zero_money(), "network": network,
        } for network in networks
    }
    grand_totals = {
        "initial_stock": zero_money(), "purchased_stock": zero_money(),
        "sold_stock": zero_money(), "final_stock": zero_money(),
        "virtual_value": zero_money(), "total_debts": zero_money(),
        "total_calculated_sold_stock": zero_money(),
    }

    if ctx['is_today']:
        calculated_data, _, total_live_debts = get_daily_report_data(
            current_app, target_date,
            start_of_utc_range=ctx['start_utc'],
            end_of_utc_range=ctx['end_utc'],
            vendeur_id=vendeur_id,
            business_id=business_id,
        )
        for network_name, data in calculated_data.items():
            report_data[network_name].update({
                "initial_stock": data["initial_stock"],
                "purchased_stock": data["purchased_stock"],
                "sold_stock": data["sold_stock_quantity"],
                "final_stock": data["final_stock"],
                "virtual_value": data["virtual_value"],
            })
            grand_totals["initial_stock"] += data["initial_stock"]
            grand_totals["purchased_stock"] += data["purchased_stock"]
            grand_totals["sold_stock"] += data["sold_stock_quantity"]
            grand_totals["final_stock"] += data["final_stock"]
            grand_totals["virtual_value"] += data["virtual_value"]
        grand_totals["total_debts"] = total_live_debts or zero_money()
    else:
        overall_report_q = DailyOverallReport.query.filter_by(report_date=target_date)
        if business_id is not None:
            overall_report_q = overall_report_q.filter_by(business_id=business_id)
        elif vendeur_id:
            overall_report_q = overall_report_q.filter_by(vendeur_id=vendeur_id)
        overall_report = overall_report_q.first()
        if overall_report:
            grand_totals.update({
                "initial_stock": overall_report.total_initial_stock,
                "purchased_stock": overall_report.total_purchased_stock,
                "sold_stock": overall_report.total_sold_stock,
                "final_stock": overall_report.total_final_stock,
                "virtual_value": overall_report.total_virtual_value,
                "total_debts": overall_report.total_debts,
            })
            net_reports_q = DailyStockReport.query.filter_by(report_date=target_date)
            if business_id is not None:
                net_reports_q = net_reports_q.filter_by(business_id=business_id)
            elif vendeur_id:
                net_reports_q = net_reports_q.filter_by(vendeur_id=vendeur_id)
            for r in net_reports_q.all():
                if r.network.name in report_data:
                    report_data[r.network.name].update({
                        "initial_stock": r.initial_stock_balance,
                        "purchased_stock": r.purchased_stock_amount,
                        "sold_stock": r.sold_stock_amount,
                        "final_stock": r.final_stock_balance,
                        "virtual_value": r.virtual_value,
                    })
        else:
            flash(f"Aucun rapport archivé pour le {ctx['date_str']}.", "warning")

    grand_totals["total_calculated_sold_stock"] = (
        grand_totals["initial_stock"]
        + grand_totals["purchased_stock"]
        - grand_totals["final_stock"]
    )

    # ── Live financial queries (always from transactions, keyed on sale_date) ──

    # Buying prices per network for cost/profit calculation
    stock_query = Stock.query
    if business_id is not None:
        stock_query = stock_query.filter_by(business_id=business_id)
    elif vendeur_id:
        stock_query = stock_query.filter_by(vendeur_id=vendeur_id)
    stock_items = stock_query.all()
    buying_price_map = {s.network: s.buying_price_per_unit for s in stock_items}

    # Price breakdown: per network × selling price → qty + revenue
    pb_q = (
        db.session.query(
            SaleItem.network,
            SaleItem.price_per_unit_applied,
            func.sum(SaleItem.quantity).label('qty'),
            func.sum(SaleItem.subtotal).label('revenue'),
            func.sum(SaleItem.cost_total).label('cost'),
            func.sum(SaleItem.margin_amount).label('margin'),
        )
        .join(Sale)
        .filter(
            Sale.sale_date == target_date,
            Sale.status == TransactionStatus.ACTIVE,
        )
    )
    if business_id is not None:
        pb_q = pb_q.filter(Sale.business_id == business_id)
    elif vendeur_id:
        pb_q = pb_q.filter(Sale.vendeur_id == vendeur_id)
    price_breakdown_rows = pb_q.group_by(
        SaleItem.network, SaleItem.price_per_unit_applied
    ).order_by(SaleItem.network, SaleItem.price_per_unit_applied).all()

    # Build price_breakdown dict: {network_name: [{price, qty, revenue}, ...]}
    price_breakdown = {}
    for row in price_breakdown_rows:
        key = row.network.name
        if key not in price_breakdown:
            price_breakdown[key] = []
        price_breakdown[key].append({
            "price": Decimal(str(row.price_per_unit_applied)),
            "qty": int(row.qty or 0),
            "revenue": Decimal(str(row.revenue or 0)),
            "cost": Decimal(str(row.cost or 0)),
            "margin": Decimal(str(row.margin or 0)),
        })

    # Profit per network
    profit_data = {}
    grand_profit = zero_money()
    grand_revenue = zero_money()
    grand_cost = zero_money()
    for network in networks:
        entries = price_breakdown.get(network.name, [])
        total_qty = sum(e["qty"] for e in entries)
        total_revenue = sum(e["revenue"] for e in entries)
        total_cost = sum(e["cost"] for e in entries)
        profit = sum(e["margin"] for e in entries)
        buying_price = (
            total_cost / Decimal(str(total_qty))
            if total_qty else buying_price_map.get(network, Decimal("0.94"))
        )
        profit_data[network.name] = {
            "network": network,
            "qty": total_qty,
            "revenue": total_revenue,
            "cost": total_cost,
            "profit": profit,
            "buying_price": buying_price,
        }
        grand_revenue += total_revenue
        grand_cost += total_cost
        grand_profit += profit

    # Cash & credit summary for the day
    cash_q = db.session.query(
        func.sum(Sale.cash_paid).label('cash'),
        func.sum(Sale.debt_amount).label('credit'),
        func.sum(Sale.total_amount_due).label('total'),
        func.count(Sale.id).label('count'),
    ).filter(
        Sale.sale_date == target_date,
        Sale.status == TransactionStatus.ACTIVE,
    )
    if business_id is not None:
        cash_q = cash_q.filter(Sale.business_id == business_id)
    elif vendeur_id:
        cash_q = cash_q.filter(Sale.vendeur_id == vendeur_id)
    cash_row = cash_q.first()
    cash_summary = {
        "cash": Decimal(str(cash_row.cash or 0)),
        "credit": Decimal(str(cash_row.credit or 0)),
        "total": Decimal(str(cash_row.total or 0)),
        "count": int(cash_row.count or 0),
    }

    # Debt detail list for the day — grouped by client so each client appears once
    debts_q = Sale.query.filter(
        Sale.sale_date == target_date,
        Sale.debt_amount > 0,
        Sale.status == TransactionStatus.ACTIVE,
    )
    if business_id is not None:
        debts_q = debts_q.filter(Sale.business_id == business_id)
    elif vendeur_id:
        debts_q = debts_q.filter(Sale.vendeur_id == vendeur_id)

    debt_map: dict = {}
    for sale in debts_q.order_by(Sale.created_at.asc()).all():
        key = sale.customer_group_key
        if key not in debt_map:
            debt_map[key] = {
                "name": sale.client_display_name,
                "total_amount_due": Decimal("0.00"),
                "cash_paid": Decimal("0.00"),
                "debt_amount": Decimal("0.00"),
                "sale_count": 0,
                "last_time": sale.created_at,
            }
        entry = debt_map[key]
        entry["total_amount_due"] += sale.total_amount_due
        entry["cash_paid"] += sale.cash_paid
        entry["debt_amount"] += sale.debt_amount
        entry["sale_count"] += 1
        if sale.created_at > entry["last_time"]:
            entry["last_time"] = sale.created_at

    debts_today = sorted(debt_map.values(), key=lambda x: x["debt_amount"], reverse=True)

    # All stock purchases for the date
    purchase_query, _ = get_stock_purchase_history_query(date_filter=True)
    all_purchases = purchase_query.all()

    # Sales history (max 10), with optional client name search
    client_search = request.args.get('client_search', '').strip()
    sales_q, _ = get_sales_history_query(date_filter=True)
    if client_search:
        sales_q = sales_q.filter(
            db.or_(
                Sale.client_name_adhoc.ilike(f'%{client_search}%'),
                Sale.client.has(Client.name.ilike(f'%{client_search}%')),
            )
        )
    sales_today = sales_q.limit(10).all()

    return render_template(
        "main/rapports.html",
        page_title=page_title,
        networks=networks,
        report_data=report_data,
        grand_totals=grand_totals,
        selected_date=ctx['date_str'],
        is_today=ctx['is_today'],
        # Financial data
        price_breakdown=price_breakdown,
        profit_data=profit_data,
        grand_profit=grand_profit,
        grand_revenue=grand_revenue,
        grand_cost=grand_cost,
        cash_summary=cash_summary,
        debts_today=debts_today,
        # Lists
        all_purchases=all_purchases,
        sales_today=sales_today,
        client_search=client_search,
        segment="rapports",
    )


@bp.route("/rapports/archive", methods=["POST"])
@login_required
@vendeur_required
def archive_daily_report():
    # 1. Get the date from the hidden input
    date_str = request.form.get('date_to_archive')

    if not date_str:
        flash("Date manquante.", "danger")
        return redirect(url_for('main_bp.rapports'))

    try:
        # Convert string 'YYYY-MM-DD' to a date object
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # 2. Get the vendeur_id for multi-tenant filtering
        vendeur_id = get_current_vendeur_id()
        business = get_current_business()
        business_id = business.id if business is not None else None

        if not vendeur_id:
            flash("Mode introuvable.", "danger")
            return redirect(url_for('main_bp.rapports', date=date_str))

        # 3. Call helper function WITH vendeur_id
        update_daily_reports(
            current_app._get_current_object(),
            report_date_to_update=report_date,
            vendeur_id=vendeur_id,
            business_id=business_id,
        )

        flash(f"Rapport du {date_str} archivé.", "success")

    except Exception as e:
        current_app.logger.error(
            f"Erreur d'archivage: {str(e)}", exc_info=True)
        flash("Une erreur est survenue.", "danger")

    return redirect(url_for('main_bp.rapports', date=date_str))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = EditProfileForm(
        original_username=current_user.username, original_email=current_user.email
    )

    if form.validate_on_submit():
        # Handle form submission for username, email, phone
        if current_user.username != form.username.data:
            if current_user.is_vendeur:
                rename_vendor(vendor=current_user, name=form.username.data)
            else:
                current_user.username = form.username.data
        if current_user.email != form.email.data:
            current_user.email = form.email.data
        if current_user.phone != form.phone.data:
            current_user.set_phone(form.phone.data)

        # Handle password change (your existing logic with translated flashes)
        if form.current_password.data or form.new_password.data:
            if not form.current_password.data:
                flash(
                    "Entrez votre mot de passe actuel.",
                    "danger",
                )
                return redirect(url_for("main_bp.profile"))
            if not current_user.check_password(form.current_password.data):
                flash("Mot de passe actuel incorrect.", "danger")
                return redirect(url_for("main_bp.profile"))
            if not form.new_password.data:
                flash("Entrez un nouveau mot de passe.", "danger")
                return redirect(url_for("main_bp.profile"))
            if form.new_password.data != form.confirm_new_password.data:
                flash("Les mots de passe ne correspondent pas.", "danger")
                return redirect(url_for("main_bp.profile"))

            current_user.set_password(form.new_password.data)
            flash("Mot de passe mis à jour.", "success")

        try:
            db.session.commit()
            flash("Profil mis à jour.", "success")
            return redirect(url_for("main_bp.profile"))
        except Exception as e:
            db.session.rollback()
            flash("Une erreur est survenue.", "danger")

    elif request.method == "GET":
        # Pre-populate form fields when page is loaded (GET request)
        form.username.data = current_user.username
        form.email.data = current_user.email
        form.phone.data = current_user.phone
        if hasattr(current_user, "about_me"):  # Pre-populate about_me if it exists
            form.about_me.data = current_user.about_me
        if hasattr(form, "role") and current_user.role:
            form.role.data = (
                current_user.role.name
            )  # Pre-select the current role using its name (e.g., 'SUPERADMIN')
        if hasattr(form, "is_active"):
            form.is_active.data = current_user.is_active

    # Fetch additional data for the profile page
    num_clients_created = (
        len(current_user.clients)
        if hasattr(current_user, "clients") and current_user.clients is not None
        else 0
    )
    num_sales_made = (
        len(current_user.sales)
        if hasattr(current_user, "sales") and current_user.sales is not None
        else 0
    )
    num_stock_purchases = (
        current_user.stock_purchases_made.count()
        if hasattr(current_user, "stock_purchases_made")
        else 0
    )

    # Generate API token if the user doesn't have one yet (lazy creation)
    api_token = current_user.get_or_create_api_token()

    return render_template(
        "main/profile.html",
        segment="profile",
        form=form,
        num_clients_created=num_clients_created,
        num_sales_made=num_sales_made,
        num_stock_purchases=num_stock_purchases,
        api_token=api_token,
    )


# Client Map route
@bp.route("/client-map", methods=["GET"])
@login_required
@business_member_required
def client_map():
    """
    Renders a map displaying clients based on their GPS coordinates.
    Clients are color-coded based on their total purchases (high-value = green, medium = orange, low = blue).
    """

    # Enhanced client data with purchase history
    # In production, this would come from your database
    hardcoded_client_locations = [
        {
            "id": 1,
            "name": "Boutique Mama Zawadi",
            "address": "Avenue Patrice Lumumba 45, Panzi",
            "lat": -2.5380,
            "lng": 28.8580,
            "phone_airtel": "0991234567",
            "phone_orange": "0841234567",
            "purchases_last_week": {
                "airtel": 150000,
                "orange": 120000,
                "vodacom": 80000,
                "africel": 50000
            },
            "total_purchases": 400000,  # High value client
            "last_purchase_date": "2024-01-25"
        },
        {
            "id": 2,
            "name": "Kiosk Bénédiction",
            "address": "Rue de l'Église 12, Panzi",
            "lat": -2.5420,
            "lng": 28.8620,
            "phone_airtel": "0997654321",
            "phone_orange": "0847654321",
            "purchases_last_week": {
                "airtel": 200000,
                "orange": 180000,
                "vodacom": 150000,
                "africel": 70000
            },
            "total_purchases": 600000,  # High value client
            "last_purchase_date": "2024-01-26"
        },
        {
            "id": 3,
            "name": "Phone House Ibanda",
            "address": "Avenue du Commerce 78, Ibanda",
            "lat": -2.5350,
            "lng": 28.8550,
            "phone_airtel": "0991122334",
            "phone_orange": "0841122334",
            "purchases_last_week": {
                "airtel": 50000,
                "orange": 40000,
                "vodacom": 30000,
                "africel": 20000
            },
            "total_purchases": 140000,  # Medium value client
            "last_purchase_date": "2024-01-24"
        },
        {
            "id": 4,
            "name": "Ets. Mumbere Telecom",
            "address": "Boulevard du Lac 156, Panzi",
            "lat": -2.5450,
            "lng": 28.8600,
            "phone_airtel": "0994455667",
            "phone_orange": "0844455667",
            "purchases_last_week": {
                "airtel": 300000,
                "orange": 250000,
                "vodacom": 200000,
                "africel": 100000
            },
            "total_purchases": 850000,  # Very high value client
            "last_purchase_date": "2024-01-26"
        },
        {
            "id": 5,
            "name": "Cyber Café Espoir",
            "address": "Rue des Écoles 34, Ibanda",
            "lat": -2.5320,
            "lng": 28.8530,
            "phone_airtel": "0998877665",
            "phone_orange": "0848877665",
            "purchases_last_week": {
                "airtel": 25000,
                "orange": 20000,
                "vodacom": 15000,
                "africel": 10000
            },
            "total_purchases": 70000,  # Low value client
            "last_purchase_date": "2024-01-23"
        },
        {
            "id": 6,
            "name": "Alimentation La Grâce",
            "address": "Avenue Industrielle 89, Panzi",
            "lat": -2.5400,
            "lng": 28.8650,
            "phone_airtel": "0993344556",
            "phone_orange": "0843344556",
            "purchases_last_week": {
                "airtel": 80000,
                "orange": 60000,
                "vodacom": 50000,
                "africel": 30000
            },
            "total_purchases": 220000,  # Medium value client
            "last_purchase_date": "2024-01-25"
        },
        {
            "id": 7,
            "name": "Pharmacie du Peuple",
            "address": "Rue de la Santé 23, Ibanda",
            "lat": -2.5370,
            "lng": 28.8510,
            "phone_airtel": "0996677889",
            "phone_orange": "0846677889",
            "purchases_last_week": {
                "airtel": 15000,
                "orange": 10000,
                "vodacom": 8000,
                "africel": 5000
            },
            "total_purchases": 38000,  # Low value client
            "last_purchase_date": "2024-01-22"
        },
        {
            "id": 8,
            "name": "Grand Marché Mobile",
            "address": "Place du Marché Central, Panzi",
            "lat": -2.5410,
            "lng": 28.8570,
            "phone_airtel": "0992233445",
            "phone_orange": "0842233445",
            "purchases_last_week": {
                "airtel": 180000,
                "orange": 150000,
                "vodacom": 120000,
                "africel": 80000
            },
            "total_purchases": 530000,  # High value client
            "last_purchase_date": "2024-01-26"
        },
    ]

    # Calculate value tier for each client (for marker coloring)
    # Thresholds: High >= 400,000 FC, Medium >= 100,000 FC, Low < 100,000 FC
    HIGH_VALUE_THRESHOLD = 400000
    MEDIUM_VALUE_THRESHOLD = 100000

    for client in hardcoded_client_locations:
        total = client["total_purchases"]
        if total >= HIGH_VALUE_THRESHOLD:
            client["value_tier"] = "high"
        elif total >= MEDIUM_VALUE_THRESHOLD:
            client["value_tier"] = "medium"
        else:
            client["value_tier"] = "low"

    client_locations = hardcoded_client_locations

    # Calculate summary statistics for the page
    total_clients = len(client_locations)
    total_weekly_sales = sum(c["total_purchases"] for c in client_locations)
    high_value_count = sum(
        1 for c in client_locations if c["value_tier"] == "high")

    # Network breakdown
    network_totals = {
        "airtel": sum(c["purchases_last_week"]["airtel"] for c in client_locations),
        "orange": sum(c["purchases_last_week"]["orange"] for c in client_locations),
        "vodacom": sum(c["purchases_last_week"]["vodacom"] for c in client_locations),
        "africel": sum(c["purchases_last_week"]["africel"] for c in client_locations),
    }

    # Set default center for Panzi/Ibanda area
    default_center_lat = -2.5395
    default_center_lng = 28.8575

    # If clients exist, center on their average location
    if client_locations:
        avg_lat = sum(loc["lat"]
                      for loc in client_locations) / len(client_locations)
        avg_lng = sum(loc["lng"]
                      for loc in client_locations) / len(client_locations)
        default_center_lat = avg_lat
        default_center_lng = avg_lng

    return render_template(
        "main/client_map.html",
        client_locations=client_locations,
        default_center_lat=default_center_lat,
        default_center_lng=default_center_lng,
        total_clients=total_clients,
        total_weekly_sales=total_weekly_sales,
        high_value_count=high_value_count,
        network_totals=network_totals,
        segment="client_map",
    )
