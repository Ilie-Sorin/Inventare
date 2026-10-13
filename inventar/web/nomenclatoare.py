"""Ecranele pentru locații, activități și grupuri."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import SelectMultipleField, StringField, SubmitField
from wtforms.validators import DataRequired

from inventar.domain import nomenclatoare
from inventar.domain.comun import EroareValidare
from inventar.extensions import db
from inventar.models import Activitate, Grup, Locatie, Persoana
from inventar.web import actor_curent, arata_eroare, rol_necesar
from inventar.web.formulare import OBLIGATORIU, FormularNomenclator

bp = Blueprint("nomenclatoare", __name__)

TIPURI = {
    "locatii": {"model": Locatie, "titlu": "Locații", "singular": "locație"},
    "activitati": {"model": Activitate, "titlu": "Activități", "singular": "activitate"},
}


def _tip(tip: str) -> dict:
    if tip not in TIPURI:
        abort(404)
    return TIPURI[tip]


@bp.route("/nomenclatoare/<tip>")
@login_required
def lista(tip: str):
    info = _tip(tip)
    model = info["model"]
    obiecte = db.session.scalars(select(model).order_by(model.activ.desc(), model.denumire)).all()
    return render_template("nomenclatoare/lista.html", tip=tip, info=info, obiecte=obiecte)


@bp.route("/nomenclatoare/<tip>/nou", methods=["GET", "POST"])
@bp.route("/nomenclatoare/<tip>/<int:obiect_id>", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def editare(tip: str, obiect_id: int | None = None):
    info = _tip(tip)
    model = info["model"]
    obiect = db.get_or_404(model, obiect_id) if obiect_id else None
    form = FormularNomenclator(obj=obiect)
    if form.validate_on_submit():
        try:
            if obiect:
                nomenclatoare.modifica_nomenclator(db.session, actor_curent(), model, obiect.id,
                                                   form.cod.data, form.denumire.data)
            else:
                nomenclatoare.creeaza_nomenclator(db.session, actor_curent(), model, form.cod.data,
                                                  form.denumire.data)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Salvat.", "success")
            return redirect(url_for(".lista", tip=tip))
    return render_template("nomenclatoare/editare.html", tip=tip, info=info, form=form, obiect=obiect)


@bp.route("/nomenclatoare/<tip>/<int:obiect_id>/activ", methods=["POST"])
@rol_necesar("OPERATOR")
def comuta_activ(tip: str, obiect_id: int):
    info = _tip(tip)
    obiect = db.get_or_404(info["model"], obiect_id)
    try:
        nomenclatoare.seteaza_activ_nomenclator(db.session, actor_curent(), info["model"], obiect.id,
                                                not obiect.activ)
    except EroareValidare as e:
        arata_eroare(e)
    return redirect(url_for(".lista", tip=tip))


class FormularGrup(FlaskForm):
    denumire = StringField("Denumire", validators=[DataRequired(OBLIGATORIU)])
    persoane = SelectMultipleField("Persoane", coerce=int)
    trimite = SubmitField("Salvează")


@bp.route("/grupuri")
@login_required
def grupuri():
    return render_template("nomenclatoare/grupuri.html",
                           grupuri=db.session.scalars(select(Grup).order_by(Grup.denumire)).all())


@bp.route("/grupuri/nou", methods=["GET", "POST"])
@bp.route("/grupuri/<int:grup_id>", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def editare_grup(grup_id: int | None = None):
    grup = db.get_or_404(Grup, grup_id) if grup_id else None
    form = FormularGrup(obj=grup)
    membri_curenti = {p.id for p in grup.persoane} if grup else set()
    form.persoane.choices = [
        (p.id, p.nume) for p in db.session.scalars(select(Persoana).order_by(Persoana.nume))
        if p.activ or p.id in membri_curenti
    ]
    if request.method == "GET":
        form.persoane.data = sorted(membri_curenti)
    if form.validate_on_submit():
        try:
            if grup:
                nomenclatoare.modifica_grup(db.session, actor_curent(), grup.id, form.denumire.data,
                                            form.persoane.data)
            else:
                nomenclatoare.creeaza_grup(db.session, actor_curent(), form.denumire.data, form.persoane.data)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Grup salvat.", "success")
            return redirect(url_for(".grupuri"))
    return render_template("nomenclatoare/grup.html", form=form, grup=grup)


@bp.route("/grupuri/<int:grup_id>/stergere", methods=["POST"])
@rol_necesar("OPERATOR")
def sterge_grup(grup_id: int):
    try:
        nomenclatoare.sterge_grup(db.session, actor_curent(), grup_id)
    except EroareValidare as e:
        arata_eroare(e)
    else:
        flash("Grup șters.", "success")
    return redirect(url_for(".grupuri"))
