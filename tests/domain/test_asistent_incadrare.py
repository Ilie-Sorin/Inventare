from datetime import date

import pytest
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.domain.documente import anuleaza
from inventar.domain.incadrare import corecteaza_ultima_incadrare, incadrare_la
from inventar.domain.schimbare_incadrare import destinatari_predare, schimba_incadrarea
from inventar.domain.stoc import bunuri_la_persoana
from inventar.models import Document
from tests.conftest import OPERATOR

START, D = date(2025, 1, 1), date(2025, 6, 1)


@pytest.fixture
def lume(session, persoana, bunuri, initial, nom):
    a = persoana("A")                              # Botosani
    coleg = persoana("COLEG")                      # Botosani
    departe = persoana("DEPARTE", locatie="dorohoi")
    b1, b2, b3 = bunuri("1", "2", "3")
    initial(START, [(b1, a), (b2, a), (b3, a)])
    return {"a": a, "coleg": coleg, "departe": departe, "b1": b1, "b2": b2, "b3": b3, "nom": nom}


def test_destinatari_doar_din_vechea_locatie(session, lume):
    assert [p.nume for p in destinatari_predare(session, lume["a"].id, D)] == ["COLEG"]


def test_bunurile_urmeaza_sau_se_predau(session, lume):
    nom = lume["nom"]
    inc = schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["dorohoi"].id, nom["2c"].id, D, "mutare",
                             predari={lume["b2"].id: lume["coleg"].id})
    assert inc.document.tip == "INCADRARE" and inc.document.stare == "VALIDAT"
    assert incadrare_la(session, lume["a"].id, D).locatie_id == nom["dorohoi"].id
    assert [b.nr_inventar for b in bunuri_la_persoana(session, lume["a"].id, D)] == ["1", "3"]
    assert [b.nr_inventar for b in bunuri_la_persoana(session, lume["coleg"].id, D)] == ["2"]
    transferuri = session.scalars(select(Document).where(Document.tip == "TRANSFER")).all()
    assert [(t.data, t.stare) for t in transferuri] == [(D, "VALIDAT")]
    # Trecutul rămâne neschimbat.
    assert incadrare_la(session, lume["a"].id, D - date.resolution).locatie_id == nom["botosani"].id


def test_predare_catre_persoana_din_alta_locatie_refuzata(session, lume):
    nom = lume["nom"]
    with pytest.raises(EroareValidare, match="vechea locație"):
        schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["dorohoi"].id, nom["2c"].id, D, None,
                           predari={lume["b1"].id: lume["departe"].id})
    session.rollback()
    assert incadrare_la(session, lume["a"].id, D).locatie_id == nom["botosani"].id


def test_predare_bun_care_nu_e_al_persoanei(session, lume, bunuri):
    nom = lume["nom"]
    [strain] = bunuri("9")
    with pytest.raises(EroareValidare, match="nu se află la"):
        schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["dorohoi"].id, nom["2c"].id, D, None,
                           predari={strain.id: lume["coleg"].id})


def test_anulare_incadrare(session, lume):
    nom = lume["nom"]
    inc = schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["dorohoi"].id, nom["2c"].id, D, None)
    document_id = inc.document_id
    anuleaza(session, OPERATOR, document_id, "greșeală")
    assert incadrare_la(session, lume["a"].id, D).locatie_id == nom["botosani"].id
    assert session.get(Document, document_id).stare == "ANULAT"


def test_anulare_incadrare_doar_ultima(session, lume):
    nom = lume["nom"]
    prima = schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["dorohoi"].id, nom["2c"].id, D, None)
    schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["botosani"].id, nom["2c"].id, date(2025, 9, 1), None)
    with pytest.raises(EroareValidare, match="ulterioară"):
        anuleaza(session, OPERATOR, prima.document_id, "x")


def test_incadrarea_din_document_nu_se_corecteaza(session, lume):
    nom = lume["nom"]
    inc = schimba_incadrarea(session, OPERATOR, lume["a"].id, nom["dorohoi"].id, nom["2c"].id, D, None)
    with pytest.raises(EroareValidare, match="anulați documentul"):
        corecteaza_ultima_incadrare(session, OPERATOR, inc.id, nom["botosani"].id, nom["2c"].id, D, None)
