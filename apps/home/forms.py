from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import Email, DataRequired
import enum


class RoleType(enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
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
