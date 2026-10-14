"""Persoane / gestiuni și încadrările lor."""
import json
from datetime import date
from decimal import Decimal
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from sqlalchemy import or_, select
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Optional

from inventar.domain import incadrare as serviciu_incadrare
from inventar.domain import persoane
from inventar.domain.comun import EroareValidare
from inventar.domain.incadrare import incadrari_la, ultima_incadrare
from inventar.domain.normalizare import cheie_nume
from inventar.domain.schimbare_incadrare import destinatari_predare, schimba_incadrarea
from inventar.domain.stoc import bunuri_la_persoana
from inventar.extensions import db
from inventar.importuri import email_persoane
from inventar.models import Activitate, Document, Incadrare, LinieDocument, Locatie, Persoana
from inventar.web import actor_curent, arata_eroare, este_htmx, rol_necesar
from inventar.web.formulare import OBLIGATORIU, FormularIncadrare, optiuni, zero_ca_none

bp = Blueprint("persoane", __name__)


def _optiuni_titular(persoana: Persoana | None) -> list[tuple[int, str]]:
    interogare = select(Persoana).where(Persoana.titular_id.is_(None), Persoana.activ.is_(True))
    if persoana is not None:
        interogare = interogare.where(Persoana.id != persoana.id)
    return [(0, "— fără titular —")] + [(p.id, p.nume) for p in db.session.scalars(interogare.order_by(Persoana.nume))]


class FormularPersoana(FlaskForm):
    nume = StringField("Nume gestiune", validators=[DataRequired(OBLIGATORIU)])
    marca = StringField("Marcă", validators=[Optional()])
    email = StringField("E-mail", validators=[Optional()])
    titular_id = SelectField("Titular (doar pentru gestiuni secundare)", coerce=int, default=0)
    trimite = SubmitField("Salvează")


class FormularEmailuri(FlaskForm):
    fisier = FileField("Fișierul Excel completat (.xlsx)",
                       validators=[FileRequired("Alegeți un fișier."), FileAllowed(["xlsx"], "Doar fișiere .xlsx.")])
    trimite = SubmitField("Încarcă și compară")


class FormularPersoanaNoua(FormularPersoana, FormularIncadrare):
    pass


@bp.route("/persoane")
@login_required
def lista():
    q = request.args.get("q", "").strip()
    stare = request.args.get("stare", "active")
    locatie_id = request.args.get("locatie_id", type=int)
    activitate_id = request.args.get("activitate_id", type=int)

    curente = incadrari_la(date.today()).subquery()
    interogare = (
        select(Persoana, Locatie.denumire, Activitate.denumire)
        .outerjoin(curente, curente.c.persoana_id == Persoana.id)
        .outerjoin(Locatie, Locatie.id == curente.c.locatie_id)
        .outerjoin(Activitate, Activitate.id == curente.c.activitate_id)
        .order_by(Persoana.nume)
    )
    if stare == "active":
        interogare = interogare.where(Persoana.activ.is_(True))
    elif stare == "inactive":
        interogare = interogare.where(Persoana.activ.is_(False))
    if locatie_id:
        interogare = interogare.where(curente.c.locatie_id == locatie_id)
    if activitate_id:
        interogare = interogare.where(curente.c.activitate_id == activitate_id)
    randuri = db.session.execute(interogare).all()
    if q:
        # Căutarea ignoră majusculele și diacriticele (inclusiv ş/ţ cu sedilă).
        cheie = cheie_nume(q)
        randuri = [r for r in randuri if cheie in cheie_nume(r[0].nume)]

    sablon = "persoane/_tabel.html" if este_htmx() else "persoane/lista.html"
    return render_template(sablon, randuri=randuri, q=q, stare=stare, locatie_id=locatie_id,
                           activitate_id=activitate_id, locatii=optiuni(Locatie, doar_active=False),
                           activitati=optiuni(Activitate, doar_active=False))


@bp.route("/persoane/<int:persoana_id>")
@login_required
def fisa(persoana_id: int):
    persoana = db.get_or_404(Persoana, persoana_id)
    ultima = ultima_incadrare(db.session, persoana.id)
    azi = date.today()
    bunuri = bunuri_la_persoana(db.session, persoana.id, azi)
    documente_recente = db.session.scalars(
        select(Document).where(Document.id.in_(select(LinieDocument.document_id).where(or_(
            LinieDocument.persoana_de_la_id == persoana.id, LinieDocument.persoana_la_id == persoana.id))))
        .order_by(Document.data.desc(), Document.id.desc()).limit(20)
    ).all()
    return render_template("persoane/fisa.html", persoana=persoana, ultima=ultima, azi=azi, bunuri=bunuri,
                           total=sum((b.pret for b in bunuri), start=Decimal("0")),
                           incadrari=list(reversed(persoana.incadrari)), documente=documente_recente)


