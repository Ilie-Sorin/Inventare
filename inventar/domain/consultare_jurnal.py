"""Consultarea jurnalului de acțiuni (§11): doar citire, filtre și export CSV."""
import csv
from dataclasses import dataclass
from datetime import date, datetime, time
from io import StringIO

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.drepturi import Actor, cere_rol
from inventar.models import Jurnal


@dataclass(frozen=True)
class FiltruJurnal:
    de_la: date | None = None
    pana_la: date | None = None
    username: str = ""
    actiune: str = ""
    rezultat: str = ""   # OK | ESEC | EROARE
    text: str = ""       # caută în obiect și detalii


def _interogare(f: FiltruJurnal) -> Select:
    q = select(Jurnal)
    if f.de_la:
        q = q.where(Jurnal.la >= datetime.combine(f.de_la, time.min))
    if f.pana_la:
        q = q.where(Jurnal.la <= datetime.combine(f.pana_la, time.max))
    if f.username:
        q = q.where(Jurnal.username == f.username)
    if f.actiune:
        q = q.where(Jurnal.actiune == f.actiune)
    if f.rezultat:
        q = q.where(Jurnal.rezultat == f.rezultat)
    if f.text:
        q = q.where(or_(Jurnal.detalii_json.contains(f.text), Jurnal.obiect_tip.contains(f.text),
                        Jurnal.ip.contains(f.text)))
    return q


def cauta(session: Session, actor: Actor, f: FiltruJurnal, pagina: int, pe_pagina: int = 100) -> tuple[list[Jurnal], int]:
    cere_rol(actor, "ADMIN")
    q = _interogare(f)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    randuri = session.scalars(q.order_by(Jurnal.id.desc()).limit(pe_pagina).offset((pagina - 1) * pe_pagina)).all()
    return list(randuri), total


def optiuni(session: Session) -> dict[str, list[str]]:
    return {
        "actiuni": list(session.scalars(select(Jurnal.actiune).distinct().order_by(Jurnal.actiune))),
        "utilizatori": list(session.scalars(select(Jurnal.username).distinct().order_by(Jurnal.username))),
    }


def export_csv(session: Session, actor: Actor, f: FiltruJurnal) -> bytes:
    """Exportul se înregistrează și el în jurnal (cine a scos jurnalul și cu ce filtru)."""
    cere_rol(actor, "ADMIN")
    text = StringIO()
    scriitor = csv.writer(text, delimiter=";", lineterminator="\r\n")
    scriitor.writerow(["Nr.", "Data și ora", "Utilizator", "IP", "Acțiune", "Obiect", "Id obiect", "Rezultat", "Detalii"])
    numar = 0
    for j in session.scalars(_interogare(f).order_by(Jurnal.id)):
        scriitor.writerow([j.id, j.la.strftime("%d.%m.%Y %H:%M:%S"), j.username, j.ip or "", j.actiune,
                           j.obiect_tip or "", j.obiect_id or "", j.rezultat, j.detalii_json])
        numar += 1
    jurnal.scrie(session, actor, "EXPORT_JURNAL", detalii={"filtru": f.__dict__, "randuri": numar})
    session.commit()
    return text.getvalue().encode("utf-8-sig")
