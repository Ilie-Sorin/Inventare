from datetime import date

import pytest
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.domain.incadrare import corecteaza_ultima_incadrare, incadrare_la, incadrari_la
from inventar.domain.schimbare_incadrare import schimba_incadrarea
from inventar.drepturi import AccesInterzis
from inventar.models import Jurnal
from tests.conftest import CONSULTARE, OPERATOR

D1, D2 = date(2025, 1, 1), date(2025, 6, 1)


def test_incadrare_valabila_la_o_data(session, nom, persoana):
    p = persoana("POP ION", de_la=D1)
    schimba_incadrarea(session, OPERATOR, p.id, nom["dorohoi"].id, nom["2c"].id, D2, "mutare")

    assert incadrare_la(session, p.id, date(2024, 12, 31)) is None
    assert incadrare_la(session, p.id, D1).locatie_id == nom["botosani"].id
    assert incadrare_la(session, p.id, date(2025, 5, 31)).locatie_id == nom["botosani"].id
    # Exact la data schimbării se aplică deja noua încadrare.
    la_schimbare = incadrare_la(session, p.id, D2)
    assert (la_schimbare.locatie_id, la_schimbare.activitate_id) == (nom["dorohoi"].id, nom["2c"].id)


def test_incadrari_la_pentru_toate_persoanele(session, nom, persoana):
    a = persoana("A", de_la=D1)
    b = persoana("B", locatie="trezorerie_loc", activitate="trezorerie_act", de_la=D1)
    persoana("C", de_la=date(2026, 1, 1))  # încă neîncadrată la D2
    schimba_incadrarea(session, OPERATOR, a.id, nom["dorohoi"].id, nom["1int"].id, D2, None)

    rezultat = {r.persoana_id: r.locatie_id for r in session.execute(incadrari_la(D2))}
    assert rezultat == {a.id: nom["dorohoi"].id, b.id: nom["trezorerie_loc"].id}
    inainte = {r.persoana_id: r.locatie_id for r in session.execute(incadrari_la(date(2025, 5, 31)))}
    assert inainte == {a.id: nom["botosani"].id, b.id: nom["trezorerie_loc"].id}


def test_istoricul_se_completeaza_doar_la_capat(session, nom, persoana):
    p = persoana("POP ION", de_la=D2)
    with pytest.raises(EroareValidare):
        schimba_incadrarea(session, OPERATOR, p.id, nom["dorohoi"].id, nom["2c"].id, D1, None)
    with pytest.raises(EroareValidare):
        schimba_incadrarea(session, OPERATOR, p.id, nom["dorohoi"].id, nom["2c"].id, D2, None)


def test_incadrare_identica_refuzata(session, nom, persoana):
    p = persoana("POP ION", de_la=D1)
    with pytest.raises(EroareValidare, match="deja"):
        schimba_incadrarea(session, OPERATOR, p.id, nom["botosani"].id, nom["1int"].id, D2, None)


def test_locatie_inactiva_refuzata(session, nom, persoana):
    from inventar.domain.nomenclatoare import seteaza_activ_nomenclator
    from inventar.models import Locatie

    p = persoana("POP ION", de_la=D1)
    seteaza_activ_nomenclator(session, OPERATOR, Locatie, nom["dorohoi"].id, False)
    with pytest.raises(EroareValidare, match="inactivă"):
        schimba_incadrarea(session, OPERATOR, p.id, nom["dorohoi"].id, nom["1int"].id, D2, None)


def test_consultarea_nu_schimba_incadrari(session, nom, persoana):
    p = persoana("POP ION", de_la=D1)
    with pytest.raises(AccesInterzis):
        schimba_incadrarea(session, CONSULTARE, p.id, nom["dorohoi"].id, nom["2c"].id, D2, None)


def test_corectare_doar_ultima_incadrare(session, nom, persoana):
    p = persoana("POP ION", de_la=D1)
    prima = incadrare_la(session, p.id, D1)
    corecteaza_ultima_incadrare(session, OPERATOR, prima.id, nom["trezorerie_loc"].id, nom["2c"].id, D1, "greșeală")
    assert incadrare_la(session, p.id, D1).locatie_id == nom["trezorerie_loc"].id
    ultima = session.scalars(select(Jurnal).order_by(Jurnal.id.desc())).first()
    assert ultima.actiune == "INCADRARE_CORECTATA"

    schimba_incadrarea(session, OPERATOR, p.id, nom["dorohoi"].id, nom["2c"].id, D2, None)
    with pytest.raises(EroareValidare, match="ultima"):
        corecteaza_ultima_incadrare(session, OPERATOR, prima.id, nom["dorohoi"].id, nom["1int"].id, D1, None)


def test_corectare_data_dupa_incadrarea_anterioara(session, nom, persoana):
    from inventar.domain.incadrare import creeaza_incadrare

    p = persoana("POP ION", de_la=D1)
    # Încadrare fără document (ca cele inițiale), ca să poată fi corectată.
    noua = creeaza_incadrare(session, p.id, nom["dorohoi"].id, nom["2c"].id, D2)
    session.commit()
    with pytest.raises(EroareValidare, match="după"):
        corecteaza_ultima_incadrare(session, OPERATOR, noua.id, nom["dorohoi"].id, nom["2c"].id, D1, None)
