"""Comisiile de inventariere, pe locație, cu perioade de valabilitate."""
import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare, curata_text
from inventar.domain.neactualizare import marcheaza_inventare
from inventar.drepturi import Actor, cere_rol
from inventar.models import Comisie, Inventar, InventarComisie, Locatie, MembruComisie


@dataclass(frozen=True)
class MembruNou:
    nume: str
    calitate: str  # PRESEDINTE | MEMBRU


def comisie_la(session: Session, locatie_id: int, data: date) -> Comisie | None:
    return session.scalar(
        select(Comisie).where(
            Comisie.locatie_id == locatie_id,
            Comisie.valabil_de_la <= data,
            (Comisie.valabil_pana_la.is_(None)) | (Comisie.valabil_pana_la >= data),
        )
    )


def _se_suprapun(a_de_la: date, a_pana_la: date | None, b_de_la: date, b_pana_la: date | None) -> bool:
    return (a_pana_la is None or a_pana_la >= b_de_la) and (b_pana_la is None or b_pana_la >= a_de_la)


def _membri_curati(membri: list[MembruNou]) -> list[MembruComisie]:
    rezultat = []
    for m in membri:
        nume = curata_text(m.nume)
        if not nume:
            continue
        if m.calitate not in ("PRESEDINTE", "MEMBRU"):
            raise EroareValidare(f"Calitate necunoscută: {m.calitate}.")
        rezultat.append(MembruComisie(nume=nume, calitate=m.calitate, ordine=len(rezultat) + 1))
    if not rezultat:
        raise EroareValidare("Comisia trebuie să aibă cel puțin un membru.")
    if sum(m.calitate == "PRESEDINTE" for m in rezultat) > 1:
        raise EroareValidare("Comisia poate avea un singur președinte.")
    return rezultat


def _verifica_perioada(session: Session, locatie_id: int, de_la: date, pana_la: date | None,
                       exclude_id: int | None) -> None:
    if pana_la is not None and pana_la < de_la:
        raise EroareValidare("Data de sfârșit nu poate fi înaintea datei de început.")
    for alta in session.scalars(select(Comisie).where(Comisie.locatie_id == locatie_id)):
        if alta.id != exclude_id and _se_suprapun(de_la, pana_la, alta.valabil_de_la, alta.valabil_pana_la):
            sfarsit = f"{alta.valabil_pana_la:%d.%m.%Y}" if alta.valabil_pana_la else "prezent"
            raise EroareValidare(
                f"Perioada se suprapune cu comisia valabilă {alta.valabil_de_la:%d.%m.%Y} – {sfarsit}."
            )


def _descriere(comisie: Comisie) -> dict:
    return {
        "locatie_id": comisie.locatie_id,
        "valabil_de_la": comisie.valabil_de_la,
        "valabil_pana_la": comisie.valabil_pana_la,
        "membri": [[m.nume, m.calitate] for m in comisie.membri],
    }


def _marcheaza_inventarele(session: Session, actor: Actor, locatie_id: int, motiv: str) -> None:
    """Inventarele GENERAT a căror copie a comisiei nu mai coincide cu comisia valabilă la data lor.

    Comparația directă acoperă la fel de bine o comisie nouă, una închisă automat, o perioadă mutată
    sau membri schimbați, fără să tratăm fiecare caz separat.
    """
    session.flush()
    afectate = []
    for copie, data in session.execute(
        select(InventarComisie, Inventar.data).join(Inventar, Inventar.id == InventarComisie.inventar_id)
        .where(Inventar.stare == "GENERAT", InventarComisie.locatie_id == locatie_id)
    ):
        comisie = comisie_la(session, locatie_id, data)
        actuali = [{"nume": m.nume, "calitate": m.calitate} for m in comisie.membri] if comisie else []
        if json.loads(copie.membri_json) != actuali:
            afectate.append(copie.inventar_id)
    marcheaza_inventare(session, actor, afectate, motiv)


def creeaza_comisie(session: Session, actor: Actor, locatie_id: int, valabil_de_la: date,
                    valabil_pana_la: date | None, membri: list[MembruNou]) -> Comisie:
    cere_rol(actor, "OPERATOR")
    if session.get(Locatie, locatie_id) is None:
        raise EroareValidare("Locația nu există.")
    membri_noi = _membri_curati(membri)
    # Cazul obișnuit: se numește o comisie nouă, iar cea veche (deschisă) se
    # închide automat în ziua dinainte, fără un pas separat.
    deschisa = session.scalar(
        select(Comisie).where(Comisie.locatie_id == locatie_id, Comisie.valabil_pana_la.is_(None))
    )
    if deschisa and deschisa.valabil_de_la < valabil_de_la:
        deschisa.valabil_pana_la = valabil_de_la - timedelta(days=1)
        jurnal.scrie(session, actor, "COMISIE_INCHISA", "comisie", deschisa.id,
                     {"valabil_pana_la": deschisa.valabil_pana_la})
        session.flush()
    _verifica_perioada(session, locatie_id, valabil_de_la, valabil_pana_la, None)
    comisie = Comisie(locatie_id=locatie_id, valabil_de_la=valabil_de_la, valabil_pana_la=valabil_pana_la,
                      membri=membri_noi)
    session.add(comisie)
    session.flush()
    jurnal.scrie(session, actor, "COMISIE_CREATA", "comisie", comisie.id, _descriere(comisie))
    _marcheaza_inventarele(session, actor, locatie_id, "comisie nouă")
    session.commit()
    return comisie


def modifica_comisie(session: Session, actor: Actor, comisie_id: int, valabil_de_la: date,
                     valabil_pana_la: date | None, membri: list[MembruNou]) -> Comisie:
    """Inventarele generate au copia lor a comisiei: nu se schimbă, dar devin NEACTUALIZAT."""
    cere_rol(actor, "OPERATOR")
    comisie = session.get(Comisie, comisie_id)
    if comisie is None:
        raise EroareValidare("Comisia nu există.")
    membri_noi = _membri_curati(membri)
    _verifica_perioada(session, comisie.locatie_id, valabil_de_la, valabil_pana_la, comisie_id)
    inainte = _descriere(comisie)
    comisie.valabil_de_la, comisie.valabil_pana_la = valabil_de_la, valabil_pana_la
    if [[m.nume, m.calitate] for m in membri_noi] != inainte["membri"]:
        comisie.membri = membri_noi
    session.flush()
    dupa = _descriere(comisie)
    if dupa != inainte:
        jurnal.scrie(session, actor, "COMISIE_MODIFICATA", "comisie", comisie.id, {"inainte": inainte, "dupa": dupa})
        _marcheaza_inventarele(session, actor, comisie.locatie_id, "modificarea comisiei")
    session.commit()
    return comisie
