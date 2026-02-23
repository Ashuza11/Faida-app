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
    EqualTo,
)
from apps.models import (
    NetworkType,
    Sale,
    CashOutflowCategory,
    RoleType,
    User,
    validate_drc_phone,
)
import enum
from decimal import Decimal


# New Stocker (user)
class StockeurForm(FlaskForm):
    """
    Form for VENDEUR to create a new STOCKEUR (employee).

    Note: No role field - vendeurs can ONLY create stockeurs.
    The role is automatically set to STOCKEUR in the route.
    """

    username = StringField(
        "Nom d'utilisateur",
        validators=[
            DataRequired(message="Le nom d'utilisateur est requis"),
            Length(min=2, max=64,
                   message="Le nom doit contenir entre 2 et 64 caractères")
        ],
        render_kw={
            "placeholder": "Ex: Jean Mutombo",
            "class": "form-control"
        }
    )

    phone = StringField(
        "Numéro de téléphone",
        validators=[
            DataRequired(message="Le numéro de téléphone est requis"),
            Length(min=9, max=20)
        ],
        render_kw={
            "placeholder": "Ex: 0812345678",
            "class": "form-control"
        }
    )

    email = StringField(
        "Email (optionnel)",
        validators=[
            Optional(),
            Email(message="Adresse email invalide"),
            Length(max=120)
        ],
        render_kw={
            "placeholder": "email@exemple.com (optionnel)",
            "class": "form-control"
        }
    )

    password = PasswordField(
        "Mot de passe",
        validators=[
            DataRequired(message="Le mot de passe est requis"),
            Length(min=6, message="Le mot de passe doit contenir au moins 6 caractères")
        ],
        render_kw={
            "placeholder": "Minimum 6 caractères",
            "class": "form-control"
        }
    )

    submit = SubmitField("Créer le stockeur")

    def validate_phone(self, field):
        """Validate phone is a valid DRC number."""
        if not validate_drc_phone(field.data):
            raise ValidationError(
                "Numéro de téléphone invalide. "
                "Format accepté: 0812345678 ou +243812345678"
            )


class UserEditForm(FlaskForm):
    """
    Form for admin to edit an existing user.
    Password field is excluded as it's typically handled separately.
    """

    username = StringField(
        "Nom",
        id="edit_username",
        validators=[DataRequired()],
        render_kw={"placeholder": "Entrer le nom d'utilisateur"},
    )
    phone = StringField(
        "Numéro",
        id="edit_phone",
        validators=[Optional(), Length(min=9, max=20)],
        render_kw={"placeholder": "Ex: 0812345678"},
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
        choices=[(network.name, network.value.capitalize())
                 for network in NetworkType],
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
        validators=[DataRequired(
            message="Veuillez choisir une option client.")],
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
            Optional(),
            NumberRange(
                min=Decimal("0.00"), message="L'argent donné ne peut pas être négatif."
            ),
        ],
        render_kw={"step": "0.01"},
    )
    submit = SubmitField("Enregistre Vente")

    def validate(self, extra_validators=None):
        # Custom validation for client fields
        if not super(SaleForm, self).validate(extra_validators):
            return False

        if self.client_choice.data == "existing":
            if not self.existing_client_id.data:
                errors = list(self.existing_client_id.errors)
                errors.append("Veuillez sélectionner un client existant.")
                self.existing_client_id.errors = errors
                return False
        elif self.client_choice.data == "new":
            if not self.new_client_name.data:
                errors = list(self.new_client_name.errors)
                errors.append("Veuillez entrer le nom du nouveau client.")
                self.new_client_name.errors = errors
                return False
        return True


def get_sales_with_debt(vendeur_id=None):
    """Return (id, label) choices for sales that still have outstanding debt.
    Always pass vendeur_id so only that business's sales are shown.
    """
    query = Sale.query.filter(Sale.debt_amount > Decimal("0.00"))
    if vendeur_id is not None:
        query = query.filter(Sale.vendeur_id == vendeur_id)
    sales = query.order_by(Sale.created_at.desc()).all()
    return [
        (
            s.id,
            f"Vente #{s.id} — {s.client.name if s.client else (s.client_name_adhoc or 'Inconnu')} "
            f"(Dette: {s.debt_amount:,.2f} FC)",
        )
        for s in sales
    ]


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
    submit = SubmitField("Enregistrer la Sortie")


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
        # Choices are set by the route after instantiation using get_sales_with_debt(vendeur_id=...)
        if not self.sale_id.choices:
            self.sale_id.choices = []


# User Profile Form
class EditProfileForm(FlaskForm):
    username = StringField(
        "Nom d'utilisateur", validators=[DataRequired(), Length(min=3, max=64)]
    )
    email = StringField(
        "Adresse e-mail", validators=[DataRequired(), Email(), Length(max=120)]
    )
    phone = StringField(
        "Numéro de téléphone (Facultatif)", validators=[Optional(), Length(max=20)]
    )

    # Include 'about_me' only if you have this column in your User model
    about_me = TextAreaField("À propos de moi", validators=[
                             Length(min=0, max=140)])

    current_password = PasswordField(
        "Mot de passe actuel (pour les modifications)", validators=[Optional()]
    )
    new_password = PasswordField(
        "Nouveau mot de passe", validators=[Optional(), Length(min=6)]
    )
    confirm_new_password = PasswordField(
        "Confirmer le nouveau mot de passe",
        validators=[
            EqualTo("new_password",
                    message="Les mots de passe doivent correspondre")
        ],
    )

    submit = SubmitField("Mettre à jour le profil")

    def __init__(self, original_username, original_email, *args, **kwargs):
        super(EditProfileForm, self).__init__(*args, **kwargs)
        self.original_username = original_username
        self.original_email = original_email

    def validate_username(self, username):
        if username.data != self.original_username:
            user = User.query.filter_by(username=self.username.data).first()
            if user:
                raise ValidationError(
                    "Ce nom d'utilisateur est déjà pris. Veuillez en choisir un autre."
                )

    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=self.email.data).first()
            if user:
                raise ValidationError(
                    "Cette adresse e-mail est déjà utilisée. Veuillez en choisir une autre."
                )


# Form for confirming deletion of a sale
class DeleteConfirmForm(FlaskForm):
    submit = SubmitField("Oui, Supprimer", validators=[DataRequired()])
