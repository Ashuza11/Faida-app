from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField
from wtforms.validators import Email, DataRequired, Optional, ValidationError
import re


# Fonction utilitaire de validation RDC
def validate_drc_phone_format(form, field):
    pattern = r'^(?:\+243|0)?(80|81|82|83|84|85|86|87|88|89|90|91|92|93|94|95|96|97|98|99)\d{7}$'
    if not re.match(pattern, field.data):
        raise ValidationError("Format RDC invalide (ex: 0812345678).")


# login and registration
class LoginForm(FlaskForm):
    # Ce champ acceptera soit le nom d'utilisateur, soit le téléphone
    login_id = StringField("Nom d'utilisateur ou Téléphone", id="login_id", validators=[DataRequired()])
    password = PasswordField("Mot de passe", id="pwd_login", validators=[DataRequired()])

    def validate_login_id(self, field):
        data = field.data
        # Si ça ressemble à un numéro (commence par +, 0 ou un chiffre)
        if any(char.isdigit() for char in data):
            # Regex RDC pour valider si c'est un téléphone
            pattern = r'^(?:\+243|0)?(80|81|82|83|84|85|86|87|88|89|90|91|92|93|94|95|96|97|98|99)\d{7}$'
            if not re.match(pattern, data):
                # Si c'est numérique mais pas au format RDC, on lève une erreur
                # Sauf si c'est un pseudo purement numérique (rare)
                if len(data) >= 9: 
                    raise ValidationError("Format de numéro RDC invalide.")

class CreateAccountForm(FlaskForm):
    username = StringField("Nom d'utilisateur", id="username_create", validators=[DataRequired()])
    phone = StringField("Téléphone", id="phone_create", validators=[DataRequired(), validate_drc_phone_format])
    email = StringField("Email (Optionnel)", id="email_create", validators=[Optional(), Email()])
    password = PasswordField("Mot de passe", id="pwd_create", validators=[DataRequired()])
