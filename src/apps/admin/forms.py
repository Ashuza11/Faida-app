from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, SelectField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange

from apps.money import MAX_LEDGER_AMOUNT


class HistoricalSaleCostRepairForm(FlaskForm):
    unit_cost = DecimalField(
        "Coût d'achat par unité ($)",
        validators=[
            DataRequired(),
            NumberRange(
                min=Decimal("0.000000000001"), max=MAX_LEDGER_AMOUNT
            ),
        ],
        places=12,
        render_kw={"step": "0.000000000001"},
    )
    confidence = SelectField(
        "Niveau de confiance",
        choices=[
            ("estimated", "Estimé — meilleure donnée disponible"),
            ("verified", "Vérifié — confirmé par une preuve d'achat"),
        ],
        validators=[DataRequired()],
    )
    note = TextAreaField(
        "Justification",
        validators=[DataRequired(), Length(min=3, max=255)],
        render_kw={"rows": 3, "placeholder": "Ex: confirmé sur le reçu fournisseur"},
    )
