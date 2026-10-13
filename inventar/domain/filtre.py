"""Filtrele de listare (§11), aplicate pe instantaneul unui inventar.

Aceeași semantică ca perimetrul de generare: o listă goală înseamnă „toate”,
dimensiunile se combină cu ȘI, gestiunile alese și cele din grupuri se adună.
"""
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from inventar.domain.generare import Perimetru
from inventar.models import Activitate, Grup, InventarLinie, Locatie, Persoana, grup_persoana


def conditii(filtru: Perimetru) -> list[ColumnElement[bool]]:
    rezultat: list[ColumnElement[bool]] = []
    if filtru.locatii:
        rezultat.append(InventarLinie.locatie_id.in_(filtru.locatii))
    if filtru.activitati:
        rezultat.append(InventarLinie.activitate_id.in_(filtru.activitati))
    if filtru.persoane or filtru.grupuri:
        din_grupuri = select(grup_persoana.c.persoana_id).where(grup_persoana.c.grup_id.in_(filtru.grupuri))
        rezultat.append(or_(InventarLinie.persoana_id.in_(filtru.persoane), InventarLinie.persoana_id.in_(din_grupuri)))
    if filtru.categorii:
        rezultat.append(InventarLinie.categorie.in_(filtru.categorii))
    if filtru.conturi:
        rezultat.append(InventarLinie.cont_sintetic.in_(filtru.conturi))
    return rezultat


def descriere(session: Session, filtru: Perimetru) -> str:
    """Text lizibil al filtrului, pentru ecrane și pentru antetul rapoartelor."""
    p = filtru.normalizat()
    if p.complet:
        return "Tot"
    parti = []
    for model, ids, eticheta, camp in ((Locatie, p.locatii, "Locații", "denumire"),
                                       (Activitate, p.activitati, "Activități", "denumire"),
                                       (Persoana, p.persoane, "Gestiuni", "nume"),
                                       (Grup, p.grupuri, "Grupuri", "denumire")):
        if ids:
            coloana = getattr(model, camp)
            nume = session.scalars(select(coloana).where(model.id.in_(ids)).order_by(coloana))
            parti.append(f"{eticheta}: {', '.join(nume)}")
    if p.categorii:
        parti.append(f"Categorii: {', '.join(p.categorii)}")
    if p.conturi:
        parti.append(f"Conturi: {', '.join(p.conturi)}")
    return "; ".join(parti)
