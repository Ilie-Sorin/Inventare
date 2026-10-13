"""Situația la o dată: cine are fiecare bun (§7.5).

Deținătorul unui bun la data D este `persoana_la_id` din ultima linie de document
VALIDAT cu data ≤ D, în ordinea (data, document.id). Null înseamnă că bunul a ieșit;
lipsa oricărei linii înseamnă că bunul e nerepartizat. Totul se calculează cu o
singură interogare (funcție fereastră), nu în buclă pe bunuri.
"""
from datetime import date
from typing import Iterable

from sqlalchemy import Select, Subquery, func, select
from sqlalchemy.orm import Session

from inventar.domain.incadrare import incadrari_la
from inventar.models import Bun, Document, LinieDocument

# Data folosită pentru „starea de acum, inclusiv documentele cu dată viitoare”.
ORICAND = date(9999, 12, 31)


def ultimele_miscari(data: date, bun_ids: Iterable[int] | None = None) -> Subquery:
    """Ultima linie validată ≤ data pentru fiecare bun: bun_id, persoana_id, data, document_id."""
    ordine = func.row_number().over(
        partition_by=LinieDocument.bun_id, order_by=(Document.data.desc(), Document.id.desc())
    )
    interogare = (
        select(
            LinieDocument.bun_id,
            LinieDocument.persoana_la_id.label("persoana_id"),
            Document.data,
            Document.id.label("document_id"),
            ordine.label("rn"),
        )
        .join(Document, Document.id == LinieDocument.document_id)
        .where(Document.stare == "VALIDAT", Document.data <= data)
    )
    if bun_ids is not None:
        interogare = interogare.where(LinieDocument.bun_id.in_(list(bun_ids)))
    numerotate = interogare.subquery()
    return (
        select(numerotate.c.bun_id, numerotate.c.persoana_id, numerotate.c.data, numerotate.c.document_id)
        .where(numerotate.c.rn == 1)
        .subquery()
    )


def situatia_la(data: date) -> Select:
    """Bunurile aflate la persoane la data D, cu locația și activitatea persoanei la D.

    Coloane: bun_id, persoana_id, locatie_id, activitate_id.
    """
    miscari = ultimele_miscari(data)
    incadrari = incadrari_la(data).subquery()
    return (
        select(miscari.c.bun_id, miscari.c.persoana_id, incadrari.c.locatie_id, incadrari.c.activitate_id)
        .outerjoin(incadrari, incadrari.c.persoana_id == miscari.c.persoana_id)
        .where(miscari.c.persoana_id.is_not(None))
    )


def detinatori_la(session: Session, data: date, bun_ids: Iterable[int]) -> dict[int, int | None]:
    """{bun_id: persoana_id sau None dacă a ieșit}; bunurile nerepartizate lipsesc din rezultat."""
    miscari = ultimele_miscari(data, bun_ids)
    return {r.bun_id: r.persoana_id for r in session.execute(select(miscari.c.bun_id, miscari.c.persoana_id))}


def bunuri_la_persoana(session: Session, persoana_id: int, data: date) -> list[Bun]:
    miscari = ultimele_miscari(data)
    return list(session.scalars(
        select(Bun).join(miscari, miscari.c.bun_id == Bun.id)
        .where(miscari.c.persoana_id == persoana_id)
        .order_by(Bun.categorie, Bun.nr_inventar)
    ))


def nerepartizate(session: Session, data: date) -> list[Bun]:
    """Bunuri fără nicio mișcare validată până la data D (inclusiv)."""
    miscari = ultimele_miscari(data)
    return list(session.scalars(
        select(Bun).outerjoin(miscari, miscari.c.bun_id == Bun.id)
        .where(miscari.c.bun_id.is_(None))
        .order_by(Bun.categorie, Bun.nr_inventar)
    ))


def are_bunuri(session: Session, persoana_id: int, data: date = ORICAND) -> int:
    miscari = ultimele_miscari(data)
    return session.scalar(select(func.count()).select_from(miscari).where(miscari.c.persoana_id == persoana_id))
