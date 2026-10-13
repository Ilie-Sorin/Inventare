"""Formularele WTForms comune mai multor ecrane."""
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Optional

from inventar.extensions import db
from inventar.models import Activitate, Locatie

OBLIGATORIU = "Câmp obligatoriu."


def optiuni(model, doar_active: bool = True, curent_id: int | None = None) -> list[tuple[int, str]]:
    """Opțiunile unui select; păstrează valoarea curentă chiar dacă între timp a fost dezactivată."""
    rezultat = []
    for obiect in db.session.scalars(select(model).order_by(model.denumire)):
        if obiect.activ or not doar_active or obiect.id == curent_id:
            rezultat.append((obiect.id, obiect.denumire))
    return rezultat


def zero_ca_none(valoare: int | None) -> int | None:
    return valoare or None


class FormularNomenclator(FlaskForm):
    cod = StringField("Cod", validators=[DataRequired(OBLIGATORIU)])
    denumire = StringField("Denumire", validators=[DataRequired(OBLIGATORIU)])
    trimite = SubmitField("Salvează")


class FormularIncadrare(FlaskForm):
    locatie_id = SelectField("Locație", coerce=int, validators=[DataRequired(OBLIGATORIU)])
    activitate_id = SelectField("Activitate", coerce=int, validators=[DataRequired(OBLIGATORIU)])
    valabil_de_la = DateField("Valabilă de la", validators=[DataRequired(OBLIGATORIU)])
    motiv = TextAreaField("Motiv", validators=[Optional()], render_kw={"rows": 2})
    trimite = SubmitField("Salvează")

    def incarca_optiuni(self, locatie_curenta: int | None = None, activitate_curenta: int | None = None) -> None:
        self.locatie_id.choices = optiuni(Locatie, curent_id=locatie_curenta)
        self.activitate_id.choices = optiuni(Activitate, curent_id=activitate_curenta)
