"""Documentele de mișcare: listă, ciornă, validare, anulare."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import func, or_, select
from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Optional

from inventar.domain import documente
from inventar.domain.comun import EroareValidare
from inventar.domain.stoc import bunuri_la_persoana, nerepartizate
from inventar.extensions import db
from inventar.models import STARI_DOCUMENT, TIPURI_DOCUMENT, Bun, Document, LinieDocument, Persoana
from inventar.web import actor_curent, arata_eroare, este_htmx, rol_necesar
from inventar.web.formulare import OBLIGATORIU, zero_ca_none

bp = Blueprint("documente", __name__)

DENUMIRI_TIP = {"INITIAL": "Inițial", "INTRARE": "Intrare (repartizare)", "IESIRE": "Ieșire",
                "TRANSFER": "Transfer", "INCADRARE": "Schimbare încadrare"}
PE_PAGINA = 50


@bp.app_context_processor
def denumiri():
    return {"DENUMIRI_TIP": DENUMIRI_TIP, "MOTIVE_IESIRE": documente.MOTIVE_IESIRE}


class FormularDocument(FlaskForm):
    data = DateField("Data", validators=[DataRequired(OBLIGATORIU)])
    serie = StringField("Serie", validators=[Optional()])
    numar = StringField("Număr", validators=[DataRequired(OBLIGATORIU)])
    persoana_de_la_id = SelectField("Predă", coerce=int, default=0)
    persoana_la_id = SelectField("Primește", coerce=int, default=0)
    # Câmpul apare doar la ieșiri; la celelalte tipuri lipsește din formular, deci nu se
    # verifică aici. Motivul e validat în domeniu, unde e și regula.
    motiv_iesire = SelectField("Motivul ieșirii", choices=[("", "—")] + list(documente.MOTIVE_IESIRE.items()),
                               validate_choice=False)
    explicatie = TextAreaField("Explicație", validators=[Optional()], render_kw={"rows": 2})
    salveaza = SubmitField("Salvează ciorna")
    valideaza = SubmitField("Salvează și validează")


def _persoane_active() -> list[tuple[int, str]]:
    return [(0, "—")] + [(p.id, p.nume) for p in
                         db.session.scalars(select(Persoana).where(Persoana.activ.is_(True)).order_by(Persoana.nume))]


def _bunuri_disponibile(tip: str, data: date | None, de_la: int | None, selectate: list[int]) -> list[Bun]:
    """Bunurile din care se alege: nerepartizatele la INTRARE, ale predătorului altfel.
    Bunurile deja alese rămân în listă chiar dacă nu mai sunt disponibile (validarea le va semnala)."""
    disponibile: list[Bun] = []
    if data and tip == "INTRARE":
        disponibile = nerepartizate(db.session, data)
    elif data and de_la:
        disponibile = bunuri_la_persoana(db.session, de_la, data)
    ids = {b.id for b in disponibile}
    lipsa = [i for i in selectate if i not in ids]
    if lipsa:
        disponibile += list(db.session.scalars(select(Bun).where(Bun.id.in_(lipsa))))
    return disponibile


def _linii(tip: str, form: FormularDocument, bun_ids: list[int]) -> list[documente.LinieNoua]:
    de_la = zero_ca_none(form.persoana_de_la_id.data) if tip != "INTRARE" else None
    la = zero_ca_none(form.persoana_la_id.data) if tip != "IESIRE" else None
    return [documente.LinieNoua(bun_id, de_la, la) for bun_id in bun_ids]


@bp.route("/documente")
@login_required
def lista():
    tip, stare = request.args.get("tip", ""), request.args.get("stare", "")
    de_la = request.args.get("de_la", type=date.fromisoformat)
    pana_la = request.args.get("pana_la", type=date.fromisoformat)
    persoana_id = request.args.get("persoana_id", type=int)
    pagina = max(request.args.get("pagina", 1, type=int), 1)

    numar_linii = (select(func.count(LinieDocument.id)).where(LinieDocument.document_id == Document.id)
                   .correlate(Document).scalar_subquery())
    interogare = select(Document, numar_linii.label("linii")).order_by(Document.data.desc(), Document.id.desc())
    if tip in TIPURI_DOCUMENT:
        interogare = interogare.where(Document.tip == tip)
    if stare in STARI_DOCUMENT:
        interogare = interogare.where(Document.stare == stare)
    if de_la:
        interogare = interogare.where(Document.data >= de_la)
    if pana_la:
        interogare = interogare.where(Document.data <= pana_la)
    if persoana_id:
        interogare = interogare.where(Document.id.in_(select(LinieDocument.document_id).where(or_(
            LinieDocument.persoana_de_la_id == persoana_id, LinieDocument.persoana_la_id == persoana_id))))
    total = db.session.scalar(select(func.count()).select_from(interogare.subquery()))
    randuri = db.session.execute(interogare.limit(PE_PAGINA).offset((pagina - 1) * PE_PAGINA)).all()
    return render_template("documente/lista.html", randuri=randuri, total=total, pagina=pagina,
                           pagini=max((total + PE_PAGINA - 1) // PE_PAGINA, 1), filtre=request.args,
                           persoane=_persoane_active())


@bp.route("/documente/<int:document_id>")
@login_required
def vizualizare(document_id: int):
    document = db.get_or_404(Document, document_id)
    total = sum((linie.bun.pret for linie in document.linii), start=0)
    return render_template("documente/vizualizare.html", document=document, total=total)


@bp.route("/documente/nou/<tip>", methods=["GET", "POST"])
@bp.route("/documente/<int:document_id>/editare", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def formular(tip: str | None = None, document_id: int | None = None):
    document = db.get_or_404(Document, document_id) if document_id else None
    if document is not None:
        if document.stare != "CIORNA" or document.tip not in documente.TIPURI_MANUALE:
            abort(404)
        tip = document.tip
    if tip not in documente.TIPURI_MANUALE:
        abort(404)
    form = FormularDocument(obj=document)
    form.persoana_de_la_id.choices = form.persoana_la_id.choices = _persoane_active()

    if request.method == "GET":
        selectate = request.args.getlist("bun", type=int)
        if document is not None:
            selectate = [linie.bun_id for linie in document.linii]
            if document.linii:
                form.persoana_de_la_id.data = document.linii[0].persoana_de_la_id or 0
                form.persoana_la_id.data = document.linii[0].persoana_la_id or 0
            form.motiv_iesire.data = document.motiv_iesire or ""
        else:
            form.data.data = _data_propusa(tip, selectate)
            form.numar.data = documente.urmatorul_numar(db.session, tip, form.data.data.year)
            form.persoana_de_la_id.data = request.args.get("de_la", 0, type=int)
        if request.args.get("toate") and form.persoana_de_la_id.data:
            selectate = [b.id for b in bunuri_la_persoana(db.session, form.persoana_de_la_id.data, form.data.data)]
    else:
        selectate = request.form.getlist("bunuri", type=int)

    if form.validate_on_submit():
        salvat = None
        try:
            salvat = documente.salveaza_ciorna(
                db.session, actor_curent(), tip, form.data.data, form.numar.data, _linii(tip, form, selectate),
                document_id=document.id if document else None, serie=form.serie.data,
                explicatie=form.explicatie.data, motiv_iesire=form.motiv_iesire.data or None,
            )
            if form.valideaza.data:
                documente.valideaza(db.session, actor_curent(), salvat.id)
        except EroareValidare as e:
            arata_eroare(e)
            if salvat is not None:
                # Ciorna s-a salvat, doar validarea a eșuat: operatorul continuă din ciornă.
                return redirect(url_for(".vizualizare", document_id=salvat.id))
        else:
            flash("Document validat." if form.valideaza.data else "Ciornă salvată.", "success")
            return redirect(url_for(".vizualizare", document_id=salvat.id))

    disponibile = _bunuri_disponibile(tip, form.data.data, zero_ca_none(form.persoana_de_la_id.data), selectate)
    return render_template("documente/formular.html", form=form, tip=tip, document=document,
                           disponibile=disponibile, selectate=set(selectate))


def _data_propusa(tip: str, bun_ids: list[int]) -> date:
    """La repartizare se propune data documentului de intrare din contabilitate (`ddoc`)."""
    if tip == "INTRARE" and bun_ids:
        date_intrare = [d for d in db.session.scalars(select(Bun.data_doc_intrare).where(Bun.id.in_(bun_ids))) if d]
        initiala = documente.data_initiala(db.session)
        if date_intrare:
            propusa = max(date_intrare)
            return max(propusa, initiala) if initiala else propusa
    return date.today()


@bp.route("/documente/bunuri-disponibile")
@rol_necesar("OPERATOR")
def bunuri_disponibile():
    if not este_htmx():
        abort(404)
    tip = request.args.get("tip", "")
    data = request.args.get("data", type=date.fromisoformat)
    de_la = request.args.get("persoana_de_la_id", 0, type=int) or None
    selectate = request.args.getlist("bunuri", type=int)
    return render_template("documente/_bunuri.html", tip=tip, disponibile=_bunuri_disponibile(tip, data, de_la, selectate),
                           selectate=set(selectate))


@bp.route("/documente/<int:document_id>/validare", methods=["POST"])
@rol_necesar("OPERATOR")
def validare(document_id: int):
    try:
        documente.valideaza(db.session, actor_curent(), document_id)
    except EroareValidare as e:
        arata_eroare(e)
    else:
        flash("Document validat.", "success")
    return redirect(url_for(".vizualizare", document_id=document_id))


@bp.route("/documente/<int:document_id>/anulare", methods=["POST"])
@rol_necesar("OPERATOR")
def anulare(document_id: int):
    try:
        documente.anuleaza(db.session, actor_curent(), document_id, request.form.get("motiv", ""))
    except EroareValidare as e:
        arata_eroare(e)
    else:
        flash("Document anulat.", "success")
    return redirect(url_for(".vizualizare", document_id=document_id))
