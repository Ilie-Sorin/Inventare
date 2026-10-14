"""Marcarea inventarelor afectate de o modificare a trecutului (§7.4 regula 6, §9.4).

Separat de `generare`, ca documentele și încadrările să-l poată folosi fără importuri circulare.
Toate funcțiile rulează fără commit, în tranzacția modificării care a produs schimbarea; inventarele
BLOCAT (semnate) rămân neatinse.
"""
from datetime import date

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.drepturi import Actor
from inventar.models import Inventar, InventarLinie


def marcheaza_inventare(session: Session, actor: Actor, inventare: list[int], motiv: str,
                        **detalii) -> list[int]:
    """Dintre inventarele date, cele GENERAT devin NEACTUALIZAT."""
    afectate = list(session.scalars(
        select(Inventar.id).where(Inventar.id.in_(inventare), Inventar.stare == "GENERAT").order_by(Inventar.id)
    )) if inventare else []
    if afectate:
        session.execute(update(Inventar).where(Inventar.id.in_(afectate)).values(stare="NEACTUALIZAT"),
                        execution_options={"synchronize_session": "fetch"})
        jurnal.scrie(session, actor, "INVENTAR_NEACTUALIZAT",
                     detalii={"inventare": afectate, "motiv": motiv, **detalii})
    return afectate


def marcheaza_neactualizate(session: Session, actor: Actor, data: date, motiv: str) -> list[int]:
    """Inventarele GENERAT cu data ≥ `data` (documentele schimbă situația de la data lor încolo)."""
    inventare = list(session.scalars(select(Inventar.id).where(Inventar.stare == "GENERAT", Inventar.data >= data)))
    return marcheaza_inventare(session, actor, inventare, motiv, de_la_data=data)


def marcheaza_cu_linii(session: Session, actor: Actor, motiv: str, *conditii) -> list[int]:
    """Inventarele care au în instantaneu linii potrivite (de ex. gestiunea redenumită).

    Numele din instantaneu (gestiune, titular, locație, activitate) ajung pe liste, deci o redenumire
    face lista veche greșită, chiar dacă situația bunurilor nu s-a schimbat.
    """
    inventare = list(session.scalars(
        select(InventarLinie.inventar_id).join(Inventar, Inventar.id == InventarLinie.inventar_id)
        .where(Inventar.stare == "GENERAT", or_(*conditii)).distinct()
    ))
    return marcheaza_inventare(session, actor, inventare, motiv)
