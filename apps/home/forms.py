from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    SelectField,
    BooleanField,
    IntegerField,
    DecimalField,
    FieldList,
    FormField,
    TextAreaField,
)
from wtforms.validators import (
    Email,
    DataRequired,
    Optional,
    Length,
    NumberRange,
    ValidationError,
)
from apps.authentication.models import NetworkType, Sale, CashOutflowCategory, RoleType
import enum
from decimal import Decimal


# New Stocker (user)
class StockerForm(FlaskForm):
    """
    Form for admin to add a new stocker.
    Fields are pre-filled with Bootstrap classes for styling.
    """

    username = StringField(
        "Nom",
        id="stocker_username",
        validators=[DataRequired()],
        render_kw={"placeholder": "Entrer le nom d'utilisateur"},
    )
    email = StringField(
        "Email",
        id="stocker_email",
        validators=[DataRequired(), Email()],
        render_kw={"placeholder": " Entrer email"},
    )
    password = PasswordField(
        "Mot de passe",
        id="stocker_password",
        validators=[DataRequired()],
        render_kw={"placeholder": "Entrer Mot de passe"},
    )
    role = SelectField(
        "Role",
        id="stocker_role",
        choices=[
            (role.value, role.name.capitalize())
            for role in RoleType
            if role != RoleType.SUPERADMIN
        ],
        validators=[DataRequired()],
    )
    submit = SubmitField("Enregistrer")


class UserEditForm(FlaskForm):
    """
    Form for admin to edit an existing user.
    Password field is excluded as it's typically handled separately.
    """

    username = StringField(
        "Nom d'utilisateur",
        id="edit_username",
        validators=[DataRequired()],
        render_kw={"placeholder": "Entrer le nom d'utilisateur"},
    )
    email = StringField(
        "Email",
        id="edit_email",
        validators=[DataRequired(), Email()],
        render_kw={"placeholder": "Entrer email"},
    )
    role = SelectField(
        "Role",
        id="edit_role",
        choices=[(role.value, role.name.capitalize()) for role in RoleType],
        validators=[DataRequired()],
    )
    is_active = BooleanField(
        "Actif",
        id="edit_is_active",
        validators=[Optional()],
    )
    submit = SubmitField("Mettre à jour")


# Form for adding a new Client
class ClientForm(FlaskForm):
    name = StringField(
        "Nom du Client", validators=[DataRequired(), Length(min=2, max=128)]
    )
    # email = StringField("Email (Optionnel)", validators=[Optional(), Email()])
    phone_airtel = StringField(
        "Téléphone Airtel (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    phone_africel = StringField(
        "Téléphone Africell (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    phone_orange = StringField(
        "Téléphone Orange (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    phone_vodacom = StringField(
        "Téléphone Vodacom (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    address = StringField(
        "Adresse (Optionnel)", validators=[Optional(), Length(max=255)]
    )
    discount_rate = DecimalField(
        "Taux de Remise (%)",
        validators=[Optional(), NumberRange(min=0, max=100)],
        default=0.0,
    )
    submit = SubmitField("Ajouter Client")


# Form for editing an existing Client (KEEP gps_lat/long here for manual editing if needed)
class ClientEditForm(FlaskForm):
    name = StringField(
        "Nom du Client", validators=[DataRequired(), Length(min=2, max=128)]
    )
    email = StringField("Email (Optionnel)", validators=[Optional(), Email()])
    phone_airtel = StringField(
        "Téléphone Airtel (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    phone_africel = StringField(
        "Téléphone Africell (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    phone_orange = StringField(
        "Téléphone Orange (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    phone_vodacom = StringField(
        "Téléphone Vodacom (Optionnel)", validators=[Optional(), Length(max=20)]
    )
    address = StringField(
        "Adresse (Optionnel)", validators=[Optional(), Length(max=255)]
    )
    gps_lat = DecimalField(
        "Latitude GPS (Optionnel)", validators=[Optional()]
    )  # Keep for editing
    gps_long = DecimalField(
        "Longitude GPS (Optionnel)", validators=[Optional()]
    )  # Keep for editing
    is_active = BooleanField("Actif")
    discount_rate = DecimalField(
        "Taux de Remise (%)",
        validators=[Optional(), NumberRange(min=0, max=100)],
        default=0.0,
    )
    submit = SubmitField("Mettre à jour")


