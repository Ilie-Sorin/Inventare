"""Tipărirea listelor și declarațiilor dintr-un inventar generat.

Listele se construiesc numai din instantaneu (`inventar_linie`, `inventar_comisie`),
niciodată din calcul direct, ca ce se tipărește azi să fie identic cu ce s-a semnat.
"""
import json
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.domain.filtre import conditii
from inventar.domain.generare import Perimetru
from inventar.domain.sabloane import citeste_sablon
from inventar.domain.setari import citeste_setari
from inventar.drepturi import Actor, cere_rol
from inventar.models import Inventar, InventarLinie
from inventar.pdf.comun import nume_fisier
from inventar.pdf.declaratii import (
    AntetDeclaratii,
    Declaratie,
    deseneaza_declaratii_inceput,
    deseneaza_declaratii_sfarsit,
)
from inventar.pdf.lista import Antet, Lista, RandLista, deseneaza_liste

ORDINE_TIRAJ = (InventarLinie.locatie, InventarLinie.activitate, InventarLinie.gestiune, InventarLinie.persoana_id,
                InventarLinie.categorie, InventarLinie.cont_sintetic, InventarLinie.cont, InventarLinie.nr_inventar)


def inventar_actual(session: Session, inventar_id: int) -> Inventar:
    """Inventarul din care se poate scoate un document: un instantaneu depășit nu ajunge pe hârtie."""
    inventar = session.get(Inventar, inventar_id)
    if inventar is None:
        raise EroareValidare("Inventarul nu există.")
    if inventar.stare == "NEACTUALIZAT":
        raise EroareValidare("Inventarul nu mai corespunde situației la zi; regenerați-l înainte de tipărire.")
    return inventar


def linii_filtrate(session: Session, inventar: Inventar, filtru: Perimetru) -> list[InventarLinie]:
    return list(session.scalars(
        select(InventarLinie).where(InventarLinie.inventar_id == inventar.id, *conditii(filtru))
        .order_by(*ORDINE_TIRAJ)
    ))


def _filtru_categorie(filtru: Perimetru, categorie: str, persoana_id: int | None) -> Perimetru:
    if categorie not in ("MF", "OI"):
        raise EroareValidare("Categoria trebuie să fie MF sau OI.")
    if filtru.categorii and categorie not in filtru.categorii:
        return replace(filtru, categorii=("--",))  # categoria cerută e exclusă de filtru
    filtru = replace(filtru, categorii=(categorie,))
    return replace(filtru, persoane=(persoana_id,), grupuri=()) if persoana_id else filtru


def _comisii(inventar: Inventar) -> dict[int, list[str]]:
    return {c.locatie_id: [m["nume"] for m in json.loads(c.membri_json)] for c in inventar.comisii}


def liste_din_inventar(session: Session, inventar: Inventar, filtru: Perimetru) -> list[Lista]:
    """O listă = gestiune × cont sintetic × locație, în ordinea tirajului (§10.1)."""
    comisii = _comisii(inventar)
    liste: dict[tuple, Lista] = {}
    for linie in linii_filtrate(session, inventar, filtru):
        cheie = (linie.persoana_id, linie.categorie, linie.cont_sintetic, linie.locatie_id)
        if cheie not in liste:
            liste[cheie] = Lista(linie.categorie, linie.cont_sintetic, linie.gestiune, linie.titular, linie.locatie,
                                 comisii.get(linie.locatie_id, []))
        liste[cheie].randuri.append(RandLista(
            linie.nr_inventar, linie.nr_inventar_vechi, linie.denumire, linie.serie, linie.um, linie.pret,
            linie.cont, linie.data_amortizare_integrala,
        ))
    return list(liste.values())


