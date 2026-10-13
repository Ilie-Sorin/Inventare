import json

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DatabaseError

from inventar import jurnal
from inventar.drepturi import AccesInterzis, Actor
from inventar.models import Jurnal
from inventar.utilizatori import EroareUtilizator, autentifica, creeaza_utilizator


def _intrari(session) -> list[Jurnal]:
    return list(session.scalars(select(Jurnal).order_by(Jurnal.id)))


def test_creare_utilizator_scrie_in_jurnal(session, creeaza):
    u = creeaza("ion", rol="OPERATOR")
    [intrare] = _intrari(session)
    assert intrare.actiune == "UTILIZATOR_CREAT"
    assert intrare.obiect_id == u.id
    assert json.loads(intrare.detalii_json) == {"username": "ion", "rol": "OPERATOR"}


def test_doar_adminul_creeaza_utilizatori(session):
    operator = Actor(utilizator_id=1, username="op", rol="OPERATOR")
    with pytest.raises(AccesInterzis):
        creeaza_utilizator(session, operator, "x", "parola123", "CONSULTARE")


@pytest.mark.parametrize("username, parola, rol", [
    ("", "parola123", "ADMIN"),
    ("ion", "scurta", "ADMIN"),
    ("ion", "parola123", "SEF"),
])
def test_creare_invalida(session, username, parola, rol):
    with pytest.raises(EroareUtilizator):
        creeaza_utilizator(session, Actor(None, "t", "ADMIN"), username, parola, rol)


def test_username_duplicat(creeaza):
    creeaza("ion")
    with pytest.raises(EroareUtilizator):
        creeaza("ion")


def test_autentificare_reusita_si_esuata(session, creeaza):
    creeaza("ion")
    assert autentifica(session, "ion", "parola123", "10.0.0.1") is not None
    assert autentifica(session, "ion", "gresit", "10.0.0.1") is None
    assert autentifica(session, "nimeni", "parola123", "10.0.0.1") is None
    intrari = _intrari(session)[1:]
    assert [(i.actiune, i.rezultat, i.username) for i in intrari] == [
        ("AUTENTIFICARE", "OK", "ion"),
        ("AUTENTIFICARE", "ESEC", "ion"),
        ("AUTENTIFICARE", "ESEC", "nimeni"),
    ]
    assert all(i.ip == "10.0.0.1" for i in intrari)


def test_cont_inactiv_nu_se_autentifica(session, creeaza):
    u = creeaza("ion")
    u.activ = False
    session.commit()
    assert autentifica(session, "ion", "parola123", None) is None
    assert json.loads(_intrari(session)[-1].detalii_json) == {"motiv": "cont inactiv"}


def test_jurnalul_nu_se_modifica_si_nu_se_sterge(session):
    jurnal.scrie(session, Actor(None, "t", "ADMIN"), "TEST")
    session.commit()
    with pytest.raises(DatabaseError):
        session.execute(update(Jurnal).values(actiune="ALTCEVA"))
    session.rollback()
    with pytest.raises(DatabaseError):
        session.execute(delete(Jurnal))
    session.rollback()
    assert [i.actiune for i in _intrari(session)] == ["TEST"]


def test_jurnalul_intra_in_tranzactia_apelantului(session):
    jurnal.scrie(session, Actor(None, "t", "ADMIN"), "TEST", detalii={"text": "ăîșțâ"})
    session.rollback()
    assert _intrari(session) == []


def test_ramane_mereu_un_admin_activ(session, creeaza):
    from inventar.utilizatori import modifica_utilizator

    admin = creeaza("admin")
    with pytest.raises(EroareUtilizator, match="cel puțin un administrator"):
        modifica_utilizator(session, Actor(admin.id, "admin", "ADMIN"), admin.id, "OPERATOR", True, None)
    al_doilea = creeaza("admin2")
    modifica_utilizator(session, Actor(admin.id, "admin", "ADMIN"), al_doilea.id, "ADMIN", False, None)
    assert not al_doilea.activ


def test_parole(session, creeaza):
    from inventar.utilizatori import reseteaza_parola, schimba_parola_proprie

    u = creeaza("ion", rol="OPERATOR")
    actor = Actor(u.id, "ion", "OPERATOR")
    with pytest.raises(EroareUtilizator, match="greșită"):
        schimba_parola_proprie(session, actor, "gresit", "parolanoua1")
    schimba_parola_proprie(session, actor, "parola123", "parolanoua1")
    assert autentifica(session, "ion", "parolanoua1", None)
    with pytest.raises(AccesInterzis):
        reseteaza_parola(session, actor, u.id, "altaparola")
    reseteaza_parola(session, Actor(None, "t", "ADMIN"), u.id, "altaparola")
    assert autentifica(session, "ion", "altaparola", None)
