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
)
from wtforms.validators import (
    Email,
    DataRequired,
    Optional,
    Length,
    NumberRange,
    ValidationError,
)
from apps.authentication.models import NetworkType, Client
import enum
from decimal import Decimal


class RoleType(enum.Enum):
    SUPERADMIN = "superadmin"
    VENDEUR = "vendeur"


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
        choices=[
            (role.value, role.name.capitalize())
            for role in RoleType  # Allow all roles for editing if needed
        ],
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


# Custom validator to ensure custom_selling_price is provided if 'custom' is selected
def validate_custom_price_if_selected(form, field):
    if form.selling_price_choice.data == "custom" and not field.data:
        raise ValidationError(
            'Veuillez entrer un prix de vente personnalisé lorsque "Entrer un prix personnalisé" est sélectionné.'
        )


class StockPurchaseForm(FlaskForm):
    """
    Form for registering a new stock purchase.
    """

    network = SelectField(
        "Réseaux",
        choices=[(tag.value, tag.value.capitalize()) for tag in NetworkType],
        validators=[DataRequired()],
        render_kw={"class": "form-control"},
    )

    amount_purchased = IntegerField(
        "Montant acheté (Unités)",
        validators=[
            DataRequired(),
            NumberRange(min=1, message="Le montant doit être positif"),
        ],
        render_kw={"placeholder": "e.g., 50000", "class": "form-control"},
    )

    # Select field for selling price choices
    selling_price_choice = SelectField(
        "Prix de vente par unité",
        choices=[
            ("", "Sélectionner un prix ou entrer un personnalisé"),
            ("27.5", "27.5 FC (27500 FC pour 1000 unités)"),
            ("28.0", "28.0 FC (28000 FC pour 1000 unités)"),
            ("custom", "Entrer un prix personnalisé"),
        ],
        validators=[
            DataRequired(
                message="Veuillez sélectionner un prix de vente ou en entrer un personnalisé."
            )
        ],
        default="",
    )

    # Field for custom selling price, validated conditionally
    custom_selling_price = DecimalField(
        "Prix de vente personnalisé (FC)",
        validators=[
            Optional(),
            NumberRange(min=0.01),
            validate_custom_price_if_selected,
        ],
        render_kw={"placeholder": "Entrer le prix personnalisé", "step": "0.01"},
    )

    submit = SubmitField(
        "Enregistrer l'achat",
        render_kw={"class": "btn btn-primary mt-3"},
    )


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
        render_kw={"step": "0.01"},  # Ensure HTML5 step for decimals
    )
    # reduction_rate_applied = DecimalField(
    #     "Taux de Réduction (%)",
    #     default=Decimal("0.00"),  # Set a default to 0.00
    #     validators=[
    #         Optional(),
    #         NumberRange(
    #             min=Decimal("0.00"),
    #             max=Decimal("100.00"),
    #             message="Le taux de réduction doit être entre 0 et 100.",
    #         ),
    #     ],
    #     render_kw={"step": "0.01"},
    # )


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
