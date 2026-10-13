import io

from PIL import Image
from sqlalchemy import select

from inventar.models import Activitate, Comisie, Grup, Locatie, Persoana, Setare


def _login(client, username, parola="parola123"):
    client.post("/autentificare", data={"username": username, "parola": parola})


def test_flux_complet_operator(client, session, creeaza):
    creeaza("op", rol="OPERATOR")
    _login(client, "op")

    assert client.post("/nomenclatoare/locatii/nou", data={"cod": "BT", "denumire": "Botoşani"}).status_code == 302
    assert client.post("/nomenclatoare/activitati/nou", data={"cod": "1Int", "denumire": "Botosani (1Int)"}).status_code == 302
    loc = session.scalar(select(Locatie))
    act = session.scalar(select(Activitate))
    assert "Botoşani" in client.get("/nomenclatoare/locatii").get_data(as_text=True)

    r = client.post("/persoane/nou", data={
        "nume": "HRITCU MARCELA", "marca": "", "email": "", "titular_id": 0,
        "locatie_id": loc.id, "activitate_id": act.id, "valabil_de_la": "2025-01-01",
    })
    assert r.status_code == 302, r.get_data(as_text=True)
    p = session.scalar(select(Persoana))
    fisa = client.get(f"/persoane/{p.id}").get_data(as_text=True)
    assert "01.01.2025" in fisa and "Botoşani" in fisa

    # Căutarea ignoră diacriticele și majusculele; htmx primește doar tabelul.
    r = client.get("/persoane?q=hritcu", headers={"HX-Request": "true"})
    corp = r.get_data(as_text=True)
    assert "HRITCU MARCELA" in corp and "<nav" not in corp

    r = client.post("/comisii/nou", data={
        "locatie_id": loc.id, "valabil_de_la": "2025-01-01", "presedinte": "POPESCU ANA", "membri": "ION\nVASILE",
    })
    assert r.status_code == 302
    assert [m.nume for m in session.scalar(select(Comisie)).membri] == ["POPESCU ANA", "ION", "VASILE"]

    r = client.post("/grupuri/nou", data={"denumire": "Grup 1", "persoane": [p.id]})
    assert r.status_code == 302
    assert session.scalar(select(Grup)).persoane[0].id == p.id


def test_eroare_de_validare_afisata(client, creeaza):
    creeaza("op", rol="OPERATOR")
    _login(client, "op")
    client.post("/nomenclatoare/locatii/nou", data={"cod": "BT", "denumire": "Botoşani"})
    r = client.post("/nomenclatoare/locatii/nou", data={"cod": "bt", "denumire": "Alt"})
    assert r.status_code == 200
    assert "există deja" in r.get_data(as_text=True)


def test_consultarea_doar_citeste(client, creeaza):
    creeaza("cons", rol="CONSULTARE")
    _login(client, "cons")
    for url in ["/persoane", "/nomenclatoare/locatii", "/nomenclatoare/activitati", "/comisii", "/grupuri"]:
        assert client.get(url).status_code == 200, url
    assert client.post("/nomenclatoare/locatii/nou", data={"cod": "X", "denumire": "X"}).status_code == 403
    assert client.get("/persoane/nou").status_code == 403
    assert client.get("/admin/setari").status_code == 403


def test_tip_nomenclator_necunoscut(client, creeaza):
    creeaza("op", rol="OPERATOR")
    _login(client, "op")
    assert client.get("/nomenclatoare/altceva").status_code == 404


def test_setari_si_sigla(client, session, creeaza, app):
    creeaza("admin")
    _login(client, "admin")
    r = client.post("/admin/setari", data={
        "unitate_superioara": "D.G.R.F.P. IASI", "unitate": "A.J.F.P. BOTOSANI",
        "antet_declaratii_1": "Agenţia Naţională de Administrare Fiscală",
        "antet_declaratii_2": "DGRFP IAŞI - A.J.F.P. Botoşani", "nivel_cont_margine": "2",
    })
    assert r.status_code == 302
    assert session.get(Setare, "unitate").valoare == "A.J.F.P. BOTOSANI"

    imagine = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(imagine, format="PNG")
    imagine.seek(0)
    r = client.post("/admin/setari", data={"incarca": "1", "sigla": (imagine, "sigla.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    assert client.get("/admin/sigla").status_code == 200


def test_administrare_utilizatori(client, session, creeaza):
    from inventar.models import Utilizator

    creeaza("admin")
    _login(client, "admin")
    r = client.post("/admin/utilizatori/nou", data={
        "username": "ion", "rol": "OPERATOR", "parola": "parola123", "confirmare": "parola123",
    })
    assert r.status_code == 302
    ion = session.scalar(select(Utilizator).where(Utilizator.username == "ion"))
    r = client.post(f"/admin/utilizatori/{ion.id}", data={"u-rol": "CONSULTARE", "u-persoana_id": 0, "u-trimite": "1"})
    assert r.status_code == 302
    assert ion.rol == "CONSULTARE" and not ion.activ  # căsuța „activ” nebifată

    r = client.post("/cont/parola", data={"parola_veche": "parola123", "parola_noua": "noua12345",
                                          "confirmare": "noua12345"})
    assert r.status_code == 302
