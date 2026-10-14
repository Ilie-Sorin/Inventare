"""Persoane / gestiuni și legătura cu titularul (§7.3)."""
import re
from datetime import date

from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare, aplica_modificari, curata_text, exista_alta_valoare, text_optional
from inventar.domain.incadrare import creeaza_incadrare
from inventar.domain.neactualizare import marcheaza_cu_linii
from inventar.domain.stoc import are_bunuri
from inventar.drepturi import Actor, cere_rol
from inventar.models import InventarLinie, Persoana

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def adresa_valida(email: str) -> bool:
    return bool(_EMAIL.match(email))


def _verifica_date(session: Session, nume: str, email: str | None, exclude_id: int | None) -> None:
    if not nume:
        raise EroareValidare("Numele este obligatoriu.")
    # Numele gestiunii apare pe liste; două gestiuni cu același nume nu s-ar
    # mai putea deosebi pe hârtie.
    if exista_alta_valoare(session, Persoana.nume, nume, exclude_id):
        raise EroareValidare(f"Există deja o gestiune cu numele „{nume}”.")
    if email and not adresa_valida(email):
        raise EroareValidare(f"Adresa de e-mail „{email}” nu este validă.")


def _verifica_titular(session: Session, persoana: Persoana | None, titular_id: int | None) -> None:
    if titular_id is None:
        return
    if persoana is not None and titular_id == persoana.id:
        raise EroareValidare("O gestiune nu poate fi propriul titular.")
    titular = session.get(Persoana, titular_id)
    if titular is None or not titular.activ:
        raise EroareValidare("Titularul ales nu există sau este inactiv.")
    # Un singur nivel: titularul e persoana fizică, nu o altă gestiune secundară.
    if titular.titular_id is not None:
        raise EroareValidare(f"„{titular.nume}” este o gestiune secundară și nu poate fi titular.")
    if persoana is not None and persoana.gestiuni_secundare:
        raise EroareValidare("Persoana este titular pentru alte gestiuni și nu poate avea la rândul ei titular.")


def creeaza_persoana(
    session: Session, actor: Actor, nume: str, marca: str | None, email: str | None, titular_id: int | None,
    locatie_id: int, activitate_id: int, valabil_de_la: date,
) -> Persoana:
    """O persoană se creează direct cu încadrarea, ca să aibă mereu exact una de la început."""
    cere_rol(actor, "OPERATOR")
    nume, email = curata_text(nume), text_optional(email)
    _verifica_date(session, nume, email, None)
    _verifica_titular(session, None, titular_id)
    persoana = Persoana(nume=nume, marca=text_optional(marca), email=email, titular_id=titular_id, activ=True)
    session.add(persoana)
    session.flush()
    creeaza_incadrare(session, persoana.id, locatie_id, activitate_id, valabil_de_la, "încadrare inițială")
    jurnal.scrie(session, actor, "PERSOANA_CREATA", "persoana", persoana.id, {
        "nume": nume, "marca": persoana.marca, "email": email, "titular_id": titular_id,
        "locatie_id": locatie_id, "activitate_id": activitate_id, "valabil_de_la": valabil_de_la,
    })
    session.commit()
    return persoana


def modifica_persoana(
    session: Session, actor: Actor, persoana_id: int, nume: str, marca: str | None, email: str | None,
    titular_id: int | None,
) -> Persoana:
    """Include redenumirea: persoana are id intern, deci documentele rămân legate corect."""
    cere_rol(actor, "OPERATOR")
    persoana = session.get(Persoana, persoana_id)
    if persoana is None:
        raise EroareValidare("Persoana nu există.")
    nume, email = curata_text(nume), text_optional(email)
    _verifica_date(session, nume, email, persoana_id)
    if titular_id != persoana.titular_id:
        _verifica_titular(session, persoana, titular_id)
    schimbari = aplica_modificari(persoana, {
        "nume": nume, "marca": text_optional(marca), "email": email, "titular_id": titular_id,
    })
    if schimbari:
        jurnal.scrie(session, actor, "PERSOANA_MODIFICATA", "persoana", persoana.id, schimbari)
    # Numele gestiunii și al titularului sunt copiate în instantaneu și tipărite pe liste.
    conditii = []
    if "nume" in schimbari:
        conditii += [InventarLinie.persoana_id == persoana.id, InventarLinie.titular_id == persoana.id]
    if "titular_id" in schimbari:
        conditii.append(InventarLinie.persoana_id == persoana.id)
    if conditii:
        marcheaza_cu_linii(session, actor, f"modificarea gestiunii „{persoana.nume}”", *conditii)
    session.commit()
    return persoana


def seteaza_activ_persoana(session: Session, actor: Actor, persoana_id: int, activ: bool) -> Persoana:
    cere_rol(actor, "OPERATOR")
    persoana = session.get(Persoana, persoana_id)
    if persoana is None:
        raise EroareValidare("Persoana nu există.")
    if persoana.activ == activ:
        return persoana
    if not activ and any(g.activ for g in persoana.gestiuni_secundare):
        raise EroareValidare("Persoana este titular pentru gestiuni active; dezactivați-le întâi pe acelea.")
    if not activ:
        # Și documentele cu dată viitoare contează: bunurile trebuie predate întâi.
        numar = are_bunuri(session, persoana.id)
        if numar:
            raise EroareValidare(f"Persoana are în primire {numar} bunuri; transferați-le întâi.")
    if activ and persoana.titular is not None and not persoana.titular.activ:
        raise EroareValidare("Titularul acestei gestiuni este inactiv; activați-l întâi.")
    persoana.activ = activ
    jurnal.scrie(session, actor, "PERSOANA_ACTIVATA" if activ else "PERSOANA_DEZACTIVATA", "persoana", persoana.id)
    session.commit()
    return persoana