@bp.route("/persoane/nou", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def nou():
    form = FormularPersoanaNoua()
    form.titular_id.choices = _optiuni_titular(None)
    form.incarca_optiuni()
    if request.method == "GET":
        form.valabil_de_la.data = date.today()
    if form.validate_on_submit():
        try:
            p = persoane.creeaza_persoana(
                db.session, actor_curent(), form.nume.data, form.marca.data, form.email.data,
                zero_ca_none(form.titular_id.data), form.locatie_id.data, form.activitate_id.data,
                form.valabil_de_la.data,
            )
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Persoană creată.", "success")
            return redirect(url_for(".fisa", persoana_id=p.id))
    return render_template("persoane/editare.html", form=form, persoana=None)


@bp.route("/persoane/<int:persoana_id>/editare", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def editare(persoana_id: int):
    persoana = db.get_or_404(Persoana, persoana_id)
    form = FormularPersoana(obj=persoana)
    form.titular_id.choices = _optiuni_titular(persoana)
    if request.method == "GET":
        form.titular_id.data = persoana.titular_id or 0
    if form.validate_on_submit():
        try:
            persoane.modifica_persoana(db.session, actor_curent(), persoana.id, form.nume.data, form.marca.data,
                                       form.email.data, zero_ca_none(form.titular_id.data))
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Salvat.", "success")
            return redirect(url_for(".fisa", persoana_id=persoana.id))
    return render_template("persoane/editare.html", form=form, persoana=persoana)


@bp.route("/persoane/<int:persoana_id>/activ", methods=["POST"])
@rol_necesar("OPERATOR")
def comuta_activ(persoana_id: int):
    persoana = db.get_or_404(Persoana, persoana_id)
    try:
        persoane.seteaza_activ_persoana(db.session, actor_curent(), persoana.id, not persoana.activ)
    except EroareValidare as e:
        arata_eroare(e)
    return redirect(url_for(".fisa", persoana_id=persoana_id))


@bp.route("/persoane/<int:persoana_id>/incadrare", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def incadrare_noua(persoana_id: int):
    """Asistentul de schimbare a încadrării: bunurile persoanei o urmează sau se predau."""
    persoana = db.get_or_404(Persoana, persoana_id)
    form = FormularIncadrare()
    form.incarca_optiuni()
    if request.method == "GET":
        form.valabil_de_la.data = date.today()
    data = form.valabil_de_la.data
    predari = {int(k[len("predare_"):]): int(v) for k, v in request.form.items()
               if k.startswith("predare_") and v.isdigit()}

    if request.form.get("actiune") == "executa" and form.validate_on_submit():
        try:
            schimba_incadrarea(db.session, actor_curent(), persoana.id, form.locatie_id.data,
                               form.activitate_id.data, data, form.motiv.data, predari)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash(f"Încadrarea a fost schimbată; {len(predari)} bunuri au fost predate.", "success")
            return redirect(url_for(".fisa", persoana_id=persoana.id))

    bunuri = bunuri_la_persoana(db.session, persoana.id, data) if data else []
    destinatari = destinatari_predare(db.session, persoana.id, data) if data else []
    return render_template("persoane/incadrare.html", form=form, persoana=persoana, incadrare=None,
                           bunuri=bunuri, destinatari=destinatari, predari=predari)


@bp.route("/incadrari/<int:incadrare_id>/corectare", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def corectare_incadrare(incadrare_id: int):
    incadrare = db.get_or_404(Incadrare, incadrare_id)
    form = FormularIncadrare(obj=incadrare)
    form.incarca_optiuni(incadrare.locatie_id, incadrare.activitate_id)
    if form.validate_on_submit():
        try:
            serviciu_incadrare.corecteaza_ultima_incadrare(
                db.session, actor_curent(), incadrare.id, form.locatie_id.data, form.activitate_id.data,
                form.valabil_de_la.data, form.motiv.data,
            )
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Încadrare corectată.", "success")
            return redirect(url_for(".fisa", persoana_id=incadrare.persoana_id))
    return render_template("persoane/incadrare.html", form=form, persoana=incadrare.persoana, incadrare=incadrare)


@bp.route("/persoane/email")
@login_required
def email_pagina():
    return render_template("persoane/email.html", form=FormularEmailuri(), analiza=None)


@bp.route("/persoane/email/export.xlsx")
@login_required
def email_export():
    continut = email_persoane.exporta(db.session, actor_curent(), include_inactive=request.args.get("inactive") == "1")
    return send_file(BytesIO(continut), as_attachment=True, download_name=f"emailuri_{date.today():%Y-%m-%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/persoane/email/previzualizare", methods=["POST"])
@rol_necesar("OPERATOR")
def email_previzualizare():
    form = FormularEmailuri()
    if not form.validate_on_submit():
        return render_template("persoane/email.html", form=form, analiza=None)
    try:
        analiza = email_persoane.analizeaza(db.session, actor_curent(), form.fisier.data.read())
    except EroareValidare as e:
        arata_eroare(e)
        return render_template("persoane/email.html", form=form, analiza=None)
    # Fișierul nu se păstrează: la confirmare se trimit doar schimbările de aplicat, care se reverifică.
    schimbari = json.dumps({s.persoana_id: s.nou for s in analiza.schimbari})
    return render_template("persoane/email.html", form=FormularEmailuri(), analiza=analiza, schimbari=schimbari)


@bp.route("/persoane/email/aplicare", methods=["POST"])
@rol_necesar("OPERATOR")
def email_aplicare():
    try:
        schimbari = {int(k): str(v) for k, v in json.loads(request.form.get("schimbari", "{}")).items()}
        n = email_persoane.aplica(db.session, actor_curent(), schimbari)
    except (ValueError, AttributeError):
        flash("Datele de confirmare nu sunt valide; încărcați din nou fișierul.", "danger")
    except EroareValidare as e:
        arata_eroare(e)
    else:
        flash(f"Adrese de e-mail actualizate: {n}.", "success")
        return redirect(url_for(".lista"))
    return redirect(url_for(".email_pagina"))
