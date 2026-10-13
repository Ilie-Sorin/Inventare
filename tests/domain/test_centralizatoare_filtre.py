from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from inventar.domain.centralizatoare import centralizator
from inventar.domain.filtre import conditii
from inventar.domain.generare import Perimetru, genereaza
from inventar.domain.nomenclatoare import creeaza_grup
from inventar.models import InventarLinie
from tests.conftest import OPERATOR

D = date(2025, 11, 28)


@pytest.fixture
def inv(session, persoana, bunuri, initial, nom):
    a = persoana("ANA")                                                   # Botosani / 1Int
    b = persoana("BOGDAN", locatie="trezorerie_loc", activitate="trezorerie_act")
    mf1 = bunuri("1", "2", cont="213.01", pret="100.00")
    mf2 = bunuri("3", cont="214.02", pret="50.00")
    oi = bunuri("4", "5", "6", categorie="OI", cont="303.02.00.04", pret="10.00")
    initial(date(2025, 1, 1), [(mf1[0], a), (mf1[1], b), (mf2[0], a), (oi[0], a), (oi[1], b), (oi[2], b)])
    inventar = genereaza(session, OPERATOR, D, Perimetru())
    return {"inv": inventar, "a": a, "b": b, "nom": nom}


def numere(session, inventar, filtru) -> set[str]:
    return set(session.scalars(select(InventarLinie.nr_inventar)
                               .where(InventarLinie.inventar_id == inventar.id, *conditii(filtru))))


def test_filtre(session, inv):
    i, nom = inv["inv"], inv["nom"]
    assert numere(session, i, Perimetru()) == {"1", "2", "3", "4", "5", "6"}
    assert numere(session, i, Perimetru(locatii=(nom["trezorerie_loc"].id,))) == {"2", "5", "6"}
    assert numere(session, i, Perimetru(activitati=(nom["1int"].id,))) == {"1", "3", "4"}
    assert numere(session, i, Perimetru(persoane=(inv["a"].id,), categorii=("OI",))) == {"4"}
    assert numere(session, i, Perimetru(conturi=("214",))) == {"3"}
    grup = creeaza_grup(session, OPERATOR, "G", [inv["b"].id])
    # Gestiunile alese direct și cele din grupuri se adună.
    assert numere(session, i, Perimetru(grupuri=(grup.id,), conturi=("213",))) == {"2"}
    assert numere(session, i, Perimetru(grupuri=(grup.id,), persoane=(inv["a"].id,))) == {"1", "2", "3", "4", "5", "6"}


def test_centralizator_pe_categorii(session, inv):
    randuri = centralizator(session, inv["inv"].id, "categorii")
    assert [(r.tip, r.eticheta, r.numar, r.valoare) for r in randuri] == [
        ("grup", "MF — Mijloace fixe", None, None),
        ("detaliu", "213.01", 2, Decimal("200.00")),
        ("detaliu", "214.02", 1, Decimal("50.00")),
        ("subtotal", "Total MF — Mijloace fixe", 3, Decimal("250.00")),
        ("grup", "OI — Obiecte de inventar", None, None),
        ("detaliu", "303.02.00.04", 3, Decimal("30.00")),
        ("subtotal", "Total OI — Obiecte de inventar", 3, Decimal("30.00")),
        ("total", "TOTAL GENERAL", 6, Decimal("280.00")),
    ]


def test_centralizator_pe_locatii_trei_niveluri(session, inv):
    randuri = centralizator(session, inv["inv"].id, "locatii")
    subtotaluri = {r.eticheta: (r.numar, r.valoare) for r in randuri if r.tip == "subtotal"}
    assert subtotaluri["Total Botosani"] == (3, Decimal("160.00"))
    assert subtotaluri["Total Trezorerie"] == (3, Decimal("120.00"))
    assert [r.nivel for r in randuri if r.tip == "detaliu"] == [2] * 5  # Botoșani 213, 214, 303; Trezorerie 213, 303
    assert randuri[-1].valoare == Decimal("280.00")


@pytest.mark.parametrize("tip", ["conturi", "activitati", "gestiuni"])
def test_totalul_general_e_acelasi_pentru_orice_tip(session, inv, tip):
    assert centralizator(session, inv["inv"].id, tip)[-1].valoare == Decimal("280.00")


def test_centralizator_filtrat_si_gol(session, inv):
    randuri = centralizator(session, inv["inv"].id, "gestiuni", Perimetru(categorii=("OI",)))
    assert randuri[-1].numar == 3
    gol = centralizator(session, inv["inv"].id, "gestiuni", Perimetru(conturi=("999",)))
    assert [(r.tip, r.numar) for r in gol] == [("total", 0)]
