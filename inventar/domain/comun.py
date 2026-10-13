"""Elemente folosite de toate serviciile de domeniu."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


class EroareValidare(ValueError):
    """Eroare cu mesaj pentru utilizator (în română), afișat ca atare în interfață."""


def curata_text(valoare: str | None) -> str:
    # Spațiile multiple apar des în datele copiate din alte aplicații.
    return " ".join((valoare or "").split())


def text_optional(valoare: str | None) -> str | None:
    return curata_text(valoare) or None


def aplica_modificari(obiect: Any, valori: dict[str, Any]) -> dict[str, list[Any]]:
    """Setează câmpurile și întoarce doar ce s-a schimbat, ca {camp: [vechi, nou]} pentru jurnal."""
    schimbari: dict[str, list[Any]] = {}
    for camp, nou in valori.items():
        vechi = getattr(obiect, camp)
        if vechi != nou:
            schimbari[camp] = [vechi, nou]
            setattr(obiect, camp, nou)
    return schimbari


def exista_alta_valoare(session: Session, coloana: Any, valoare: str, exclude_id: int | None = None) -> bool:
    """Verifică unicitatea fără diferență de majuscule, inclusiv pentru diacritice.

    Comparația se face în Python: `lower()` din SQLite nu cunoaște ș/ț/ă.
    Nomenclatoarele au cel mult câteva sute de rânduri, deci costul e neglijabil.
    """
    model = coloana.class_
    cheie = valoare.casefold()
    for id_, existent in session.execute(select(model.id, coloana)):
        if id_ != exclude_id and existent.casefold() == cheie:
            return True
    return False
