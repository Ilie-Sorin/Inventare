from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.pool import StaticPool

from inventar import create_app
from inventar.domain import nomenclatoare, persoane
from inventar.drepturi import Actor
from inventar.extensions import db as _db
from inventar.models import Activitate, Locatie
from inventar.utilizatori import creeaza_utilizator

ADMIN_CLI = Actor(utilizator_id=None, username="test", rol="ADMIN")
OPERATOR = Actor(utilizator_id=None, username="op", rol="OPERATOR")
CONSULTARE = Actor(utilizator_id=None, username="cons", rol="CONSULTARE")


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        # O singură conexiune partajată: baza în memorie rămâne aceeași pe tot testul.
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
        "WTF_CSRF_ENABLED": False,
    })
    app.instance_path = str(tmp_path)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def session(app):
    return _db.session


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def creeaza(session):
    def _creeaza(username: str = "admin", parola: str = "parola123", rol: str = "ADMIN"):
        return creeaza_utilizator(session, ADMIN_CLI, username, parola, rol)
    return _creeaza


@pytest.fixture
def nom(session):
    """Câteva locații și activități; „Trezorerie” e intenționat în ambele."""
    def loc(cod):
        return nomenclatoare.creeaza_nomenclator(session, OPERATOR, Locatie, cod, cod)

    def act(cod):
        return nomenclatoare.creeaza_nomenclator(session, OPERATOR, Activitate, cod, cod)

    return {
        "botosani": loc("Botosani"), "dorohoi": loc("Dorohoi"), "trezorerie_loc": loc("Trezorerie"),
        "1int": act("Botosani (1Int)"), "2c": act("Botosani (2C)"), "trezorerie_act": act("Trezorerie"),
    }


@pytest.fixture
def persoana(session, nom):
    def _persoana(nume: str, locatie: str = "botosani", activitate: str = "1int",
                  de_la: date = date(2025, 1, 1), titular_id: int | None = None, email: str | None = None):
        return persoane.creeaza_persoana(session, OPERATOR, nume, None, email, titular_id,
                                         nom[locatie].id, nom[activitate].id, de_la)
    return _persoana


@pytest.fixture
def bunuri(session):
    """Creează bunuri direct în bază (datele contabile nu se editează prin servicii)."""
    from datetime import datetime
    from decimal import Decimal

    from inventar.models import Bun, Cont

    def _bunuri(*numere: str, categorie: str = "MF", cont: str = "213.01", pret: str = "100.00", **extra):
        obiect_cont = session.scalar(select(Cont).where(Cont.simbol == cont))
        if obiect_cont is None:
            obiect_cont = Cont(simbol=cont, sintetic=cont[:3], categorie=categorie)
            session.add(obiect_cont)
        rezultat = []
        for nr in numere:
            b = Bun(nr_inventar=nr, categorie=categorie, cont=obiect_cont, denumire=f"BUN {nr}", um="BUC",
                    pret=Decimal(pret), prezent_in_export=True, actualizat_la=datetime.now(), **extra)
            session.add(b)
            rezultat.append(b)
        session.commit()
        return rezultat
    return _bunuri


@pytest.fixture
def initial(session):
    """Document INITIAL validat, ca după importul inițial."""
    from datetime import datetime

    from inventar.models import Document, LinieDocument

    def _initial(data: date, repartizare: list[tuple]):
        doc = Document(tip="INITIAL", numar="1", data=data, stare="VALIDAT", creat_la=datetime.now(),
                       validat_la=datetime.now())
        session.add(doc)
        for bun, persoana in repartizare:
            session.add(LinieDocument(document=doc, bun=bun, persoana_la=persoana))
        session.commit()
        return doc
    return _initial
