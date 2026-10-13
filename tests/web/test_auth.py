from flask import Blueprint
from sqlalchemy import select

from inventar.models import Jurnal
from inventar.web import rol_necesar


def _login(client, username="admin", parola="parola123"):
    return client.post("/autentificare", data={"username": username, "parola": parola})


def test_pagina_principala_cere_autentificare(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/autentificare" in r.headers["Location"]


def test_login_logout(client, session, creeaza):
    creeaza()
    r = _login(client)
    assert r.status_code == 302
    assert "Bun venit" in client.get("/").get_data(as_text=True)

    r = client.post("/deconectare", follow_redirects=True)
    assert "V-ați deconectat." in r.get_data(as_text=True)
    assert client.get("/").status_code == 302
    actiuni = list(session.scalars(select(Jurnal.actiune).order_by(Jurnal.id)))
    assert actiuni == ["UTILIZATOR_CREAT", "AUTENTIFICARE", "DECONECTARE"]


def test_login_gresit(client, creeaza):
    creeaza()
    r = _login(client, parola="gresita")
    assert r.status_code == 200
    assert "Utilizator sau parolă greșită." in r.get_data(as_text=True)


def test_redirectionare_externa_ignorata(client, creeaza):
    creeaza()
    r = client.post("/autentificare?next=//evil.example", data={"username": "admin", "parola": "parola123"})
    assert r.headers["Location"] == "/"


def test_decorator_rol(app, client, creeaza):
    bp = Blueprint("proba", __name__)

    @bp.route("/doar-admin")
    @rol_necesar("ADMIN")
    def doar_admin():
        return "ok"

    app.register_blueprint(bp)
    creeaza("cons", rol="CONSULTARE")
    creeaza("admin")

    _login(client, "cons")
    assert client.get("/doar-admin").status_code == 403
    client.post("/deconectare")
    _login(client, "admin")
    assert client.get("/doar-admin").status_code == 200
