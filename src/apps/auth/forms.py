"""
Authentication Forms - Phone-based login

Changes from original:
- Login uses phone number instead of username
- Registration requires invite code for vendeurs
- Phone validation for DRC numbers
"""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import (
    DataRequired,
    Length,
    Optional,
    Email,
    EqualTo,
    ValidationError,
)
from apps.models import User, InviteCode, normalize_phone, validate_drc_phone


class LoginForm(FlaskForm):
    """
    Login form using phone number (replaces username-based login).
    """
    phone = StringField(
        "Numéro de téléphone",
        id="phone_login",
        validators=[
            DataRequired(message="Le numéro de téléphone est requis"),
            Length(min=9, max=20, message="Numéro de téléphone invalide")
        ],
        render_kw={
            "placeholder": "Ex: 0812345678 ou +243812345678",
            "class": "form-control",
            "autofocus": True
        }
    )

    password = PasswordField(
        "Mot de passe",
        id="pwd_login",
        validators=[
            DataRequired(message="Le mot de passe est requis")
        ],
        render_kw={
            "placeholder": "Votre mot de passe",
            "class": "form-control"
        }
    )

    remember_me = BooleanField("Se souvenir de moi")

    submit = SubmitField("Connexion")

    def validate_phone(self, field):
        """Validate phone number format."""
        if not validate_drc_phone(field.data):
            raise ValidationError(
                "Numéro de téléphone invalide. "
                "Format accepté: 0812345678 ou +243812345678"
            )


class VendeurRegistrationForm(FlaskForm):
    """
    Registration form for new Vendeurs (business owners).
    Requires a valid invite code from platform admin.
    """

    # Invite code (required for vendeur registration)
    invite_code = StringField(
        "Code d'invitation",
        validators=[
            DataRequired(message="Le code d'invitation est requis"),
            Length(min=6, max=32)
        ],
        render_kw={
            "placeholder": "Entrez votre code d'invitation",
            "class": "form-control"
        }
    )

    username = StringField(
        "Nom de votre entreprise",
        validators=[
            DataRequired(message="Le nom est requis"),
            Length(min=2, max=64,
                   message="Le nom doit contenir entre 2 et 64 caractères")
        ],
        render_kw={
            "placeholder": "Ex: Ets. Mumbere Telecom",
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
            "placeholder": "votre@email.com (optionnel)",
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

    password_confirm = PasswordField(
        "Confirmer le mot de passe",
        validators=[
            DataRequired(message="Veuillez confirmer le mot de passe"),
            EqualTo('password', message="Les mots de passe ne correspondent pas")
        ],
        render_kw={
            "placeholder": "Répétez le mot de passe",
            "class": "form-control"
        }
    )

    submit = SubmitField("Créer mon compte")

    def validate_invite_code(self, field):
        """Check if invite code exists and is valid."""
        code = InviteCode.query.filter_by(code=field.data.strip()).first()

        if not code:
            raise ValidationError("Code d'invitation invalide")

        if not code.is_valid:
            if code.used_by_id is not None:
                raise ValidationError(
                    "Ce code d'invitation a déjà été utilisé")
            else:
                raise ValidationError("Ce code d'invitation a expiré")

    def validate_phone(self, field):
        """Validate phone number format and uniqueness."""
        if not validate_drc_phone(field.data):
            raise ValidationError(
                "Numéro de téléphone invalide. "
                "Format accepté: 0812345678 ou +243812345678"
            )

        # Check if phone already exists
        normalized = normalize_phone(field.data)
        existing = User.query.filter_by(phone=normalized).first()
        if existing:
            raise ValidationError("Ce numéro de téléphone est déjà utilisé")

    def validate_username(self, field):
        """Check if username is unique."""
        existing = User.query.filter_by(username=field.data.strip()).first()
        if existing:
            raise ValidationError("Ce nom d'entreprise est déjà utilisé")

    def validate_email(self, field):
        """Check if email is unique (if provided)."""
        if field.data:
            existing = User.query.filter_by(
                email=field.data.strip().lower()).first()
            if existing:
                raise ValidationError("Cette adresse email est déjà utilisée")


# Keep the old form for backward compatibility (but it won't be used)
class CreateAccountForm(FlaskForm):
    """Legacy form - kept for template compatibility."""
    username = StringField(
        "Username", id="username_create", validators=[DataRequired()]
    )
    email = StringField(
        "Email", id="email_create", validators=[DataRequired(), Email()]
    )
    password = PasswordField("Password", id="pwd_create",
                             validators=[DataRequired()])
