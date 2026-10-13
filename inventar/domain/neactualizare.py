"""Marcarea inventarelor afectate de o modificare a trecutului (§7.4 regula 6, §9.4).

Separat de `generare`, ca documentele și încadrările să-l poată folosi fără importuri circulare.
"""
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.drepturi import Actor
from inventar.models import Inventar


def marcheaza_neactualizate(session: Session, actor: Actor, data: date, motiv: str) -> list[int]:
    """Inventarele GENERAT cu data ≥ `data` devin NEACTUALIZAT; cele BLOCAT (semnate) rămân neatinse.

    Fără commit: rulează în tranzacția modificării care a produs schimbarea.
    """
    afectate = list(session.scalars(select(Inventar.id).where(Inventar.stare == "GENERAT", Inventar.data >= data)))
    if afectate:
        session.execute(update(Inventar).where(Inventar.id.in_(afectate)).values(stare="NEACTUALIZAT"),
                        execution_options={"synchronize_session": "fetch"})
        jurnal.scrie(session, actor, "INVENTAR_NEACTUALIZAT",
                     detalii={"inventare": afectate, "de_la_data": data, "motiv": motiv})
    return afectate
