"""Comisiile de inventariere pe locații."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Optional

from inventar.domain.comisii import MembruNou, creeaza_comisie, modifica_comisie
from inventar.domain.comun import EroareValidare
from inventar.extensions import db
from inventar.models import Comisie, Locatie
from inventar.web import actor_curent, arata_eroare, rol_necesar
from inventar.web.formulare import OBLIGATORIU, optiuni

bp = Blueprint("comisii", __name__)


class FormularComisie(FlaskForm):
    locatie_id = SelectField("Locație", coerce=int, validators=[DataRequired(OBLIGATORIU)])
    valabil_de_la = DateField("Valabilă de la", validators=[DataRequired(OBLIGATORIU)])
    valabil_pana_la = DateField("Valabilă până la (opțional)", validators=[Optional()])
    presedinte = StringField("Președinte", validators=[Optional()])
    membri = TextAreaField("Membri (câte unul pe rând, în ordinea de pe listă)", render_kw={"rows": 5})
    trimite = SubmitField("Salvează")

    def membri_noi(self) -> list[MembruNou]:
        rezultat = [MembruNou(self.presedinte.data or "", "PRESEDINTE")]
        rezultat += [MembruNou(rand, "MEMBRU") for rand in (self.membri.data or "").splitlines()]
        return rezultat


@bp.route("/comisii")
@login_required
def lista():
    locatii = db.session.scalars(select(Locatie).order_by(Locatie.activ.desc(), Locatie.denumire)).all()
    comisii: dict[int, list[Comisie]] = {}
    for c in db.session.scalars(select(Comisie).order_by(Comisie.valabil_de_la.desc())):
        comisii.setdefault(c.locatie_id, []).append(c)
    return render_template("comisii/lista.html", locatii=locatii, comisii=comisii)


@bp.route("/comisii/nou", methods=["GET", "POST"])
@bp.route("/comisii/<int:comisie_id>", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def editare(comisie_id: int | None = None):
    comisie = db.get_or_404(Comisie, comisie_id) if comisie_id else None
    form = FormularComisie(obj=comisie)
    form.locatie_id.choices = optiuni(Locatie, curent_id=comisie.locatie_id if comisie else None)
    if request.method == "GET":
        if comisie:
            form.presedinte.data = next((m.nume for m in comisie.membri if m.calitate == "PRESEDINTE"), "")
            form.membri.data = "\n".join(m.nume for m in comisie.membri if m.calitate == "MEMBRU")
        elif request.args.get("locatie_id", type=int):
            form.locatie_id.data = request.args.get("locatie_id", type=int)
    if comisie:
        # Locația unei comisii existente nu se schimbă: s-ar muta tot istoricul ei.
        form.locatie_id.data = comisie.locatie_id
        form.locatie_id.render_kw = {"disabled": True}
    if form.validate_on_submit():
        try:
            if comisie:
                modifica_comisie(db.session, actor_curent(), comisie.id, form.valabil_de_la.data,
                                 form.valabil_pana_la.data, form.membri_noi())
            else:
                creeaza_comisie(db.session, actor_curent(), form.locatie_id.data, form.valabil_de_la.data,
                                form.valabil_pana_la.data, form.membri_noi())
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Comisie salvată.", "success")
            return redirect(url_for(".lista"))
    return render_template("comisii/editare.html", form=form, comisie=comisie)
