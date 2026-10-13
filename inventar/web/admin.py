"""Setări și utilizatori — doar pentru administrator."""
from datetime import date
from io import BytesIO
from pathlib import Path

from flask import (Blueprint, current_app, flash, redirect, render_template, request, send_file,
                   send_from_directory, url_for)
from flask_login import login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from sqlalchemy import select
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo

from inventar import utilizatori
from inventar.domain import consultare_jurnal
from inventar.domain.comun import EroareValidare
from inventar.domain.consultare_jurnal import FiltruJurnal
from inventar.domain.sabloane import SABLOANE, citeste_sablon, reseteaza_sablon, salveaza_sablon
from inventar.domain.setari import FISIER_SIGLA, SETARI, citeste_setari, salveaza_setari, salveaza_sigla
from inventar.extensions import db
from inventar.models import ROLURI, Persoana, Utilizator
from inventar.web import actor_curent, arata_eroare, rol_necesar
from inventar.web.formulare import OBLIGATORIU, zero_ca_none

bp = Blueprint("admin", __name__)


def director_sigla() -> Path:
    return Path(current_app.instance_path)


class FormularSigla(FlaskForm):
    sigla = FileField("Sigla (PNG sau JPG)", validators=[FileAllowed(["png", "jpg", "jpeg"], "Doar PNG sau JPG.")])
    incarca = SubmitField("Încarcă sigla")


@bp.route("/admin/setari", methods=["GET", "POST"])
@rol_necesar("ADMIN")
def setari():
    valori = citeste_setari(db.session)
    form_sigla = FormularSigla()
    if request.method == "POST" and "incarca" in request.form:
        if form_sigla.validate_on_submit() and form_sigla.sigla.data:
            try:
                salveaza_sigla(db.session, actor_curent(), form_sigla.sigla.data.read(), director_sigla())
            except EroareValidare as e:
                arata_eroare(e)
            else:
                flash("Sigla a fost încărcată.", "success")
                return redirect(url_for(".setari"))
        else:
            flash("Alegeți un fișier PNG sau JPG.", "danger")
    elif request.method == "POST":
        # Câmpurile de text au CSRF verificat global de CSRFProtect.
        noi = {s.cheie: request.form.get(s.cheie, "") for s in SETARI}
        try:
            salveaza_setari(db.session, actor_curent(), noi)
        except EroareValidare as e:
            arata_eroare(e)
            valori.update(noi)
        else:
            flash("Setările au fost salvate.", "success")
            return redirect(url_for(".setari"))
    return render_template("admin/setari.html", setari=SETARI, valori=valori, form_sigla=form_sigla)


@bp.route("/admin/sigla")
@login_required
def sigla():
    return send_from_directory(director_sigla(), FISIER_SIGLA, max_age=0)


class FormularUtilizatorNou(FlaskForm):
    username = StringField("Utilizator", validators=[DataRequired(OBLIGATORIU)])
    rol = SelectField("Rol", choices=[(r, r) for r in ROLURI])
    parola = PasswordField("Parolă", validators=[DataRequired(OBLIGATORIU)])
    confirmare = PasswordField("Confirmare parolă", validators=[EqualTo("parola", "Parolele nu coincid.")])
    trimite = SubmitField("Creează")


class FormularUtilizator(FlaskForm):
    rol = SelectField("Rol", choices=[(r, r) for r in ROLURI])
    activ = BooleanField("Activ")
    persoana_id = SelectField("Persoana asociată (opțional)", coerce=int, default=0)
    trimite = SubmitField("Salvează")


class FormularParolaNoua(FlaskForm):
    parola = PasswordField("Parolă nouă", validators=[DataRequired(OBLIGATORIU)])
    confirmare = PasswordField("Confirmare", validators=[EqualTo("parola", "Parolele nu coincid.")])
    reseteaza = SubmitField("Resetează parola")


