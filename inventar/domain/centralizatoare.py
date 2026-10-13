"""Centralizatoarele (§11): număr de bunuri și valoare, cu subtotaluri și total general.

Se calculează numai din instantaneu, ca să corespundă exact listelor tipărite.
"""
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inventar.domain.filtre import conditii
from inventar.domain.generare import Perimetru
from inventar.models import InventarLinie

DENUMIRI_CATEGORII = {"MF": "MF — Mijloace fixe", "OI": "OI — Obiecte de inventar"}

# tip → (titlu, niveluri de grupare); ultimul nivel e rândul de detaliu.
TIPURI = {
    "categorii": ("pe categorii", (InventarLinie.categorie, InventarLinie.cont)),
    "conturi": ("pe conturi", (InventarLinie.cont_sintetic, InventarLinie.cont)),
    "locatii": ("pe locații", (InventarLinie.locatie, InventarLinie.categorie, InventarLinie.cont_sintetic)),
    "activitati": ("pe activități", (InventarLinie.activitate, InventarLinie.categorie, InventarLinie.cont_sintetic)),
    "gestiuni": ("pe gestiuni", (InventarLinie.gestiune, InventarLinie.categorie)),
}


@dataclass(frozen=True)
class RandCentralizator:
    tip: str          # grup | detaliu | subtotal | total
    nivel: int
    eticheta: str
    numar: int | None = None
    valoare: Decimal | None = None


def _eticheta(coloana, valoare: str) -> str:
    if coloana is InventarLinie.categorie:
        return DENUMIRI_CATEGORII.get(valoare, valoare)
    if coloana is InventarLinie.cont_sintetic:
        return f"Cont {valoare}"
    return valoare


def centralizator(session: Session, inventar_id: int, tip: str, filtru: Perimetru = Perimetru()) -> list[RandCentralizator]:
    _, coloane = TIPURI[tip]
    detalii = session.execute(
        select(*coloane, func.count(), func.sum(InventarLinie.pret))
        .where(InventarLinie.inventar_id == inventar_id, *conditii(filtru))
        .group_by(*coloane).order_by(*coloane)
    ).all()
    randuri: list[RandCentralizator] = []

    def construieste(grup: list, nivel: int) -> tuple[int, Decimal]:
        if nivel == len(coloane) - 1:
            for r in grup:
                randuri.append(RandCentralizator("detaliu", nivel, _eticheta(coloane[nivel], r[nivel]), r[-2], r[-1]))
            return sum(r[-2] for r in grup), sum((r[-1] for r in grup), Decimal("0"))
        total_numar, total_valoare = 0, Decimal("0")
        for cheie, subgrup in groupby(grup, key=lambda r: r[nivel]):
            eticheta = _eticheta(coloane[nivel], cheie)
            randuri.append(RandCentralizator("grup", nivel, eticheta))
            numar, valoare = construieste(list(subgrup), nivel + 1)
            randuri.append(RandCentralizator("subtotal", nivel, f"Total {eticheta}", numar, valoare))
            total_numar, total_valoare = total_numar + numar, total_valoare + valoare
        return total_numar, total_valoare

    numar, valoare = construieste(detalii, 0)
    randuri.append(RandCentralizator("total", 0, "TOTAL GENERAL", numar, valoare))
    return randuri
