from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField
from wtforms.validators import Email, DataRequired, Optional, ValidationError
import re


# Fonction utilitaire de validation RDC
def validate_drc_phone_format(form, field):
    pattern = r'^(?:\+243|0)?(80|81|82|83|84|85|86|87|88|89|90|91|92|93|94|95|96|97|98|99)\d{7}$'
    if not re.match(pattern, field.data):
        raise ValidationError("Format RDC invalide (ex: 0812345678).")


def normalize_drc_phone(phone: str) -> str:
    """
    Normalise un numéro de téléphone de la RDC vers le format international +243XXXXXXXXX
    Gère les formats :
    - 0812345678
    - +243812345678
    - 00243812345678
    - 912345678
    """
    phone = phone.replace(" ", "").strip()

    if phone.startswith("00243"):
        phone = phone[5:]  # enlever 00243
    elif phone.startswith("+243"):
        phone = phone[4:]  # enlever +243
    elif phone.startswith("0"):
        phone = phone[1:]  # enlever 0

    if len(phone) == 9 and phone.isdigit():
        return "+243" + phone

    return phone




# login and registration
class LoginForm(FlaskForm):
    phone = StringField(
        "Téléphone",
        validators=[DataRequired()],
        render_kw={"placeholder": "Ex: 0812345678 ou +243812345678"}
    )
    password = PasswordField(
        "Mot de passe",
        validators=[DataRequired()],
        render_kw={"placeholder": "Mot de passe"}
    )

    def validate_phone(self, field):
        data = field.data.strip().replace(" ", "")
        pattern = r'^(?:\+243|0)?(80|81|82|83|84|85|86|87|88|89|90|91|92|93|94|95|96|97|98|99)\d{7}$'
        if not re.match(pattern, data):
            raise ValidationError("Numéro RDC invalide.")





class CreateAccountForm(FlaskForm):
    username = StringField("Nom d'utilisateur", id="username_create", validators=[DataRequired()])
    phone = StringField("Téléphone", id="phone_create", validators=[DataRequired(), validate_drc_phone_format])
    email = StringField("Email (Optionnel)", id="email_create", validators=[Optional(), Email()])
    password = PasswordField("Mot de passe", id="pwd_create", validators=[DataRequired()])