@bp.route("/admin/utilizatori")
@rol_necesar("ADMIN")
def lista_utilizatori():
    return render_template("admin/utilizatori.html",
                           utilizatori=db.session.scalars(select(Utilizator).order_by(Utilizator.username)).all())


@bp.route("/admin/utilizatori/nou", methods=["GET", "POST"])
@rol_necesar("ADMIN")
def utilizator_nou():
    form = FormularUtilizatorNou()
    if form.validate_on_submit():
        try:
            utilizatori.creeaza_utilizator(db.session, actor_curent(), form.username.data, form.parola.data,
                                           form.rol.data)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Utilizator creat.", "success")
            return redirect(url_for(".lista_utilizatori"))
    return render_template("admin/utilizator_nou.html", form=form)


@bp.route("/admin/utilizatori/<int:utilizator_id>", methods=["GET", "POST"])
@rol_necesar("ADMIN")
def utilizator(utilizator_id: int):
    u = db.get_or_404(Utilizator, utilizator_id)
    form = FormularUtilizator(obj=u, prefix="u")
    form_parola = FormularParolaNoua(prefix="p")
    form.persoana_id.choices = [(0, "—")] + [
        (p.id, p.nume) for p in db.session.scalars(select(Persoana).order_by(Persoana.nume))
    ]
    if request.method == "GET":
        form.persoana_id.data = u.persoana_id or 0
    if form.trimite.data and form.validate_on_submit():
        try:
            utilizatori.modifica_utilizator(db.session, actor_curent(), u.id, form.rol.data, form.activ.data,
                                            zero_ca_none(form.persoana_id.data))
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Salvat.", "success")
            return redirect(url_for(".lista_utilizatori"))
    if form_parola.reseteaza.data and form_parola.validate_on_submit():
        try:
            utilizatori.reseteaza_parola(db.session, actor_curent(), u.id, form_parola.parola.data)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Parola a fost resetată.", "success")
            return redirect(url_for(".lista_utilizatori"))
    return render_template("admin/utilizator.html", u=u, form=form, form_parola=form_parola)


@bp.route("/admin/sabloane", methods=["GET", "POST"])
@rol_necesar("ADMIN")
def sabloane():
    if request.method == "POST":
        cod = request.form.get("cod", "")
        try:
            if request.form.get("actiune") == "reseteaza":
                reseteaza_sablon(db.session, actor_curent(), cod)
            else:
                salveaza_sablon(db.session, actor_curent(), cod, request.form.get("subiect") or None,
                                request.form.get("corp", ""))
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Șablonul a fost salvat.", "success")
            return redirect(url_for(".sabloane"))
    valori = {cod: citeste_sablon(db.session, cod) for cod in SABLOANE}
    return render_template("admin/sabloane.html", sabloane=SABLOANE, valori=valori)


def _filtru_jurnal() -> FiltruJurnal:
    a = request.args
    return FiltruJurnal(
        de_la=a.get("de_la", type=date.fromisoformat), pana_la=a.get("pana_la", type=date.fromisoformat),
        username=a.get("username", "").strip(), actiune=a.get("actiune", "").strip(),
        rezultat=a.get("rezultat", "").strip(), text=a.get("text", "").strip(),
    )


@bp.route("/admin/jurnal")
@rol_necesar("ADMIN")
def jurnal_actiuni():
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    randuri, total = consultare_jurnal.cauta(db.session, actor_curent(), _filtru_jurnal(), pagina)
    return render_template("admin/jurnal.html", randuri=randuri, total=total, pagina=pagina,
                           pagini=max((total + 99) // 100, 1), filtre=request.args,
                           optiuni=consultare_jurnal.optiuni(db.session))


@bp.route("/admin/jurnal.csv")
@rol_necesar("ADMIN")
def jurnal_csv():
    continut = consultare_jurnal.export_csv(db.session, actor_curent(), _filtru_jurnal())
    return send_file(BytesIO(continut), mimetype="text/csv; charset=utf-8", as_attachment=True,
                     download_name=f"Jurnal_{date.today().isoformat()}.csv")
