"""Sincronizarea anuală: încărcare export → raport → selecție → aplicare (§9.4)."""
import json
import secrets
import shutil
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from sqlalchemy import select
from wtforms import SubmitField
from wtforms.validators import DataRequired

from inventar import rapoarte
from inventar.domain.comun import EroareValidare
from inventar.extensions import db
from inventar.importuri import sincronizare as serviciu
from inventar.importuri.mf_baza import RezultatCitire, citeste_mf_baza
from inventar.models import Sincronizare
from inventar.web import actor_curent, arata_eroare, rol_necesar

bp = Blueprint("sincronizari", __name__)


class FormularSincronizare(FlaskForm):
    mf_baza = MultipleFileField("Exportul MF_BAZA (.xls) — mijloace fixe și obiecte de inventar",
                                validators=[DataRequired("Alegeți cel puțin un fișier.")])
    trimite = SubmitField("Încarcă și compară")


def _radacina() -> Path:
    return Path(current_app.instance_path) / "sincronizari"


def _citeste(director: str, fisiere: list[dict]) -> list[RezultatCitire]:
    return [citeste_mf_baza((_radacina() / director / f["salvat"]).read_bytes(), f["original"]) for f in fisiere]


@bp.route("/sincronizari")
@login_required
def lista():
    return _pagina_lista(FormularSincronizare())


def _pagina_lista(form: FormularSincronizare):
    sincronizari = db.session.scalars(select(Sincronizare).order_by(Sincronizare.id.desc())).all()
    return render_template("sincronizari/lista.html", form=form, sincronizari=sincronizari,
                           rezumate={s.id: json.loads(s.rezumat_json).get("diferente", {}) for s in sincronizari},
                           tipuri=serviciu.TIPURI)


@bp.route("/sincronizari/incarcare", methods=["POST"])
@rol_necesar("OPERATOR")
def incarcare():
    form = FormularSincronizare()
    if not form.validate_on_submit():
        return _pagina_lista(form)
    director = secrets.token_hex(16)
    cale = _radacina() / director
    cale.mkdir(parents=True)
    fisiere = []
    for i, fisier in enumerate(form.mf_baza.data):
        salvat = f"mf_{i}.xls"
        fisier.save(cale / salvat)
        original = (fisier.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip() or salvat
        fisiere.append({"original": original, "salvat": salvat})
    try:
        s = serviciu.incarca(db.session, actor_curent(), _citeste(director, fisiere), fisiere, director)
    except EroareValidare as e:
        shutil.rmtree(cale, ignore_errors=True)
        arata_eroare(e)
        return _pagina_lista(form)
    return redirect(url_for(".detalii", sincronizare_id=s.id))


@bp.route("/sincronizari/<int:sincronizare_id>")
@login_required
def detalii(sincronizare_id: int):
    s = db.get_or_404(Sincronizare, sincronizare_id)
    pe_tip: dict[str, list] = {tip: [] for tip in serviciu.TIPURI}
    for d in s.diferente:
        pe_tip[d.tip].append((d, serviciu.descriere_diferenta(d), serviciu.este_aplicabila(d)))
    rezumat = json.loads(s.rezumat_json)
    return render_template("sincronizari/detalii.html", s=s, pe_tip=pe_tip, tipuri=serviciu.TIPURI,
                           totaluri=rezumat.get("totaluri", []), fisiere=json.loads(s.fisier))


@bp.route("/sincronizari/<int:sincronizare_id>/aplicare", methods=["POST"])
@rol_necesar("OPERATOR")
def aplicare(sincronizare_id: int):
    s = db.get_or_404(Sincronizare, sincronizare_id)
    selectate = set(request.form.getlist("diferente", type=int))
    try:
        rezultat = serviciu.aplica(db.session, actor_curent(), s.id, _citeste(s.director, json.loads(s.fisier)),
                                   selectate)
    except EroareValidare as e:
        arata_eroare(e)
    else:
        aplicate = sum(rezultat["aplicate"].values())
        flash(f"Sincronizarea a fost aplicată: {aplicate} propuneri, {rezultat['documente_iesire']} documente de "
              "ieșire.", "success")
    return redirect(url_for(".detalii", sincronizare_id=sincronizare_id))


@bp.route("/sincronizari/<int:sincronizare_id>/abandonare", methods=["POST"])
@rol_necesar("OPERATOR")
def abandonare(sincronizare_id: int):
    try:
        serviciu.abandoneaza(db.session, actor_curent(), sincronizare_id)
    except EroareValidare as e:
        arata_eroare(e)
    else:
        flash("Sincronizarea a fost abandonată; nu s-a aplicat nimic.", "info")
    return redirect(url_for(".detalii", sincronizare_id=sincronizare_id))


@bp.route("/sincronizari/<int:sincronizare_id>/raport.<format_>")
@login_required
def raport(sincronizare_id: int, format_: str):
    try:
        nume, continut, mime = rapoarte.raport_sincronizare(db.session, actor_curent(), sincronizare_id, format_)
    except EroareValidare as e:
        arata_eroare(e)
        return redirect(url_for(".detalii", sincronizare_id=sincronizare_id))
    return send_file(BytesIO(continut), mimetype=mime, download_name=nume, as_attachment=format_ != "pdf")
