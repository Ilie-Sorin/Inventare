import json
from datetime import date

import pytest
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.domain.persoane import creeaza_persoana, modifica_persoana, seteaza_activ_persoana
from inventar.models import Jurnal, Persoana
from tests.conftest import OPERATOR


def test_persoana_noua_are_incadrare(session, nom, persoana):
    p = persoana("  POP   ION ", de_la=date(2025, 1, 1))
    assert p.nume == "POP ION"
    assert len(p.incadrari) == 1
    assert p.incadrari[0].locatie_id == nom["botosani"].id


def test_creare_atomica_la_eroare_de_incadrare(session, nom):
    with pytest.raises(EroareValidare):
        creeaza_persoana(session, OPERATOR, "POP ION", None, None, None, 999, nom["1int"].id, date(2025, 1, 1))
    session.rollback()
    assert session.scalar(select(Persoana.id)) is None


def test_nume_unic(persoana):
    persoana("POP ION")
    with pytest.raises(EroareValidare, match="Există deja"):
        persoana("pop ion")


def test_email_invalid(persoana):
    with pytest.raises(EroareValidare, match="e-mail"):
        persoana("POP ION", email="fara-arond")


def test_gestiune_secundara_si_nume_la_semnatura(session, persoana):
    titular = persoana("NECHIFOR DAN")
    secundara = persoana("NECHIFOR DAN ET2", titular_id=titular.id)
    assert secundara.nume_semnatura == "NECHIFOR DAN"
    assert titular.nume_semnatura == "NECHIFOR DAN"
    assert [g.nume for g in titular.gestiuni_secundare] == ["NECHIFOR DAN ET2"]


def test_titular_un_singur_nivel(session, persoana):
    titular = persoana("NECHIFOR DAN")
    secundara = persoana("NECHIFOR DAN ET2", titular_id=titular.id)
    with pytest.raises(EroareValidare, match="gestiune secundară"):
        persoana("ALTA", titular_id=secundara.id)
    # Cine e deja titular nu poate primi el însuși titular.
    alt = persoana("POP ION")
    with pytest.raises(EroareValidare, match="titular pentru alte"):
        modifica_persoana(session, OPERATOR, titular.id, titular.nume, None, None, alt.id)
    with pytest.raises(EroareValidare, match="propriul"):
        modifica_persoana(session, OPERATOR, alt.id, alt.nume, None, None, alt.id)


def test_redenumire_in_jurnal(session, persoana):
    p = persoana("AIONITOAIE CORNELIU")
    modifica_persoana(session, OPERATOR, p.id, "AIONIŢOAIE CORNELIU", "123", "a@b.ro", None)
    intrare = session.scalars(select(Jurnal).order_by(Jurnal.id.desc())).first()
    assert intrare.actiune == "PERSOANA_MODIFICATA"
    detalii = json.loads(intrare.detalii_json)
    assert detalii["nume"] == ["AIONITOAIE CORNELIU", "AIONIŢOAIE CORNELIU"]
    assert detalii["email"] == [None, "a@b.ro"]


def test_dezactivare_titular_cu_gestiuni_active(session, persoana):
    titular = persoana("NECHIFOR DAN")
    secundara = persoana("NECHIFOR DAN ET2", titular_id=titular.id)
    with pytest.raises(EroareValidare, match="gestiuni active"):
        seteaza_activ_persoana(session, OPERATOR, titular.id, False)
    seteaza_activ_persoana(session, OPERATOR, secundara.id, False)
    seteaza_activ_persoana(session, OPERATOR, titular.id, False)
    assert not titular.activ
    with pytest.raises(EroareValidare, match="Titularul"):
        seteaza_activ_persoana(session, OPERATOR, secundara.id, True)