def declaratii_din_inventar(session: Session, inventar: Inventar, filtru: Perimetru) -> list[Declaratie]:
    """Câte o declarație pe gestiune × categorie, în ordinea tirajului."""
    comisii = _comisii(inventar)
    vazute: dict[tuple, Declaratie] = {}
    for linie in linii_filtrate(session, inventar, filtru):
        cheie = (linie.persoana_id, linie.categorie)
        if cheie not in vazute:
            vazute[cheie] = Declaratie(linie.categorie, linie.gestiune, linie.titular, linie.locatie,
                                       comisii.get(linie.locatie_id, []))
    return list(vazute.values())


def antet_liste(session: Session, inventar: Inventar, director_instanta: Path | None) -> Antet:
    setari = citeste_setari(session)
    sigla = director_instanta / setari["sigla"] if director_instanta and setari.get("sigla") else None
    return Antet(inventar.data, setari["unitate"], setari["unitate_superioara"], sigla,
                 int(setari["nivel_cont_margine"] or 2))


def deseneaza_declaratii(session: Session, inventar: Inventar, declaratii: list[Declaratie], tip: str) -> bytes:
    setari = citeste_setari(session)
    antet = AntetDeclaratii(inventar.data, setari["antet_declaratii_1"], setari["antet_declaratii_2"],
                            setari["unitate"])
    if tip == "inceput":
        _, puncte = citeste_sablon(session, "declaratie_inceput")
        return deseneaza_declaratii_inceput(declaratii, antet, puncte)
    return deseneaza_declaratii_sfarsit(declaratii, antet)


def _nume(prefix: str, inventar: Inventar, categorie: str, filtru: Perimetru, elemente: list) -> str:
    if len(filtru.persoane) == 1 and not filtru.grupuri and elemente:
        eticheta = elemente[0].gestiune
    else:
        # Categoria e mereu fixată aici; în rest, fără filtre înseamnă tot tirajul.
        eticheta = "tiraj" if replace(filtru, categorii=()).complet else "selectie"
    return nume_fisier(prefix, inventar.data.isoformat(), eticheta, categorie)


def tipareste_liste(session: Session, actor: Actor, inventar_id: int, categorie: str, director_instanta: Path | None,
                    persoana_id: int | None = None, filtru: Perimetru = Perimetru()) -> tuple[str, bytes]:
    cere_rol(actor, "CONSULTARE")
    inventar = inventar_actual(session, inventar_id)
    filtru = _filtru_categorie(filtru, categorie, persoana_id)
    liste = liste_din_inventar(session, inventar, filtru)
    if not liste:
        raise EroareValidare("Nu există bunuri de această categorie pentru filtrul ales.")
    continut = deseneaza_liste(liste, antet_liste(session, inventar, director_instanta))
    nume = _nume("Inventar", inventar, categorie, filtru, liste)
    jurnal.scrie(session, actor, "PDF_LISTE", "inventar", inventar.id,
                 {"fisier": nume, "filtru": json.loads(filtru.json()), "liste": len(liste)})
    session.commit()
    return nume, continut


def tipareste_declaratii(session: Session, actor: Actor, inventar_id: int, categorie: str, tip: str,
                         persoana_id: int | None = None, filtru: Perimetru = Perimetru()) -> tuple[str, bytes]:
    cere_rol(actor, "CONSULTARE")
    if tip not in ("inceput", "sfarsit"):
        raise EroareValidare("Tip de declarație necunoscut.")
    inventar = inventar_actual(session, inventar_id)
    filtru = _filtru_categorie(filtru, categorie, persoana_id)
    declaratii = declaratii_din_inventar(session, inventar, filtru)
    if not declaratii:
        raise EroareValidare("Nu există bunuri de această categorie pentru filtrul ales.")
    continut = deseneaza_declaratii(session, inventar, declaratii, tip)
    nume = _nume(f"Declaratii_{tip}", inventar, categorie, filtru, declaratii)
    jurnal.scrie(session, actor, "PDF_DECLARATII", "inventar", inventar.id,
                 {"fisier": nume, "tip": tip, "filtru": json.loads(filtru.json()), "declaratii": len(declaratii)})
    session.commit()
    return nume, continut
