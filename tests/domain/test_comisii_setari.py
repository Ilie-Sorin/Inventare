from datetime import date

import pytest
from PIL import Image

from inventar.domain.comisii import MembruNou, comisie_la, creeaza_comisie, modifica_comisie
from inventar.domain.comun import EroareValidare
from inventar.domain.setari import citeste_setari, salveaza_setari, salveaza_sigla
from inventar.drepturi import AccesInterzis
from tests.conftest import ADMIN_CLI, OPERATOR

MEMBRI = [MembruNou("POPESCU ANA", "PRESEDINTE"), MembruNou("IONESCU ŞTEFAN", "MEMBRU"), MembruNou("  ", "MEMBRU")]


def test_comisie_noua_o_inchide_pe_cea_veche(session, nom):
    loc = nom["botosani"].id
    veche = creeaza_comisie(session, OPERATOR, loc, date(2024, 1, 1), None, MEMBRI)
    noua = creeaza_comisie(session, OPERATOR, loc, date(2025, 11, 1), None, [MembruNou("X", "PRESEDINTE")])
    assert veche.valabil_pana_la == date(2025, 10, 31)
    assert comisie_la(session, loc, date(2025, 10, 31)).id == veche.id
    assert comisie_la(session, loc, date(2025, 11, 1)).id == noua.id
    assert comisie_la(session, loc, date(2023, 12, 31)) is None
    # Rândurile goale se ignoră, ordinea se păstrează.
    assert [(m.nume, m.ordine) for m in veche.membri] == [("POPESCU ANA", 1), ("IONESCU ŞTEFAN", 2)]


def test_perioade_suprapuse_refuzate(session, nom):
    loc = nom["botosani"].id
    creeaza_comisie(session, OPERATOR, loc, date(2025, 1, 1), date(2025, 12, 31), MEMBRI)
    with pytest.raises(EroareValidare, match="suprapune"):
        creeaza_comisie(session, OPERATOR, loc, date(2025, 6, 1), None, MEMBRI)
    session.rollback()
    # Altă locație: nicio legătură.
    creeaza_comisie(session, OPERATOR, nom["dorohoi"].id, date(2025, 6, 1), None, MEMBRI)


def test_validari_membri_si_perioada(session, nom):
    loc = nom["botosani"].id
    with pytest.raises(EroareValidare, match="cel puțin"):
        creeaza_comisie(session, OPERATOR, loc, date(2025, 1, 1), None, [MembruNou("", "MEMBRU")])
    with pytest.raises(EroareValidare, match="un singur președinte"):
        creeaza_comisie(session, OPERATOR, loc, date(2025, 1, 1), None,
                        [MembruNou("A", "PRESEDINTE"), MembruNou("B", "PRESEDINTE")])
    with pytest.raises(EroareValidare, match="înaintea"):
        creeaza_comisie(session, OPERATOR, loc, date(2025, 1, 1), date(2024, 1, 1), MEMBRI)


def test_modificare_membri(session, nom):
    c = creeaza_comisie(session, OPERATOR, nom["botosani"].id, date(2025, 1, 1), None, MEMBRI)
    modifica_comisie(session, OPERATOR, c.id, date(2025, 1, 1), None, [MembruNou("NOU", "MEMBRU")])
    assert [m.nume for m in c.membri] == ["NOU"]


def test_setari(session):
    assert citeste_setari(session)["nivel_cont_margine"] == "2"
    with pytest.raises(AccesInterzis):
        salveaza_setari(session, OPERATOR, {"unitate": "X"})
    with pytest.raises(EroareValidare):
        salveaza_setari(session, ADMIN_CLI, {"nivel_cont_margine": "9"})
    session.rollback()
    salveaza_setari(session, ADMIN_CLI, {"unitate": " A.J.F.P. BOTOSANI ", "antet_declaratii_2": "DGRFP IAŞI"})
    valori = citeste_setari(session)
    assert valori["unitate"] == "A.J.F.P. BOTOSANI"
    assert valori["antet_declaratii_2"] == "DGRFP IAŞI"


def test_sigla(session, tmp_path):
    with pytest.raises(EroareValidare):
        salveaza_sigla(session, ADMIN_CLI, b"nu e imagine", tmp_path)
    fisier = tmp_path / "s.jpg"
    Image.new("RGB", (20, 10), "red").save(fisier)
    salveaza_sigla(session, ADMIN_CLI, fisier.read_bytes(), tmp_path / "out")
    assert Image.open(tmp_path / "out" / "sigla.png").size == (20, 10)
    assert citeste_setari(session)["sigla"] == "sigla.png"
