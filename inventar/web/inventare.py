"""Inventarele generate: generare cu perimetru, stări, regenerare, blocare, ștergere."""
import json
from datetime import date
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import func, select
from wtforms import DateField, SelectMultipleField, SubmitField
from wtforms.validators import DataRequired

from inventar import rapoarte, tiparire
from inventar.domain import generare
from inventar.domain.centralizatoare import TIPURI as TIPURI_CENTRALIZATOR
from inventar.domain.centralizatoare import centralizator
from inventar.domain.comun import EroareValidare
from inventar.domain.filtre import descriere
from inventar.domain.generare import Perimetru
from inventar.extensions import db
from inventar.models import Activitate, Cont, Grup, Inventar, InventarLinie, Locatie, Persoana
from inventar.web import actor_curent, arata_eroare, rol_necesar
from inventar.web.formulare import OBLIGATORIU, optiuni

bp = Blueprint("inventare", __name__)


class FormularInventar(FlaskForm):
    data = DateField("Data inventarului", validators=[DataRequired(OBLIGATORIU)])
    locatii = SelectMultipleField("Locații", coerce=int)
    activitati = SelectMultipleField("Activități", coerce=int)
    persoane = SelectMultipleField("Gestiuni", coerce=int)
    grupuri = SelectMultipleField("Grupuri", coerce=int)
    categorii = SelectMultipleField("Categorii", choices=[("MF", "Mijloace fixe"), ("OI", "Obiecte de inventar")])
    conturi = SelectMultipleField("Conturi sintetice")
    genereaza = SubmitField("Generează")

    def incarca_optiuni(self) -> None:
        self.locatii.choices = optiuni(Locatie, doar_active=False)
        self.activitati.choices = optiuni(Activitate, doar_active=False)
        self.persoane.choices = [(p.id, p.nume) for p in db.session.scalars(select(Persoana).order_by(Persoana.nume))]
        self.grupuri.choices = [(g.id, g.denumire) for g in db.session.scalars(select(Grup).order_by(Grup.denumire))]
        self.conturi.choices = [(s, s) for s in db.session.scalars(select(Cont.sintetic).distinct().order_by(Cont.sintetic))]

    def perimetru(self) -> Perimetru:
        return Perimetru(
            locatii=tuple(self.locatii.data or ()), activitati=tuple(self.activitati.data or ()),
            persoane=tuple(self.persoane.data or ()), grupuri=tuple(self.grupuri.data or ()),
            categorii=tuple(self.categorii.data or ()), conturi=tuple(self.conturi.data or ()),
        )


@bp.app_template_filter("perimetru")
def _filtru_perimetru(perimetru_json: str) -> str:
    return descriere(db.session, Perimetru.din_json(perimetru_json))


@bp.route("/inventare")
@login_required
def lista():
    inventare = db.session.scalars(select(Inventar).order_by(Inventar.data.desc(), Inventar.id.desc())).all()
    return render_template("inventare/lista.html", inventare=inventare)


