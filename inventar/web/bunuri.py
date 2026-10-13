"""Situația bunurilor la o dată și fișa bunului."""
from datetime import date

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, or_, select

from inventar.domain.incadrare import incadrari_la
from inventar.domain.stoc import detinatori_la, ultimele_miscari
from inventar.extensions import db
from inventar.models import Activitate, Bun, Cont, Document, LinieDocument, Locatie, Persoana
from inventar.web.formulare import optiuni

bp = Blueprint("bunuri", __name__)

PE_PAGINA = 100
STARI = {"la_persoane": "La persoane", "nerepartizate": "Nerepartizate", "iesite": "Ieșite", "toate": "Toate"}


@bp.route("/bunuri")
@login_required
def situatie():
    f = request.args
    data = f.get("data", type=date.fromisoformat) or date.today()
    stare = f.get("stare") if f.get("stare") in STARI else "la_persoane"
    pagina = max(f.get("pagina", 1, type=int), 1)

    miscari = ultimele_miscari(data)
    incadrari = incadrari_la(data).subquery()
    interogare = (
        select(Bun, Persoana, Locatie.denumire, Activitate.denumire)
        .join(Cont, Cont.id == Bun.cont_id)
        .outerjoin(miscari, miscari.c.bun_id == Bun.id)
        .outerjoin(Persoana, Persoana.id == miscari.c.persoana_id)
        .outerjoin(incadrari, incadrari.c.persoana_id == miscari.c.persoana_id)
        .outerjoin(Locatie, Locatie.id == incadrari.c.locatie_id)
        .outerjoin(Activitate, Activitate.id == incadrari.c.activitate_id)
    )
    if stare == "la_persoane":
        interogare = interogare.where(miscari.c.persoana_id.is_not(None))
    elif stare == "nerepartizate":
        interogare = interogare.where(miscari.c.bun_id.is_(None))
    elif stare == "iesite":
        interogare = interogare.where(miscari.c.bun_id.is_not(None), miscari.c.persoana_id.is_(None))
    if f.get("locatie_id", type=int):
        interogare = interogare.where(incadrari.c.locatie_id == f.get("locatie_id", type=int))
    if f.get("activitate_id", type=int):
        interogare = interogare.where(incadrari.c.activitate_id == f.get("activitate_id", type=int))
    if f.get("persoana_id", type=int):
        interogare = interogare.where(miscari.c.persoana_id == f.get("persoana_id", type=int))
    if f.get("categorie") in ("MF", "OI"):
        interogare = interogare.where(Bun.categorie == f.get("categorie"))
    if f.get("sintetic"):
        interogare = interogare.where(Cont.sintetic == f.get("sintetic"))
    if f.get("q", "").strip():
        text = f.get("q").strip()
        interogare = interogare.where(or_(Bun.nr_inventar == text, Bun.denumire.ilike(f"%{text}%")))

    filtrate = interogare.subquery()
    numar, valoare = db.session.execute(select(func.count(), func.coalesce(func.sum(filtrate.c.pret), 0))).one()
    randuri = db.session.execute(
        interogare.order_by(Persoana.nume, Bun.categorie, Cont.simbol, Bun.nr_inventar)
        .limit(PE_PAGINA).offset((pagina - 1) * PE_PAGINA)
    ).all()
    return render_template(
        "bunuri/situatie.html", randuri=randuri, numar=numar, valoare=valoare, data=data, stare=stare,
        stari=STARI, filtre=f, pagina=pagina, pagini=max((numar + PE_PAGINA - 1) // PE_PAGINA, 1),
        locatii=optiuni(Locatie, doar_active=False), activitati=optiuni(Activitate, doar_active=False),
        persoane=[(p.id, p.nume) for p in db.session.scalars(select(Persoana).order_by(Persoana.nume))],
        sintetice=list(db.session.scalars(select(Cont.sintetic).distinct().order_by(Cont.sintetic))),
    )


@bp.route("/bunuri/<int:bun_id>")
@login_required
def fisa(bun_id: int):
    bun = db.get_or_404(Bun, bun_id)
    azi = date.today()
    detinatori = detinatori_la(db.session, azi, [bun.id])
    detinator = db.session.get(Persoana, detinatori[bun.id]) if detinatori.get(bun.id) else None
    stare = "nerepartizat" if bun.id not in detinatori else ("iesit" if detinator is None else "la_persoana")
    istoric = db.session.execute(
        select(LinieDocument, Document).join(Document, Document.id == LinieDocument.document_id)
        .where(LinieDocument.bun_id == bun.id).order_by(Document.data, Document.id)
    ).all()
    return render_template("bunuri/fisa.html", bun=bun, detinator=detinator, stare=stare, istoric=istoric, azi=azi)
