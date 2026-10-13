from datetime import date

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import select

from inventar.domain.generare import Perimetru, genereaza
from inventar.extensions import db
from inventar.models import Setare, TrimitereEmail
from inventar.utilizatori import creeaza_utilizator
from tests.conftest import ADMIN_CLI, OPERATOR
from tests.domain.test_email import Colector, port_liber


@pytest.fixture
def smtp_local():
    colector, port = Colector(), port_liber()
    controller = Controller(colector, hostname="127.0.0.1", port=port)
    controller.start()
    yield colector, port
    controller.stop()


@pytest.fixture
def lume(app, client, session, creeaza, persoana, bunuri, initial):
    app.config["EMAIL_SINCRON"] = True
    a = persoana("POP ANA", email="ana@exemplu.ro")
    persoana("FĂRĂ ADRESĂ")
    [b1] = bunuri("1")
    [b2] = bunuri("2")
    initial(date(2025, 1, 1), [(b1, a)])
    inventar = genereaza(session, OPERATOR, date(2025, 11, 28), Perimetru())
    creeaza("admin")
    creeaza("op", rol="OPERATOR")
    return {"inv": inventar, "b2": b2}


def _login(client, nume):
    client.post("/deconectare")
    client.post("/autentificare", data={"username": nume, "parola": "parola123"})


def test_flux_email(client, session, lume, smtp_local):
    colector, port = smtp_local
    _login(client, "admin")
    r = client.post("/admin/email", data={"actiune": "salveaza", "server": "127.0.0.1", "port": port,
                                          "securitate": "niciuna", "utilizator": "", "parola": "",
                                          "expeditor": "inventar@exemplu.ro", "nume_expeditor": "Inventar"})
    assert r.status_code == 302
    client.post("/admin/email", data={"actiune": "test", "adresa_test": "admin@exemplu.ro"})
    assert colector.mesaje[-1]["To"] == "admin@exemplu.ro"

    _login(client, "op")
    url = f"/inventare/{lume['inv'].id}/email"
    pagina = client.get(url).get_data(as_text=True)
    assert "ana@exemplu.ro" in pagina and "Inventar_2025-11-28_POP_ANA_MF.pdf" in pagina
    assert "Declaratii_sfarsit_2025-11-28_POP_ANA_MF.pdf" in pagina
    assert "Bună ziua, POP ANA," in pagina
    r = client.post(url)
    assert r.status_code == 302
    pagina = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Trimitere încheiată" in pagina and "trimis" in pagina
    assert any(m["To"] == "ana@exemplu.ro" for m in colector.mesaje)
    assert "detalii" in client.get("/email").get_data(as_text=True)


def test_retrimitere_din_pagina(client, session, lume, smtp_local):
    colector, port = smtp_local
    for cheie, valoare in {"smtp_server": "127.0.0.1", "smtp_port": str(port_liber()), "smtp_securitate": "niciuna",
                           "smtp_expeditor": "inventar@exemplu.ro"}.items():
        session.add(Setare(cheie=cheie, valoare=valoare))
    session.commit()
    _login(client, "op")
    r = client.post(f"/inventare/{lume['inv'].id}/email")
    lot = r.headers["Location"].rsplit("/", 1)[-1]
    rand = session.scalar(select(TrimitereEmail))
    assert rand.stare == "EROARE"
    assert "Retrimite" in client.get(f"/email/{lot}").get_data(as_text=True)

    session.get(Setare, "smtp_port").valoare = str(port)
    session.commit()
    client.post(f"/email/{lot}/retrimitere")
    session.refresh(rand)
    assert rand.stare == "TRIMIS" and len(colector.mesaje) == 1


def test_drepturi(client, lume):
    _login(client, "op")
    assert client.get("/admin/email").status_code == 403
    creeaza_utilizator(db.session, ADMIN_CLI, "cons", "parola123", "CONSULTARE")
    _login(client, "cons")
    assert client.get(f"/inventare/{lume['inv'].id}/email").status_code == 403
    assert client.get("/email").status_code == 200


def test_fara_smtp_nu_se_poate_trimite(client, lume):
    _login(client, "op")
    pagina = client.get(f"/inventare/{lume['inv'].id}/email").get_data(as_text=True)
    assert "Setările SMTP nu sunt completate" in pagina and "Confirmă și trimite" not in pagina
    r = client.post(f"/inventare/{lume['inv'].id}/email", follow_redirects=True)
    assert "Setările SMTP nu sunt completate" in r.get_data(as_text=True)