@bp.route("/inventare/nou", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def nou():
    form = FormularInventar()
    form.incarca_optiuni()
    if request.method == "GET":
        form.data.data = date.today()
    mesaje: list[str] = []
    if form.validate_on_submit():
        perimetru = form.perimetru()
        mesaje = generare.avertismente(db.session, form.data.data, perimetru)
        # Avertismentele nu blochează, dar operatorul trebuie să le fi văzut înainte de generare.
        if not mesaje or request.form.get("confirmat") == "1":
            try:
                inventar = generare.genereaza(db.session, actor_curent(), form.data.data, perimetru)
            except EroareValidare as e:
                arata_eroare(e)
            else:
                flash(f"Inventarul a fost generat: {inventar.nr_linii} bunuri.", "success")
                return redirect(url_for(".detalii", inventar_id=inventar.id))
    return render_template("inventare/nou.html", form=form, avertismente=mesaje)


@bp.route("/inventare/<int:inventar_id>")
@login_required
def detalii(inventar_id: int):
    inventar = db.get_or_404(Inventar, inventar_id)
    # O listă = gestiune × cont sintetic × locație, în ordinea tirajului (§10.1).
    liste = db.session.execute(
        select(InventarLinie.locatie, InventarLinie.activitate, InventarLinie.gestiune, InventarLinie.titular,
               InventarLinie.categorie, InventarLinie.cont_sintetic, func.count(), func.sum(InventarLinie.pret),
               InventarLinie.persoana_id)
        .where(InventarLinie.inventar_id == inventar.id)
        .group_by(InventarLinie.locatie, InventarLinie.activitate, InventarLinie.persoana_id, InventarLinie.gestiune,
                  InventarLinie.titular, InventarLinie.categorie, InventarLinie.cont_sintetic)
        .order_by(InventarLinie.locatie, InventarLinie.activitate, InventarLinie.gestiune, InventarLinie.categorie,
                  InventarLinie.cont_sintetic)
    ).all()
    totaluri = db.session.execute(
        select(InventarLinie.categorie, func.count(), func.sum(InventarLinie.pret))
        .where(InventarLinie.inventar_id == inventar.id).group_by(InventarLinie.categorie)
        .order_by(InventarLinie.categorie)
    ).all()
    comisii = [(c.locatie, json.loads(c.membri_json)) for c in inventar.comisii]
    return render_template("inventare/detalii.html", inventar=inventar, liste=liste, totaluri=totaluri,
                           comisii=comisii, categorii=[t[0] for t in totaluri])


def _actiune(functie, mesaj: str, *args):
    try:
        functie(db.session, actor_curent(), *args)
    except EroareValidare as e:
        arata_eroare(e)
        return False
    flash(mesaj, "success")
    return True


@bp.route("/inventare/<int:inventar_id>/regenerare", methods=["POST"])
@rol_necesar("OPERATOR")
def regenerare(inventar_id: int):
    _actiune(generare.regenereaza, "Inventarul a fost regenerat.", inventar_id)
    return redirect(url_for(".detalii", inventar_id=inventar_id))


@bp.route("/inventare/<int:inventar_id>/blocare", methods=["POST"])
@rol_necesar("OPERATOR")
def blocare(inventar_id: int):
    _actiune(generare.blocheaza, "Inventarul a fost blocat.", inventar_id)
    return redirect(url_for(".detalii", inventar_id=inventar_id))


@bp.route("/inventare/<int:inventar_id>/deblocare", methods=["POST"])
@rol_necesar("ADMIN")
def deblocare(inventar_id: int):
    _actiune(generare.deblocheaza, "Inventarul a fost deblocat.", inventar_id, request.form.get("motiv", ""))
    return redirect(url_for(".detalii", inventar_id=inventar_id))


@bp.route("/inventare/<int:inventar_id>/stergere", methods=["POST"])
@rol_necesar("OPERATOR")
def stergere(inventar_id: int):
    if _actiune(generare.sterge, "Inventarul a fost șters.", inventar_id):
        return redirect(url_for(".lista"))
    return redirect(url_for(".detalii", inventar_id=inventar_id))


CHEI_FILTRU = ("locatii", "activitati", "persoane", "grupuri", "categorii", "conturi")


def filtru_din_cerere() -> Perimetru:
    a = request.args
    return Perimetru(
        locatii=tuple(a.getlist("locatii", type=int)), activitati=tuple(a.getlist("activitati", type=int)),
        persoane=tuple(a.getlist("persoane", type=int)), grupuri=tuple(a.getlist("grupuri", type=int)),
        categorii=tuple(c for c in a.getlist("categorii") if c in ("MF", "OI")),
        conturi=tuple(c for c in a.getlist("conturi") if c.isdigit()),
    )


def argumente_filtru() -> dict[str, list[str]]:
    """Parametrii filtrului din adresa curentă, ca să fie transmiși mai departe în legături."""
    return {k: v for k, v in request.args.to_dict(flat=False).items() if k in CHEI_FILTRU}


def _fisier(nume: str, continut: bytes, mime: str, atasament: bool):
    return send_file(BytesIO(continut), mimetype=mime, download_name=nume, as_attachment=atasament)


@bp.route("/inventare/<int:inventar_id>/listari")
@login_required
def listari(inventar_id: int):
    inventar = db.get_or_404(Inventar, inventar_id)
    filtru = filtru_din_cerere()

    def distincte(*coloane):
        return db.session.execute(select(*coloane).where(InventarLinie.inventar_id == inventar.id)
                                  .distinct().order_by(coloane[-1])).all()

    optiuni_filtru = {
        "locatii": distincte(InventarLinie.locatie_id, InventarLinie.locatie),
        "activitati": distincte(InventarLinie.activitate_id, InventarLinie.activitate),
        "persoane": distincte(InventarLinie.persoana_id, InventarLinie.gestiune),
        "grupuri": [(g.id, g.denumire) for g in db.session.scalars(select(Grup).order_by(Grup.denumire))],
        "categorii": [("MF", "Mijloace fixe"), ("OI", "Obiecte de inventar")],
        "conturi": [(c, c) for (c,) in distincte(InventarLinie.cont_sintetic)],
    }
    tip = request.args.get("centralizator")
    randuri = centralizator(db.session, inventar.id, tip, filtru) if tip in TIPURI_CENTRALIZATOR else None
    selectate = {k: set(request.args.getlist(k)) for k in CHEI_FILTRU}
    return render_template("inventare/listari.html", inventar=inventar, optiuni=optiuni_filtru, selectate=selectate,
                           argumente=argumente_filtru(), descriere_filtru=descriere(db.session, filtru),
                           tipuri=TIPURI_CENTRALIZATOR, tip=tip, randuri=randuri)


@bp.route("/inventare/<int:inventar_id>/pdf/<tip>/<categorie>")
@login_required
def pdf(inventar_id: int, tip: str, categorie: str):
    """tip: liste | inceput | sfarsit; filtrul din adresă sau ?persoana_id= pentru o singură gestiune."""
    persoana_id = request.args.get("persoana_id", type=int)
    try:
        if tip == "liste":
            nume, continut = tiparire.tipareste_liste(db.session, actor_curent(), inventar_id, categorie,
                                                      Path(current_app.instance_path), persoana_id,
                                                      filtru_din_cerere())
        else:
            nume, continut = tiparire.tipareste_declaratii(db.session, actor_curent(), inventar_id, categorie, tip,
                                                           persoana_id, filtru_din_cerere())
    except EroareValidare as e:
        arata_eroare(e)
        return redirect(request.referrer or url_for(".detalii", inventar_id=inventar_id))
    # Se deschide în browser (pentru tipărire); numele e cel din §10.4 dacă se salvează.
    return _fisier(nume, continut, "application/pdf", atasament=False)


@bp.route("/inventare/<int:inventar_id>/centralizator/<tip>.<format_>")
@login_required
def centralizator_fisier(inventar_id: int, tip: str, format_: str):
    try:
        nume, continut, mime = rapoarte.centralizator_fisier(db.session, actor_curent(), inventar_id, tip, format_,
                                                             filtru_din_cerere())
    except EroareValidare as e:
        arata_eroare(e)
        return redirect(request.referrer or url_for(".listari", inventar_id=inventar_id))
    return _fisier(nume, continut, mime, atasament=format_ != "pdf")


@bp.route("/inventare/<int:inventar_id>/export.<format_>")
@login_required
def export(inventar_id: int, format_: str):
    try:
        nume, continut, mime = rapoarte.export_linii(db.session, actor_curent(), inventar_id, format_,
                                                     filtru_din_cerere())
    except EroareValidare as e:
        arata_eroare(e)
        return redirect(request.referrer or url_for(".listari", inventar_id=inventar_id))
    return _fisier(nume, continut, mime, atasament=True)