# Custom validator for conditional price fields
def validate_custom_price_if_selected(form, field):

    # Check for custom buying price
    if field.name == "custom_buying_price":
        if form.buying_price_choice.data == "custom" and not field.data:
            raise ValidationError(
                'Veuillez entrer un prix d\'achat personnalisé lorsque "Entrer un prix personnalisé" est sélectionné.'
            )
    # Check for custom selling price
    elif field.name == "custom_intended_selling_price":
        if form.intended_selling_price_choice.data == "custom" and not field.data:
            raise ValidationError(
                'Veuillez entrer un prix de vente personnalisé lorsque "Entrer un prix personnalisé" est sélectionné.'
            )


class StockPurchaseForm(FlaskForm):
    """
    Form for registering a new stock purchase.
    """

    network = SelectField(
        "Réseaux",
        choices=[(tag.name, tag.value) for tag in NetworkType],
        validators=[DataRequired()],
        render_kw={"class": "form-control"},
    )

    amount_purchased = IntegerField(
        "Quantité achetée (Unités)",
        validators=[
            DataRequired(),
            NumberRange(min=1, message="La quantité doit être positive"),
        ],
        render_kw={"placeholder": "e.g., 50000", "class": "form-control"},
    )

    buying_price_choice = SelectField(
        "Prix d'achat par unité",
        choices=[
            ("", "Sélectionner un prix d'achat ou entrer un personnalisé"),
            ("26.79", "26.79 FC"),
            ("27.075", "27.075 FC"),
            ("custom", "Entrer un prix personnalisé"),
        ],
        validators=[
            DataRequired(
                message="Veuillez sélectionner un prix d'achat ou en entrer un personnalisé."
            )
        ],
        default="",
    )

    # Field for custom BUYING price, validated conditionally
    custom_buying_price = DecimalField(
        "Prix d'achat personnalisé (FC)",
        validators=[
            Optional(),
            NumberRange(min=1),
            validate_custom_price_if_selected,
        ],
        render_kw={
            "placeholder": "Entrer le prix d'achat personnalisé",
            "step": "0.01",
        },
    )

    # INTENDED SELLING price choices
    intended_selling_price_choice = SelectField(
        "Prix de vente par unité (Prévu)",
        choices=[
            ("", "Sélectionner un prix de vente ou entrer un personnalisé"),
            ("27.5", "27.5 FC"),
            ("28.0", "28.0 FC"),
            ("custom", "Entrer un prix personnalisé"),
        ],
        validators=[
            DataRequired(
                message="Veuillez sélectionner un prix de vente ou en entrer un personnalisé."
            )
        ],
        default="",
    )

    # INTENDED SELLING price
    custom_intended_selling_price = DecimalField(
        "Prix de vente personnalisé (FC)",
        validators=[
            Optional(),
            NumberRange(min=0.01),
            validate_custom_price_if_selected,
        ],
        render_kw={
            "placeholder": "Entrer le prix de vente personnalisé",
            "step": "0.01",
        },
    )

    submit = SubmitField(
        "Enregistrer l'achat",
        render_kw={"class": "btn btn-primary mt-3"},
    )

    # Override validate method to ensure consistency for custom fields
    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False

        return True


# Helper to get choices for network enum
def get_network_choices():
    return [(network.name, network.value.capitalize()) for network in NetworkType]


