import re
from datetime import date

import pytest
from sqlalchemy import select

from inventar.domain.stoc import bunuri_la_persoana
from inventar.models import Document, Incadrare

START = date(2025, 1, 1)


@pytest.fixture
def lume(client, creeaza, persoana, bunuri, initial, nom):
    a, b = persoana("POP ANA"), persoana("ION VASILE")
    b1, b2, b3 = bunuri("101", "102", "103", pret="1000.50")
    initial(START, [(b1, a), (b2, a)])
    creeaza("op", rol="OPERATOR")
    client.post("/autentificare", data={"username": "op", "parola": "parola123"})
    return {"a": a, "b": b, "b1": b1, "b2": b2, "b3": b3, "nom": nom}


def test_transfer_ciorna_validare_anulare(client, session, lume):
    a, b = lume["a"], lume["b"]
    r = client.post("/documente/nou/TRANSFER", data={
        "data": "2025-03-01", "numar": "5", "persoana_de_la_id": a.id, "persoana_la_id": b.id,
        "bunuri": [lume["b1"].id], "salveaza": "1",
    })
    assert r.status_code == 302
    doc = session.scalar(select(Document).where(Document.tip == "TRANSFER"))
    assert doc.stare == "CIORNA"
    pagina = client.get(f"/documente/{doc.id}").get_data(as_text=True)
    assert "ciornă" in pagina and "1.000,50" in pagina

    client.post(f"/documente/{doc.id}/validare")
    assert doc.stare == "VALIDAT"
    assert [x.nr_inventar for x in bunuri_la_persoana(session, b.id, date(2025, 3, 1))] == ["101"]

    r = client.post(f"/documente/{doc.id}/anulare", data={"motiv": ""}, follow_redirects=True)
    assert "Motivul anulării este obligatoriu" in r.get_data(as_text=True)
    client.post(f"/documente/{doc.id}/anulare", data={"motiv": "greșit"})
    assert doc.stare == "ANULAT"


def test_validare_esuata_lasa_ciorna(client, session, lume):
    r = client.post("/documente/nou/TRANSFER", data={
        "data": "2025-03-01", "numar": "6", "persoana_de_la_id": lume["b"].id, "persoana_la_id": lume["a"].id,
        "bunuri": [lume["b1"].id], "valideaza": "1",
    }, follow_redirects=True)
    assert "nu se află la" in r.get_data(as_text=True)
    assert session.scalar(select(Document.stare).where(Document.tip == "TRANSFER")) == "CIORNA"


def test_lista_bunuri_disponibile_htmx(client, lume):
    r = client.get(f"/documente/bunuri-disponibile?tip=TRANSFER&data=2025-03-01&persoana_de_la_id={lume['a'].id}",
                   headers={"HX-Request": "true"})
    corp = r.get_data(as_text=True)
    assert "101" in corp and "102" in corp and "103" not in corp
    r = client.get("/documente/bunuri-disponibile?tip=INTRARE&data=2025-03-01", headers={"HX-Request": "true"})
    assert "103" in r.get_data(as_text=True)


def test_transfer_in_masa_preselecteaza_toate(client, lume):
    pagina = client.get(f"/documente/nou/TRANSFER?de_la={lume['a'].id}&toate=1").get_data(as_text=True)
    assert len(re.findall(r'name="bunuri"[^>]*\schecked>', pagina)) == 2


def test_repartizare_propune_data_documentului_de_intrare(client, session, lume):
    lume["b3"].data_doc_intrare = date(2025, 4, 15)
    session.commit()
    pagina = client.get(f"/documente/nou/INTRARE?bun={lume['b3'].id}").get_data(as_text=True)
    assert 'value="2025-04-15"' in pagina


def test_situatia_si_fisa_bunului(client, lume):
    pagina = client.get("/bunuri?data=2025-03-01").get_data(as_text=True)
    assert "101" in pagina and "POP ANA" in pagina and "2 bunuri" in pagina and "2.001,00" in pagina
    pagina = client.get("/bunuri?stare=nerepartizate").get_data(as_text=True)
    assert "103" in pagina and "101" not in pagina
    pagina = client.get(f"/bunuri/{lume['b1'].id}").get_data(as_text=True)
    assert "POP ANA" in pagina and "Inițial" in pagina
    assert "Repartizează" in client.get(f"/bunuri/{lume['b3'].id}").get_data(as_text=True)


def test_asistent_incadrare(client, session, lume, persoana):
    nom = lume["nom"]
    coleg = persoana("COLEG")
    url = f"/persoane/{lume['a'].id}/incadrare"
    pagina = client.get(url).get_data(as_text=True)
    assert "se predă lui COLEG" in pagina and "101" in pagina

    r = client.post(url, data={
        "locatie_id": nom["dorohoi"].id, "activitate_id": nom["2c"].id, "valabil_de_la": "2025-06-01",
        "motiv": "mutare", "actiune": "executa", f"predare_{lume['b2'].id}": coleg.id,
    })
    assert r.status_code == 302
    assert session.scalar(select(Incadrare).where(Incadrare.document_id.is_not(None))).locatie_id == nom["dorohoi"].id
    assert [x.nr_inventar for x in bunuri_la_persoana(session, coleg.id, date(2025, 6, 1))] == ["102"]
    fisa = client.get(f"/persoane/{lume['a'].id}").get_data(as_text=True)
    assert "document nr." in fisa and "Transfer în masă" in fisa


def test_consultarea_nu_creeaza_documente(client, lume, creeaza):
    client.post("/deconectare")
    creeaza("cons", rol="CONSULTARE")
    client.post("/autentificare", data={"username": "cons", "parola": "parola123"})
    assert client.get("/documente").status_code == 200
    assert client.get("/bunuri").status_code == 200
    assert client.get("/documente/nou/TRANSFER").status_code == 403
    assert client.get(f"/persoane/{lume['a'].id}/incadrare").status_code == 403


def test_tip_document_nepermis(client, lume):
    assert client.get("/documente/nou/INITIAL").status_code == 404
