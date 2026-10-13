"""Încadrarea (locație + activitate) a unei persoane, cu istoric (§7.2)."""
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.neactualizare import marcheaza_neactualizate
from inventar.domain.comun import EroareValidare, aplica_modificari, text_optional
from inventar.drepturi import Actor, cere_rol
from inventar.models import Activitate, Incadrare, Locatie


def incadrare_la(session: Session, persoana_id: int, data: date) -> Incadrare | None:
    """Încadrarea valabilă la `data`: cea mai recentă cu valabil_de_la ≤ data."""
    return session.scalar(
        select(Incadrare)
        .where(Incadrare.persoana_id == persoana_id, Incadrare.valabil_de_la <= data)
        .order_by(Incadrare.valabil_de_la.desc())
        .limit(1)
    )


def incadrari_la(data: date) -> Select:
    """Subinterogare cu încadrarea valabilă la `data` pentru toate persoanele.

    O singură interogare (funcție fereastră), nu o buclă pe persoane: se
    folosește în listări și, mai târziu, la calculul stocului și la generare.
    Coloane: persoana_id, locatie_id, activitate_id, valabil_de_la.
    """
    numerotate = (
        select(
            Incadrare.persoana_id,
            Incadrare.locatie_id,
            Incadrare.activitate_id,
            Incadrare.valabil_de_la,
            func.row_number()
            .over(partition_by=Incadrare.persoana_id, order_by=Incadrare.valabil_de_la.desc())
            .label("rn"),
        )
        .where(Incadrare.valabil_de_la <= data)
        .subquery()
    )
    return select(
        numerotate.c.persoana_id,
        numerotate.c.locatie_id,
        numerotate.c.activitate_id,
        numerotate.c.valabil_de_la,
    ).where(numerotate.c.rn == 1)


def ultima_incadrare(session: Session, persoana_id: int) -> Incadrare | None:
    return session.scalar(
        select(Incadrare)
        .where(Incadrare.persoana_id == persoana_id)
        .order_by(Incadrare.valabil_de_la.desc())
        .limit(1)
    )


def _verifica_nomenclatoare(session: Session, locatie_id: int, activitate_id: int) -> None:
    locatie = session.get(Locatie, locatie_id)
    if locatie is None or not locatie.activ:
        raise EroareValidare("Locația aleasă nu există sau este inactivă.")
    activitate = session.get(Activitate, activitate_id)
    if activitate is None or not activitate.activ:
        raise EroareValidare("Activitatea aleasă nu există sau este inactivă.")


def creeaza_incadrare(
    session: Session, persoana_id: int, locatie_id: int, activitate_id: int, valabil_de_la: date,
    motiv: str | None = None, document_id: int | None = None,
) -> Incadrare:
    """Fără commit și fără jurnal: folosită din servicii care le fac ele (creare persoană, import)."""
    _verifica_nomenclatoare(session, locatie_id, activitate_id)
    ultima = ultima_incadrare(session, persoana_id)
    # Doar adăugare la capătul istoricului: o încadrare inserată în trecut ar
    # schimba retroactiv locația din inventarele deja făcute.
    if ultima and valabil_de_la <= ultima.valabil_de_la:
        raise EroareValidare(
            f"Noua încadrare trebuie să înceapă după {ultima.valabil_de_la:%d.%m.%Y} "
            "(data ultimei încadrări)."
        )
    if ultima and (ultima.locatie_id, ultima.activitate_id) == (locatie_id, activitate_id):
        raise EroareValidare("Persoana are deja această locație și activitate.")
    incadrare = Incadrare(
        persoana_id=persoana_id, locatie_id=locatie_id, activitate_id=activitate_id,
        valabil_de_la=valabil_de_la, motiv=text_optional(motiv), document_id=document_id,
    )
    session.add(incadrare)
    session.flush()
    return incadrare


def corecteaza_ultima_incadrare(
    session: Session, actor: Actor, incadrare_id: int, locatie_id: int, activitate_id: int,
    valabil_de_la: date, motiv: str | None,
) -> Incadrare:
    """Corectează o greșeală de introducere; doar ultima încadrare, ca istoricul anterior să rămână neatins."""
    cere_rol(actor, "OPERATOR")
    incadrare = session.get(Incadrare, incadrare_id)
    if incadrare is None:
        raise EroareValidare("Încadrarea nu există.")
    if incadrare.document_id is not None:
        raise EroareValidare("Încadrarea provine dintr-un document de schimbare a încadrării; "
                             "pentru corectare anulați documentul și refaceți schimbarea.")
    ultima = ultima_incadrare(session, incadrare.persoana_id)
    if ultima is None or ultima.id != incadrare.id:
        raise EroareValidare("Se poate corecta doar ultima încadrare a persoanei.")
    precedenta = session.scalar(
        select(Incadrare)
        .where(Incadrare.persoana_id == incadrare.persoana_id, Incadrare.id != incadrare.id)
        .order_by(Incadrare.valabil_de_la.desc())
        .limit(1)
    )
    if precedenta and valabil_de_la <= precedenta.valabil_de_la:
        raise EroareValidare(
            f"Data trebuie să fie după {precedenta.valabil_de_la:%d.%m.%Y} (încadrarea anterioară)."
        )
    if (locatie_id, activitate_id) != (incadrare.locatie_id, incadrare.activitate_id):
        _verifica_nomenclatoare(session, locatie_id, activitate_id)
    data_veche = incadrare.valabil_de_la
    schimbari = aplica_modificari(incadrare, {
        "locatie_id": locatie_id, "activitate_id": activitate_id,
        "valabil_de_la": valabil_de_la, "motiv": text_optional(motiv),
    })
    if schimbari:
        jurnal.scrie(session, actor, "INCADRARE_CORECTATA", "incadrare", incadrare.id,
                     {"persoana_id": incadrare.persoana_id, **schimbari})
        # Locația și activitatea se schimbă retroactiv de la cea mai veche dintre cele două date.
        marcheaza_neactualizate(session, actor, min(data_veche, valabil_de_la), "corectare încadrare")
    session.commit()
    return incadrare