# Form for a single sale item (network order)
class SaleItemForm(FlaskForm):
    # Add this line to disable CSRF for subforms
    class Meta(FlaskForm.Meta):
        csrf = False

    network = SelectField(
        "Réseau",
        choices=[(network.name, network.value.capitalize()) for network in NetworkType],
        validators=[DataRequired(message="Veuillez sélectionner un réseau.")],
    )
    quantity = IntegerField(
        "Quantité",
        validators=[
            DataRequired(message="Veuillez entrer la quantité."),
            NumberRange(min=1, message="La quantité doit être au moins 1."),
        ],
    )
    price_per_unit_applied = DecimalField(
        "Prix Unitaire Appliqué (FC)",
        validators=[
            Optional(),
            NumberRange(
                min=Decimal("0.01"), message="Le prix unitaire doit être positif."
            ),
        ],
        render_kw={"step": "0.01"},
    )


# Form for a single sale item (network order)
class SaleForm(FlaskForm):
    client_choice = SelectField(
        "Choix du Client",
        choices=[
            ("existing", "Client Existant"),
            ("new", "Nouveau Client (Ad-hoc)"),
        ],
        validators=[DataRequired(message="Veuillez choisir une option client.")],
    )
    existing_client_id = SelectField(
        "Sélectionnez un client existant",
        coerce=str,
        validators=[Optional()],
        render_kw={"class": "form-control"},
    )
    new_client_name = StringField(
        "Nom du Nouveau Client",
        validators=[
            Optional(),
            Length(
                max=100, message="Le nom du client ne peut pas dépasser 100 caractères."
            ),
        ],
    )
    sale_items = FieldList(
        FormField(SaleItemForm), min_entries=1
    )  # Ensure at least one item
    cash_paid = DecimalField(
        "Argent donné (FC)",
        validators=[
            Optional(),  # Make it optional here
            NumberRange(
                min=Decimal("0.00"), message="L'argent donné ne peut pas être négatif."
            ),
        ],
        render_kw={"step": "0.01"},
    )
    submit = SubmitField("Enregistrer la Vente")

    def validate(self, extra_validators=None):
        # Custom validation for client fields
        if not super(SaleForm, self).validate(extra_validators):
            return False

        if self.client_choice.data == "existing":
            if not self.existing_client_id.data:
                self.existing_client_id.errors.append(
                    "Veuillez sélectionner un client existant."
                )
                return False
        elif self.client_choice.data == "new":
            if not self.new_client_name.data:
                self.new_client_name.errors.append(
                    "Veuillez entrer le nom du nouveau client."
                )
                return False
        return True


def get_sales_with_debt():
    sales = Sale.query.filter(Sale.debt_amount > Decimal("0.00")).all()
    choices = [
        (
            s.id,
            f"Vente ID: {s.id} - Client: {s.client.name if s.client else s.client_name_adhoc} (Dette: {s.debt_amount:,.2f} FC)",
        )
        for s in sales
    ]
    return choices


class CashOutflowForm(FlaskForm):
    amount = DecimalField(
        "Montant (FC)",
        validators=[DataRequired(), NumberRange(min=0.01)],
        render_kw={"placeholder": "Ex: 15000.00"},
    )
    category = SelectField(
        "Catégorie",
        choices=[(cat.name, cat.value) for cat in CashOutflowCategory],
        validators=[DataRequired()],
    )
    description = StringField(
        "Description", render_kw={"placeholder": "Ex: Achat fournitures bureau"}
    )
    submit = SubmitField("Enregistrer la Sortie")  # Generic name 'submit'


class DebtCollectionForm(FlaskForm):
    sale_id = SelectField(
        "Sélectionner la Vente", coerce=int, validators=[DataRequired()]
    )
    amount_paid = DecimalField(
        "Montant Payé (FC)",
        validators=[DataRequired(), NumberRange(min=0.01)],
        render_kw={"placeholder": "Ex: 10000.00"},
    )
    description = StringField(
        "Description (Optionnel)",
        render_kw={"placeholder": "Ex: 1ère tranche paiement"},
    )
    submit = SubmitField("Enregistrer le Paiement")  # Generic name 'submit'

    def __init__(self, *args, **kwargs):
        super(DebtCollectionForm, self).__init__(*args, **kwargs)
        self.sale_id.choices = get_sales_with_debt()
