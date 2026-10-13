"""Ecranele importului inițial: încărcare fișiere → raport → decizii → confirmare.

Fișierele încărcate se păstrează în instance/importuri/<token>/ între pași și
se recitesc la fiecare afișare, ca raportul să fie mereu calculat din aceleași date.
"""
import json
import re
import secrets
import shutil
import time
from datetime import date
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired, MultipleFileField
from sqlalchemy import select
from wtforms import DateField, SubmitField
from wtforms.validators import DataRequired

from inventar.domain.comun import EroareValidare
from inventar.extensions import db
from inventar.importuri import import_initial
from inventar.importuri.extras import citeste_extras
from inventar.importuri.mf_baza import citeste_mf_baza
from inventar.models import Document
from inventar.web import actor_curent, arata_eroare, rol_necesar
from inventar.web.formulare import OBLIGATORIU

bp = Blueprint("importuri", __name__)

_TOKEN = re.compile(r"^[0-9a-f]{32}$")
VALABILITATE_SECUNDE = 24 * 3600


class FormularImportInitial(FlaskForm):
    mf_baza = MultipleFileField("Exporturile MF_BAZA (.xls) — mijloace fixe și obiecte de inventar",
                                validators=[DataRequired("Alegeți cel puțin un fișier MF_BAZA.")])
    extras = FileField("Extrasul din aplicația existentă (.xlsx)",
                       validators=[FileRequired("Alegeți extrasul."), FileAllowed(["xlsx"], "Doar fișiere .xlsx.")])
    data_start = DateField("Data de start (data inventarului inițial)", validators=[DataRequired(OBLIGATORIU)])
    trimite = SubmitField("Încarcă și verifică")


def _nume_original(fisier) -> str:
    # Doar pentru afișare și jurnal; pe disc fișierele au nume generate de aplicație.
    return (fisier.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def _radacina() -> Path:
    return Path(current_app.instance_path) / "importuri"


def _curata_vechi() -> None:
    if not _radacina().exists():
        return
    for director in _radacina().iterdir():
        if director.is_dir() and time.time() - director.stat().st_mtime > VALABILITATE_SECUNDE:
            shutil.rmtree(director, ignore_errors=True)


def _director(token: str) -> tuple[Path, dict]:
    if not _TOKEN.match(token):
        abort(404)
    director = _radacina() / token
    meta_fisier = director / "meta.json"
    if not meta_fisier.exists():
        abort(404)
    meta = json.loads(meta_fisier.read_text(encoding="utf-8"))
    if meta["utilizator_id"] != current_user.id:
        abort(403)
    return director, meta


def _citeste(director: Path, meta: dict):
    exporturi = [citeste_mf_baza((director / f["salvat"]).read_bytes(), f["original"]) for f in meta["mf_baza"]]
    extras = citeste_extras((director / meta["extras"]["salvat"]).read_bytes(), meta["extras"]["original"])
    fisiere = [f["original"] for f in meta["mf_baza"]] + [meta["extras"]["original"]]
    return exporturi, extras, date.fromisoformat(meta["data_start"]), fisiere


def _import_facut() -> Document | None:
    return db.session.scalar(select(Document).where(Document.tip == "INITIAL"))


@bp.route("/importuri/initial", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def initial():
    document = _import_facut()
    form = FormularImportInitial()
    if document is None and form.validate_on_submit():
        _curata_vechi()
        token = secrets.token_hex(16)
        director = _radacina() / token
        director.mkdir(parents=True)
        meta = {"utilizator_id": current_user.id, "data_start": form.data_start.data.isoformat(), "mf_baza": []}
        for i, fisier in enumerate(form.mf_baza.data):
            salvat = f"mf_{i}.xls"
            fisier.save(director / salvat)
            meta["mf_baza"].append({"original": _nume_original(fisier) or salvat, "salvat": salvat})
        form.extras.data.save(director / "extras.xlsx")
        meta["extras"] = {"original": _nume_original(form.extras.data) or "extras.xlsx",
                          "salvat": "extras.xlsx"}
        (director / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return redirect(url_for(".raport", token=token))
    return render_template("importuri/initial.html", form=form, document=document)


@bp.route("/importuri/initial/<token>", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def raport(token: str):
    director, meta = _director(token)
    exporturi, extras, data_start, fisiere = _citeste(director, meta)
    decizii = {k[len("decizie_"):]: v for k, v in request.form.items() if k.startswith("decizie_")}

    if request.method == "POST" and request.form.get("actiune") == "confirma":
        try:
            document = import_initial.confirma(db.session, actor_curent(), exporturi, extras, data_start, decizii,
                                               fisiere)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            shutil.rmtree(director, ignore_errors=True)
            flash(f"Importul inițial a fost salvat: {len(document.linii)} bunuri repartizate la "
                  f"{document.data:%d.%m.%Y}.", "success")
            return redirect(url_for("persoane.lista"))

    rezultat = import_initial.analizeaza(db.session, exporturi, extras, data_start, decizii)
    return render_template("importuri/raport.html", raport=rezultat, decizii=decizii, data_start=data_start,
                           fisiere=fisiere, optiuni=import_initial.DECIZII, token=token)
