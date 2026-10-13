from datetime import date

import pytest
from sqlalchemy import func, select

from inventar.domain.comun import EroareValidare
from inventar.domain.nomenclatoare import (
    creeaza_grup,
    creeaza_nomenclator,
    modifica_grup,
    modifica_nomenclator,
    seteaza_activ_nomenclator,
    sterge_grup,
)
from inventar.drepturi import AccesInterzis
from inventar.models import Activitate, Grup, Locatie, grup_persoana
from tests.conftest import CONSULTARE, OPERATOR


def test_aceeasi_denumire_in_locatii_si_activitati(nom):
    assert nom["trezorerie_loc"].cod == nom["trezorerie_act"].cod == "Trezorerie"


def test_cod_unic_fara_diferenta_de_majuscule(session, nom):
    with pytest.raises(EroareValidare, match="există deja"):
        creeaza_nomenclator(session, OPERATOR, Locatie, "botosani", "Alt")
    with pytest.raises(EroareValidare, match="există deja"):
        modifica_nomenclator(session, OPERATOR, Locatie, nom["dorohoi"].id, "BOTOSANI", "x")


def test_campuri_obligatorii(session):
    with pytest.raises(EroareValidare):
        creeaza_nomenclator(session, OPERATOR, Activitate, "  ", "x")


def test_consultarea_nu_creeaza(session):
    with pytest.raises(AccesInterzis):
        creeaza_nomenclator(session, CONSULTARE, Locatie, "X", "X")


def test_nu_se_dezactiveaza_locatia_cu_persoane_active(session, nom, persoana):
    persoana("POP ION", locatie="dorohoi", de_la=date(2025, 1, 1))
    with pytest.raises(EroareValidare, match="1 persoane"):
        seteaza_activ_nomenclator(session, OPERATOR, Locatie, nom["dorohoi"].id, False, azi=date(2025, 2, 1))
    # Înainte de încadrare locația era liberă.
    seteaza_activ_nomenclator(session, OPERATOR, Locatie, nom["dorohoi"].id, False, azi=date(2024, 12, 1))
    assert not nom["dorohoi"].activ


def test_grupuri(session, persoana):
    a, b, c = persoana("A"), persoana("B"), persoana("C")
    grup = creeaza_grup(session, OPERATOR, "Șefi de serviciu", [a.id, b.id])
    assert [p.nume for p in grup.persoane] == ["A", "B"]
    modifica_grup(session, OPERATOR, grup.id, "Șefi", [b.id, c.id])
    assert [p.nume for p in grup.persoane] == ["B", "C"]
    with pytest.raises(EroareValidare, match="există deja"):
        creeaza_grup(session, OPERATOR, "ȘEFI", [])
    with pytest.raises(EroareValidare, match="nu există"):
        creeaza_grup(session, OPERATOR, "Alt grup", [999])
    sterge_grup(session, OPERATOR, grup.id)
    assert session.scalar(select(func.count()).select_from(Grup)) == 0
    assert session.scalar(select(func.count()).select_from(grup_persoana)) == 0
