from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo

from inventar import utilizatori
from inventar.domain.comun import EroareValidare
from inventar.extensions import db
from inventar.web import actor_curent, arata_eroare

bp = Blueprint("auth", __name__)


class FormularAutentificare(FlaskForm):
    username = StringField("Utilizator", validators=[DataRequired(message="Completați utilizatorul.")])
    parola = PasswordField("Parolă", validators=[DataRequired(message="Completați parola.")])
    trimite = SubmitField("Autentificare")


def _destinatie_sigura(urmator: str | None) -> str:
    # Se acceptă doar căi relative din aplicație, ca să nu poată fi folosită
    # pagina de login pentru redirecționări spre alte site-uri.
    if urmator and urmator.startswith("/") and not urlsplit(urmator).netloc and not urmator.startswith("//"):
        return urmator
    return url_for("principal.acasa")


@bp.route("/autentificare", methods=["GET", "POST"])
def autentificare():
    form = FormularAutentificare()
    if form.validate_on_submit():
        utilizator = utilizatori.autentifica(db.session, form.username.data, form.parola.data, request.remote_addr)
        if utilizator:
            session.clear()
            session.permanent = True
            login_user(utilizator)
            return redirect(_destinatie_sigura(request.args.get("next")))
        flash("Utilizator sau parolă greșită.", "danger")
    return render_template("auth/autentificare.html", form=form)


@bp.route("/deconectare", methods=["POST"])
@login_required
def deconectare():
    utilizatori.deconecteaza(db.session, actor_curent())
    logout_user()
    session.clear()
    flash("V-ați deconectat.", "info")
    return redirect(url_for("auth.autentificare"))


class FormularParolaProprie(FlaskForm):
    parola_veche = PasswordField("Parola actuală", validators=[DataRequired(message="Câmp obligatoriu.")])
    parola_noua = PasswordField("Parola nouă", validators=[DataRequired(message="Câmp obligatoriu.")])
    confirmare = PasswordField("Confirmare", validators=[EqualTo("parola_noua", "Parolele nu coincid.")])
    trimite = SubmitField("Schimbă parola")


@bp.route("/cont/parola", methods=["GET", "POST"])
@login_required
def parola():
    form = FormularParolaProprie()
    if form.validate_on_submit():
        try:
            utilizatori.schimba_parola_proprie(db.session, actor_curent(), form.parola_veche.data,
                                               form.parola_noua.data)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            flash("Parola a fost schimbată.", "success")
            return redirect(url_for("principal.acasa"))
    return render_template("auth/parola.html", form=form)
