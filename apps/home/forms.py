from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    SelectField,
    BooleanField,
    IntegerField,
    DecimalField,
)
from wtforms.validators import Email, DataRequired, Optional, Length, NumberRange
from apps.authentication.models import NetworkType
import enum


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
    amount_purchased = DecimalField(
        "Montant acheté",
        validators=[
            DataRequired(),
            NumberRange(min=0.01, message=""),
        ],
        render_kw={
            "placeholder": "e.g., 50000",
            "class": "form-control",
        },
    )

    amount_purchased = IntegerField(
        "Montant acheté (Unités)",
        validators=[
            DataRequired(),
            NumberRange(min=1, message="Le montant doit être positif"),
        ],  # Min changed to 1
        render_kw={"placeholder": "e.g., 50000", "class": "form-control"},
    )

    submit = SubmitField(
        "Enregistrer l'achat",
        render_kw={"class": "btn btn-primary mt-3"},
    )
