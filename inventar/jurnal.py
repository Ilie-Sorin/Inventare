"""Scrierea în jurnalul de acțiuni.

Nu face commit: înregistrarea intră în tranzacția serviciului care o cheamă,
astfel încât acțiunea și urma ei în jurnal reușesc sau eșuează împreună.
"""
import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from inventar.drepturi import Actor
from inventar.models import Jurnal


def scrie(
    session: Session,
    actor: Actor,
    actiune: str,
    obiect_tip: str | None = None,
    obiect_id: int | None = None,
    detalii: dict[str, Any] | None = None,
    rezultat: str = "OK",
) -> Jurnal:
    intrare = Jurnal(
        la=datetime.now(),
        utilizator_id=actor.utilizator_id,
        username=actor.username,
        ip=actor.ip,
        actiune=actiune,
        obiect_tip=obiect_tip,
        obiect_id=obiect_id,
        detalii_json=json.dumps(detalii or {}, ensure_ascii=False, default=str),
        rezultat=rezultat,
    )
    session.add(intrare)
    return intrare
